"""Synthetic travel files and stable segment navigation, real loopback Flask/Edge.

No real accounts, provider IO, production data or public domains. HTTP races hold
actual responses; accepted writes are checked in SQLite before their UI resumes.
"""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
from PIL import Image
from playwright.sync_api import expect,sync_playwright
from werkzeug.serving import make_server,WSGIRequestHandler

PDF=b'%PDF-1.7\nsynthetic travel document\n%%EOF\n'


class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):pass


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths=set(ROOT.glob('*.py'))|{Path(__file__)}
    for folder in ('static','deploy'):
        paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(ROOT/name for name in ('Dockerfile','compose.yaml','requirements.txt','pytest.ini') if (ROOT/name).exists())
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths)}


def check_segment_focus_after_refresh(page, context, base, journey_id, segment_key):
    """Use the real polling timer and a shared task change to force a body repaint."""
    expect(page.locator('[data-journey=refresh-execution]')).to_be_enabled()
    cards=page.locator('.journey-itinerary-item')
    assert cards.nth(1).get_attribute('data-segment-key')==segment_key
    card=page.locator('.journey-itinerary-item[data-segment-key="'+segment_key+'"]')
    title=card.locator('h3').inner_text()
    first_title=cards.first.locator('h3').inner_text()
    assert title!=first_title
    button=card.locator('[data-journey=copy-segment]')
    page.evaluate("()=>navigator.clipboard.writeText('')")
    button.focus();original=button.element_handle()
    state=context.request.get(base+'/api/journeys/'+journey_id)
    assert state.status==200
    task=state.json()['tasks'][0]
    member=context.request.get(base+'/api/me')
    assert member.status==200
    updated=context.request.patch(base+'/api/items/tasks/'+task['id'],headers={'X-CSRF-Token':member.json()['csrf']},
                                  data={'revision':task['revision'],'done':not task['done']})
    assert updated.status==200
    page.wait_for_function('(node)=>!node.isConnected',arg=original,timeout=20000)
    expect(button).to_be_focused()
    assert button.get_attribute('data-segment-key')==segment_key
    page.keyboard.press('Enter')
    page.wait_for_function('(title)=>navigator.clipboard.readText().then(text=>text.includes(title))',arg=title)
    copied=page.evaluate('()=>navigator.clipboard.readText()')
    assert title in copied and first_title not in copied


