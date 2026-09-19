"""Exact reference conversion, persisted revisions and bounded public downloads."""
from contextlib import closing
import csv
from datetime import date, timedelta
import hashlib
import http.client
import io
import sqlite3
import urllib.error

import pytest

import finance_fx as fx


START, END = '2026-09-10', '2026-09-18'
STAMP = '2026-09-19T06:11:15.621256+00:00'
FIELDS = ('KEY', 'FREQ', 'CURRENCY', 'CURRENCY_DENOM', 'EXR_TYPE', 'EXR_SUFFIX',
          'TIME_PERIOD', 'OBS_VALUE', 'OBS_STATUS', 'UNIT', 'UNIT_MULT')


def observation(currency='USD', value='1.25', day=END, **changes):
    return dict(KEY=f'EXR.D.{currency}.EUR.SP00.A', FREQ='D', CURRENCY=currency,
                CURRENCY_DENOM='EUR', EXR_TYPE='SP00', EXR_SUFFIX='A',
                TIME_PERIOD=day, OBS_VALUE=value, OBS_STATUS='A', UNIT=currency,
                UNIT_MULT='0', **changes)


def csv_body(rows=None):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows if rows is not None else [observation(), observation('CNY', '8')])
    return stream.getvalue().encode('utf-8')


def batch(rows=None, stamp=STAMP):
    return fx.parse_ecb_csv(csv_body(rows), START, END, stamp)


@pytest.fixture
def con(tmp_path):
    with closing(sqlite3.connect(tmp_path/'fx.sqlite3')) as db:
        fx.init_fx_schema(db)
        yield db


def store(con, payload):
    con.execute('BEGIN')
    result = fx.save_fx_batch(con, payload)
    con.commit()
    return result


def test_real_sqlite_persists_rates_and_exact_provenance(con):
    payload = batch()
    assert store(con, payload) == dict(inserted=2, updated=0, rateCount=2, retrievedAt=STAMP)
    rows = fx.load_fx_rates(con, START, END)
    assert [(r['currency'], r['unitsPerEur']) for r in rows] == [('CNY', '8'), ('USD', '1.25')]
    for row in rows:
        assert row['sourceUrl'] == fx.ecb_url(START, END)
        assert row['bodySha256'] == hashlib.sha256(csv_body()).hexdigest()
        assert row['fetchedAt'] == row['lastCheckedAt'] == STAMP
        assert len(row['version']) == 64
    quote = fx.resolve_fx_quote(rows, END, 'USD', 'CNY')
    assert quote['rateDate'] == END and quote['ageDays'] == 0
    assert fx.convert_cents(10000, quote['sourcePerEur'], quote['targetPerEur']) == 64000
    assert [r['currency'] for r in quote['observations']] == ['USD', 'CNY']
    # Closing and reopening the file demonstrates persistence, not only an in-memory view.
    filename = con.execute('PRAGMA database_list').fetchone()[2]
    with closing(sqlite3.connect(filename)) as reopened:
        assert fx.load_fx_rates(reopened, START, END) == rows


def test_refresh_keeps_original_provenance_and_corrected_rate_versions(con):
    initial = batch([observation(value='1.20')])
    store(con, initial)
    first = fx.load_fx_rates(con, START, END)[0]
    later = batch([observation(value='1.2000')], '2026-09-19T07:00:00Z')
    assert store(con, later)['updated'] == 1
    identical = fx.load_fx_rates(con, START, END)[0]
    assert identical['version'] == first['version']
    assert identical['fetchedAt'] == first['fetchedAt']
    assert identical['bodySha256'] == first['bodySha256']
    assert identical['lastCheckedAt'] == '2026-09-19T07:00:00.000000+00:00'
    correction = batch([observation(value='1.21')], '2026-09-19T08:00:00+00:00')
    assert store(con, correction)['inserted'] == 1
    changed = fx.load_fx_rates(con, START, END)[0]
    assert changed['version'] != first['version'] and changed['unitsPerEur'] == '1.21'
    assert con.execute('SELECT count(*) FROM finance_fx_rates').fetchone()[0] == 2
    # A late response downloaded earlier must not replace the newer observation.
    store(con, later)
    assert fx.load_fx_rates(con, START, END)[0] == changed
    # A subsequent official reversion is a new check of the retained old version.
    reverted = batch([observation(value='1.2')], '2026-09-19T09:00:00+00:00')
    store(con, reverted)
    assert fx.load_fx_rates(con, START, END)[0]['version'] == first['version']


def test_caller_transaction_rolls_back_whole_batch(con):
    with pytest.raises(fx.FxError):
        fx.save_fx_batch(con, batch())
    con.execute('BEGIN')
    fx.save_fx_batch(con, batch())
    assert con.in_transaction
    con.rollback()
    assert fx.load_fx_rates(con, START, END) == []


def test_invalid_late_row_cannot_partially_save(con):
    payload = batch()
    payload['rates'][-1]['unitsPerEur'] = 'NaN'
    con.execute('BEGIN')
    with pytest.raises(fx.FxError):
        fx.save_fx_batch(con, payload)
    assert con.execute('SELECT count(*) FROM finance_fx_rates').fetchone()[0] == 0
    con.rollback()


