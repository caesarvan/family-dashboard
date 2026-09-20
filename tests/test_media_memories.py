"""Owner memories through real Flask/SQLite and encrypted synthetic photo metadata."""
from contextlib import closing, contextmanager
from datetime import datetime
import secrets
import sqlite3

from flask import request
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from app import create_app
from test_device_sessions import invalidate
from test_household_media import env, offline, configured, confirm, device, selected, share, stage
from test_journey_documents import login
from test_media_suggestion_sessions import snapshot


URL = '/api/media/memories/on-this-day'
TODAY = '2026-09-20T00:00:00+00:00'


def set_today(env, instant=TODAY):
    env[2][0] = datetime.fromisoformat(instant).timestamp()


def photos(env, stamps=('2025-09-20T00:00:00Z',), number=1):
    sources = []
    for stamp in stamps:
        item = selected(secrets.token_hex(12))
        item['createTime'] = stamp
        sources.append(item)
    client, headers, detail, _ = stage(env, number, sources)
    confirm(client, headers, detail)
    items = [client.get('/api/media/items/' + row['id']).json['item'] for row in detail['items']]
    return client, headers, items


def change_metadata(env, uid, changes=None, remove=()):
    engine = env[1]
    with engine.transaction(True) as con:
        row = con.execute('SELECT * FROM media_items WHERE id=?', (uid,)).fetchone()
        value = engine._metadata(row)
        value.update(changes or {})
        for key in remove:
            value.pop(key, None)
        con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?',
                    (engine._seal('media-metadata', row, value), uid))


def memories(client, query=''):
    response = client.get(URL + query)
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json


def test_owner_original_dto_source_date_and_read_only_restart(env):
    client, headers, items = photos(env)
    shared = share(client, headers, items[0])
    set_today(env)
    before = snapshot(env)
    result = memories(client)
    assert result == {
        'referenceDate': '2026-09-20', 'referenceTimezone': 'Asia/Shanghai',
        'dateBasis': 'sourceCreatedAt', 'scope': 'mine',
        'items': [{'item': shared, 'sourceLocalDate': '2025-09-20', 'yearsAgo': 1}],
        'total': 1, 'limit': 24, 'offset': 0, 'hasMore': False, 'unknownSourceTimeCount': 0,
    }
    assert shared['createdAt'] != shared['sourceCreatedAt']
    assert snapshot(env) == before
    restarted = create_app(dict(env[0].config))
    restarted.extensions['household_media'].clock = env[1].clock
    other, _ = login(restarted)
    assert memories(other) == result
    assert snapshot(env) == before


def test_source_date_offsets_exclude_current_future_adjacent_days(env):
    client, _, items = photos(env, (
        '2025-09-19T16:00:00.000000001Z',  # midnight in Shanghai
        '2024-09-20T15:59:59.999999999Z',  # last instant of that civil day
        '2023-09-20T00:30:00+14:00',      # September 19 in Shanghai
        '2025-09-19T15:59:59.999999999Z',
        '2025-09-20T16:00:00Z',
        '2026-09-20T00:00:00Z',
        '2027-09-20T00:00:00Z',
    ))
    set_today(env)
    result = memories(client)
    assert [entry['item']['id'] for entry in result['items']] == [items[0]['id'], items[1]['id']]
    assert [entry['yearsAgo'] for entry in result['items']] == [1, 2]
    assert result['total'] == 2 and result['unknownSourceTimeCount'] == 0


@pytest.mark.parametrize('today,expected_date,expected_indices', [
    ('2026-09-19T15:59:59+00:00', '2026-09-19', [0]),
    ('2026-09-19T16:00:00+00:00', '2026-09-20', [1]),
    ('2028-02-28T16:00:00+00:00', '2028-02-29', [3]),
    ('2027-02-27T16:00:00+00:00', '2027-02-28', [2]),
])
def test_server_midnight_and_leap_day_no_substitution(env, today, expected_date, expected_indices):
    client, _, items = photos(env, ('2025-09-19T00:00:00Z', '2025-09-20T00:00:00Z',
                                  '2024-02-28T00:00:00Z', '2024-02-29T00:00:00Z'))
    set_today(env, today)
    result = memories(client)
    assert result['referenceDate'] == expected_date
    assert [entry['item']['id'] for entry in result['items']] == [items[n]['id'] for n in expected_indices]


