"""Real WSGI routing, session and database isolation; no external services."""
from pathlib import Path
import sqlite3
import pytest
from test_app import app, member


def create_space(app, slug='second-home'):
    c, h = member(app)
    invite = c.post('/api/spaces/invitations', json={}, headers=h)
    assert invite.status_code == 201
    payload = {'invitation': invite.json['invitation'], 'name': '新家庭', 'slug': slug,
               'MEMBER1_PASSWORD': 'second-home-password-one', 'MEMBER2_PASSWORD': 'second-home-password-two'}
    public = app.test_client()
    result = public.post('/api/spaces/redeem', json=payload)
    assert result.status_code == 201, result.json
    return public, payload, result.json


def test_tenant_isolation_and_sessions(app):
    primary, headers = member(app)
    item = primary.post('/api/items/tasks', json={'title': 'ORIGINAL_HOUSEHOLD_PRIVATE_TASK'}, headers=headers).json['id']
    b, _, result = create_space(app)
    assert b.get(result['entry']).status_code == 303
    assert b.get('/api/state').status_code == 401
    assert b.post('/api/login', json={'username': 'member1', 'password': 'testing-password-one'}).status_code == 401
    assert b.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    bh = {'X-CSRF-Token': b.get('/api/me').json['csrf']}
    assert b.get('/api/state').json['tasks'] == []
    assert b.patch('/api/items/tasks/' + item, json={'revision': 1, 'done': True}, headers=bh).status_code == 404
    assert b.post('/api/items/tasks', json={'title': 'SECOND_FAMILY'}, headers=bh).status_code == 201
    assert 'SECOND_FAMILY' not in primary.get('/api/state').get_data(as_text=True)
    assert b.post('/api/spaces/invitations', json={}, headers=bh).status_code == 403
    # Routing is not authentication, including even a previously valid main session.
    stolen_session = primary.get_cookie('session').value
    b.set_cookie('session', stolen_session)
    assert b.get('/api/state').status_code == 401
    assert b.get('/space/home').status_code == 303
    assert b.get('/api/state').status_code == 401
    assert primary.get('/api/state').status_code == 200


def test_invite_one_use_validation_and_preferences(app):
    b, payload, result = create_space(app)
    assert b.post('/api/spaces/redeem', json={**payload, 'slug': 'third-home'}).status_code == 403
    assert b.post('/api/spaces/redeem', json={**payload, 'slug': '../../other'}).status_code == 400
    assert b.post('/api/spaces/redeem', json=payload, headers={'Origin': 'https://evil.example'}).status_code == 403
    c, h = member(app)
    assert c.put('/api/preferences', json={'revision': 0, 'changes': {'theme': 'light', 'density': 'compact', 'homeView': 'week'}}, headers=h).status_code == 200
    assert c.get('/api/preferences').json['theme'] == 'light'
    other, _ = member(app, 2)
    assert other.get('/api/preferences').json['theme'] == 'forest'
    assert c.put('/api/preferences', json={'revision': 1, 'changes': {'theme': {'x': 1}, 'density': 'compact', 'homeView': 'week'}}, headers=h).status_code == 400
    assert other.post('/api/spaces/invitations', json={}, headers={'X-CSRF-Token': other.get('/api/me').json['csrf']}).status_code == 403


def test_restart_loads_existing_child_and_rejects_tampered_routing(app):
    b, _, result = create_space(app)
    platform = app.extensions['household_platform']
    platform.cache.clear()
    assert b.get(result['entry']).status_code == 303
    assert b.get('/api/spaces/current').json['slug'] == 'second-home'
    b.set_cookie('household_space', 'unsigned-second-home')
    bad=b.get('/api/state')
    assert bad.status_code == 400 and bad.json['recoveryUrl']=='/space/home'
    assert bad.headers['Cache-Control']=='no-store'
    assert b.get('/space/does-not-exist').status_code == 404


