"""Real local Flask/SQLite routines, synthetic data, hard network denial."""
import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier

import pytest

import household_routines as routines
from test_app import app, member

PREFIX = routines.PREFIX


@pytest.fixture(autouse=True)
def isolated_clock_and_network(monkeypatch):
    monkeypatch.setattr(routines, "today", lambda: date(2026, 9, 15))
    def denied(*args, **kwargs):
        raise AssertionError("Routine tests must not access a network")
    monkeypatch.setattr(socket.socket, "connect", denied)


def database(app):
    con = sqlite3.connect(Path(app.config["DATA_DIR"]) / "household.sqlite3", timeout=15)
    con.row_factory = sqlite3.Row
    return con


def make_payload(kind="tasks", frequency="daily", interval=1, anchor="2026-09-15", **template):
    data = {"title": "SYNTHETIC_ROUTINE", "owner": "shared", "note": ""}
    if kind == "shopping":
        data.update(quantity="2 件", budget=12000)
    data.update(template)
    return {"operation": "create", "kind": kind, "template": data,
            "schedule": {"frequency": frequency, "interval": interval, "anchor": anchor}}


def preview(client, headers, payload):
    return client.post(PREFIX + "/preview", json=payload, headers=headers)


def confirm(client, headers, p):
    assert p.status_code == 200, p.json
    return client.post(PREFIX + "/confirm", json={"previewToken": p.json["previewToken"]}, headers=headers)


def create(client, headers, **kwargs):
    response = confirm(client, headers, preview(client, headers, make_payload(**kwargs)))
    assert response.status_code == 200, response.json
    return response.json


def context(client, **args):
    response = client.get(PREFIX + "/context", query_string=args)
    assert response.status_code == 200, response.json
    return response.json


def plan(client, plan_id):
    return next(p for p in context(client, planId=plan_id)["plans"] if p["id"] == plan_id)


def operation(client, headers, rule, action, **extra):
    return preview(client, headers, {"operation": action, "planId": rule["id"], "revision": rule["revision"], **extra})


def entity(client, rule):
    return next(row for row in client.get("/api/state").json[rule["kind"]]
                if row["id"] == rule["current"]["entityId"])


def edit(client, headers, rule, **fields):
    current = entity(client, rule)
    result = client.patch(f"/api/items/{rule['kind']}/{current['id']}",
                          json={"revision": current["revision"], **fields}, headers=headers)
    assert result.status_code == 200, result.json
    return entity(client, rule)


