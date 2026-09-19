"""Local document search with real Flask/SQLite ACLs; synthetic files only."""
import json
import sqlite3

import pytest

from app import create_app
import home_assistant
import journey_documents as documents
from test_journey_documents import (app, no_network, setup, PASSWORD, PDF, login, clone,
    connection, create_journey, upload, payload, patch_value, path, business_snapshot)
from test_device_sessions import install_connection, database, invalidate
from test_member_sessions import legacy


def search(client, query, **paging):
    response = client.get('/api/assistant/search', query_string={'q': query, **paging})
    assert response.status_code == 200, response.json
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json


def snapshot(app):
    result = business_snapshot(app)
    with connection(app) as con:
        result['assistant_plans'] = [tuple(row) for row in con.execute('SELECT * FROM assistant_plans ORDER BY id')]
    return result


def test_minimal_domain_projection_never_reads_blob_or_writes_business_data(app, setup, monkeypatch):
    client, headers, journey = setup
    document, _ = upload(client, headers, journey['id'], title='资料 <img src=x onerror=alert(1)>')
    before = snapshot(app)
    calls, forbidden = [], []
    current = app.extensions['member_sessions'].current
    projection = documents.metadata
    def metadata(row, *args):
        calls.append(row['id'])
        return projection(row, *args)
    def checked(con):
        assert con.in_transaction
        result = current(con)
        def authorize(operation, table, column, *_):
            if operation == sqlite3.SQLITE_READ and (table.startswith('hub_') or
                    table == 'journey_documents' and column in {'content', 'payload_digest', 'request_id'}):
                forbidden.append((table, column)); return sqlite3.SQLITE_DENY
            if operation in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                forbidden.append((table, 'write')); return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        con.set_authorizer(authorize)
        return result
    monkeypatch.setattr(documents, 'metadata', metadata)
    monkeypatch.setattr(app.extensions['member_sessions'], 'current', checked)
    monkeypatch.setattr(home_assistant, 'model_plan', lambda *_: pytest.fail('search must stay local'))
    response = search(client, 'SYNTHETIC-TICKET.PDF')
    assert response['matches'] == [{'kind': 'documents', 'id': document['id'], 'title': document['title'],
        'filename': document['filename'], 'mimeType': 'application/pdf', 'revision': 1, 'visibility': 'private',
        'journey': {'id': journey['id'], 'tripId': journey['tripId'], 'title': '合成旅行'}}]
    assert response['total'] == 1 and calls == [document['id'], document['id']] and not forbidden
    assert snapshot(app) == before
    assert 'SYNTHETIC TICKET' not in json.dumps(response)


def test_private_shared_withdrawal_and_deleted_totals(app, setup):
    owner, headers, journey = setup; partner, ph = login(app, 2)
    mine, _ = upload(owner, headers, journey['id'], title='可见边界_本人秘密')
    theirs, _ = upload(partner, ph, journey['id'], title='可见边界_伙伴秘密')
    shared, _ = upload(owner, headers, journey['id'], title='可见边界_共享', visibility='shared')
    assert {x['id'] for x in search(owner, '可见边界')['matches']} == {mine['id'], shared['id']}
    assert {x['id'] for x in search(partner, '可见边界')['matches']} == {theirs['id'], shared['id']}
    assert search(owner, '伙伴秘密')['total'] == search(partner, '本人秘密')['total'] == 0
    changed = owner.patch(path(shared), headers=headers, json=patch_value(shared, visibility='private'))
    assert changed.status_code == 200
    assert search(partner, '可见边界')['total'] == 1
    assert owner.delete(path(mine), headers=headers, json={'revision': mine['revision']}).status_code == 200
    assert search(owner, '本人秘密')['matches'] == [] and search(owner, '可见边界')['total'] == 1
    assert search(partner, '本人秘密')['total'] == 0


