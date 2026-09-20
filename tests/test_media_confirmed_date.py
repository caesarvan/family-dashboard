"""Real local upload, Flask sessions, encrypted SQLite and day-only projections."""
from contextlib import closing
from datetime import datetime
import sqlite3
from types import SimpleNamespace

import pytest

from app import create_app
from test_device_sessions import invalidate
from test_household_media import env, offline, configured, device, share, confirm
from test_journey_documents import login
from test_local_photo_import import saved, start, put, picture, finish
from test_media_journey_suggestions import photo, journey, payload
from test_media_memories import change_metadata
from test_media_portability import snapshot as export_snapshot
from test_media_suggestion_sessions import snapshot


MODE = '?dateMode=confirmed-or-source'
MEMORIES = '/api/media/memories/on-this-day'


def patch(client, headers, item, value, **extra):
    return client.patch('/api/media/items/' + item['id'], headers=headers,
                        json={'revision': item['revision'], 'userConfirmedDate': value, **extra})


def load(env, uid):
    with env[1].transaction() as con:
        row = con.execute('SELECT * FROM media_items WHERE id=?', (uid,)).fetchone()
        return dict(row), env[1]._metadata(row), [tuple(r) for r in con.execute(
            'SELECT * FROM media_tv_grants WHERE media_id=? ORDER BY device_id', (uid,))]


def suggestions(client, item, mode=MODE):
    response = client.get('/api/media/items/' + item['id'] + '/journey-suggestions' + mode)
    assert response.status_code == 200, response.json
    return response.json


def today(env, value='2028-02-29T00:00:00+00:00'):
    env[2][0] = datetime.fromisoformat(value).timestamp()


def test_upload_set_restart_same_date_clear_cas_preserves_all_other_media(env):
    client, headers, item = saved(env)
    assert item['userConfirmedDate'] is None
    before, metadata, grants = load(env, item['id'])
    display = client.get(item['previewUrl']).data
    env[2][0] += 1
    response = patch(client, headers, item, '2024-02-29')
    assert response.status_code == 200, response.json
    updated = response.json['item']
    after, meta_after, grants_after = load(env, item['id'])
    assert updated['revision'] == item['revision'] + 1
    assert updated['sourceCreatedAt'] is None and updated['sourceTimeState'] == 'unknown'
    assert updated['userConfirmedDate'] == '2024-02-29'
    assert b'2024-02-29' not in after['metadata_cipher']
    assert {k:v for k,v in before.items() if k not in ('metadata_cipher','revision','updated_at')} == {
        k:v for k,v in after.items() if k not in ('metadata_cipher','revision','updated_at')}
    assert meta_after == {**metadata, 'userConfirmedDate': '2024-02-29'}
    assert grants == grants_after and client.get(item['previewUrl']).data == display
    assert patch(client, headers, item, '2024-02-29').status_code == 409
    restarted = create_app(dict(env[0].config))
    again, auth = login(restarted)
    current = again.get('/api/media/items/' + item['id']).json['item']
    assert current['userConfirmedDate'] == '2024-02-29'
    same = patch(again, auth, current, '2024-02-29')
    assert same.status_code == 200 and same.json['item']['revision'] == current['revision'] + 1
    clear = patch(again, auth, same.json['item'], None)
    assert clear.status_code == 200 and clear.json['item']['userConfirmedDate'] is None
    with env[1].transaction() as con:
        assert con.execute("SELECT COUNT(*) FROM audit WHERE action='media_item_update'").fetchone()[0] == 3


@pytest.mark.parametrize('value', ['0001-01-01','1900-01-01','2000-02-29','9999-12-31'])
def test_valid_full_calendar_range(env, value):
    client, headers, item = saved(env)
    response = patch(client, headers, item, value)
    assert response.status_code == 200, response.json
    assert response.json['item']['userConfirmedDate'] == value


@pytest.mark.parametrize('value', ['', '0000-01-01','1900-02-29','2024-02-30','2024-2-29',
                                  '2024-02-29T00:00:00Z',' 2024-02-29',True,20240229,[],{}])
