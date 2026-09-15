"""Isolated databases and fake HTTP only: never publish to any real calendar."""
from copy import deepcopy
import json
import re
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app import create_app
from cloud_accounts import calendar_write_allowed, missing_sync_permissions
from cloud_providers import ProviderError, PUBLICATION_PROPERTY


class Remote:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.created = 0
        self.patched = 0
        self.lose_create = False
        self.lose_patch = False
        self.acl = True
        self.race_patch = False

    def fail(self, code):
        exc = ProviderError('synthetic upstream error', 409 if code in {409, 412} else code)
        exc.upstream_status = code
        raise exc

    def transport(self, method, url, token, body=None, headers=None):
        self.calls.append((method, url, deepcopy(body), deepcopy(headers)))
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        microsoft = parsed.hostname == 'graph.microsoft.com'
        if '/calendarList/' in path:
            return {'accessRole': 'owner' if self.acl else 'reader'}
        if '/events' not in path:
            return {'canEdit': self.acl, 'id': 'calendar-1'}
        base, _, event_id = path.partition('/events')
        event_id = event_id.lstrip('/')
        if method == 'GET' and not event_id:
            query = parse_qs(parsed.query)
            text = query.get('$filter', [''])[0]
            match = re.search(r"'([a-f0-9]{64}):'", text)
            assert match, text
            key = match[1]
            values = [deepcopy(row) for row in self.records.values() if any(p.get('value', '').startswith(key + ':') for p in row.get('singleValueExtendedProperties', []))]
            return {'value': values}
        if method == 'GET':
            if event_id not in self.records:
                self.fail(404)
            return deepcopy(self.records[event_id])
        if method == 'POST':
            assert 'attendees' not in body
            assert not microsoft or 'transactionId' in body
            assert microsoft or parse_qs(parsed.query)['sendUpdates'] == ['none']
            if microsoft:
                existing = next((r for r in self.records.values() if r.get('transactionId') == body['transactionId']), None)
                if existing:
                    return deepcopy(existing)
            elif body['id'] in self.records:
                self.fail(409)
            self.created += 1
            eid = 'ms-' + str(self.created) if microsoft else body['id']
            raw = {**deepcopy(body), 'id': eid, '@odata.etag' if microsoft else 'etag': '"v1"'}
            self.records[eid] = raw
            if self.lose_create:
                self.lose_create = False
                self.fail(502)
            return deepcopy(raw)
        if method == 'PATCH':
            assert 'attendees' not in body
            raw = self.records[event_id]
            etag = '@odata.etag' if microsoft else 'etag'
            if self.race_patch:
                raw[etag] = '"race"'
            if headers.get('If-Match') != raw[etag]:
                self.fail(412)
            raw.update(deepcopy(body))
            self.patched += 1
            raw[etag] = '"v' + str(self.patched + 1) + '"'
            if self.lose_patch:
                self.lose_patch = False
                self.fail(502)
            return deepcopy(raw)
        raise AssertionError((method, url))


@pytest.fixture(params=['google', 'microsoft'])
def env(tmp_path, request):
    provider = request.param
    remote = Remote()
    cfg = {'TESTING':True, 'SECRET_KEY':'calendar-publication-test', 'DATA_DIR':str(tmp_path),
           'SESSION_COOKIE_SECURE':False, 'PUBLIC_ORIGIN':'http://localhost',
           'MEMBER1_PASSWORD':'testing-password-one', 'MEMBER2_PASSWORD':'testing-password-two',
           'GOOGLE_CLIENT_ID':'test-google-client', 'GOOGLE_CLIENT_SECRET':'test-google-secret',
           'MICROSOFT_CLIENT_ID':'test-ms-client', 'MICROSOFT_CLIENT_SECRET':'test-ms-secret',
           'CLOUD_TRANSPORT':remote.transport}
    app = create_app(cfg)
    engine = app.extensions['cloud_accounts']
    scope = 'User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider == 'microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks'
    client_id = cfg[provider.upper()+'_CLIENT_ID']
    tokens = engine.encrypt({'access_token':'synthetic-token','refresh_token':'synthetic-refresh','scope':scope,'expires_at':time.time()+3600})
    event={'title':'Synthetic journey','location':'Synthetic city','note':'Test only','start':'2026-10-01T00:00:00+08:00','end':'2026-10-04T00:00:00+08:00','allDay':True,'owner':'shared'}
    with engine.db() as con:
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)', ('account-1','member1',provider,client_id,'subject-1','Synthetic','test@example.test',tokens))
        con.execute('INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner) VALUES(?,?,?,?,?,?)', ('source-1','account-1','calendar-1','calendar','Synthetic Calendar','member1'))
        con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)', ('trip-1','trips','{}','now'))
        con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)', ('event-1','events',json.dumps(event),'now'))
        con.execute('INSERT INTO journey_workflows(id,trip_id,plan,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)', ('journey-1','trip-1','{}','member1','now','now'))
        con.execute('INSERT INTO journey_links VALUES(?,?,?,?)', ('journey-1','event:overview','event-1','events'))
    client = app.test_client()
    assert client.post('/api/login',json={'username':'member1','password':'testing-password-one'}).status_code == 200
    headers = {'X-CSRF-Token':client.get('/api/me').json['csrf']}
    return app, client, headers, remote, provider


