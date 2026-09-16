"""Bounded, server-only Google Photos Picker adapter; no OAuth or persistence.

Create one instance per authorized Google account/import operation. A complete
list establishes temporary download capabilities for that instance, never for
arbitrary caller URLs. The caller owns household permissions, polling, consent,
quota, token refresh and storage. There are no retries or whole-library calls.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from http.client import HTTPException
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SCOPE = 'https://www.googleapis.com/auth/photospicker.mediaitems.readonly'
API_ORIGIN = 'https://photospicker.googleapis.com'
MEDIA_ORIGIN = 'https://lh3.googleusercontent.com'
PICKER_ORIGIN = 'https://photos.google.com'
JSON_LIMIT = 2 * 1024 * 1024
CATALOG_LIMIT = 16 * 1024 * 1024
MAX_ITEMS, MAX_PAGES = 2000, 40
SOCKET_TIMEOUT, JSON_DEADLINE, LIST_DEADLINE, MEDIA_DEADLINE = 30, 30, 120, 120
PREVIEW_LIMIT, PHOTO_LIMIT, VIDEO_LIMIT = 8 * 1024**2, 25 * 1024**2, 100 * 1024**2
IMAGE_TYPES = frozenset({'image/jpeg','image/png','image/webp','image/gif'})

_MESSAGES = {
    'invalid_input': '相册请求参数无效。',
    'invalid_token': 'Google Photos 授权凭据不可用，请重新授权。',
    'reauth': 'Google Photos 授权已失效，请重新授权。',
    'forbidden': 'Google Photos 选择会话无权访问或已过期。',
    'api_disabled': 'Google Photos Picker API 尚未启用。请联系应用维护者启用后，再重新选片；无需重复授权。',
    'not_found': 'Google Photos 选择会话或媒体不可访问。',
    'not_ready': '请先完成 Google Photos 选择，或等待视频处理完成。',
    'rate_limited': 'Google Photos 请求暂时受限，请稍后由原流程重试。',
    'unavailable': 'Google Photos 暂时无法访问，请稍后由原流程重试。',
    'timeout': 'Google Photos 请求超时，结果需要重新核对。',
    'network': 'Google Photos 连接中断，结果需要重新核对。',
    'redirect': 'Google Photos 请求发生了不允许的跳转。',
    'bad_response': 'Google Photos 返回内容无法安全处理。',
    'too_large': 'Google Photos 返回内容超过本次处理上限。',
    'selection_limit': '所选媒体或分页超过本次处理上限，请缩小选择范围后重试。',
    'not_selected': '请先完整读取本人本次选择的媒体。',
    'expired': '本次媒体访问已过期，请重新读取选择会话。',
    'unsupported_media': '此媒体格式暂不支持安全导入。',
}


class PickerError(Exception):
    """Only fixed messages/codes cross the adapter boundary; no remote details."""
    def __init__(self, code, *, outcome_unknown=False):
        self.code = code
        self.message = _MESSAGES[code]
        self.status = {'invalid_input':400,'invalid_token':401,'reauth':401,'forbidden':403,'api_disabled':503,
                       'not_found':404,'not_ready':409,'not_selected':409,'expired':410,
                       'rate_limited':429,'too_large':413,'selection_limit':413,
                       'unsupported_media':415}.get(code,502)
        self.retryable = code in {'rate_limited','unavailable','timeout','network'}
        self.reauth = code in {'invalid_token','reauth'}
        self.outcome_unknown = outcome_unknown
        super().__init__(self.message)


@dataclass(frozen=True)
class DownloadedMedia:
    data: bytes = field(repr=False)
    content_type: str
    # Original filename is metadata only: never a filesystem path.
    filename: str = field(repr=False)
    variant: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _transport(method, url, *, headers, body, timeout):
    return build_opener(_NoRedirect()).open(Request(url,data=body,headers=headers,method=method),timeout=timeout)


def _text(value, maximum, *, empty=False, ascii_only=False, code='bad_response'):
    if (not isinstance(value,str) or len(value)>maximum or not empty and not value
            or any(ord(c)<32 or ord(c)==127 or 0xD800<=ord(c)<=0xDFFF for c in value)
            or ascii_only and not value.isascii()):
        raise PickerError(code)
    return value


def _identifier(value, *, code='invalid_input'):
    value = _text(value,1024,ascii_only=True,code=code)
    if not re.fullmatch(r'[A-Za-z0-9_~.-]+',value) or value in {'.','..'}:
        raise PickerError(code)
    return value


def _integer(value, minimum, maximum, *, code='invalid_input'):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PickerError(code)
    return value


def _url(value, origin, *, query=False):
    value = _text(value,8192,ascii_only=True)
    if any(c.isspace() for c in value) or '\\' in value or re.search(r'%(?![0-9a-fA-F]{2})',value):
        raise PickerError('bad_response')
    try:
        parts = urlsplit(value)
        if (parts.scheme!='https' or parts.netloc!=urlsplit(origin).netloc or parts.fragment
                or parts.query and not query or not parts.path.startswith('/') or parts.path=='/'):
            raise ValueError()
        decoded = unquote(parts.path)
        if any(c.isspace() or ord(c)<32 or ord(c)==127 for c in decoded) or '\\' in decoded:
            raise ValueError()
        if any(segment in {'.','..'} for segment in decoded.split('/')):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise PickerError('bad_response') from None
    return value


def _timestamp(value):
    value = _text(value,40,ascii_only=True)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})',value):
        raise PickerError('bad_response')
    try:
        return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError, OverflowError, OSError):
        raise PickerError('bad_response') from None


def _duration(value):
    value = _text(value,32,ascii_only=True)
    if not re.fullmatch(r'\d{1,5}(?:\.\d{1,9})?s',value) or float(value[:-1])>86400:
        raise PickerError('bad_response')
    return value


def _object(value):
    if not isinstance(value,dict):
        raise PickerError('bad_response')
    return value


def _json(raw, token):
    def reject(_value):
        raise ValueError()
    def finite(value):
        number = float(value)
        return number if math.isfinite(number) else reject(value)
    def pairs(entries):
        result = {}
        for key,value in entries:
            if key in result:
                raise ValueError()
            result[key]=value
        return result
    try:
        result = json.loads(raw.decode('utf-8'),parse_constant=reject,parse_float=finite,object_pairs_hook=pairs)
        _object(result)
        # Check decoded strings as well as keys, including Unicode-escaped echoes.
        pending = [result]
        while pending:
            value = pending.pop()
            if isinstance(value,str) and token in value:
                raise ValueError()
            if isinstance(value,dict):
                pending.extend(value.keys());pending.extend(value.values())
            elif isinstance(value,list):
                pending.extend(value)
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise PickerError('bad_response') from None


def _header(response, name):
    headers = response.headers
    if hasattr(headers,'get_all') and len(headers.get_all(name) or [])>1:
        raise PickerError('bad_response')
    return _text(headers.get(name,''),4096,empty=True,ascii_only=True).strip()


def _sniff(data, mime):
    if mime=='image/jpeg':
        return data.startswith(b'\xff\xd8\xff')
    if mime=='image/png':
        return data.startswith(b'\x89PNG\r\n\x1a\n')
    if mime=='image/webp':
        return len(data)>=12 and data[:4]==b'RIFF' and data[8:12]==b'WEBP'
    if mime=='image/gif':
        return data.startswith((b'GIF87a',b'GIF89a'))
    if mime=='video/mp4':
        return len(data)>=16 and data[4:8]==b'ftyp' and data[8:12] in {
            b'isom',b'iso2',b'iso4',b'iso5',b'iso6',b'mp41',b'mp42',b'avc1',b'M4V ',b'dash'}
    return False


class GooglePhotosPicker:
    def __init__(self, access_token, *, transport=None):
        token = _text(access_token,8192,ascii_only=True,code='invalid_token')
        if any(c.isspace() for c in token):
            raise PickerError('invalid_token')
        self._token, self._transport = token, transport or _transport
        self._clear_selection()

    def _clear_selection(self):
        self._selected_session = None
        self._selected = {}
        self._selected_until = 0

    def close(self):
        self._clear_selection()
        self._token = ''

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _permission_code(self, response, url, deadline):
        # Error bodies are untrusted. Inspect only a bounded ErrorInfo allowlist;
        # never expose its message, project, activation URL or other metadata.
        try:
            if (response.geturl()!=url or _header(response,'Content-Encoding').lower() not in ('','identity')
                    or _header(response,'Content-Type').split(';',1)[0].strip().lower()!='application/json'):
                return 'forbidden'
            chunks, size, limit = [], 0, 64*1024
            while True:
                if time.monotonic()>=deadline:
                    return 'forbidden'
                chunk = response.read1(min(4096,limit+1-size))
                if time.monotonic()>=deadline or not isinstance(chunk,bytes):
                    return 'forbidden'
                if not chunk:
                    break
                size += len(chunk)
                if size>limit:
                    return 'forbidden'
                chunks.append(chunk)
            error = _json(b''.join(chunks),self._token).get('error')
            if (not isinstance(error,dict) or type(error.get('code')) is not int or error['code']!=403
                    or error.get('status')!='PERMISSION_DENIED' or not isinstance(error.get('details'),list)):
                return 'forbidden'
            for detail in error['details']:
                if (isinstance(detail,dict) and detail.get('@type')=='type.googleapis.com/google.rpc.ErrorInfo'
                        and detail.get('domain')=='googleapis.com' and detail.get('reason')=='SERVICE_DISABLED'
                        and isinstance(detail.get('metadata'),dict)
                        and detail['metadata'].get('service')=='photospicker.googleapis.com'):
                    return 'api_disabled'
        except Exception:
            pass
        return 'forbidden'

    def _request(self, method, url, *, body=None, limit=JSON_LIMIT, media=False, deadline=None):
        if not self._token:
            raise PickerError('invalid_token')
        # Every URL is built internally, and validated before passing credentials.
        _url(url,MEDIA_ORIGIN if media else API_ORIGIN,query=not media)
        started = time.monotonic()
        deadline = min(deadline or float('inf'),started+(MEDIA_DEADLINE if media else JSON_DEADLINE))
        if started>=deadline:
            raise PickerError('timeout')
        headers = {'Authorization':'Bearer '+self._token,'Accept':'*/*' if media else 'application/json',
                   'Accept-Encoding':'identity'}
        if body is not None:
            headers['Content-Type']='application/json'
        response = None
        try:
            response = self._transport(method,url,headers=headers,body=body,timeout=min(SOCKET_TIMEOUT,deadline-started))
            status = response.status
            if type(status) is not int:
                raise PickerError('bad_response')
            if status==403 and not media:
                raise PickerError(self._permission_code(response,url,deadline))
            self._status(status)
            if response.geturl()!=url:
                raise PickerError('redirect')
            encoding = _header(response,'Content-Encoding').lower()
            if encoding not in ('','identity'):
                raise PickerError('bad_response')
            length = _header(response,'Content-Length')
            if length and not re.fullmatch(r'\d{1,12}',length):
                raise PickerError('bad_response')
            if length and int(length)>limit:
                raise PickerError('too_large')
            mime = _header(response,'Content-Type').split(';',1)[0].strip().lower()
            if not media and mime not in ('application/json',''):
                raise PickerError('bad_response')
            chunks, size = [],0
            while True:
                if time.monotonic()>=deadline:
                    raise PickerError('timeout')
                chunk = response.read1(min(65536,limit+1-size))
                if time.monotonic()>=deadline:
                    raise PickerError('timeout')
                if not isinstance(chunk,bytes):
                    raise PickerError('bad_response')
                if not chunk:
                    break
                size += len(chunk)
                if size>limit:
                    raise PickerError('too_large')
                chunks.append(chunk)
            if length and int(length)!=size:
                raise PickerError('bad_response')
            return b''.join(chunks),mime,status
        except HTTPError as error:
            try:
                if error.code==403 and not media:
                    raise PickerError(self._permission_code(error,url,deadline))
                self._status(error.code)
                raise PickerError('bad_response')
            except PickerError as safe:
                raise safe from None
            finally:
                try:
                    error.close()
                except Exception:
                    pass
        except (TimeoutError,):
            raise PickerError('timeout') from None
        except (URLError, OSError, HTTPException):
            raise PickerError('network') from None
        except PickerError:
            raise
        except Exception:
            # A trusted injected transport still must not leak raw exceptions.
            raise PickerError('bad_response') from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    @staticmethod
    def _status(status):
        if status in (200,201,204):
            return
        if 300<=status<400:
            raise PickerError('redirect')
        code = {400:'invalid_input',401:'reauth',403:'forbidden',404:'not_found',409:'not_ready',
                412:'not_ready',429:'rate_limited'}.get(status,'unavailable' if 500<=status<600 else 'bad_response')
        raise PickerError(code)

    def _api(self, method, suffix, *, body=None, deadline=None):
        raw,_,status = self._request(method,API_ORIGIN+suffix,body=body,deadline=deadline)
        if method=='DELETE' and status in (200,204) and not raw:
            return {},len(raw)
        if status!=200 and not (method=='POST' and status==201):
            raise PickerError('bad_response')
        return _json(raw,self._token),len(raw)

    def _session(self, value, expected=None, *, require_picker=False):
        value = _object(value)
        identifier = _identifier(value.get('id'),code='bad_response')
        if expected is not None and identifier!=expected:
            raise PickerError('bad_response')
        expires = value.get('expireTime')
        _timestamp(expires)
        ready = value.get('mediaItemsSet',False)
        if type(ready) is not bool:
            raise PickerError('bad_response')
        result = {'id':identifier,'expireTime':expires,'mediaItemsSet':ready}
        if value.get('pickerUri') or require_picker:
            result['pickerUri']=_url(value.get('pickerUri'),PICKER_ORIGIN,query=True)
        if not ready:
            polling = _object(value.get('pollingConfig'))
            result['pollingConfig']={'pollInterval':_duration(polling.get('pollInterval')),
                                     'timeoutIn':_duration(polling.get('timeoutIn'))}
        if 'pickingConfig' in value:
            count = _object(value['pickingConfig']).get('maxItemCount','0')
            if not isinstance(count,str) or not re.fullmatch(r'\d{1,4}',count) or int(count)>MAX_ITEMS:
                raise PickerError('bad_response')
            result['pickingConfig']={'maxItemCount':count}
        return result

    def create_session(self, max_item_count=100):
        _integer(max_item_count,1,MAX_ITEMS)
        body = json.dumps({'pickingConfig':{'maxItemCount':str(max_item_count)}}).encode('utf-8')
        try:
            value,_ = self._api('POST','/v1/sessions',body=body)
            return self._session(value,require_picker=True)
        except PickerError as error:
            if error.code in {'network','timeout','unavailable','bad_response','too_large','redirect'}:
                error.outcome_unknown=True
            raise error from None

    def get_session(self, session_id):
        session_id = _identifier(session_id)
        try:
            value,_ = self._api('GET','/v1/sessions/'+quote(session_id,safe=''))
            result = self._session(value,session_id)
            if _timestamp(result['expireTime'])<=time.time():
                raise PickerError('expired')
            if self._selected_session==session_id:
                if not result['mediaItemsSet']:
                    self._clear_selection()
                else:
                    self._selected_until=min(self._selected_until,_timestamp(result['expireTime']))
            return result
        except PickerError:
            if self._selected_session==session_id:
                self._clear_selection()
            raise

    def delete_session(self, session_id):
        session_id = _identifier(session_id)
        if self._selected_session==session_id:
            self._clear_selection()
        try:
            value,_ = self._api('DELETE','/v1/sessions/'+quote(session_id,safe=''))
            if value:
                raise PickerError('bad_response')
        except PickerError as error:
            if error.code in {'network','timeout','unavailable','bad_response','too_large','redirect'}:
                error.outcome_unknown=True
            raise error from None

    @staticmethod
    def _media(value, session_id):
        value = _object(value)
        if 'sessionId' in value and value['sessionId']!=session_id:
            raise PickerError('bad_response')
        identifier = _identifier(value.get('id'),code='bad_response')
        kind = value.get('type')
        if not isinstance(kind,str) or kind not in {'PHOTO','VIDEO'}:
            raise PickerError('unsupported_media')
        created = value.get('createTime')
        _timestamp(created)
        file = _object(value.get('mediaFile'))
        base = _url(file.get('baseUrl'),MEDIA_ORIGIN)
        if '=' in urlsplit(base).path:
            raise PickerError('bad_response')
        mime = _text(file.get('mimeType'),128,ascii_only=True).lower()
        if not re.fullmatch(r'(?:image|video)/[a-z0-9.+-]+',mime) or not mime.startswith('image/' if kind=='PHOTO' else 'video/'):
            raise PickerError('bad_response')
        filename = _text(file.get('filename'),255)
        if any(c in filename for c in '/\\:') or filename in {'.','..'}:
            raise PickerError('bad_response')
        metadata = _object(file.get('mediaFileMetadata',{}))
        public_file = {'mimeType':mime,'filename':filename,'mediaFileMetadata':{}}
        for key in ('width','height'):
            if key in metadata:
                public_file['mediaFileMetadata'][key]=_integer(metadata[key],0,100000,code='bad_response')
        if kind=='VIDEO':
            video = _object(metadata.get('videoMetadata',{}))
            status = video.get('processingStatus','UNSPECIFIED')
            if not isinstance(status,str) or status not in {'UNSPECIFIED','PROCESSING','READY','FAILED'}:
                raise PickerError('bad_response')
            public_file['mediaFileMetadata']['videoMetadata']={'processingStatus':status}
        return {'id':identifier,'createTime':created,'type':kind,'mediaFile':public_file},base

    def list_selected_media(self, session_id, *, page_size=100, max_items=MAX_ITEMS, max_pages=MAX_PAGES):
        session_id = _identifier(session_id)
        _integer(page_size,1,100);_integer(max_items,1,MAX_ITEMS);_integer(max_pages,1,MAX_PAGES)
        # Replacing a catalog never retains old or partially received capability.
        self._clear_selection()
        deadline = time.monotonic()+LIST_DEADLINE
        session = self.get_session(session_id)
        if not session['mediaItemsSet']:
            raise PickerError('not_ready')
        expires = min(_timestamp(session['expireTime']),time.time()+3600)
        pending, tokens, token, total_bytes, normalized_bytes = {},set(),'',0,0
        for _page in range(max_pages):
            tokens.add(token)
            query = {'sessionId':session_id,'pageSize':page_size}
            if token:
                query['pageToken']=token
            value,size = self._api('GET','/v1/mediaItems?'+urlencode(query),deadline=deadline)
            total_bytes += size
            if total_bytes>CATALOG_LIMIT:
                raise PickerError('too_large')
            if 'sessionId' in value and value['sessionId']!=session_id:
                raise PickerError('bad_response')
            items = value.get('mediaItems',[])
            if not isinstance(items,list) or len(items)>page_size:
                raise PickerError('bad_response')
            for raw in items:
                public,base = self._media(raw,session_id)
                identifier = public['id']
                candidate = (public,base)
                if identifier in pending:
                    if pending[identifier]!=candidate:
                        raise PickerError('bad_response')
                    continue
                normalized_bytes += len(json.dumps(public,ensure_ascii=False).encode('utf-8'))+len(base)
                if normalized_bytes>CATALOG_LIMIT:
                    raise PickerError('too_large')
                pending[identifier]=candidate
                if len(pending)>max_items:
                    raise PickerError('selection_limit')
            token = _text(value.get('nextPageToken',''),4096,empty=True,ascii_only=True)
            if not token:
                if time.monotonic()>=deadline:
                    raise PickerError('timeout')
                if time.time()>=expires:
                    raise PickerError('expired')
                self._selected_session, self._selected, self._selected_until = session_id,pending,expires
                return [deepcopy(entry[0]) for entry in pending.values()]
            if token in tokens:
                raise PickerError('bad_response')
            if len(pending)>=max_items:
                raise PickerError('selection_limit')
        raise PickerError('selection_limit')

    def download_media(self, session_id, media_id, *, variant='preview', width=2048, height=2048):
        session_id, media_id = _identifier(session_id),_identifier(media_id)
        if session_id!=self._selected_session or media_id not in self._selected:
            raise PickerError('not_selected')
        if time.time()>=self._selected_until:
            self._clear_selection()
            raise PickerError('expired')
        public,base = self._selected[media_id]
        if variant=='preview':
            _integer(width,1,4096);_integer(height,1,4096)
            suffix,limit,allowed = f'=w{width}-h{height}',PREVIEW_LIMIT,IMAGE_TYPES
        elif variant=='photo' and public['type']=='PHOTO':
            if public['mediaFile']['mimeType'] not in IMAGE_TYPES:
                raise PickerError('unsupported_media')
            suffix,limit,allowed = '=d',PHOTO_LIMIT,IMAGE_TYPES
        elif variant=='video' and public['type']=='VIDEO':
            video = public['mediaFile']['mediaFileMetadata']['videoMetadata']
            if video['processingStatus']!='READY':
                raise PickerError('not_ready')
            suffix,limit,allowed = '=dv',VIDEO_LIMIT,{'video/mp4'}
        else:
            raise PickerError('invalid_input')
        try:
            raw,mime,status = self._request('GET',base+suffix,limit=limit,media=True)
            if status!=200 or mime not in allowed or not _sniff(raw,mime):
                raise PickerError('unsupported_media')
            if self._token.encode('ascii') in raw:
                raise PickerError('bad_response')
            if time.time()>=self._selected_until:
                self._clear_selection()
                raise PickerError('expired')
            return DownloadedMedia(raw,mime,public['mediaFile']['filename'],variant)
        except PickerError as error:
            if error.code in {'reauth','forbidden','not_found'}:
                self._clear_selection()
            raise