def snapshot(app, tables):
    with database(app) as con:
        return {table: [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in tables}


def finance_snapshot(app):
    tables = ["private_finance", "finance_baselines", "hub_transactions", "hub_reconciliations",
              "hub_investments", "hub_budgets", "hub_imports", "cloud_accounts", "cloud_sources",
              "calendar_publications", "task_publications"]
    with database(app) as con:
        present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = snapshot(app, [t for t in tables if t in present])
        result["public_finance"] = tuple(con.execute("SELECT * FROM settings WHERE id='finance'").fetchone())
    return result


@pytest.mark.parametrize("frequency,interval,anchor,boundary,expected", [
    ("daily", 1, "2026-09-01", "2026-09-15", ["2026-09-15", "2026-09-16", "2026-09-17"]),
    ("daily", 365, "2000-01-01", "2026-09-15", ["2026-12-25", "2027-12-25", "2028-12-24"]),
    ("weekly", 2, "2026-09-02", "2026-09-15", ["2026-09-16", "2026-09-30", "2026-10-14"]),
    ("weekly", 52, "2026-01-01", "2026-01-02", ["2026-12-31", "2027-12-30", "2028-12-28"]),
    ("monthly", 1, "2026-01-31", "2026-02-01", ["2026-02-28", "2026-03-31", "2026-04-30"]),
    ("monthly", 1, "2024-01-31", "2024-02-01", ["2024-02-29", "2024-03-31", "2024-04-30"]),
    ("monthly", 1, "2026-01-30", "2026-02-28", ["2026-02-28", "2026-03-30", "2026-04-30"]),
    ("monthly", 2, "2026-01-31", "2026-02-28", ["2026-03-31", "2026-05-31", "2026-07-31"]),
    ("monthly", 12, "2024-02-29", "2025-01-01", ["2025-02-28", "2026-02-28", "2027-02-28"]),
    ("monthly", 1, "2100-11-30", "2100-12-01", ["2100-12-30"]),
])
def test_anchor_calendar_math(frequency, interval, anchor, boundary, expected):
    schedule = {"frequency": frequency, "interval": interval, "anchor": anchor}
    assert routines.next_dates(schedule, date.fromisoformat(boundary)) == expected


@pytest.mark.parametrize("frequency", ["daily", "weekly", "monthly"])
def test_strict_next_date_never_reuses_boundary_or_exceeds_supported_calendar(frequency):
    schedule = {"frequency": frequency, "interval": 1, "anchor": "2100-12-31"}
    assert routines.next_dates(schedule, date(2100, 12, 31)) == ["2100-12-31"]
    assert routines.next_dates(schedule, date(2100, 12, 31), strict=True) == []


@pytest.mark.parametrize("kind", ["tasks", "shopping"])
def test_create_is_readonly_until_confirm_and_replay_is_receipt(app, kind):
    client, headers = member(app)
    tables = ["household_routines", "routine_occurrences", "routine_receipts", "entities", "audit"]
    before = snapshot(app, tables)
    financial = finance_snapshot(app)
    payload = make_payload(kind, frequency="monthly", anchor="2026-01-31")
    p = preview(client, headers, payload)
    assert p.status_code == 200, p.json
    assert p.json["nextDates"] == ["2026-09-30", "2026-10-31", "2026-11-30"]
    assert p.json["willGenerate"]["scheduledOn"] == p.json["nextDates"][0]
    assert p.json["willGenerate"]["index"] == 1
    assert context(client)["plans"] == []
    assert snapshot(app, tables) == before
    result = confirm(client, headers, p)
    assert result.status_code == 200 and not result.json["replayed"]
    rule = result.json["plan"]
    assert rule["current"]["scheduledOn"] == "2026-09-30"
    assert rule["nextDates"] == ["2026-10-31", "2026-11-30", "2026-12-31"]
    created = entity(client, rule)
    assert created["done"] is False
    if kind == "shopping":
        assert created["actual"] is None and created["photoIds"] == [] and created["budget"] == 12000
    else:
        assert created["due"] == "2026-09-30" and created["tripId"] == ""
    after = snapshot(app, tables)
    again = confirm(client, headers, p)
    assert again.status_code == 200 and again.json["replayed"]
    assert snapshot(app, tables) == after
    assert finance_snapshot(app) == financial


def test_clock_uses_shanghai_date(monkeypatch):
    from datetime import datetime, timezone
    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc).astimezone(zone)
    monkeypatch.undo()
    monkeypatch.setattr(routines, "datetime", Clock)
    assert routines.today() == date(2026, 1, 2)


def test_completion_advances_only_one_original_period_and_preserves_manual_changes(app, monkeypatch):
    client, headers = member(app)
    created = create(client, headers, frequency="weekly", interval=2, anchor="2026-09-02")
    rule = created["plan"]
    old = edit(client, headers, rule, title="INDEPENDENT_EDIT", due="2099-01-01", note="KEEP", done=True)
    monkeypatch.setattr(routines, "today", lambda: date(2026, 11, 20))
    financial = finance_snapshot(app)
    result = app.extensions["household_routines"].tick()
    assert result["generated"] == 1
    fresh = plan(client, rule["id"])
    assert fresh["current"]["scheduledOn"] == "2026-11-25"
    assert fresh["current"]["index"] == 2
    assert fresh["current"]["entity"]["title"] == "SYNTHETIC_ROUTINE"
    assert entity(client, rule) == old
    assert fresh["history"][1]["state"] == "completed"
    state = snapshot(app, ["household_routines", "routine_occurrences", "entities", "audit", "settings"])
    assert app.extensions["household_routines"].tick()["generated"] == 0
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "audit", "settings"]) == state
    edit(client, headers, rule, done=False)
    assert app.extensions["household_routines"].tick()["generated"] == 0
    assert plan(client, rule["id"])["history"][1]["state"] == "completed"
    assert finance_snapshot(app) == financial


