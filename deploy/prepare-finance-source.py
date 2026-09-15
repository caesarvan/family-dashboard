"""Prepare one private candidate from completed local reports; never refresh or import."""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from finance_source_bridge import VERSION, REPORT_PATHS, SOURCE_PATHS, normalize_candidate, digest
from finance_baseline import BaselineError, MAX_AMOUNT

REPORT = '08_Budgets/all-email-spend-report-12m.json'
ADAPTERS = {
    'banking': ('04_Banking/accounts.csv', 'assets', '余额', '统计日期', 'cash'),
    'loans': ('03_Loans/loans.csv', 'liabilities', '当前余额', None, 'liability'),
    'holdings': ('05_Investments/holdings-template.csv', 'assets', '当前市值', '统计日期', 'investment'),
    'property': ('05_Investments/property-valuation.csv', 'assets', '当前估值', '统计日期', 'property'),
    'income': ('01_Income/income-history.csv', 'income', '税前金额', '年度或月份', 'historical_income'),
}
TRAILING_NOTES_KINDS = {'holdings', 'property', 'income'}


class PrepareError(ValueError):
    pass


def reject(message='来源准备失败，请核对私人映射、日期和已完成产物；原候选已保留。'):
    raise PrepareError(message)


def strict_json(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                reject()
            out[key] = value
        return out
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_float=Decimal, parse_constant=lambda _: reject())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        reject('来源路径包含链接，未读取或更新候选。')
    if not path.is_file():
        reject('必需来源文件缺失，原候选已保留。')
    return path.resolve(strict=True)


def read_frozen(path):
    path = regular(path)
    before = path.stat()
    if not 0 < before.st_size <= 50_000_000:
        reject('来源文件为空或超过大小限制，原候选已保留。')
    raw = path.read_bytes()
    after = path.stat()
    if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        reject('来源正在变化，请等待生产任务完成后重试。')
    return {'path': path, 'bytes': raw, 'sha256': sha(raw), 'mtime': after.st_mtime,
            'mtime_ns': after.st_mtime_ns}


def money(value, nullable=False, signed=False):
    if value is None or (isinstance(value, str) and value.strip() in ('', '-', '--', '待确认', '未知', '待补充', '待估值')):
        if nullable:
            return None
        reject('来源金额缺失，原候选已保留。')
    if isinstance(value, (bool, float)):
        reject('来源金额必须可精确解析为整数分。')
    text = str(value).strip()
    if len(text) > 80 or not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', text):
        reject('来源金额格式不明确，原候选已保留。')
    amount = Decimal(text.replace(',', '')) * 100
    if not amount.is_finite() or amount != amount.to_integral_value() or abs(amount) > MAX_AMOUNT or (not signed and amount < 0):
        reject('来源金额无法精确转换为有效整数分。')
    return int(amount)


def business_date(raw, mapping, kind):
    raw = (raw or '').strip()
    if raw:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
            return date.fromisoformat(raw).isoformat(), 'source_record_date'
        if kind == 'income' and re.fullmatch(r'\d{4}-\d{2}', raw):
            year, month = map(int, raw.split('-'))
            return date(year, month, calendar.monthrange(year, month)[1]).isoformat(), 'income_period_end_not_receipt_date'
        if kind == 'income' and re.fullmatch(r'\d{4}', raw):
            return date(int(raw), 12, 31).isoformat(), 'income_year_end_not_receipt_date'
        reject('来源业务日期格式不明确，不使用文件修改时间代替。')
    if not isinstance(mapping.get('date'), str) or not isinstance(mapping.get('dateBasis'), str) or not mapping['dateBasis'].strip():
        reject('来源缺少业务日期，需要在私人映射中提供核对日期及依据。')
    return date.fromisoformat(mapping['date']).isoformat(), mapping['dateBasis']


