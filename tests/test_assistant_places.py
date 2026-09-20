"""Actual SQLite commits between assistant search snapshots; external I/O forbidden."""
from contextlib import closing

import pytest

from test_journey_places import app, no_network, create, path, PASSWORD
from test_journey_documents import login, connection, create_journey
from test_device_sessions import install_connection


def search(client, headers=None, *, plan=False, **params):
    response = (client.post('/api/assistant/plan', headers=headers, json={'prompt': '搜索 needle'})
                if plan else client.get('/api/assistant/search', query_string={'q': 'needle', **params}))
    assert response.status_code == 200, response.json
    return response, response.json['search'] if plan else response.json


def intercept(app, action, *, plan=False, at=1):
    observed = []
    def after(sql):
        if ' FROM journey_places WHERE deleted_at IS NULL AND (owner=' in sql:
            assert not any(name in sql for name in ('latitude', 'longitude', 'SELECT *'))
            observed.append(sql)
            if len(observed) == at:
                with closing(connection(app)) as con:
                    action(con)
                    con.commit()
    install_connection(app, '/api/assistant/' + ('plan' if plan else 'search'), 'POST' if plan else 'GET', after=after)
    return observed


@pytest.mark.parametrize('change', ['unshare', 'delete', 'rename'])
@pytest.mark.parametrize('plan', [False, True])
def test_final_place_snapshot_removes_old_title_and_count(app, change, plan):
    owner, h = login(app)
    item, _ = create(owner, h, name='needle PRIVATE_PLACE_CANARY', visibility='shared')
    partner, ph = login(app, 2)
    sql = {'unshare': "UPDATE journey_places SET visibility='private' WHERE id=?",
           'delete': 'UPDATE journey_places SET deleted_at=1 WHERE id=?',
           'rename': "UPDATE journey_places SET name='no longer matches' WHERE id=?"}[change]
    observed = intercept(app, lambda con: con.execute(sql, (item['id'],)), plan=plan)
    response, result = search(partner, ph, plan=plan)
    assert len(observed) == 2 and result['total'] == 0 and result['nextOffset'] is None
    assert response.json['matches'] == []
    assert 'PRIVATE_PLACE_CANARY' not in response.text and item['id'] not in response.text


def test_final_place_projection_reads_current_revision_and_linked_trip(app):
    owner, h = login(app)
    trip = create_journey(owner, h)
    item, _ = create(owner, h, name='needle old', visibility='shared', journeyId=trip['id'])
    partner, _ = login(app, 2)
    observed = intercept(app, lambda con: con.execute(
        "UPDATE journey_places SET name='needle current',journey_id=NULL,revision=revision+1 WHERE id=?", (item['id'],)))
    _, result = search(partner)
    assert len(observed) == 2 and result['total'] == 1
    hit = result['matches'][0]
    assert hit['id'] == item['id'] and hit['revision'] == 2 and hit['title'] == 'needle current' and hit['journey'] is None
    assert not {'coordinates', 'latitude', 'longitude', 'coordinateDisclosure', 'owner'} & hit.keys()


def test_final_session_revocation_discards_all_place_metadata(app):
    owner, h = login(app)
    create(owner, h, name='needle PRIVATE_PLACE_CANARY', visibility='shared')
    partner, _ = login(app, 2)
    observed = intercept(app, lambda con: con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member2'"), at=2)
    response = partner.get('/api/assistant/search?q=needle')
    assert len(observed) == 2 and response.status_code == 401
    assert set(response.json) == {'error'} and 'PRIVATE_PLACE_CANARY' not in response.text


def test_page_outside_map_first_page_keeps_original_id_and_readonly_projection(app):
    owner, h = login(app)
    ids = []
    for i in range(25):
        item, _ = create(owner, h, name=f'needle {i}', visibility='shared',
                         coordinates={'latitude': 31.2304, 'longitude': 121.4737}, coordinateDisclosure='coarse')
        ids.append(item['id'])
    partner, _ = login(app, 2)
    before = search(partner, limit=1, offset=24)[1]
    assert before['total'] == 25 and before['nextOffset'] is None
    hit = before['matches'][0]
    assert hit['id'] == sorted(ids)[24]
    current = partner.get('/api/journey-places/' + hit['id'])
    assert current.status_code == 200 and current.json['place']['id'] == hit['id']
    assert current.json['place']['revision'] == hit['revision'] and not current.json['place']['canManage']
    assert current.json['place']['coordinatePrecision'] == 'approximate'
    assert search(partner, limit=1, offset=24)[1] == before


def test_private_and_second_household_are_excluded_and_search_is_readonly(app):
    owner, h = login(app)
    secret, _ = create(owner, h, name='needle PRIVATE_PLACE_CANARY')
    partner, _ = login(app, 2)
    assert search(partner)[1]['total'] == 0
    invitation = owner.post('/api/spaces/invitations', json={}, headers=h).json['invitation']
    child = app.test_client()
    response = child.post('/api/spaces/redeem', json={'invitation': invitation, 'name': '合成第二家庭', 'slug': 'assistant-place-second',
        'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    assert response.status_code == 201 and child.get(response.json['entry']).status_code == 303
    child, ch = login(app, client=child)
    create(child, ch, name='needle SECOND_HOUSEHOLD_CANARY', visibility='shared')
    with closing(connection(app)) as con:
        before = [tuple(row) for row in con.execute('SELECT * FROM journey_places ORDER BY id')]
        audit = con.execute('SELECT count(*) FROM audit').fetchone()[0]
    result = search(owner)[1]
    assert result['total'] == 1 and result['matches'][0]['id'] == secret['id']
    assert 'SECOND_HOUSEHOLD_CANARY' not in str(result)
    assert child.get(path(secret)).status_code == 404
    with closing(connection(app)) as con:
        assert before == [tuple(row) for row in con.execute('SELECT * FROM journey_places ORDER BY id')]
        assert audit == con.execute('SELECT count(*) FROM audit').fetchone()[0]
