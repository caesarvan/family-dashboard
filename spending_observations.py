"""Owner-only dated report snapshots. Never mutate the financial baseline or ledger."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import re

from flask import g, jsonify
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from finance_baseline import BaselineError, _amount, _date

MODE = 'spending_observation'
VERSION = 'spending-observation-v1'
REPORT_PATHS = frozenset({'08_Budgets/all-email-spend-report-12m.json',
                         '08_Budgets/all-email-spend-transactions-12m.json',
                         '08_Budgets/statement-attachment-inventory-12m.json'})
QUALITY = ('knownGapsCount', 'unreadableStatementsCount', 'channelOnlyAdded', 'orderOnlyAdded')
MONTH_KEYS = ('period', 'currency', 'grossSpendCents', 'refundCents', 'netSpendCents', 'transactionCount')
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS finance_spending_observations(
    owner TEXT PRIMARY KEY REFERENCES users(id), revision INTEGER NOT NULL,
    source_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL,
    candidate_json TEXT NOT NULL, accepted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finance_spending_receipts(
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
    candidate_digest TEXT NOT NULL, source_digest TEXT NOT NULL,
    expected_revision INTEGER NOT NULL, expected_baseline_revision INTEGER NOT NULL,
    observation_revision INTEGER NOT NULL, status TEXT NOT NULL,
    accepted_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS finance_spending_receipts_owner
    ON finance_spending_receipts(owner,accepted_at);
'''


class SpendingError(BaselineError):
    def __init__(self, message='消费观察候选格式不正确', status=400):
        super().__init__(message)
        self.status = status


def fail(message='消费观察候选格式不正确', status=400):
    raise SpendingError(message, status)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        fail()


def hash_value(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        fail('来源摘要格式不正确')


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        fail('报告生成时间必须包含时区')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            fail('报告生成时间必须包含时区')
        return parsed
    except ValueError:
        fail('报告生成时间必须包含时区')


def validate_spending(value):
    exact(value, ('generatedAt', 'requestedStart', 'requestedEnd', 'monthly', 'quality'))
    generated = timestamp(value['generatedAt'])
    start, end = _date(value['requestedStart']), _date(value['requestedEnd'])
    # The producer subtracts 365 days; the two inclusive endpoint labels are not 364 days apart.
    if (date.fromisoformat(end) - date.fromisoformat(start)).days != 365 or end != generated.date().isoformat():
        fail('消费观察须覆盖生产者完整的 365 天区间，结束日与报告生成日期一致')
    q = value['quality']
    exact(q, QUALITY)
    if any(type(q[k]) is not int or not 0 <= q[k] <= 1000000 for k in QUALITY[:2]) or any(type(q[k]) is not bool for k in QUALITY[2:]):
        fail('报告质量标记不正确')
    if not isinstance(value['monthly'], list) or not 1 <= len(value['monthly']) <= 240:
        fail('消费观察须包含 1 至 240 条月份与币种记录')
    seen = set()
    for row in value['monthly']:
        exact(row, MONTH_KEYS)
        if not isinstance(row['period'], str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', row['period']):
            fail('消费月份格式不正确')
        if not start[:7] <= row['period'] <= end[:7] or not isinstance(row['currency'], str) or not re.fullmatch('[A-Z]{3}', row['currency']):
            fail('消费月份或币种不正确')
        key = row['period'], row['currency']
        if key in seen:
            fail('月份与币种重复')
        seen.add(key)
        for field in MONTH_KEYS[2:5]:
            _amount(row[field], signed=field == 'netSpendCents')
        if row['grossSpendCents'] - row['refundCents'] != row['netSpendCents']:
            fail('消费减退款与净观察金额不一致')
        if type(row['transactionCount']) is not int or not 0 <= row['transactionCount'] <= 1000000:
            fail('观察记录数量不正确')


def normalize_spending_candidate(candidate):
    exact(candidate, ('schemaVersion', 'kind', 'converterVersion', 'sourceManifest', 'spending'))
    if type(candidate['schemaVersion']) is not int or candidate['schemaVersion'] != 1 or candidate['kind'] != MODE or candidate['converterVersion'] != VERSION:
        fail('消费观察候选版本不支持')
    if len(encode(candidate).encode()) >= 1950000:
        fail('消费观察候选须小于 1.95 MB')
    manifest = candidate['sourceManifest']
    exact(manifest, ('version', 'files', 'run', 'coverage'))
    if type(manifest['version']) is not int or manifest['version'] != 1 or not isinstance(manifest['files'], list) or len(manifest['files']) != 3:
        fail('需要成功运行的三个报告产物')
    paths = set()
    for item in manifest['files']:
        exact(item, ('path', 'sha256', 'bytes'))
        if not isinstance(item['path'], str) or item['path'] not in REPORT_PATHS or item['path'] in paths:
            fail('报告文件不在固定白名单或重复')
        paths.add(item['path']); hash_value(item['sha256'])
        if type(item['bytes']) is not int or not 0 < item['bytes'] <= 50000000:
            fail('报告文件大小不正确')
    if sum(x['bytes'] for x in manifest['files']) > 100000000:
        fail('报告文件总大小超过限制')
    run = manifest['run']
    exact(run, ('sha256', 'generatedAt', 'status', 'exitCode', 'loginActionRequired'))
    hash_value(run['sha256'])
    if run['status'] != 'success' or type(run['exitCode']) is not int or run['exitCode'] != 0 or run['loginActionRequired'] is not False:
        fail('报告生产任务未完成或需要重新登录')
    validate_spending(candidate['spending'])
    spending = candidate['spending']
    coverage = manifest['coverage']
    exact(coverage, ('requestedStart', 'requestedEnd', *QUALITY))
    if run['generatedAt'] != spending['generatedAt'] or coverage != {k: spending[k] for k in ('requestedStart', 'requestedEnd')} | spending['quality']:
        fail('运行记录、报告日期或覆盖不一致')
    frozen = deepcopy(candidate)
    frozen['sourceManifest']['files'].sort(key=lambda x: x['path'])
    frozen['spending']['monthly'].sort(key=lambda x: (x['period'], x['currency']))
    return frozen, digest(frozen), digest({'converterVersion': VERSION, 'manifest': frozen['sourceManifest']})


def table_exists(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='finance_spending_observations'").fetchone() is not None


def load_current(con, owner):
    if not table_exists(con):
        return None
    row = con.execute('SELECT revision,source_digest,candidate_digest,candidate_json,accepted_at FROM finance_spending_observations WHERE owner=?', (owner,)).fetchone()
    if row is None:
        return None
    return {'revision': row[0], 'sourceDigest': row[1], 'candidateDigest': row[2], 'candidate': json.loads(row[3]), 'acceptedAt': row[4]}


def known_spending(value):
    try:
        validate_spending(value)
        return True
    except (BaselineError, ValueError, TypeError, KeyError):
        return False


def selected_spending(private, current):
    baseline = (private or {}).get('spending')
    if current is None:
        return baseline, 'baseline', []
    observation = current['candidate']['spending']
    warnings = []
    if known_spending(baseline):
        if timestamp(baseline['generatedAt']) > timestamp(observation['generatedAt']) and baseline['requestedEnd'] >= observation['requestedEnd']:
            return baseline, 'baseline', ['完整基线含更新的消费观察，本页使用该版本；独立观察保留，不相加。']
        if timestamp(baseline['generatedAt']) == timestamp(observation['generatedAt']) and baseline != observation:
            warnings.append('完整基线与独立观察的同日内容不同，继续显示已确认的独立观察；请核对来源。')
    return observation, MODE, warnings


def decorate_private_spending(con, owner, private):
    result = deepcopy(private)
    current = load_current(con, owner)
    if current is None or result is None:
        return result
    spending, origin, warnings = selected_spending(private, current)
    result['spending'] = deepcopy(spending)
    result['spendingObservation'] = {k: current[k] for k in ('revision', 'sourceDigest', 'acceptedAt')}
    result['spendingObservation'].update(origin=origin, warnings=warnings, assetBaselineUnchanged=True)
    return result


def export_owned_spending_observations(con, owner):
    current = load_current(con, owner)
    # Re-normalize so a future nested field cannot silently widen the export contract.
    if current:
        candidate, _, _ = normalize_spending_candidate(current['candidate'])
        current = {k: current[k] for k in ('revision', 'sourceDigest', 'candidateDigest', 'acceptedAt')} | {'candidate': candidate}
    receipts = []
    if table_exists(con):
        for row in con.execute('SELECT id,candidate_digest,source_digest,observation_revision,status,accepted_at FROM finance_spending_receipts WHERE owner=? ORDER BY accepted_at,id', (owner,)):
            receipts.append(dict(zip(('receiptId','candidateDigest','sourceDigest','revision','status','acceptedAt'), row)))
    return {'current': current, 'receipts': receipts}


class SpendingObservations:
    def __init__(self, app, db, Problem, require_member, audit):
        self.app, self.db, self.Problem, self.require_member, self.audit = app, db, Problem, require_member, audit
        self.signer = URLSafeTimedSerializer(app.secret_key, salt='spending-observation-v1')
        with app.app_context():
            db().executescript(SCHEMA_SQL); db().commit()

    def identity(self, con):
        self.require_member()
        sessions = self.app.extensions.get('member_sessions')
        current = sessions.current(con) if sessions else None
        if (not current or current['owner'] != g.actor['id'] or current['auth_version'] != g.actor.get('auth_version')
                or g.actor.get('householdId') != self.app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')):
            fail('登录状态已改变，请重新登录后预览', 401)
        return digest({'owner': current['owner'], 'household': self.app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default'),
                       'session': current['id'], 'credential': current['credential_hash'], 'authVersion': current['auth_version']})

    def baseline(self, con, owner):
        row = con.execute('SELECT private_data,revision,source_digest FROM finance_baselines WHERE owner=?', (owner,)).fetchone()
        return (json.loads(row[0]), row[1], row[2]) if row else (None, 0, None)

    def version(self, con, owner):
        private, base_revision, base_digest = self.baseline(con, owner)
        current = load_current(con, owner)
        expected = {'expectedRevision': current['revision'] if current else 0,
                    'expectedSourceDigest': current['sourceDigest'] if current else None,
                    'expectedBaselineRevision': base_revision, 'expectedBaselineSourceDigest': base_digest}
        return private, current, expected

    def checked(self, fn):
        try:
            return fn()
        except SpendingError as exc:
            raise self.Problem(str(exc), exc.status) from None
        except (BaselineError, ValueError, TypeError, KeyError, RecursionError):
            raise self.Problem('消费观察候选格式不正确', 400) from None

    def status(self):
        def run():
            self.require_member(); con = self.db(); self.identity(con)
            private, current, expected = self.version(con, g.actor['id'])
            selected, origin, warnings = selected_spending(private, current)
            old_known = known_spending(selected)
            return jsonify(mode=MODE, expected=expected, current=({k: current[k] for k in ('revision','sourceDigest','acceptedAt')} if current else None),
                           baseline={'exists': private is not None, 'asOf': (private or {}).get('asOf'),
                                     'balanceAsOfStart': (private or {}).get('balanceAsOfStart'), 'balanceAsOfEnd': (private or {}).get('balanceAsOfEnd')},
                           previousCoverageKnown=old_known, requiresUnknownCoverageAcknowledgement=bool(selected) and not old_known,
                           spending=({k: selected[k] for k in ('generatedAt','requestedStart','requestedEnd')} if old_known else None), warnings=warnings)
        return self.checked(run)

    def assess(self, private, current, candidate, acknowledgement):
        if private is None:
            fail('尚无财产基线；请先核对并导入原基线，再独立更新消费观察', 409)
        previous, _, warnings = selected_spending(private, current)
        if previous and not known_spending(previous):
            if acknowledgement is not True:
                fail('旧消费观察缺少可比较的覆盖日期；请明确确认保留旧快照且不推断旧覆盖', 409)
            warnings.append('旧消费覆盖无法比较；原基线快照完整保留，没有补造旧日期。')
        fresh = candidate['spending']
        # Compare both stored lanes: an older full-baseline replacement cannot reopen a rollback path.
        for old in [previous, current['candidate']['spending'] if current else None]:
            if known_spending(old) and (timestamp(fresh['generatedAt']) < timestamp(old['generatedAt']) or fresh['requestedEnd'] < old['requestedEnd']):
                fail('消费观察生成日期或覆盖结束日期倒退，已保留旧观察', 409)
        old_rows = {(r['period'], r['currency']): r for r in previous['monthly']} if known_spending(previous) else {}
        new_rows = {(r['period'], r['currency']): r for r in fresh['monthly']}
        removed = sorted(set(old_rows)-set(new_rows))
        # The advancing lower boundary can remove the last source record from a
        # partially covered first month. No zero-valued row or transaction date is invented.
        partial_exits = {key for key in removed if known_spending(previous)
                         and fresh['requestedStart'] > previous['requestedStart']
                         and date.fromisoformat(fresh['requestedStart']).day > 1
                         and key[0] == fresh['requestedStart'][:7]}
        if any(fresh['requestedStart'][:7] <= period <= fresh['requestedEnd'][:7]
               and (period, currency) not in partial_exits for period, currency in removed):
            fail('新报告缺少仍在覆盖窗口内的旧月份或币种，已保留旧观察', 409)
        if partial_exits:
            warnings.append('首月覆盖起点已前移，下列分组可能随窗口滚出，须核对报告；没有补零或推算交易日期：'
                            + '、'.join(period + ' ' + currency for period,currency in sorted(partial_exits)))
        changes = {'added': sum(k not in old_rows for k in new_rows),
                   'updated': sum(k in old_rows and old_rows[k] != v for k,v in new_rows.items()),
                   'preserved': sum(k in old_rows and old_rows[k] == v for k,v in new_rows.items()),
                   'removedMonths': [{'period': p, 'currency': c} for p,c in removed]}
        warnings += ['仅更新本人消费观察，财产基线和共享汇总保持原样。',
                     '报告含渠道或订单补记，不能当作已核对实付；不写账本、采购、投资或公共荷包。',
                     '覆盖按报告日期滚动，首尾月份可能不完整；币种分别展示，不合并换汇。']
        return changes, warnings

    def preview(self, payload):
        def run():
            exact(payload, ('mode','candidate','expectedRevision','expectedSourceDigest','expectedBaselineRevision','expectedBaselineSourceDigest','acknowledgeUnknownPreviousCoverage'))
            if payload['mode'] != MODE or type(payload['acknowledgeUnknownPreviousCoverage']) is not bool:
                fail()
            con = self.db(); context = self.identity(con); owner = g.actor['id']
            private, current, expected = self.version(con, owner)
            if any(payload[k] != v or type(payload[k]) is not type(v) for k,v in expected.items()):
                fail('财产基线或消费观察已改变，请保留文件并重新预览', 409)
            candidate, candidate_digest, source_digest = normalize_spending_candidate(payload['candidate'])
            changes, warnings = self.assess(private, current, candidate, payload['acknowledgeUnknownPreviousCoverage'])
            signed = {'owner': owner, 'context': context, 'candidateDigest': candidate_digest, **expected,
                      'acknowledgeUnknownPreviousCoverage': payload['acknowledgeUnknownPreviousCoverage']}
            token = self.signer.dumps(signed)
            return jsonify(mode=MODE, previewToken=token, candidateDigest=candidate_digest, sourceDigest=source_digest,
                           expected=expected, spending=candidate['spending'], changes=changes, warnings=warnings,
                           baseline={'asOf':private['asOf'],'balanceAsOfStart':private['balanceAsOfStart'],'balanceAsOfEnd':private['balanceAsOfEnd']},
                           assetBaselineUnchanged=True, expiresIn=1200)
        return self.checked(run)

    def confirm(self, payload):
        def run():
            exact(payload, ('mode','candidate','previewToken'))
            if payload['mode'] != MODE or not isinstance(payload['previewToken'],str) or len(payload['previewToken'])>4000:
                fail()
            try:
                signed = self.signer.loads(payload['previewToken'], max_age=1200)
            except (BadSignature, SignatureExpired):
                fail('消费观察预览已失效，请重新预览', 409)
            candidate, candidate_digest, source_digest = normalize_spending_candidate(payload['candidate'])
            con = self.db(); owner = g.actor['id']; con.execute('BEGIN IMMEDIATE')
            try:
                context = self.identity(con)
                if signed.get('owner') != owner or signed.get('context') != context or signed.get('candidateDigest') != candidate_digest:
                    fail('预览不属于当前会话、成员、家庭或文件', 403)
                receipt_id = digest(signed)
                old = con.execute('SELECT id,status,observation_revision,source_digest,candidate_digest,accepted_at FROM finance_spending_receipts WHERE id=? AND owner=?', (receipt_id,owner)).fetchone()
                if old:
                    con.rollback()
                    return jsonify(dict(zip(('receiptId','status','revision','sourceDigest','candidateDigest','acceptedAt'),old)) | {'replayed':True,'assetBaselineUnchanged':True})
                private,current,expected = self.version(con,owner)
                if any(signed.get(k)!=v for k,v in expected.items()):
                    fail('财产基线或消费观察已改变，请保留文件并重新预览',409)
                self.assess(private,current,candidate,signed.get('acknowledgeUnknownPreviousCoverage'))
                unchanged = bool(current and current['candidateDigest']==candidate_digest)
                revision = expected['expectedRevision'] + (0 if unchanged else 1)
                accepted = datetime.now(timezone.utc).isoformat(timespec='seconds')
                if not unchanged:
                    con.execute('''INSERT INTO finance_spending_observations VALUES(?,?,?,?,?,?)
                        ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision,source_digest=excluded.source_digest,
                        candidate_digest=excluded.candidate_digest,candidate_json=excluded.candidate_json,accepted_at=excluded.accepted_at''',
                        (owner,revision,source_digest,candidate_digest,encode(candidate),accepted))
                status = 'unchanged' if unchanged else 'imported'
                con.execute('INSERT INTO finance_spending_receipts VALUES(?,?,?,?,?,?,?,?,?)',
                            (receipt_id,owner,candidate_digest,source_digest,expected['expectedRevision'],expected['expectedBaselineRevision'],revision,status,accepted))
                self.audit('finance.spending_observation',receipt_id)
                con.commit()
                return jsonify(receiptId=receipt_id,status=status,revision=revision,sourceDigest=source_digest,
                               candidateDigest=candidate_digest,acceptedAt=accepted,replayed=False,assetBaselineUnchanged=True)
            except Exception:
                con.rollback(); raise
        return self.checked(run)
