"""Independent security and failure-path checks for household cloud integration."""
import json
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from app import create_app
from cloud_providers import ProviderError


@pytest.fixture
def setup(tmp_path):
    state = {"subject": "fixed-subject", "exchanges": 0, "snapshot": []}

    class FakeProvider:
        def identity(self):
            return {"subject": state["subject"], "name": "Owner", "email": "private@example.com"}

        def list_sources(self):
            return [{"id": "todo-list", "kind": "tasks", "name": "Shared list", "writable": True}]

        def snapshot(self, source, start, end):
            if isinstance(state["snapshot"], Exception):
                raise state["snapshot"]
            return state["snapshot"]

    def tokens(provider, params):
        state["exchanges"] += 1
        return {"access_token": "sensitive-access-token", "refresh_token": "sensitive-refresh-token",
                "expires_in": 3600, "scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks"}

    app = create_app({"TESTING": True, "SECRET_KEY": "review-only-secret", "DATA_DIR": str(tmp_path),
                      "MEMBER1_PASSWORD": "review-password-one", "MEMBER2_PASSWORD": "review-password-two",
                      "SESSION_COOKIE_SECURE": False, "PUBLIC_ORIGIN": "http://localhost",
                      "GOOGLE_CLIENT_ID": "review-client", "GOOGLE_CLIENT_SECRET": "sensitive-client-secret",
                      "CLOUD_PROVIDER_FACTORY": lambda *args, **kwargs: FakeProvider(), "OAUTH_TRANSPORT": tokens})
    return app, app.extensions["cloud_accounts"], state


def login(app, member=1):
    client = app.test_client()
    assert client.post("/api/login", json={"username": f"member{member}", "password": "review-password-" + ("one" if member == 1 else "two")}).status_code == 200
    return client, {"X-CSRF-Token": client.get("/api/me").json["csrf"]}


def start_bind(client, headers):
    response = client.post("/api/accounts/bind", json={"provider": "google"}, headers=headers)
    assert response.status_code == 200
    return parse_qs(urlsplit(response.json["url"]).query)["state"][0]


def finish_bind(client, state):
    return client.get("/auth/google/callback?" + urlencode({"state": state, "code": "private-authorization-code"}))


def seed_source(engine, owner="member1", aid="account-one", sid="source-one"):
    tokens = engine.encrypt({"access_token": "sensitive-access-token", "refresh_token": "sensitive-refresh-token", "expires_at": time.time()+3600})
    with engine.db() as con:
        con.execute("INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,'google','review-client',?,'Owner','private@example.com',?)", (aid, owner, aid, tokens))
        con.execute("INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,'todo-list','tasks','Shared list','shared')", (sid, aid))
        return dict(con.execute("SELECT * FROM cloud_sources WHERE id=?", (sid,)).fetchone())


def record(rid="remote-one", title="Shared task"):
    return {"id": rid, "version": "v1", "data": {"title": title, "done": False, "owner": "shared", "note": "", "due": "", "tripId": ""}}


def test_callback_browser_binding_and_replay_do_not_exchange_tokens(setup):
    app, engine, state = setup
    owner, headers = login(app)
    oauth_state = start_bind(owner, headers)
    attacker = app.test_client()
    assert "invalid_state" in finish_bind(attacker, oauth_state).location
    assert state["exchanges"] == 0
    assert "auth=connected" in finish_bind(owner, oauth_state).location
    assert state["exchanges"] == 1
    assert "invalid_state" in finish_bind(owner, oauth_state).location
    assert state["exchanges"] == 1
    with engine.db() as con:
        stored = con.execute("SELECT * FROM cloud_accounts").fetchone()
    assert "sensitive-access-token" not in stored["tokens"]
    assert "sensitive-refresh-token" not in stored["tokens"]
    response = owner.get("/api/state").get_data(as_text=True)
    assert "private@example.com" not in response
    assert "sensitive-" not in response


