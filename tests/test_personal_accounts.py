"""Real temporary platform/household SQLite and Flask cookies; no business reply mocks."""
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time

from flask import jsonify, request
import pytest
from werkzeug.security import check_password_hash

import personal_accounts as personal
from personal_accounts import PersonalAccounts, PersonalAccountError, digest, init_schema
from test_app import app, member
from test_household_spaces import create_space


@pytest.fixture(scope='session')
def domain():
    root=Path(os.environ.get('PERSONAL_ACCOUNTS_DOMAIN_ROOT',Path(__file__).resolve().parents[1])).resolve()
    path=root/'household_memberships.py'
    spec=importlib.util.spec_from_file_location('personal_test_membership_domain',path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(app,domain,monkeypatch):
    _,_,second=create_space(app)
    platform=app.extensions['household_platform']
    @contextmanager
    def household(uid):
        path=Path(app.config['DATA_DIR'])/('household.sqlite3' if uid=='default' else f'spaces/{uid}/household.sqlite3')
        con=sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)
        con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON')
        try:yield con
        finally:con.rollback();con.close()
    for item in platform.households():
        with household(item['id']) as con:
            con.execute('BEGIN IMMEDIATE');domain.schema_initialize(con);con.commit()
    def selected():
        raw=request.cookies.get('household_space')
        uid=platform.signer.loads(raw) if raw else 'default'
        item=next(h for h in platform.households() if h['id']==uid)
        return uid,platform.child(item)
    def check_member(con,target,proof=None,password=None):
        sessions=target.extensions['member_sessions']
        try:row=sessions.current(con)
        except sessions.Problem as exc:
            raise PersonalAccountError(str(exc.args[0]),exc.args[1]) from None
        signed=sessions.request_signed()[0]
        header='X-Member-CSRF-Token' if request.path.startswith('/api/account/') else 'X-CSRF-Token'
        if proof is None and request.headers.get(header)!=signed['csrf']:
            raise PersonalAccountError('成员CSRF不匹配',403)
        uid=target.config.get('HOUSEHOLD_INFO',{}).get('id','default')
        active=domain.active_member(con,row['owner'])
        if not active:raise PersonalAccountError('成员已停用',401)
        result={'householdId':uid,'memberId':row['owner'],'authVersion':row['auth_version'],
                'sessionId':row['id'],'membershipRevision':active['membershipRevision']}
        if proof is not None and result!=proof:raise PersonalAccountError('原成员会话已变化',401)
        if password is not None:
            stored=con.execute('SELECT password FROM users WHERE id=?',(row['owner'],)).fetchone()[0]
            if not check_password_hash(stored,password):raise PersonalAccountError('家庭密码不正确',401)
        return result
    def member_proof(pcon,password):
        uid,target=selected()
        with household(uid) as con:
            con.execute('BEGIN');return check_member(con,target,password=password)
    def validate_member_proof(pcon,proof,household_con=None):
        uid,target=selected()
        if uid!=proof['householdId']:raise PersonalAccountError('家庭已变化',401)
        if household_con is not None:return check_member(household_con,target,proof)
        with household(uid) as con:
            con.execute('BEGIN');return check_member(con,target,proof)
    installed=[]
    def install_member(pcon,hcon,identity,summary):
        # Actual local session row is created by the existing session engine;
        # its future Root live() projection is validated here via engine.current.
        target=platform.child(next(h for h in platform.households() if h['id']==summary['householdId']))
        sessions=target.extensions['member_sessions'];token=secrets.token_urlsafe(32);now=time.time()
        key=sessions.ensure_browser(hcon,token,now)
        generation=hcon.execute('SELECT generation FROM member_session_browsers WHERE browser_hash=?',(key,)).fetchone()[0]
        context={'browserHash':key,'generation':generation,'credentialHash':None,'owner':None,'av':None}
        user=hcon.execute('SELECT * FROM users WHERE id=?',(summary['memberId'],)).fetchone()
        value=sessions.complete_login(hcon,user,context,token)
        value['personal']=engine.identity_dict(identity)
        signed=target.session_interface.get_signing_serializer(target).dumps(value)
        installed.append(value)
        def apply(response):
            response.set_cookie('session',signed,httponly=True,samesite='Lax')
            response.set_cookie('household_space',platform.signer.dumps(summary['householdId']),httponly=True)
            return response
        return apply
    engine=PersonalAccounts(platform,{'membership':domain,'household':household,'member_proof':member_proof,
        'validate_member_proof':validate_member_proof,'install_member':install_member,
        'is_tv':lambda:request.headers.get('X-Display-Mode')=='tv'})
    # All actual member-session connections must share this fixture's platform guard.
    monkeypatch.setattr(platform,'personal_accounts',engine)
    engine.app.config['TESTING']=True
    engine.app.add_url_rule('/api/membership-links','test_bind',lambda:jsonify(engine.handle_bind(
        engine._body({'requestId','memberPassword','expectedAuthVersion','expectedRevision'}))),methods=['POST'])
    engine.app.add_url_rule('/api/memberships/self/leave','test_leave',lambda:jsonify(engine.handle_leave(
        engine._body({'requestId','expectedAuthVersion','expectedRevision'}))),methods=['POST'])
    original=app.wsgi_app
    app.wsgi_app=lambda e,s:engine.app.wsgi_app(e,s) if e['PATH_INFO'].startswith('/api/account/') or e['PATH_INFO'] in ('/api/membership-links','/api/memberships/self/leave') else original(e,s)
    return app,engine,domain,household,installed


