from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

import cloud_providers as module
from cloud_providers import CloudProvider, ProviderError

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 1, tzinfo=timezone.utc)
TASKS = {"id": "list/with=special", "kind": "tasks", "writable": True}
CALENDAR = {"id": "calendar@example.com", "kind": "calendar", "writable": False}


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, token, body=None, headers=None):
        self.calls.append((method, url, token, body, headers))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_google_tasks_completed_hidden_pagination_and_date_semantics():
    transport = Transport(
        {"items": [{"id": "one", "title": "买机票", "status": "needsAction", "etag": '"a"', "due": "2026-09-22T00:00:00Z"}], "nextPageToken": "token with&symbols"},
        {"items": [{"id": "two", "title": "酒店", "status": "completed", "hidden": True, "etag": '"b"'},
                   {"id": "deleted", "deleted": True}]},
    )
    result = CloudProvider("google", "private-token", transport).snapshot(TASKS, START, END)
    assert len(result) == 2
    assert result[0]["data"]["due"] == "2026-09-22"
    assert result[1]["data"]["done"] is True
    assert result[1]["version"] == '"b"'
    query = parse_qs(urlsplit(transport.calls[0][1]).query)
    assert query["showCompleted"] == ["true"]
    assert query["showHidden"] == ["true"]
    assert query["showDeleted"] == ["false"]
    assert parse_qs(urlsplit(transport.calls[1][1]).query)["pageToken"] == ["token with&symbols"]
    assert "/list%2Fwith%3Dspecial/" in transport.calls[0][1]


def test_google_event_expansion_and_all_day_exclusive_end():
    transport = Transport({"items": [
        {"id": "daily-occurrence", "summary": "会议", "etag": '"1"', "location": "东京",
         "start": {"dateTime": "2026-09-14T09:00:00+09:00"}, "end": {"dateTime": "2026-09-14T10:00:00+09:00"}},
        {"id": "holiday", "summary": "假期", "start": {"date": "2026-09-21"}, "end": {"date": "2026-09-23"}},
        {"id": "cancelled", "status": "cancelled"},
    ]})
    records = CloudProvider("google", "token", transport).snapshot(CALENDAR, START, END)
    assert len(records) == 2
    assert records[0]["data"]["start"] == "2026-09-14T08:00:00+08:00"
    assert records[0]["data"]["location"] == "东京"
    assert records[1]["data"]["allDay"] is True
    assert records[1]["data"]["start"] == "2026-09-21T00:00:00+08:00"
    assert records[1]["data"]["end"] == "2026-09-23T00:00:00+08:00"
    query = parse_qs(urlsplit(transport.calls[0][1]).query)
    assert query["singleEvents"] == ["true"]
    assert query["timeMin"] == [START.isoformat()]
    assert query["timeMax"] == [END.isoformat()]


def test_microsoft_utc_calendar_preserves_original_all_day_date():
    transport = Transport({"value": [
        {"id": "tokyo-holiday", "subject": "日本休假", "isAllDay": True,
         "originalStartTimeZone": "Tokyo Standard Time", "originalEndTimeZone": "Tokyo Standard Time",
         "start": {"dateTime": "2026-09-20T15:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-09-21T15:00:00.0000000", "timeZone": "UTC"}},
        {"id": "meeting", "subject": "会议", "isAllDay": False, "@odata.etag": 'W/"2"',
         "start": {"dateTime": "2026-09-21T01:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-09-21T02:00:00.0000000", "timeZone": "UTC"}},
        {"id": "cancelled", "isCancelled": True},
    ]})
    records = CloudProvider("microsoft", "token", transport).snapshot(CALENDAR, START, END)
    assert records[0]["data"]["start"] == "2026-09-21T00:00:00+08:00"
    assert records[0]["data"]["end"] == "2026-09-22T00:00:00+08:00"
    assert records[1]["data"]["start"] == "2026-09-21T09:00:00+08:00"
    assert len(records) == 2
    assert transport.calls[0][4]["Prefer"] == 'outlook.timezone="UTC"'


def test_microsoft_tasks_strip_html_and_preserve_due_wall_date():
    transport = Transport({"value": [{"id": "task1", "title": "完成", "status": "completed",
                            "body": {"contentType": "html", "content": "<p>看清单 &amp; 金额</p>"},
                            "dueDateTime": {"dateTime": "2026-09-21T00:00:00", "timeZone": "Tokyo Standard Time"},
                            "lastModifiedDateTime": "2026-09-14T01:00:00Z"}]})
    record = CloudProvider("microsoft", "token", transport).snapshot(TASKS, START, END)[0]
    assert record["data"]["note"] == "看清单 & 金额"
    assert record["data"]["due"] == "2026-09-21"
    assert record["data"]["done"] is True