def test_capacity_allows_existing_versions_without_erasing_history(con, monkeypatch):
    monkeypatch.setattr(fx, 'MAX_STORED_RATES', 2)
    store(con, batch())
    assert store(con, batch())['inserted'] == 0
    con.execute('BEGIN')
    with pytest.raises(fx.FxError, match='容量') as error:
        fx.save_fx_batch(con, batch([observation(value='1.26')]))
    assert error.value.code == 'fx_capacity'
    assert con.execute('SELECT count(*) FROM finance_fx_rates').fetchone()[0] == 2
    con.rollback()


def test_corrupt_stored_rate_does_not_become_a_plausible_quote(con):
    store(con, batch())
    con.execute("UPDATE finance_fx_rates SET units_per_eur='999' WHERE currency='USD'")
    con.commit()
    with pytest.raises(fx.FxError):
        fx.load_fx_rates(con, START, END)


def test_cross_currency_uses_latest_common_day_and_never_future_rates():
    rates = [dict(date='2026-09-18', currency='USD', unitsPerEur='1.3'),
             dict(date='2026-09-17', currency='USD', unitsPerEur='1.25'),
             dict(date='2026-09-17', currency='CNY', unitsPerEur='8'),
             dict(date='2026-09-19', currency='CNY', unitsPerEur='9')]
    quote = fx.resolve_fx_quote(rates, END, 'USD', 'CNY')
    assert quote['rateDate'] == '2026-09-17' and quote['ageDays'] == 1
    assert (quote['sourcePerEur'], quote['targetPerEur']) == ('1.25', '8')
    # Independently available dates cannot be mixed into an invented pair.
    assert fx.resolve_fx_quote([rates[0], rates[2]], END, 'USD', 'CNY') is None
    assert fx.resolve_fx_quote(rates, END, 'USD', 'XYZ') is None
    assert fx.resolve_fx_quote(rates, '2026-09-25', 'USD', 'CNY') is None


def test_seven_day_boundary_eur_base_and_identity():
    rates = [dict(date='2026-09-11', currency='USD', unitsPerEur='1.25')]
    quote = fx.resolve_fx_quote(rates, END, 'EUR', 'USD')
    assert quote['ageDays'] == 7
    assert fx.convert_cents(10000, quote['sourcePerEur'], quote['targetPerEur']) == 12500
    reverse = fx.resolve_fx_quote(rates, END, 'USD', 'EUR')
    assert fx.convert_cents(12500, reverse['sourcePerEur'], reverse['targetPerEur']) == 10000
    assert fx.resolve_fx_quote(rates, '2026-09-19', 'EUR', 'USD') is None
    assert fx.resolve_fx_quote([], END, 'XYZ', 'XYZ') == dict(
        sourceCurrency='XYZ', targetCurrency='XYZ', sourcePerEur='1', targetPerEur='1',
        rateDate=None, ageDays=0, method='identity', observations=[])


@pytest.mark.parametrize('amount,source,target,expected', [
    (1, '2', '1', 1), (-1, '2', '1', -1), (1, '3', '1', 0),
    (101, '2', '1', 51), (-101, '2', '1', -51),
    (10**14, '1.25', '8', 640000000000000),
    (10**20, '0.000000000001', '999999999999', 999999999999*10**32),
    (0, '1.25', '8', 0),
])
def test_decimal_conversion_rounds_once_without_binary_float(amount, source, target, expected):
    assert fx.convert_cents(amount, source, target) == expected


@pytest.mark.parametrize('amount', [True, 1.0, '1', 10**20+1, None])
def test_invalid_amount_never_silently_coerced(amount):
    with pytest.raises(fx.FxError):
        fx.convert_cents(amount, '1', '1')


@pytest.mark.parametrize('value', ['0', '-1', '1e2', 'NaN', 'Infinity', '01', '1,20',
                                 '0.0000000000001', '1000000000000', 1.25, None])
def test_invalid_rates(value):
    with pytest.raises(fx.FxError):
        fx.rate_text(value)


@pytest.mark.parametrize('field,value', [
    ('KEY', 'EXR.M.USD.EUR.SP00.A'), ('FREQ', 'M'), ('CURRENCY_DENOM', 'USD'),
    ('EXR_TYPE', 'OTHER'), ('EXR_SUFFIX', 'E'), ('UNIT', 'CNY'), ('UNIT_MULT', '3'),
    ('OBS_STATUS', 'P'), ('TIME_PERIOD', '2026-09-19'), ('TIME_PERIOD', '2026-02-30'),
    ('CURRENCY', 'usd'), ('OBS_VALUE', '0'),
])
def test_changed_series_or_units_fail_whole_batch(field, value):
    changed = observation()
    changed[field] = value
    with pytest.raises(fx.FxError):
        fx.parse_ecb_csv(csv_body([observation('CNY', '8'), changed]), START, END, STAMP)