def test_journey_deletion_makes_stored_shared_document_owner_only_then_relink(app, setup):
    owner, headers, journey = setup; partner, _ = login(app, 2)
    item, _ = upload(owner, headers, journey['id'], title='未关联资料索引', visibility='shared')
    assert search(partner, '未关联资料索引')['total'] == 1
    trip = owner.get('/api/journeys/' + journey['id']).json['trip']
    assert owner.delete('/api/items/trips/' + journey['tripId'], headers=headers,
                        json={'revision': trip['revision']}).status_code == 200
    result = search(owner, '未关联资料索引')['matches'][0]
    assert result['visibility'] == 'private' and result['journey'] is None and result['revision'] == 2
    assert search(partner, '未关联资料索引')['total'] == 0
    # The existing generated calendar event may remain after deleting its trip;
    # document search must drop the old linkage without changing legacy kinds.
    assert not [row for row in search(owner, '合成旅行')['matches'] if row['kind'] == 'documents']
    with connection(app) as con:
        row = con.execute('SELECT visibility,journey_id FROM journey_documents WHERE id=?', (item['id'],)).fetchone()
        assert tuple(row) == ('shared', None)  # Effective scope comes from domain metadata.
    new = create_journey(owner, headers, title='重新关联索引')
    response = owner.patch(path(item), headers=headers,
        json=patch_value(item, revision=2, journeyId=new['id'], visibility='shared', segmentKey=''))
    assert response.status_code == 200
    matched = [x for x in search(partner, '重新关联索引')['matches'] if x['kind'] == 'documents']
    assert matched[0]['journey'] == {'id': new['id'], 'tripId': new['tripId'], 'title': '重新关联索引'}


def test_metadata_matching_is_literal_casefolded_and_does_not_search_file_content(app, setup):
    client, headers, journey = setup
    value = payload(journey['id'], title='Straße 100%_ 合成资料')
    value['file']['name'] = '专用文件名.Pdf'.replace('.Pdf', '.pdf')
    response = client.post('/api/journey-documents', headers=headers, json=value)
    assert response.status_code == 201
    uid = response.json['document']['id']
    for query in ('STRASSE', '100%_', '专用文件名', '合成旅行'):
        assert uid in {x['id'] for x in search(client, query)['matches']}
    for query in ('SYNTHETIC TICKET ONLY', "%' OR 1=1 --", 'SYNTHETIC_PROVIDER_TOKEN'):
        assert search(client, query)['total'] == 0


def test_global_pagination_stays_stable_and_private_documents_do_not_inflate_counts(app, setup):
    owner, headers, journey = setup; partner, ph = login(app, 2)
    ids = {upload(owner, headers, journey['id'], title='分页资料_' + str(n))[0]['id'] for n in range(5)}
    for n in range(3): upload(partner, ph, journey['id'], title='分页资料_隐藏' + str(n))
    task = owner.post('/api/items/tasks', headers=headers, json={'title': '分页资料_待办'})
    assert task.status_code == 201; ids.add(task.json['id'])
    rows, offset = [], 0
    while offset is not None:
        page = search(owner, '分页资料', limit=2, offset=offset)
        assert page['total'] == 6 and len(page['matches']) <= 2
        rows.extend((x['kind'], x['id']) for x in page['matches']); offset = page['nextOffset']
    assert rows == sorted(rows) and {uid for _, uid in rows} == ids and len(rows) == len(set(rows))
    assert search(owner, '分页资料', offset=6)['matches'] == []
    assert search(owner, '分页资料', offset=20000)['nextOffset'] is None
    assert search(owner, '分页资料_隐藏')['total'] == 0


@pytest.mark.parametrize('prompt', ['搜索：本地资料标记', '查找 本地资料标记', '找一下 本地资料标记'])
def test_local_query_plan_reuses_readonly_results_even_when_model_requested(app, setup, monkeypatch, prompt):
    client, headers, journey = setup
    document, _ = upload(client, headers, journey['id'], title='本地资料标记')
    expected = search(client, '本地资料标记')
    before = snapshot(app)
    monkeypatch.setattr(home_assistant, 'model_plan', lambda *_: pytest.fail('search called model'))
    response = client.post('/api/assistant/plan', headers=headers,
        json={'prompt': prompt, 'useModel': True, 'includeHouseholdContext': True})
    assert response.status_code == 200
    assert response.json['matches'] == expected['matches']
    assert response.json['mode'] == 'local' and response.json['id'] is None and response.json['actions'] == []
    assert response.json['search']['total'] == 1 and response.json['matches'][0]['id'] == document['id']
    assert snapshot(app) == before