def test_invalid_dates_do_not_write(env, value):
    client, headers, item = saved(env)
    before = snapshot(env)
    response = patch(client, headers, item, value)
    assert response.status_code == 400 and response.json['code'] == 'invalid_input'
    assert snapshot(env) == before


def test_mixed_fields_origin_csrf_and_required_revision_rejected(env):
    client, headers, item = saved(env)
    before = snapshot(env)
    for extra in ({'caption':'draft'}, {'journeyId':None}, {'visibility':'shared'},
                  {'expectedJourneyRevision':1}, {'owner':'member2'}):
        assert patch(client, headers, item, '2024-02-29', **extra).status_code == 400
    assert patch(client, {}, item, '2024-02-29').status_code == 403
    assert patch(client, {**headers,'Origin':'https://outside.invalid'}, item, '2024-02-29').status_code == 403
    assert client.patch('/api/media/items/' + item['id'], headers=headers,
                        json={'userConfirmedDate':None}).status_code == 400
    assert snapshot(env) == before


def test_shared_grants_and_dangling_journey_do_not_change(env):
    client, headers, item = saved(env)
    item = share(client, headers, item)
    device_id, tv, _ = device(env)
    response = client.put('/api/media/items/' + item['id'] + '/tv-grants', headers=headers,
        json={'revision':item['revision'],'deviceIds':[device_id],
              'consentVersion':'media-v1','allowTvDisplay':True})
    assert response.status_code == 200
    # Legacy damaged reference: no foreign-key bypass in the runtime writer.
    with closing(sqlite3.connect(env[1].sessions.path)) as con:
        con.execute('UPDATE media_items SET journey_id=? WHERE id=?', ('f'*24,item['id']))
        con.commit()
    item = client.get('/api/media/items/' + item['id']).json['item']
    before, meta, grants = load(env, item['id'])
    assert grants
    response = patch(client, headers, item, '2024-02-29')
    assert response.status_code == 200, response.json
    after, changed, final_grants = load(env, item['id'])
    assert before['journey_id'] == after['journey_id'] == 'f'*24
    assert after['visibility'] == 'shared' and final_grants == grants
    assert changed == {**meta,'userConfirmedDate':'2024-02-29'}
    assert 'userConfirmedDate' not in tv.get('/api/media-tv/items').json['items'][0]


def test_owner_shared_tv_household_and_export_privacy(env, tmp_path, monkeypatch):
    client, headers, item = saved(env)
    item = patch(client, headers, item, '2024-02-29').json['item']
    other, auth = login(env[0], 2)
    assert other.get('/api/media/items/' + item['id']).status_code == 404
    item = share(client, headers, item)
    shared = other.get('/api/media/items/' + item['id']).json['item']
    assert 'userConfirmedDate' not in shared
    assert patch(other, auth, item, '2023-02-28').status_code == 403
    _, tv, _ = device(env)
    assert patch(tv, headers, item, '2023-02-28').status_code == 403
    assert env[0].test_client().get('/api/media/items/' + item['id']).status_code == 401
    second = configured(tmp_path/'second', monkeypatch, 'synthetic-other-household')
    stranger, stranger_auth = login(second[0])
    assert patch(stranger, stranger_auth, item, '2023-02-28').status_code == 404
    own_export, _ = export_snapshot(client.post('/api/portability/export', headers=headers, json={}))
    assert own_export['personal']['householdMedia'][0]['userConfirmedDate'] == '2024-02-29'
    other_export, _ = export_snapshot(other.post('/api/portability/export', headers=auth, json={'includeShared':True}))
    assert 'userConfirmedDate' not in other_export['shared']['householdMedia'][0]