@pytest.mark.parametrize("next_url", [
    "https://attacker.example/v1.0/me/todo/lists/list/tasks",
    "https://graph.microsoft.com@attacker.example/v1.0/me/todo/lists/list/tasks",
    "https://graph.microsoft.com/v1.0/me/messages",
    "http://graph.microsoft.com/v1.0/me/todo/lists/list/tasks",
])
def test_microsoft_unsafe_continuations_rejected_before_token_sent(next_url):
    transport = Transport({"value": [{"id": "one", "title": "preserve"}], "@odata.nextLink": next_url})
    with pytest.raises(ProviderError):
        CloudProvider("microsoft", "sensitive", transport).snapshot(TASKS, START, END)
    assert len(transport.calls) == 1


def test_failed_last_page_does_not_return_partial_snapshot():
    transport = Transport({"items": [{"id": "one", "title": "preserve"}], "nextPageToken": "next"},
                          ProviderError("provider unavailable"))
    with pytest.raises(ProviderError, match="provider unavailable"):
        CloudProvider("google", "token", transport).snapshot(TASKS, START, END)


def test_pagination_limit_and_duplicate_records_fail_instead_of_truncate(monkeypatch):
    monkeypatch.setattr(module, "MAX_PAGES", 2)
    transport = Transport({"items": [], "nextPageToken": "one"}, {"items": [], "nextPageToken": "two"})
    with pytest.raises(ProviderError, match="分页过多"):
        CloudProvider("google", "token", transport).snapshot(TASKS, START, END)
    duplicate = Transport({"items": [{"id": "same", "title": "one"}, {"id": "same", "title": "two"}]})
    with pytest.raises(ProviderError, match="重复"):
        CloudProvider("google", "token", duplicate).snapshot(TASKS, START, END)


@pytest.mark.parametrize("provider, endpoint", [
    ("microsoft", "https://graph.microsoft.com/oidc/userinfo"),
    ("google", "https://openidconnect.googleapis.com/v1/userinfo"),
])
def test_identity_uses_authenticated_stable_subject(provider, endpoint):
    transport = Transport({"sub": "stable-subject", "name": "Member", "email": "email@example.com"})
    identity = CloudProvider(provider, "token", transport).identity()
    assert identity == {"subject": "stable-subject", "name": "Member", "email": "email@example.com"}
    assert transport.calls[0][:3] == ("GET", endpoint, "token")
    no_subject = Transport({"email": "email@example.com"})
    with pytest.raises(ProviderError):
        CloudProvider(provider, "token", no_subject).identity()


def test_google_sources_only_supported_visibility_and_readonly_calendar():
    transport = Transport({"items": [{"id": "work", "summary": "工作"}]},
                          {"items": [{"id": "todo", "title": "共同待办"}]})
    sources = CloudProvider("google", "token", transport).list_sources()
    assert sources == [{"id": "work", "name": "工作", "kind": "calendar", "writable": False},
                       {"id": "todo", "name": "共同待办", "kind": "tasks", "writable": True}]
    assert parse_qs(urlsplit(transport.calls[0][1]).query)["minAccessRole"] == ["reader"]


def test_write_conflict_stops_before_patch():
    transport = Transport({"id": "task", "title": "changed elsewhere", "etag": '"new"'})
    with pytest.raises(ProviderError) as raised:
        CloudProvider("google", "token", transport).write_task(TASKS, {"done": True}, "task", '"old"')
    assert raised.value.status == 409
    assert [call[0] for call in transport.calls] == ["GET"]


@pytest.mark.parametrize("provider, tag_name, undone", [
    ("microsoft", "@odata.etag", "notStarted"), ("google", "etag", "needsAction"),
])
def test_write_task_narrow_patch_conditional_version_and_remote_ack(provider, tag_name, undone):
    transport = Transport({"id": "task", "title": "only status changes", "status": "completed", tag_name: '"v1"'},
                          {"id": "task", "title": "only status changes", "status": undone, tag_name: '"v2"'})
    record = CloudProvider(provider, "token", transport).write_task(TASKS, {"done": False, "revision": 7}, "task", '"v1"')
    patch = transport.calls[1]
    assert patch[0] == "PATCH"
    assert patch[4] == {"If-Match": '"v1"'}
    assert patch[3] == ({"status": undone, "completed": None} if provider == "google" else {"status": undone})
    assert record["data"]["done"] is False
    assert record["version"] == '"v2"'


