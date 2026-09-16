"""Synthetic transports only; no OAuth, accounts, providers or network calls."""
from copy import deepcopy
from email.message import Message
from io import BytesIO
import json
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

import google_photos_picker as picker

TOKEN='synthetic-picker-access-token-89b8cd'
SESSION='synthetic-session-1'
PNG=b'\x89PNG\r\n\x1a\nsynthetic-not-a-decoded-image'
MP4=b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00synthetic-not-a-decoded-video'


def session(ready=True, **changes):
    value={'id':SESSION,'pickerUri':'https://photos.google.com/picker/synthetic',
           'expireTime':'2030-01-01T00:00:00Z','mediaItemsSet':ready,
           'pickingConfig':{'maxItemCount':'100'}}
    if not ready:
        value['pollingConfig']={'pollInterval':'5.000000001s','timeoutIn':'600s'}
    value.update(changes)
    return value


def item(identifier='media-1',kind='PHOTO',status='READY', **changes):
    value={'id':identifier,'createTime':'2025-01-02T03:04:05.123456789Z','type':kind,
           'mediaFile':{'baseUrl':'https://lh3.googleusercontent.com/p/synthetic-'+identifier,
                        'mimeType':'image/png' if kind=='PHOTO' else 'video/mp4',
                        'filename':'合成照片.png' if kind=='PHOTO' else '合成视频.mp4',
                        'mediaFileMetadata':{'width':200,'height':100}}}
    if kind=='VIDEO':
        value['mediaFile']['mediaFileMetadata']['videoMetadata']={'processingStatus':status}
    value.update(changes)
    return value


class Response:
    def __init__(self, body=b'', status=200, mime='application/json', headers=None, url=None, chunk=65536, on_read=None):
        self.body=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
        self.status,self.url,self.chunk,self.on_read=status,url,chunk,on_read
        self.headers=Message()
        self.headers['Content-Type']=mime
        for key,value in (headers or {}).items():
            self.headers[key]=value
        self.closed=False
        self.cursor=0
        self.read_calls=0

    def geturl(self):
        return self.url

    def read1(self,size):
        self.read_calls+=1
        if self.on_read:
            self.on_read()
        end=min(len(self.body),self.cursor+min(size,self.chunk))
        data=self.body[self.cursor:end];self.cursor=end
        return data

    def close(self):
        self.closed=True


class Transport:
    def __init__(self,*responses):
        self.responses=list(responses)
        self.calls=[]

    def __call__(self,method,url,*,headers,body,timeout):
        self.calls.append({'method':method,'url':url,'headers':headers,'body':body,'timeout':timeout})
        if not self.responses:
            raise AssertionError('Unexpected synthetic request')
        response=self.responses.pop(0)
        if isinstance(response,Exception):
            raise response
        if not isinstance(response,Response):
            response=Response(response)
        response.url=response.url or url
        return response


@pytest.fixture(autouse=True)
def no_real_transport(monkeypatch):
    def blocked(*_args,**_kwargs):
        raise AssertionError('Real provider IO forbidden in tests')
    monkeypatch.setattr(picker,'_transport',blocked)


def selected(*extra, items=None):
    transport=Transport(session(),{'mediaItems':items or [item()]},*extra)
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    metadata=client.list_selected_media(SESSION)
    return client,transport,metadata


def assert_error(code, call):
    with pytest.raises(picker.PickerError) as caught:
        call()
    error=caught.value
    assert error.code==code
    assert TOKEN not in str(error) and TOKEN not in repr(error)
    assert TOKEN not in ''.join(traceback.format_exception(error))
    return error