def test_missing_observation_is_gap_not_zero():
    missing = observation('JPY', '')
    missing['OBS_STATUS'] = 'M'
    payload = batch([observation(), missing])
    assert [r['currency'] for r in payload['rates']] == ['USD']
    with pytest.raises(fx.FxError) as error:
        batch([missing])
    assert error.value.code == 'fx_no_data'


@pytest.mark.parametrize('raw', [b'', b'\xff', b'KEY\x00,FREQ\n', b'KEY,KEY,FREQ\nx,x,D\n',
                               b'KEY,FREQ\nx,D\n'])
def test_bad_csv_rejected(raw):
    with pytest.raises(fx.FxError):
        fx.parse_ecb_csv(raw, START, END, STAMP)


def test_duplicate_and_oversized_csv_rejected(monkeypatch):
    with pytest.raises(fx.FxError):
        batch([observation(), observation()])
    monkeypatch.setattr(fx, 'MAX_ROWS', 1)
    with pytest.raises(fx.FxError):
        batch()
    monkeypatch.setattr(fx, 'MAX_BYTES', 20)
    with pytest.raises(fx.FxError):
        batch([observation()])


@pytest.mark.parametrize('start,end', [('1999-01-03', END), (END, START),
    ('2026-9-10', END), ('2026-01-01', '2027-01-09')])
def test_fixed_endpoint_validates_range(start, end):
    with pytest.raises(fx.FxError):
        fx.ecb_url(start, end)


class Response:
    def __init__(self, body=None, *, status=200, content_type='text/csv; charset=utf-8', url=None, error=None):
        self.status, self.headers = status, {'Content-Type': content_type}
        self.body, self.url, self.error = io.BytesIO(csv_body() if body is None else body), url, error
    def geturl(self):
        return self.url or fx.ecb_url(START, END)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.body.close()
    def read(self, size):
        if self.error:
            raise self.error
        return self.body.read(size)


def install_download(monkeypatch, response=None, error=None):
    seen = []
    class Opener:
        def open(self, request, timeout):
            seen.append((request, timeout))
            if error:
                raise error
            return response
    def build(handler):
        assert isinstance(handler, fx._NoRedirect)
        return Opener()
    monkeypatch.setattr(fx.urllib.request, 'build_opener', build)
    return seen


def test_download_uses_only_public_fixed_url_and_retains_body_hash(monkeypatch):
    seen = install_download(monkeypatch, Response())
    result = fx.fetch_ecb_rates(START, END)
    assert result['bodySha256'] == hashlib.sha256(csv_body()).hexdigest()
    request, timeout = seen[0]
    assert request.full_url == fx.ecb_url(START, END)
    assert request.data is None and request.get_method() == 'GET'
    assert timeout == 25
    assert set(k.lower() for k in request.headers) == {'accept', 'user-agent'}


@pytest.mark.parametrize('response', [Response(status=500), Response(content_type='text/html'),
    Response(url='https://unrelated.invalid/data'), Response(error=http.client.IncompleteRead(b'partial'))])
def test_unusable_network_response_is_sanitized(monkeypatch, response):
    install_download(monkeypatch, response)
    with pytest.raises(fx.FxError) as error:
        fx.fetch_ecb_rates(START, END)
    assert error.value.code == 'fx_unavailable'
    assert 'partial' not in str(error.value) and 'unrelated.invalid' not in str(error.value)


@pytest.mark.parametrize('error', [TimeoutError('private diagnostic'),
    urllib.error.URLError('private diagnostic'), http.client.RemoteDisconnected('private diagnostic')])
def test_network_errors_do_not_expose_raw_messages(monkeypatch, error):
    install_download(monkeypatch, error=error)
    with pytest.raises(fx.FxError) as caught:
        fx.fetch_ecb_rates(START, END)
    assert caught.value.code == 'fx_unavailable'
    assert 'private diagnostic' not in str(caught.value)


def test_network_deadline_byte_limit_and_no_data(monkeypatch):
    install_download(monkeypatch, Response(status=204))
    with pytest.raises(fx.FxError) as caught:
        fx.fetch_ecb_rates(START, END)
    assert caught.value.code == 'fx_no_data'
    install_download(monkeypatch, Response(body=b'x'*21))
    monkeypatch.setattr(fx, 'MAX_BYTES', 20)
    with pytest.raises(fx.FxError, match='过大'):
        fx.fetch_ecb_rates(START, END)
    install_download(monkeypatch, Response())
    times = iter([0, 26])
    monkeypatch.setattr(fx.time, 'monotonic', lambda: next(times))
    with pytest.raises(fx.FxError, match='超时'):
        fx.fetch_ecb_rates(START, END)


def test_future_request_and_redirect_never_issue_second_request(monkeypatch):
    seen = install_download(monkeypatch, Response())
    future = (date.today()+timedelta(days=2)).isoformat()
    with pytest.raises(fx.FxError):
        fx.fetch_ecb_rates(future, future)
    assert seen == []
    with pytest.raises(fx.FxError):
        fx._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private')
