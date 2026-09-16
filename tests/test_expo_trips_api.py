"""Real TS form payload -> authenticated Flask -> temporary SQLite, without cloud IO."""
import json
from pathlib import Path
import subprocess

from test_app import app, member

ROOT = Path(__file__).resolve().parents[1]


def payload(client, **extra):
    source = {'people': client.get('/api/state').json['people'], **extra}
    run = subprocess.run(['node', str(ROOT / 'tests/expo_trips_payload.mjs')], input=json.dumps(source), text=True, encoding='utf-8', capture_output=True, check=True, cwd=ROOT)
    return json.loads(run.stdout)


def create(client, headers):
    proposed = client.post('/api/journeys/preview', json=payload(client), headers=headers)
    assert proposed.status_code == 200, proposed.json
    request = {'previewToken': proposed.json['previewToken'], 'idempotencyKey': 'expo-trip-synthetic-create'}
    saved = client.post('/api/journeys/apply', json=request, headers=headers)
    assert saved.status_code == 201, saved.json
    return saved.json, request


def test_ts_new_plan_roundtrip_and_unknown_response_retry(app):
    client, headers = member(app)
    saved, original = create(client, headers)
    replay = client.post('/api/journeys/apply', json=original, headers=headers)
    assert replay.status_code == 200 and replay.json['replayed'] is True
    assert replay.json['id'] == saved['id']
    detail = client.get('/api/journeys/' + saved['id']).json
    assert detail['budget']['total'] == 123429
    assert len(detail['tasks']) == 5
    overview = next(e for e in detail['events'] if e['workflowKey'] == 'event:overview')
    assert overview['start'] == '2026-10-01T00:00:00+08:00'
    assert overview['end'] == '2026-10-04T00:00:00+08:00'
    assert len(client.get('/api/state').json['trips']) == 1
    assert client.get('/api/state').json['finance']['livingSpent'] == 0


def test_ts_edit_keeps_completed_task_and_edited_live_fields(app):
    client, headers = member(app)
    saved, _ = create(client, headers)
    path = '/api/journeys/' + saved['id']
    task = client.get(path).json['tasks'][0]
    response = client.patch('/api/items/tasks/' + task['id'], json={'revision': task['revision'], 'done': True, 'title': '成员单独改过的准备'}, headers=headers)
    assert response.status_code == 200
    draft = payload(client, journey=client.get(path).json, title='新的旅行标题')
    preview = client.post('/api/journeys/preview', json=draft, headers=headers)
    assert preview.status_code == 200, preview.json
    applied = client.post('/api/journeys/apply', json={'previewToken': preview.json['previewToken'], 'idempotencyKey': 'expo-trip-synthetic-edit'}, headers=headers)
    assert applied.status_code == 200, applied.json
    detail = client.get(path).json
    same = next(t for t in detail['tasks'] if t['id'] == task['id'])
    assert same['title'] == '成员单独改过的准备' and same['done'] is True
    assert detail['trip']['title'] == '新的旅行标题'
    assert len(client.get('/api/state').json['trips']) == 1


def test_ts_preview_rejects_intervening_preparation_completion(app):
    client, headers = member(app)
    saved, _ = create(client, headers)
    detail = client.get('/api/journeys/' + saved['id']).json
    proposed = client.post('/api/journeys/preview', json=payload(client, journey=detail, title='旧预览标题'), headers=headers).json
    task = detail['tasks'][0]
    assert client.patch('/api/items/tasks/' + task['id'], json={'revision': task['revision'], 'done': True}, headers=headers).status_code == 200
    rejected = client.post('/api/journeys/apply', json={'previewToken': proposed['previewToken'], 'idempotencyKey': 'expo-trip-synthetic-conflict'}, headers=headers)
    assert rejected.status_code == 409
    latest = client.get('/api/journeys/' + saved['id']).json
    assert latest['trip']['title'] != '旧预览标题'
    assert next(t for t in latest['tasks'] if t['id'] == task['id'])['done'] is True


def test_ts_preview_is_bound_to_requesting_member_and_tv_cannot_apply(app):
    client, headers = member(app)
    partner, partner_headers = member(app, 2)
    proposed = client.post('/api/journeys/preview', json=payload(client), headers=headers).json
    operation = {'previewToken': proposed['previewToken'], 'idempotencyKey': 'expo-trip-synthetic-bound'}
    assert partner.post('/api/journeys/apply', json=operation, headers=partner_headers).status_code == 403
    tv = app.test_client()
    pairing = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pairing['code'], 'name': '合成电视', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pairing['secret']}).json['approved'] is True
    assert tv.post('/api/journeys/apply', json=operation, headers=headers).status_code == 403
    assert not client.get('/api/state').json['trips']
