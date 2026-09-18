"""Synthetic real Flask/cookie bridge for the focused Node recovery contract."""
import json
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sys
import subprocess
import tempfile

source = Path(os.environ.get('MEMBERSHIP_RECOVERY_SOURCE', Path(__file__).resolve().parents[1])).resolve()
if os.environ.get('MEMBERSHIP_RECOVERY_SOURCE'):
    expected = os.environ['MEMBERSHIP_RECOVERY_HEAD']
    assert len(expected) == 40 and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == expected
sys.path[:0] = [str(source), str(source / 'tests')]
from app import create_app
from test_membership_integration import legacy, register_old, post, invite, join, switch, PERSONAL_PASSWORD, PASSWORD

socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network forbidden'))
guard_paths = ['app.py', 'household_spaces.py', 'membership_http.py', 'membership_storage.py',
               'personal_accounts.py', 'household_memberships.py', 'member_sessions.py', 'tests/test_membership_integration.py']
before = {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in guard_paths}

with tempfile.TemporaryDirectory(prefix='membership-ui-recovery-') as temporary:
    app = create_app({'TESTING': True, 'DATA_DIR': temporary, 'SECRET_KEY': 'recovery-ui-test-key',
                      'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD})
    client = legacy(app)
    first = register_old(client, 'recovery.account')
    invitation = post(client, '/api/spaces/invitations', {}, member=True, expected=201)
    other = app.test_client()
    created = post(other, '/api/spaces/redeem', {'invitation': invitation['invitation'], 'name': 'Recovery target',
        'slug': 'recovery-target', 'MEMBER1_PASSWORD': PASSWORD, 'MEMBER2_PASSWORD': PASSWORD}, expected=201)
    assert other.get(created['entry']).status_code == 303
    legacy(app, client=other)
    second = join(client, invite(other)['token'], slug='recovery-target')
    switch(client, first)
    post(client, '/api/account/logout', {'requestId': secrets.token_hex(16)}, account=True)
    mode = sys.argv[1]
    missing = None
    if mode == 'invalid_route':
        client.set_cookie('household_space', 'invalid-signed-route')
    elif mode == 'missing_route':
        client.set_cookie('household_space', app.extensions['household_platform'].signer.dumps('f' * 24))
    elif mode == 'missing_default':
        missing = Path(temporary) / 'household.sqlite3'
        missing.rename(missing.with_suffix('.unavailable'))
    elif mode == 'missing_child':
        client.set_cookie('household_space', app.extensions['household_platform'].signer.dumps(second['householdId']))
        missing = Path(temporary) / 'spaces' / second['householdId'] / 'household.sqlite3'
        missing.rename(missing.with_suffix('.unavailable'))
    else:
        raise AssertionError(mode)
    print(json.dumps({'ready': True, 'login': 'recovery.account', 'password': PERSONAL_PASSWORD,
                      'target': first if mode == 'missing_child' else second}), flush=True)
    for line in sys.stdin:
        command = json.loads(line)
        if command.get('invalidateRoute'):
            client.set_cookie('household_space', 'invalid-signed-route')
            print(json.dumps({'invalidated': True}), flush=True)
            continue
        if command.get('close'):
            if missing is not None:
                assert not missing.exists(), 'Recovery must not recreate unavailable household storage'
            assert before == {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in guard_paths}
            break
        response = client.open(command['path'], method=command['method'], data=command.get('body'), headers=command.get('headers', {}))
        print(json.dumps({'status': response.status_code, 'body': response.get_data(as_text=True),
                          'contentType': response.content_type}), flush=True)
