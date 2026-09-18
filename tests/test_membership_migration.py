"""Historical real Flask/SQLite startup and readonly migration counterexamples.

Requires fixed Git objects locally (never fetched). All databases are synthetic.
"""
import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from deploy import membership_migration as check
from deploy.git_blobs import read_git_blobs

ROOT = Path(__file__).resolve().parents[1]
BASE = '8e6a9954aec21ac69cf0c9d33817f631c4a789f4'
PRIVATE = 'SYNTHETIC_PRIVATE_SENTINEL_NOT_FOR_REPORT'
STARTUP = r'''
import json, socket, sqlite3, sys
from pathlib import Path
def denied(*args, **kwargs): raise AssertionError('Network forbidden')
socket.socket.connect = denied
from app import create_app
root = Path(sys.argv[1])
app = create_app({'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'migration-synthetic-secret',
 'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
 'MEMBER1_PASSWORD': 'synthetic-password-one', 'MEMBER2_PASSWORD': 'synthetic-password-two',
 'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '', 'MICROSOFT_CLIENT_ID': '', 'GOOGLE_CLIENT_ID': ''})
platform = app.extensions['household_platform']
if sys.argv[2] == 'seed':
 c = app.test_client()
 assert c.post('/api/login', json={'username':'member1','password':'synthetic-password-one'}).status_code == 200
 h = {'X-CSRF-Token':c.get('/api/me').json['csrf']}
 assert c.post('/api/items/tasks', json={'title':'SYNTHETIC_PRIVATE_SENTINEL_NOT_FOR_REPORT'}, headers=h).status_code == 201
 invite = c.post('/api/spaces/invitations', json={}, headers=h)
 assert invite.status_code == 201
 response = app.test_client().post('/api/spaces/redeem', json={'invitation':invite.json['invitation'],
  'name':'Synthetic second household','slug':'migration-second',
  'MEMBER1_PASSWORD':'synthetic-password-three','MEMBER2_PASSWORD':'synthetic-password-four'})
 assert response.status_code == 201, response.status_code
for household in platform.households():
 if household['id'] != 'default': platform.child(household)
if sys.argv[2] == 'seed':
 for path in root.rglob('household.sqlite3'):
  with sqlite3.connect(path) as con:
   con.execute("UPDATE users SET household_role='member' WHERE id='member2'")
   con.execute("INSERT INTO private_finance(owner,data) VALUES('member1',?)", ('{"synthetic":"SYNTHETIC_PRIVATE_SENTINEL_NOT_FOR_REPORT","zero":0,"unknown":null}',))
   con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES('member1','synthetic','retained','2026-09-18')")
print(json.dumps({'started':True,'households':len(platform.households()),'mode':sys.argv[2]}))
'''


def materialize(target, commit):
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    raw = subprocess.check_output(['git', '--no-replace-objects', 'ls-tree', '-r', '--name-only', commit], cwd=ROOT, env=env)
    names = [n for n in raw.decode().splitlines() if n.endswith('.py') and '/' not in n]
    blobs = read_git_blobs(ROOT, commit, names)
    target.mkdir()
    for name, data in blobs.items():
        (target / name).write_bytes(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in blobs.items()}


def startup(source, data, mode):
    env = {k: v for k, v in os.environ.items() if k.upper() not in {
        'SECRET_KEY', 'DATA_DIR', 'OPENAI_API_KEY', 'NVIDIA_API_KEY', 'GOOGLE_CLIENT_SECRET',
        'MICROSOFT_CLIENT_SECRET', 'PYTHONPATH'}}
    p = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', STARTUP, str(data), mode], cwd=source,
                       env=env, capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def clone_databases(source, target):
    target.mkdir()
    for path in sorted(source.rglob('*.sqlite3')):
        out = target / path.relative_to(source)
        out.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(out)) as dst:
            src.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')


@pytest.fixture(scope='module')
def historical(tmp_path_factory):
    root = tmp_path_factory.mktemp('membership-migration-historical')
    source = root / 'old-source'
    old_hashes = materialize(source, BASE)
    assert startup(source, root / 'seed', 'seed') == {'started': True, 'households': 2, 'mode': 'seed'}
    clone_databases(root / 'seed', root / 'before')
    clone_databases(root / 'before', root / 'after')
    future = root / 'new-source'
    new_hashes = materialize(future, check.SOURCE_PINS['wiringCommit'])
    for name, prefix in [('household_memberships.py', 'domain'), ('personal_accounts.py', 'personal')]:
        data = read_git_blobs(ROOT, check.SOURCE_PINS[prefix + 'Commit'], [name])[name]
        assert hashlib.sha256(data).hexdigest() == check.SOURCE_PINS[prefix + 'Sha256']
        (future / name).write_bytes(data)
        new_hashes[name] = hashlib.sha256(data).hexdigest()
    assert startup(future, root / 'after', 'upgrade') == {'started': True, 'households': 2, 'mode': 'upgrade'}
    clone_databases(root / 'after', root / 'upgraded')
    value = {'root': root, 'before': root / 'before', 'after': root / 'upgraded', 'newSource': future,
             'sources': {'baseline': old_hashes, 'candidate': new_hashes}}
    (root / 'startup-sources.json').write_text(json.dumps(value['sources'], sort_keys=True, indent=2), encoding='utf-8')
    return value