def main():
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%dT%H%M%S%f')
    report_path=out/'journey-documents-browser-verification.json'
    if report_path.exists():shutil.copy2(report_path,out/('journey-documents-browser-history-'+stamp+'.json'))
    report={'passed':False,'checks':[],'screenshots':[],'pageErrors':[],'externalRequests':[],'providerCalls':[],
            'requestCounts':{},'sourceHashes':sources(),'realCloudWrites':0,'productionWrites':0,'realPrivateInputs':0,
            'scope':'Real temporary Flask/SQLite/Edge; synthetic PDF/images and two households; loopback only.',
            'knownBoundary':'A cookie-only switch after the final identity response cannot be observed atomically; started downloads cannot be recalled.'}
    def passed(name):report['checks'].append({'name':name,'passed':True});print('PASS '+name,flush=True)
    def deny(*args,**kwargs):report['providerCalls'].append('blocked');raise AssertionError('Provider forbidden')
    original_connect,original_dns=socket.socket.connect,socket.getaddrinfo
    def allowed(host):return host in ('127.0.0.1','::1','localhost',b'127.0.0.1',b'localhost',b'::1')
    def connect(sock,address):
        if isinstance(address,tuple) and not allowed(address[0]):report['externalRequests'].append('socket');raise AssertionError('External socket')
        return original_connect(sock,address)
    def dns(host,*args,**kwargs):
        if host is not None and not allowed(host):report['externalRequests'].append('dns');raise AssertionError('External DNS')
        return original_dns(host,*args,**kwargs)
    active=None
    try:
        with patch.object(socket.socket,'connect',connect),patch.object(socket,'getaddrinfo',dns),tempfile.TemporaryDirectory(prefix='journey-documents-browser-') as folder:
            app=create_app({'TESTING':True,'DATA_DIR':folder,'SECRET_KEY':'synthetic-travel-documents-key','SESSION_COOKIE_SECURE':False,
                            'PUBLIC_ORIGIN':'http://localhost','MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two',
                            'CLOUD_TRANSPORT':deny,'OAUTH_TRANSPORT':deny,'OPENAI_API_KEY':'','OPENAI_MODEL':''})
            dbpath=Path(folder)/'household.sqlite3'
            def sql(query,args=()):
                with sqlite3.connect(dbpath) as con:con.row_factory=sqlite3.Row;return [dict(row) for row in con.execute(query,args)]
            client=app.test_client();assert client.post('/api/login',json={'username':'member1','password':'testing-password-one'}).status_code==200
            headers={'X-CSRF-Token':client.get('/api/me').json['csrf']}
            def post(path,data):
                response=client.post('/api'+path,json=data,headers=headers);assert response.status_code in (200,201),(path,response.status_code);return response.json
            plan=json.loads((ROOT/'static/examples/journey-plan-v2.json').read_text(encoding='utf-8'))
            plan['title']='虚构资料旅行 A';plan['segments'][0]['flightNumber']='SYNTH-321'
            for segment in plan['segments']:
                segment['note']='集合信息：虚构入口东侧；https://example.invalid/never-fetch'
                if segment['kind']=='stay':segment['location']='虚构市中心';segment['address']='虚构完整地址 123 号 4 楼'
            def create(value,key):
                preview=post('/journeys/preview',{'plan':value});return post('/journeys/apply',{'previewToken':preview['previewToken'],'idempotencyKey':key})['id']
            jid=create(plan,'synthetic-documents-a');other=create({**deepcopy(plan),'title':'虚构资料旅行 B'},'synthetic-documents-b')
            detail=client.get('/api/journeys/'+jid).json
            segment_key=next(row['key'] for row in detail['plan']['segments'] if row['kind']=='stay')
            original_links={row['id']:row['workflowKey'] for row in detail['events']}
            server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                    def login(ctx,number=1,child=False):
                        sql('DELETE FROM attempts');ctx.request.get(base+'/api/me')
                        response=ctx.request.post(base+'/api/login',data={'username':'member'+str(number),'password':('child-password-' if child else 'testing-password-')+('one' if number==1 else 'two')});assert response.status==200
                    def auth(ctx):return {'X-CSRF-Token':ctx.request.get(base+'/api/me').json()['csrf']}
                    admin=browser.new_context();login(admin)
                    invitation=admin.request.post(base+'/api/spaces/invitations',headers=auth(admin),data={});assert invitation.status==201
                    child=admin.request.post(base+'/api/spaces/redeem',data={'invitation':invitation.json()['invitation'],'name':'虚构资料第二家庭','slug':'synthetic-documents-child','MEMBER1_PASSWORD':'child-password-one','MEMBER2_PASSWORD':'child-password-two'});assert child.status==201
                    child_entry=child.json()['entry']
                    class Flow:
                        def __init__(self,number=1):
                            self.ctx=browser.new_context(viewport={'width':1440,'height':1050},permissions=['clipboard-read','clipboard-write'],accept_downloads=True)
                            self.calls=[];self.payloads=[];self.held=[];self.holding=None;self.fail=set()
                            self.ctx.add_init_script('window.jdPending=0;const actualFetch=fetch;window.fetch=async(...args)=>{window.jdPending++;try{return await actualFetch(...args);}finally{window.jdPending--;}};')
                            self.ctx.route('**/*',self.route);login(self.ctx,number)
                            self.page=self.ctx.new_page();self.page.on('pageerror',lambda e:report['pageErrors'].append(str(e)));self.page.goto(base+'/#trips');expect(self.page.locator('.ps-trip-grid')).to_be_visible()
                        def route(self,route):
                            request=route.request;path=urlsplit(request.url).path;key=(request.method,path)
                            if not request.url.startswith(base+'/'):report['externalRequests'].append(path);route.abort();return
                            self.calls.append(key);label=' '.join(key);report['requestCounts'][label]=report['requestCounts'].get(label,0)+1
                            if request.method=='POST' and path=='/api/journey-documents':self.payloads.append(request.post_data_json)
                            if key in self.fail:route.fulfill(status=503,json={'error':'synthetic unavailable'});return
                            if self.holding==key:
                                self.holding=None;self.held.append((route,route.fetch()));return
                            route.continue_()
                        def hold(self,path,method='GET'):self.holding=(method,path)
                        def waiting(self):
                            end=time.monotonic()+15
                            while not self.held and time.monotonic()<end:self.page.wait_for_timeout(25)
                            assert self.held,'expected held request'
                        def release(self,error=False):
                            route,response=self.held.pop(0)
                            if error:route.fulfill(status=503,json={'error':'synthetic late failure'})
                            else:route.fulfill(response=response)
                            self.page.wait_for_function('()=>window.jdPending===0',timeout=15000)
                        def open(self,j=jid,key=''):
                            self.page.evaluate('(o)=>JourneyDocuments.open(o)',{'journeyId':j,'segmentKey':key});expect(self.page.locator('[data-jd=upload]')).to_be_visible()
                        def upload(self,title='虚构私人资料',shared=False,image=False):
                            self.page.locator('[data-jd=upload]').click();form=self.page.locator('#journey-document-form');expect(form).to_be_visible();form.locator('[name=title]').fill(title)
                            content=PDF;name='synthetic.pdf';mime='application/pdf'
                            if image:
                                target=BytesIO();Image.new('RGB',(50,35),(22,90,120)).save(target,format='PNG');content=target.getvalue();name='synthetic.png';mime='image/png'
                            form.locator('[name=file]').set_input_files({'name':name,'mimeType':mime,'buffer':content})
                            if shared:form.locator('[name=shared]').check()
                            return form
                        def save(self,form):form.locator('[type=submit]').click();expect(self.page.locator('[data-jd-message]')).to_contain_text('已保存并读取最新资料')
                        def switch(self,number=2,household=False,boot=True):
                            if household:self.ctx.request.get(base+child_entry,max_redirects=0)
                            login(self.ctx,number,household)
                            if boot:self.page.evaluate('async()=>{await boot();}')
                        def close(self):
                            for route,response in self.held:route.fulfill(response=response)
                            self.held=[];self.ctx.close()
                    flow=Flow();active=flow
                    try:
                        flow.page.evaluate('(id)=>JourneyUI.open(id)',jid)
                        expect(flow.page.locator('.journey-itinerary-item').filter(has_text='SYNTH-321')).to_be_visible()
                        stay=flow.page.locator('.journey-itinerary-item[data-segment-key="'+segment_key+'"]')
                        expect(stay).to_contain_text('虚构市中心');expect(stay).to_contain_text('虚构完整地址 123 号 4 楼');expect(stay).to_contain_text('集合信息：虚构入口东侧')
                        assert not any(path.startswith('/api/journey-documents') for _,path in flow.calls)
                        passed('saved_flight_address_notes_visible_without_private_document_fetch')
                        stay.locator('[data-journey=copy-segment]').click();flow.page.wait_for_function("()=>navigator.clipboard.readText().then(t=>t.includes('虚构完整地址'))")
                        passed('explicit_copy_contains_saved_address_and_meeting_information')
                        check_segment_focus_after_refresh(flow.page,flow.ctx,base,jid,segment_key)
                        passed('automatic_repaint_keeps_second_segment_button_focus_and_Enter_copies_original_segment')
                        stay.locator('[data-journey=segment-edit]').click();expect(flow.page.locator('.journey-v2-segment.journey-segment-target')).to_have_attribute('data-key',segment_key)
                        form=flow.page.locator('#journey-form');form.locator('.journey-v2-segment[data-key="'+segment_key+'"] [name=note]').fill('已更新的合成集合信息')
                        form.locator('[type=submit]').click();flow.page.locator('#journey-apply').click();expect(flow.page.locator('.journey-itinerary-item.journey-segment-target')).to_have_attribute('data-segment-key',segment_key)
                        updated=client.get('/api/journeys/'+jid).json;assert original_links=={row['id']:row['workflowKey'] for row in updated['events']}
                        passed('stable_segment_editor_preview_save_returns_to_same_item_and_entity_ids')
                        flow.page.locator('.journey-itinerary-item[data-segment-key="'+segment_key+'"] [data-journey=segment-documents]').click();expect(flow.page.locator('.jd-filter')).to_contain_text('当前细项')
                        form=flow.upload('虚构资料'+('长'*105));assert not form.locator('[name=shared]').is_checked();flow.save(form)
                        rows=sql('SELECT id,visibility,segment_key,filename FROM journey_documents WHERE deleted_at IS NULL');private_id=rows[0]['id'];assert rows[0]['visibility']=='private' and rows[0]['segment_key']==segment_key
                        passed('segment_upload_is_private_by_default_and_explicitly_associated')
                        assert not any(path.endswith('/file') for _,path in flow.calls)
                        with flow.page.expect_download() as download:flow.page.locator('[data-jd=download]').click()
                        value=download.value;assert Path(value.path()).read_bytes()==PDF
                        assert flow.ctx.request.get(base+'/api/journey-documents/'+private_id+'/file').headers['cache-control'].find('no-store')>=0
                        passed('PDF_download_is_explicit_correct_bytes_and_not_embedded')
                        flow.page.locator(f'[data-document-id="{private_id}"] [data-jd=edit]').click();long_form=flow.page.locator('#journey-document-form');expect(long_form.locator('[name=title]')).to_have_attribute('maxlength','120');assert long_form.locator('[name=title]').evaluate('(n)=>n.checkValidity()');flow.save(long_form)
                        passed('existing_101_to_120_character_title_remains_editable')
                        form=flow.upload('大图拒绝后保留草稿');large=BytesIO();Image.new('RGB',(2100,2000),(22,40,70)).save(large,format='PNG');assert len(large.getvalue())<5000000
                        form.locator('[name=file]').set_input_files({'name':'large.png','mimeType':'image/png','buffer':large.getvalue()});form.locator('[type=submit]').click();expect(form.locator('[data-jd-message]')).to_contain_text('2000 × 2000');expect(form.locator('[name=title]')).to_have_value('大图拒绝后保留草稿')
                        small=BytesIO();Image.new('RGB',(50,40),(22,40,70)).save(small,format='PNG');form.locator('[name=file]').set_input_files({'name':'smaller.png','mimeType':'image/png','buffer':small.getvalue()});flow.save(form)
                        passed('oversize_pixel_image_has_actionable_message_and_smaller_file_retry_preserves_draft')
                        flow.open();form=flow.upload('虚构共享图片',shared=True,image=True);flow.save(form)
                        shared_id=sql("SELECT id FROM journey_documents WHERE title='虚构共享图片'")[0]['id'];assert sql('SELECT filename,mime_type FROM journey_documents WHERE id=?',(shared_id,))[0]=={'filename':'synthetic.jpg','mime_type':'image/jpeg'}
                        passed('explicit_shared_image_saved_as_sanitized_JPEG_with_actual_filename')
                        for theme in ('forest','light','ocean'):
                            for width in (360,768,1440):
                                flow.page.set_viewport_size({'width':width,'height':1000});flow.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                                assert flow.page.locator('#dialog').evaluate('(n)=>n.scrollWidth<=n.clientWidth+2')
                                path=out/f'journey-documents-{theme}-{width}-{stamp}.png';flow.page.screenshot(path=str(path),full_page=True);report['screenshots'].append({'path':str(path),'sha256':sha(path)})
                        passed('three_themes_and_three_widths_have_no_horizontal_overflow')
                        flow.page.set_viewport_size({'width':1440,'height':1050})
                        flow.page.locator(f'[data-document-id="{private_id}"] [data-jd=edit]').click();form=flow.page.locator('#journey-document-form');form.locator('[name=journeyId]').select_option(other)
                        expect(form.locator('[name=segmentKey]')).to_be_enabled();form.locator('[name=segmentKey]').select_option(segment_key);flow.save(form)
                        assert sql('SELECT journey_id FROM journey_documents WHERE id=?',(private_id,))[0]['journey_id']==other
                        passed('owner_reassociates_document_to_another_household_journey')
                        flow.page.locator(f'[data-document-id="{private_id}"] [data-jd=edit]').click();form=flow.page.locator('#journey-document-form');form.locator('[name=title]').fill('保留的本地草稿')
                        actual=flow.ctx.request.get(base+'/api/journey-documents').json()['documents'];doc=next(d for d in actual if d['id']==private_id)
                        changed=flow.ctx.request.patch(base+'/api/journey-documents/'+private_id,headers=auth(flow.ctx),data={'revision':doc['revision'],'title':'另一窗口的最新设置','visibility':'private','segmentKey':segment_key,'journeyId':other});assert changed.status==200
                        form.locator('[type=submit]').click();expect(form.locator('[data-jd-conflict]')).to_be_visible();expect(form.locator('[name=title]')).to_have_value('保留的本地草稿')
                        form.locator('[data-jd=latest]').click();expect(form.locator('[data-jd-conflict]')).to_contain_text('另一窗口的最新设置');expect(form.locator('[name=title]')).to_have_value('保留的本地草稿')
                        form.locator('[data-jd=use-latest]').click();expect(flow.page.locator('#journey-document-form [name=title]')).to_have_value('另一窗口的最新设置')
                        passed('revision_conflict_preserves_draft_and_latest_read_requires_explicit_adoption')
                        form=flow.page.locator('#journey-document-form');form.locator('[name=journeyId]').select_option('');flow.page.wait_for_function("()=>document.querySelector('#journey-document-form')._loadingSegments===false")
                        flow.save(form);assert sql('SELECT journey_id,visibility,segment_key FROM journey_documents WHERE id=?',(private_id,))[0]=={'journey_id':None,'visibility':'private','segment_key':''}
                        passed('explicit_detach_keeps_file_in_owner_library_private')
                        flow.page.locator(f'[data-document-id="{private_id}"] [data-jd=edit]').click();form=flow.page.locator('#journey-document-form');form.locator('[data-jd=delete]').click()
                        assert sql('SELECT deleted_at FROM journey_documents WHERE id=?',(private_id,))[0]['deleted_at'] is None
                        form.locator('[data-jd=cancel-delete]').click();assert form.is_visible();form.locator('[data-jd=delete]').click();form.locator('[data-jd=confirm-delete]').click();expect(flow.page.locator('[data-jd-message]')).to_contain_text('已保存并读取最新资料')
                        assert sql('SELECT deleted_at FROM journey_documents WHERE id=?',(private_id,))[0]['deleted_at'] is not None
                        passed('delete_requires_explicit_confirmation_and_clears_owner_file')
                    finally:flow.close()
                    partner=Flow(2);active=partner
                    try:
                        partner.open();expect(partner.page.locator(f'[data-document-id="{shared_id}"]')).to_be_visible();expect(partner.page.locator('[data-jd=edit]')).to_have_count(0)
                        assert partner.ctx.request.get(base+'/api/journey-documents/'+private_id+'/file').status==404
                        assert partner.ctx.request.patch(base+'/api/journey-documents/'+shared_id,headers=auth(partner.ctx),data={'revision':1,'title':'不能修改他人资料','visibility':'shared','segmentKey':'','journeyId':jid}).status==403
                        with partner.page.expect_download() as download:partner.page.locator('[data-jd=download]').click()
                        assert Path(download.value.path()).read_bytes().startswith(b'\xff\xd8')
                        partner.open('');expect(partner.page.locator('.jd-card')).to_have_count(0)
                        passed('partner_can_download_shared_only_has_no_management_and_owner_library_stays_private')
                    finally:partner.close()
                    for view in ('list','upload'):
                        for replacement in ('logout','member'):
                            flow=Flow();active=flow
                            try:
                                flow.open();private_title='空闲私人资料 '+view+' '+replacement
                                form=flow.upload(private_title)
                                if view=='list':flow.save(form);original=flow.page.locator('.jd-grid').element_handle()
                                else:original=form.element_handle()
                                flow.page.wait_for_function('()=>window.jdPending===0')
                                assert not flow.held
                                reads=sum(path.startswith('/api/journey-documents') for _,path in flow.calls)
                                if replacement=='logout':
                                    assert flow.ctx.request.post(base+'/api/logout',headers=auth(flow.ctx),data={}).status==200
                                    flow.page.evaluate('async()=>{await refresh(true);}')
                                    expect(flow.page.locator('#login-form')).to_be_visible()
                                else:flow.switch(2)
                                expect(flow.page.locator('[data-jd-root]')).to_contain_text('资料已收起')
                                assert not original.evaluate('(node)=>node.isConnected')
                                expect(flow.page.locator('#dialog')).not_to_contain_text(private_title)
                                expect(flow.page.locator('#dialog')).not_to_contain_text('synthetic.pdf')
                                expect(flow.page.locator('#journey-document-form')).to_have_count(0)
                                assert sum(path.startswith('/api/journey-documents') for _,path in flow.calls)==reads
                                passed('idle_'+view+'_'+replacement+'_redraw_clears_private_content_without_document_request_or_click')
                            finally:flow.close()
                    # A failed response may follow an already accepted upload.
                    flow=Flow();active=flow
                    try:
                        flow.open();form=flow.upload('未知结果只创建一份');flow.hold('/api/journey-documents','POST');form.locator('[type=submit]').click();flow.waiting()
                        assert len(sql("SELECT id FROM journey_documents WHERE title='未知结果只创建一份'"))==1
                        flow.release(True);expect(form.locator('[type=submit]')).to_be_enabled();flow.save(form)
                        assert flow.payloads[-1]==flow.payloads[-2] and len(sql("SELECT id FROM journey_documents WHERE title='未知结果只创建一份'"))==1
                        passed('lost_upload_response_retries_identical_payload_and_request_id_without_duplicate')
                        form=flow.upload('已保存但读回失败');flow.fail.add(('GET','/api/journey-documents'));form.locator('[type=submit]').click();expect(flow.page.locator('.jd-receipt')).to_contain_text('最新资料列表暂未读回')
                        uploads=len(flow.payloads);flow.fail.clear();flow.page.locator('[data-jd=refresh]').click();expect(flow.page.locator('.jd-card').filter(has_text='已保存但读回失败')).to_be_visible();assert len(flow.payloads)==uploads
                        passed('accepted_upload_then_readback_failure_retries_GET_only')
                    finally:flow.close()
                    for change in ('deleted_journey','reassociated'):
                        original_journey=create({**deepcopy(plan),'title':'虚构重放旅行 '+change},'synthetic-replay-'+change)
                        flow=Flow();active=flow
                        try:
                            flow.open(original_journey);title='原关联变化后重放 '+change
                            form=flow.upload(title);flow.hold('/api/journey-documents','POST');form.locator('[type=submit]').click();flow.waiting()
                            saved=sql('SELECT id FROM journey_documents WHERE title=?',(title,));assert len(saved)==1
                            document_id=saved[0]['id']
                            flow.release(True);expect(form.locator('[type=submit]')).to_be_enabled()
                            if change=='deleted_journey':
                                original=admin.request.get(base+'/api/journeys/'+original_journey).json()
                                deleted=admin.request.delete(base+'/api/items/trips/'+original['trip']['id'],headers=auth(admin),data={'revision':original['trip']['revision']})
                                assert deleted.status==200
                            else:
                                current=admin.request.get(base+'/api/journey-documents?journeyId='+original_journey).json()['documents'][0]
                                updated=admin.request.patch(base+'/api/journey-documents/'+document_id,headers=auth(admin),data={
                                    'revision':current['revision'],'title':current['title'],'visibility':'private','segmentKey':segment_key,'journeyId':other})
                                assert updated.status==200
                            flow.save(form)
                            assert flow.payloads[-1]==flow.payloads[-2]
                            expect(flow.page.locator(f'[data-document-id="{document_id}"]')).to_be_visible()
                            heading=flow.page.locator('.jd-heading h3')
                            expect(heading).to_have_text('我的旅行资料' if change=='deleted_journey' else '虚构资料旅行 B')
                            row=sql('SELECT journey_id FROM journey_documents WHERE id=?',(document_id,))[0]
                            assert row['journey_id']==(None if change=='deleted_journey' else other)
                            assert len(sql('SELECT id FROM journey_documents WHERE title=?',(title,)))==1
                            passed('accepted_upload_lost_response_'+change+'_replay_uses_current_document_location')
                        finally:flow.close()
                    for path,method in [('/api/journey-documents','GET'),('/api/journey-documents','POST'),('/api/journey-documents/'+shared_id+'/file','GET')]:
                        for replacement in ('draft','member','household'):
                            for error in (False,True):
                                flow=Flow();active=flow
                                try:
                                    if method=='POST':flow.open();form=flow.upload('迟到上传 '+replacement+str(error));flow.hold(path,method);form.locator('[type=submit]').click()
                                    elif path.endswith('/file'):flow.open();flow.hold(path);flow.page.locator(f'[data-document-id="{shared_id}"] [data-jd=download]').click()
                                    else:flow.hold(path);flow.page.evaluate('(id)=>{void JourneyDocuments.open({journeyId:id});}',jid)
                                    flow.waiting()
                                    if replacement=='draft':flow.page.evaluate('()=>JourneyUI.create()');flow.page.locator('#journey-core-fields [name=title]').fill('新草稿不得覆盖');marker=flow.page.locator('#journey-form')
                                    else:
                                        flow.switch(2,replacement=='household');flow.page.evaluate('()=>{void JourneyDocuments.open();}');expect(flow.page.locator('[data-jd=upload]')).to_be_visible();marker=flow.page.locator('[data-jd-root]')
                                    handle=marker.element_handle();flow.release(error);assert handle.evaluate('(node)=>node.isConnected')
                                    if replacement=='draft':expect(flow.page.locator('#journey-core-fields [name=title]')).to_have_value('新草稿不得覆盖')
                                    else:expect(flow.page.locator('[data-jd-root]')).not_to_contain_text('虚构共享图片')
                                    passed(method+'_'+path.rsplit('/',1)[-1]+'_late_'+str(error)+'_preserves_'+replacement)
                                finally:flow.close()
                    flow=Flow();active=flow
                    try:
                        flow.hold('/api/journey-documents');flow.page.evaluate('(id)=>{void JourneyDocuments.open({journeyId:id});}',jid);flow.waiting();flow.switch(2,boot=False);flow.release();expect(flow.page.locator('[data-jd-root]')).to_contain_text('登录成员或家庭已变化');expect(flow.page.locator('.jd-card')).to_have_count(0)
                        passed('cookie_only_member_switch_rejected_by_fresh_identity_check')
                    finally:flow.close()
                    for route in ('/demo','/demo?tv=1'):
                        ctx=browser.new_context();page=ctx.new_page();page.goto(base+route);page.wait_for_function('()=>typeof JourneyDocuments!=="undefined"');before=len(sql('SELECT id FROM journey_documents'))
                        page.evaluate('()=>JourneyDocuments.open()');expect(page.locator('[data-jd-root]')).to_have_count(0);assert len(sql('SELECT id FROM journey_documents'))==before;ctx.close()
                    tv=browser.new_context();pair=tv.request.post(base+'/api/pair/start',data={}).json();approve=admin.request.post(base+'/api/pair/approve',headers=auth(admin),data={'code':pair['code'],'name':'虚构资料电视','focus':'shared'});assert approve.status==200
                    assert tv.request.post(base+'/api/pair/poll',data={'secret':pair['secret']}).json()['approved']
                    assert tv.request.get(base+'/api/journey-documents').status==403 and tv.request.get(base+'/api/journey-documents/'+shared_id+'/file').status==403
                    page=tv.new_page();page.goto(base+'/tv');page.wait_for_function('()=>typeof JourneyDocuments!=="undefined"');page.evaluate('()=>JourneyDocuments.open()');expect(page.locator('[data-jd-root]')).to_have_count(0);tv.close()
                    passed('demo_and_TV_have_no_document_UI_and_real_TV_APIs_are_forbidden')
                    admin.close();browser.close()
            finally:server.shutdown();server.server_close();thread.join(timeout=5)
        assert not report['externalRequests'] and not report['pageErrors'] and not report['providerCalls']
        report['passed']=True
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error);report['traceback']=traceback.format_exc();print(report['traceback'],flush=True)
    finally:
        report['sourceHashesAfter']=sources();report['sourceUnchanged']=report['sourceHashes']==report['sourceHashesAfter'];report['passed']=report['passed'] and report['sourceUnchanged'];report['checkCount']=len(report['checks'])
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'sourceUnchanged':report['sourceUnchanged'],'report':str(report_path)}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