def queue(env):
    app,client,headers,remote,provider=env
    payload={'journeyId':'journey-1','sourceId':'source-1'}
    p=client.post('/api/calendar-publish/preview',json=payload,headers=headers)
    assert p.status_code==200,p.json
    result=client.post('/api/calendar-publish/confirm',json={**payload,'previewToken':p.json['previewToken']},headers=headers)
    assert result.status_code==200,result.json
    return result.json['publicationIds'][0]


def publication(env):
    return env[1].get('/api/calendar-publish/journeys/journey-1').json['publications'][0]


def update_local(app, title='Updated local'):
    with app.extensions['cloud_accounts'].db() as con:
        value=json.loads(con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0])
        value['title']=title
        con.execute("UPDATE entities SET data=?,revision=revision+1 WHERE id='event-1'",(json.dumps(value),))
        con.execute('UPDATE calendar_publications SET next_attempt=0')


def test_preview_no_queue_or_remote_calls_and_idempotent_confirm(env):
    app,client,headers,remote,provider=env
    r=client.post('/api/calendar-publish/preview',json={'journeyId':'journey-1','sourceId':'source-1'},headers=headers)
    assert r.status_code==200
    assert not remote.calls
    with app.extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0]==0
    rid=queue(env)
    assert queue(env)==rid
    app.extensions['calendar_publish'].tick()
    assert publication(env)['status']=='published'
    assert remote.created==1
    assert remote.patched==0
    with app.extensions['cloud_accounts'].db() as con:
        row=con.execute('SELECT * FROM calendar_publications').fetchone()
        assert row['remote_id'] and row['etag'] and row['last_hash'] and not row['pending_data']
    app.extensions['calendar_publish'].process(rid)
    assert remote.created==1


def test_uncertain_create_and_update_recover_without_duplicates(env):
    app,client,headers,remote,provider=env
    rid=queue(env)
    remote.lose_create=True
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='retry'
    assert remote.created==1
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='published'
    assert remote.created==1
    update_local(app)
    remote.lose_patch=True
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='retry'
    assert remote.patched==1
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='published'
    assert remote.patched==1
    assert any(call[0]=='PATCH' and call[3].get('If-Match') for call in remote.calls)


def test_unchanged_local_never_writes_and_live_revision_updates(env):
    app,client,headers,remote,provider=env
    rid=queue(env)
    app.extensions['calendar_publish'].process(rid)
    calls=len(remote.calls)
    app.extensions['calendar_publish'].process(rid)
    assert len(remote.calls)>calls
    assert not any(call[0] in {'POST','PATCH','DELETE'} for call in remote.calls[calls:])
    update_local(app)
    app.extensions['calendar_publish'].process(rid)
    assert remote.patched==1
    assert publication(env)['localRevision']==2


def test_scopes_missing_preserves_read_binding_and_no_remote_write(env):
    app,client,headers,remote,provider=env
    engine=app.extensions['cloud_accounts']
    with engine.db() as con:
        account=con.execute('SELECT * FROM cloud_accounts').fetchone()
        tokens=engine.decrypt(account['tokens'])
        tokens['scope']='User.Read Calendars.Read Tasks.ReadWrite' if provider=='microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks'
        con.execute('UPDATE cloud_accounts SET tokens=?',(engine.encrypt(tokens),))
    rid=queue(env)
    assert publication(env)['status']=='needs_authorization'
    app.extensions['calendar_publish'].process(rid)
    assert not remote.calls
    assert not engine.account('account-1')['needs_reauth']
    url=client.post('/api/calendar-publish/authorize',json={'accountId':'account-1'},headers=headers).json['url']
    scope=parse_qs(urlsplit(url).query)['scope'][0]
    assert calendar_write_allowed(provider,scope)
    default=client.post('/api/accounts/bind',json={'provider':provider},headers=headers).json['url']
    assert not calendar_write_allowed(provider,parse_qs(urlsplit(default).query)['scope'][0])