def test_create_get_delete_contract():
    assert picker.SCOPE=='https://www.googleapis.com/auth/photospicker.mediaitems.readonly'
    transport=Transport(session(False),session(),{})
    with picker.GooglePhotosPicker(TOKEN,transport=transport) as client:
        created=client.create_session(37)
        assert created['pollingConfig']['pollInterval']=='5.000000001s'
        assert created['pollingConfig']['timeoutIn']=='600s'
        assert created['expireTime']=='2030-01-01T00:00:00Z'
        assert client.get_session(SESSION)['mediaItemsSet'] is True
        assert client.delete_session(SESSION) is None
    assert [c['method'] for c in transport.calls]==['POST','GET','DELETE']
    assert json.loads(transport.calls[0]['body'])=={'pickingConfig':{'maxItemCount':'37'}}
    assert transport.calls[0]['url']==picker.API_ORIGIN+'/v1/sessions'
    for call in transport.calls:
        assert call['headers']['Authorization']=='Bearer '+TOKEN
        assert call['timeout']<=30
        assert TOKEN not in call['url']
        assert urlsplit(call['url']).hostname=='photospicker.googleapis.com'
    assert_error('invalid_token',lambda:client.get_session(SESSION))


@pytest.mark.parametrize('value',[0,2001,-1,True,'100',None])
def test_invalid_create_limit_never_sends(value):
    transport=Transport()
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('invalid_input',lambda:client.create_session(value))
    assert not transport.calls


@pytest.mark.parametrize('value',['','x\r\ny','x y','非ascii',None,'x'*8193])
def test_invalid_token(value):
    assert_error('invalid_token',lambda:picker.GooglePhotosPicker(value))


@pytest.mark.parametrize('value',['../other','/other','other?x=y','https://evil.invalid','x%2Fy','x\n','..','x'*1025])
def test_session_path_injection_never_sends(value):
    transport=Transport()
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('invalid_input',lambda:client.get_session(value))
    assert not transport.calls


@pytest.mark.parametrize('body',[[],None,'plain',b'{',b'{"v":NaN}',b'{"v":1e999}',b'{"id":"a","id":"b"}'])
def test_bad_create_json_unknown_without_retry(body):
    transport=Transport(Response(body if body is not None else b'null'))
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    error=assert_error('bad_response',client.create_session)
    assert error.outcome_unknown and len(transport.calls)==1


@pytest.mark.parametrize('error,code',[(TimeoutError(TOKEN),'timeout'),(URLError(TOKEN),'network'),
                                     (OSError(TOKEN),'network'),(RuntimeError(TOKEN),'bad_response')])
def test_create_transport_failure_unknown_safe(error,code):
    transport=Transport(error)
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert assert_error(code,client.create_session).outcome_unknown
    assert len(transport.calls)==1


@pytest.mark.parametrize('status,code',[(400,'invalid_input'),(401,'reauth'),(403,'forbidden'),(404,'not_found'),
                                     (409,'not_ready'),(429,'rate_limited'),(500,'unavailable'),(503,'unavailable'),
                                     (301,'redirect'),(302,'redirect'),(307,'redirect'),(308,'redirect')])
def test_http_errors_expose_no_remote_body_headers(status,code):
    response=Response(TOKEN.encode(),status=status,headers={'Retry-After':TOKEN,'Location':'https://evil.invalid/'+TOKEN})
    transport=Transport(response)
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    error=assert_error(code,client.create_session)
    assert error.outcome_unknown==(status>=500 or 300<=status<400)
    assert response.closed and (response.read_calls>0 if status==403 else response.read_calls==0) and len(transport.calls)==1
    assert not hasattr(error,'headers') and not hasattr(error,'body')


def test_urllib_http_error_context_is_suppressed():
    transport=Transport(HTTPError('https://secret.invalid/'+TOKEN,403,TOKEN,{},BytesIO(TOKEN.encode())))
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('forbidden',lambda:client.get_session(SESSION))


def disabled_service_body():
    return {'error':{'code':403,'status':'PERMISSION_DENIED','message':'untrusted-provider-message',
        'details':[{'@type':'type.googleapis.com/google.rpc.ErrorInfo','reason':'SERVICE_DISABLED',
                    'domain':'googleapis.com','metadata':{'service':'photospicker.googleapis.com',
                    'consumer':'projects/synthetic-private-project','activationUrl':'https://untrusted.invalid/activate'}}]}}


