export type SyncProvider = 'microsoft' | 'google';
export type SyncAuthResult = { status: 'connected' | 'error'; reason?: string };

const reasons: Record<string, string> = {
  not_configured: '这个平台尚未完成配置。请先使用家庭密码登录。',
  unbound_account: '这个账户尚未绑定。请先用家庭密码登录，再连接自己的账户。',
  already_bound: '这个账户已绑定到其他成员，请选择自己的账户。',
  provider_denied: '本次授权未完成，请在服务商页面确认所需权限。',
  invalid_state: '这次授权已过期或页面状态已改变，请重新连接。',
  bind_session_changed: '授权期间登录状态已变化，请从当前成员账户重新连接。',
  session_changed: '授权期间登录状态已变化，请从当前成员账户重新连接。',
  account_limit: '已达到每位成员最多 4 个账户的限制，请先管理已有连接。',
  missing_refresh_token: '未取得持续同步所需的授权，请重新连接并完成授权。',
  insufficient_permissions: '缺少日历或清单权限，请重新连接并允许这些权限。',
  invalid_client: '平台应用配置需要维护，请稍后重试或联系管理员。',
  invalid_grant: '这次授权已失效，请重新开始连接。',
  token_failed: '暂时未能完成账户授权，请稍后重新连接。',
  identity_failed: '暂时无法核对平台账户身份，请稍后重新连接。',
  provider_error: '账户授权未完成，请稍后重试。',
};

/** OAuth query text is untrusted; display only fixed local messages. */
export function readSyncAuthResult(auth: unknown, reason: unknown): SyncAuthResult | undefined {
  if (auth === 'connected') return { status: 'connected' };
  if (auth !== 'error') return undefined;
  return { status: 'error', reason: typeof reason === 'string' && Object.hasOwn(reasons, reason) ? reason : 'provider_error' };
}

export function syncAuthMessage(result: SyncAuthResult): string {
  if (result.status === 'connected') return '请核对下方账户，并选择要同步和共享的日历、清单。';
  return typeof result.reason === 'string' && Object.hasOwn(reasons, result.reason) ? reasons[result.reason] : reasons.provider_error;
}

/** Bind authorization to the exact provider endpoint and this app's callback. */
export function syncAuthorizeUrl(raw: unknown, provider: SyncProvider, origin: string): string {
  if (typeof raw !== 'string' || raw.length > 16384 || /[\s\\\u0000-\u001f\u007f]/.test(raw)) return '';
  try {
    const url = new URL(raw), app = new URL(origin);
    const endpoint = provider === 'microsoft'
      ? ['login.microsoftonline.com', '/common/oauth2/v2.0/authorize']
      : provider === 'google' ? ['accounts.google.com', '/o/oauth2/v2/auth'] : null;
    if (!endpoint || url.protocol !== 'https:' || url.username || url.password || url.hash || url.port
      || url.hostname !== endpoint[0] || url.pathname !== endpoint[1]
      || !['http:', 'https:'].includes(app.protocol) || app.username || app.password
      || app.pathname !== '/' || app.search || app.hash) return '';
    const params = url.searchParams;
    for (const key of ['client_id', 'redirect_uri', 'response_type', 'state', 'code_challenge', 'code_challenge_method']) {
      if (params.getAll(key).length !== 1) return '';
    }
    if (!params.get('client_id') || params.get('response_type') !== 'code'
      || params.get('redirect_uri') !== `${app.origin}/auth/${provider}/callback`
      || params.get('code_challenge_method') !== 'S256'
      || !/^[A-Za-z0-9_-]{32,200}$/.test(params.get('state') || '')
      || !/^[A-Za-z0-9_-]{43}$/.test(params.get('code_challenge') || '')) return '';
    return url.href;
  } catch { return ''; }
}