def csv_records(source, raw):
    if not isinstance(source, dict) or set(source) - {'kind', 'path', 'records', 'encoding', 'allowMissingTrailingNotes', 'reviewedTrailingNotesFileSha256'}:
        reject()
    kind = source.get('kind')
    if kind not in ADAPTERS:
        reject('来源适配器不支持。')
    expected_path, collection, amount_column, date_column, category = ADAPTERS[kind]
    if source.get('path') != expected_path:
        reject('来源适配器路径不在白名单。')
    if source.get('encoding', 'utf-8-sig') not in ('utf-8-sig', 'utf-8', 'gb18030'):
        reject()
    allow_notes = source.get('allowMissingTrailingNotes', False)
    if type(allow_notes) is not bool:
        reject('尾部备注兼容策略必须明确为布尔值。')
    if allow_notes:
        reviewed_hash = source.get('reviewedTrailingNotesFileSha256')
        if kind not in TRAILING_NOTES_KINDS or not isinstance(reviewed_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', reviewed_hash):
            reject('尾部备注兼容仅限已知来源，并须提供已核对文件的 SHA256。')
        if reviewed_hash != sha(raw):
            reject('尾部备注来源已换版，请重新核对文件内容；原候选已保留。')
    elif 'reviewedTrailingNotesFileSha256' in source:
        reject('已核对的备注文件摘要须与明确启用的兼容策略一起配置。')
    content = raw.decode(source.get('encoding', 'utf-8-sig'))
    reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
    if (not reader.fieldnames or any(not name.strip() for name in reader.fieldnames)
            or len(set(reader.fieldnames)) != len(reader.fieldnames) or amount_column not in reader.fieldnames
            or (date_column and date_column not in reader.fieldnames) or len(reader.fieldnames) > 60):
        reject('来源列名缺失或重复，原候选已保留。')
    if allow_notes and reader.fieldnames[-1] != '备注':
        reject('尾部备注兼容要求最后一列明确为备注。')
    rows = []
    for row in reader:
        if len(rows) >= 500 or None in row:
            reject('来源行结构不正确或记录过多。')
        missing = [key for key, value in row.items() if value is None]
        if missing:
            # This is an explicitly reviewed file-format interpretation, not a
            # claim that an arbitrary missing middle delimiter can be detected.
            if allow_notes and missing == ['备注']:
                row['备注'] = ''
            else:
                reject('来源行缺少必需字段，原候选已保留。')
        if any(v.strip() for v in row.values()):
            rows.append(row)
    mappings = source.get('records')
    if not rows or not isinstance(mappings, list) or not mappings:
        reject('来源或稳定映射为空，原候选已保留。')
    selected, result = set(), {collection: []}
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) - {'id', 'legacyId', 'match', 'label', 'include', 'exclusionReason', 'date', 'dateBasis', 'currency', 'status', 'recordType', 'liabilitySign'}:
            reject()
        selector = mapping.get('match')
        if not isinstance(selector, dict) or not selector or any(k not in reader.fieldnames or not isinstance(v, str) for k, v in selector.items()):
            reject('稳定映射必须使用现有列的精确文本匹配。')
        matches = [(index, row) for index, row in enumerate(rows) if all(row[k].strip() == v.strip() for k, v in selector.items())]
        if len(matches) != 1 or matches[0][0] in selected:
            reject('稳定映射缺失、重复或对应多个来源记录，原候选已保留。')
        index, row = matches[0]; selected.add(index)
        if type(mapping.get('include')) is not bool or not isinstance(mapping.get('exclusionReason'), str):
            reject('稳定映射需要明确汇总范围及排除理由。')
        target_collection, target_category = collection, category
        if kind != 'banking' and any(key in mapping for key in ('recordType', 'liabilitySign')):
            reject('资产或负债类型配置仅适用于银行账户来源。')
        record_type = mapping.get('recordType', 'asset')
        if kind == 'banking' and record_type not in ('asset', 'liability'):
            reject('银行账户映射须明确选择资产或负债类型。')
        if kind == 'banking' and record_type == 'liability':
            sign = mapping.get('liabilitySign')
            if sign not in ('positive', 'negative'):
                reject('银行负债须明确余额以正数或负数记录，不按金额猜测。')
            amount = money(row[amount_column], nullable=True, signed=True)
            if amount is not None:
                amount *= -1 if sign == 'negative' else 1
                if amount < 0:
                    reject('银行负债余额符号与已声明口径不一致，原候选已保留。')
            target_collection, target_category = 'liabilities', 'liability'
        else:
            if 'liabilitySign' in mapping:
                reject('负债余额符号配置不能用于资产记录。')
            amount = money(row[amount_column], nullable=True)
        as_of, date_basis = business_date(row.get(date_column, '') if date_column else '', mapping, kind)
        currency = row.get('币种', mapping.get('currency', 'CNY')).strip().upper()
        # Currency aliases are explicit language labels, never exchange rates.
        currency = {'人民币': 'CNY', '人民币元': 'CNY', '美元': 'USD', '港币': 'HKD', '欧元': 'EUR'}.get(currency, currency)
        entry = {'id': mapping.get('id'), 'label': mapping.get('label'), 'category': target_category,
                 'amountCents': amount, 'currency': currency, 'asOf': as_of,
                 'status': mapping.get('status', 'missing_valuation' if amount is None else ('historical_income' if kind == 'income' else 'dated_record')),
                 'source': expected_path, 'includedInRecordedSubtotal': mapping['include'],
                 'exclusionReason': mapping['exclusionReason'], 'dateBasis': date_basis}
        if 'legacyId' in mapping:
            entry['legacyId'] = mapping['legacyId']
        result.setdefault(target_collection, []).append(entry)
    if len(selected) != len(rows):
        reject('来源包含未映射的新记录，请先注明稳定标识与排除范围。')
    return result


