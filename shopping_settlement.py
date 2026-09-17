"""Owner-confirmed payment snapshots projected onto shared shopping fields.

This is a private evidence link, not a payment integration or another ledger.
Only actual/done are projected; later source or shopping changes need review.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from finance_hub import reconciliation_rows


PREFIX = '/api/finance-hub/shopping-settlements'
PAGE_SIZE = 40
PREVIEW_SECONDS = 600
MAX_AMOUNT = 100_000_000_000
MAX_LINKS = 20_000
MAX_RECEIPTS = 40_000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def stored_link(row):
    """Business-only serialization shared with the explicitly requested export."""
    return {'id': row['id'], 'revision': row['revision'], 'shoppingId': row['shopping_id'],
            'paymentId': row['payment_id'], 'amountCents': row['amount_cents'], 'status': row['status'],
            'appliedShoppingRevision': row['applied_shopping_revision'],
            'createdAt': row['created_at'], 'updatedAt': row['updated_at']}


def export_owned_settlements(con, owner):
    """No raw preview, nonce/context/digest, provider identifier, or other owner."""
    links = [stored_link(dict(row)) for row in con.execute(
        'SELECT id,revision,shopping_id,payment_id,amount_cents,status,applied_shopping_revision,created_at,updated_at '
        'FROM hub_shopping_settlements WHERE owner=? ORDER BY id', (owner,))]
    receipts = []
    for row in con.execute('SELECT id,operation,link_id,result,created_at FROM hub_shopping_settlement_receipts '
                           'WHERE owner=? ORDER BY id', (owner,)):
        item = dict(row)
        result = json.loads(item['result'])
        receipts.append({'id': item['id'], 'operation': item['operation'], 'linkId': item['link_id'],
                         'createdAt': item['created_at'],
                         'changedFields': [key for key in result.get('changedFields', []) if key in {'actual', 'done'}]})
    return {'links': links, 'receipts': receipts}


def register_shopping_settlement(app, db, Problem, body, require_member, audit):
    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS hub_shopping_settlements(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
            payment_id TEXT NOT NULL, shopping_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 0 AND 100000000000),
            status TEXT NOT NULL CHECK(status IN ('active','revoked')),
            revision INTEGER NOT NULL DEFAULT 1,
            before_values TEXT NOT NULL, projected_values TEXT NOT NULL,
            applied_shopping_revision INTEGER NOT NULL,
            source_snapshot TEXT NOT NULL, source_digest TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS hub_shopping_settlements_active
            ON hub_shopping_settlements(owner,shopping_id) WHERE status='active';
        CREATE INDEX IF NOT EXISTS hub_shopping_settlements_payment
            ON hub_shopping_settlements(owner,payment_id,status);
        CREATE TABLE IF NOT EXISTS hub_shopping_settlement_receipts(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), nonce_digest TEXT NOT NULL,
            operation TEXT NOT NULL, link_id TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(owner,nonce_digest));
        ''')
        db().commit()

    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='shopping-settlement-preview-v1')

    def authenticated(con, expected=None):
        require_member()
        sessions = app.extensions.get('member_sessions')
        if sessions is None:
            raise Problem('暂时无法核对登录状态，请稍后重试', 503)
        current = sessions.current(con)
        captured = getattr(g, 'member_session', None) or {}
        household = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')
        if (current['id'] != captured.get('id') or current['owner'] != captured.get('owner')
                or current['credential_hash'] != captured.get('credential_hash')
                or current['auth_version'] != captured.get('auth_version')
                or current['owner'] != g.actor['id'] or current['auth_version'] != g.actor.get('auth_version')
                or household != g.actor.get('householdId')):
            raise Problem('登录或家庭已变化，请重新打开', 401)
        identity = current['owner'], digest({'household': household, 'owner': current['owner'],
                                            'session': current['id'], 'credential': current['credential_hash'],
                                            'authVersion': current['auth_version']})
        if expected is not None and identity != expected:
            raise Problem('登录或家庭已变化，请重新打开', 401)
        return identity

    @contextmanager
    def read_snapshot():
        con = db()
        # The global guard already committed registration/bootstrap. Resolving
        # a legacy cookie may UPDATE expiry; release that write before reading.
        con.rollback()
        try:
            identity = authenticated(con)
            con.rollback()
            con.execute('BEGIN')
            yield con, identity
            con.rollback()
            authenticated(con, identity)
        finally:
            con.rollback()

    def identifier(value, label):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
            raise Problem(label + '格式不正确')
        return value

    def integer(value, label, maximum=MAX_AMOUNT, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum:
            raise Problem(label + '须为有效整数')
        return value

    def owned(con, uid, rid):
        row = con.execute('SELECT * FROM hub_shopping_settlements WHERE id=? AND owner=?', (rid, uid)).fetchone()
        if not row:
            raise Problem('关联不存在', 404)
        return dict(row)

    def load(con, uid):
        raw = {r['id']: dict(r) for r in con.execute(
            'SELECT id,data,revision FROM hub_transactions WHERE owner=? ORDER BY id', (uid,))}
        records = [{**json.loads(r['data']), 'id': r['id'], 'revision': r['revision']} for r in raw.values()]
        relations = [dict(r) for r in con.execute(
            'SELECT * FROM hub_reconciliations WHERE owner=? ORDER BY id', (uid,))]
        links = [dict(r) for r in con.execute(
            'SELECT * FROM hub_shopping_settlements WHERE owner=? ORDER BY id', (uid,))]
        shopping = {r['id']: {'row': dict(r), 'value': {**json.loads(r['data']), 'id': r['id'], 'revision': r['revision']}}
                    for r in con.execute("SELECT * FROM entities WHERE kind='shopping' ORDER BY id")}
        source_relations, reservations = {}, {}
        for relation in relations:
            if relation['status'] == 'active':
                for rid in {relation['left_id'], relation['right_id']}:
                    source_relations.setdefault(rid, []).append(relation)
        for link in links:
            if link['status'] == 'active':
                pid = link['payment_id']
                reservations[pid] = reservations.get(pid, 0) + link['amount_cents']
        return {'raw': raw, 'transactions': {r['id']: r for r in reconciliation_rows(records, relations)},
                'relations': relations, 'links': links, 'shopping': shopping,
                'source_relations': source_relations, 'reservations': reservations,
                'links_by_id': {row['id']: row for row in links}, 'source_cache': {}}

    def source_digest(state, pid):
        # These caches belong only to this freshly loaded transaction snapshot.
        if pid in state['source_cache']:
            return state['source_cache'][pid]
        relevant = state['source_relations'].get(pid, [])
        neighbors = {pid}
        for relation in relevant:
            neighbors.update((relation['left_id'], relation['right_id']))
        value = digest({'records': [state['raw'].get(key) for key in sorted(neighbors)], 'relations': relevant})
        state['source_cache'][pid] = value
        return value

    def payment(state, pid, excluding=None):
        row = state['transactions'].get(pid)
        if not row:
            return None
        reason = ('not_payment' if row['kind'] != 'payments' else
                  'not_expense' if row['flow'] != 'expense' else
                  'duplicate' if row['reconciliation']['duplicateOf'] else
                  'unsupported_currency' if row['currency'] != 'CNY' else None)
        refunded = row['reconciliation']['refundedCents']
        net = row['amountCents'] - refunded
        reserved = state['reservations'].get(pid, 0)
        ignored = state['links_by_id'].get(excluding)
        if ignored and ignored['status'] == 'active' and ignored['payment_id'] == pid:
            reserved -= ignored['amount_cents']
        return {'id': pid, 'revision': row['revision'], 'title': row['title'], 'date': row['date'],
                'currency': row['currency'], 'amountCents': row['amountCents'], 'refundedCents': refunded,
                'netCents': net, 'reservedCents': reserved, 'availableCents': max(0, net - reserved),
                'eligible': reason is None, 'reasonCode': reason}

    def shopping_value(state, sid):
        row = state['shopping'].get(sid)
        if row is None:
            return None
        value = row['value']
        return {key: value.get(key) for key in ('id', 'revision', 'title', 'actual', 'done')}

    def public_link(state, row):
        result = stored_link(row)
        reasons = []
        if row['status'] == 'active':
            pay = payment(state, row['payment_id'])
            item = shopping_value(state, row['shopping_id'])
            if pay is None:
                reasons.append('source_missing')
            else:
                if source_digest(state, row['payment_id']) != row['source_digest']:
                    reasons.append('source_changed')
                if not pay['eligible']:
                    reasons.append('source_ineligible')
            if item is None:
                reasons.append('shopping_missing')
            elif (item['revision'] != row['applied_shopping_revision']
                  or {key: item[key] for key in ('actual', 'done')} != json.loads(row['projected_values'])):
                reasons.append('shopping_changed')
        result.update(state='revoked' if row['status'] == 'revoked' else 'needs_review' if reasons else 'current',
                      reviewReasons=reasons)
        return result

    def normalized(payload):
        operation = payload.get('operation')
        fields = {'apply': {'operation', 'paymentId', 'shoppingId', 'shoppingRevision', 'amountCents', 'done'},
                  'update': {'operation', 'linkId', 'revision', 'shoppingRevision', 'amountCents', 'done'},
                  'revoke': {'operation', 'linkId', 'revision', 'shoppingRevision', 'mode'}}
        if not isinstance(operation, str) or operation not in fields or set(payload) != fields[operation]:
            raise Problem('操作字段不正确，请重新填写')
        result = dict(payload)
        if operation == 'apply':
            identifier(result['paymentId'], '付款编号')
            identifier(result['shoppingId'], '采购编号')
        else:
            identifier(result['linkId'], '关联编号')
            integer(result['revision'], '关联版本', minimum=1)
        if operation == 'revoke':
            if result['mode'] not in ('detach_keep_current', 'restore_if_unchanged'):
                raise Problem('解除方式不正确')
            if result['shoppingRevision'] is not None:
                integer(result['shoppingRevision'], '采购版本', minimum=1)
        else:
            integer(result['shoppingRevision'], '采购版本', minimum=1)
            integer(result['amountCents'], '实付金额')
            if type(result['done']) is not bool:
                raise Problem('请明确选择是否已买到')
        return result

    def assess(con, uid, plan):
        state = load(con, uid)
        operation = plan['operation']
        link = None if operation == 'apply' else owned(con, uid, plan['linkId'])
        if link:
            if link['status'] != 'active' or link['revision'] != plan['revision']:
                raise Problem('关联已改变，请重新读取并预览', 409)
            pid, sid = link['payment_id'], link['shopping_id']
        else:
            pid, sid = plan['paymentId'], plan['shoppingId']
            if any(r['shopping_id'] == sid and r['status'] == 'active' for r in state['links']):
                raise Problem('你已为这件采购建立关联，请更新或解除原关联', 409)
        item = shopping_value(state, sid)
        if (item['revision'] if item else None) != plan['shoppingRevision']:
            raise Problem('采购已改变，请重新读取并预览', 409)
        before = None if item is None else {'shoppingId': sid, 'revision': item['revision'], 'actual': item['actual'], 'done': item['done']}
        after = None if before is None else {k: before[k] for k in ('shoppingId', 'actual', 'done')}
        pay = payment(state, pid, link['id'] if link else None)
        warnings = ['仅将明确确认的整项实付与已买到状态写入家庭采购；账本、预算和公共余额不变。']
        if operation in {'apply', 'update'}:
            if item is None or pay is None:
                raise Problem('付款或采购不存在', 404)
            if not pay['eligible']:
                raise Problem('请选择本人有效的人民币实际消费付款；订单、转账与重复记录不能直接投影')
            if plan['amountCents'] + pay['reservedCents'] > pay['netCents']:
                raise Problem('分配合计超过该付款扣除已确认退款后的金额，请调整或先解除其他关联')
            after = {'shoppingId': sid, 'actual': plan['amountCents'], 'done': plan['done']}
            warnings.append('实付是这件采购的整项替换值，不与原实付相加；付款不代表已经买到。')
            if pay['refundedCents']:
                warnings.append('可分配上限已扣除明确关联的退款；未核对的退款不自动推算。')
        elif plan['mode'] == 'restore_if_unchanged':
            if (item is None or item['revision'] != link['applied_shopping_revision']
                    or {k: item[k] for k in ('actual', 'done')} != json.loads(link['projected_values'])):
                raise Problem('采购后来已修改，不能恢复前值；可明确选择仅解除并保留当前采购', 409)
            after = {'shoppingId': sid, **json.loads(link['before_values'])}
            warnings.append('本次解除会把实付与已买到恢复为关联前的值。')
        else:
            warnings.append('仅解除本人关联；保留采购现在的金额和状态，不删除或重建采购。')
        allocations = [{k: r[k] for k in ('id', 'revision', 'status', 'amount_cents')}
                       for r in state['links'] if r['payment_id'] == pid and r['status'] == 'active']
        dependencies = {'source': source_digest(state, pid), 'allocations': digest(allocations),
                        'shopping': digest(state['shopping'].get(sid)), 'link': digest(link)}
        output = {'operation': operation, 'linkId': link['id'] if link else None, 'before': before, 'after': after,
                  'payment': None if pay is None else {'id': pid, 'currency': pay['currency'], 'netCents': pay['netCents'],
                            'reservedOtherCents': pay['reservedCents'], 'availableCents': pay['availableCents']},
                  'sharing': {'fields': ['actual', 'done'], 'ledgerUnchanged': True}, 'warnings': warnings}
        return state, link, pid, sid, dependencies, output

    @app.get(PREFIX + '/context')
    def settlement_context():
        if set(request.args) - {'transactionId', 'shoppingId', 'linkId', 'q', 'page'}:
            raise Problem('查询字段不正确')
        query = request.args.get('q', '')
        if (len(query) > 80 or any(ord(c) < 32 for c in query)
                or not re.fullmatch(r'(?:0|[1-9][0-9]{0,8})', request.args.get('page', '0'))):
            raise Problem('搜索或页码格式不正确')
        page = int(request.args.get('page', '0'))
        ids = {key: identifier(request.args[key], '编号') for key in ('transactionId', 'shoppingId', 'linkId') if key in request.args}
        with read_snapshot() as (con, (uid, _)):
            state = load(con, uid)
            target = state['transactions'].get(ids.get('transactionId'))
            if 'transactionId' in ids and target is None:
                raise Problem('记录不存在', 404)
            focus_link = owned(con, uid, ids['linkId']) if 'linkId' in ids else None
            if 'shoppingId' in ids and ids['shoppingId'] not in state['shopping']:
                raise Problem('采购不存在', 404)
            allowed_payments = None
            if target and target['kind'] == 'orders':
                allowed_payments = {r['right_id'] for r in state['relations']
                                    if r['status'] == 'active' and r['kind'] == 'order_payment' and r['left_id'] == target['id']}
            pay_focus = {target['id']} if target and target['kind'] != 'orders' else set()
            shopping_focus = {ids['shoppingId']} if 'shoppingId' in ids else set()
            link_focus = {focus_link['id']} if focus_link else set()
            if focus_link:
                pay_focus.add(focus_link['payment_id'])
                shopping_focus.add(focus_link['shopping_id'])
            # Only the current owner/target link is pinned; a payment can have
            # thousands of historical links and must not defeat pagination.
            link_focus.update(r['id'] for r in state['links']
                              if r['status'] == 'active' and r['shopping_id'] in shopping_focus)
            payments = [payment(state, key) for key, value in state['transactions'].items()
                        if (value['kind'] == 'payments' or key in pay_focus)
                        and (allowed_payments is None or key in allowed_payments)]
            shopping = [shopping_value(state, sid) for sid in state['shopping']]
            links = [public_link(state, r) for r in state['links']]
            term = query.casefold().strip()

            def paged(rows, focus, search):
                chosen = [r for r in rows if r['id'] not in focus and (not term or term in search(r).casefold())]
                chosen.sort(key=lambda r: r['id'])
                selected = chosen[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
                selected.extend(r for r in rows if r['id'] in focus)
                return selected, len(chosen) > (page + 1) * PAGE_SIZE

            payments, more_pay = paged(payments, pay_focus, lambda r: r['title'])
            shopping, more_shop = paged(shopping, shopping_focus, lambda r: r['title'])
            links, more_links = paged(links, link_focus, lambda r: (
                (state['transactions'].get(r['paymentId']) or {}).get('title', '') + ' ' +
                (shopping_value(state, r['shoppingId']) or {}).get('title', '')))
            warnings = ['这里只展示本人的账单与关联；采购内容及确认后的实付、已买到状态由家庭共享。']
            if allowed_payments is not None:
                warnings.append('订单金额不能作为实付；请先核对订单与实际付款，再选择付款。')
            result = {'version': 1, 'transaction': None if target is None else {k: target[k] for k in ('id', 'revision', 'kind', 'flow', 'currency')},
                      'payments': payments, 'shopping': shopping, 'links': links, 'warnings': warnings,
                      'pageInfo': {'page': page, 'pageSize': PAGE_SIZE, 'paymentsMore': more_pay,
                                   'shoppingMore': more_shop, 'linksMore': more_links}}
            return jsonify(result)

    @app.post(PREFIX + '/preview')
    def settlement_preview():
        plan = normalized(body())
        with read_snapshot() as (con, (uid, context)):
            *_, dependencies, output = assess(con, uid, plan)
            token = signer.dumps({'version': 1, 'owner': uid, 'context': context, 'plan': plan,
                                  'dependencies': dependencies, 'nonce': secrets.token_hex(24)})
            return jsonify(**output, previewToken=token, expiresInSeconds=PREVIEW_SECONDS)

    @app.post(PREFIX + '/confirm')
    def settlement_confirm():
        payload = body()
        token = payload.get('previewToken')
        if set(payload) != {'previewToken'} or not isinstance(token, str) or not 20 <= len(token) <= 12_000:
            raise Problem('请先预览并确认共享字段')
        try:
            signed = signer.loads(token, max_age=PREVIEW_SECONDS)
        except (BadSignature, SignatureExpired):
            raise Problem('预览已失效，请重新预览') from None
        if not isinstance(signed, dict) or set(signed) != {'version', 'owner', 'context', 'plan', 'dependencies', 'nonce'} or signed['version'] != 1:
            raise Problem('预览格式不正确')
        if not isinstance(signed['nonce'], str) or not re.fullmatch(r'[a-f0-9]{48}', signed['nonce']):
            raise Problem('预览格式不正确')
        if not isinstance(signed['plan'], dict):
            raise Problem('预览格式不正确')
        plan = normalized(signed['plan'])
        con = db()
        con.rollback()
        try:
            con.execute('BEGIN IMMEDIATE')
            identity = authenticated(con)
            uid, context = identity
            if signed['owner'] != uid or not secrets.compare_digest(str(signed['context']), context):
                raise Problem('登录或家庭已变化，请重新预览', 403)
            nonce = digest(signed['nonce'])
            old = con.execute('SELECT result FROM hub_shopping_settlement_receipts WHERE owner=? AND nonce_digest=?', (uid, nonce)).fetchone()
            if old:
                result = json.loads(old['result'])
                response = jsonify(**{**result, 'replayed': True})
                con.rollback()
                authenticated(con, identity)
                con.rollback()
                return response
            try:
                state, link, pid, sid, dependencies, output = assess(con, uid, plan)
            except Problem as exc:
                if exc.status in {400, 404}:
                    raise Problem('来源、分配或采购已变化，请重新读取并预览', 409) from None
                raise
            if dependencies != signed['dependencies']:
                raise Problem('来源、分配或采购已变化，请重新读取并预览', 409)
            if con.execute('SELECT count(*) FROM hub_shopping_settlement_receipts WHERE owner=?', (uid,)).fetchone()[0] >= MAX_RECEIPTS:
                raise Problem('确认记录已达上限，请联系维护者整理', 409)
            operation = plan['operation']
            if operation == 'apply' and con.execute('SELECT count(*) FROM hub_shopping_settlements WHERE owner=?', (uid,)).fetchone()[0] >= MAX_LINKS:
                raise Problem('采购关联已达上限，请联系维护者整理', 409)
            after, before = output['after'], output['before']
            changed = [] if after is None else [k for k in ('actual', 'done') if before[k] != after[k]]
            shopping_revision = None if before is None else before['revision']
            if changed:
                # Preserve every field outside the explicit sharing whitelist, including journey metadata/photos.
                value = dict(state['shopping'][sid]['value'])
                value.pop('id', None)
                value.pop('revision', None)
                value.update({key: after[key] for key in ('actual', 'done')})
                updated = con.execute("UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=? AND kind='shopping' AND revision=?",
                                      (canonical(value), stamp(), sid, shopping_revision))
                if updated.rowcount != 1:
                    raise Problem('采购已改变，请重新预览', 409)
                shopping_revision += 1
            moment = stamp()
            if operation == 'apply':
                rid = secrets.token_hex(16)
                source = payment(state, pid)
                source_snapshot = {k: source[k] for k in ('currency', 'date', 'amountCents', 'refundedCents', 'netCents')}
                con.execute('INSERT INTO hub_shopping_settlements '
                            '(id,owner,payment_id,shopping_id,amount_cents,status,before_values,projected_values,applied_shopping_revision,source_snapshot,source_digest,created_at,updated_at) '
                            "VALUES(?,?,?,?,?,'active',?,?,?,?,?,?,?)",
                            (rid, uid, pid, sid, plan['amountCents'], canonical({k: before[k] for k in ('actual', 'done')}),
                             canonical({k: after[k] for k in ('actual', 'done')}), shopping_revision,
                             canonical(source_snapshot), source_digest(state, pid), moment, moment))
            elif operation == 'update':
                rid = link['id']
                source = payment(state, pid)
                source_snapshot = {k: source[k] for k in ('currency', 'date', 'amountCents', 'refundedCents', 'netCents')}
                con.execute('UPDATE hub_shopping_settlements SET amount_cents=?,revision=revision+1,before_values=?,projected_values=?,applied_shopping_revision=?,source_snapshot=?,source_digest=?,updated_at=? '
                            "WHERE id=? AND owner=? AND revision=? AND status='active'",
                            (plan['amountCents'], canonical({k: before[k] for k in ('actual', 'done')}),
                             canonical({k: after[k] for k in ('actual', 'done')}), shopping_revision,
                             canonical(source_snapshot), source_digest(state, pid), moment, rid, uid, link['revision']))
            else:
                rid = link['id']
                con.execute("UPDATE hub_shopping_settlements SET status='revoked',revision=revision+1,updated_at=? WHERE id=? AND owner=? AND revision=? AND status='active'",
                            (moment, rid, uid, link['revision']))
            fresh = load(con, uid)
            result = {'operation': operation, 'link': public_link(fresh, owned(con, uid, rid)),
                      'shopping': None if shopping_revision is None else {'id': sid, 'revision': shopping_revision,
                                   'actual': after['actual'], 'done': after['done']},
                      'changedFields': changed, 'replayed': False}
            con.execute('INSERT INTO hub_shopping_settlement_receipts VALUES(?,?,?,?,?,?,?)',
                        (secrets.token_hex(16), uid, nonce, operation, rid, canonical(result), moment))
            audit('finance.shopping.' + operation, rid)
            authenticated(con, identity)
            con.commit()
            return jsonify(result)
        except BaseException:
            con.rollback()
            raise

    app.extensions['shopping_settlement'] = {'export_for_owner': export_owned_settlements}
