import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readSyncAuthResult, syncAuthMessage, syncAuthorizeUrl } from '../frontend/src/lib/authNavigation.ts';

const origin = 'https://home.example.test';
function authorization(provider) {
  const url = new URL(provider === 'microsoft' ? 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize' : 'https://accounts.google.com/o/oauth2/v2/auth');
  url.search = new URLSearchParams({ client_id: 'synthetic-public-client-id', redirect_uri: `${origin}/auth/${provider}/callback`, response_type: 'code', state: 's'.repeat(43), code_challenge: 'c'.repeat(43), code_challenge_method: 'S256' });
  return url;
}

test('both real provider endpoints require this application callback and PKCE', () => {
  for (const provider of ['microsoft', 'google']) {
    const url = authorization(provider);
    assert.equal(syncAuthorizeUrl(url.href, provider, origin), url.href);
    assert.equal(syncAuthorizeUrl(url.href, provider === 'google' ? 'microsoft' : 'google', origin), '');
    for (const [key, value] of [['redirect_uri', 'https://elsewhere.invalid/auth'], ['response_type', 'token'], ['state', ''], ['code_challenge_method', 'plain'], ['code_challenge', 'short']]) {
      const changed = new URL(url); changed.searchParams.set(key, value);
      assert.equal(syncAuthorizeUrl(changed.href, provider, origin), '');
    }
    const repeated = new URL(url); repeated.searchParams.append('redirect_uri', url.searchParams.get('redirect_uri'));
    assert.equal(syncAuthorizeUrl(repeated.href, provider, origin), '');
  }
});

test('foreign origins, credentials, alternate paths and malformed URLs never navigate', () => {
  const raw = authorization('google').href;
  for (const changed of [raw.replace('accounts.google.com', 'accounts.google.com.evil.invalid'), raw.replace('https:', 'http:'), raw.replace('https://', 'https://user:password@'), raw.replace('/o/oauth2/v2/auth', '/other'), raw + '#fragment', raw + '\\path', raw + '\n', '//accounts.google.com/o/oauth2/v2/auth', 'javascript:alert(1)']) {
    assert.equal(syncAuthorizeUrl(changed, 'google', origin), '');
  }
  for (const app of ['', 'not-a-url', origin + '/other', origin + '?next=elsewhere', 'file:///']) assert.equal(syncAuthorizeUrl(raw, 'google', app), '');
});

test('OAuth result text uses fixed messages, and callback status alone proves no sync success', () => {
  for (const raw of ['SECRET', '__proto__', 'constructor', '<script>', ['provider_denied'], undefined]) {
    const result = readSyncAuthResult('error', raw);
    assert.deepEqual(result, { status: 'error', reason: 'provider_error' });
    assert.equal(syncAuthMessage(result), '账户授权未完成，请稍后重试。');
  }
  assert.match(syncAuthMessage(readSyncAuthResult('error', 'unbound_account')), /家庭密码/);
  assert.match(syncAuthMessage(readSyncAuthResult('connected', 'SECRET')), /请核对/);
  assert.equal(readSyncAuthResult(['connected'], ''), undefined);
  assert.equal(readSyncAuthResult('signed-in', ''), undefined);
});