@pytest.mark.parametrize('kind', ['google','forged_null_google','video','unconfirmed','deleted','local_bad_key'])
def test_only_authentic_confirmed_local_photo_is_editable(env, kind):
    if kind == 'unconfirmed':
        client,headers,_,detail=start(env)
        response=put(client,headers,detail,picture())
        assert response.status_code==200,response.json
        detail,_=finish(client,headers,response.json)
        item=detail['items'][0]['item']
    elif kind in ('google','forged_null_google'):
        client, headers, item, _ = photo(env)
        if kind == 'forged_null_google':
            with env[1].transaction(True) as con:
                row = con.execute('SELECT * FROM media_items WHERE id=?',(item['id'],)).fetchone()
                meta = env[1]._metadata(row);meta.update(accountId=None,source='local-upload',sourceVersion=1,
                    uploadSha256='0'*64,userConfirmedDate='2024-02-29')
                con.execute('UPDATE media_items SET account_id=NULL,metadata_cipher=? WHERE id=?',
                    (env[1]._seal('media-metadata',row,meta),item['id']))
    else:
        client, headers, item = saved(env)
        if kind == 'video':
            change_metadata(env,item['id'],{'mediaType':'video','durationMs':10,'hasAudio':False})
        else:
            with env[1].transaction(True) as con:
                if kind == 'deleted':env[1]._delete_item(con,con.execute('SELECT * FROM media_items WHERE id=?',(item['id'],)).fetchone())
            if kind == 'local_bad_key':change_metadata(env,item['id'],{'uploadSha256':'0'*64})
    current = client.get('/api/media/items/' + item['id'])
    if kind != 'deleted':assert current.json['item']['userConfirmedDate'] is None
    before = snapshot(env)
    response = patch(client, headers, item, '2024-02-29')
    assert response.status_code == (410 if kind == 'deleted' else 403), response.json
    assert snapshot(env) == before


def test_staged_photo_not_editable(env):
    client, headers, _, detail = start(env)
    detail = put(client, headers, detail, picture()).json
    item = detail['items'][0]['item']
    assert item['userConfirmedDate'] is None
    assert patch(client, headers, item, '2024-02-29').status_code == 403


def test_v1_unchanged_v2_manual_suggestions_no_timezone_shift_and_stale_confirmation(env):
    client, headers, item = saved(env)
    for tz in ('Pacific/Kiritimati','Pacific/Honolulu'):
        journey(client,headers,start='2024-02-29',end='2024-02-29',tz=tz)
    before = suggestions(client,item,'')
    unknown = suggestions(client,item)
    assert unknown['version'] == 2 and unknown['dateBasis'] == 'unknown'
    assert unknown['reason']['code'] == 'date_unknown' and unknown['suggestions'] == []
    item = patch(client,headers,item,'2024-02-29').json['item']
    legacy = suggestions(client,item,'')
    assert legacy == {**before,'photoRevision':item['revision']}
    result = suggestions(client,item)
    assert set(result) == {'version','photoId','photoRevision','sourceTimeState','sourceCreatedAt',
        'userConfirmedDate','dateBasis','currentJourneyId','suggestions','limit','hasMore','reason'}
    assert result['dateBasis'] == 'userConfirmedDate' and result['sourceTimeState'] == 'unknown'
    assert len(result['suggestions']) == 2
    assert all(r['matchDate']=='2024-02-29' and 'sourceDate' not in r for r in result['suggestions'])
    old_confirmation = payload(result)
    item = patch(client,headers,item,'2024-03-01').json['item']
    assert client.patch('/api/media/items/'+item['id'],headers=headers,json=old_confirmation).status_code == 409
    assert suggestions(client,item)['reason']['code'] == 'no_matching_journeys'
    item = patch(client,headers,item,'2024-02-29').json['item']
    fresh = suggestions(client,item)
    linked = client.patch('/api/media/items/'+item['id'],headers=headers,json=payload(fresh))
    assert linked.status_code == 200 and linked.json['item']['journey']['id'] == fresh['suggestions'][0]['journeyId']
    cleared = patch(client,headers,linked.json['item'],None)
    assert cleared.status_code == 200 and cleared.json['item']['journey'] == linked.json['item']['journey']