def test_monthly_complete_clamps_then_returns_to_anchor_day(app, monkeypatch):
    client, headers = member(app)
    monkeypatch.setattr(routines, "today", lambda: date(2026, 1, 31))
    rule = create(client, headers, frequency="monthly", anchor="2026-01-31")["plan"]
    for day, expected in [(date(2026, 1, 31), "2026-02-28"), (date(2026, 2, 28), "2026-03-31")]:
        monkeypatch.setattr(routines, "today", lambda day=day: day)
        edit(client, headers, rule, done=True)
        assert app.extensions["household_routines"].tick()["generated"] == 1
        rule = plan(client, rule["id"])
        assert rule["current"]["scheduledOn"] == expected


def test_rule_update_pause_resume_archive_preserve_current_and_history(app):
    client, headers = member(app)
    rule = create(client, headers, kind="shopping")["plan"]
    old = edit(client, headers, rule, title="USER_EDIT", actual=4500, budget=9900, done=True)
    paused = confirm(client, headers, operation(client, headers, rule, "pause")).json["plan"]
    idle = snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"])
    assert app.extensions["household_routines"].tick()["generated"] == 0
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"]) == idle
    update = operation(client, headers, paused, "update",
                       template={**paused["template"], "title": "NEW_TEMPLATE", "budget": None},
                       schedule={"frequency": "monthly", "interval": 1, "anchor": "2026-09-30"})
    updated = confirm(client, headers, update).json["plan"]
    assert entity(client, rule) == old and updated["state"] == "paused"
    resumed = confirm(client, headers, operation(client, headers, updated, "resume"))
    assert resumed.status_code == 200 and resumed.json["generated"]["scheduledOn"] == "2026-09-30"
    fresh = resumed.json["plan"]
    assert fresh["current"]["entity"]["actual"] is None
    assert fresh["current"]["entity"]["budget"] is None
    assert fresh["current"]["entity"]["title"] == "NEW_TEMPLATE"
    archived = confirm(client, headers, operation(client, headers, fresh, "archive")).json["plan"]
    assert archived["status"] == "archived"
    assert context(client)["plans"] == []
    assert plan(client, archived["id"])["id"] == archived["id"]
    assert len(context(client, includeArchived="true")["plans"]) == 1
    for action in ["resume", "update", "pause", "skip", "archive"]:
        extra = {"template": archived["template"], "schedule": archived["schedule"]} if action == "update" else {}
        assert operation(client, headers, archived, action, **extra).status_code == 409


@pytest.mark.parametrize("kind", ["tasks", "shopping"])
def test_deleted_current_is_missing_and_explicit_skip_never_resurrects(app, kind):
    client, headers = member(app)
    result = create(client, headers, kind=kind)
    rule = result["plan"]
    current = entity(client, rule)
    response = client.delete(f"/api/items/{kind}/{current['id']}", json={"revision": current["revision"]}, headers=headers)
    assert response.status_code == 200
    before = snapshot(app, ["household_routines", "routine_occurrences", "entities", "audit", "settings"])
    assert app.extensions["household_routines"].tick()["missing"] == 1
    assert plan(client, rule["id"])["status"] == "missing"
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "audit", "settings"]) == before
    p = operation(client, headers, rule, "skip")
    assert any("保留现有事项" in warning for warning in p.json["warnings"])
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "audit", "settings"]) == before
    confirmed = confirm(client, headers, p)
    assert confirmed.status_code == 200
    fresh = confirmed.json["plan"]
    assert fresh["current"]["entityId"] != current["id"]
    assert fresh["history"][1]["state"] == "skipped" and fresh["history"][1]["entity"] is None
    again = confirm(client, headers, p)
    assert again.json["replayed"] and again.json["generated"]["id"] == fresh["current"]["entityId"]
    assert len(client.get("/api/state").json[kind]) == 1


