"""Same-target reconnect and old-lock races with temporary DB/fake cloud only."""
from contextlib import contextmanager
import json

import pytest

from cloud_providers import ProviderError
from test_calendar_publish import env, queue, publication
from test_journey_publication_review import hold_timing, review, confirm_review


def row(env, rid):
    with env[0].extensions['cloud_accounts'].db() as con:
        return dict(con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone())


def reselect(env, replace_account=False, subject=None, calendar=None, owner=None):
    """Synthetic reconnect equivalent to disconnect + successful owned rebind."""
    engine = env[0].extensions['cloud_accounts']
    with engine.db() as con:
        account = dict(con.execute("SELECT * FROM cloud_accounts WHERE id='account-1'").fetchone())
        source = dict(con.execute("SELECT * FROM cloud_sources WHERE id='source-1'").fetchone())
        engine.remove_source(con, source['id'])
        if replace_account:
            con.execute('DELETE FROM cloud_accounts WHERE id=?', (account['id'],))
            account['id'] = 'account-new'
            account['subject'] = subject or account['subject']
            account['owner'] = owner or account['owner']
            columns = ','.join(account)
            con.execute(f"INSERT INTO cloud_accounts({columns}) VALUES({','.join('?' for _ in account)})", list(account.values()))
        source.update(id='source-new', account_id=account['id'], remote_id=calendar or source['remote_id'], owner=owner or source['owner'])
        columns = ','.join(source)
        con.execute(f"INSERT INTO cloud_sources({columns}) VALUES({','.join('?' for _ in source)})", list(source.values()))
    return account, source


def confirm_target(env, client=None, headers=None):
    client, headers = client or env[1], headers or env[2]
    payload = {'journeyId': 'journey-1', 'sourceId': 'source-new'}
    preview = client.post('/api/calendar-publish/preview', json=payload, headers=headers)
    assert preview.status_code == 200, preview.json
    return client.post('/api/calendar-publish/confirm', json={**payload, 'previewToken': preview.json['previewToken']}, headers=headers)


@pytest.mark.parametrize('status', ['needs_review', 'paused', 'conflict', 'retry'])
@pytest.mark.parametrize('replace_account', [False, True])
def test_same_target_reconnect_preserves_queue_and_remote_evidence(env, status, replace_account):
    app, _, _, remote, _ = env
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE calendar_publications SET status=?,review_required=?,pending_data=?,pending_hash='unacknowledged-hash',pending_revision=8,attempts=3 WHERE id=?",
                    (status, int(status == 'needs_review'), '{"title":"synthetic unacknowledged write"}', rid))
    before = row(env, rid)
    reselect(env, replace_account)
    result = confirm_target(env)
    assert result.status_code == 200, result.json
    assert result.json['publicationIds'] == [rid]
    after = row(env, rid)
    assert after['source_id'] == 'source-new'
    assert after['account_id'] == ('account-new' if replace_account else 'account-1')
    for field in ('id', 'owner', 'status', 'review_required', 'remote_id', 'etag', 'last_hash', 'pending_data', 'pending_hash', 'pending_revision', 'attempts'):
        assert after[field] == before[field], field
    if status == 'needs_review':
        assert review(env, rid)['remote']
    assert remote.created == 1 and remote.patched == 0


def test_reselected_review_can_finish_without_duplicate(env):
    app, _, _, remote, _ = env
    rid = queue(env)
    remote.lose_create = True
    app.extensions['calendar_publish'].process(rid)
    hold_timing(app)
    reselect(env, True)
    assert confirm_target(env).status_code == 200
    preview = review(env, rid)
    assert preview['previous']['allDay'] and preview['remote']['allDay']
    assert confirm_review(env, rid, preview).status_code == 200
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status'] == 'published'
    assert remote.created == 1 and remote.patched == 1


def inject_rebind_before_lock(env, monkeypatch, rid):
    engine = env[0].extensions['cloud_accounts']
    real_lock = engine.lock
    fired = False
    snapshots = []
    @contextmanager
    def lock(account_id):
        nonlocal fired
        if not fired:
            fired = True
            reselect(env, True)
            with engine.db() as con:
                con.execute("UPDATE calendar_publications SET account_id='account-new',source_id='source-new' WHERE id=?", (rid,))
            snapshots.append(row(env, rid))
        with real_lock(account_id):
            yield
    monkeypatch.setattr(engine, 'lock', lock)
    return snapshots


@pytest.mark.parametrize('action', ['process', 'error', 'pause', 'retry', 'resume', 'conflict-preview', 'conflict-confirm', 'review-preview', 'review-confirm'])
def test_old_account_lock_never_reads_cloud_or_changes_new_binding(env, monkeypatch, action):
    app, client, headers, remote, _ = env
    publisher = app.extensions['calendar_publish']
    rid = queue(env)
    token = None
    if action.startswith('review'):
        hold_timing(app)
        if action.endswith('confirm'):
            token = review(env, rid)['previewToken']
    elif action.startswith('conflict'):
        publisher.process(rid)
        with app.extensions['cloud_accounts'].db() as con:
            con.execute("UPDATE calendar_publications SET status='conflict' WHERE id=?", (rid,))
        if action.endswith('confirm'):
            p = client.post(f'/api/calendar-publish/publications/{rid}/conflict-preview', json={}, headers=headers)
            assert p.status_code == 200
            token = p.json['previewToken']
    elif action == 'resume':
        with app.extensions['cloud_accounts'].db() as con:
            con.execute("UPDATE calendar_publications SET status='paused' WHERE id=?", (rid,))
    before_calls = len(remote.calls)
    expected = inject_rebind_before_lock(env, monkeypatch, rid)
    if action == 'process':
        publisher.process(rid)
    elif action == 'error':
        publisher._set_error(rid, ProviderError('stale synthetic error', 502), 8)
    else:
        result = client.post(f'/api/calendar-publish/publications/{rid}/{action}', json={'previewToken': token} if token else {}, headers=headers)
        assert result.status_code == 409, result.json
    assert expected and row(env, rid) == expected[0]
    assert len(remote.calls) == before_calls