def test_provider_instants_keep_zone_conversion_and_offline_owner_semantics(env):
    stamp='2024-02-28T16:30:00.123456789Z'
    client,headers,item,_=photo(env,stamp)
    journey(client,headers,start='2024-02-29',end='2024-02-29')
    before=suggestions(client,item,'')
    with env[1].transaction(True) as con:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?',(env[3][1],))
    result=suggestions(client,item)
    assert result['sourceCreatedAt']==stamp and result['userConfirmedDate'] is None
    assert result['dateBasis']=='sourceCreatedAt'
    assert result['suggestions']==[{**{k:v for k,v in x.items() if k!='sourceDate'},'matchDate':x['sourceDate']} for x in before['suggestions']]


def test_memories_v2_day_counts_clearing_midnight_and_leap_policy(env):
    client,headers,item=saved(env)
    today(env)
    legacy=client.get(MEMORIES).json
    assert legacy['unknownSourceTimeCount']==1 and legacy['items']==[]
    item=patch(client,headers,item,'2024-02-29').json['item']
    assert client.get(MEMORIES).json==legacy
    value=client.get(MEMORIES+MODE).json
    assert set(value)=={'version','datePolicy','referenceDate','referenceTimezone','scope','items','total',
        'limit','offset','hasMore','unknownSourceTimeCount','unknownEffectiveDateCount'}
    assert value['unknownSourceTimeCount']==1 and value['unknownEffectiveDateCount']==0
    assert value['items']==[{'item':item,'displayDate':'2024-02-29','dateBasis':'userConfirmedDate','yearsAgo':4}]
    today(env,'2028-02-29T16:00:00+00:00')
    assert client.get(MEMORIES+MODE).json['items']==[]
    today(env,'2027-02-28T00:00:00+00:00')
    assert client.get(MEMORIES+MODE).json['items']==[]
    today(env)
    cleared=patch(client,headers,item,None)
    assert cleared.status_code==200
    value=client.get(MEMORIES+MODE).json
    assert value['total']==0 and value['unknownEffectiveDateCount']==1


@pytest.mark.parametrize('query',['?dateMode=source','?dateMode=','?dateMode=confirmed-or-source&dateMode=confirmed-or-source',
                                  '?dateMode=confirmed-or-source&owner=member2'])
def test_derived_query_mode_is_explicit_and_strict(env,query):
    client,_,item=saved(env)
    for path in (MEMORIES,'/api/media/items/'+item['id']+'/journey-suggestions'):
        response=client.get(path+query)
        assert response.status_code==400 and response.json['code']=='invalid_input'
    assert client.get(MEMORIES+MODE+'&limit=2').status_code==400


def test_write_expiry_after_audit_rolls_back_and_read_revocation_hides_date(env,monkeypatch):
    import member_sessions
    client,headers,item=saved(env)
    before=snapshot(env)
    with env[1].transaction() as con:
        expiry=con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    original=env[1]._audit
    with monkeypatch.context() as patcher:
        def expire(con,*args):
            original(con,*args)
            patcher.setattr(member_sessions,'time',SimpleNamespace(time=lambda:expiry+1))
        patcher.setattr(env[1],'_audit',expire)
        response=patch(client,headers,item,'2024-02-29')
        assert response.status_code==401 and snapshot(env)==before
    client,headers=login(env[0])
    item=patch(client,headers,item,'2024-02-29').json['item']
    original_meta=env[1]._metadata
    revoked=[]
    def revoke(row):
        value=original_meta(row)
        if not revoked:
            revoked.append(True)
            with closing(sqlite3.connect(env[1].sessions.path)) as con:
                invalidate(con);con.commit()
        return value
    monkeypatch.setattr(env[1],'_metadata',revoke)
    response=client.get('/api/media/items/'+item['id']+'/journey-suggestions'+MODE)
    assert response.status_code==401 and 'userConfirmedDate' not in response.json