@pytest.mark.parametrize("done", [False, True])
def test_skip_retains_exact_old_item_and_fixed_skipped_state(app, done):
    client, headers = member(app)
    rule = create(client, headers)["plan"]
    old = edit(client, headers, rule, done=done, title="KEEP_ALL_FIELDS", due="2027-04-01")
    fresh = confirm(client, headers, operation(client, headers, rule, "skip")).json["plan"]
    assert entity(client, rule) == old
    assert fresh["current"]["scheduledOn"] == "2026-09-16"
    edit(client, headers, rule, done=not done)
    assert plan(client, rule["id"])["history"][1]["state"] == "skipped"


@pytest.mark.parametrize("change", ["current", "rule", "date", "capacity"])
def test_preview_compare_and_swap_rejects_changed_dependencies(app, monkeypatch, change):
    client, headers = member(app)
    rule = create(client, headers)["plan"]
    p = operation(client, headers, rule, "skip")
    if change == "current":
        edit(client, headers, rule, note="CHANGED")
    elif change == "rule":
        other, oh = member(app, 2)
        assert confirm(other, oh, operation(other, oh, rule, "pause")).status_code == 200
    elif change == "date":
        monkeypatch.setattr(routines, "today", lambda: date(2026, 9, 16))
    else:
        assert client.post("/api/items/shopping", json={"title": "CAPACITY_CHANGE"}, headers=headers).status_code == 201
    before = snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities"])
    assert confirm(client, headers, p).status_code == 409
    assert snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities"]) == before


def fill_capacity(app, kind):
    with database(app) as con:
        existing = con.execute("SELECT count(*) FROM entities WHERE kind=?", (kind,)).fetchone()[0]
        con.executemany("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)",
                        [(f"capacity-{kind}-{i}", kind, '{"title":"SYNTHETIC_CAPACITY","done":false}', "2026-09-15")
                         for i in range(routines.MAX_ITEMS-existing)])


@pytest.mark.parametrize("kind", ["tasks", "shopping"])
def test_capacity_visible_no_busy_writes_and_recovery_after_explicit_room(app, kind):
    client, headers = member(app)
    rule = create(client, headers, kind=kind)["plan"]
    edit(client, headers, rule, done=True)
    fill_capacity(app, kind)
    state = snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"])
    assert app.extensions["household_routines"].tick()["blocked"] == 1
    assert plan(client, rule["id"])["status"] == "capacity_blocked"
    assert preview(client, headers, make_payload(kind)).status_code == 409
    assert operation(client, headers, rule, "skip").status_code == 409
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"]) == state
    with database(app) as con:
        con.execute("DELETE FROM entities WHERE id=?", (f"capacity-{kind}-0",))
    assert app.extensions["household_routines"].tick()["generated"] == 1
    with database(app) as con:
        assert con.execute("SELECT count(*) FROM entities WHERE kind=?", (kind,)).fetchone()[0] == 2500


def test_supported_calendar_exhaustion_visible_without_writes(app, monkeypatch):
    client, headers = member(app)
    monkeypatch.setattr(routines, "today", lambda: date(2100, 12, 31))
    rule = create(client, headers, anchor="2100-12-31")["plan"]
    edit(client, headers, rule, done=True)
    state = snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"])
    assert plan(client, rule["id"])["status"] == "exhausted"
    assert app.extensions["household_routines"].tick()["blocked"] == 1
    assert operation(client, headers, rule, "skip").status_code == 409
    assert snapshot(app, ["household_routines", "routine_occurrences", "entities", "settings", "audit"]) == state