@pytest.mark.parametrize('method',['create','get','delete'])
@pytest.mark.parametrize('http_error',[False,True])
def test_service_disabled_is_fixed_safe_error_without_retry(method,http_error):
    body=disabled_service_body()
    suffix='/v1/sessions' if method=='create' else '/v1/sessions/'+SESSION
    headers=Message();headers['Content-Type']='application/json; charset=UTF-8'
    response=(HTTPError(picker.API_ORIGIN+suffix,403,'untrusted-http-message',headers,BytesIO(json.dumps(body).encode()))
              if http_error else Response(body,status=403,chunk=23))
    transport=Transport(response);client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    call={'create':client.create_session,'get':lambda:client.get_session(SESSION),'delete':lambda:client.delete_session(SESSION)}[method]
    error=assert_error('api_disabled',call)
    assert not error.reauth and not error.retryable and not error.outcome_unknown
    assert len(transport.calls)==1
    public=str(error)+repr(vars(error))+''.join(traceback.format_exception(error))
    assert all(value not in public for value in ['untrusted-provider-message','untrusted-http-message','synthetic-private-project','untrusted.invalid'])


@pytest.mark.parametrize('field,value',[
    ('@type','type.googleapis.com/other.ErrorInfo'),('@type',None),('reason','ACCESS_TOKEN_SCOPE_INSUFFICIENT'),
    ('domain','untrusted.invalid'),('service','photoslibrary.googleapis.com'),('service',None)])
def test_service_disabled_rejects_wrong_errorinfo_identity(field,value):
    body=disabled_service_body();detail=body['error']['details'][0]
    (detail['metadata'] if field=='service' else detail)[field]=value
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(Response(body,status=403)))
    assert_error('forbidden',client.create_session)


@pytest.mark.parametrize('case',['invalid-json','oversize','duplicate-key','wrong-status','wrong-code','token-echo','compressed','wrong-mime'])
def test_service_disabled_untrusted_body_fails_closed(case):
    body=disabled_service_body();kwargs={}
    if case=='invalid-json':body=b'not json'
    elif case=='oversize':body=b' '*(64*1024)+json.dumps(body).encode()
    elif case=='duplicate-key':body=json.dumps(body).replace('"code": 403','"code": 403, "code": 403').encode()
    elif case=='wrong-status':body['error']['status']='OTHER'
    elif case=='wrong-code':body['error']['code']='403'
    elif case=='token-echo':body['error']['message']=TOKEN
    elif case=='compressed':kwargs={'headers':{'Content-Encoding':'gzip'}}
    elif case=='wrong-mime':kwargs={'mime':'text/html'}
    response=Response(body,status=403,**kwargs)
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(response))
    assert_error('forbidden',client.create_session)
    assert response.cursor<=64*1024+1 and response.closed


def test_service_disabled_body_does_not_override_401_or_media_403():
    response=Response(disabled_service_body(),status=401)
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(response))
    assert assert_error('reauth',client.create_session).reauth and response.read_calls==0
    client,_,_=selected(Response(disabled_service_body(),status=403))
    assert_error('forbidden',lambda:client.download_media(SESSION,'media-1'))
    assert not client._selected


@pytest.mark.parametrize('mutation',[
    {'id':'other-session'}, {'expireTime':'bad'}, {'expireTime':'2020-01-01T00:00:00Z'},
    {'mediaItemsSet':'true'}, {'mediaItemsSet':False,'pollingConfig':{'pollInterval':'NaNs','timeoutIn':'20s'}},
    {'mediaItemsSet':False,'pollingConfig':{'pollInterval':'5s','timeoutIn':'86401s'}},
    {'pickerUri':'https://photos.google.com.evil.invalid/picker'},
    {'pickingConfig':{'maxItemCount':100}},
])
def test_invalid_session(mutation):
    transport=Transport(session(**mutation))
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    code='expired' if mutation.get('expireTime')=='2020-01-01T00:00:00Z' else 'bad_response'
    assert_error(code,lambda:client.get_session(SESSION))


