"""Real member/SQLite/encrypted metadata and journey APIs; synthetic photos only."""
import json
import secrets

import pytest

from household_media import MediaLibrary, MediaError, manifest_map
from test_household_media import env, offline, configured, stage, selected, confirm, share, device
from test_journey_documents import login
from test_media_portability import snapshot


def photo(env, stamp='2026-12-01T16:30:00.123456789Z', number=1, source_id=None):
    source=selected(source_id or secrets.token_hex(12));source['createTime']=stamp
    client,headers,detail,_=stage(env,number,[source])
    confirm(client,headers,detail)
    item=client.get('/api/media/items/'+detail['items'][0]['id']).json['item']
    return client,headers,item,detail


def journey(client,headers,*,start='2026-12-02',end='2026-12-02',tz=None,title='Synthetic trip'):
    plan={'title':title,'start':start,'end':end,'destinations':[{'key':'city','city':'Synthetic city',
        'arrival':start,'departure':end}], 'checklist':[],'shopping':[],'segments':[]}
    if tz is not None:
        plan.update(schemaVersion=2,referenceTimezone=tz)
        plan['destinations'][0]['timeZone']=tz
    preview=client.post('/api/journeys/preview',headers=headers,json={'plan':plan})
    assert preview.status_code==200,preview.json
    applied=client.post('/api/journeys/apply',headers=headers,json={'previewToken':preview.json['previewToken'],'idempotencyKey':secrets.token_hex(16)})
    assert applied.status_code==201,applied.json
    return client.get('/api/journeys/'+applied.json['id']).json


def suggestions(client,item):
    response=client.get('/api/media/items/'+item['id']+'/journey-suggestions')
    assert response.status_code==200,response.json
    return response.json


def payload(value,index=0):
    match=value['suggestions'][index]
    return {'revision':value['photoRevision'],'journeyId':match['journeyId'],
        'expectedJourneyRevision':match['journeyRevision'],'expectedTripRevision':match['tripRevision']}


def dump(engine):
    with engine.transaction() as con:
        return '\n'.join(con.iterdump())


def metadata(env,uid,*,remove=False):
    engine=env[1]
    with engine.transaction(remove) as con:
        row=con.execute('SELECT * FROM media_items WHERE id=?',(uid,)).fetchone()
        value=engine._metadata(row)
        if remove:
            value.pop('sourceCreatedAt',None)
            con.execute('UPDATE media_items SET metadata_cipher=? WHERE id=?',(engine._seal('media-metadata',row,value),uid))
        return value,dict(row)


def test_creation_instant_persists_encrypted_through_confirm_cleanup_and_restart(env):
    stamp='2026-12-01T23:30:00.123456789-07:00'
    client,headers,item,detail=photo(env,stamp)
    assert item['sourceCreatedAt']==stamp and item['sourceTimeState']=='known'
    assert item['createdAt']!=stamp
    _,row=metadata(env,item['id'])
    assert stamp.encode() not in row['metadata_cipher']
    with env[1].transaction() as con:
        receipt=con.execute('SELECT manifest_cipher,session_cipher FROM media_imports WHERE id=?',(detail['import']['id'],)).fetchone()
        assert tuple(receipt)==(None,None)
    restarted=MediaLibrary(env[0])
    with restarted.transaction() as con:
        loaded=con.execute('SELECT * FROM media_items WHERE id=?',(item['id'],)).fetchone()
        assert restarted._item_dto(con,loaded,'member1')['sourceCreatedAt']==stamp
    exported,_=snapshot(client.post('/api/portability/export',json={},headers=headers))
    assert exported['personal']['householdMedia'][0]['sourceCreatedAt']==stamp
    assert exported['personal']['householdMedia'][0]['sourceTimeState']=='known'


def test_legacy_metadata_unknown_and_duplicate_does_not_backfill(env):
    client,headers,item,_=photo(env,source_id='old-source')
    metadata(env,item['id'],remove=True)
    _,before=metadata(env,item['id'])
    response=suggestions(client,item)
    assert response['sourceTimeState']=='unknown' and response['sourceCreatedAt'] is None
    assert response['reason']['code']=='source_time_unknown' and response['suggestions']==[]
    assert client.get('/api/media/items/'+item['id']).json['item']['sourceCreatedAt'] is None
    _,_,duplicate,_=photo(env,'2026-12-03T00:00:00Z',source_id='old-source')
    _,after=metadata(env,item['id'])
    assert duplicate['id']==item['id'] and duplicate['sourceTimeState']=='unknown'
    assert after['metadata_cipher']==before['metadata_cipher'] and after['revision']==before['revision']
    exported,_=snapshot(client.post('/api/portability/export',json={},headers=headers))
    assert exported['personal']['householdMedia'][0]['sourceTimeState']=='unknown'
    assert exported['personal']['householdMedia'][0]['sourceCreatedAt'] is None