@pytest.mark.parametrize("path,value", [
    ("schedule.interval", True), ("schedule.interval", "1"), ("schedule.interval", 1.0),
    ("schedule.interval", 0), ("schedule.interval", 366), ("schedule.frequency", []),
    ("schedule.frequency", "yearly"), ("schedule.anchor", "2026-02-30"),
    ("schedule.anchor", "1999-12-31"), ("schedule.anchor", "2101-01-01"),
    ("schedule.anchor", "20260915"), ("schedule.timeZone", "UTC"), ("schedule.monthEnd", "skip"),
    ("template.title", ""), ("template.title", "x"*101), ("template.note", "x"*501),
    ("template.owner", "other-household-member"), ("template.source", "PRIVATE_ACCOUNT"),
    ("template.tripId", "OTHER_TRIP"), ("template.done", True), ("template.photoIds", []),
    ("template.password", "MUST_NOT_ENTER_RULE"), ("kind", "events"), ("unexpected", "x"),
])
def test_bad_or_private_rule_fields_rejected_without_rows(app, path, value):
    client, headers = member(app)
    payload = make_payload()
    if "." in path:
        outer, key = path.split(".")
        payload[outer][key] = value
    else:
        payload[path] = value
    assert preview(client, headers, payload).status_code == 400
    assert snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts"]) == {
        "household_routines": [], "routine_occurrences": [], "routine_receipts": []}


@pytest.mark.parametrize("frequency,interval", [("weekly", 53), ("monthly", 13)])
def test_frequency_specific_interval_limits(app, frequency, interval):
    client, headers = member(app)
    assert preview(client, headers, make_payload(frequency=frequency, interval=interval)).status_code == 400


@pytest.mark.parametrize("budget", [True, 1.2, "100", -1, 100_000_000_001])
def test_shopping_budget_rejects_non_integer_minor_units(app, budget):
    client, headers = member(app)
    assert preview(client, headers, make_payload("shopping", budget=budget)).status_code == 400


def test_zero_and_unknown_shopping_budget_are_distinct(app):
    client, headers = member(app)
    a = create(client, headers, kind="shopping", budget=0)["plan"]
    b = create(client, headers, kind="shopping", budget=None)["plan"]
    assert a["current"]["entity"]["budget"] == 0
    assert b["current"]["entity"]["budget"] is None


def test_read_and_write_member_household_tv_csrf_and_signature_boundaries(app):
    client, headers = member(app)
    other, oh = member(app, 2)
    p = preview(client, headers, make_payload())
    assert app.test_client().get(PREFIX + "/context").status_code == 401
    assert client.post(PREFIX + "/preview", json=make_payload()).status_code == 403
    assert preview(client, {**headers, "Origin": "https://other.invalid"}, make_payload()).status_code == 403
    assert confirm(other, oh, p).status_code == 403
    result = confirm(client, headers, p).json
    assert plan(other, result["plan"]["id"])["createdBy"] == "member1"
    assert confirm(other, oh, operation(other, oh, result["plan"], "pause")).status_code == 200
    tv = app.test_client()
    pair = tv.post("/api/pair/start", json={}).json
    assert client.post("/api/pair/approve", json={"code": pair["code"], "name": "SYNTHETIC_TV", "focus": "member1"}, headers=headers).status_code == 200
    assert tv.post("/api/pair/poll", json={"secret": pair["secret"]}).json["approved"]
    assert tv.get(PREFIX + "/context").status_code == 403
    assert tv.post(PREFIX + "/preview", json=make_payload(), headers=headers).status_code == 403
    assert len(tv.get("/api/state").json["tasks"]) == 1
    assert "previewToken" not in tv.get("/api/state").get_data(as_text=True)
    assert client.post(PREFIX + "/confirm", json={"previewToken": "invalid"}, headers=headers).status_code == 400
    assert client.post(PREFIX + "/confirm", json={"previewToken": p.json["previewToken"], "owner": "member2"}, headers=headers).status_code == 400


def test_old_session_preview_cannot_confirm_after_relogin(app):
    client, headers = member(app)
    p = preview(client, headers, make_payload())
    assert client.post("/api/logout", json={}, headers=headers).status_code == 200
    assert client.post("/api/login", json={"username": "member1", "password": "testing-password-one"}).status_code == 200
    fresh = {"X-CSRF-Token": client.get("/api/me").json["csrf"]}
    assert confirm(client, fresh, p).status_code == 403
    assert context(client)["plans"] == []