def test_member_ownership_csrf_and_tv_block(env):
    app,client,headers,remote,provider=env
    rid=queue(env)
    other=app.test_client()
    other.post('/api/login',json={'username':'member2','password':'testing-password-two'})
    h={'X-CSRF-Token':other.get('/api/me').json['csrf']}
    state=other.get('/api/calendar-publish/journeys/journey-1').json
    assert state['sources']==[] and state['publications']==[]
    assert other.post('/api/calendar-publish/authorize',json={'accountId':'account-1'},headers=h).status_code==404
    assert other.post('/api/calendar-publish/preview',json={'journeyId':'journey-1','sourceId':'source-1'},headers=h).status_code==404
    for action in ['retry','pause','resume','conflict-preview','conflict-confirm']:
        assert other.post('/api/calendar-publish/publications/'+rid+'/'+action,json={},headers=h).status_code in {400,404}
    assert client.post('/api/calendar-publish/preview',json={}).status_code==403
    assert client.get('/api/calendar-publish/journeys/journey-1',headers={'X-Display-Mode':'tv'}).status_code==401
    assert not remote.calls


def test_stale_preview_cannot_queue_changed_plan(env):
    app,client,headers,remote,provider=env
    data={'journeyId':'journey-1','sourceId':'source-1'}
    p=client.post('/api/calendar-publish/preview',json=data,headers=headers).json
    update_local(app)
    r=client.post('/api/calendar-publish/confirm',json={**data,'previewToken':p['previewToken']},headers=headers)
    assert r.status_code==409
    assert not remote.calls


def test_conflict_stops_overwrite_and_explicit_resolution_is_conditional(env):
    app,client,headers,remote,provider=env
    rid=queue(env)
    app.extensions['calendar_publish'].process(rid)
    raw=next(iter(remote.records.values()))
    etag='@odata.etag' if provider=='microsoft' else 'etag'
    title='subject' if provider=='microsoft' else 'summary'
    raw[etag]='"external"';raw[title]='Changed in calendar'
    update_local(app)
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='conflict' and remote.patched==0
    assert client.post('/api/calendar-publish/publications/'+rid+'/retry',json={},headers=headers).status_code==409
    p=client.post('/api/calendar-publish/publications/'+rid+'/conflict-preview',json={},headers=headers)
    assert p.status_code==200,p.json
    assert p.json['remote']['title']=='Changed in calendar'
    assert p.json['local']['title']=='Updated local'
    confirm=client.post('/api/calendar-publish/publications/'+rid+'/conflict-confirm',json={'previewToken':p.json['previewToken']},headers=headers)
    assert confirm.status_code==200
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='published' and remote.patched==1
    assert raw[title]=='Updated local'


def test_race_after_conflict_preview_still_prevents_overwrite(env):
    app,client,headers,remote,provider=env
    rid=queue(env);app.extensions['calendar_publish'].process(rid)
    raw=next(iter(remote.records.values()))
    etag='@odata.etag' if provider=='microsoft' else 'etag'
    raw[etag]='"external"'
    update_local(app)
    app.extensions['calendar_publish'].process(rid)
    p=client.post('/api/calendar-publish/publications/'+rid+'/conflict-preview',json={},headers=headers).json
    raw[etag]='"changed-after-preview"'
    client.post('/api/calendar-publish/publications/'+rid+'/conflict-confirm',json={'previewToken':p['previewToken']},headers=headers)
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='conflict' and remote.patched==0


def test_patch_if_match_race_and_attendees_never_invite(env):
    app,client,headers,remote,provider=env
    rid=queue(env);app.extensions['calendar_publish'].process(rid)
    update_local(app)
    remote.race_patch=True
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='conflict' and remote.patched==0
    raw=next(iter(remote.records.values()));raw['attendees']=[{'email':'synthetic@example.test'}]
    assert client.post('/api/calendar-publish/publications/'+rid+'/conflict-preview',json={},headers=headers).status_code==409
    assert remote.patched==0


def test_pause_resume_and_local_delete_preserve_remote(env):
    app,client,headers,remote,provider=env
    rid=queue(env);app.extensions['calendar_publish'].process(rid)
    assert client.post('/api/calendar-publish/publications/'+rid+'/pause',json={},headers=headers).status_code==200
    update_local(app)
    app.extensions['calendar_publish'].process(rid)
    assert remote.patched==0
    assert client.post('/api/calendar-publish/publications/'+rid+'/resume',json={},headers=headers).status_code==200
    app.extensions['calendar_publish'].process(rid)
    assert remote.patched==1 and publication(env)['status']=='published'
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("DELETE FROM entities WHERE id='event-1'")
    app.extensions['calendar_publish'].process(rid)
    with app.extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT status FROM calendar_publications').fetchone()[0]=='local_deleted'
    assert len(remote.records)==1 and not any(c[0]=='DELETE' for c in remote.calls)


