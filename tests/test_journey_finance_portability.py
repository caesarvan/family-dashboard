"""Owner-only personal ZIP: historical IDs, no token/digest/private neighbor."""
import pytest
from test_app import app, member
from test_data_portability import unpack
from test_journey_finance import setup, create, database, offline


@pytest.mark.parametrize('shared', [False, True])
def test_export_allocation_and_receipt_allowlists_and_other_owner_absence(app, shared):
    c, h, j, p = setup(app)
    receipt, original = create(c, h, j, p)
    with database(app) as con:
        before = {t: [tuple(r) for r in con.execute('SELECT * FROM '+t)] for t in ('hub_journey_allocations', 'hub_journey_allocation_operations')}
        private_digest = con.execute('SELECT source_digest FROM hub_journey_allocations').fetchone()[0]
    data, files = unpack(c.post('/api/portability/export', json={'includeShared': shared}, headers=h))
    value = data['personal']['journeyAllocations']
    assert set(value['allocations'][0]) == {'id', 'revision', 'journeyId', 'tripId', 'paymentId', 'amountCents', 'status',
                                           'acceptedNetCents', 'acceptedRefundedCents', 'createdAt', 'updatedAt'}
    assert value['allocations'][0]['id'] == receipt['allocationId']
    assert value['operations'] == [{k: v for k, v in receipt.items() if k != 'requestId'}]
    assert data['coverage']['journeyAllocations'] == 'owner_allocations_and_minimal_operations_without_preview_or_source_digests'
    joined = b''.join(files.values())
    for secret in (original['previewToken'], original['requestId'], private_digest): assert secret.encode() not in joined
    assert 'journeyAllocations' not in data.get('shared', {})
    other, oh = member(app, 2)
    theirs, otherfiles = unpack(other.post('/api/portability/export', json={'includeShared': shared}, headers=oh))
    assert theirs['personal']['journeyAllocations'] == {'allocations': [], 'operations': []}
    assert receipt['allocationId'].encode() not in b''.join(otherfiles.values())
    with database(app) as con:
        assert before == {t: [tuple(r) for r in con.execute('SELECT * FROM '+t)] for t in before}