@pytest.mark.parametrize('stamp,tz,local_date',[
    ('2026-12-01T16:00:00.000000001Z','Asia/Shanghai','2026-12-02'),
    ('2026-12-01T23:59:59.999999999-08:00','America/Los_Angeles','2026-12-01'),
    ('2026-12-02T00:30:00+14:00','Pacific/Honolulu','2026-12-01'),
    ('2026-12-01T23:30:00-12:00','Pacific/Kiritimati','2026-12-03'),
    ('2026-03-08T09:59:59.999999999Z','America/Los_Angeles','2026-03-08'),
    ('2026-03-08T10:00:00Z','America/Los_Angeles','2026-03-08'),
    ('2026-11-01T08:30:00Z','America/Los_Angeles','2026-11-01'),
    ('2026-11-01T09:30:00Z','America/Los_Angeles','2026-11-01'),
])
def test_zone_date_line_dst_nanoseconds_and_inclusive_trip_dates(env,stamp,tz,local_date):
    client,headers,item,_=photo(env,stamp)
    trip=journey(client,headers,start=local_date,end=local_date,tz=tz)
    match=suggestions(client,item)['suggestions'][0]
    assert match['journeyId']==trip['id']!=trip['tripId']
    assert match['journeyRevision']==trip['revision'] and match['tripRevision']==trip['trip']['revision']
    assert match['sourceDate']==local_date and match['referenceTimezone']==tz
    assert match['referenceTimezoneSource']=='plan' and match['reason']['code']=='date_overlap'


def test_current_trip_dates_and_title_override_stale_plan_with_explicit_legacy_timezone(env):
    client,headers,item,_=photo(env)
    trip=journey(client,headers,start='2026-11-01',end='2026-11-02')
    assert suggestions(client,item)['reason']['code']=='no_matching_journeys'
    response=client.patch('/api/items/trips/'+trip['tripId'],headers=headers,json={
        'revision':trip['trip']['revision'],'start':'2026-12-02','end':'2026-12-03','title':'Current edited trip'})
    assert response.status_code==200,response.json
    match=suggestions(client,item)['suggestions'][0]
    assert match['title']=='Current edited trip' and match['start']=='2026-12-02'
    assert match['referenceTimezone']=='Asia/Shanghai' and match['referenceTimezoneSource']=='legacy_default'
    assert match['journeyRevision']==trip['revision'] and match['tripRevision']>trip['trip']['revision']


def test_suggestions_read_only_bounded_sorted_and_existing_association_untouched(env):
    client,headers,item,_=photo(env)
    trips=[journey(client,headers,title='Overlapping '+str(n),start='2026-12-01' if n%2 else '2026-12-02') for n in range(22)]
    # A normal explicit manual link remains supported, without expected revisions.
    response=client.patch('/api/media/items/'+item['id'],headers=headers,json={'revision':item['revision'],'journeyId':trips[0]['id']})
    assert response.status_code==200,response.json
    before=dump(env[1]);result=suggestions(client,item)
    assert dump(env[1])==before
    assert len(result['suggestions'])==20 and result['hasMore'] and result['limit']==20
    assert result['currentJourneyId']==trips[0]['id']
    expected=sorted(trips,key=lambda t:t['id'])
    expected.sort(key=lambda t:t['trip']['start'],reverse=True)
    assert [s['journeyId'] for s in result['suggestions']]==[t['id'] for t in expected[:20]]
    assert all(s['alreadyLinked']==(s['journeyId']==trips[0]['id']) for s in result['suggestions'])


def test_explicit_confirm_changes_only_link_and_returns_fresh_photo_revision(env):
    client,headers,item,_=photo(env)
    trip=journey(client,headers)
    before=suggestions(client,item)
    with env[1].transaction() as con:
        tables={name:[tuple(r) for r in con.execute('SELECT * FROM '+name)] for name in ('journey_workflows','entities','journey_places','media_tv_grants')}
    response=client.patch('/api/media/items/'+item['id'],headers=headers,json=payload(before))
    assert response.status_code==200,response.json
    updated=response.json['item']
    assert updated['journey']['id']==trip['id'] and updated['revision']==item['revision']+1
    assert updated['visibility']=='private' and updated['caption']==item['caption'] and updated['sourceCreatedAt']==item['sourceCreatedAt']
    with env[1].transaction() as con:
        for name,rows in tables.items(): assert [tuple(r) for r in con.execute('SELECT * FROM '+name)]==rows
    assert suggestions(client,updated)['suggestions'][0]['alreadyLinked']
    assert client.patch('/api/media/items/'+item['id'],headers=headers,json=payload(before)).status_code==409