def test_bind_session_member_swap_invalidates_flow(setup):
    app, engine, state = setup
    owner, headers = login(app)
    oauth_state = start_bind(owner, headers)
    # Preserve the browser nonce while switching household identities.
    with owner.session_transaction() as session:
        session["uid"] = "member2"
    assert "bind_session_changed" in finish_bind(owner, oauth_state).location
    assert state["exchanges"] == 0
    with engine.db() as con:
        assert con.execute("SELECT COUNT(*) FROM cloud_accounts").fetchone()[0] == 0


def test_bind_same_provider_subject_cannot_move_between_household_members(setup):
    app, engine, state = setup
    first, first_headers = login(app, 1)
    second, second_headers = login(app, 2)
    assert "auth=connected" in finish_bind(first, start_bind(first, first_headers)).location
    assert "already_bound" in finish_bind(second, start_bind(second, second_headers)).location
    assert second.get("/api/accounts").json["accounts"] == []
    assert first.get("/api/accounts").json["accounts"][0]["email"] == "private@example.com"


def test_partner_cannot_discover_modify_disconnect_or_force_owner_account(setup):
    app, engine, state = setup
    source = seed_source(engine)
    partner, headers = login(app, 2)
    assert partner.get("/api/accounts/account-one/sources").status_code == 404
    assert partner.post("/api/accounts/account-one/sources", json={"sources": []}, headers=headers).status_code == 404
    assert partner.post("/api/accounts/account-one/sync", json={}, headers=headers).status_code == 404
    assert partner.delete("/api/accounts/account-one", json={}, headers=headers).status_code == 404
    assert partner.get("/api/accounts").json["accounts"] == []
    assert engine.account("account-one")["owner"] == "member1"
    with engine.db() as con:
        assert con.execute("SELECT COUNT(*) FROM cloud_sources WHERE id=?", (source["id"],)).fetchone()[0] == 1


def test_provider_409_is_not_mistaken_for_account_lock_contention(setup):
    app, engine, state = setup
    source = seed_source(engine)
    engine.publish(source, engine.account("account-one"), [record()])
    with engine.db() as con:
        con.execute("UPDATE cloud_sources SET next_attempt=0 WHERE id=?", (source["id"],))
    state["snapshot"] = ProviderError("Remote selected list no longer exists", 409)
    before = time.time()
    engine.tick()
    with engine.db() as con:
        failed = con.execute("SELECT * FROM cloud_sources WHERE id=?", (source["id"],)).fetchone()
        assert failed["error"]
        assert failed["next_attempt"] > before
        assert failed["failures"] == 1
        assert con.execute("SELECT COUNT(*) FROM cloud_items").fetchone()[0] == 1


def test_snapshot_publication_deletes_only_its_cloud_items(setup):
    app, engine, state = setup
    source = seed_source(engine)
    other_source = seed_source(engine, "member2", "account-two", "source-two")
    account = engine.account("account-one")
    engine.publish(source, account, [record()])
    engine.publish(other_source, engine.account("account-two"), [record("other-remote", "Partner cloud task")])
    owner, headers = login(app)
    assert owner.post("/api/items/tasks", json={"title": "Local task", "sourceId": ""}, headers=headers).status_code == 201
    engine.publish(source, account, [])
    tasks = owner.get("/api/state").json["tasks"]
    assert {item["title"] for item in tasks} == {"Local task", "Partner cloud task"}
    engine.disconnect("account-one", "member1")
    assert {item["title"] for item in owner.get("/api/state").json["tasks"]} == {"Local task", "Partner cloud task"}


def test_publish_rolls_back_entire_snapshot_on_malformed_late_record(setup):
    app, engine, state = setup
    source = seed_source(engine)
    account = engine.account("account-one")
    engine.publish(source, account, [record()])
    with engine.db() as con:
        before = [tuple(row) for row in con.execute("SELECT * FROM entities ORDER BY id")]
    with pytest.raises(KeyError):
        engine.publish(source, account, [record(title="Should roll back"), {"id": "late-bad", "version": "v1"}])
    with engine.db() as con:
        assert [tuple(row) for row in con.execute("SELECT * FROM entities ORDER BY id")] == before