def test_source_local_date_id_order_and_pagination_do_not_use_update_time(env):
    client, headers, items = photos(env, (
        '2025-09-20T00:00:00.000000001Z',
        '2025-09-20T08:00:00.000000003+08:00',
        '2025-09-20T00:00:00.000000002Z',
        '2024-09-20T00:00:00Z', '2024-09-20T08:00:00+08:00',
    ))
    assert client.patch('/api/media/items/' + items[3]['id'], headers=headers,
                        json={'revision': items[3]['revision'], 'caption': 'Edited old photo'}).status_code == 200
    set_today(env)
    expected = sorted(items[n]['id'] for n in (0, 1, 2)) + sorted(items[n]['id'] for n in (3, 4))
    pages = [memories(client, '?limit=2&offset=' + str(n)) for n in (0, 2, 4)]
    assert [entry['item']['id'] for page in pages for entry in page['items']] == expected
    assert [page['hasMore'] for page in pages] == [True, True, False]
    assert all(page['total'] == 5 for page in pages)
    assert memories(client, '?limit=100&offset=4000')['items'] == []
    assert memories(client, '?limit=1')['items'][0]['item']['id'] == expected[0]
    assert [entry['item']['id'] for entry in memories(client)['items']] == expected


def test_unknown_legacy_invalid_time_and_video_counts_are_owner_photo_only(env):
    client, _, items = photos(env, ('2025-09-20T00:00:00Z',) * 7)
    change_metadata(env, items[0]['id'], remove=('mediaType',))  # existing legacy photo
    change_metadata(env, items[1]['id'], remove=('sourceCreatedAt',))
    change_metadata(env, items[2]['id'], {'sourceCreatedAt': '2025-02-30T00:00:00Z'})
    change_metadata(env, items[3]['id'], {'sourceCreatedAt': '9999-12-31T23:59:59-23:59'})
    change_metadata(env, items[4]['id'], {'sourceCreatedAt': 123})
    # This is a metadata exclusion fixture, not a claim of successful video decoding.
    change_metadata(env, items[5]['id'], {'mediaType': 'video', 'sourceCreatedAt': None})
    change_metadata(env, items[6]['id'], {'mediaType': 'unsupported', 'sourceCreatedAt': None})
    set_today(env)
    before = snapshot(env)
    result = memories(client)
    assert result['total'] == 1 and result['unknownSourceTimeCount'] == 4
    assert result['items'][0]['item']['id'] == items[0]['id']
    assert result['items'][0]['item']['mediaType'] == 'photo'
    assert snapshot(env) == before


def test_staged_unconfirmed_deleted_and_partner_content_do_not_leak_counts(env):
    client, headers, items = photos(env, ('2025-09-20T00:00:00Z',) * 2)
    assert client.delete('/api/media/items/' + items[1]['id'], headers=headers,
                         json={'revision': items[1]['revision']}).status_code == 200
    source = selected(secrets.token_hex(12)); source['createTime'] = '2025-09-20T00:00:00Z'
    stage(env, items=[source])  # unconfirmed staging is never a memory
    partner, partner_headers, theirs = photos(env, number=2)
    share(partner, partner_headers, theirs[0])
    change_metadata(env, theirs[0]['id'], {'sourceCreatedAt': None})
    set_today(env)
    result = memories(client)
    assert result['total'] == 1 and result['unknownSourceTimeCount'] == 0
    assert result['items'][0]['item']['id'] == items[0]['id']
    theirs_result = memories(partner)
    assert theirs_result['total'] == 0 and theirs_result['unknownSourceTimeCount'] == 1


def test_separate_households_and_real_tv_and_anonymous_are_isolated(env, tmp_path, monkeypatch):
    client, headers, items = photos(env)
    item = share(client, headers, items[0])
    device_id, tv, _ = device(env)
    assert client.put('/api/media/items/' + item['id'] + '/tv-grants', headers=headers, json={
        'revision': item['revision'], 'deviceIds': [device_id],
        'consentVersion': 'media-v1', 'allowTvDisplay': True}).status_code == 200
    assert tv.get(URL).status_code == 403
    assert env[0].test_client().get(URL).status_code == 401
    partner, _ = login(env[0], 2)
    shared = partner.get('/api/media/items/' + item['id']).json['item']
    assert 'sourceCreatedAt' not in shared and 'sourceTimeState' not in shared
    set_today(env)
    assert memories(partner)['total'] == 0
    second = configured(tmp_path / 'second', monkeypatch, 'synthetic-second-household')
    other, _ = login(second[0]); set_today(second)
    assert memories(other)['total'] == 0
    assert memories(other)['unknownSourceTimeCount'] == 0
    assert other.get('/api/media/items/' + item['id']).status_code == 404
    assert client.post('/api/logout', headers=headers, json={}).status_code == 200
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize('query', [
    '?limit=0', '?limit=101', '?limit=-1', '?limit=1.5', '?limit=',
    '?offset=-1', '?offset=4001', '?offset=1e2', '?offset=',
    '?limit=1&limit=2', '?offset=0&offset=1', '?date=2025-09-20',
    '?owner=member2', '?scope=shared', '?timezone=UTC', '?journeyId=' + 'a' * 24,
])
def test_query_boundaries_reject_client_scope_and_clock(env, query):
    client, _ = login(env[0])
    response = client.get(URL + query)
    assert response.status_code == 400 and response.json['code'] == 'invalid_input'
    assert 'items' not in response.json