@pytest.fixture
def pair(historical, tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    clone_databases(historical['before'], before)
    clone_databases(historical['after'], after)
    return before, after


def alter(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.execute(sql)
        con.commit()


def test_exact_fixed_ddl_literals(historical):
    for name, variable, expected in [('household_memberships.py', 'SCHEMA_STATEMENTS', check.HOUSEHOLD_SQL),
                                     ('personal_accounts.py', 'SCHEMA', check.PLATFORM_SQL)]:
        tree = ast.parse((historical['newSource'] / name).read_text(encoding='utf-8'))
        values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == variable for t in n.targets)]
        assert values == [expected]


def test_actual_two_household_upgrade_and_restart(historical, tmp_path):
    for path in historical['before'].rglob('household.sqlite3'):
        result = check.verify_household(path, historical['after'] / path.relative_to(historical['before']))
        assert result['verified'] and result['beforeTableCount'] == 58 and result['afterTableCount'] == 61
        assert result['after']['tables']['household_memberships']['count'] == 2
    assert check.verify_platform(historical['before'] / 'platform.sqlite3', historical['after'] / 'platform.sqlite3')['afterTableCount'] == 9
    clone_databases(historical['after'], tmp_path / 'restarted')
    assert startup(historical['newSource'], tmp_path / 'restarted', 'restart')['households'] == 2
    for path in historical['after'].rglob('*.sqlite3'):
        old = check._summary(check._read(path))
        new = check._summary(check._read(tmp_path / 'restarted' / path.relative_to(historical['after'])))
        assert old | {'fileSha256': None} == new | {'fileSha256': None}


@pytest.mark.parametrize('sql', [
    "UPDATE users SET password='replacement' WHERE id='member1'",
    "UPDATE users SET household_role='admin' WHERE id='member2'",
    "UPDATE users SET auth_version=auth_version+1 WHERE id='member1'",
    "UPDATE private_finance SET owner='member2'",
    "UPDATE private_finance SET data='{}'",
    "UPDATE audit SET target='changed'",
    "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
    "UPDATE settings SET revision=revision+1 WHERE id='meta'",
    "DELETE FROM settings WHERE id='finance'",
    "INSERT INTO settings(id,data) VALUES('unexpected','secret')",
    "UPDATE settings SET data='{}' WHERE id='membership_schema_v1'",
    "UPDATE settings SET revision=2 WHERE id='membership_schema_v1'",
    "UPDATE member_sessions SET personal_identity='unexpected'",
    "UPDATE member_sessions SET revoked_at=1",
    "DELETE FROM household_memberships WHERE member_id='member2'",
    "UPDATE household_memberships SET account_id='bound' WHERE member_id='member1'",
    "UPDATE household_memberships SET state='removed' WHERE member_id='member1'",
    "UPDATE household_memberships SET revision=2 WHERE member_id='member1'",
    "UPDATE household_memberships SET id='not-stable-hex' WHERE member_id='member1'",
    "UPDATE household_memberships SET updated_at=created_at+1 WHERE member_id='member1'",
    "INSERT INTO member_invitations VALUES('id','hash','member1',1,'pending',1,1,2,NULL,NULL,NULL)",
    "INSERT INTO membership_operations VALUES('member:member1','request','kind','digest','member1','{}',1)",
    "CREATE TABLE extra(value TEXT)",
    "CREATE INDEX extra_index ON users(name)",
    "DROP INDEX member_sessions_owner",
    "CREATE TRIGGER unexpected AFTER UPDATE ON users BEGIN SELECT 1; END",
    "ALTER TABLE users ADD COLUMN accidental TEXT",
    "DROP TABLE hub_imports",
    "PRAGMA user_version=1",
    "PRAGMA application_id=123",
])
def test_household_fail_closed(pair, sql):
    before, after = pair
    alter(after / 'household.sqlite3', sql)
    with pytest.raises(check.MigrationCheckError):
        check.verify_household(before / 'household.sqlite3', after / 'household.sqlite3')