def test_session_revoked_after_before_request_is_rechecked_in_write_transaction(app, monkeypatch):
    client, headers = member(app)
    p = preview(client, headers, make_payload())
    original = app.extensions["member_sessions"].current
    def revoked(con):
        con.execute("UPDATE member_sessions SET revoked_at=1")
        return original(con)
    monkeypatch.setattr(app.extensions["member_sessions"], "current", revoked)
    assert confirm(client, headers, p).status_code == 401
    assert snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts"]) == {
        "household_routines": [], "routine_occurrences": [], "routine_receipts": []}


def test_two_concurrent_confirmations_replay_once(app):
    client, headers = member(app)
    p = preview(client, headers, make_payload())
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"]).value
    barrier = Barrier(2)
    def run():
        c = app.test_client()
        c.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)
        barrier.wait()
        return confirm(c, headers, p)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json["replayed"] for r in results) == [False, True]
    assert len(context(client)["plans"]) == 1
    assert len(client.get("/api/state").json["tasks"]) == 1


def test_two_workers_advance_once_and_keep_history_unique(app):
    client, headers = member(app)
    rule = create(client, headers)["plan"]
    edit(client, headers, rule, done=True)
    barrier = Barrier(2)
    def run():
        barrier.wait()
        return app.extensions["household_routines"].tick()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(r["generated"] for r in results) == 1
    fresh = plan(client, rule["id"])
    assert fresh["current"]["index"] == 2 and len(fresh["history"]) == 2
    with database(app) as con:
        assert con.execute("SELECT count(*) FROM audit WHERE actor='system:routines' AND action='routines.advance'").fetchone()[0] == 1


def test_context_pagination_archived_focus_and_active_capacity(app):
    client, headers = member(app)
    first = create(client, headers)["plan"]
    with database(app) as con:
        source = dict(con.execute("SELECT * FROM household_routines WHERE id=?", (first["id"],)).fetchone())
        columns = list(source)
        con.executemany("INSERT INTO household_routines("+",".join(columns)+") VALUES("+",".join("?" for _ in columns)+")",
            [tuple({**source, "id": f"synthetic-rule-{i:03}", "current_index": 0,
                    "created_at": f"2026-09-{1+i%28:02}"}[key] for key in columns) for i in range(99)])
    first_page = context(client)
    assert len(first_page["plans"]) == 40 and first_page["pageInfo"]["more"]
    assert len(context(client, page=2)["plans"]) == 20
    assert plan(client, first["id"])["id"] == first["id"]
    assert preview(client, headers, make_payload()).status_code == 409
    archived = confirm(client, headers, operation(client, headers, first, "archive"))
    assert archived.status_code == 200
    assert plan(client, first["id"])["state"] == "archived"
    assert create(client, headers)["plan"]["state"] == "active"
    assert len(context(client, includeArchived="true", page=2)["plans"]) == 21


@pytest.mark.parametrize("query", ["page=-1", "page=01", "page=true", "page=1000000000", "includeArchived=1", "owner=member2", "page=0&page=1"])
def test_query_shape_is_strict(app, query):
    client, _ = member(app)
    assert client.get(PREFIX + "/context?" + query).status_code == 400


def test_readonly_brief_prioritizes_issues_and_caps_eight(app):
    client, headers = member(app)
    for number in range(10):
        create(client, headers, title=f"SYNTHETIC_ROUTINE_{number}")
    rule = context(client)["plans"][0]
    old = entity(client, rule)
    client.delete(f"/api/items/tasks/{old['id']}", json={"revision": old["revision"]}, headers=headers)
    before = snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities", "settings", "audit"])
    with database(app) as con:
        summary = app.extensions["household_routines"].brief(con)
    assert summary["limit"] == 8 and len(summary["items"]) == 8
    assert summary["dueCount"] == 10 and summary["issueCount"] == 1
    assert summary["items"][0]["id"] == rule["id"] and summary["items"][0]["status"] == "missing"
    assert all(set(row) == {"id", "title", "kind", "owner", "scheduledOn", "status"} for row in summary["items"])
    assert snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities", "settings", "audit"]) == before