@pytest.mark.parametrize('route',['item','list','import','memories'])
@pytest.mark.parametrize('when',['before','after'])
def test_actual_member_reads_fence_revocation_before_and_after_projection(env,monkeypatch,route,when):
    client,headers,item=saved(env)
    item=patch(client,headers,item,'2024-02-29').json['item']
    if route=='import':
        client,headers,_,detail=start(env,[picture('blue')])
        detail=put(client,headers,detail,picture('blue')).json
        endpoint='/api/media/imports/'+detail['import']['id']
    else:
        endpoint={'item':'/api/media/items/'+item['id'],'list':'/api/media/items',
                  'memories':MEMORIES+MODE}.get(route)
    def revoke():
        with closing(sqlite3.connect(env[1].sessions.path)) as con:
            invalidate(con);con.commit()
    if when=='before':
        env[0].before_request_funcs[None].append(revoke)
    else:
        original=env[1]._metadata
        once=[]
        def read(row):
            result=original(row)
            if not once:
                once.append(True);revoke()
            return result
        monkeypatch.setattr(env[1],'_metadata',read)
    response=client.get(endpoint)
    assert response.status_code==401,response.json
    assert '2024-02-29' not in response.get_data(as_text=True)


def test_lost_write_response_recheck_does_not_create_receipt_or_rewrite(env):
    client,headers,item=saved(env)
    lost=[]
    def transport_failure(response):
        from flask import request, jsonify
        if request.method=='PATCH' and request.path=='/api/media/items/'+item['id'] and not lost:
            assert response.status_code==200
            lost.append(True)
            failed=jsonify(error='synthetic transport response lost');failed.status_code=503
            return failed
        return response
    env[0].after_request_funcs.setdefault(None,[]).append(transport_failure)
    response=patch(client,headers,item,'2024-02-29')
    assert response.status_code==503 and lost==[True]
    current=client.get('/api/media/items/'+item['id']).json['item']
    assert current['revision']==item['revision']+1 and current['userConfirmedDate']=='2024-02-29'
    assert patch(client,headers,item,'2024-02-29').status_code==409
    with env[1].transaction() as con:
        assert con.execute("SELECT COUNT(*) FROM audit WHERE action='media_item_update'").fetchone()[0]==1


def test_v2_effective_date_sort_pagination_and_source_unknown_counts(env):
    items=[]
    # Three real batches respect the existing ten-batches-per-day admission.
    for begin in (0,10,20):
        raws=[picture('#%06x'%index) for index in range(begin,min(begin+10,25))]
        client,headers,_,detail=start(env,raws)
        for position,raw in enumerate(raws):
            response=put(client,headers,detail,raw,position)
            assert response.status_code==200,response.json
            detail=response.json
        detail,_=finish(client,headers,detail)
        confirm(client,headers,detail)
        for position,record in enumerate(detail['items']):
            item=client.get('/api/media/items/'+record['id']).json['item']
            value='2024-02-29' if begin+position<24 else '2020-02-29'
            response=patch(client,headers,item,value)
            assert response.status_code==200,response.json
            items.append(response.json['item'])
    today(env)
    first=client.get(MEMORIES+MODE).json
    second=client.get(MEMORIES+MODE+'&offset=24').json
    expected=sorted(x['id'] for x in items[:24])+[items[24]['id']]
    assert [entry['item']['id'] for page in (first,second) for entry in page['items']]==expected
    assert first['hasMore'] and not second['hasMore'] and first['total']==second['total']==25
    assert first['unknownSourceTimeCount']==25 and first['unknownEffectiveDateCount']==0


def test_invalid_stored_date_falls_back_without_rewriting_cipher(env):
    client,headers,item=saved(env)
    change_metadata(env,item['id'],{'userConfirmedDate':'2024-02-30','sourceCreatedAt':'2024-02-28T16:00:00Z'})
    before=snapshot(env);today(env)
    current=client.get('/api/media/items/'+item['id']).json['item']
    assert current['userConfirmedDate'] is None
    result=client.get(MEMORIES+MODE).json
    assert result['items'][0]['dateBasis']=='sourceCreatedAt' and result['items'][0]['displayDate']=='2024-02-29'
    assert result['unknownEffectiveDateCount']==result['unknownSourceTimeCount']==0
    assert snapshot(env)==before