@pytest.mark.parametrize('sql', [
    "UPDATE households SET name='replacement' WHERE id='default'",
    "DELETE FROM household_invitations",
    "DROP TABLE household_invitations",
    "INSERT INTO personal_accounts VALUES('a','login','hash',1,1)",
    "INSERT INTO personal_limits VALUES('limiter',1,1)",
    "CREATE INDEX extra ON households(name)",
    "ALTER TABLE personal_limits ADD COLUMN extra TEXT",
    "DROP TABLE account_operations",
    "PRAGMA user_version=0",
    "PRAGMA user_version=2",
])
def test_platform_fail_closed(pair, sql):
    before, after = pair
    alter(after / 'platform.sqlite3', sql)
    with pytest.raises(check.MigrationCheckError):
        check.verify_platform(before / 'platform.sqlite3', after / 'platform.sqlite3')


@pytest.mark.parametrize('which,sql', [
    ('household', 'DROP TABLE hub_imports'), ('household', 'CREATE TABLE future(value TEXT)'),
    ('platform', 'DROP TABLE household_invitations'), ('platform', 'PRAGMA user_version=1'),
])
def test_bad_baseline_refused(pair, which, sql):
    before, after = pair
    filename = 'household.sqlite3' if which == 'household' else 'platform.sqlite3'
    alter(before / filename, sql)
    with pytest.raises(check.MigrationCheckError):
        getattr(check, 'verify_' + which)(before / filename, after / filename)


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_sidecar_refused(pair, suffix):
    before, after = pair
    Path(str(before / 'household.sqlite3') + suffix).touch()
    with pytest.raises(check.MigrationCheckError, match='sqlite_sidecar_present'):
        check.verify_household(before / 'household.sqlite3', after / 'household.sqlite3')


def test_missing_same_corrupt_and_changed_inputs(pair, monkeypatch):
    before, after = pair
    original = before / 'household.sqlite3'
    with pytest.raises(check.MigrationCheckError, match='missing_input'):
        check.verify_household(before / 'absent.sqlite3', original)
    assert not (before / 'absent.sqlite3').exists()
    with pytest.raises(check.MigrationCheckError, match='same_input_file'):
        check.verify_household(original, original)
    bad = after / 'bad.sqlite3'
    bad.write_bytes(b'not sqlite')
    with pytest.raises(check.MigrationCheckError):
        check.verify_household(original, bad)
    actual, calls = check.file_digest, []
    def changed(path):
        calls.append(path)
        return '0' * 64 if len(calls) == 2 else actual(path)
    monkeypatch.setattr(check, 'file_digest', changed)
    with pytest.raises(check.MigrationCheckError, match='input_changed_during_read'):
        check.verify_household(original, after / 'household.sqlite3')


def test_cli_readonly_private_output_and_exclusive_failure(pair, tmp_path):
    before, after = pair
    args = []
    for path in sorted(before.rglob('household.sqlite3')):
        args += ['--household-pair', str(path), str(after / path.relative_to(before))]
    args += ['--platform-pair', str(before / 'platform.sqlite3'), str(after / 'platform.sqlite3')]
    files = {str(p): check.file_digest(p) for root in pair for p in root.rglob('*') if p.is_file()}
    output = tmp_path / 'result.json'
    assert check.main([*args, '--output', str(output)]) == 0
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['verified'] and len(result['households']) == 2
    assert result['scope'] == 'explicit_pairs_not_registry_completeness'
    text = output.read_text(encoding='utf-8')
    assert all(v not in text for v in (PRIVATE, 'synthetic-password', 'replacement', 'member1', 'member2', str(before)))
    assert files == {str(p): check.file_digest(p) for root in pair for p in root.rglob('*') if p.is_file()}
    saved = output.read_bytes()
    with pytest.raises(SystemExit, match='output_not_new'):
        check.main([*args, '--output', str(output)])
    assert output.read_bytes() == saved
    alter(after / 'household.sqlite3', "UPDATE users SET name='private changed'")
    failure = tmp_path / 'failure.json'
    assert check.main([*args, '--output', str(failure)]) == 1
    assert json.loads(failure.read_text()) == {'verified': False, 'readOnly': True, 'code': 'old_rows_or_sequence_changed'}
    assert 'private changed' not in failure.read_text()


@pytest.mark.parametrize('output_name', ['missing.sqlite3', 'household.sqlite3-wal'])
def test_cli_never_writes_input_directory(pair, output_name):
    before, after = pair
    output = before / output_name
    args = ['--household-pair', str(before / 'missing.sqlite3'), str(after / 'household.sqlite3'),
            '--platform-pair', str(before / 'platform.sqlite3'), str(after / 'platform.sqlite3'),
            '--output', str(output)]
    with pytest.raises(SystemExit, match='output_inside_input_directory'):
        check.main(args)
    assert not output.exists()


def test_new_household_ddl_must_be_exact(pair):
    before, after = pair
    alter(after / 'household.sqlite3', 'ALTER TABLE household_memberships ADD COLUMN extra TEXT')
    with pytest.raises(check.MigrationCheckError, match='schema_delta_not_exact'):
        check.verify_household(before / 'household.sqlite3', after / 'household.sqlite3')