def test_endpoint_is_read_only_and_empty_state_is_explicit(env):
    client, headers = login(env[0]); set_today(env)
    before = snapshot(env)
    result = memories(client)
    assert result['total'] == result['unknownSourceTimeCount'] == 0
    assert result['items'] == [] and not result['hasMore']
    for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        assert client.open(URL, method=method, headers=headers, json={}).status_code == 405
    assert snapshot(env) == before


def test_no_preview_video_blob_reads_and_no_source_reauthorization_requirement(env, monkeypatch):
    client, _, items = photos(env)
    engine = env[1]
    with engine.transaction(True) as con:
        engine.on_account_authority_changed(con, env[3][1], 'reauth')
    set_today(env)
    original = engine.sessions.db
    forbidden, reads = [], []

    @contextmanager
    def checked_connections():
        with original() as con:
            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ:
                    reads.append((table, column))
                    if table == 'media_video_cache' or (table == 'media_items' and column == 'preview_cipher'):
                        forbidden.append((table, column))
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorize)
            yield con
    monkeypatch.setattr(engine.sessions, 'db', checked_connections)
    result = memories(client)
    assert not forbidden and ('media_items', 'metadata_cipher') in reads
    assert result['items'][0]['item']['id'] == items[0]['id']


@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version'])
@pytest.mark.parametrize('unknown', [False, True])
def test_mid_read_committed_revocation_discards_rows_and_counts(env, monkeypatch, kind, unknown):
    client, _, items = photos(env)
    if unknown:
        change_metadata(env, items[0]['id'], remove=('sourceCreatedAt',))
    set_today(env)
    engine = env[1]
    before, original, revoked = snapshot(env), engine._metadata, []

    def revoke(row):
        value = original(row)
        if not revoked:
            with closing(sqlite3.connect(engine.sessions.path)) as writer:
                invalidate(writer, kind)
                writer.commit()
            revoked.append(True)
        return value
    monkeypatch.setattr(engine, '_metadata', revoke)
    response = client.get(URL)
    assert revoked == [True] and response.status_code == 401
    assert 'items' not in response.json and 'unknownSourceTimeCount' not in response.json
    assert snapshot(env) == before


@pytest.mark.parametrize('number', [1, 2])
def test_valid_cookie_cannot_replace_captured_identity_mid_read(env, monkeypatch, number):
    client, _, _ = photos(env)
    replacement, _ = login(env[0], number)
    cookie = replacement.get_cookie('session').value
    assert cookie != client.get_cookie('session').value
    set_today(env)
    original = env[1]._metadata

    def replace(row):
        value = original(row)
        cookies = dict(request.cookies); cookies['session'] = cookie
        request.__dict__['cookies'] = ImmutableMultiDict(cookies)
        return value
    monkeypatch.setattr(env[1], '_metadata', replace)
    assert client.get(URL).status_code == 401


def test_corrupt_cipher_is_not_silently_counted_as_unknown(env):
    client, _, items = photos(env); set_today(env)
    with env[1].transaction(True) as con:
        con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?', (b'corrupt-synthetic', items[0]['id']))
    response = client.get(URL)
    assert response.status_code == 503 and response.json['code'] == 'unavailable'
    assert 'items' not in response.json and 'unknownSourceTimeCount' not in response.json


def test_reference_day_is_captured_once_and_next_read_rolls_over(env, monkeypatch):
    client, _, items = photos(env, ('2025-09-19T00:00:00Z', '2025-09-20T00:00:00Z'))
    set_today(env, '2026-09-19T15:59:59+00:00')
    original = env[1]._metadata

    def cross_midnight(row):
        value = original(row)
        set_today(env, '2026-09-19T16:00:00+00:00')
        return value
    monkeypatch.setattr(env[1], '_metadata', cross_midnight)
    first, second = memories(client), memories(client)
    assert first['referenceDate'] == '2026-09-19' and first['items'][0]['item']['id'] == items[0]['id']
    assert second['referenceDate'] == '2026-09-20' and second['items'][0]['item']['id'] == items[1]['id']