def test_confirm_reconnect_locks_both_accounts_before_database_write(env, monkeypatch):
    app = env[0]
    engine = app.extensions['cloud_accounts']
    rid = queue(env)
    reselect(env, True)
    actual = engine.lock
    locked = []
    @contextmanager
    def lock(account_id):
        # A write probe can only succeed while the confirmation holds no DB write lock.
        with engine.db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.rollback()
        locked.append(account_id)
        with actual(account_id):
            yield
    monkeypatch.setattr(engine, 'lock', lock)
    assert confirm_target(env).status_code == 200
    assert locked == ['account-1', 'account-new']
    assert row(env, rid)['account_id'] == 'account-new'


@pytest.mark.parametrize('change', ['identity', 'calendar'])
def test_explicit_different_target_does_not_migrate_original_publication(env, change):
    rid = queue(env)
    before = row(env, rid)
    reselect(env, True, subject='different-subject' if change == 'identity' else None,
             calendar='different-calendar' if change == 'calendar' else None)
    result = confirm_target(env)
    assert result.status_code == 200
    assert result.json['publicationIds'] != [rid]
    assert row(env, rid) == before
    # Multiple calendars are an existing explicit feature; neither old publication
    # identity nor its evidence may be repurposed for the newly confirmed target.
    assert not env[3].created


def test_same_identity_now_owned_by_partner_cannot_take_over_prior_publication(env):
    rid = queue(env)
    before = row(env, rid)
    reselect(env, True, owner='member2')
    other = env[0].test_client()
    assert other.post('/api/login', json={'username': 'member2', 'password': 'testing-password-two'}).status_code == 200
    headers = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert confirm_target(env, other, headers).status_code == 409
    assert row(env, rid) == before


def test_reconnect_removes_new_source_mirror_preserving_original_event(env):
    app = env[0]
    engine = app.extensions['cloud_accounts']
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    old = row(env, rid)
    account, source = reselect(env)
    record = {'id': old['remote_id'], 'version': old['etag'], 'data': {'title': 'Synthetic mirror', 'start': '2026-10-01T00:00:00+08:00', 'end': '2026-10-04T00:00:00+08:00', 'allDay': True}}
    with engine.db() as con:
        mirror_id, _ = engine.save_record(con, source, account, record)
    assert mirror_id != old['entity_id']
    assert confirm_target(env).status_code == 200
    with engine.db() as con:
        assert con.execute('SELECT 1 FROM entities WHERE id=?', (old['entity_id'],)).fetchone()
        assert not con.execute('SELECT 1 FROM entities WHERE id=?', (mirror_id,)).fetchone()


def test_review_and_conflict_tokens_are_invalid_after_explicit_reconnect(env):
    app, client, headers, _, _ = env
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    hold_timing(app)
    signed = review(env, rid)
    reselect(env)
    assert confirm_target(env).status_code == 200
    assert confirm_review(env, rid, signed).status_code == 409
    assert publication(env)['reviewRequired'] == 1


@pytest.mark.parametrize('status', ['conflict', 'paused', 'permission_denied', 'needs_review'])
def test_late_error_does_not_resurrect_stopped_queue_generation(env, status):
    app = env[0]
    rid = queue(env)
    with app.extensions['cloud_accounts'].db() as con:
        con.execute('UPDATE calendar_publications SET status=?,review_required=? WHERE id=?', (status, int(status == 'needs_review'), rid))
    before = row(env, rid)
    app.extensions['calendar_publish']._set_error(rid, ProviderError('late synthetic error', 502), 7)
    assert row(env, rid) == before


def test_conflict_confirmation_token_must_be_repreviewed_after_reconnect(env):
    app, client, headers, remote, _ = env
    rid = queue(env)
    app.extensions['calendar_publish'].process(rid)
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE calendar_publications SET status='conflict' WHERE id=?", (rid,))
    p = client.post(f'/api/calendar-publish/publications/{rid}/conflict-preview', json={}, headers=headers)
    assert p.status_code == 200
    reselect(env)
    assert confirm_target(env).status_code == 200
    result = client.post(f'/api/calendar-publish/publications/{rid}/conflict-confirm', json={'previewToken': p.json['previewToken']}, headers=headers)
    assert result.status_code == 409
    assert publication(env)['status'] == 'conflict'
    assert remote.created == 1 and remote.patched == 0


@pytest.mark.parametrize('change', ['subject', 'calendar'])
def test_signed_preview_rejects_target_changed_without_source_id_change(env, change):
    app, client, headers, remote, _ = env
    payload = {'journeyId': 'journey-1', 'sourceId': 'source-1'}
    preview = client.post('/api/calendar-publish/preview', json=payload, headers=headers)
    assert preview.status_code == 200
    with app.extensions['cloud_accounts'].db() as con:
        if change == 'subject':
            con.execute("UPDATE cloud_accounts SET subject='different-subject' WHERE id='account-1'")
        else:
            con.execute("UPDATE cloud_sources SET remote_id='different-calendar' WHERE id='source-1'")
    result = client.post('/api/calendar-publish/confirm', json={**payload, 'previewToken': preview.json['previewToken']}, headers=headers)
    assert result.status_code == 409
    with app.extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0] == 0
    assert not remote.calls