def test_not_ready_and_zero_poll_timeout_are_distinct():
    transport=Transport(session(False,pollingConfig={'pollInterval':'0s','timeoutIn':'0s'}),session(False))
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert client.get_session(SESSION)['pollingConfig']['timeoutIn']=='0s'
    assert_error('not_ready',lambda:client.list_selected_media(SESSION))
    assert len(transport.calls)==2


def test_pagination_metadata_only_and_duplicate_identical_id():
    first=item()
    transport=Transport(session(),{'mediaItems':[first],'nextPageToken':'opaque+/='},
                        {'mediaItems':[first,item('media-2')]})
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    result=client.list_selected_media(SESSION)
    assert [p['id'] for p in result]==['media-1','media-2']
    assert 'baseUrl' not in json.dumps(result) and TOKEN not in json.dumps(result)
    assert parse_qs(urlsplit(transport.calls[2]['url']).query)['pageToken']==['opaque+/=']
    result[0]['mediaFile']['mimeType']='image/svg+xml'
    assert client._selected['media-1'][0]['mediaFile']['mimeType']=='image/png'


@pytest.mark.parametrize('pages,code',[
    ([{'mediaItems':[item()],'nextPageToken':'same'},{'mediaItems':[],'nextPageToken':'same'}],'bad_response'),
    ([{'mediaItems':[item()],'nextPageToken':'next'},{'mediaItems':[item(createTime='2024-01-01T00:00:00Z')]}],'bad_response'),
    ([{'mediaItems':[item()],'nextPageToken':'next'},Response(b'bad')],'bad_response'),
    ([{'mediaItems':{},'nextPageToken':''}],'bad_response'),
    ([{'mediaItems':[item()],'sessionId':'other'}],'bad_response'),
    ([{'mediaItems':[item(sessionId='other')]}],'bad_response'),
    ([{'mediaItems':[],'nextPageToken':5}],'bad_response'),
])
def test_partial_catalog_never_grants_download(pages,code):
    transport=Transport(session(),*pages)
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error(code,lambda:client.list_selected_media(SESSION))
    count=len(transport.calls)
    assert_error('not_selected',lambda:client.download_media(SESSION,'media-1'))
    assert len(transport.calls)==count


@pytest.mark.parametrize('kwargs,pages',[
    ({'max_items':1},[{'mediaItems':[item()],'nextPageToken':'more'}]),
    ({'max_pages':1},[{'mediaItems':[],'nextPageToken':'more'}]),
    ({'max_items':1},[{'mediaItems':[item(),item('media-2')]}]),
])
def test_selection_caps_are_errors_not_false_complete(kwargs,pages):
    transport=Transport(session(),*pages)
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('selection_limit',lambda:client.list_selected_media(SESSION,**kwargs))
    assert not client._selected


def test_page_size_and_total_json_budget(monkeypatch):
    transport=Transport(session(),{'mediaItems':[item(),item('media-2')]})
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('bad_response',lambda:client.list_selected_media(SESSION,page_size=1))
    body={'mediaItems':[item()],'ignored':'z'*400}
    size=len(json.dumps(body,ensure_ascii=False).encode())
    monkeypatch.setattr(picker,'CATALOG_LIMIT',size+50)
    transport.responses=[session(),dict(body,nextPageToken='next'),body]
    assert_error('too_large',lambda:client.list_selected_media(SESSION))
    assert not client._selected