def bootstrap(client):
    response=client.get('/api/account/me');assert response.status_code==200,response.json
    return response.json,{'X-CSRF-Token':response.json['csrf']}


def registered(env,number=1,login=None):
    app,engine,domain,household,_=env;client,mh=member(app,number)
    _,ah=bootstrap(client)
    q=client.post('/api/account/eligibility',json={'memberPassword':'testing-password-'+('one' if number==1 else 'two')},
                  headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']})
    assert q.status_code==200,q.json
    body={'requestId':secrets.token_hex(16),'login':login or f'account{number}','password':'synthetic-personal-password',
          'eligibilityToken':q.json['eligibilityToken']}
    response=client.post('/api/account/register',json=body,headers=ah);assert response.status_code==201,response.json
    account=response.json['account'];me,ah=bootstrap(client)
    return client,mh,ah,account,body


def bind(env,client,mh,ah,number=1):
    with env[3]('default') as con:
        item=env[2].active_member(con,'member'+str(number))
    body={'requestId':secrets.token_hex(16),'memberPassword':'testing-password-'+('one' if number==1 else 'two'),
          'expectedAuthVersion':item['authVersion'],'expectedRevision':item['membershipRevision']}
    response=client.post('/api/membership-links',json=body,
                         headers={**mh,'X-Account-CSRF-Token':ah['X-CSRF-Token']})
    assert response.status_code==200,response.json
    return response.json,body


def invite(env,household_id='default'):
    with env[3](household_id) as con:
        con.execute('BEGIN IMMEDIATE')
        # Same actual domain function used by the forthcoming Root admin route.
        result=env[2].create_invitation(con,household_id=household_id,actor_member_id='member1',
            expected_auth_version=1,request_id=secrets.token_hex(16),intent_digest='a'*64)
        con.commit();return result


def inspect(client,ah,token,slug='home'):
    r=client.post('/api/account/invitations/inspect',json={'householdSlug':slug,'token':token},headers=ah)
    assert r.status_code==200,r.json
    return r.json


def counts(engine):
    with engine.connection() as con:
        return {name:con.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in sorted(personal.TABLES)}


def test_schema_no_reset_and_partial_refused(env):
    _,engine,_,_,_=env;registered(env)
    with engine.connection() as con:
        before=list(map(tuple,con.execute('SELECT * FROM personal_accounts')));init_schema(con)
        assert list(map(tuple,con.execute('SELECT * FROM personal_accounts')))==before
        con.execute('DROP TABLE personal_limits');con.commit()
        with pytest.raises(PersonalAccountError,match='不完整'):init_schema(con)
        assert 'personal_limits' not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_schema_marker_rejects_all_personal_tables_missing(env):
    with env[1].connection() as con:
        old=[tuple(r) for r in con.execute('SELECT * FROM households ORDER BY id')]
        assert con.execute('PRAGMA user_version').fetchone()[0]==1
        con.execute('PRAGMA foreign_keys=OFF')
        for name in personal.TABLES:con.execute('DROP TABLE '+name)
        con.commit()
        with pytest.raises(PersonalAccountError,match='不完整'):init_schema(con)
        assert [tuple(r) for r in con.execute('SELECT * FROM households ORDER BY id')]==old
        assert not personal.TABLES & {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_register_preserves_household_passwords_owners_and_roles(env):
    with env[3]('default') as con:before=[tuple(r) for r in con.execute('SELECT * FROM users ORDER BY id')]
    client,mh,ah,account,body=registered(env)
    with env[3]('default') as con:
        assert [tuple(r) for r in con.execute('SELECT * FROM users ORDER BY id')]==before
        assert con.execute('SELECT count(*) FROM household_memberships WHERE account_id IS NOT NULL').fetchone()[0]==0
    assert client.get('/api/account/households').json=={'memberships':[],'unavailable':[]}
    with env[1].connection() as con:
        assert 'synthetic-personal-password' not in '\n'.join(con.iterdump())
        assert body['eligibilityToken'] not in '\n'.join(con.iterdump())
    assert client.get('/api/private-finance').status_code==200


def test_register_lost_reply_is_receipt_not_new_auth(env):
    app,engine,*_=env;c,mh=member(app);_,ah=bootstrap(c)
    q=c.post('/api/account/eligibility',json={'memberPassword':'testing-password-one'},
             headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).json
    old=c.get_cookie(engine.COOKIE).value
    body={'requestId':secrets.token_hex(16),'login':'lost.reply','password':'synthetic-personal-password','eligibilityToken':q['eligibilityToken']}
    actual=c.post('/api/account/register',json=body,headers=ah);assert actual.status_code==201
    c.set_cookie(engine.COOKIE,old)
    found=c.get('/api/account/operations/'+body['requestId']);assert found.json['state']=='completed' and found.json['result']==actual.json
    replay=c.post('/api/account/register',json=body,headers=ah)
    assert replay.status_code==200 and replay.json==actual.json and not replay.headers.getlist('Set-Cookie')
    assert counts(engine)['personal_accounts']==1
    assert c.post('/api/account/register',json={**body,'password':'different-password'},headers=ah).status_code==409
    _,fresh=bootstrap(c)
    assert c.post('/api/account/login',json={'login':body['login'],'password':body['password']},headers=fresh).status_code==200
    assert c.get('/api/account/operations/'+body['requestId']).json['result']==actual.json


@pytest.mark.parametrize('bad', ['missing_csrf','member_csrf','cross_origin','wrong_password','tv'])
def test_eligibility_two_independent_csrf_and_identity(env,bad):
    c,mh=member(env[0]);_,ah=bootstrap(c);headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']};password='testing-password-one'
    if bad=='missing_csrf':headers.pop('X-CSRF-Token')
    if bad=='member_csrf':headers['X-Member-CSRF-Token']=ah['X-CSRF-Token']
    if bad=='cross_origin':headers['Origin']='https://other.invalid'
    if bad=='wrong_password':password='incorrect-password'
    if bad=='tv':headers['X-Display-Mode']='tv'
    assert c.post('/api/account/eligibility',json={'memberPassword':password},headers=headers).status_code in (401,403)
    assert counts(env[1])['account_qualifications']==0


@pytest.mark.parametrize('body', ['{"login":"one","login":"two","password":"synthetic-password"}', '[]', '{"login":"ok.name","password":true}', '{"login":"ok.name","password":"synthetic-password","owner":"member1"}'])
def test_strict_body_fail_closed(env,body):
    c=env[0].test_client();_,h=bootstrap(c)
    assert c.post('/api/account/login',data=body,content_type='application/json',headers=h).status_code==400
    assert counts(env[1])['personal_accounts']==0


def test_login_logout_rotation_and_other_browser(env):
    c,mh,ah,account,_=registered(env);engine=env[1]
    first=engine.capture(c.get_cookie(engine.COOKIE).value)
    other=env[0].test_client();_,oh=bootstrap(other)
    assert other.post('/api/account/login',json={'login':account['login'],'password':'synthetic-personal-password'},headers=oh).status_code==200
    independent=engine.capture(other.get_cookie(engine.COOKIE).value)
    assert c.post('/api/account/login',json={'login':account['login'],'password':'synthetic-personal-password'},headers=ah).status_code==200
    me,ah=bootstrap(c);assert me['authenticationGeneration']==first.generation+1
    with engine.guard() as con:
        with pytest.raises(PersonalAccountError):engine.current(con,first)
        assert engine.current(con,independent)['accountId']==account['id']
    local_cookie=c.get_cookie('session').value
    assert c.post('/api/account/logout',json={'requestId':secrets.token_hex(16)},headers=ah).status_code==200
    assert c.get_cookie('session').value==local_cookie and c.get('/api/private-finance').status_code==200
    assert c.get('/api/account/me').json['account'] is None
    assert other.get('/api/account/me').json['account']==account


@pytest.mark.parametrize('change',['expire','revoke','auth_version','browser_generation'])
def test_actual_sqlite_changes_invalidate_captured_session(env,change):
    c,_,_,_,_=registered(env);engine=env[1];identity=engine.capture(c.get_cookie(engine.COOKIE).value)
    with engine.connection() as writer:
        if change=='expire':writer.execute('UPDATE personal_sessions SET expires_at=?',(time.time()-1,))
        elif change=='revoke':writer.execute('UPDATE personal_sessions SET revoked_at=?',(time.time(),))
        elif change=='auth_version':writer.execute('UPDATE personal_accounts SET auth_version=auth_version+1')
        else:writer.execute('UPDATE personal_browsers SET generation=generation+1')
        writer.commit()
    with engine.guard() as con:
        with pytest.raises(PersonalAccountError):engine.current(con,engine.identity_dict(identity),require=True)
    assert c.get('/api/account/households').status_code==401


def test_expired_qualification_and_revoked_original_member(env):
    c,mh=member(env[0]);_,ah=bootstrap(c)
    q=c.post('/api/account/eligibility',json={'memberPassword':'testing-password-one'},headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).json
    body={'requestId':secrets.token_hex(16),'login':'expired','password':'synthetic-password','eligibilityToken':q['eligibilityToken']}
    with env[1].connection() as con:con.execute('UPDATE account_qualifications SET expires_at=?',(time.time()-1,));con.commit()
    assert c.post('/api/account/register',json=body,headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).status_code==409
    q=c.post('/api/account/eligibility',json={'memberPassword':'testing-password-one'},headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).json
    with env[3]('default') as con:con.execute("UPDATE member_sessions SET revoked_at=? WHERE owner='member1'",(time.time(),));con.commit()
    body['eligibilityToken']=q['eligibilityToken']
    assert c.post('/api/account/register',json=body,headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).status_code==401
    assert counts(env[1])['personal_accounts']==0


def test_bind_keeps_owner_roles_and_personal_generation(env):
    c,mh,ah,account,_=registered(env);before=c.get('/api/account/me').json
    summary,_=bind(env,c,mh,ah)
    assert summary['memberId']=='member1' and summary['householdRole']=='admin'
    assert c.get('/api/account/me').json==before
    directory=c.get('/api/account/households').json
    assert directory['memberships'][0]['id']==summary['id'] and directory['memberships'][0]['householdId']=='default'
    other,_,_,_,_=registered(env,2)
    assert other.get('/api/account/households').json['memberships']==[]
    assert other.post('/api/account/switch-household',json={'requestId':secrets.token_hex(16),'membershipId':summary['id'],'expectedRevision':summary['revision']},headers={'X-CSRF-Token':other.get('/api/account/me').json['csrf']}).status_code==404


def test_bind_requires_recent_independent_personal_password(env):
    c,mh,ah,_,_=registered(env)
    with env[1].connection() as con:con.execute('UPDATE personal_sessions SET verified_at=?',(time.time()-301,));con.commit()
    with env[3]('default') as con:item=env[2].active_member(con,'member1')
    response=c.post('/api/membership-links',json={'requestId':secrets.token_hex(16),'memberPassword':'testing-password-one',
        'expectedAuthVersion':item['authVersion'],'expectedRevision':item['membershipRevision']},headers={**mh,'X-Account-CSRF-Token':ah['X-CSRF-Token']})
    assert response.status_code==401


def test_invitation_registration_requires_new_account_bound_ticket(env):
    invitation=invite(env);c=env[0].test_client();_,ah=bootstrap(c)
    old=inspect(c,ah,invitation['token'])
    assert set(old)=={'household','householdRole','joinTicket','eligibilityToken','expiresAt'} and set(old['household'])=={'id','name','slug'}
    body={'requestId':secrets.token_hex(16),'login':'new.person','password':'synthetic-password','eligibilityToken':old['eligibilityToken']}
    assert c.post('/api/account/register',json=body,headers=ah).status_code==201
    _,ah=bootstrap(c)
    assert c.post('/api/account/invitations/accept',json={'requestId':secrets.token_hex(16),'joinTicket':old['joinTicket']},headers=ah).status_code==409
    new=inspect(c,ah,invitation['token']);rid=secrets.token_hex(16)
    accepted=c.post('/api/account/invitations/accept',json={'requestId':rid,'joinTicket':new['joinTicket']},headers=ah)
    assert accepted.status_code==200,accepted.json
    assert accepted.json['memberId'].startswith('m_') and accepted.json['householdRole']=='member'
    replay=c.post('/api/account/invitations/accept',json={'requestId':rid,'joinTicket':new['joinTicket']},headers=ah)
    assert replay.status_code==200 and replay.json==accepted.json
    with env[3]('default') as con:assert con.execute('SELECT count(*) FROM users').fetchone()[0]==3


@pytest.mark.parametrize('boundary',['pending_committed','household_committed'])
def test_crash_recovery_does_not_replay_domain_writes(env,boundary):
    c,_,ah,account,_=registered(env);invitation=invite(env);ticket=inspect(c,ah,invitation['token'])
    rid=secrets.token_hex(16);body={'requestId':rid,'joinTicket':ticket['joinTicket']}
    def crash(point):
        if point==boundary:raise RuntimeError('synthetic process interruption')
    env[1].callbacks['boundary']=crash
    with pytest.raises(RuntimeError):c.post('/api/account/invitations/accept',json=body,headers=ah)
    env[1].callbacks.pop('boundary')
    assert c.get('/api/account/operations/'+rid).json['state']=='pending'
    with env[3]('default') as con:count=con.execute('SELECT count(*) FROM users').fetchone()[0]
    response=c.post('/api/account/operations/'+rid+'/resume',json={},headers=ah)
    assert response.status_code==200,response.json
    assert response.json['state']==('not_committed' if boundary=='pending_committed' else 'completed')
    with env[3]('default') as con:assert con.execute('SELECT count(*) FROM users').fetchone()[0]==count
    again=c.post('/api/account/invitations/accept',json=body,headers=ah)
    assert again.status_code==200
    if boundary=='pending_committed':assert again.json['state']=='not_committed' and again.json['result'] is None
    else:assert again.json==response.json['result']


def test_unknown_database_is_not_not_committed(env):
    c,_,ah,_,_=registered(env);ticket=inspect(c,ah,invite(env)['token']);rid=secrets.token_hex(16)
    env[1].callbacks['boundary']=lambda point: (_ for _ in ()).throw(RuntimeError('stop')) if point=='pending_committed' else None
    with pytest.raises(RuntimeError):c.post('/api/account/invitations/accept',json={'requestId':rid,'joinTicket':ticket['joinTicket']},headers=ah)
    env[1].callbacks.pop('boundary')
    original=env[1].callbacks['household']
    @contextmanager
    def missing(uid):
        raise OSError('synthetic unavailable household');yield
    env[1].callbacks['household']=missing
    assert c.post('/api/account/operations/'+rid+'/resume',json={},headers=ah).json['state']=='pending'
    env[1].callbacks['household']=original
    missing_id=secrets.token_hex(16)
    assert c.get('/api/account/operations/'+missing_id).json=={'requestId':missing_id,'found':False,'state':None,'result':None}
    assert c.post('/api/account/operations/'+rid+'/resume',json={},headers=ah).json['state']=='not_committed'


def test_switch_rotates_identity_late_cookie_is_invalid_and_receipt_is_history(env):
    c,mh,ah,account,_=registered(env);summary,_=bind(env,c,mh,ah);engine=env[1]
    before=engine.capture(c.get_cookie(engine.COOKIE).value)
    with engine.connection() as con:verified=con.execute('SELECT verified_at FROM personal_sessions WHERE id=?',(before.session_id,)).fetchone()[0]
    body={'requestId':secrets.token_hex(16),'membershipId':summary['id'],'expectedRevision':summary['revision']}
    first=c.post('/api/account/switch-household',json=body,headers=ah);assert first.status_code==200,first.json
    assert first.json=={'ok':True,'householdId':'default','memberId':'member1','entry':'/app/home'}
    late_cookie=c.get_cookie(engine.COOKIE).value;first_identity=engine.capture(late_cookie)
    assert first_identity.generation==before.generation+1
    with engine.guard() as con:assert engine.current(con,first_identity)['verified_at']==verified
    _,ah=bootstrap(c)
    second=c.post('/api/account/switch-household',json={**body,'requestId':secrets.token_hex(16)},headers=ah)
    assert second.status_code==200,second.json
    second_identity=engine.capture(c.get_cookie(engine.COOKIE).value)
    with engine.guard() as con:
        with pytest.raises(PersonalAccountError):engine.current(con,env[4][-2]['personal'])
        assert engine.current(con,env[4][-1]['personal'])['accountId']==account['id']
    c.set_cookie(engine.COOKIE,late_cookie)
    assert c.get('/api/account/households').status_code==401
    assert second_identity.generation==first_identity.generation+1


def test_guard_reentrant_without_http_and_waited_revocation(env):
    c,_,_,_,_=registered(env);engine=env[1];identity=engine.capture(c.get_cookie(engine.COOKIE).value)
    with engine.guard(identity) as con:
        with engine.guard() as nested:assert nested is con is engine.guard_con
    assert engine.guard_con is None
    started=threading.Event();finished=threading.Event();results=[]
    def worker():
        started.set()
        try:
            with engine.guard(identity,require=True):results.append('authorized')
        except PersonalAccountError as exc:results.append(exc.status)
        finally:finished.set()
    with engine.connection() as writer:
        writer.execute('BEGIN IMMEDIATE')
        thread=threading.Thread(target=worker);thread.start();assert started.wait(5)
        writer.execute('UPDATE personal_sessions SET revoked_at=? WHERE id=?',(time.time(),identity.session_id));writer.commit()
    assert finished.wait(5);thread.join(5);assert results==[401]


def test_late_original_pending_cannot_write_after_resume(env):
    c,_,_,account,_=registered(env);engine=env[1];identity=engine.capture(c.get_cookie(engine.COOKIE).value)
    rid=secrets.token_hex(16);pending=threading.Event();release=threading.Event();result=[];errors=[]
    def boundary(point):
        if point=='pending_committed':pending.set();assert release.wait(5)
    engine.callbacks['boundary']=boundary
    def original():
        try:result.append(engine.coordinate(identity,rid,'accept','default',{'marker':'real-pending'},
            lambda *args: (_ for _ in ()).throw(AssertionError('must never execute ended intent'))))
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=original);thread.start();assert pending.wait(5)
    try:assert engine.resume(identity,rid)['state']=='not_committed'
    finally:release.set();thread.join(5);engine.callbacks.pop('boundary')
    assert not errors and result[0]['state']=='not_committed'


def test_request_id_cannot_alias_registration_and_later_write(env):
    c,_,ah,account,registration=registered(env)
    response=c.post('/api/account/logout',json={'requestId':registration['requestId']},headers=ah)
    assert response.status_code==409
    assert c.get('/api/account/me').json['account']==account
    assert c.get('/api/account/operations/'+registration['requestId']).json['result']=={'account':account}


@pytest.mark.parametrize('change',['revoked','expired','inviter_version'])
def test_invitation_qualification_rechecks_original_inviter(env,change):
    invitation=invite(env);c=env[0].test_client();_,ah=bootstrap(c)
    proof=inspect(c,ah,invitation['token'])
    with env[3]('default') as con:
        if change=='revoked':con.execute("UPDATE member_invitations SET state='revoked',revision=revision+1")
        elif change=='expired':con.execute('UPDATE member_invitations SET expires_at=?',(time.time()-1,))
        else:con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        con.commit()
    body={'requestId':secrets.token_hex(16),'login':'invalid.invite','password':'synthetic-password',
          'eligibilityToken':proof['eligibilityToken']}
    assert c.post('/api/account/register',json=body,headers=ah).status_code==409
    assert counts(env[1])['personal_accounts']==0


def test_registration_expiry_after_password_hash_rolls_back(env,monkeypatch):
    c,mh=member(env[0]);_,ah=bootstrap(c)
    q=c.post('/api/account/eligibility',json={'memberPassword':'testing-password-one'},
             headers={**ah,'X-Member-CSRF-Token':mh['X-CSRF-Token']}).json
    original=personal.generate_password_hash
    def hash_then_expire(password):
        result=original(password)
        env[1].guard_con.execute('UPDATE account_qualifications SET expires_at=?',(time.time()-1,))
        return result
    monkeypatch.setattr(personal,'generate_password_hash',hash_then_expire)
    r=c.post('/api/account/register',json={'requestId':secrets.token_hex(16),'login':'expired.hash',
        'password':'synthetic-password','eligibilityToken':q['eligibilityToken']},headers=ah)
    assert r.status_code==409
    assert counts(env[1])['personal_accounts']==counts(env[1])['account_operations']==0


def test_personal_expiry_after_domain_write_rolls_back_household(env,monkeypatch):
    c,_,ah,_,_=registered(env);invitation=invite(env);proof=inspect(c,ah,invitation['token']);rid=secrets.token_hex(16)
    original=env[2].accept_invitation
    def write_then_expire(*args,**kwargs):
        result=original(*args,**kwargs)
        env[1].guard_con.execute('UPDATE personal_sessions SET expires_at=?',(time.time()-1,))
        return result
    monkeypatch.setattr(env[2],'accept_invitation',write_then_expire)
    r=c.post('/api/account/invitations/accept',json={'requestId':rid,'joinTicket':proof['joinTicket']},headers=ah)
    assert r.status_code==401
    with env[3]('default') as con:
        assert con.execute('SELECT count(*) FROM users').fetchone()[0]==2
        assert con.execute('SELECT state FROM member_invitations').fetchone()[0]=='pending'
        assert env[2].operation(con,subject='account:'+env[1].capture(c.get_cookie(env[1].COOKIE).value).account_id,request_id=rid)['found'] is False
    assert c.get('/api/account/operations/'+rid).json['state']=='pending'
    assert c.post('/api/account/operations/'+rid+'/resume',json={},headers=ah).json['state']=='not_committed'


def test_switch_interruption_never_installs_cookie_or_reissues_on_resume(env):
    c,mh,ah,_,_=registered(env);summary,_=bind(env,c,mh,ah);engine=env[1]
    original_personal=c.get_cookie(engine.COOKIE).value;original_member=c.get_cookie('session').value
    rid=secrets.token_hex(16)
    engine.callbacks['boundary']=lambda point: (_ for _ in ()).throw(RuntimeError('lost after household commit')) if point=='household_committed' else None
    with pytest.raises(RuntimeError):
        c.post('/api/account/switch-household',json={'requestId':rid,'membershipId':summary['id'],
            'expectedRevision':summary['revision']},headers=ah)
    engine.callbacks.pop('boundary')
    assert c.get_cookie(engine.COOKIE).value==original_personal and c.get_cookie('session').value==original_member
    with engine.guard() as con:
        with pytest.raises(PersonalAccountError):engine.current(con,env[4][-1]['personal'],require=True)
    resumed=c.post('/api/account/operations/'+rid+'/resume',json={},headers=ah)
    assert resumed.status_code==200 and resumed.json['state']=='completed'
    assert not resumed.headers.getlist('Set-Cookie')
    assert c.get_cookie(engine.COOKIE).value==original_personal and c.get_cookie('session').value==original_member


def test_same_account_two_households_keeps_distinct_membership_and_private_owner(env):
    c,mh,ah,account,_=registered(env);first,_=bind(env,c,mh,ah)
    platform=env[0].extensions['household_platform'];second=next(h for h in platform.households() if h['id']!='default')
    c.set_cookie('household_space',platform.signer.dumps(second['id']))
    c.delete_cookie('session')
    csrf=c.get('/api/me').json['csrf']
    login=c.post('/api/login',json={'username':'member1','password':'second-home-password-one'},headers={'X-CSRF-Token':csrf})
    assert login.status_code==200,login.json
    mh={'X-CSRF-Token':c.get('/api/me').json['csrf']}
    with env[3](second['id']) as con:item=env[2].active_member(con,'member1')
    body={'requestId':secrets.token_hex(16),'memberPassword':'second-home-password-one',
          'expectedAuthVersion':item['authVersion'],'expectedRevision':item['membershipRevision']}
    linked=c.post('/api/membership-links',json=body,headers={**mh,'X-Account-CSRF-Token':ah['X-CSRF-Token']})
    assert linked.status_code==200,linked.json
    assert linked.json['id']!=first['id'] and linked.json['memberId']==first['memberId']=='member1'
    directory=c.get('/api/account/households').json
    assert {m['householdId'] for m in directory['memberships']}=={'default',second['id']}
    for household_id in ('default',second['id']):
        with env[3](household_id) as con:
            assert env[2].membership_record(con,member_id='member1')['account_id']==account['id']
            assert con.execute('SELECT count(*) FROM users').fetchone()[0]==2


def test_leave_history_survives_member_revocation_and_other_account_cannot_read(env):
    c,mh,ah,_,_=registered(env);summary,_=bind(env,c,mh,ah);rid=secrets.token_hex(16)
    with env[3]('default') as con:item=env[2].active_member(con,'member1')
    response=c.post('/api/memberships/self/leave',json={'requestId':rid,'expectedAuthVersion':item['authVersion'],
        'expectedRevision':summary['revision']},headers={**mh,'X-Account-CSRF-Token':ah['X-CSRF-Token']})
    assert response.status_code==200 and response.json['state']=='left',response.json
    assert c.get('/api/private-finance').status_code==401
    assert c.get('/api/account/households').json['memberships']==[]
    assert c.get('/api/account/operations/'+rid).json['result']==response.json
    other,_,oh,_,_=registered(env,2)
    assert other.get('/api/account/operations/'+rid).json['found'] is False
    assert other.post('/api/account/operations/'+rid+'/resume',json={},headers=oh).json['found'] is False


def test_concurrent_login_from_same_browser_only_one_generation_wins(env):
    c,_,ah,account,_=registered(env);engine=env[1]
    raw=c.get_cookie(engine.COOKIE).value;original=engine.capture(raw)
    gate=threading.Barrier(3);results=[];errors=[]
    def attempt():
        client=env[0].test_client();client.set_cookie(engine.COOKIE,raw)
        try:
            gate.wait(5)
            response=client.post('/api/account/login',json={'login':account['login'],
                'password':'synthetic-personal-password'},headers=ah)
            results.append((response.status_code,client.get_cookie(engine.COOKIE).value))
        except BaseException as exc:errors.append(exc)
    threads=[threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:thread.start()
    gate.wait(5)
    for thread in threads:thread.join(10)
    assert not errors and not any(thread.is_alive() for thread in threads)
    assert sorted(status for status,_ in results)==[200,401]
    winner=engine.capture(next(cookie for status,cookie in results if status==200))
    assert winner.generation==original.generation+1
    with engine.guard() as con:
        assert con.execute('SELECT count(*) FROM personal_sessions WHERE revoked_at IS NULL').fetchone()[0]==1
        with pytest.raises(PersonalAccountError):engine.current(con,original,require=True)


def test_failed_login_limit_is_persistent_not_rolled_back(env):
    c=env[0].test_client();_,ah=bootstrap(c)
    for _ in range(20):
        assert c.post('/api/account/login',json={'login':'no.account','password':'synthetic-wrong-password'},headers=ah).status_code==401
    assert c.post('/api/account/login',json={'login':'no.account','password':'synthetic-wrong-password'},headers=ah).status_code==429
    assert counts(env[1])['personal_accounts']==0
    with env[1].connection() as con:
        assert con.execute('SELECT attempts FROM personal_limits').fetchone()[0]==21


def test_caught_nested_guard_failure_cannot_commit_outer_writes(env):
    engine=env[1]
    with pytest.raises(PersonalAccountError,match='未完成'):
        with engine.guard() as con:
            con.execute("INSERT INTO personal_limits VALUES('synthetic-rollback',1,1)")
            try:
                with engine.guard():raise ValueError('inner failed')
            except ValueError:pass
    with engine.connection() as con:
        assert con.execute("SELECT 1 FROM personal_limits WHERE id='synthetic-rollback'").fetchone() is None
    assert engine.guard_con is None
