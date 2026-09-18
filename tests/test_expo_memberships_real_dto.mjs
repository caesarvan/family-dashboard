// Real fixed household-domain functions + temporary app database; no HTTP/browser claim.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { registerHooks } from 'node:module';
registerHooks({ resolve(specifier, context, next) { return next(specifier === './personalAccounts' ? './personalAccounts.ts' : specifier, context); } });
const m = await import('../frontend/src/lib/memberships.ts');
const source = process.env.MEMBERSHIP_DOMAIN_ROOT;
const python = process.env.MEMBERSHIP_TEST_PYTHON;
test('actual create/list/replay/revoke/expired/invalid invitation DTOs decode without fabricated success', () => {
  assert(source && python, 'Set MEMBERSHIP_DOMAIN_ROOT to fixed 754d2e15 tree and MEMBERSHIP_TEST_PYTHON to the project venv.');
  const result = spawnSync(python, ['-B', '-X', 'utf8', '-c', String.raw`
import contextlib, hashlib, json, pathlib, socket, sqlite3, subprocess, sys, tempfile
root=pathlib.Path(sys.argv[1]); sys.path.insert(0,str(root))
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()=='754d2e1552c8953b9d490df246d1328bdf3abf43'
before=hashlib.sha256((root/'household_memberships.py').read_bytes()).hexdigest()
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Network forbidden'))
from app import create_app
import household_memberships as domain
with tempfile.TemporaryDirectory(prefix='membership-client-dto-') as tmp:
    app=create_app({'TESTING':True,'DATA_DIR':tmp,'SECRET_KEY':'synthetic-membership-ui-key','SESSION_COOKIE_SECURE':False,
                    'MEMBER1_PASSWORD':'synthetic-password-111','MEMBER2_PASSWORD':'synthetic-password-222'})
    with contextlib.closing(sqlite3.connect(pathlib.Path(tmp)/'household.sqlite3')) as con:
        con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON'); con.execute('BEGIN IMMEDIATE')
        domain.schema_initialize(con)
        args=dict(household_id='default',actor_member_id='member1',expected_auth_version=1,request_id='1'*32,intent_digest='a'*64,now=1700000000)
        created=domain.create_invitation(con,**args)
        listed=domain.list_invitations(con,'default','member1',now=1700000001)
        replay=domain.create_invitation(con,**args)
        operation=domain.member_operation(con,member_id='member1',request_id='1'*32)
        revoked=domain.revoke_invitation(con,household_id='default',actor_member_id='member1',invitation_id=created['invitation']['id'],
            expected_revision=1,request_id='2'*32,intent_digest='b'*64,now=1700000002)
        second=domain.create_invitation(con,**(args|{'request_id':'3'*32,'intent_digest':'c'*64}))
        expired=domain.list_invitations(con,'default','member1',now=1700000000+domain.INVITATION_TTL+1)
        con.execute("UPDATE users SET auth_version=auth_version+1 WHERE id='member1'")
        invalid=domain.list_invitations(con,'default','member1',now=1700000001)
        con.commit()
assert hashlib.sha256((root/'household_memberships.py').read_bytes()).hexdigest()==before
print(json.dumps({'created':created,'listed':listed,'replay':replay,'operation':operation,'revoked':revoked,'expired':expired,'invalid':invalid,'sourceSha256':before}))
`, source], { encoding: 'utf8', timeout: 30000, windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  const raw = JSON.parse(result.stdout);
  const created = m.readInvitationCreated(raw.created);
  assert.equal(created.invitation.state, 'pending'); assert(created.token);
  assert.equal(m.readInvitations({ invitations: raw.listed })[0].state, 'pending');
  assert.equal(m.readInvitationCreated(raw.replay, true).token, null);
  assert.equal(m.readMembershipResult('invite', raw.operation.result, true).invitation.state, 'pending');
  assert.equal(m.readMembershipResult('revoke', raw.revoked).invitation.state, 'revoked');
  assert(m.readInvitations({ invitations: raw.expired }).some(v => v.state === 'expired'));
  assert(m.readInvitations({ invitations: raw.invalid }).some(v => v.state === 'invalid'));
  assert.match(raw.sourceSha256, /^[a-f0-9]{64}$/);
});
