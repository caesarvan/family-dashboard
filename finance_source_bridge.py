"""Private, dated source candidates; explicit preview and atomic owner-scoped CAS.

This module never contacts a financial institution or writes the payment ledger.
Source hashes describe supplied evidence, not proof of an institution's accuracy.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3

from flask import g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from finance_baseline import (BaselineError, EXCLUDED_KEYS, MAX_PAYLOAD_BYTES,
                              _amount, _date, _json, _timestamp, _validate,
                              import_baseline)

VERSION = 'finance-source-v1'
SOURCE_PATHS = {
    '04_Banking/accounts.csv', '03_Loans/loans.csv',
    '05_Investments/holdings-template.csv', '05_Investments/property-valuation.csv',
    '01_Income/income-history.csv',
    '08_Budgets/all-email-spend-report-12m.json',
    '08_Budgets/all-email-spend-transactions-12m.json',
    '08_Budgets/statement-attachment-inventory-12m.json',
}
REPORT_PATHS = {p for p in SOURCE_PATHS if p.endswith('.json')}
KINDS = ('assets', 'liabilities', 'income')
ENTRY_KEYS = {'id', 'legacyId', 'label', 'category', 'amountCents', 'currency', 'asOf',
              'status', 'source', 'includedInRecordedSubtotal', 'exclusionReason', 'dateBasis'}
RECEIPT_COLUMNS = ('id', 'owner', 'candidate_digest', 'source_digest', 'expected_revision',
                   'expected_source_digest', 'baseline_revision', 'status', 'accepted_at')


class SourceError(BaselineError):
    def __init__(self, message='来源候选格式不正确', status=400):
        super().__init__(message)
        self.status = status


def fail(message='来源候选格式不正确', status=400):
    raise SourceError(message, status)


def digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


class ImportRecoveryError(Exception):
    def __init__(self, message, code, status):
        super().__init__(message)
        self.code, self.status = code, status


class ImportSession:
    """One captured HTTP identity, checked in fresh SQLite snapshots."""
    def __init__(self, app, db, Problem, require_member):
        require_member()
        self.app, self.con, self.Problem, self.require_member = app, db(), Problem, require_member
        self.engine = app.extensions.get('member_sessions')
        if self.engine is None:
            raise Problem('会话验证暂不可用，请稍后重试', 503)
        self.actor = dict(g.actor)
        self.original = dict(getattr(g, 'member_session', None) or {})
        self.owner = self.actor.get('id')
        self.household = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')

    def check(self):
        self.require_member()
        current = self.engine.current(self.con)
        if (g.actor != self.actor
                or self.app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default') != self.household
                or self.actor.get('householdId') != self.household
                or current['owner'] != self.owner
                or current['auth_version'] != self.actor.get('auth_version')
                or any(current[key] != self.original.get(key)
                       for key in ('id', 'owner', 'auth_version', 'credential_hash'))):
            raise self.Problem('会话已失效，请重新登录', 401)
        return digest({'owner': current['owner'], 'household': self.household,
                       'session': current['id'], 'credential': current['credential_hash'],
                       'authVersion': current['auth_version']})

    @contextmanager
    def read(self):
        # Legacy credential resolution can open an implicit transaction.
        self.con.rollback()
        try:
            self.con.execute('BEGIN')
            self.check()
            yield self.con
        finally:
            self.con.rollback()
        self.fresh()

    def fresh(self):
        self.con.rollback()
        try:
            self.check()
        finally:
            self.con.rollback()

    @contextmanager
    def write(self):
        self.con.rollback()
        try:
            self.con.execute('BEGIN IMMEDIATE')
            self.check()
            yield self.con
            self.check()
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise


def signed_preview(signer, token):
    if not isinstance(token, str) or len(token) > 4000:
        raise ImportRecoveryError('来源预览凭据不正确', 'preview_invalid', 400)
    try:
        value, issued = signer.loads(token, return_timestamp=True)
    except BadSignature:
        raise ImportRecoveryError('来源预览凭据不正确，请重新预览', 'preview_invalid', 409) from None
    if not isinstance(value, dict):
        raise ImportRecoveryError('来源预览凭据不正确', 'preview_invalid', 400)
    return value, issued


def require_fresh_preview(signer, issued):
    age = signer.make_signer().get_timestamp() - int(issued.timestamp())
    if not 0 <= age <= 1200:
        raise ImportRecoveryError('预览已过期且尚无保存回执，请重新预览', 'preview_expired', 410)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def exact(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        fail()


def text_field(value, maximum=200):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        fail()
    return value


def hash_field(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        fail('来源文件摘要格式不正确')


def integer(value, maximum=1000000):
    if type(value) is not int or not 0 <= value <= maximum:
        fail()


def quality(value):
    exact(value, ('knownGapsCount', 'unreadableStatementsCount', 'channelOnlyAdded', 'orderOnlyAdded'))
    for key in ('knownGapsCount', 'unreadableStatementsCount'):
        integer(value[key])
    for key in ('channelOnlyAdded', 'orderOnlyAdded'):
        if type(value[key]) is not bool:
            fail()


def normalize_candidate(candidate, owner, imported_at=None):
    """Strict pure conversion; deliberately ignore no client-supplied shared fields."""
    exact(candidate, ('schemaVersion', 'converterVersion', 'asOf', 'sourceManifest', *KINDS, 'spending'))
    try:
        if len(_json(candidate).encode('utf-8')) > MAX_PAYLOAD_BYTES - 50000:
            fail('来源候选文件过大')
    except (TypeError, ValueError, RecursionError):
        fail()
    if type(candidate['schemaVersion']) is not int or candidate['schemaVersion'] != 1 or candidate['converterVersion'] != VERSION:
        fail('来源候选版本不支持')
    _date(candidate['asOf'])
    manifest = candidate['sourceManifest']
    exact(manifest, ('version', 'files', 'configDigest', 'run', 'coverage'))
    if type(manifest['version']) is not int or manifest['version'] != 1:
        fail()
    hash_field(manifest['configDigest'])
    if not isinstance(manifest['files'], list) or not 4 <= len(manifest['files']) <= len(SOURCE_PATHS):
        fail('来源文件清单不完整')
    paths = set()
    for entry in manifest['files']:
        exact(entry, ('path', 'sha256', 'bytes'))
        if entry['path'] not in SOURCE_PATHS or entry['path'] in paths:
            fail('来源文件不在白名单或重复')
        paths.add(entry['path'])
        hash_field(entry['sha256'])
        integer(entry['bytes'], 50_000_000)
        if not entry['bytes']:
            fail('来源文件为空，保留原有基线')
    if not REPORT_PATHS <= paths:
        fail('来源产物清单不完整')
    run = manifest['run']
    exact(run, ('sha256', 'generatedAt', 'status', 'exitCode', 'loginActionRequired'))
    hash_field(run['sha256'])
    _timestamp(run['generatedAt'])
    if datetime.fromisoformat(run['generatedAt'].replace('Z', '+00:00')) > datetime.now(timezone.utc) + timedelta(minutes=5):
        fail('来源产物生成时间不可在未来')
    if run['status'] != 'success' or type(run['exitCode']) is not int or run['exitCode'] != 0 or run['loginActionRequired'] is not False:
        fail('来源生产任务未成功完成，保留原有基线')
    if run['generatedAt'][:10] != candidate['asOf']:
        fail('来源版本日期与产物生成日期不一致')
    coverage = manifest['coverage']
    exact(coverage, ('requestedStart', 'requestedEnd', 'knownGapsCount', 'unreadableStatementsCount', 'channelOnlyAdded', 'orderOnlyAdded'))
    _date(coverage['requestedStart']); _date(coverage['requestedEnd'])
    if not coverage['requestedStart'] <= coverage['requestedEnd'] <= candidate['asOf']:
        fail('来源覆盖区间不正确')
    q = {k: coverage[k] for k in ('knownGapsCount', 'unreadableStatementsCount', 'channelOnlyAdded', 'orderOnlyAdded')}
    quality(q)
    dates, all_ids, all_legacy = [], set(), set()
    excluded = {key: False for key in EXCLUDED_KEYS}
    totals = {'complete': False, 'assetCents': None, 'liabilityCents': None, 'netCents': None,
              'recordedAssetCents': 0, 'recordedLiabilityCents': 0}
    entries = {}
    for kind in KINDS:
        rows = candidate[kind]
        if not isinstance(rows, list) or len(rows) > 500:
            fail('来源记录过多或格式不正确')
        entries[kind] = []
        for item in rows:
            exact(item, ENTRY_KEYS - {'legacyId'}, ('legacyId',))
            for key in ('id', 'label', 'category', 'status', 'dateBasis'):
                text_field(item[key], 200)
            if not re.fullmatch('[A-Za-z0-9_.:-]{1,100}', item['id']) or item['id'] in all_ids:
                fail('来源记录稳定标识重复或不正确')
            all_ids.add(item['id'])
            if 'legacyId' in item:
                text_field(item['legacyId'], 100)
                old_key = (kind, item['legacyId'])
                if old_key in all_legacy:
                    fail('旧记录映射重复')
                all_legacy.add(old_key)
            _date(item['asOf'])
            if item['asOf'] > candidate['asOf']:
                fail('记录日期晚于来源版本日期')
            if item['source'] not in paths or not item['source'].endswith('.csv'):
                fail('记录来源不在已冻结文件清单')
            if not isinstance(item['currency'], str) or not re.fullmatch('[A-Z]{3}', item['currency']):
                fail('记录币种不正确')
            _amount(item['amountCents'], nullable=True)
            if type(item['includedInRecordedSubtotal']) is not bool or not isinstance(item['exclusionReason'], str) or len(item['exclusionReason']) > 500:
                fail('记录汇总口径不正确')
            if item['includedInRecordedSubtotal']:
                if item['amountCents'] is None or item['currency'] != 'CNY' or item['exclusionReason'] or kind == 'income' or item['status'] != 'dated_record':
                    fail('未估值、外币或收入不可计入资产负债小计')
            elif not item['exclusionReason'].strip():
                fail('排除记录必须注明理由')
            if item['currency'] != 'CNY':
                excluded['foreignCurrencyConversion'] = True
            if item['amountCents'] is None:
                excluded['missingValuations'] = True
            for status, flag in (('unvested_compensation', 'unvestedCompensation'),
                                 ('unconfirmed_transfer', 'unconfirmedTransfers'),
                                 ('unconfirmed_credit_balance', 'unconfirmedCreditBalances')):
                if item['status'] == status:
                    excluded[flag] = True
            if kind != 'income':
                dates.append(item['asOf'])
                if item['includedInRecordedSubtotal']:
                    key = 'recordedAssetCents' if kind == 'assets' else 'recordedLiabilityCents'
                    totals[key] += item['amountCents']
                    _amount(totals[key])
            entries[kind].append(deepcopy(item))
        entries[kind].sort(key=lambda item: item['id'])
    if not dates:
        fail('没有可核对的资产或负债记录，保留原有基线')
    spending = candidate['spending']
    exact(spending, ('generatedAt', 'requestedStart', 'requestedEnd', 'monthly', 'quality'))
    if spending['generatedAt'] != run['generatedAt'] or any(spending[k] != coverage[k] for k in ('requestedStart', 'requestedEnd')) or spending['quality'] != q:
        fail('消费观察报告与来源覆盖不一致')
    if not isinstance(spending['monthly'], list) or len(spending['monthly']) > 240:
        fail('来源消费观察格式不正确')
    seen_months = set()
    for month in spending['monthly']:
        exact(month, ('period', 'currency', 'grossSpendCents', 'refundCents', 'netSpendCents', 'transactionCount'))
        if not isinstance(month['period'], str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month['period']):
            fail('来源消费月份不正确')
        if not coverage['requestedStart'][:7] <= month['period'] <= coverage['requestedEnd'][:7]:
            fail('来源消费月份超出覆盖范围')
        if not isinstance(month['currency'], str) or not re.fullmatch('[A-Z]{3}', month['currency']):
            fail()
        key = (month['period'], month['currency'])
        if key in seen_months:
            fail('来源消费月份和币种重复')
        seen_months.add(key)
        for key in ('grossSpendCents', 'refundCents', 'netSpendCents'):
            _amount(month[key], signed=key == 'netSpendCents')
        integer(month['transactionCount'])
        if month['grossSpendCents'] - month['refundCents'] != month['netSpendCents']:
            fail('来源消费观察汇总不一致')
    frozen = deepcopy(candidate)
    frozen['sourceManifest']['files'].sort(key=lambda item: item['path'])
    frozen['spending']['monthly'].sort(key=lambda item: (item['period'], item['currency']))
    for kind in KINDS:
        frozen[kind] = entries[kind]
    candidate_digest = digest(frozen)
    source_digest = digest({'converterVersion': VERSION, 'manifest': frozen['sourceManifest']})
    common = {'schemaVersion': 1, 'owner': owner, 'asOf': frozen['asOf'], 'importedAt': imported_at or now(),
              'currency': 'CNY', 'sourceDigest': source_digest,
              'balanceAsOfStart': min(dates), 'balanceAsOfEnd': max(dates)}
    private = {**common, **entries, 'totals': totals, 'spending': frozen['spending'],
               'sourceBridge': {'converterVersion': VERSION, 'candidateDigest': candidate_digest,
                                'manifest': frozen['sourceManifest']}}
    shared = {**common, **totals, 'excluded': excluded}
    return frozen, private, shared, candidate_digest


def ensure_receipts(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS finance_source_receipts(
        id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
        candidate_digest TEXT NOT NULL, source_digest TEXT NOT NULL,
        expected_revision INTEGER NOT NULL, expected_source_digest TEXT,
        baseline_revision INTEGER NOT NULL, status TEXT NOT NULL,
        accepted_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS finance_source_receipts_owner ON finance_source_receipts(owner,accepted_at)')


def current(conn, owner):
    row = conn.execute('SELECT private_data,revision,source_digest FROM finance_baselines WHERE owner=?', (owner,)).fetchone()
    return (json.loads(row[0]), row[1], row[2]) if row else (None, 0, None)


def expected_fields(payload):
    revision, source = payload.get('expectedRevision'), payload.get('expectedSourceDigest')
    integer(revision, 2**53 - 1)
    if revision == 0:
        if source is not None:
            fail('目标版本与来源摘要不一致')
    else:
        hash_field(source)
    return revision, source


def assess_update(previous, private):
    changes = {'added': 0, 'updated': 0, 'preserved': 0}
    if previous and private['asOf'] < previous['asOf']:
        fail('来源版本日期倒退，已保留原有基线', 409)
    if previous:
        prior_manifest = previous.get('sourceBridge', {}).get('manifest')
        if prior_manifest:
            before = prior_manifest['coverage']; after = private['sourceBridge']['manifest']['coverage']
            before_days = (date.fromisoformat(before['requestedEnd']) - date.fromisoformat(before['requestedStart'])).days
            after_days = (date.fromisoformat(after['requestedEnd']) - date.fromisoformat(after['requestedStart'])).days
            if after['requestedEnd'] < before['requestedEnd'] or after_days < before_days:
                fail('来源覆盖缩短或倒退，已保留原有基线', 409)
            if not {x['path'] for x in prior_manifest['files']} <= {x['path'] for x in private['sourceBridge']['manifest']['files']}:
                fail('来源文件缺失，已保留原有基线', 409)
    for kind in KINDS:
        old = {str(item.get('id', f'legacy-{kind}-{i}')): item for i, item in enumerate((previous or {}).get(kind, []))}
        consumed = set()
        for entry in private[kind]:
            prior_id = entry['id'] if entry['id'] in old else entry.get('legacyId')
            prior = old.get(prior_id)
            if prior is None:
                changes['added'] += 1
                continue
            if prior_id in consumed:
                fail('同一旧记录被多次映射', 409)
            consumed.add(prior_id)
            if entry['asOf'] < prior['asOf']:
                fail('记录日期倒退，已保留原有基线', 409)
            if prior.get('amountCents') is not None and entry['amountCents'] is None:
                fail('来源缺少已有金额，已保留原有基线', 409)
            comparable_keys = ('label', 'category', 'amountCents', 'currency', 'asOf', 'status', 'includedInRecordedSubtotal')
            changes['preserved' if all(entry.get(k) == prior.get(k) for k in comparable_keys) else 'updated'] += 1
        if set(old) - consumed:
            fail('旧记录缺少稳定映射或来源记录消失，已保留原有基线；请补全映射后重新生成', 409)
    return changes


def register_finance_source_bridge(app, db, Problem, body, require_member, audit):
    from spending_observations import SpendingObservations, MODE
    observations = SpendingObservations(app, db, Problem, require_member, audit)
    app.extensions['spending_observations'] = observations
    signer = URLSafeTimedSerializer(app.secret_key, salt='finance-source-import-v1')
    with app.app_context():
        ensure_receipts(db()); db().commit()

    @app.errorhandler(ImportRecoveryError)
    def recovery_error(exc):
        return jsonify(error=str(exc), code=exc.code), exc.status

    def context():
        return ImportSession(app, db, Problem, require_member)

    def translated(fn):
        try:
            return fn()
        except SourceError as exc:
            raise Problem(str(exc), exc.status)
        except BaselineError as exc:
            raise Problem(str(exc), 400)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise Problem('来源候选格式不正确', 400)

    def receipt_view(row, replayed=False):
        value = dict(zip(RECEIPT_COLUMNS, row))
        return {'receiptId': value['id'], 'status': value['status'], 'revision': value['baseline_revision'],
                'sourceDigest': value['source_digest'], 'candidateDigest': value['candidate_digest'],
                'acceptedAt': value['accepted_at'], 'replayed': replayed}

    @app.get('/api/finance-baseline/imports/status')
    def finance_source_status():
        if len(request.args.getlist('mode')) > 1:
            raise Problem('来源更新模式不支持', 400)
        if request.args.get('mode') == MODE:
            return observations.status()
        if request.args.get('mode') not in (None, '', 'baseline'):
            raise Problem('来源更新模式不支持', 400)
        session = context()
        operation = request.args.get('operationId')
        if operation is not None and (len(request.args.getlist('operationId')) != 1
                                      or not re.fullmatch('[a-f0-9]{64}', operation)):
            raise Problem('操作编号格式不正确', 400)
        with session.read() as con:
            if operation is not None:
                row = con.execute('SELECT ' + ','.join(RECEIPT_COLUMNS) + ' FROM finance_source_receipts WHERE id=? AND owner=?',
                                  (operation, session.owner)).fetchone()
                result = dict(mode='baseline', operationId=operation, found=row is not None,
                              receipt=receipt_view(row, True) if row else None)
            else:
                private, revision, source = current(con, session.owner)
                row = con.execute('SELECT ' + ','.join(RECEIPT_COLUMNS) + ' FROM finance_source_receipts WHERE owner=? ORDER BY accepted_at DESC,rowid DESC LIMIT 1', (session.owner,)).fetchone()
                view = ({key: private[key] for key in ('asOf', 'balanceAsOfStart', 'balanceAsOfEnd')} | {'revision': revision, 'sourceDigest': source}) if private else None
                result = dict(current=view, lastReceipt=receipt_view(row) if row else None,
                              coverage='partial_dated_records', warnings=['来源观察不会写入实付账本、投资账户或公共荷包。'])
        return jsonify(result)

    @app.post('/api/finance-baseline/imports/preview')
    def finance_source_preview():
        require_member()
        payload = body()
        if isinstance(payload, dict) and payload.get('mode') == MODE:
            return observations.preview(payload)
        def run():
            payload = body()
            exact(payload, ('candidate', 'expectedRevision', 'expectedSourceDigest'))
            session = context()
            owner, household = session.owner, session.household
            revision, source = expected_fields(payload)
            frozen, private, shared, candidate_digest = normalize_candidate(payload['candidate'], owner)
            with session.read() as con:
                previous, actual_revision, actual_source = current(con, owner)
                if (revision, source) != (actual_revision, actual_source):
                    fail('财务基线已变更，请保留候选并重新预览', 409)
                shared = _validate(con, private, shared)
                changes = assess_update(previous, private)
                signed = {'owner': owner, 'household': household, 'candidateDigest': candidate_digest,
                          'context': session.check(), 'expectedRevision': revision, 'expectedSourceDigest': source}
                token = signer.dumps(signed)
            return jsonify(previewToken=token, operationId=digest(signed), candidateDigest=candidate_digest,
                           expectedRevision=revision, expectedSourceDigest=source, private=private, shared=shared,
                           changes=changes, asOf=private['asOf'], balanceAsOfStart=private['balanceAsOfStart'],
                           balanceAsOfEnd=private['balanceAsOfEnd'], coverage='partial_dated_records', expiresIn=1200,
                           warnings=['仅更新已有日期依据的本人基线，共享资产和负债小计。',
                                     '消费报告含渠道或订单补记，作为来源观察，不代表全部已确认实付。',
                                     '未估值、外币及排除项目不进入人民币共享小计，完整净资产仍为空。'])
        return translated(run)

    @app.post('/api/finance-baseline/imports/confirm')
    def finance_source_confirm():
        require_member()
        payload = body()
        if isinstance(payload, dict) and payload.get('mode') == MODE:
            return observations.confirm(payload)
        def run():
            payload = body()
            exact(payload, ('candidate', 'previewToken'))
            session = context()
            owner, household = session.owner, session.household
            signed, issued = signed_preview(signer, payload['previewToken'])
            exact(signed, ('owner', 'household', 'candidateDigest', 'expectedRevision', 'expectedSourceDigest'), ('context',))
            text_field(signed['owner']); text_field(signed['household'])
            hash_field(signed['candidateDigest'])
            if 'context' in signed:
                hash_field(signed['context'])
            frozen, private, shared, candidate_digest = normalize_candidate(payload['candidate'], owner)
            if not isinstance(signed, dict) or signed.get('owner') != owner or signed.get('household') != household or signed.get('candidateDigest') != candidate_digest:
                fail('来源预览不属于当前成员、家庭或候选', 403)
            revision, source = expected_fields(signed)
            receipt_id = digest(signed)
            with session.write() as conn:
                receipt = conn.execute('SELECT ' + ','.join(RECEIPT_COLUMNS) + ' FROM finance_source_receipts WHERE id=? AND owner=?', (receipt_id, owner)).fetchone()
                if receipt:
                    if receipt[2] != candidate_digest or receipt[3] != private['sourceDigest']:
                        fail('保存回执与候选不一致', 409)
                    response = receipt_view(receipt, True)
                else:
                    require_fresh_preview(signer, issued)
                    if 'context' not in signed:
                        raise ImportRecoveryError('旧预览缺少会话绑定，请重新预览', 'preview_repreview_required', 409)
                    if signed['context'] != session.check():
                        fail('来源预览不属于当前会话，请重新预览', 403)
                    previous, actual_revision, actual_source = current(conn, owner)
                    if (revision, source) != (actual_revision, actual_source):
                        fail('财务基线已变更，请保留候选并重新预览', 409)
                    assess_update(previous, private)
                    result = import_baseline(conn, private, shared)
                    accepted_at = now()
                    row = (receipt_id, owner, candidate_digest, private['sourceDigest'], revision, source,
                           result['revision'], 'imported' if result['imported'] else 'unchanged', accepted_at)
                    conn.execute('INSERT INTO finance_source_receipts(' + ','.join(RECEIPT_COLUMNS) + ') VALUES(?,?,?,?,?,?,?,?,?)', row)
                    audit('finance_source_import', receipt_id)
                    response = receipt_view(row)
            if receipt:
                session.fresh()
            return jsonify(response)
        return translated(run)

    app.extensions['finance_source_bridge'] = {'receiptColumns': RECEIPT_COLUMNS,
                                                'normalizeCandidate': normalize_candidate}