@pytest.mark.parametrize('url',[
    'http://lh3.googleusercontent.com/p/a','https://lh3.googleusercontent.com.evil.invalid/p/a',
    'https://evil.invalid/p/a','https://127.0.0.1/p/a','https://[::1]/p/a',
    'https://lh3.googleusercontent.com:443/p/a','https://user@lh3.googleusercontent.com/p/a',
    'https://lh3.googleusercontent.com/p/a?secret=1','https://lh3.googleusercontent.com/p/a#f',
    'https://lh3.googleusercontent.com/p/../a','https://lh3.googleusercontent.com/p/%2e%2e/a',
    'https://lh3.googleusercontent.com/p/a=d','https://lh3.googleusercontent.com/p/%0a',
    ' https://lh3.googleusercontent.com/p/a','https://lh3.googleusercontent.com\\evil.invalid/p/a',
    'https://lh3.googleusercontent.com/p/%ZZ',
])
def test_unapproved_media_urls_never_receive_credentials(url):
    value=item();value['mediaFile']['baseUrl']=url
    transport=Transport(session(),{'mediaItems':[value]})
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert_error('bad_response',lambda:client.list_selected_media(SESSION))
    assert len(transport.calls)==2
    assert all(urlsplit(c['url']).hostname=='photospicker.googleapis.com' for c in transport.calls)


def test_token_echo_rejected_after_unicode_json_decode():
    value=session();value['unused']=TOKEN
    escaped=json.dumps(value).replace(TOKEN,''.join('\\u%04x'%ord(c) for c in TOKEN)).encode()
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(Response(escaped)))
    assert_error('bad_response',lambda:client.get_session(SESSION))


@pytest.mark.parametrize('data,mime',[(PNG,'image/png'),(b'\xff\xd8\xffsynthetic','image/jpeg'),
                                   (b'GIF89asynthetic','image/gif'),(b'RIFF1234WEBPsynthetic','image/webp')])
def test_photo_download_variants_validate_bytes_and_mime(data,mime):
    response=Response(data,mime=mime)
    client,transport,_=selected(response)
    downloaded=client.download_media(SESSION,'media-1',variant='photo')
    assert downloaded.data==data and downloaded.content_type==mime
    assert transport.calls[-1]['url'].endswith('=d')
    assert downloaded.variant=='photo'
    assert 'baseUrl' not in vars(downloaded) and 'url' not in vars(downloaded)
    assert '合成照片' not in repr(downloaded) and data.hex() not in repr(downloaded)
    assert response.closed


def test_video_preview_and_download_are_distinct():
    client,transport,_=selected(Response(PNG,mime='image/png'),Response(MP4,mime='video/mp4'),items=[item(kind='VIDEO')])
    preview=client.download_media(SESSION,'media-1',width=320,height=240)
    assert preview.content_type=='image/png' and transport.calls[-1]['url'].endswith('=w320-h240')
    video=client.download_media(SESSION,'media-1',variant='video')
    assert video.content_type=='video/mp4' and transport.calls[-1]['url'].endswith('=dv')
    assert_error('invalid_input',lambda:client.download_media(SESSION,'media-1',variant='photo'))


@pytest.mark.parametrize('status',['UNSPECIFIED','PROCESSING','FAILED'])
def test_unready_video_never_downloads_but_can_preview(status):
    client,transport,_=selected(Response(PNG,mime='image/png'),items=[item(kind='VIDEO',status=status)])
    assert_error('not_ready',lambda:client.download_media(SESSION,'media-1',variant='video'))
    assert len(transport.calls)==2
    assert client.download_media(SESSION,'media-1').data==PNG


@pytest.mark.parametrize('body,mime',[(b'<script>synthetic</script>','image/png'),(PNG,'text/html'),
                                   (PNG,'image/svg+xml'),(MP4,'image/png'),(b'','image/jpeg')])
def test_header_and_declared_mime_are_not_enough(body,mime):
    client,_,_=selected(Response(body,mime=mime))
    assert_error('unsupported_media',lambda:client.download_media(SESSION,'media-1'))


def test_heic_original_refused_preview_can_be_converted():
    value=item();value['mediaFile']['mimeType']='image/heic'
    client,transport,_=selected(Response(PNG,mime='image/png'),items=[value])
    assert_error('unsupported_media',lambda:client.download_media(SESSION,'media-1',variant='photo'))
    assert len(transport.calls)==2
    assert client.download_media(SESSION,'media-1').content_type=='image/png'