def test_write_rejects_other_fields_and_readonly_sources_without_network():
    transport = Transport()
    provider = CloudProvider("google", "token", transport)
    with pytest.raises(ProviderError):
        provider.write_task(TASKS, {"done": True, "title": "not allowed"}, "task", "version")
    with pytest.raises(ProviderError):
        provider.write_task({**TASKS, "writable": False}, {"title": "not allowed"})
    with pytest.raises(ProviderError):
        provider.write_task(CALENDAR, {"title": "not allowed"})
    assert transport.calls == []


def test_microsoft_create_escapes_note_and_writes_only_requested_fields():
    transport = Transport({"id": "new-task", "title": "采购", "status": "notStarted", "@odata.etag": '"new"'})
    record = CloudProvider("microsoft", "token", transport).write_task(TASKS, {"title": "采购", "note": "<b>2 & 3</b>\n备注", "due": "2026-09-22"})
    assert record["id"] == "new-task"
    payload = transport.calls[0][3]
    assert payload["body"] == {"contentType": "html", "content": "&lt;b&gt;2 &amp; 3&lt;/b&gt;<br>备注"}
    assert payload["dueDateTime"] == {"dateTime": "2026-09-22T00:00:00", "timeZone": "China Standard Time"}
    assert set(payload) == {"title", "body", "dueDateTime"}


def test_malformed_snapshot_preserves_old_generation_by_failing():
    transport = Transport({"items": [{"id": "good", "title": "okay"}, {"title": "missing id"}]})
    with pytest.raises(ProviderError, match="标识"):
        CloudProvider("google", "token", transport).snapshot(TASKS, START, END)
    transport = Transport({"items": [{"id": "bad-event", "start": {"dateTime": "invalid"}, "end": {"dateTime": "invalid"}}]})
    with pytest.raises(ProviderError, match="日期"):
        CloudProvider("google", "token", transport).snapshot(CALENDAR, START, END)


def test_full_provider_titles_locations_and_notes_preserved_or_fail():
    title, location, note = "完整标题" * 100, "完整地点" * 100, "完整备注" * 1000
    transport = Transport({"items": [{"id": "long-task", "title": title, "notes": note}]})
    record = CloudProvider("google", "token", transport).snapshot(TASKS, START, END)[0]
    assert record["data"]["title"] == title
    assert record["data"]["note"] == note
    transport = Transport({"items": [{"id": "long-event", "summary": title, "location": location,
                                      "start": {"date": "2026-09-21"}, "end": {"date": "2026-09-22"}}]})
    record = CloudProvider("google", "token", transport).snapshot(CALENDAR, START, END)[0]
    assert record["data"]["title"] == title
    assert record["data"]["location"] == location
    oversized = Transport({"items": [{"id": "long-task", "title": "x" * 2049}]})
    with pytest.raises(ProviderError, match="上限"):
        CloudProvider("google", "token", oversized).snapshot(TASKS, START, END)


def test_microsoft_valid_pagination_may_normalize_percent_encoding():
    next_url = module.GRAPH + "/me/todo/lists/list%2Fwith=special/tasks?$skiptoken=next"
    transport = Transport({"value": [{"id": "one", "title": "one"}], "@odata.nextLink": next_url},
                          {"value": [{"id": "two", "title": "two"}]})
    records = CloudProvider("microsoft", "token", transport).snapshot(TASKS, START, END)
    assert [record["id"] for record in records] == ["one", "two"]


def test_total_request_budget_stops_pagination_without_partial_result(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(module, "perf_counter", lambda: now[0])
    calls = []

    def transport(method, url, token, body=None, headers=None):
        calls.append(url)
        now[0] = 26.0
        return {"items": [{"id": "first", "title": "should not be published"}], "nextPageToken": "next"}

    provider = CloudProvider("google", "token", transport)
    with pytest.raises(ProviderError, match="读取超时") as raised:
        provider.snapshot(TASKS, START, END)
    assert raised.value.status == 504
    assert len(calls) == 1


def test_socket_timeout_is_bounded_by_remaining_total_budget(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(module, "perf_counter", lambda: now[0])
    timeouts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, maximum):
            return b'{"sub":"subject"}'

    class Opener:
        def open(self, request, timeout):
            timeouts.append(timeout)
            return Response()

    monkeypatch.setattr(module, "build_opener", lambda *args: Opener())
    provider = CloudProvider("google", "token")
    now[0] = 20.0
    assert provider.identity()["subject"] == "subject"
    assert timeouts == [5.0]