def test_documents_never_enter_optional_model_context_or_brief(app, setup, monkeypatch):
    client, headers, journey = setup
    document, _ = upload(client, headers, journey['id'], title='DOCUMENT_PRIVATE_CANARY')
    app.config.update(ASSISTANT_PROVIDER='openai', OPENAI_API_KEY='synthetic', OPENAI_MODEL='synthetic')
    calls = []
    def model(_config, prompt, context):
        calls.append((prompt, context)); return {'summary': '合成草案', 'actions': []}
    monkeypatch.setattr(home_assistant, 'model_plan', model)
    response = client.post('/api/assistant/plan', headers=headers,
        json={'prompt': '安排本周事项', 'useModel': True, 'includeHouseholdContext': True})
    assert response.status_code == 200 and len(calls) == 1
    serialized = json.dumps(calls)
    for secret in (document['id'], document['title'], document['filename'], PDF.decode()): assert secret not in serialized
    assert set(calls[0][1]) == {'today', 'events', 'tasks'}
    assert document['title'] not in client.get('/api/assistant/brief').get_data(as_text=True)


def test_cross_household_routing_and_foreign_cookie(app, setup):
    root, headers, journey = setup
    upload(root, headers, journey['id'], title='ROOT_DOCUMENT_ONLY', visibility='shared')
    invitation = root.post('/api/spaces/invitations', headers=headers, json={}).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem', json={'invitation': invitation, 'name': '资料搜索合成第二户',
        'slug': 'document-search-two', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert response.status_code == 201 and child.get(response.json['entry']).status_code == 303
    child, ch = login(app, client=child); other_journey = create_journey(child, ch)
    upload(child, ch, other_journey['id'], title='CHILD_DOCUMENT_ONLY', visibility='shared')
    assert search(root, 'CHILD_DOCUMENT_ONLY')['total'] == search(child, 'ROOT_DOCUMENT_ONLY')['total'] == 0
    assert search(child, 'CHILD_DOCUMENT_ONLY')['total'] == 1
    child.set_cookie('session', root.get_cookie('session').value)
    assert child.get('/api/assistant/search?q=DOCUMENT').status_code == 401


def test_anonymous_tv_csrf_and_logout_boundaries(app, setup):
    owner, headers, journey = setup
    upload(owner, headers, journey['id'], title='PRIVATE_DOCUMENT')
    assert app.test_client().get('/api/assistant/search?q=PRIVATE').status_code == 401
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert owner.post('/api/pair/approve', headers=headers, json={'code': pair['code'], 'name': '合成电视'}).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.get('/api/assistant/search?q=PRIVATE').status_code == 403
    assert owner.get('/api/assistant/search?q=PRIVATE', headers={'X-Display-Mode': 'tv'}).status_code in (401, 403)
    assert owner.post('/api/assistant/plan', json={'prompt': '搜索 PRIVATE'}).status_code == 403
    old = clone(app, owner)
    assert owner.post('/api/logout', headers=headers, json={}).status_code == 200
    assert old.get('/api/assistant/search?q=PRIVATE').status_code == 401


@pytest.mark.parametrize('params', [{}, {'q': ''}, {'q': 'x' * 101}, {'q': 'x', 'limit': '31'},
    {'q': 'x', 'offset': '-1'}, {'q': 'x', 'owner': 'member2'}, [('q', 'x'), ('q', 'y')]])
def test_existing_query_contract_rejects_invalid_or_identity_selector_inputs(app, params):
    client, _ = login(app)
    assert client.get('/api/assistant/search', query_string=params).status_code == 400


def test_restart_and_legacy_session_keep_same_document_projection(app, setup, monkeypatch):
    client, headers, journey = setup
    upload(client, headers, journey['id'], title='重启资料索引')
    before = search(client, '重启资料索引')
    restarted = create_app(dict(app.config))
    assert search(clone(restarted, client), '重启资料索引') == before
    old, _, _ = legacy(app, app.extensions['member_sessions'], monkeypatch)
    assert search(old, '重启资料索引') == before
    assert search(old, '重启资料索引') == before


