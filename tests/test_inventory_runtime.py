"""Actual factory/household registration and packaging; synthetic local data only."""
from pathlib import Path
import socket
import tarfile

from flask import g, request
import pytest

from app import create_app
from deploy.prepare_release import prepare
import inventory_core
from test_inventory_api import create, acquisition, move, rid, P
from test_journey_documents import PASSWORD, clone, connection, login


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Runtime checks must not use external services')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True, 'DATA_DIR':str(tmp_path/'home'),
        'SECRET_KEY':'synthetic-inventory-runtime-secret', 'SESSION_COOKIE_SECURE':False,
        'MEMBER1_PASSWORD':PASSWORD, 'MEMBER2_PASSWORD':PASSWORD,
        'PUBLIC_ORIGIN':'http://localhost', 'GOOGLE_CLIENT_ID':'', 'GOOGLE_CLIENT_SECRET':'',
        'MICROSOFT_CLIENT_ID':'', 'MICROSOFT_CLIENT_SECRET':'',
        'OPENAI_API_KEY':'', 'OPENAI_MODEL':'', 'NVIDIA_API_KEY':'', 'NVIDIA_MODEL':''})


def tables(app):
    with connection(app) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_real_factory_has_exact_schema_and_one_registration(app):
    assert len(tables(app)) == 53
    assert {t for t in tables(app) if t.startswith('inventory_')} == set(inventory_core.LIMITS)
    assert {'inventory', 'household_media', 'media_playback'} <= app.extensions.keys()
    routes = [(method, r.rule) for r in app.url_map.iter_rules()
              if r.rule.startswith(P+'/') for method in r.methods-{'HEAD','OPTIONS'}]
    assert len(routes) == len(set(routes)) == 13
    with app.extensions['household_platform'].db() as con:
        assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")} == {'households','household_invitations'}


def test_inventory_uses_same_request_database_and_restart_keeps_receipt(app):
    observed = []
    @app.before_request
    def observe():
        if request.path.startswith(P):
            observed.append(app.extensions['inventory'].db() is g.db)
    c,h = login(app)
    result,_ = create(c,h)
    current,_ = acquisition(c,h,result['item'])
    current,payload = move(c,h,current,quantity=2)
    restarted = create_app(dict(app.config))
    resumed = clone(restarted,c)
    replay = resumed.post(P+'/acquisitions/'+current['acquisition']['id']+'/movements',json=payload,headers=h)
    assert replay.status_code == 200 and replay.json['operation']['replayed']
    assert replay.json['item']['onHandQty'] == 2
    assert observed and all(observed)
    assert len(tables(restarted)) == 53
    with connection(restarted) as con:
        assert con.execute('SELECT count(*) FROM inventory_movements').fetchone()[0] == 1
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []


def test_real_child_factory_four_members_and_wsgi_isolation(app):
    c,h = login(app)
    first,_ = create(c,h,visibility='shared')
    invite = c.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    response = app.test_client().post('/api/spaces/redeem',json={'invitation':invite,
        'name':'合成库存第二户','slug':'inventory-child',
        'MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert response.status_code == 201,response.json
    platform = app.extensions['household_platform']
    household = next(v for v in platform.households() if v['slug']=='inventory-child')
    child = platform.child(household)
    assert 'inventory' in child.extensions and len(tables(child)) == 53
    assert child.secret_key != app.secret_key
    second,sh = login(child)
    other,_ = create(second,sh,visibility='shared')
    for application,own,foreign in ((app,first,other),(child,other,first)):
        peer,_ = login(application,2)
        assert peer.get(P+'/items').json['total'] == 1
        assert peer.get(P+'/items/'+own['item']['id']).status_code == 200
        assert peer.get(P+'/items/'+foreign['item']['id']).status_code == 404
    routed = app.test_client()
    routed.set_cookie('household_space',platform.signer.dumps(household['id']))
    routed,_ = login(app,client=routed)
    assert routed.get('/api/me').json['user']['householdId'] == household['id']
    assert routed.get(P+'/items/'+other['item']['id']).status_code == 200
    assert routed.get(P+'/items/'+first['item']['id']).status_code == 404


def test_factory_auth_csrf_tv_and_shared_withdrawal(app):
    c,h = login(app)
    peer,_ = login(app,2)
    result,_ = create(c,h)
    path = P+'/items/'+result['item']['id']
    assert peer.get(path).status_code == 404
    shared = c.patch(path,json={'requestId':rid(),'revision':1,'patch':{'visibility':'shared'}},headers=h)
    assert shared.status_code == 200
    assert peer.get(path).status_code == 200
    private = c.patch(path,json={'requestId':rid(),'revision':2,'patch':{'visibility':'private'}},headers=h)
    assert private.status_code == 200 and peer.get(path).status_code == 404
    assert app.test_client().get(P+'/items').status_code == 401
    assert c.post(P+'/items',json={'requestId':rid(),'data':{'title':'合成','unit':'件'}}).status_code == 403
    tv = app.test_client()
    pair = tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'合成只读屏'},headers=h).status_code == 200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    assert tv.get(P+'/items').status_code == 403
    assert tv.get('/api/media-tv/playback').status_code == 200
    assert c.get('/api/media/items').status_code == 200
    assert 'inventory' not in tv.get('/api/state').json
    assert c.post('/api/logout',json={},headers=h).status_code == 200
    assert c.get(path).status_code == 401


def test_factory_rejects_inventory_schema_drift(app):
    with connection(app) as con:
        con.execute('DROP INDEX inventory_sources_line')
    with pytest.raises(inventory_core.InventoryError) as caught:
        create_app(dict(app.config))
    assert caught.value.code == 'schema'


def test_real_source_archive_contains_runtime_and_static_assets(tmp_path):
    root = Path(__file__).resolve().parents[1]
    required = {'inventory_core.py','inventory_api.py','static/inventory-ui.js','static/inventory-ui.css'}
    release = prepare(root,access=tmp_path/'release')
    with tarfile.open(release['archive']) as archive:
        assert required <= set(archive.getnames())
        for name in required:
            assert archive.extractfile(name).read() == (root/name).read_bytes()
    docker = (root/'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY inventory_core.py inventory_api.py ./' in docker
    html = (root/'static/index.html').read_text(encoding='utf-8')
    assert html.count('src="/static/inventory-ui.js"') == 1
    assert html.index('src="/static/inventory-ui.js"') < html.index('src="/static/product-shell.js"')
    assert 'href="/static/inventory-ui.css"' in html
