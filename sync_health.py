"""Read-only source freshness and consent-bound publication diagnostics.

No provider calls, token decryption, queue changes, schema initialization or
success timestamps invented from publication updated_at. The household summary
contains counts/timestamps only; private names and publication titles are scoped
to the current member before being selected.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import math
import sqlite3

from flask import g, jsonify


STALE_AFTER_SECONDS = 300
SOURCE_STATES = ('current', 'waiting', 'delayed', 'error', 'needs_authorization', 'unknown')
ACCOUNT_PRIORITY = ('needs_authorization', 'error', 'unknown', 'delayed', 'waiting', 'current')
REASONS = {
    'current': None, 'error': 'sync_failed', 'unknown': 'invalid_success_time',
    'delayed': 'stale_success', 'waiting': 'awaiting_first_success',
    'not_selected': 'none_selected',
}


def _clock(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now):
        return datetime.fromtimestamp(now, timezone.utc)
    if isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None:
        return now.astimezone(timezone.utc)
    raise ValueError('now must be a timezone-aware datetime or finite epoch seconds')


def _iso(value):
    return value.isoformat() if value is not None else None


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _next_attempt(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return _iso(datetime.fromtimestamp(value, timezone.utc)) if math.isfinite(value) and value > 0 else None
    except (OverflowError, ValueError, OSError):
        return None


@contextmanager
def _snapshot(con):
    """Join an existing caller transaction, otherwise own one deferred read."""
    own = not con.in_transaction
    if own:
        con.execute('BEGIN')
    try:
        yield
    finally:
        if own:
            # End the read snapshot without ever committing caller state.
            con.rollback()


def _rows(con, sql, parameters=()):
    cursor = con.execute(sql, parameters)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor]


def _source_snapshot(con, client_ids, now):
    accounts = _rows(con, 'SELECT id,provider,client_id,needs_reauth FROM cloud_accounts ORDER BY id')
    sources = _rows(con, '''SELECT id,account_id,last_success,next_attempt,
        CASE WHEN error IS NOT NULL AND length(error)>0 THEN 1 ELSE 0 END AS has_error,
        failures FROM cloud_sources ORDER BY id''')
    account_info = {}
    for row in accounts:
        configured = client_ids.get(row['provider'])
        reason = ('reauth_required' if row['needs_reauth'] else
                  'client_configuration_changed' if not configured or configured != row['client_id'] else None)
        account_info[row['id']] = {'reasonCode': reason, 'sources': []}
    for row in sources:
        account = account_info.get(row['account_id'])
        reason = account['reasonCode'] if account else 'client_configuration_changed'
        success = _timestamp(row['last_success'])
        valid = success is not None and success <= now
        age = (now - success).total_seconds() if valid else None
        if reason:
            state = 'needs_authorization'
        elif row['has_error'] or (isinstance(row['failures'], (int, float)) and row['failures'] > 0):
            state = 'error'
        elif row['last_success'] is None or row['last_success'] == '':
            state = 'waiting'
        elif not valid:
            state = 'unknown'
        elif age > STALE_AFTER_SECONDS:
            state = 'delayed'
        else:
            state = 'current'
        row['health'] = {
            'state': state, 'reasonCode': reason if state == 'needs_authorization' else REASONS[state],
            'lastSuccess': _iso(success) if valid else None,
            'ageSeconds': math.floor(age) if age is not None else None,
            'nextAttemptAt': _next_attempt(row['next_attempt']),
        }
        row['success'] = success if valid else None
        if account is not None:
            account['sources'].append(row)
    return account_info, sources


def _household(account_info, sources):
    counts = {state: 0 for state in SOURCE_STATES}
    for row in sources:
        counts[row['health']['state']] += 1
    reauth = sum(bool(row['reasonCode']) for row in account_info.values())
    successes = [row['success'] for row in sources if row['success'] is not None]
    if not account_info and not sources:
        state = 'not_connected'
    elif reauth or any(counts[key] for key in ('delayed', 'error', 'needs_authorization', 'unknown')):
        state = 'needs_attention'
    elif not sources:
        state = 'not_selected'
    elif counts['waiting']:
        state = 'waiting'
    else:
        state = 'current'
    return {
        'state': state, 'connectedAccounts': len(account_info), 'selectedSources': len(sources),
        'sourceCounts': counts, 'reauthAccounts': reauth,
        'latestSuccess': _iso(max(successes)) if successes else None,
        'oldestSuccess': _iso(min(successes)) if successes else None,
        'lastCompleteSuccess': _iso(min(successes)) if sources and counts['current'] == len(sources) else None,
    }


def household_health(con, client_ids, now=None):
    """Return a shareable household summary using only the supplied DB/config.

    client_ids is {provider: configured_client_id}; now may be an aware datetime
    or epoch seconds. Tokens, account names/emails/subjects and provider errors
    are never selected. An outer transaction remains owned by its caller.
    """
    checked = _clock(now)
    with _snapshot(con):
        return _household(*_source_snapshot(con, client_ids, checked))


def _accounts(con, owner, account_info, sources):
    selected = {row['id']: row['health'] for row in sources}
    result = []
    for row in _rows(con, 'SELECT id,provider,name FROM cloud_accounts WHERE owner=? ORDER BY provider,name,id', (owner,)):
        info = account_info[row['id']]
        states = {source['health']['state'] for source in info['sources']}
        state = ('needs_authorization' if info['reasonCode'] else
                 next((key for key in ACCOUNT_PRIORITY if key in states), 'not_selected'))
        own_sources = _rows(con, '''SELECT id,name,kind,is_primary FROM cloud_sources
            WHERE account_id=? ORDER BY kind,name,id''', (row['id'],))
        result.append({
            'id': row['id'], 'provider': row['provider'], 'label': row['name'], 'state': state,
            'reasonCode': info['reasonCode'] if state == 'needs_authorization' else REASONS[state],
            'selectedSources': len(own_sources),
            'sources': [{'id': source['id'], 'name': source['name'], 'kind': source['kind'],
                         'primary': bool(source['is_primary']), **selected[source['id']]} for source in own_sources],
        })
    return result


def _publications(con, owner, kind):
    # These SQL fragments are module constants chosen by the caller, never
    # request parameters. Filter ownership before selecting any entity title.
    calendar = kind == 'calendar'
    table = 'calendar_publications' if calendar else 'task_publications'
    allowed = 'p.owner=?' if calendar else '(p.owner=? OR p.account_owner=?)'
    parameters = (owner,) if calendar else (owner, owner)
    flag = 'p.review_required' if calendar else '0'
    counts = {row['status']: row['count'] for row in _rows(con,
        f'SELECT p.status,count(*) AS count FROM {table} p WHERE {allowed} GROUP BY p.status', parameters)}
    rows = _rows(con, f'''SELECT p.id,p.journey_id,p.entity_id,p.status,
        {flag} AS review_required,p.updated_at,p.next_attempt,
        CASE WHEN json_valid(e.data) THEN json_extract(e.data,'$.title') ELSE NULL END AS title,
        e.id AS existing_entity,j.id AS existing_journey
        FROM {table} p
        LEFT JOIN entities e ON e.id=p.entity_id AND e.kind= ?
        LEFT JOIN journey_workflows j ON j.id=p.journey_id
        WHERE {allowed} AND p.status!='published'
        ORDER BY CASE
          WHEN {flag}=1 OR p.status IN ('needs_review','conflict') THEN 0
          WHEN p.status IN ('needs_authorization','permission_denied','disconnected') THEN 1
          WHEN p.status IN ('error','retry','uncertain','remote_deleted') THEN 2
          WHEN p.status IN ('pending','publishing') THEN 3
          WHEN p.status='paused' THEN 4 ELSE 5 END,
          p.updated_at DESC,p.id LIMIT 101''', (('events' if calendar else 'tasks'), *parameters))
    items = []
    for row in rows[:100]:
        action = None
        if row['existing_entity'] and (not calendar or row['existing_journey']):
            action = {'kind': kind, 'target': row['journey_id'] if calendar else row['entity_id']}
        title = row['title'] if isinstance(row['title'], str) and row['title'].strip() else (
            '本地日程已移除或标题不可用' if calendar else '本地待办已移除或标题不可用')
        items.append({
            'id': row['id'], 'journeyId': row['journey_id'], 'entityId': row['entity_id'],
            'title': title[:2048], 'status': row['status'], 'reviewRequired': bool(row['review_required']),
            'updatedAt': _iso(_timestamp(row['updated_at'])),
            'nextAttemptAt': _next_attempt(row['next_attempt']), 'action': action,
        })
    return {'counts': counts, 'items': items, 'truncated': len(rows) > 100}


def register_sync_health(app, db, require_member):
    @app.get('/api/sync-health')
    def sync_health():
        require_member()
        checked = _clock()
        client_ids = {provider: app.config.get(provider.upper() + '_CLIENT_ID', '')
                      for provider in ('google', 'microsoft')}
        try:
            con = db()
            with _snapshot(con):
                account_info, sources = _source_snapshot(con, client_ids, checked)
                result = {
                    'version': 1, 'checkedAt': _iso(checked), 'staleAfterSeconds': STALE_AFTER_SECONDS,
                    'household': _household(account_info, sources),
                    'accounts': _accounts(con, g.actor['id'], account_info, sources),
                    'publications': {kind: _publications(con, g.actor['id'], kind) for kind in ('calendar', 'tasks')},
                }
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            # Even TESTING mode must not echo SQL, upstream errors or partially
            # collected private state. No log receives the exception text.
            return jsonify(error='同步状态暂时无法读取，请稍后刷新', reasonCode='sync_health_unavailable'), 503
        return jsonify(result)
