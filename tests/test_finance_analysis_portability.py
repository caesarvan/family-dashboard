"""Real ZIP projection: own analysis only and explicit bounded public FX coverage."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest
import data_portability
from test_app import app, member
from test_data_portability import unpack


@pytest.mark.parametrize('include_shared', [False, True])
def test_analysis_export_is_owner_private_with_minimal_operations(app, include_shared):
    clients, ids = [], []
    for number in (1, 2):
        client, headers = member(app, number); clients.append((client, headers))
        response = client.post('/api/finance-accounts', headers=headers, json={
            'requestId': str(number) * 32, 'revision': 0, 'name': 'SYNTHETIC_ACCOUNT_' + str(number),
            'institution': '', 'note': '', 'kind': 'asset', 'currency': 'USD',
            'valuation': {'asOf': '2026-09-01', 'amountCents': 0}})
        assert response.status_code == 201, response.json
        ids.append(response.json['accountId'])
        response = client.put('/api/finance-analysis/accounts/' + ids[-1] + '/profile', headers=headers,
            json={'requestId': str(number + 2) * 32, 'revision': 0, 'assetClass': 'cash', 'liquidity': 'immediate'})
        assert response.status_code == 200, response.json
        response = client.post('/api/finance-analysis/accounts/' + ids[-1] + '/cashflows', headers=headers,
            json={'requestId': str(number + 4) * 32, 'revision': 0, 'date': '2026-09-10',
                  'direction': 'in', 'amountCents': 0, 'note': 'PRIVATE_FLOW_' + str(number)})
        assert response.status_code == 200, response.json
    path = Path(app.config['DATA_DIR']) / 'household.sqlite3'
    with closing(sqlite3.connect(path)) as con:
        for number, account_id in enumerate(ids, 1):
            con.execute('INSERT INTO finance_account_reviews VALUES(?,?,?,?,?,?,?)',
                        ('member' + str(number), account_id, '2026-09-01', '2026-09-18', 'context', 1, 'now'))
        for table in data_portability.ANALYSIS_TABLES:
            con.execute('ALTER TABLE ' + table + ' ADD COLUMN future_secret TEXT')
            con.execute('UPDATE ' + table + " SET future_secret='FORBIDDEN_FUTURE_FIELD'")
        con.execute("UPDATE finance_analysis_operations SET result=?", (json.dumps({'secret': 'FORBIDDEN_RESULT'}),))
        con.commit()
    for number, (client, headers) in enumerate(clients, 1):
        summary = client.get('/api/portability/summary')
        assert summary.status_code == 200
        assert summary.json['personal']['financeAnalysis'] == {'profiles': 1, 'cashflows': 1, 'reviews': 1, 'operations': 2}
        result, files = unpack(client.post('/api/portability/export', json={'includeShared': include_shared}, headers=headers))
        analysis = result['personal']['financeAnalysis']
        assert set(analysis) == {'profiles', 'cashflows', 'reviews', 'operations'}
        assert analysis['cashflows'][0]['amountCents'] == 0
        assert analysis['cashflows'][0]['note'] == 'PRIVATE_FLOW_' + str(number)
        assert all(row['accountId'] == ids[number - 1] for rows in analysis.values() for row in rows)
        assert all(set(row) == {'operation', 'accountId', 'completedAt'} for row in analysis['operations'])
        assert 'financeAnalysis' not in result.get('shared', {})
        combined = b''.join(files.values())
        for sentinel in ('FORBIDDEN_', ids[2 - number], 'PRIVATE_FLOW_' + str(3 - number)):
            assert sentinel.encode() not in combined
        assert result['coverage']['completeFinancialCoverage'] is False


def test_empty_analysis_and_bounded_public_fx_are_separate_and_explicit(app, monkeypatch):
    monkeypatch.setattr(data_portability, 'MAX_REFERENCE_FX_ROWS', 2)
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')) as con:
        for number in range(3):
            con.execute('INSERT INTO finance_fx_rates VALUES(?,?,?,?,?,?,?,?)',
                (str(number) * 64, '2026-09-1' + str(number), 'USD', '1.2',
                 'https://data-api.ecb.europa.eu/', 'a' * 64, 'now', 'now'))
        con.execute('ALTER TABLE finance_fx_rates ADD COLUMN future_secret TEXT')
        con.execute("UPDATE finance_fx_rates SET future_secret='FORBIDDEN_PUBLIC_CACHE_FIELD'")
        con.commit()
    client, headers = member(app)
    result, files = unpack(client.post('/api/portability/export', json={}, headers=headers))
    assert result['personal']['financeAnalysis'] == {'profiles': [], 'cashflows': [], 'reviews': [], 'operations': []}
    assert len(result['referenceData']['financeFxRates']) == 2
    assert [r['rateDate'] for r in result['referenceData']['financeFxRates']] == ['2026-09-12', '2026-09-11']
    coverage = result['coverage']['financeFxRates']
    assert coverage['totalRows'] == 3 and coverage['includedRows'] == coverage['rowLimit'] == 2
    assert coverage['complete'] is False and coverage['historicalReportReconstruction'] is False
    assert 'financeFxRates' not in result['personal']
    assert b'FORBIDDEN_PUBLIC_CACHE_FIELD' not in b''.join(files.values())