def test_never_download_unlisted_or_other_session_and_expiry(monkeypatch):
    client,transport,_=selected()
    assert_error('not_selected',lambda:client.download_media(SESSION,'unlisted'))
    assert_error('not_selected',lambda:client.download_media('other-session','media-1'))
    monkeypatch.setattr(picker.time,'time',lambda:client._selected_until+1)
    assert_error('expired',lambda:client.download_media(SESSION,'media-1'))
    assert not client._selected and len(transport.calls)==2


def test_expiry_is_minimum_of_session_and_base_url_hour(monkeypatch):
    now=picker.time.time()
    monkeypatch.setattr(picker.time,'time',lambda:now)
    client,_,_=selected()
    assert client._selected_until==now+3600
    expires='2026-09-16T00:00:00Z'
    instant=picker._timestamp(expires)-60
    monkeypatch.setattr(picker.time,'time',lambda:instant)
    transport=Transport(session(expireTime=expires),{'mediaItems':[item()]})
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    client.list_selected_media(SESSION)
    assert client._selected_until==instant+60


def test_failed_refresh_and_delete_clear_previous_capability():
    client,transport,_=selected(session(),Response(b'bad'),{})
    assert_error('bad_response',lambda:client.list_selected_media(SESSION))
    assert not client._selected
    client.delete_session(SESSION)
    assert_error('not_selected',lambda:client.download_media(SESSION,'media-1'))


def test_permission_revocation_clears_download_catalog():
    client,transport,_=selected(Response(TOKEN.encode(),status=403))
    assert_error('forbidden',lambda:client.download_media(SESSION,'media-1'))
    assert not client._selected
    assert_error('not_selected',lambda:client.download_media(SESSION,'media-1'))
    assert len(transport.calls)==3


@pytest.mark.parametrize('headers,body,code',[
    ({'Content-Length':str(picker.JSON_LIMIT+1)},b'{}','too_large'),
    ({'Content-Length':'100'},b'{}','bad_response'),
    ({'Content-Length':'-1'},b'{}','bad_response'),
    ({'Content-Encoding':'gzip'},b'{}','bad_response'),
    ({},b'x'*(picker.JSON_LIMIT+1),'too_large'),
],ids=['declared-oversize','short-body','negative-length','encoded-body','stream-oversize'])
def test_json_body_size_encoding_and_lengths(headers,body,code):
    response=Response(body,headers=headers)
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(response))
    assert_error(code,lambda:client.get_session(SESSION))
    assert response.closed


def test_media_size_limit_checked_before_read_and_while_streaming(monkeypatch):
    response=Response(PNG,mime='image/png',headers={'Content-Length':str(picker.PREVIEW_LIMIT+1)})
    client,_,_=selected(response)
    assert_error('too_large',lambda:client.download_media(SESSION,'media-1'))
    assert response.read_calls==0
    monkeypatch.setattr(picker,'PREVIEW_LIMIT',16)
    client,_,_=selected(Response(PNG,mime='image/png',chunk=3))
    assert_error('too_large',lambda:client.download_media(SESSION,'media-1'))


def test_slow_drip_deadline_closes_response(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(picker.time,'monotonic',lambda:clock[0])
    response=Response(session(),chunk=1,on_read=lambda:clock.__setitem__(0,clock[0]+11))
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(response))
    assert_error('timeout',lambda:client.get_session(SESSION))
    assert response.closed and response.read_calls==3


def test_total_pagination_deadline_includes_all_pages(monkeypatch):
    clock=[10.0]
    monkeypatch.setattr(picker.time,'monotonic',lambda:clock[0])
    def elapsed():
        clock[0]+=10
    pages=[Response({'mediaItems':[],'nextPageToken':'next-'+str(n)},on_read=elapsed) for n in range(10)]
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(session(),*pages))
    assert_error('timeout',lambda:client.list_selected_media(SESSION))
    assert not client._selected


