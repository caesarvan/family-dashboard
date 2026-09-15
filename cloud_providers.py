"""Bounded Microsoft Graph / Google Calendar and Tasks adapters.

Callers own OAuth, encryption, selection/visibility and atomic snapshot publication.
No provider request is retried here: POST retries can duplicate remote tasks.
Optional transport(method, url, token, body=None, headers=None) returns decoded JSON
or raises ProviderError. Its URL is validated before invocation, like real requests.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import socket
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
DISPLAY_TZ = ZoneInfo("Asia/Shanghai")
MAX_ITEMS = 2500
MAX_PAGES = 100
MAX_BODY = 4_000_000
REQUEST_BUDGET_SECONDS = 25
GRAPH = "https://graph.microsoft.com/v1.0"
GOOGLE_CALENDAR = "https://www.googleapis.com/calendar/v3"
GOOGLE_TASKS = "https://tasks.googleapis.com/tasks/v1"
PUBLICATION_PROPERTY = 'String {ae486c85-a64c-4f5d-8907-b282e5bc9188} Name HouseholdPublication'

# Common Microsoft/Windows identifiers. Unknown zones fail the entire snapshot
# rather than silently moving an all-day occurrence to the wrong calendar date.
WINDOWS_ZONES = {
    "UTC": "UTC", "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Etc/GMT+11", "UTC-09": "Etc/GMT+9", "UTC-08": "Etc/GMT+8",
    "UTC-02": "Etc/GMT+2", "UTC+12": "Etc/GMT-12", "UTC+13": "Etc/GMT-13",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles", "Mountain Standard Time": "America/Denver",
    "US Mountain Standard Time": "America/Phoenix", "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York", "US Eastern Standard Time": "America/Indiana/Indianapolis",
    "Atlantic Standard Time": "America/Halifax", "Newfoundland Standard Time": "America/St_Johns",
    "SA Pacific Standard Time": "America/Bogota", "SA Western Standard Time": "America/La_Paz",
    "SA Eastern Standard Time": "America/Cayenne", "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires", "Pacific SA Standard Time": "America/Santiago",
    "Greenland Standard Time": "America/Nuuk", "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde", "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw", "W. Central Africa Standard Time": "Africa/Lagos",
    "Morocco Standard Time": "Africa/Casablanca", "FLE Standard Time": "Europe/Kyiv",
    "GTB Standard Time": "Europe/Bucharest", "E. Europe Standard Time": "Europe/Chisinau",
    "Egypt Standard Time": "Africa/Cairo", "South Africa Standard Time": "Africa/Johannesburg",
    "Israel Standard Time": "Asia/Jerusalem", "Turkey Standard Time": "Europe/Istanbul",
    "Russian Standard Time": "Europe/Moscow", "Arab Standard Time": "Asia/Riyadh",
    "Arabic Standard Time": "Asia/Baghdad", "E. Africa Standard Time": "Africa/Nairobi",
    "Iran Standard Time": "Asia/Tehran", "Arabian Standard Time": "Asia/Dubai",
    "Azerbaijan Standard Time": "Asia/Baku", "Georgian Standard Time": "Asia/Tbilisi",
    "Afghanistan Standard Time": "Asia/Kabul", "Pakistan Standard Time": "Asia/Karachi",
    "West Asia Standard Time": "Asia/Tashkent", "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo", "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Bishkek", "Bangladesh Standard Time": "Asia/Dhaka",
    "Myanmar Standard Time": "Asia/Yangon", "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei", "W. Australia Standard Time": "Australia/Perth",
    "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "AUS Central Standard Time": "Australia/Darwin", "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Australia Standard Time": "Australia/Brisbane", "AUS Eastern Standard Time": "Australia/Sydney",
    "Tasmania Standard Time": "Australia/Hobart", "West Pacific Standard Time": "Pacific/Port_Moresby",
    "New Zealand Standard Time": "Pacific/Auckland", "Fiji Standard Time": "Pacific/Fiji",
    "Tonga Standard Time": "Pacific/Tongatapu", "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}


class ProviderError(Exception):
    def __init__(self, message, status=502, reauth=False):
        super().__init__(message)
        self.message, self.status, self.reauth = message, status, reauth


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")


def _text(value, maximum=100, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise ProviderError("云端返回了无效的文本数据")
    return value.strip()[:maximum] or default


def _full_text(value, maximum=2048, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise ProviderError("云端返回了无效的文本数据")
    if len(value.strip()) > maximum:
        raise ProviderError("云端标题、地点或备注超过显示上限，已保留上次成功同步的数据")
    return value.strip() or default


def _object(value):
    if not isinstance(value, dict):
        raise ProviderError("云端返回了无效的数据格式")
    return value


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ProviderError("云端记录缺少有效标识")
    return value


def _zone(name):
    name = name or "UTC"
    try:
        return ZoneInfo(WINDOWS_ZONES.get(name, name))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ProviderError("日历使用了尚不支持的时区，请在原日历中检查时区设置") from None


def _datetime(value, zone="UTC"):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_zone(zone))
    except (ValueError, AttributeError, TypeError):
        raise ProviderError("云端日历包含无法识别的日期") from None


def _iso(value):
    return value.astimezone(DISPLAY_TZ).isoformat(timespec="seconds")


def _day(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ProviderError("云端清单包含无法识别的日期") from None
    return datetime.combine(parsed, time.min, DISPLAY_TZ).isoformat(timespec="seconds")


def _version(item):
    return str(item.get("@odata.etag") or item.get("etag") or
               item.get("lastModifiedDateTime") or item.get("updated") or
               hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest())


def _error(status):
    if status == 401:
        return ProviderError("云端授权已失效，请重新绑定此账号", 401, True)
    if status == 403:
        return ProviderError("云端拒绝访问，请检查授权范围或该日历、清单的访问权限", 403)
    if status == 404:
        return ProviderError("云端记录已删除或不再共享，请刷新同步状态", 409)
    if status in {409, 412}:
        return ProviderError("这条任务已在云端更新，请同步后重试", 409)
    if status == 429:
        return ProviderError("云端服务暂时限流，稍后会自动重试", 429)
    return ProviderError("云端服务暂时不可用，请稍后重试")


class CloudProvider:
    def __init__(self, provider: str, access_token: str, transport=None):
        if provider not in {"microsoft", "google"}:
            raise ProviderError("不支持的云端服务", 400)
        if not isinstance(access_token, str) or not access_token:
            raise ProviderError("缺少云端授权，请重新绑定", 401, True)
        self.provider, self.token, self.transport = provider, access_token, transport
        self.deadline = perf_counter() + REQUEST_BUDGET_SECONDS

    def _check_url(self, url):
        parsed = urlsplit(url)
        allowed = ({"graph.microsoft.com": ("/v1.0/", "/oidc/userinfo")} if self.provider == "microsoft" else {
            "openidconnect.googleapis.com": ("/v1/userinfo",),
            "www.googleapis.com": ("/calendar/v3/",),
            "tasks.googleapis.com": ("/tasks/v1/",),
        })
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.netloc != parsed.hostname or parsed.hostname not in allowed
                or not any(parsed.path.startswith(prefix) for prefix in allowed[parsed.hostname])):
            raise ProviderError("云端返回了不安全的分页地址")

    def request(self, method, url, body=None, headers=None):
        self._check_url(url)
        remaining = self.deadline - perf_counter()
        if remaining <= 0:
            raise ProviderError("本次云端读取超时，已保留上次成功同步的数据，请稍后重试", 504)
        headers = dict(headers or {})
        if self.transport:
            result = self.transport(method, url, self.token, body=body, headers=headers)
            return _object(result)
        request_headers = {"Accept": "application/json", "Authorization": "Bearer " + self.token,
                           **headers}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        req = Request(url, data=payload, headers=request_headers, method=method)
        try:
            with build_opener(_NoRedirect()).open(req, timeout=min(15, remaining)) as response:
                raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ProviderError("云端数据量过大，请缩小所选日历或清单范围")
            return _object(json.loads(raw) if raw else {})
        except HTTPError as error:
            failure = _error(error.code)
            failure.upstream_status = error.code
            raise failure from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise ProviderError("暂时无法连接云端服务，请稍后重试") from None
        except (ValueError, UnicodeError):
            raise ProviderError("云端返回了无法读取的数据") from None

    def _pages(self, url, headers=None, maximum=MAX_ITEMS):
        """Collect everything or raise: callers never receive a partial snapshot."""
        initial = urlsplit(url)
        base_query = dict(parse_qsl(initial.query, keep_blank_values=True))
        records, seen = [], set()
        for _ in range(MAX_PAGES):
            if url in seen:
                raise ProviderError("云端分页出现循环，已保留上次成功同步的数据")
            seen.add(url)
            payload = self.request("GET", url, headers=headers)
            key = "value" if self.provider == "microsoft" else "items"
            # Google permits omitted items for empty collections; Graph does not.
            values = payload.get(key, [] if self.provider == "google" else None)
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise ProviderError("云端返回了无效的分页数据")
            records.extend(values)
            if len(records) > maximum:
                raise ProviderError("所选来源超过同步数量上限，请先整理云端记录")
            if self.provider == "microsoft":
                next_url = payload.get("@odata.nextLink")
                if not next_url:
                    return records
                if not isinstance(next_url, str) or len(next_url) > 16000:
                    raise ProviderError("云端返回了无效的分页地址")
                self._check_url(next_url)
                # Graph owns continuation queries; it cannot change resources.
                candidate = urlsplit(next_url)
                if unquote(candidate.path) != unquote(initial.path):
                    raise ProviderError("云端分页切换了数据来源")
                url = next_url
            else:
                token = payload.get("nextPageToken")
                if not token:
                    return records
                if not isinstance(token, str) or len(token) > 16000:
                    raise ProviderError("云端返回了无效的分页标识")
                url = urlunsplit((initial.scheme, initial.netloc, initial.path,
                                  urlencode({**base_query, "pageToken": token}), ""))
        raise ProviderError("云端分页过多，已保留上次成功同步的数据")

    def identity(self):
        endpoint = ("https://graph.microsoft.com/oidc/userinfo" if self.provider == "microsoft"
                    else "https://openidconnect.googleapis.com/v1/userinfo")
        identity = self.request("GET", endpoint)
        subject = _identifier(identity.get("sub"))
        # Email is a display label only, never a lookup or auto-link identity.
        return {"subject": subject, "name": _text(identity.get("name"), 120, "已绑定账号"),
                "email": _text(identity.get("email"), 254)}

    def list_sources(self):
        if self.provider == "microsoft":
            calendars = self._pages(GRAPH + "/me/calendars?$top=100", maximum=500)
            tasks = self._pages(GRAPH + "/me/todo/lists?$top=100", maximum=500)
            result = [{"id": _identifier(item.get("id")), "kind": "calendar",
                       "name": _text(item.get("name"), 150, "未命名日历"), "writable": False}
                      for item in calendars]
            result.extend({"id": _identifier(item.get("id")), "kind": "tasks",
                           "name": _text(item.get("displayName"), 150, "未命名清单"), "writable": True}
                          for item in tasks)
            return result
        calendars = self._pages(GOOGLE_CALENDAR + "/users/me/calendarList?maxResults=250&minAccessRole=reader", maximum=500)
        tasks = self._pages(GOOGLE_TASKS + "/users/@me/lists?maxResults=100", maximum=500)
        result = [{"id": _identifier(item.get("id")), "kind": "calendar",
                   "name": _text(item.get("summaryOverride") or item.get("summary"), 150, "未命名日历"),
                   "writable": False} for item in calendars if not item.get("deleted")]
        result.extend({"id": _identifier(item.get("id")), "kind": "tasks",
                       "name": _text(item.get("title"), 150, "未命名清单"), "writable": True}
                      for item in tasks)
        return result

    def snapshot(self, source: dict, start: datetime, end: datetime):
        kind = source.get("kind")
        sid = quote(_identifier(source.get("id")), safe="")
        if kind not in {"calendar", "tasks"}:
            raise ProviderError("未知的数据来源类型", 400)
        if kind == "tasks":
            url = (GRAPH + f"/me/todo/lists/{sid}/tasks?$top=100" if self.provider == "microsoft" else
                   GOOGLE_TASKS + f"/lists/{sid}/tasks?maxResults=100&showCompleted=true&showHidden=true&showDeleted=false")
            raw = self._pages(url)
        else:
            if not isinstance(start, datetime) or not isinstance(end, datetime) or start.tzinfo is None or end.tzinfo is None or start >= end:
                raise ProviderError("日历同步需要有效的带时区日期范围", 400)
            if self.provider == "microsoft":
                url = GRAPH + f"/me/calendars/{sid}/calendarView?" + urlencode({
                    "startDateTime": start.astimezone(UTC).isoformat(),
                    "endDateTime": end.astimezone(UTC).isoformat(), "$top": 100})
                raw = self._pages(url, headers={"Prefer": 'outlook.timezone="UTC"'})
            else:
                url = GOOGLE_CALENDAR + f"/calendars/{sid}/events?" + urlencode({
                    "singleEvents": "true", "showDeleted": "false", "maxResults": 250,
                    "timeMin": start.astimezone(UTC).isoformat(), "timeMax": end.astimezone(UTC).isoformat(),
                    "timeZone": "Asia/Shanghai"})
                raw = self._pages(url)
        normalized = []
        seen = set()
        for item in raw:
            if item.get("deleted") or item.get("@removed") or item.get("isCancelled") or item.get("status") == "cancelled":
                continue
            record = self._task(item) if kind == "tasks" else self._event(item)
            if record["id"] in seen:
                raise ProviderError("云端分页包含重复记录，请稍后重新同步")
            seen.add(record["id"])
            normalized.append(record)
        return normalized

    def _task(self, item):
        if self.provider == "microsoft":
            body = _object(item.get("body") or {})
            note = _text(body.get("content"), 100_000)
            if str(body.get("contentType", "")).lower() == "html":
                parser = _PlainText()
                parser.feed(note)
                note = "".join(parser.parts).strip()
            due = _object(item.get("dueDateTime") or {})
            due_day = _datetime(due["dateTime"], due.get("timeZone", "UTC")).date().isoformat() if due.get("dateTime") else ""
        else:
            note = _full_text(item.get("notes"), 8000)
            # Google Tasks stores a date encoded at UTC midnight, not a deadline instant.
            due_day = str(item.get("due") or "")[:10]
            if due_day:
                _day(due_day)
        data = {"title": _full_text(item.get("title"), default="未命名任务"), "owner": "shared",
                "done": item.get("status") == "completed", "due": due_day, "note": _full_text(note, 8000), "tripId": ""}
        record = {"id": _identifier(item.get("id")), "version": _version(item), "data": data}
        marker = re.search(r'(?:\n\s*)?\[家庭看板同步:([a-f0-9]{64})\]\s*$', data['note'])
        if marker:
            record['publicationKey'] = marker[1]
            data['note'] = data['note'][:marker.start()].rstrip()
        return record

    def _event(self, item):
        start, end = _object(item.get("start")), _object(item.get("end"))
        if self.provider == "microsoft":
            all_day = item.get("isAllDay") is True
            begin = _datetime(start.get("dateTime"), start.get("timeZone", "UTC"))
            finish = _datetime(end.get("dateTime"), end.get("timeZone", "UTC"))
            if all_day:
                # UTC calendarView times must be converted back to original wall dates.
                begin_day = begin.astimezone(_zone(item.get("originalStartTimeZone") or start.get("timeZone"))).date().isoformat()
                end_day = finish.astimezone(_zone(item.get("originalEndTimeZone") or item.get("originalStartTimeZone") or end.get("timeZone"))).date().isoformat()
                begin_text, end_text = _day(begin_day), _day(end_day)
            else:
                begin_text, end_text = _iso(begin), _iso(finish)
            location = _full_text(_object(item.get("location") or {}).get("displayName"))
            title = _full_text(item.get("subject"), default="未命名安排")
        else:
            all_day = bool(start.get("date"))
            if all_day:
                begin_text, end_text = _day(start.get("date")), _day(end.get("date"))
            else:
                begin_text = _iso(_datetime(start.get("dateTime"), start.get("timeZone", "UTC")))
                end_text = _iso(_datetime(end.get("dateTime"), end.get("timeZone", "UTC")))
            location = _full_text(item.get("location"))
            title = _full_text(item.get("summary"), default="未命名安排")
        if end_text < begin_text or (all_day and end_text == begin_text):
            raise ProviderError("云端日历包含无效的起止日期")
        data = {"title": title, "start": begin_text, "end": end_text, "allDay": all_day,
                "location": location, "owner": "shared", "source": "Outlook" if self.provider == "microsoft" else "Google",
                "imported": False}
        return {"id": _identifier(item.get("id")), "version": _version(item), "data": data}

    def write_task(self, source, changes, remote_id=None, version=None):
        if source.get("kind") != "tasks" or source.get("writable") is False:
            raise ProviderError("此来源只支持查看", 403)
        sid = quote(_identifier(source.get("id")), safe="")
        base = (GRAPH + f"/me/todo/lists/{sid}/tasks" if self.provider == "microsoft" else
                GOOGLE_TASKS + f"/lists/{sid}/tasks")
        if remote_id is not None:
            if set(changes) - {"done", "revision"} or not isinstance(changes.get("done"), bool):
                raise ProviderError("同步任务目前仅支持勾选和取消完成，请在原应用编辑其他内容", 400)
            if not isinstance(version, str) or not version:
                raise ProviderError("任务缺少云端版本，请先同步", 409)
            url = base + "/" + quote(_identifier(remote_id), safe="")
            current = self.request("GET", url)
            if _version(current) != version:
                raise ProviderError("这条任务已在云端更新，请同步后重试", 409)
            etag = current.get("@odata.etag") if self.provider == "microsoft" else current.get("etag")
            headers = {"If-Match": etag} if isinstance(etag, str) and etag else {}
            status = "completed" if changes["done"] else ("notStarted" if self.provider == "microsoft" else "needsAction")
            payload = {"status": status}
            if self.provider == "google" and not changes["done"]:
                payload["completed"] = None
            updated = self.request("PATCH", url, payload, headers)
            return self._task(updated)
        title = changes.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise ProviderError("任务名称需为 1～100 个字符", 400)
        note = changes.get("note", "")
        due = changes.get("due", "")
        if not isinstance(note, str) or len(note) > 500:
            raise ProviderError("任务备注不能超过 500 个字符", 400)
        if due:
            _day(due)
        payload = {"title": title.strip()}
        if self.provider == "microsoft":
            if note:
                payload["body"] = {"contentType": "html", "content": html.escape(note).replace("\n", "<br>")}
            if due:
                payload["dueDateTime"] = {"dateTime": due + "T00:00:00", "timeZone": "China Standard Time"}
        else:
            if note:
                payload["notes"] = note
            if due:
                payload["due"] = due + "T00:00:00Z"
        return self._task(self.request("POST", base, payload))

    def _task_publication_base(self, source):
        if source.get('kind') != 'tasks':
            raise ProviderError('请选择待办清单', 400)
        sid = quote(_identifier(source.get('id')), safe='')
        return GRAPH + f'/me/todo/lists/{sid}/tasks' if self.provider == 'microsoft' else GOOGLE_TASKS + f'/lists/{sid}/tasks'

    def task_publication_payload(self, task, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ProviderError('待办发布标识无效', 400)
        note = _full_text(task.get('note'), 500) + '\n\n[家庭看板同步:' + key + ']'
        title = _full_text(task.get('title'), 100)
        due = task.get('due', '')
        if not title or not isinstance(task.get('done'), bool):
            raise ProviderError('待办标题或完成状态无效', 400)
        if due:
            _day(due)
        payload = {'title': title, 'status': 'completed' if task['done'] else ('notStarted' if self.provider == 'microsoft' else 'needsAction')}
        if self.provider == 'microsoft':
            # To Do's documented body type is HTML. Escape the user note and
            # append the recovery marker in the same POST, never a second write.
            payload.update(body={'contentType': 'html', 'content': html.escape(note).replace('\n', '<br>')},
                           dueDateTime={'dateTime': due + 'T00:00:00', 'timeZone': 'China Standard Time'} if due else None)
        else:
            payload.update(notes=note, due=due + 'T00:00:00Z' if due else None)
            if not task['done']:
                payload['completed'] = None
        return payload

    def _task_publication_record(self, raw):
        if raw.get('deleted') or raw.get('@removed'):
            error = ProviderError('云端任务已删除，本地任务仍保留', 409)
            error.upstream_status = 404
            raise error
        record = self._task(raw)
        etag = raw.get('@odata.etag') if self.provider == 'microsoft' else raw.get('etag')
        if not isinstance(etag, str) or not etag or len(etag) > 1000 or '\r' in etag or '\n' in etag:
            raise ProviderError('云端未提供可安全更新的版本，待办同步已暂停', 409)
        return {'id': record['id'], 'etag': etag, 'key': record.get('publicationKey', ''),
                'managed': {k: record['data'][k] for k in ('title', 'due', 'note', 'done')}}

    def get_task_publication(self, source, remote_id):
        return self._task_publication_record(self.request('GET', self._task_publication_base(source) + '/' + quote(_identifier(remote_id), safe='')))

    def find_task_publication(self, source, key):
        # Neither Tasks API documents a caller-chosen idempotency key. Search
        # every bounded page, including completed/hidden Google tasks, before
        # interpreting a missing response. An incomplete scan raises, not None.
        url = self._task_publication_base(source) + ('?$top=100' if self.provider == 'microsoft' else '?maxResults=100&showCompleted=true&showHidden=true&showDeleted=false')
        matches = [r for r in self._pages(url) if self._task(r).get('publicationKey') == key and not r.get('deleted') and not r.get('@removed')]
        if len(matches) > 1:
            raise ProviderError('云端有多个相同关联标识，请在原清单核对后重试', 409)
        return self.get_task_publication(source, matches[0]['id']) if matches else None

    def create_task_publication(self, source, task, key):
        try:
            raw = self.request('POST', self._task_publication_base(source), self.task_publication_payload(task, key))
        except ProviderError as error:
            # Only an explicit upstream rejection of the POST proves no task
            # was committed. A failed subsequent GET is still uncertain.
            if getattr(error, 'upstream_status', None) in {400, 401, 403, 404, 429}:
                error.create_rejected = True
            raise
        return self.get_task_publication(source, _identifier(raw.get('id')))

    def update_task_publication(self, source, task, key, remote_id, etag):
        if not isinstance(etag, str) or not etag or len(etag) > 1000 or '\r' in etag or '\n' in etag:
            raise ProviderError('缺少云端版本，无法安全更新待办', 409)
        url = self._task_publication_base(source) + '/' + quote(_identifier(remote_id), safe='')
        self.request('PATCH', url, self.task_publication_payload(task, key), {'If-Match': etag})
        return self.get_task_publication(source, remote_id)

    def calendar_access(self, source):
        """Check actual per-calendar ACL independently of OAuth scope."""
        sid = quote(_identifier(source.get('id')), safe='')
        if source.get('kind') != 'calendar':
            raise ProviderError('请选择日历', 400)
        if self.provider == 'microsoft':
            raw = self.request('GET', GRAPH + f'/me/calendars/{sid}?$select=id,name,canEdit')
            return raw.get('canEdit') is True
        raw = self.request('GET', GOOGLE_CALENDAR + f'/users/me/calendarList/{sid}')
        return raw.get('accessRole') in {'owner', 'writer'}

    def _publication_base(self, source):
        if source.get('kind') != 'calendar':
            raise ProviderError('请选择日历', 400)
        sid = quote(_identifier(source.get('id')), safe='')
        return GRAPH + f'/me/calendars/{sid}/events' if self.provider == 'microsoft' else GOOGLE_CALENDAR + f'/calendars/{sid}/events'

    def publication_payload(self, event, key, digest, creating=False):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ProviderError('发布标识无效', 400)
        title = _full_text(event.get('title'), 2048)
        location, note = _full_text(event.get('location'), 2048), _full_text(event.get('note'), 8000)
        begin, end = _datetime(event.get('start')), _datetime(event.get('end'))
        all_day = event.get('allDay') is True
        if not title or end <= begin:
            raise ProviderError('日程标题或起止日期无效', 400)
        if self.provider == 'microsoft':
            def ms_time(value):
                if all_day:
                    return {'dateTime': value.astimezone(DISPLAY_TZ).strftime('%Y-%m-%dT00:00:00'), 'timeZone': 'China Standard Time'}
                return {'dateTime': value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'}
            payload = {'subject': title, 'location': {'displayName': location}, 'body': {'contentType': 'text', 'content': note},
                       'start': ms_time(begin), 'end': ms_time(end), 'isAllDay': all_day,
                       'singleValueExtendedProperties': [{'id': PUBLICATION_PROPERTY, 'value': key + ':' + digest}]}
            if creating:
                payload['transactionId'] = '-'.join([key[:8], key[8:12], key[12:16], key[16:20], key[20:32]])
                payload['isReminderOn'] = False
        else:
            def google_time(value):
                return {'date': value.astimezone(DISPLAY_TZ).date().isoformat()} if all_day else {'dateTime': value.isoformat()}
            payload = {'summary': title, 'location': location, 'description': note, 'start': google_time(begin), 'end': google_time(end),
                       'extendedProperties': {'private': {'householdPublication': key, 'householdDigest': digest}}}
            if creating:
                payload['id'] = 'h' + key
                payload['reminders'] = {'useDefault': False}
        return payload

    def _publication_record(self, raw):
        if raw.get('attendees'):
            raise ProviderError('云端事项含参与者，已停止更新以免发送邀请或会议变更', 409)
        if raw.get('isCancelled') or raw.get('status') == 'cancelled':
            raise ProviderError('云端事项已取消，请先核对', 409)
        etag = raw.get('@odata.etag') if self.provider == 'microsoft' else raw.get('etag')
        if not isinstance(etag, str) or not etag or len(etag) > 1000 or '\r' in etag or '\n' in etag:
            raise ProviderError('云端未提供可安全更新的版本标识，发布已暂停', 409)
        record = self._event(raw)
        if self.provider == 'microsoft':
            values = raw.get('singleValueExtendedProperties') or []
            metadata = {r.get('id'): r.get('value') for r in values if isinstance(r, dict)}
            marker = metadata.get(PUBLICATION_PROPERTY, '')
            key, _, digest = marker.partition(':') if isinstance(marker, str) else ('', '', '')
            body = _object(raw.get('body') or {})
            note = _full_text(body.get('content'), 8000)
            if str(body.get('contentType', '')).lower() == 'html':
                parser = _PlainText(); parser.feed(note); note = ''.join(parser.parts).strip()
        else:
            metadata = _object(_object(raw.get('extendedProperties') or {}).get('private') or {})
            key, digest = metadata.get('householdPublication'), metadata.get('householdDigest')
            note = _full_text(raw.get('description'), 8000)
        managed = {k: record['data'][k] for k in ('title', 'location', 'start', 'end', 'allDay')}
        managed['note'] = note
        return {'id': record['id'], 'etag': etag, 'key': key, 'digest': digest, 'managed': managed}

    def get_calendar_publication(self, source, remote_id):
        url = self._publication_base(source) + '/' + quote(_identifier(remote_id), safe='')
        headers = {}
        if self.provider == 'microsoft':
            url += '?' + urlencode({'$expand': f"singleValueExtendedProperties($filter=id eq '{PUBLICATION_PROPERTY}')"})
            headers = {'Prefer': 'outlook.body-content-type="text"'}
        return self._publication_record(self.request('GET', url, headers=headers))

    def find_calendar_publication(self, source, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ProviderError('发布标识无效', 400)
        if self.provider == 'google':
            try:
                return self.get_calendar_publication(source, 'h' + key)
            except ProviderError as exc:
                if getattr(exc, 'upstream_status', exc.status) == 404:
                    return None
                raise
        url = self._publication_base(source) + '?' + urlencode({
            '$filter': f"singleValueExtendedProperties/Any(ep: ep/id eq '{PUBLICATION_PROPERTY}' and startswith(ep/value, '{key}:'))",
            '$top': 2})
        values = self._pages(url, headers={'Prefer': 'outlook.body-content-type="text"'}, maximum=2)
        if len(values) > 1:
            raise ProviderError('云端存在多个相同发布标识，已暂停以避免重复事项', 409)
        return self.get_calendar_publication(source, _identifier(values[0].get('id'))) if values else None

    def create_calendar_publication(self, source, event, key, digest):
        payload = self.publication_payload(event, key, digest, creating=True)
        url = self._publication_base(source)
        if self.provider == 'google':
            url += '?sendUpdates=none'
        raw = self.request('POST', url, payload)
        # Some Graph create responses omit expanded properties. Read back using
        # the returned ID before calling a queued operation successful.
        return self.get_calendar_publication(source, _identifier(raw.get('id')))

    def update_calendar_publication(self, source, event, key, digest, remote_id, etag):
        if not isinstance(etag, str) or not etag or len(etag) > 1000 or '\r' in etag or '\n' in etag:
            raise ProviderError('缺少云端版本，无法安全更新', 409)
        url = self._publication_base(source) + '/' + quote(_identifier(remote_id), safe='')
        if self.provider == 'google':
            url += '?sendUpdates=none'
        payload = self.publication_payload(event, key, digest)
        self.request('PATCH', url, payload, {'If-Match': etag})
        return self.get_calendar_publication(source, remote_id)