@pytest.mark.parametrize('changed',['photo','journey','trip','deleted_trip'])
def test_stale_three_revisions_and_removed_trip_reject_without_mutation(env,changed):
    client,headers,item,_=photo(env);trip=journey(client,headers)
    expected=payload(suggestions(client,item))
    if changed=='photo':
        assert client.patch('/api/media/items/'+item['id'],headers=headers,json={'revision':item['revision'],'caption':'New caption'}).status_code==200
    elif changed=='trip':
        assert client.patch('/api/items/trips/'+trip['tripId'],headers=headers,json={'revision':trip['trip']['revision'],'title':'New trip title'}).status_code==200
    elif changed=='deleted_trip':
        assert client.delete('/api/items/trips/'+trip['tripId'],headers=headers,json={'revision':trip['trip']['revision']}).status_code==200
    else:
        plan=trip['plan'];plan['note']='Revised workflow'
        preview=client.post('/api/journeys/preview',headers=headers,json={'journeyId':trip['id'],'revision':trip['revision'],'plan':plan})
        assert preview.status_code==200,preview.json
        assert client.post('/api/journeys/apply',headers=headers,json={'previewToken':preview.json['previewToken'],'idempotencyKey':secrets.token_hex(16)}).status_code==200
    before=dump(env[1])
    response=client.patch('/api/media/items/'+item['id'],headers=headers,json=expected)
    assert response.status_code==409 and response.json['code']=='conflict'
    assert dump(env[1])==before


@pytest.mark.parametrize('change',[
    {'expectedJourneyRevision':None},{'expectedTripRevision':False},{'expectedJourneyRevision':0},
    {'journeyId':None},{'caption':'cannot mix draft'},{'visibility':'shared'},
])
def test_suggestion_confirm_requires_exact_positive_pair_and_link_only(env,change):
    client,headers,item,_=photo(env);journey(client,headers)
    expected=payload(suggestions(client,item));expected.update(change)
    assert client.patch('/api/media/items/'+item['id'],headers=headers,json=expected).status_code==400
    expected=payload(suggestions(client,item));expected.pop('expectedTripRevision')
    assert client.patch('/api/media/items/'+item['id'],headers=headers,json=expected).status_code==400


def test_owner_only_shared_tv_other_household_and_expired_member_boundaries(env,tmp_path,monkeypatch):
    client,headers,item,_=photo(env);journey(client,headers)
    item=share(client,headers,item)
    partner,ph=login(env[0],2)
    partner_item=partner.get('/api/media/items/'+item['id']).json['item']
    assert not {'sourceCreatedAt','sourceTimeState'} & partner_item.keys()
    assert partner.get('/api/media/items/'+item['id']+'/journey-suggestions').status_code==404
    exported,_=snapshot(partner.post('/api/portability/export',headers=ph,json={'includeShared':True}))
    assert not {'sourceCreatedAt','sourceTimeState'} & exported['shared']['householdMedia'][0].keys()
    device_id,tv,_=device(env)
    assert client.put('/api/media/items/'+item['id']+'/tv-grants',headers=headers,json={
        'revision':item['revision'],'deviceIds':[device_id],'consentVersion':'media-v1','allowTvDisplay':True}).status_code==200
    linked=client.patch('/api/media/items/'+item['id'],headers=headers,json=payload(suggestions(client,item)))
    assert linked.status_code==200 and linked.json['item']['visibility']=='shared'
    assert client.get('/api/media/items/'+item['id']+'/tv-grants').json['deviceIds']==[device_id]
    assert tv.get('/api/media/items/'+item['id']+'/journey-suggestions').status_code==403
    assert not {'sourceCreatedAt','sourceTimeState'} & tv.get('/api/media-tv/items').json['items'][0].keys()
    second=configured(tmp_path/'second',monkeypatch,'synthetic-second-household')
    other,_=login(second[0])
    assert other.get('/api/media/items/'+item['id']+'/journey-suggestions').status_code==404
    assert client.post('/api/logout',headers=headers,json={}).status_code==200
    assert client.get('/api/media/items/'+item['id']+'/journey-suggestions').status_code==401


def test_not_ready_deleted_invalid_id_and_query(env):
    client,headers,detail,_=stage(env)
    uid=detail['items'][0]['id'];url='/api/media/items/'+uid+'/journey-suggestions'
    assert client.get(url).status_code==409 and client.get(url).json['code']=='not_ready'
    confirm(client,headers,detail)
    item=client.get('/api/media/items/'+uid).json['item']
    assert client.get(url+'?offset=0').status_code==400
    assert client.get('/api/media/items/not-an-id/journey-suggestions').status_code==400
    assert client.delete('/api/media/items/'+uid,headers=headers,json={'revision':item['revision']}).status_code==200
    assert client.get(url).status_code==410


@pytest.mark.parametrize('stamp',[None,123,'2026-12-01','2026-12-01 00:00:00Z','2026-12-01T00:00:00',
    '2026-02-30T00:00:00Z','2026-12-01T00:00:00.1234567890Z','2026-12-01T00:00:00+00:60','2026-12-01T00:00:00+24:00'])
def test_only_strict_source_creation_instants_enter_new_manifests(stamp):
    item=selected();item['createTime']=stamp
    with pytest.raises(MediaError,match='媒体服务响应无效'):
        manifest_map([item])