@pytest.mark.parametrize('endpoint', ['search', 'plan'])
@pytest.mark.parametrize('change', ['unshare', 'delete', 'unlink'])
def test_fresh_metadata_pass_removes_revoked_results_and_counts(app, setup, endpoint, change):
    owner, headers, journey = setup; partner, ph = login(app, 2)
    document, _ = upload(owner, headers, journey['id'], title='WITHDRAWN_DOCUMENT_CANARY', visibility='shared')
    observed = []
    def withdraw(sql):
        if sql.startswith('SELECT d.id,') and not observed:
            with connection(app) as con:
                if change == 'unshare':
                    con.execute("UPDATE journey_documents SET visibility='private',revision=revision+1 WHERE id=?", (document['id'],))
                elif change == 'delete':
                    con.execute("UPDATE journey_documents SET deleted_at='2026-09-20',revision=revision+1 WHERE id=?", (document['id'],))
                else:
                    con.execute('UPDATE journey_documents SET journey_id=NULL WHERE id=?', (document['id'],))
            observed.append(change)
    method = 'GET' if endpoint == 'search' else 'POST'
    install_connection(app, '/api/assistant/' + endpoint, method, after=withdraw)
    response = (partner.get('/api/assistant/search?q=WITHDRAWN_DOCUMENT_CANARY') if endpoint == 'search' else
                partner.post('/api/assistant/plan', headers=ph, json={'prompt': '搜索 WITHDRAWN_DOCUMENT_CANARY'}))
    assert response.status_code == 200 and observed == [change]
    result = response.json if endpoint == 'search' else response.json['search']
    assert result['total'] == 0 and response.json['matches'] == []
    # Query text can echo the user's input; no record identity or metadata survives.
    assert document['id'] not in response.get_data(as_text=True) and document['filename'] not in response.get_data(as_text=True)


@pytest.mark.parametrize('pass_number', [1, 2])
@pytest.mark.parametrize('kind', ['session', 'expired', 'auth_version', 'generation'])
def test_session_revoked_during_either_document_snapshot_returns_no_metadata(app, setup, pass_number, kind):
    client, headers, journey = setup
    upload(client, headers, journey['id'], title='REVOKED_DOCUMENT_CANARY')
    reads = []
    def revoke(sql):
        if sql.startswith('SELECT d.id,'):
            reads.append(True)
            if len(reads) == pass_number:
                with connection(app) as con:
                    if kind == 'generation': con.execute('UPDATE member_session_browsers SET generation=generation+1')
                    else: invalidate(con, kind)
    install_connection(app, '/api/assistant/search', 'GET', after=revoke)
    response = client.get('/api/assistant/search?q=REVOKED_DOCUMENT_CANARY')
    assert len(reads) == pass_number and response.status_code == (409 if kind == 'generation' else 401)
    assert set(response.json) == {'error'} and 'REVOKED_DOCUMENT_CANARY' not in response.get_data(as_text=True)


def test_projection_requires_existing_transaction_and_private_changes_are_invisible(app, setup):
    owner, headers, journey = setup; partner, _ = login(app, 2)
    document, _ = upload(owner, headers, journey['id'], title='OWNER_PRIVATE_DOCUMENT')
    with connection(app) as con:
        with pytest.raises(ValueError, match='authorized_transaction'):
            documents.search_metadata(con, 'member1', 'OWNER_PRIVATE_DOCUMENT')
    changed = []
    def update_private(sql):
        if sql.startswith('SELECT d.id,') and not changed:
            with connection(app) as con:
                con.execute("UPDATE journey_documents SET title='OWNER_PRIVATE_DOCUMENT_CHANGED',revision=revision+1 WHERE id=?", (document['id'],))
            changed.append(True)
    install_connection(app, '/api/assistant/search', 'GET', after=update_private)
    result = search(partner, 'OWNER_PRIVATE_DOCUMENT')
    assert changed == [True] and result['matches'] == [] and result['total'] == 0
