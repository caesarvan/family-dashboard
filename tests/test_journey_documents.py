"""Real member sessions, WSGI, concurrent SQLite writes and synthetic files only."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import threading

from PIL import Image
import pytest

from app import create_app
import journey_documents as documents
import journey_workflows


PDF = b'%PDF-1.7\n% SYNTHETIC TICKET ONLY\n%%EOF\n'
PASSWORD = 'synthetic-document-password'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network forbidden in document API tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('MEMBER1_PASSWORD', PASSWORD)
    monkeypatch.setenv('MEMBER2_PASSWORD', PASSWORD)
    return create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'),
        'SECRET_KEY': 'synthetic-document-test-secret', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': ''})


def login(app, number=1, client=None, password=PASSWORD):
    client = client or app.test_client()
    client.get('/api/me')
    response = client.post('/api/login', json={'username': f'member{number}', 'password': password})
    assert response.status_code == 200, response.json
    return client, {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}


def clone(app, client):
    other = app.test_client()
    for name in ('session', 'household_space'):
        cookie = client.get_cookie(name)
        if cookie:
            other.set_cookie(name, cookie.value)
    return other


def connection(app):
    con = sqlite3.connect((Path(app.config['DATA_DIR']) / 'household.sqlite3').as_uri() + '?mode=rw', uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def create_journey(client, headers, title='合成旅行'):
    plan = {'title': title, 'start': '2026-12-01', 'end': '2026-12-04', 'budget': 100000,
        'destinations': [{'key': 'city', 'city': '合成城市', 'country': '合成地区', 'arrival': '2026-12-01', 'departure': '2026-12-04'}],
        'checklist': [], 'shopping': [],
        'segments': [{'key': 'hotel', 'title': '合成酒店', 'start': '2026-12-01', 'end': '2026-12-04'}]}
    preview = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
    assert preview.status_code == 200, preview.json
    result = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': secrets.token_hex(16)}, headers=headers)
    assert result.status_code == 201, result.json
    return result.json


@pytest.fixture
def setup(app):
    client, headers = login(app)
    return client, headers, create_journey(client, headers)


def payload(journey_id, **values):
    return {'journeyId': journey_id, 'requestId': secrets.token_hex(16), 'title': '仅供测试的预订凭证',
        'file': {'name': 'synthetic-ticket.pdf', 'mimeType': 'application/pdf', 'dataBase64': base64.b64encode(PDF).decode()}, **values}


def upload(client, headers, journey_id, **values):
    value = payload(journey_id, **values)
    response = client.post('/api/journey-documents', json=value, headers=headers)
    assert response.status_code == 201, response.json
    return response.json['document'], value


def patch_value(item, **values):
    return {key: values.get(key, item[key]) for key in ('revision', 'title', 'visibility', 'segmentKey', 'journeyId')}


def path(item):
    return '/api/journey-documents/' + item['id']


def image_file(fmt='PNG', size=(9, 6), exif=None):
    picture = Image.new('RGB', size, '#8eaaa1')
    out = BytesIO()
    picture.save(out, format=fmt, **({'exif': exif} if exif else {}))
    mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp', 'GIF': 'image/gif'}[fmt]
    return {'name': '合成.' + {'JPEG': 'jpeg'}.get(fmt, fmt.lower()), 'mimeType': mime,
            'dataBase64': base64.b64encode(out.getvalue()).decode()}


def business_snapshot(app):
    with connection(app) as con:
        return {table: [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                for table in ('entities', 'journey_workflows', 'journey_links', 'journey_actions', 'journey_documents', 'audit')}


def test_pdf_private_upload_list_download_and_no_plan_projection(app, setup):
    client, headers, trip = setup
    before = client.get('/api/journeys/' + trip['id']).json
    item, _ = upload(client, headers, trip['id'], segmentKey='hotel')
    assert set(item) == {'id','journeyId','owner','title','filename','mimeType','bytes','visibility','segmentKey',
                         'unlinked','createdAt','updatedAt','revision','segmentMissing','canManage','downloadUrl'}
    assert item['visibility'] == 'private' and item['canManage'] and not item['segmentMissing'] and not item['unlinked']
    response = client.get('/api/journey-documents', query_string={'journeyId': trip['id']})
    assert response.status_code == 200
    assert set(response.json) == {'journey','segments','journeys','documents','limits'}
    assert response.json['journey']['id'] == trip['id']
    assert response.json['segments'] == [{'key':'hotel','title':'合成酒店','kind':'legacy_day'}]
    assert response.json['documents'] == [item]
    assert response.json['limits']['maxFileBytes'] == 5_000_000
    own = client.get('/api/journey-documents').json
    assert own['journey'] is None and own['segments'] == [] and own['documents'] == [item]
    result = client.get(item['downloadUrl'])
    assert result.data == PDF and result.mimetype == 'application/pdf'
    assert result.headers['Content-Disposition'].startswith('attachment;')
    assert 'no-store' in result.headers['Cache-Control'] and result.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'ETag' not in result.headers
    assert client.get('/api/journeys/' + trip['id']).json == before
    for endpoint in ('/api/state', '/api/journeys/' + trip['id'] + '/calendar.ics', '/api/assistant/brief'):
        text = client.get(endpoint).get_data(as_text=True)
        assert item['title'] not in text and item['id'] not in text and 'SYNTHETIC TICKET' not in text


def test_owner_shared_partner_private_and_tv_all_routes(app, setup):
    client, headers, trip = setup
    partner, ph = login(app, 2)
    item, _ = upload(client, headers, trip['id'])
    assert partner.get('/api/journey-documents').json['documents'] == []
    assert partner.get('/api/journey-documents', query_string={'journeyId': trip['id']}).json['documents'] == []
    for method, suffix, body in [('get','/file',None),('patch','',patch_value(item)),('delete','',{'revision':1})]:
        assert getattr(partner, method)(path(item)+suffix, json=body, headers=ph).status_code == 404
    updated = client.patch(path(item), json=patch_value(item, visibility='shared'), headers=headers).json['document']
    assert not partner.get('/api/journey-documents', query_string={'journeyId': trip['id']}).json['documents'][0]['canManage']
    assert partner.get(updated['downloadUrl']).data == PDF
    assert partner.patch(path(item), json=patch_value(updated), headers=ph).status_code == 403
    assert partner.delete(path(item), json={'revision':updated['revision']}, headers=ph).status_code == 403
    assert partner.get('/api/journey-documents').json['documents'] == []
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code':pairing['code'],'name':'合成电视','focus':'shared'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret':pairing['secret']}).json['approved']
    for method, endpoint, data in [('get','/api/journey-documents',None), ('get',item['downloadUrl'],None),
            ('post','/api/journey-documents',payload(trip['id'])), ('patch',path(item),patch_value(updated)),
            ('delete',path(item),{'revision':updated['revision']})]:
        assert getattr(tv, method)(endpoint, json=data, headers=headers).status_code == 403
        assert getattr(app.test_client(), method)(endpoint, json=data, headers=headers).status_code == 401
    assert item['id'] not in tv.get('/api/state').get_data(as_text=True)


def test_upload_csrf_origin_and_non_json_rejected(app, setup):
    client, headers, trip = setup
    value = payload(trip['id'])
    before = business_snapshot(app)
    assert client.post('/api/journey-documents', json=value).status_code == 403
    assert client.post('/api/journey-documents', json=value, headers={**headers,'Origin':'https://external.invalid'}).status_code == 403
    assert client.post('/api/journey-documents', data=b'file', headers=headers).status_code == 415
    assert business_snapshot(app) == before


@pytest.mark.parametrize('changes', [
    {'extra':1}, {'journeyId':None}, {'journeyId':1}, {'requestId':True}, {'requestId':'A'*32}, {'requestId':'a'*31},
    {'title':None}, {'title':[]}, {'title':' '}, {'title':'x'*121}, {'title':'bad\nheader'}, {'visibility':None},
    {'visibility':[]}, {'visibility':'public'}, {'segmentKey':None}, {'segmentKey':[]}, {'segmentKey':'missing'},
])
def test_upload_strict_shape_and_metadata_no_rows(app, setup, changes):
    client, headers, trip = setup
    before = business_snapshot(app)
    result = client.post('/api/journey-documents', json=payload(trip['id'], **changes), headers=headers)
    assert result.status_code in (400,409), result.json
    assert business_snapshot(app) == before


@pytest.mark.parametrize('file_changes', [
    {'extra':'bad'}, {'name':'../ticket.pdf'}, {'name':'C:\\ticket.pdf'}, {'name':'x\r\n.pdf'},
    {'name':'x.html'}, {'name':'x.jpg'}, {'mimeType':'text/html'}, {'mimeType':[]}, {'dataBase64':None},
    {'dataBase64':'%%%bad'}, {'dataBase64':''}, {'dataBase64':'中'},
    {'dataBase64':base64.b64encode(b'%PDF-1.7\nmissing ending').decode()},
    {'dataBase64':base64.b64encode(b'not pdf\n%%EOF').decode()},
    {'dataBase64':base64.b64encode(PDF+b'<html>after eof').decode()},
])
def test_file_format_validation_keeps_business_unchanged(app, setup, file_changes):
    client, headers, trip = setup
    value = payload(trip['id'])
    value['file'].update(file_changes)
    before = business_snapshot(app)
    result = client.post('/api/journey-documents', json=value, headers=headers)
    assert result.status_code == 400, result.json
    assert business_snapshot(app) == before


@pytest.mark.parametrize('fmt', ['JPEG','PNG','WEBP'])
def test_images_are_decoded_and_saved_as_clean_jpeg(app, setup, fmt):
    client, headers, trip = setup
    exif = Image.Exif()
    exif[274], exif[270] = 6, 'PRIVATE-EXIF-MARKER'
    value = image_file(fmt, exif=exif if fmt == 'JPEG' else None)
    item, _ = upload(client, headers, trip['id'], file=value)
    response = client.get(item['downloadUrl'])
    assert response.mimetype == 'image/jpeg' and item['filename'].endswith('.jpg')
    assert item['bytes'] == len(response.data)
    with Image.open(BytesIO(response.data)) as clean:
        assert clean.format == 'JPEG' and not clean.getexif() and 'icc_profile' not in clean.info
        assert clean.size == ((6,9) if fmt == 'JPEG' else (9,6))
    assert b'PRIVATE-EXIF-MARKER' not in response.data


@pytest.mark.parametrize('case', ['disguised-gif','wrong-mime','pixel-cap','animated'])
def test_invalid_images_reject_and_decoder_slot_recovers(app, setup, case):
    client, headers, trip = setup
    if case == 'disguised-gif':
        file = image_file('GIF'); file.update(name='x.png',mimeType='image/png')
    elif case == 'wrong-mime':
        file = image_file('PNG'); file.update(name='x.jpg',mimeType='image/jpeg')
    elif case == 'pixel-cap':
        file = image_file('PNG', (2001,2000))
    else:
        out=BytesIO(); Image.new('RGB',(4,4),'red').save(out,format='WEBP',save_all=True,append_images=[Image.new('RGB',(4,4),'blue')],duration=100)
        file={'name':'x.webp','mimeType':'image/webp','dataBase64':base64.b64encode(out.getvalue()).decode()}
    before=business_snapshot(app)
    assert client.post('/api/journey-documents',json=payload(trip['id'],file=file),headers=headers).status_code==400
    assert business_snapshot(app)==before
    upload(client,headers,trip['id'],file=image_file())


def test_busy_decoder_returns_429_then_can_retry_same_request(app, setup):
    client,headers,trip=setup
    value=payload(trip['id'],file=image_file())
    assert documents.DECODE_SLOT.acquire(blocking=False)
    try:
        assert client.post('/api/journey-documents',json=value,headers=headers).status_code==429
    finally:
        documents.DECODE_SLOT.release()
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==201


def test_exact_file_size_and_raw_overflow_limits(app, setup):
    client,headers,trip=setup
    value=payload(trip['id'])
    raw=b'%PDF-1.7\n'+b' '*(5_000_000-16)+b'\n%%EOF\n'
    assert len(raw)==5_000_000
    value['file']['dataBase64']=base64.b64encode(raw).decode()
    result=client.post('/api/journey-documents',json=value,headers=headers)
    assert result.status_code==201, result.json
    assert client.get(result.json['document']['downloadUrl']).data==raw
    value['requestId']=secrets.token_hex(16)
    value['file']['dataBase64']=base64.b64encode(raw+b' ').decode()
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==413
    assert len(client.get('/api/journey-documents').json['documents'])==1


@pytest.mark.parametrize('limit', ['MAX_DOCUMENTS','MAX_TOTAL_BYTES','MAX_JOURNEY_DOCUMENTS'])
def test_quotas_atomic_and_delete_frees_active_capacity(app, setup, monkeypatch, limit):
    client,headers,trip=setup
    monkeypatch.setattr(documents,limit,len(PDF) if limit=='MAX_TOTAL_BYTES' else 1)
    item,_=upload(client,headers,trip['id'])
    value=payload(trip['id'])
    before=business_snapshot(app)
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==409
    assert business_snapshot(app)==before
    assert client.delete(path(item),json={'revision':1},headers=headers).status_code==200
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==201


def test_idempotency_uses_original_payload_but_returns_current_metadata(app, setup):
    client,headers,trip=setup
    item,value=upload(client,headers,trip['id'])
    patch=client.patch(path(item),json=patch_value(item,title='更改后的名称',visibility='shared'),headers=headers)
    assert patch.status_code==200
    before=business_snapshot(app)
    replay=client.post('/api/journey-documents',json=value,headers=headers)
    assert replay.status_code==200 and replay.json=={'document':patch.json['document'],'replayed':True}
    assert business_snapshot(app)==before
    for changed in ({'title':'different'},{'visibility':'shared'},{'segmentKey':'hotel'}, {'journeyId':'f'*24}):
        assert client.post('/api/journey-documents',json={**value,**changed},headers=headers).status_code==409
    different=deepcopy(value);different['file']['dataBase64']=base64.b64encode(PDF+b' ').decode()
    assert client.post('/api/journey-documents',json=different,headers=headers).status_code==409


def test_delete_scrubs_blob_and_metadata_but_never_revives_request(app, setup):
    client,headers,trip=setup
    item,value=upload(client,headers,trip['id'],segmentKey='hotel',visibility='shared')
    assert client.delete(path(item),json={'revision':1},headers=headers).json=={'deleted':True,'id':item['id']}
    assert client.get(item['downloadUrl']).status_code==404
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==409
    assert client.patch(path(item),json=patch_value(item),headers=headers).status_code==404
    assert client.delete(path(item),json={'revision':2},headers=headers).status_code==404
    with connection(app) as con:
        row=con.execute('SELECT * FROM journey_documents').fetchone()
        assert row['content']==b'' and row['bytes']==0 and row['title']==row['filename']==row['mime_type']==row['segment_key']==''
        assert row['journey_id'] is None and row['deleted_at'] and row['owner']=='member1'
        assert row['request_id']==value['requestId'] and len(row['payload_digest'])==64 and row['revision']==2


@pytest.mark.parametrize('bad_revision', [True,False,0,-1,1.0,'1',None])
def test_revision_type_is_strict_on_patch_and_delete(app, setup, bad_revision):
    client,headers,trip=setup
    item,_=upload(client,headers,trip['id'])
    before=business_snapshot(app)
    assert client.patch(path(item),json=patch_value(item,revision=bad_revision),headers=headers).status_code==400
    assert client.delete(path(item),json={'revision':bad_revision},headers=headers).status_code==400
    assert business_snapshot(app)==before


def test_queries_patch_shape_and_missing_parent(app, setup):
    client,headers,trip=setup
    item,_=upload(client,headers,trip['id'])
    for query in ('page=0','documentId='+item['id'],'journeyId=','journeyId='+trip['id']+'&journeyId='+trip['id']):
        assert client.get('/api/journey-documents?'+query).status_code==400
    assert client.get('/api/journey-documents?journeyId='+'f'*24).status_code==404
    assert client.post('/api/journey-documents',json=payload('f'*24),headers=headers).status_code==404
    value=patch_value(item)
    for key in value:
        assert client.patch(path(item),json={k:v for k,v in value.items() if k!=key},headers=headers).status_code==400
    assert client.patch(path(item),json={**value,'owner':'member2'},headers=headers).status_code==400
    assert client.delete(path(item),json={'revision':1,'force':True},headers=headers).status_code==400
    assert client.patch(path(item),json=patch_value(item,journeyId=None,visibility='shared'),headers=headers).status_code==400
    assert client.patch(path(item),json=patch_value(item,journeyId=None,segmentKey='hotel'),headers=headers).status_code==400


def test_segment_removal_keeps_file_and_new_association_must_exist(app, setup):
    client,headers,trip=setup
    item,_=upload(client,headers,trip['id'],segmentKey='hotel')
    detail=client.get('/api/journeys/'+trip['id']).json
    plan=deepcopy(detail['plan']);plan['segments']=[]
    preview=client.post('/api/journeys/preview',json={'journeyId':trip['id'],'revision':detail['revision'],'plan':plan},headers=headers)
    assert preview.status_code==200, preview.json
    result=client.post('/api/journeys/apply',json={'previewToken':preview.json['previewToken'],'idempotencyKey':secrets.token_hex(16)},headers=headers)
    assert result.status_code==200, result.json
    current=client.get('/api/journey-documents?journeyId='+trip['id']).json['documents'][0]
    assert current['segmentMissing'] and current['revision']==1
    assert client.get(item['downloadUrl']).data==PDF
    renamed=client.patch(path(item),json=patch_value(current,title='保留缺失分段的资料'),headers=headers)
    assert renamed.status_code==200 and renamed.json['document']['segmentMissing']
    assert client.patch(path(item),json=patch_value(renamed.json['document'],segmentKey='another-missing'),headers=headers).status_code==409
    assert client.post('/api/journey-documents',json=payload(trip['id'],segmentKey='hotel'),headers=headers).status_code==409


def test_partner_deleting_journey_preserves_owner_file_and_invalidates_old_revision(app, setup):
    client,headers,trip=setup
    partner,ph=login(app,2)
    item,value=upload(client,headers,trip['id'],visibility='shared',segmentKey='hotel')
    entity=client.get('/api/journeys/'+trip['id']).json['trip']
    assert partner.delete('/api/items/trips/'+trip['tripId'],json={'revision':entity['revision']},headers=ph).status_code==200
    assert client.get(item['downloadUrl']).data==PDF
    assert partner.get(item['downloadUrl']).status_code==404
    current=client.get('/api/journey-documents').json['documents'][0]
    assert current['journeyId'] is None and current['unlinked'] and current['visibility']=='private' and current['segmentMissing']
    assert current['revision']==2 and current['updatedAt']!=item['updatedAt']
    assert client.patch(path(item),json=patch_value(item,title='过时'),headers=headers).status_code==409
    assert client.delete(path(item),json={'revision':1},headers=headers).status_code==409
    assert client.post('/api/journey-documents',json=value,headers=headers).json=={'document':current,'replayed':True}
    second=create_journey(client,headers,'重新归档旅行')
    associated=client.patch(path(item),json=patch_value(current,journeyId=second['id'],segmentKey='hotel',visibility='shared'),headers=headers)
    assert associated.status_code==200 and associated.json['document']['revision']==3
    assert partner.get(item['downloadUrl']).status_code==200


def test_explicit_unlink_single_revision_and_reassociation_quota(app, setup, monkeypatch):
    client,headers,trip=setup
    item,_=upload(client,headers,trip['id'],visibility='shared')
    current=client.patch(path(item),json=patch_value(item,journeyId=None),headers=headers).json
    assert current['error']
    current=client.patch(path(item),json=patch_value(item,journeyId=None,visibility='private'),headers=headers).json['document']
    assert current['revision']==2 and current['unlinked']
    upload(client,headers,trip['id'])
    monkeypatch.setattr(documents,'MAX_JOURNEY_DOCUMENTS',1)
    assert client.patch(path(item),json=patch_value(current,journeyId=trip['id']),headers=headers).status_code==409


def test_concurrent_upload_same_request_is_one_blob_and_one_audit(app, setup):
    client,headers,trip=setup
    clients=[clone(app,client),clone(app,client)]
    value=payload(trip['id'])
    barrier=threading.Barrier(2)
    def write(c):
        barrier.wait(timeout=5)
        return c.post('/api/journey-documents',json=value,headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(write,clients))
    assert sorted(r.status_code for r in results)==[200,201]
    assert len({r.json['document']['id'] for r in results})==1
    with connection(app) as con:
        assert tuple(con.execute('SELECT count(*),sum(bytes) FROM journey_documents').fetchone())==(1,len(PDF))
        assert con.execute("SELECT count(*) FROM audit WHERE action='journey_document_upload'").fetchone()[0]==1


def test_concurrent_cas_only_one_change_commits(app, setup):
    client,headers,trip=setup
    item,_=upload(client,headers,trip['id'])
    clients=[clone(app,client),clone(app,client)]
    barrier=threading.Barrier(2)
    def write(args):
        index,c=args;barrier.wait(timeout=5)
        return c.patch(path(item),json=patch_value(item,title='并发名称'+str(index)),headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(write,enumerate(clients)))
    assert sorted(r.status_code for r in results)==[200,409]
    current=client.get('/api/journey-documents').json['documents'][0]
    assert current['revision']==2 and client.get(item['downloadUrl']).data==PDF


def test_concurrent_quota_does_not_overfill(app, setup, monkeypatch):
    client,headers,trip=setup
    monkeypatch.setattr(documents,'MAX_DOCUMENTS',1)
    clients=[clone(app,client),clone(app,client)]
    barrier=threading.Barrier(2)
    def write(c):
        value=payload(trip['id']);barrier.wait(timeout=5)
        return c.post('/api/journey-documents',json=value,headers=headers)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(write,clients))
    assert sorted(r.status_code for r in results)==[201,409]
    assert len(client.get('/api/journey-documents').json['documents'])==1


def test_audit_failure_rolls_back_blob_reference_and_idempotency(app, setup):
    client,headers,trip=setup
    value=payload(trip['id'])
    with connection(app) as con:
        con.execute("CREATE TRIGGER reject_document_audit BEFORE INSERT ON audit WHEN NEW.action='journey_document_upload' BEGIN SELECT RAISE(ABORT,'synthetic rollback'); END")
    before=business_snapshot(app)
    with pytest.raises(sqlite3.IntegrityError,match='synthetic rollback'):
        client.post('/api/journey-documents',json=value,headers=headers)
    assert business_snapshot(app)==before
    with connection(app) as con:
        con.execute('DROP TRIGGER reject_document_audit')
    assert client.post('/api/journey-documents',json=value,headers=headers).status_code==201


def test_revoked_session_during_decode_cannot_commit(app, setup, monkeypatch):
    client,headers,trip=setup
    actor=clone(app,client)
    original=documents.Image.open
    called=[]
    def revoked(*args,**kwargs):
        if not called:
            called.append(True)
            assert actor.post('/api/logout',json={},headers=headers).status_code==200
        return original(*args,**kwargs)
    monkeypatch.setattr(documents.Image,'open',revoked)
    response=client.post('/api/journey-documents',json=payload(trip['id'],file=image_file()),headers=headers)
    assert response.status_code==401 and called
    with connection(app) as con:
        assert con.execute('SELECT count(*) FROM journey_documents').fetchone()[0]==0


def test_households_with_same_journey_document_ids_remain_separate(app, monkeypatch):
    primary,h=login(app)
    invitation=primary.post('/api/spaces/invitations',json={},headers=h).json['invitation']
    child=app.test_client()
    created=child.post('/api/spaces/redeem',json={'invitation':invitation,'name':'第二合成家庭','slug':'documents-second',
        'MEMBER1_PASSWORD':PASSWORD,'MEMBER2_PASSWORD':PASSWORD})
    assert created.status_code==201, created.json
    assert child.get(created.json['entry']).status_code==303
    child,ch=login(app,client=child)
    original=secrets.token_hex
    def create_same(c,headers):
        counter=iter(range(100,200))
        with monkeypatch.context() as change:
            change.setattr(journey_workflows.secrets,'token_hex',lambda n:format(next(counter),'024x') if n==12 else original(n))
            return create_journey(c,headers)
    a=create_same(primary,h);b=create_same(child,ch)
    assert a['id']==b['id']
    value=payload(a['id'],requestId='c'*32,title='MAIN-PRIVATE-DOCUMENT')
    with monkeypatch.context() as change:
        change.setattr(documents.secrets,'token_hex',lambda n:'d'*32 if n==16 else original(n))
        first=primary.post('/api/journey-documents',json=value,headers=h)
        second=child.post('/api/journey-documents',json={**value,'title':'CHILD-PRIVATE-DOCUMENT'},headers=ch)
    assert first.status_code==second.status_code==201
    assert first.json['document']['id']==second.json['document']['id']
    assert 'MAIN-PRIVATE-DOCUMENT' not in child.get('/api/journey-documents').get_data(as_text=True)
    assert 'CHILD-PRIVATE-DOCUMENT' not in primary.get('/api/journey-documents').get_data(as_text=True)
    child.set_cookie('session',primary.get_cookie('session').value)
    assert child.get(first.json['document']['downloadUrl']).status_code==401


def test_export_hook_is_read_only_and_never_selects_blob(app, setup):
    client,headers,trip=setup
    other,oh=login(app,2)
    own,_=upload(client,headers,trip['id'])
    shared,_=upload(other,oh,trip['id'],visibility='shared')
    upload(other,oh,trip['id'],title='HIDDEN-PARTNER-DOCUMENT')
    with connection(app) as con:
        trace=[];con.set_trace_callback(trace.append)
        before=con.total_changes
        value=documents.exported_documents(con,'member1',True)
        assert con.total_changes==before and len(value['personal'])==len(value['shared'])==1
        assert value['personal'][0]['id']==own['id'] and value['shared'][0]['id']==shared['id']
        assert not {'downloadUrl','requestId','payloadDigest','content','canManage'} & set(value['personal'][0])
        assert all('content' not in statement.lower() and 'select *' not in statement.lower() for statement in trace)
    empty=sqlite3.connect(':memory:');empty.row_factory=sqlite3.Row
    assert documents.exported_documents(empty,'member1',True)=={'personal':[],'shared':[]}
    assert empty.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]==0
    empty.close()


def test_schema_is_repeatable_and_backup_preserves_file_and_tombstone(app, setup, tmp_path):
    client,headers,trip=setup
    live,_=upload(client,headers,trip['id'])
    dead,original=upload(client,headers,trip['id'])
    assert client.delete(path(dead),json={'revision':1},headers=headers).status_code==200
    with connection(app) as con:
        before=[tuple(r) for r in con.execute('SELECT * FROM journey_documents ORDER BY id')]
        con.executescript(documents.SCHEMA_SQL)
        assert [tuple(r) for r in con.execute('SELECT * FROM journey_documents ORDER BY id')]==before
        copy=sqlite3.connect(tmp_path/'synthetic-backup.sqlite3')
        con.backup(copy)
        assert copy.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert copy.execute('SELECT content FROM journey_documents WHERE id=?',(live['id'],)).fetchone()[0]==PDF
        row=copy.execute('SELECT content,request_id,payload_digest FROM journey_documents WHERE id=?',(dead['id'],)).fetchone()
        assert row[0]==b'' and row[1]==original['requestId'] and len(row[2])==64
        assert copy.execute('PRAGMA foreign_key_check').fetchall()==[]
        copy.close()
