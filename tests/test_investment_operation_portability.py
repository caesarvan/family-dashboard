"""Owner-scoped durable operation export; synthetic records, no network."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from test_app import app, member
from test_data_portability import unpack


@pytest.mark.parametrize('include_shared', [False, True])
def test_operation_export_whitelists_business_results_for_each_member(app, include_shared):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')) as con:
        for uid in ('member1', 'member2'):
            result = {'id': uid + '-record', 'revision': 2, 'name': uid + '_PRIVATE_HOLDING',
                'institution': uid + '_PRIVATE_INSTITUTION', 'assetType': '基金', 'currency': 'USD',
                'quantity': '1.20', 'costCents': 12500, 'valueCents': None, 'asOf': '2026-09-17',
                'note': uid + '_PRIVATE_NOTE', 'valuationSource': 'manual', 'visibility': 'private',
                'futureSecret': 'FORBIDDEN_FUTURE_EXTENSION'}
            con.execute('INSERT INTO hub_investment_operations VALUES(?,?,?,?,?,?,?)',
                (uid, 'a' * 32, 'update', result['id'], 'FORBIDDEN_DIGEST_' + uid, json.dumps(result), '2026-09-17'))
            con.execute('INSERT INTO hub_investment_operations VALUES(?,?,?,?,?,?,?)',
                (uid, 'b' * 32, 'delete', result['id'], 'FORBIDDEN_DELETE_DIGEST',
                 json.dumps({'deleted': True, 'name': 'FORBIDDEN_DELETED_EXTENSION'}), '2026-09-18'))
        con.commit()
        before = con.execute('SELECT * FROM hub_investment_operations ORDER BY owner,request_id').fetchall()
    for number in (1, 2):
        client, headers = member(app, number)
        snapshot, files = unpack(client.post('/api/portability/export', json={'includeShared': include_shared}, headers=headers))
        rows = snapshot['personal']['investmentOperations']
        assert len(rows) == 2
        assert set(rows[0]) == {'requestId', 'kind', 'recordId', 'result', 'completedAt'}
        assert rows[0]['result']['name'] == f'member{number}_PRIVATE_HOLDING'
        assert rows[0]['result']['valueCents'] is None
        assert rows[1]['result'] == {'deleted': True}
        joined = b''.join(files.values())
        assert b'FORBIDDEN_' not in joined
        assert f'member{3-number}_PRIVATE'.encode() not in joined
        assert 'investmentOperations' not in snapshot.get('shared', {})
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3')) as con:
        assert con.execute('SELECT * FROM hub_investment_operations ORDER BY owner,request_id').fetchall() == before