def test_normalized_catalog_budget_includes_private_urls(monkeypatch):
    value=item(kind='VIDEO')
    del value['mediaFile']['mediaFileMetadata']
    public,base=picker.GooglePhotosPicker._media(value,SESSION)
    minimum=len(json.dumps(public,ensure_ascii=False).encode())+len(base)
    assert minimum-1>len(json.dumps({'mediaItems':[value]},ensure_ascii=False).encode())
    monkeypatch.setattr(picker,'CATALOG_LIMIT',minimum-1)
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(session(),{'mediaItems':[value]}))
    assert_error('too_large',lambda:client.list_selected_media(SESSION))
    assert not client._selected


@pytest.mark.parametrize('change',[
    {'type':[]},{'type':None},{'createTime':'yesterday'},
    {'mediaFile':None},{'id':None},
])
def test_malformed_media_fields_are_fixed_errors(change):
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(session(),{'mediaItems':[item(**change)]}))
    with pytest.raises(picker.PickerError):
        client.list_selected_media(SESSION)
    assert not client._selected


@pytest.mark.parametrize('field,value',[
    ('filename','../private.png'),('filename','a'*256),('filename','\ud800'),('mimeType',7),('baseUrl','x'*8193),
    ('mediaFileMetadata',{'width':True}),('mediaFileMetadata',{'height':100001}),
    ('mediaFileMetadata',{'videoMetadata':{'processingStatus':[]}}),
],ids=['filename-path','filename-size','unicode-surrogate','mime-shape','url-size','boolean-width','huge-height','video-status-shape'])
def test_malformed_file_fields(field,value):
    record=item(kind='VIDEO') if field=='mediaFileMetadata' and 'videoMetadata' in value else item()
    record['mediaFile'][field]=value
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(session(),{'mediaItems':[record]}))
    assert_error('bad_response',lambda:client.list_selected_media(SESSION))


def test_fake_transport_final_url_change_is_rejected():
    response=Response(session(),url='https://evil.invalid/'+TOKEN)
    client=picker.GooglePhotosPicker(TOKEN,transport=Transport(response))
    assert_error('redirect',lambda:client.get_session(SESSION))
    assert response.read_calls==0


def test_download_token_echo_is_not_returned():
    client,_,_=selected(Response(PNG+TOKEN.encode(),mime='image/png'))
    assert_error('bad_response',lambda:client.download_media(SESSION,'media-1'))


def test_refresh_get_not_ready_invalidates_existing_selection():
    client,_,_=selected(session(False))
    assert client.get_session(SESSION)['mediaItemsSet'] is False
    assert_error('not_selected',lambda:client.download_media(SESSION,'media-1'))


def test_delete_unknown_clears_selection_and_does_not_retry():
    client,transport,_=selected(TimeoutError(TOKEN))
    assert assert_error('timeout',lambda:client.delete_session(SESSION)).outcome_unknown
    assert not client._selected and len(transport.calls)==3


def test_empty_complete_list_and_delete_204():
    transport=Transport(session(),{},Response(b'',status=204,mime=''))
    client=picker.GooglePhotosPicker(TOKEN,transport=transport)
    assert client.list_selected_media(SESSION)==[]
    assert client.delete_session(SESSION) is None


def test_default_transport_disables_redirect_and_passes_socket_timeout(monkeypatch):
    seen={}
    class Opener:
        def open(self,request,timeout):
            seen.update(request=request,timeout=timeout)
            return Response(session(),url=request.full_url)
    def builder(handler):
        assert isinstance(handler,picker._NoRedirect)
        assert handler.redirect_request(None,None,302,'',{},'https://evil.invalid') is None
        return Opener()
    monkeypatch.setattr(picker,'build_opener',builder)
    # Retrieve the production function saved before the autouse guard below.
    client=picker.GooglePhotosPicker(TOKEN,transport=REAL_TRANSPORT)
    client.get_session(SESSION)
    assert seen['timeout']<=30
    assert seen['request'].get_header('Authorization')=='Bearer '+TOKEN


REAL_TRANSPORT=picker._transport