def test_polling_does_not_duplicate_published_journey_or_replace_metadata(env):
    app,client,headers,remote,provider=env
    rid=queue(env);app.extensions['calendar_publish'].process(rid)
    engine=app.extensions['cloud_accounts']
    raw=next(iter(remote.records.values()))
    adapter=engine.provider(provider,'synthetic-token')
    record=adapter._event(raw)
    with engine.db() as con:
        source=con.execute('SELECT * FROM cloud_sources').fetchone()
        original=con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0]
        entity_id,changed=engine.save_record(con,source,engine.account('account-1'),record)
        assert entity_id=='event-1' and not changed
        assert con.execute('SELECT count(*) FROM cloud_items').fetchone()[0]==0
        assert con.execute("SELECT data FROM entities WHERE id='event-1'").fetchone()[0]==original
    record['version']='"remote-change"'
    with engine.db() as con:
        engine.save_record(con,source,engine.account('account-1'),record)
    assert publication(env)['status']=='conflict'


def test_calendar_acl_failure_and_bound_input(env):
    app,client,headers,remote,provider=env
    rid=queue(env);remote.acl=False;app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='permission_denied' and remote.created==0
    assert client.post('/api/calendar-publish/preview',json={'journeyId':[],'sourceId':'source-1'},headers=headers).status_code==400
    assert client.post('/api/calendar-publish/authorize',json={'accountId':{}},headers=headers).status_code==400


def test_remote_deletion_or_edit_detected_without_local_change(env):
    app,client,headers,remote,provider=env
    rid=queue(env);app.extensions['calendar_publish'].process(rid)
    raw=next(iter(remote.records.values()))
    raw['@odata.etag' if provider=='microsoft' else 'etag']='"remote-edit-without-local-change"'
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='conflict' and remote.created==1 and remote.patched==0
    with app.extensions['cloud_accounts'].db() as con:
        con.execute("UPDATE calendar_publications SET status='published'")
    remote.records.clear()
    app.extensions['calendar_publish'].process(rid)
    assert publication(env)['status']=='conflict' and remote.created==1


def test_write_scopes_are_supersets_of_baseline_permissions():
    assert not missing_sync_permissions('microsoft','User.Read Calendars.ReadWrite Tasks.ReadWrite')
    assert not missing_sync_permissions('microsoft','User.Read https://graph.microsoft.com/Calendars.ReadWrite.Shared Tasks.ReadWrite')
    assert not missing_sync_permissions('google','https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/tasks')
    assert not calendar_write_allowed('microsoft','Calendars.Read Calendars.Read.Shared')
    assert not calendar_write_allowed('google','https://www.googleapis.com/auth/calendar.readonly')


def test_upgrade_callback_uses_same_identity_and_preserves_read_account_on_denial(env):
    app,client,headers,remote,provider=env
    engine=app.extensions['cloud_accounts']
    original=engine.account('account-1')['tokens']
    write_scope='User.Read Calendars.ReadWrite Tasks.ReadWrite' if provider=='microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks'
    def begin():
        r=client.post('/api/calendar-publish/authorize',json={'accountId':'account-1'},headers=headers)
        assert r.status_code==200
        return parse_qs(urlsplit(r.json['url']).query)['state'][0]
    def finish(state):
        return client.get('/auth/'+provider+'/callback',query_string={'state':state,'code':'synthetic-upgrade'})
    app.config['OAUTH_TRANSPORT']=lambda name,params:{'access_token':'upgraded','refresh_token':'upgraded-refresh','scope':write_scope,'expires_in':3600}
    app.config['CLOUD_PROVIDER_FACTORY']=lambda name,token,transport=None:SimpleNamespace(identity=lambda:{'subject':'different-account','name':'Other','email':''})
    r=finish(begin())
    assert 'auth=error' in r.location
    assert engine.account('account-1')['tokens']==original
    app.config['CLOUD_PROVIDER_FACTORY']=lambda name,token,transport=None:SimpleNamespace(identity=lambda:{'subject':'subject-1','name':'Synthetic','email':''})
    app.config['OAUTH_TRANSPORT']=lambda name,params:{'access_token':'no-grant','refresh_token':'no-grant-refresh','scope':'User.Read Calendars.Read Tasks.ReadWrite' if name=='microsoft' else 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/tasks','expires_in':3600}
    r=finish(begin())
    assert 'insufficient_permissions' in r.location
    assert engine.account('account-1')['tokens']==original
    app.config['OAUTH_TRANSPORT']=lambda name,params:{'access_token':'upgraded','refresh_token':'upgraded-refresh','scope':write_scope,'expires_in':3600}
    r=finish(begin())
    assert r.location.endswith('/?auth=connected')
    assert calendar_write_allowed(provider,engine.decrypt(engine.account('account-1')['tokens'])['scope'])
