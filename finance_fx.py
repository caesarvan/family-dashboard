"""Public ECB observations and exact display-currency conversion.

No account data leaves this module. Callers own authorization, transactions,
receipts and scheduling. Reference observations are not executable prices.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_UP
import hashlib
import http.client
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = 'https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A'
PROVIDER_PAGE = 'https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html'
MIN_DATE = date(1999, 1, 4)
MAX_DAYS = 373
MAX_BYTES = 5_000_000
MAX_ROWS = 20_000
MAX_STORED_RATES = 400_000
TIMEOUT_SECONDS = 25
FINANCE_FX_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS finance_fx_rates(
  version TEXT PRIMARY KEY, rate_date TEXT NOT NULL, currency TEXT NOT NULL,
  units_per_eur TEXT NOT NULL, source_url TEXT NOT NULL, body_sha256 TEXT NOT NULL,
  fetched_at TEXT NOT NULL, last_checked_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS finance_fx_rates_day_currency
  ON finance_fx_rates(rate_date,currency,last_checked_at);
'''


class FxError(Exception):
    def __init__(self, message, code='fx_invalid_data'):
        super().__init__(message)
        self.code = code


def init_fx_schema(con):
    for statement in FINANCE_FX_SCHEMA_SQL.split(';'):
        if statement.strip():
            con.execute(statement)


def fx_day(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise FxError('请选择有效的汇率日期。', 'fx_invalid_range')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise FxError('请选择有效的汇率日期。', 'fx_invalid_range') from None
    if result < MIN_DATE:
        raise FxError('参考汇率日期须从 1999-01-04 起。', 'fx_invalid_range')
    return result


def rate_text(value):
    if type(value) is not str or not re.fullmatch(r'(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?', value):
        raise FxError('参考汇率数值无法核对。')
    number = Decimal(value)
    if not Decimal('0.000000000001') <= number <= Decimal('999999999999'):
        raise FxError('参考汇率数值超出支持范围。')
    return format(number.normalize(), 'f')


def currency_code(value):
    if type(value) is not str or not re.fullmatch('[A-Z]{3}', value):
        raise FxError('请选择三位字母币种。', 'fx_invalid_currency')
    return value


def timestamp(value):
    if type(value) is not str or len(value) > 40:
        raise FxError('汇率读取时间无法核对。')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise FxError('汇率读取时间无法核对。') from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise FxError('汇率读取时间须为 UTC。')
    return parsed.isoformat(timespec='microseconds')


def ecb_url(start, end):
    left, right = fx_day(start), fx_day(end)
    if right < left or (right-left).days >= MAX_DAYS:
        raise FxError('每次汇率查询最多覆盖 373 天。', 'fx_invalid_range')
    return ENDPOINT + '?' + urllib.parse.urlencode(dict(startPeriod=start, endPeriod=end, format='csvdata'))


def parse_ecb_csv(raw, start, end, retrieved_at):
    """Validate series units and dates; missing values never become zero."""
    url, fetched = ecb_url(start, end), timestamp(retrieved_at)
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise FxError('汇率来源返回的数据为空或过大。')
    try:
        content = raw.decode('utf-8-sig', errors='strict')
    except UnicodeError:
        raise FxError('汇率来源编码无法核对。') from None
    if '\x00' in content:
        raise FxError('汇率来源含无效字符。')
    required = {'KEY', 'FREQ', 'CURRENCY', 'CURRENCY_DENOM', 'EXR_TYPE', 'EXR_SUFFIX',
                'TIME_PERIOD', 'OBS_VALUE', 'OBS_STATUS', 'UNIT', 'UNIT_MULT'}
    rates, seen = [], set()
    try:
        reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
        fields = reader.fieldnames
        if not fields or len(fields) > 80 or len(set(fields)) != len(fields) or not required <= set(fields):
            raise FxError('汇率来源缺少可核对的字段。')
        for index, row in enumerate(reader):
            if index >= MAX_ROWS or None in row or any(v is None or len(v) > 2048 for v in row.values()):
                raise FxError('汇率来源行数或字段无效。')
            currency = currency_code(row['CURRENCY'])
            observed = fx_day(row['TIME_PERIOD']).isoformat()
            key = (observed, currency)
            if currency == 'EUR' or key in seen or not start <= observed <= end:
                raise FxError('汇率来源日期、币种或重复行无法核对。')
            seen.add(key)
            if (row['KEY'] != f'EXR.D.{currency}.EUR.SP00.A' or row['FREQ'] != 'D'
                    or row['CURRENCY_DENOM'] != 'EUR' or row['EXR_TYPE'] != 'SP00'
                    or row['EXR_SUFFIX'] != 'A' or row['UNIT'] != currency or row['UNIT_MULT'] != '0'):
                raise FxError('汇率来源的基准或单位已变化。')
            if row['OBS_STATUS'] == 'M' and not row['OBS_VALUE']:
                continue
            if row['OBS_STATUS'] != 'A':
                raise FxError('汇率来源含未支持的观测状态。')
            rates.append(dict(date=observed, currency=currency, unitsPerEur=rate_text(row['OBS_VALUE'])))
    except (csv.Error, RecursionError):
        raise FxError('汇率来源表格无法解析。') from None
    if not rates:
        raise FxError('所选日期没有可用的参考汇率。', 'fx_no_data')
    return dict(provider='ECB', sourceUrl=url, retrievedAt=fetched,
                bodySha256=hashlib.sha256(raw).hexdigest(), requestedStart=start,
                requestedEnd=end, rates=sorted(rates, key=lambda r: (r['date'], r['currency'])))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FxError('汇率来源地址发生跳转，本次未更新。', 'fx_unavailable')


def fetch_ecb_rates(start, end):
    url = ecb_url(start, end)
    if fx_day(end) > datetime.now(timezone.utc).date():
        raise FxError('尚不能获取未来日期的参考汇率。', 'fx_invalid_range')
    request = urllib.request.Request(url, headers={'Accept': 'text/csv',
        'User-Agent': 'FamilyDashboard/1.0 (public ECB reference rates)'})
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status == 204:
                raise FxError('所选日期没有可用的参考汇率。', 'fx_no_data')
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if response.status != 200 or response.geturl() != url or content_type not in {
                    'text/csv', 'application/csv', 'application/vnd.sdmx.data+csv'}:
                raise FxError('汇率来源没有返回可核对的表格。', 'fx_unavailable')
            chunks, count = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise FxError('汇率读取超时，已保留原有记录。', 'fx_unavailable')
                chunk = response.read(min(64 * 1024, MAX_BYTES + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_BYTES:
                    raise FxError('汇率来源返回的数据过大，本次未更新。', 'fx_unavailable')
                chunks.append(chunk)
            if time.monotonic() > deadline:
                raise FxError('汇率读取超时，已保留原有记录。', 'fx_unavailable')
        return parse_ecb_csv(b''.join(chunks), start, end, datetime.now(timezone.utc).isoformat())
    except FxError:
        raise
    except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
        raise FxError('暂时无法读取 ECB 参考汇率，已保留原有记录。', 'fx_unavailable') from None


def _version(day, currency, value):
    return hashlib.sha256(json.dumps(['ECB', day, currency, value], separators=(',', ':')).encode('ascii')).hexdigest()


def save_fx_batch(con, batch):
    """Caller owns transaction; immutable rate versions retain first provenance."""
    if not con.in_transaction:
        raise FxError('汇率保存必须在授权事务内进行。')
    required = {'provider', 'sourceUrl', 'retrievedAt', 'bodySha256', 'requestedStart', 'requestedEnd', 'rates'}
    if type(batch) is not dict or set(batch) != required or batch['provider'] != 'ECB':
        raise FxError('汇率批次无法核对。')
    start, end = batch['requestedStart'], batch['requestedEnd']
    if batch['sourceUrl'] != ecb_url(start, end) or not re.fullmatch('[a-f0-9]{64}', str(batch['bodySha256'])):
        raise FxError('汇率批次来源无法核对。')
    fetched = timestamp(batch['retrievedAt'])
    if type(batch['rates']) is not list or not 1 <= len(batch['rates']) <= MAX_ROWS:
        raise FxError('汇率批次大小无法核对。')
    rows, seen = [], set()
    for item in batch['rates']:
        if type(item) is not dict or set(item) != {'date', 'currency', 'unitsPerEur'}:
            raise FxError('汇率批次内容无法核对。')
        day, currency, value = fx_day(item['date']).isoformat(), currency_code(item['currency']), rate_text(item['unitsPerEur'])
        if currency == 'EUR' or not start <= day <= end or (day, currency) in seen:
            raise FxError('汇率批次日期或重复行无法核对。')
        seen.add((day, currency))
        rows.append((_version(day, currency, value), day, currency, value,
                     batch['sourceUrl'], batch['bodySha256'], fetched, fetched))
    existing = {r[0] for r in con.execute('SELECT version FROM finance_fx_rates')}
    additions = sum(row[0] not in existing for row in rows)
    if len(existing) + additions > MAX_STORED_RATES:
        raise FxError('参考汇率记录已达到容量限制，原有记录仍可查看。', 'fx_capacity')
    con.executemany('INSERT INTO finance_fx_rates VALUES(?,?,?,?,?,?,?,?) '
        'ON CONFLICT(version) DO UPDATE SET last_checked_at=MAX(finance_fx_rates.last_checked_at,excluded.last_checked_at)', rows)
    return dict(inserted=additions, updated=len(rows)-additions, rateCount=len(rows), retrievedAt=fetched)


def load_fx_rates(con, start, end):
    ecb_url(start, end)
    rows = con.execute('SELECT version,rate_date,currency,units_per_eur,source_url,body_sha256,fetched_at,last_checked_at '
        'FROM finance_fx_rates WHERE rate_date>=? AND rate_date<=? '
        'ORDER BY rate_date,currency,last_checked_at DESC,version DESC', (start, end))
    result, seen = [], set()
    for row in rows:
        version, day, currency, value, url, digest, fetched, checked = row
        if (day, currency) in seen:
            continue
        seen.add((day, currency))
        if len(result) >= MAX_ROWS:
            raise FxError('所选期间的汇率记录过多，请缩短时间范围。', 'fx_capacity')
        if _version(day, currency, rate_text(value)) != version:
            raise FxError('已保存的参考汇率无法核对。')
        result.append(dict(date=day, currency=currency, unitsPerEur=value, version=version,
                           sourceUrl=url, bodySha256=digest, fetchedAt=fetched, lastCheckedAt=checked))
    return result


def resolve_fx_quote(rates, as_of, source_currency, target_currency, max_age_days=7):
    target_day = fx_day(as_of)
    source, target = currency_code(source_currency), currency_code(target_currency)
    if type(max_age_days) is not int or not 0 <= max_age_days <= 31:
        raise FxError('参考汇率回溯范围无效。')
    if source == target:
        return dict(sourceCurrency=source, targetCurrency=target, sourcePerEur='1', targetPerEur='1',
                    rateDate=None, ageDays=0, method='identity', observations=[])
    by_day = {}
    for rate in rates:
        if rate['currency'] not in {source, target} or rate['date'] > as_of:
            continue
        age = (target_day-fx_day(rate['date'])).days
        if 0 <= age <= max_age_days:
            by_day.setdefault(rate['date'], {})[rate['currency']] = rate
    for day in sorted(by_day, reverse=True):
        observations = by_day[day]
        if all(c == 'EUR' or c in observations for c in (source, target)):
            return dict(sourceCurrency=source, targetCurrency=target,
                        sourcePerEur='1' if source == 'EUR' else rate_text(observations[source]['unitsPerEur']),
                        targetPerEur='1' if target == 'EUR' else rate_text(observations[target]['unitsPerEur']),
                        rateDate=day, ageDays=(target_day-fx_day(day)).days, method='ecb_cross',
                        observations=[dict(observations[c]) for c in (source, target) if c != 'EUR'])
    return None


def convert_cents(amount, source_rate, target_rate):
    """Stored account cents are 1/100 original unit, including JPY legacy data."""
    if type(amount) is not int or abs(amount) > 10**20:
        raise FxError('待换算金额超出支持范围。')
    source, target = Decimal(rate_text(source_rate)), Decimal(rate_text(target_rate))
    with localcontext() as context:
        context.prec = 80
        try:
            return int((Decimal(amount)*target/source).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            raise FxError('待换算金额无法精确处理。') from None