def test_export_is_explicit_shared_business_whitelist_not_receipt_context(app):
    client, headers = member(app)
    created = create(client, headers)
    with database(app) as con:
        row = dict(con.execute("SELECT * FROM routine_receipts").fetchone())
        result = json.loads(row["result"])
        result.update(token="DO_NOT_EXPORT_SYNTHETIC_TOKEN", context="DO_NOT_EXPORT_CONTEXT")
        con.execute("UPDATE routine_receipts SET result=?", (json.dumps(result),))
    with database(app) as con:
        output = routines.export_shared_routines(con)
    raw = json.dumps(output)
    assert created["plan"]["id"] in raw
    assert output["plans"][0]["createdBy"] == "member1"
    assert set(output["receipts"][0]) == {"id", "operation", "planId", "createdAt", "generatedId"}
    assert all(forbidden not in raw for forbidden in ["nonce_digest", "previewToken", "DO_NOT_EXPORT", row["nonce_digest"]])


def test_empty_tick_and_get_never_generate_or_increment_meta(app):
    client, _ = member(app)
    before = snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities", "settings", "audit"])
    assert context(client)["plans"] == []
    assert app.extensions["household_routines"].tick() == {"examined": 0, "generated": 0, "missing": 0, "blocked": 0}
    assert snapshot(app, ["household_routines", "routine_occurrences", "routine_receipts", "entities", "settings", "audit"]) == before


def test_idle_missing_and_capacity_blocked_ticks_do_not_take_write_locks(app, monkeypatch):
    client, headers = member(app)
    pending = create(client, headers)["plan"]
    missing = create(client, headers)["plan"]
    gone = entity(client, missing)
    client.delete(f"/api/items/tasks/{gone['id']}", json={"revision": gone["revision"]}, headers=headers)
    engine, statements = app.extensions["household_routines"], []
    original_db = engine.db
    def traced_db():
        con = original_db()
        con.set_trace_callback(statements.append)
        return con
    monkeypatch.setattr(engine, "db", traced_db)
    result = engine.tick()
    assert result["examined"] == 2 and result["missing"] == 1
    assert not any("BEGIN IMMEDIATE" in sql for sql in statements)
    edit(client, headers, pending, done=True)
    fill_capacity(app, "tasks")
    statements.clear()
    assert engine.tick()["blocked"] == 1
    assert not any("BEGIN IMMEDIATE" in sql for sql in statements)
    with database(app) as con:
        con.execute("DELETE FROM entities WHERE id='capacity-tasks-0'")
    statements.clear()
    assert engine.tick()["generated"] == 1
    assert sum("BEGIN IMMEDIATE" in sql for sql in statements) == 1


def test_tick_rechecks_pause_after_readonly_candidate_hint(app, monkeypatch):
    client, headers = member(app)
    rule = create(client, headers)["plan"]
    edit(client, headers, rule, done=True)
    engine = app.extensions["household_routines"]
    original_dates = engine.dates
    paused = False
    def change_after_hint(*args):
        nonlocal paused
        dates = original_dates(*args)
        if not paused:
            paused = True
            with database(app) as con:
                con.execute("UPDATE household_routines SET state='paused',revision=revision+1 WHERE id=?", (rule["id"],))
        return dates
    monkeypatch.setattr(engine, "dates", change_after_hint)
    assert engine.tick()["generated"] == 0
    assert plan(client, rule["id"])["state"] == "paused"
    assert len(client.get("/api/state").json["tasks"]) == 1


def test_expired_preview_rejected_without_mutation(app):
    from itsdangerous.timed import TimestampSigner
    client, headers = member(app)
    p = preview(client, headers, make_payload())
    assert p.status_code == 200
    # Backdate only this valid preview signature, never the login cookie clock.
    class ExpiredSigner(TimestampSigner):
        def get_timestamp(self):
            return super().get_timestamp() - 601
    normal = routines.URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="household-routines-preview-v1")
    expired = routines.URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="household-routines-preview-v1", signer=ExpiredSigner)
    token = expired.dumps(normal.loads(p.json["previewToken"]))
    assert client.post(PREFIX + "/confirm", json={"previewToken": token}, headers=headers).status_code == 400
    assert context(client)["plans"] == []