def timestamp(raw):
    if not isinstance(raw, str):
        reject()
    value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if value.utcoffset() is None:
        reject('生产任务时间缺少时区。')
    return value


def positive_flag(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or value < 0:
        reject('消费观察质量元数据不正确。')
    return value > 0


def prepare(config_path, output_path, mode='baseline'):
    """Freeze allowlisted bytes in memory, validate twice, atomically publish outside source."""
    config_path, output_path = Path(config_path).absolute(), Path(output_path).absolute()
    if config_path.resolve().is_relative_to(ROOT) or output_path.resolve().is_relative_to(ROOT):
        reject('私人配置和候选必须保存在源码目录之外。')
    config_blob = read_frozen(config_path)
    config = strict_json(config_blob['bytes'])
    if mode not in ('baseline', 'spending_observation'):
        reject('来源更新模式不支持。')
    required_config = {'schemaVersion', 'sourceRoot', 'runFile'} | ({'sources'} if mode == 'baseline' else set())
    if not isinstance(config, dict) or set(config) != required_config or type(config['schemaVersion']) is not int or config['schemaVersion'] != 1:
        reject('私人配置格式不正确。')
    source_root = Path(config['sourceRoot']).absolute()
    if not source_root.is_dir() or source_root.resolve().is_relative_to(ROOT):
        reject('私人来源目录不存在或位于源码中。')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (source_root, *source_root.parents)):
        reject('来源路径包含链接。')
    source_root = source_root.resolve(strict=True)
    run_path = Path(config['runFile']).absolute()
    if not re.fullmatch(r'run-\d{4}-\d{2}-\d{2}\.json', run_path.name):
        reject('只接受指定日期的生产任务运行记录。')
    if output_path.resolve().is_relative_to(source_root) or output_path.resolve() in (config_path.resolve(), run_path.resolve()):
        reject('候选输出不得覆盖来源、私人配置或运行记录。')
    sources = config.get('sources', [])
    if mode == 'baseline' and (not isinstance(sources, list) or not 1 <= len(sources) <= len(ADAPTERS)):
        reject('需要至少一个明确配置的来源。')
    paths = set(REPORT_PATHS)
    for source in sources:
        if not isinstance(source, dict) or source.get('kind') not in ADAPTERS or source.get('path') != ADAPTERS[source['kind']][0] or source['path'] in paths:
            reject('来源路径重复或不在白名单。')
        paths.add(source['path'])
    frozen = {p: read_frozen(source_root / p) for p in sorted(paths)}
    if sum(len(item['bytes']) for item in frozen.values()) > 100_000_000:
        reject('来源集合超过大小限制。')
    run_blob = read_frozen(run_path)
    run = strict_json(run_blob['bytes'])
    if not isinstance(run, dict) or run.get('status') != 'success' or type(run.get('exit_code')) is not int or run['exit_code'] != 0 or run.get('login_action_required') is not False:
        reject('生产任务未成功完成或仍需登录，原候选已保留。')
    generated = run.get('generated_at')
    generated_time = timestamp(generated)
    if run_blob['path'].name != f'run-{generated[:10]}.json':
        reject('生产任务记录日期与产物生成日期不一致。')
    listed = run.get('files')
    if not isinstance(listed, list) or len(listed) != len(REPORT_PATHS):
        reject('生产任务产物清单不完整。')
    checked = set()
    for entry in listed:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            reject()
        target = Path(entry['path'])
        target = (source_root / target) if not target.is_absolute() else target
        target = target.resolve(strict=True)
        if not target.is_relative_to(source_root):
            reject('生产任务产物路径越界。')
        relative = target.relative_to(source_root).as_posix()
        if relative not in REPORT_PATHS or relative in checked:
            reject('生产任务产物清单不正确。')
        checked.add(relative)
        item = frozen[relative]
        if type(entry.get('bytes')) is not int or entry['bytes'] != len(item['bytes']) or abs(timestamp(entry.get('modified_at')).timestamp() - item['mtime']) >= 1:
            reject('生产任务产物大小或修改时间不匹配，原候选已保留。')
    report = strict_json(frozen[REPORT]['bytes'])
    if mode == 'spending_observation':
        # Parse sidecars in memory; never include original rows in the candidate.
        for relative in REPORT_PATHS - {REPORT}:
            if not isinstance(strict_json(frozen[relative]['bytes']), (list, dict)):
                reject('报告产物结构不正确，原候选已保留。')
    report_quality, coverage = report['quality'], report['coverage']
    if report_quality.get('generated_at') != generated:
        reject('消费报告生成时间与成功运行记录不一致。')
    if not isinstance(coverage.get('known_gaps'), list) or not isinstance(report_quality.get('encrypted_unreadable_statements'), list):
        reject('消费报告覆盖信息缺失。')
    q = {'knownGapsCount': len(coverage['known_gaps']),
         'unreadableStatementsCount': len(report_quality['encrypted_unreadable_statements']),
         'channelOnlyAdded': positive_flag(report_quality.get('channel_only_spend_added')),
         'orderOnlyAdded': positive_flag(report_quality.get('order_only_spend_added'))}
    mapped_coverage = {'requestedStart': coverage['requested_start'], 'requestedEnd': coverage['requested_end'], **q}
    monthly = []
    if not isinstance(report.get('monthly'), list):
        reject()
    for row in report['monthly']:
        monthly.append({'period': row['period'], 'currency': row['currency'],
                        'grossSpendCents': money(row['gross_spend']), 'refundCents': money(row['refunds']),
                        'netSpendCents': money(row['net_spend'], signed=True), 'transactionCount': row['transaction_count']})
    candidate = {'schemaVersion': 1, 'converterVersion': VERSION, 'asOf': generated[:10],
                 'sourceManifest': {'version': 1, 'configDigest': digest({'schemaVersion': 1, 'sources': sources}),
                    'files': [{'path': p, 'sha256': item['sha256'], 'bytes': len(item['bytes'])} for p, item in frozen.items()],
                    'run': {'sha256': run_blob['sha256'], 'generatedAt': generated, 'status': 'success', 'exitCode': 0, 'loginActionRequired': False},
                    'coverage': mapped_coverage},
                 'assets': [], 'liabilities': [], 'income': [],
                 'spending': {'generatedAt': generated, 'requestedStart': coverage['requested_start'],
                              'requestedEnd': coverage['requested_end'], 'monthly': monthly, 'quality': q}}
    if mode == 'spending_observation':
        from spending_observations import VERSION as OBSERVATION_VERSION, normalize_spending_candidate
        manifest = candidate['sourceManifest']
        manifest.pop('configDigest')
        candidate = {'schemaVersion': 1, 'kind': mode, 'converterVersion': OBSERVATION_VERSION,
                     'sourceManifest': manifest, 'spending': candidate['spending']}
        candidate, candidate_digest, source_digest = normalize_spending_candidate(candidate)
    else:
        for source in sources:
            for kind, entries in csv_records(source, frozen[source['path']]['bytes']).items():
                candidate[kind].extend(entries)
        candidate, private, shared, candidate_digest = normalize_candidate(candidate, 'member1', generated)
        source_digest = private['sourceDigest']
    # No writes have happened: verify all original inputs before replacing the old output.
    for item in [config_blob, run_blob, *frozen.values()]:
        checked = read_frozen(item['path'])
        if checked['sha256'] != item['sha256'] or checked['mtime_ns'] != item['mtime_ns']:
            reject('来源在准备期间变化，原候选已保留，请稍后重试。')
    if output_path.exists() and (output_path.is_symlink() or not output_path.is_file()):
        reject('候选输出路径不正确。')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in output_path.parents):
        reject('候选输出路径包含链接。')
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    descriptor, temporary = tempfile.mkstemp(prefix='.finance-source-', suffix='.tmp', dir=output_path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if mode == 'spending_observation':
        return {'status': 'prepared', 'generatedAt': generated, 'candidateDigest': candidate_digest,
                'sourceDigest': source_digest, 'monthCount': len(candidate['spending']['monthly'])}
    return {'status': 'prepared', 'asOf': candidate['asOf'], 'candidateDigest': candidate_digest,
            'sourceDigest': private['sourceDigest'], 'counts': {kind: len(candidate[kind]) for kind in ('assets', 'liabilities', 'income')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description='只读已有财务产物，生成源码外的私人来源候选；不刷新邮箱或写入看板')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('baseline', 'spending_observation'), default='baseline')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.config, args.output, args.mode), ensure_ascii=False))
        return 0
    except (PrepareError, BaselineError, OSError, ValueError, TypeError, KeyError, csv.Error, RecursionError):
        print('来源准备失败；请核对成功运行记录、来源映射、日期和文件完整性。原候选未被替换。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