def test_child_cloud_storage_and_keys_are_distinct(app):
    create_space(app)
    platform = app.extensions['household_platform']
    household = next(h for h in platform.households() if h['id'] != 'default')
    child = platform.child(household)
    assert child.secret_key != app.secret_key
    assert child.extensions['cloud_accounts'].path != app.extensions['cloud_accounts'].path
    assert child.extensions['cloud_accounts'].lock_dir != app.extensions['cloud_accounts'].lock_dir
    assert Path(child.config['DATA_DIR']).parent == Path(app.config['DATA_DIR']) / 'spaces'


def test_damaged_child_never_recreates_member_using_parent_password(app):
    import pytest
    create_space(app)
    platform=app.extensions['household_platform']
    household=next(h for h in platform.households() if h['id']!='default')
    child=platform.child(household)
    with sqlite3.connect(Path(child.config['DATA_DIR'])/'household.sqlite3') as con:
        con.execute("DELETE FROM users WHERE id='member1'")
    platform.cache.clear()
    with pytest.raises(RuntimeError,match='MEMBER1_PASSWORD'):
        platform.child(household)
    with sqlite3.connect(Path(child.config['DATA_DIR'])/'household.sqlite3') as con:
        assert con.execute("SELECT count(*) FROM users WHERE id='member1'").fetchone()[0]==0


@pytest.mark.parametrize('clear_cache', [False, True], ids=['cached-child', 'reload-child'])
def test_capacity_enforced_on_child_redemption_and_missing_db_is_recoverable(app, clear_cache):
    app.config['MAX_HOUSEHOLDS']=2
    b,_,result=create_space(app)
    admin,h=member(app)
    invitation=admin.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    b.get(result['entry'])
    value={'invitation':invitation,'name':'Over capacity','slug':'third-home',
           'MEMBER1_PASSWORD':'third-password-one','MEMBER2_PASSWORD':'third-password-two'}
    assert b.post('/api/spaces/redeem',json=value).status_code==409
    platform=app.extensions['household_platform']
    household=next(h for h in platform.households() if h['id']!='default')
    if clear_cache:
        platform.cache.clear()
    # Simulate a missing child database without moving or deleting directories.
    path=Path(app.config['DATA_DIR'])/'spaces'/household['id']/'household.sqlite3'
    path.rename(path.with_suffix('.saved'))
    response=b.get('/api/state')
    assert response.status_code==503 and response.json['recoveryUrl']=='/space/home'
    assert response.headers['Cache-Control']=='no-store'
    assert b.get('/').status_code==503
    assert b.get('/space/home').status_code==303
    assert b.get('/api/spaces/current').json['slug']=='home'


@pytest.mark.parametrize('clear_cache', [False, True], ids=['cached-child', 'reload-child'])
def test_missing_child_db_with_real_session_fails_closed_without_cookie_or_storage_changes(app, clear_cache):
    client, _, result = create_space(app)
    assert client.get(result['entry']).status_code == 303
    client.get('/api/me')
    assert client.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    assert client.get('/api/me').json['user']['id'] == 'member1'
    previous_session = client.get_cookie('session').value
    previous_route = client.get_cookie('household_space').value
    platform = app.extensions['household_platform']
    household = next(h for h in platform.households() if h['id'] != 'default')
    if clear_cache:
        platform.cache.clear()
    path = Path(app.config['DATA_DIR']) / 'spaces' / household['id'] / 'household.sqlite3'
    saved = path.with_suffix('.saved')
    path.rename(saved)
    saved_bytes = saved.read_bytes()

    unavailable = client.get('/api/state')
    assert unavailable.status_code == 503 and unavailable.json['recoveryUrl'] == '/space/home'
    assert not unavailable.headers.getlist('Set-Cookie')
    assert not path.exists()
    response = client.get('/space/home')
    assert response.status_code == 503
    assert response.headers['Cache-Control'] == 'no-store'
    assert not response.headers.getlist('Set-Cookie')
    assert client.get_cookie('session').value == previous_session
    assert client.get_cookie('household_space').value == previous_route
    assert not path.exists() and saved.read_bytes() == saved_bytes
