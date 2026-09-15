"""Synthetic downloadable plans must use the actual journey API contract."""
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from test_app import app, member

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'id','journeyId','tripId','revision','tripRevision','previewToken','idempotencyKey','csrf','access_token','refresh_token','client_secret','instant','offsetMinutes'}


def keys(value):
    if isinstance(value, dict):
        for key,item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:yield from keys(item)


@pytest.mark.parametrize('version', [1,2])
def test_downloaded_example_preview_apply_roundtrip_preserves_units_dates_and_links(app, version):
    raw=(ROOT/f'static/examples/journey-plan-v{version}.json').read_bytes()
    anonymous=app.test_client()
    download=anonymous.get(f'/static/examples/journey-plan-v{version}.json')
    assert download.status_code==200 and download.mimetype=='application/json' and download.data==raw
    assert len(raw)<200000
    plan=json.loads(raw)
    assert not FORBIDDEN.intersection(keys(plan))
    assert plan['schemaVersion']==version and '虚构' in plan['title']
    assert {d['country'] for d in plan['destinations']}=={'日本','法国'}
    assert [d['city'] for d in plan['destinations']]==['东京','京都','巴黎']
    client,headers=member(app)
    preview=client.post('/api/journeys/preview',json={'plan':plan},headers=headers)
    assert preview.status_code==200,preview.json
    assert preview.json['canApply'] is True
    before=client.get('/api/state').json
    assert not any(before[k] for k in ('trips','tasks','shopping','events'))
    assert not client.get('/api/journeys').json['journeys']
    expected_events=4 if version==1 else 8
    assert preview.json['summary']['create']=={'trips':1,'tasks':3,'shopping':2,'events':expected_events}
    assert preview.json['plan']['budget']==2000000 and preview.json['plan']['saved']==500000 and preview.json['plan']['paid']==300000
    assert [t['due'] for t in preview.json['plan']['checklist']]==['2027-09-01','2027-09-17','2027-09-29']
    payload={'previewToken':preview.json['previewToken'],'idempotencyKey':f'example-v{version}-confirm'}
    applied=client.post('/api/journeys/apply',json=payload,headers=headers)
    assert applied.status_code==201,applied.json
    again=client.post('/api/journeys/apply',json=payload,headers=headers)
    assert again.status_code==200 and again.json['id']==applied.json['id']
    detail=client.get('/api/journeys/'+applied.json['id']).json
    assert detail['progress']=={'done':0,'total':3,'purchased':0,'purchaseCount':2}
    assert detail['budget']['total']==2000000 and detail['budget']['paid']==300000 and detail['budget']['reserved']==500000
    assert detail['budget']['purchaseBudget']==8000 and detail['budget']['unknownPurchaseBudgets']==1
    assert len(detail['events'])==expected_events and detail['calendar']['cloud']=='not_requested'
    original_ids={kind:{item['workflowKey']:item['id'] for item in detail[kind]} for kind in ('tasks','shopping','events')}
    repeated=client.post('/api/journeys/preview',json={'journeyId':detail['id'],'revision':detail['revision'],'plan':detail['plan']},headers=headers)
    assert repeated.status_code==200,repeated.json
    changed=client.post('/api/journeys/apply',json={'previewToken':repeated.json['previewToken'],'idempotencyKey':f'example-v{version}-roundtrip'},headers=headers)
    assert changed.status_code==200,changed.json
    after=client.get('/api/journeys/'+detail['id']).json
    assert original_ids=={kind:{item['workflowKey']:item['id'] for item in after[kind]} for kind in ('tasks','shopping','events')}
    state=client.get('/api/state').json
    assert len(state['trips'])==1 and state['finance']['livingSpent']==0
    with app.extensions['cloud_accounts'].db() as con:
        assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM calendar_publications').fetchone()[0]==0


def test_v2_example_canonical_times_and_exclusive_dates(app):
    client,headers=member(app)
    plan=json.loads((ROOT/'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
    result=client.post('/api/journeys/preview',json={'plan':plan},headers=headers)
    assert result.status_code==200,result.json
    segments={row['key']:row for row in result.json['plan']['segments']}
    flight=segments['flight-outbound']
    assert flight['departure']['instant']=='2027-10-01T01:00:00Z'
    assert flight['arrival']['instant']=='2027-10-01T04:00:00Z'
    assert (datetime.fromisoformat(flight['arrival']['instant'])-datetime.fromisoformat(flight['departure']['instant'])).total_seconds()==10800
    assert segments['tokyo-stay']['nights']==3 and segments['paris-stay']['nights']==5
    assert 'checkInInstant' not in segments['tokyo-stay'] and segments['tokyo-stay']['checkInTime']==''
    created=client.post('/api/journeys/apply',json={'previewToken':result.json['previewToken'],'idempotencyKey':'example-v2-time-semantics'},headers=headers)
    detail=client.get('/api/journeys/'+created.json['id']).json
    events={row['workflowKey']:row for row in detail['events']}
    assert events['segment:tokyo-stay']['startDate']=='2027-10-01'
    assert events['segment:tokyo-stay']['endDateExclusive']=='2027-10-04'
    assert events['segment:kyoto-day']['endDateExclusive']=='2027-10-06'
    assert events['segment:kyoto-legacy-days']['endDateExclusive']=='2027-10-07'
    ics=client.get(detail['calendar']['icsUrl']).data.decode()
    assert 'DTSTART:20271001T010000Z' in ics and 'DTEND:20271001T040000Z' in ics
    assert 'DTSTART;VALUE=DATE:20271001' in ics and 'DTEND;VALUE=DATE:20271004' in ics
