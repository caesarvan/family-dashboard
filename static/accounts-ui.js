/* Account passwords and authorization stay on the provider's own website. */
'use strict';
const accountProviderName = id => id === 'microsoft' ? 'Microsoft' : id === 'google' ? 'Google' : '云账户';
const accountSourceKey = source => source.kind + ':' + (source.remoteId ?? source.id);
/* Return intents contain identifiers only. CSRF is compared in memory and is
 * never serialized. A full-page return starts a fresh selection, not a session
 * continuation: auth_version alone cannot identify a logout/login cycle. */
window.AccountsReturn = (() => {
  const key = 'family-dashboard.connection-return.v1', ttl = 10 * 60 * 1000;
  let current = null, generation = 0;
  const validId = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value);
  const stale = () => new Error('登录或页面状态已改变，请重新打开连接入口。');
  const sessionChanged = () => Object.assign(stale(), {connectionSessionChanged:true});
  const identity = actor => actor?.role === 'member' ? JSON.stringify([actor.householdId || 'default', actor.id, actor.auth_version]) : '';
  const same = context => !!context && canEdit() && identity(user) === context.identity && csrf === context.csrf;
  function read() { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_) { return null; } }
  function remove(flowId) { try { if (!flowId || read()?.flowId === flowId) sessionStorage.removeItem(key); } catch (_) {} }
  function clear(expected) {
    if (expected && current !== expected) return;
    const previous = current; current = null; generation++;
    remove(expected ? previous?.flowId : undefined);
  }
  async function capture() {
    const context = {identity: identity(user), csrf};
    if (!same(context)) throw sessionChanged();
    await verify(context); return context;
  }
  async function verify(context) {
    if (!same(context)) throw sessionChanged();
    const me = await api('/me');
    if (!same(context) || identity(me.user) !== context.identity || me.csrf !== context.csrf) throw sessionChanged();
    return me.user;
  }
  function target(value) {
    // Configuration has no publishing target and can never select records implicitly.
    if (value?.kind === 'task-setup' && Object.keys(value).length === 1) return {kind:'task-setup'};
    if (!value || !['calendar', 'tasks'].includes(value.kind)) throw stale();
    if (validId(value.journeyId)) return {kind:value.kind, journeyId:value.journeyId};
    if (value.kind === 'tasks' && Array.isArray(value.entityIds) && value.entityIds.length > 0 && value.entityIds.length <= 100 && value.entityIds.every(validId) && new Set(value.entityIds).size === value.entityIds.length) return {kind:'tasks', entityIds:[...value.entityIds]};
    throw new Error('请先添加或选择待办，再连接账户来源。');
  }
  async function recheck(flow) {
    await verify(flow.context);
    if (current !== flow) throw stale();
    const t = flow.target;
    if (t.kind === 'task-setup') return; // Identity-only configuration, no publication API.
    const path = t.kind === 'calendar' ? '/calendar-publish/journeys/' + encodeURIComponent(t.journeyId)
      : '/task-publish/state?' + new URLSearchParams(t.journeyId ? {journeyId:t.journeyId} : {entityIds:t.entityIds.join(',')});
    await api(path); // Read the original records in the current household; cache no content.
    await verify(flow.context);
    if (current !== flow) throw stale();
  }
  async function begin(value, context) {
    const origin = document.querySelector('#dialog .dialog-content');
    const selected = target(value); clear(); const ticket = generation;
    context = context || await capture(); await verify(context);
    if (ticket !== generation) throw stale();
    const flow = {target:selected, context, flowId:crypto.randomUUID(), restored:false}; current = flow;
    try {
      await recheck(flow);
      if (!origin?.isConnected || !document.querySelector('#dialog')?.open) throw stale();
      await accountsModal();
    }
    catch (error) { clear(flow); throw error; }
  }
  function footer() {
    if (!current || !same(current.context)) return '';
    if (current.target.kind === 'task-setup') return `<div class="info-box" id="account-return-context"><p>可以先选择常用清单，也可以暂不连接。返回后继续安排家庭待办；这里不会自动创建待办或发布到云端。</p><button class="btn secondary" type="button" id="account-return">返回待办</button><p class="error" id="account-return-error" role="alert"></p></div>`;
    const label = current.target.kind === 'calendar' ? '日历发布' : '待办发布';
    return `<div class="info-box" id="account-return-context"><p>${current.restored ? '授权页面已返回。请重新读取原记录并开始新的选择。' : '配置完成后可返回原发布页，重新读取日程或待办。'}选择来源只开启读取同步；发布仍需另行预览和确认。</p><button class="btn secondary" type="button" id="account-return">${current.restored ? '重新打开' : '返回'}${label}</button><p class="error" id="account-return-error" role="alert"></p></div>`;
  }
  async function resume(button) {
    const flow = current; if (!flow) throw stale(); if (button.disabled) return; button.disabled = true;
    try {
      await recheck(flow);
      if (!button.isConnected || !document.querySelector('#dialog')?.open) throw stale();
      const selected = flow.target, context = flow.context;
      if (selected.kind === 'task-setup') {
        await ProductShell.openTasks({originNode:button}, context); clear(flow); return;
      }
      clear(flow);
      if (selected.kind === 'calendar') await CalendarPublish.open(selected.journeyId, context);
      else await TaskPublish.open(selected.journeyId ? {journeyId:selected.journeyId} : {entityIds:selected.entityIds}, context);
    } catch (error) {
      if (current === flow && (error.connectionSessionChanged || !same(flow.context))) {
        clear(flow);
        if (button.isConnected) openModal('登录状态已改变', '<p class="error">请刷新页面，再从当前家庭账户重新打开发布入口。</p>');
      }
      if (button.isConnected) { const box = $('#account-return-error'); if (box) box.textContent = error.message; button.disabled = false; }
      else if (current === flow) toast(error.message, true);
    }
  }
  async function prepareOAuth(value, context) {
    let flow = current;
    if (value) {
      const selected = target(value), ticket = generation;
      context = context || await capture(); await verify(context);
      if (ticket !== generation) throw stale();
      clear(); flow = {target:selected, context, flowId:crypto.randomUUID(), restored:false}; current = flow;
    }
    if (!flow) return; // Ordinary binding has no publishing return intent.
    await recheck(flow);
    const actor = await verify(flow.context); if (current !== flow) throw stale();
    const now = Date.now();
    sessionStorage.setItem(key, JSON.stringify({v:1, flowId:flow.flowId, target:flow.target,
      memberId:actor.id, householdId:actor.householdId || 'default', authVersion:actor.auth_version,
      createdAt:now, expiresAt:now + ttl}));
  }
  async function restore(result) {
    const saved = read(); if (!saved) return false;
    const ticket = generation, now = Date.now();
    try {
      if (!['connected', 'error'].includes(result) || !canEdit() || saved.v !== 1 || !validId(saved.flowId) || !validId(saved.memberId) || !validId(saved.householdId)
        || !Number.isInteger(saved.authVersion) || !Number.isInteger(saved.createdAt) || !Number.isInteger(saved.expiresAt)
        || saved.createdAt > now + 30000 || saved.expiresAt <= now || saved.expiresAt - saved.createdAt !== ttl
        || Object.keys(saved).some(k => !['v','flowId','target','memberId','householdId','authVersion','createdAt','expiresAt'].includes(k))) throw stale();
      const selected = target(saved.target), context = await capture();
      if (ticket !== generation) return false;
      const expected = JSON.stringify([saved.householdId, saved.memberId, saved.authVersion]);
      if (context.identity !== expected) throw stale();
      const flow = {target:selected, context, flowId:saved.flowId, restored:true}; current = flow;
      await recheck(flow); remove(saved.flowId);
      await accountsModal(); return true;
    } catch (_) { if (ticket === generation && current?.flowId === saved.flowId) clear(current); return false; }
    finally { remove(saved.flowId); }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('#account-return'); if (button) { resume(button); return; }
    const link = event.target.closest('a');
    if (event.target.closest('[data-action="logout"]') || link && /^\/(space\/|auth\/.*\/login)/.test(link.getAttribute('href') || '')) clear();
  }, true);
  document.addEventListener('submit', event => { if (['login-form', 'space-switch', 'space-create'].includes(event.target.id)) clear(); }, true);
  document.querySelector('#dialog')?.addEventListener('close', () => clear());
  return {begin, capture, verify, same, footer, prepareOAuth, restore};
})();
function accountTimestamp(value) {
  if (!value) return '尚未成功同步';
  const parsed = new Date(typeof value === 'number' ? value * 1000 : value);
  if (Number.isNaN(parsed.getTime())) return '尚未成功同步';
  return new Intl.DateTimeFormat('zh-CN', {month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'}).format(parsed);
}
function accountLoginUrl(provider) {
  return /^\/auth\/(microsoft|google)\/login$/.test(provider.loginUrl || '') ? provider.loginUrl : '';
}
async function renderAccountLogin() {
  const container = $('#account-login');
  if (!container) return;
  try {
    const result = await api('/auth/providers');
    if (!container.isConnected) return;
    container.innerHTML = `<p class="help">已绑定账户也可直接登录</p><div class="provider-login-buttons">${result.providers.map(provider => {
      const url = accountLoginUrl(provider);
      return provider.configured && url
        ? `<a class="btn secondary" href="${esc(url)}">使用 ${esc(accountProviderName(provider.id))} 登录</a>`
        : `<button class="btn secondary" type="button" disabled>${esc(accountProviderName(provider.id))} · 等待配置</button>`;
    }).join('')}</div><p class="help account-login-note">首次使用请先用家庭密码登录，再绑定账户。仅限你和伴侣。<a href="/static/account-setup.html">接入步骤</a></p>`;
  } catch (error) {
    if (container.isConnected) container.innerHTML = `<p class="help">暂时无法读取第三方登录状态，仍可使用家庭密码登录。</p>`;
  }
}
function showAccountAuthResult() {
  const query = new URLSearchParams(location.search);
  const result = query.get('auth');
  if (!result) { AccountsReturn.restore(null); return; }
  const reasons = {
    not_configured:'这个登录入口还未完成应用配置，请先使用家庭密码登录。',
    unbound:'这个账户尚未绑定。请先用家庭密码登录，再在设置中绑定。',
    unbound_account:'这个账户尚未绑定。请先用家庭密码登录，再在设置中绑定。',
    not_bound:'这个账户尚未绑定。请先用家庭密码登录，再在设置中绑定。',
    account_not_bound:'这个账户尚未绑定。请先用家庭密码登录，再在设置中绑定。',
    already_bound:'这个账户已绑定到另一位家庭成员，请换用自己的账户。',
    account_in_use:'这个账户已绑定到另一位家庭成员，请换用自己的账户。',
    denied:'账户服务商未批准这次授权。请确认所需权限已允许；工作或学校账户也可能受组织策略限制。',
    access_denied:'账户服务商未批准这次授权。请确认所需权限已允许；工作或学校账户也可能受组织策略限制。',
    provider_denied:'账户服务商未批准这次授权。请确认所需权限已允许；工作或学校账户也可能受组织策略限制。',
    expired:'这次授权已过期，请重新开始。',
    invalid_state:'授权会话已失效，请在同一个浏览器重新开始。',
    session_changed:'家庭登录状态已改变，请重新登录后再绑定。',
    bind_session_changed:'家庭登录状态已改变，请重新登录后再绑定。',
    account_limit:'当前成员已达到可绑定账户数量，请先在设置中整理已有绑定。',
    token_failed:'暂时未能完成授权令牌兑换，请重新绑定；若仍失败，请联系看板维护者检查连接状态。',
    invalid_client:'应用身份校验失败。请核对该平台的应用 ID、客户端密钥值及密钥有效期；微软需使用密钥的“值”，而非“密钥 ID”。',
    invalid_grant:'本次授权码已失效，请重新开始账户绑定。',
    insufficient_permissions:'本次授权未包含所需的日历和清单权限，请重新授权并允许这些权限。',
    missing_refresh_token:'本次授权未取得后台同步所需的离线访问权限，请重新授权。',
    identity_failed:'暂时无法读取已授权账户的身份，请重新尝试绑定。',
    provider_error:'账户授权未完成，请重新尝试；若仍失败，请联系看板维护者查看具体原因。',
  };
  const message = result === 'connected' ? '账户已绑定，请选择要共享的日历和清单。'
    : result === 'photos-connected' ? 'Google Photos 已连接，请选择要保存的照片。'
    : result === 'signed-in' ? '已使用绑定账户登录。'
    : reasons[query.get('reason')] || '账户授权未完成，请重新尝试。';
  query.delete('auth'); query.delete('reason');
  history.replaceState(null, '', location.pathname + (query.size ? '?' + query.toString() : '') + location.hash);
  const error = $('#login-form .error');
  if (result === 'error' && error) error.textContent = message;
  else toast(message, result === 'error');
  if (result === 'photos-connected') { window.ProductShell?.navigate('photos'); return; }
  AccountsReturn.restore(result).then(restored => {
    if (!restored && result === 'connected' && canEdit()) return accountsModal();
  }).catch(error => toast(error.message, true));
}
async function accountViewCheck(context, element) {
  try { await AccountsReturn.verify(context); }
  catch (error) {
    if (error.connectionSessionChanged && element.isConnected && $('#dialog')?.open) openModal('登录状态已改变', '<p class="error">请刷新页面，再从当前家庭账户重新打开连接入口。</p>');
    throw error;
  }
  if (!element.isConnected || !$('#dialog')?.open) throw new Error('页面已改变，请重新打开账户管理。');
}
async function accountViewRead(title, path) {
  openModal(title, '<p class="help" id="account-loading">正在读取当前账户状态…</p>', true);
  const marker = $('#account-loading');
  try {
    const context = await AccountsReturn.capture(); await accountViewCheck(context, marker);
    const result = await api(path); await accountViewCheck(context, marker);
    return {result, context};
  } catch (error) {
    if (marker.isConnected) openModal(title, `<p class="error" role="alert">${esc(error.message)}</p>`);
    throw error;
  }
}
async function bindAccount(provider, button, context) {
  button.disabled = true;
  try {
    await accountViewCheck(context, button);
    const result = await write('/accounts/bind', 'POST', {provider});
    const target = new URL(result.url);
    const expectedHost = provider === 'microsoft' ? 'login.microsoftonline.com' : 'accounts.google.com';
    if (target.protocol !== 'https:' || target.hostname !== expectedHost) throw new Error('授权地址无效，请检查服务端配置');
    await accountViewCheck(context, button);
    await AccountsReturn.prepareOAuth();
    await accountViewCheck(context, button);
    location.assign(target.href);
  } catch (error) { toast(error.message, true); button.disabled = false; }
}
async function accountsModal() {
  if (!canEdit()) return;
  const {result, context} = await accountViewRead('账户与自动同步', '/accounts');
  const providers = result.providers || [];
  const accounts = result.accounts || [];
  const connections = accounts.map(account => `<article class="account-card">
    <header><div><strong>${esc(accountProviderName(account.provider))} · ${esc(account.name || '已绑定账户')}</strong>${account.email ? `<small>${esc(account.email)}</small>` : ''}</div><span class="pill ${account.needsReauth ? 'demo' : ''}">${account.needsReauth ? '需要重新授权' : '已绑定'}</span></header>
    ${account.needsReauth ? '<p class="error">授权已失效，请使用下方同一平台的绑定按钮重新授权这个账户。</p>' : ''}
    <div class="account-sources">${account.sources.length ? account.sources.map(source => `<div class="account-source-summary"><span>${icon(source.kind === 'calendar' ? 'calendar' : 'list')} ${esc(source.name)}${source.primary ? ' <span class="sage">· 共同待办主清单</span>' : ''}</span><small>${source.kind === 'calendar' ? esc(who(source.owner)) + ' · ' : ''}${esc(accountTimestamp(source.lastSuccess))}</small>${source.error ? `<p class="error">${esc(source.error)}</p>` : ''}</div>`).join('') : account.capabilities?.sync === false ? '<p class="help">这个账户用于相册，照片请在家庭相册中选择和管理。日历与清单需要另外授权。</p>' : '<p class="help">还没有共享数据。选择日历或清单后才会开始同步。</p>'}</div>
    <div class="account-actions">${account.capabilities?.photos ? `<button class="btn small secondary" data-account-photos="${esc(account.id)}">管理相册</button>` : ''}<button class="btn small secondary" data-account-select="${esc(account.id)}" ${account.needsReauth || account.capabilities?.sync === false ? 'disabled' : ''}>选择日历与清单</button><button class="btn small secondary" data-account-sync="${esc(account.id)}" ${account.needsReauth || !account.sources.length ? 'disabled' : ''}>立即检查更新</button><button class="quiet" data-account-disconnect="${esc(account.id)}">断开绑定</button></div>
  </article>`).join('');
  openModal('账户与自动同步', `<div class="info-box">只同步你明确选择的日历与清单。选中的完整日程标题、地点和任务会展示给双方与已配对电视；个人财务仍仅本人可见。</div>
    ${AccountsReturn.footer()}
    <div class="account-provider-grid">${providers.map(provider => `<div class="account-provider"><strong>${esc(accountProviderName(provider.id))}</strong><p class="help">${provider.id === 'microsoft' ? 'Outlook 日历 · Microsoft To Do' : 'Google 日历 · Google Tasks'}</p><button class="btn secondary" data-account-bind="${esc(provider.id)}" ${provider.configured ? '' : 'disabled'}>${provider.configured ? '绑定 / 重新授权' : '等待应用配置'}</button></div>`).join('')}</div>
    <p class="help"><a href="/static/account-setup.html" target="_blank" rel="noopener">打开应用注册与授权步骤 ↗</a>。请在微软或 Google 页面登录，不在看板中填写第三方密码。</p>
    ${connections || '<p class="help">当前家庭成员还没有绑定账户。你和伴侣需分别登录各自的家庭账户进行绑定。</p>'}
    <p class="help account-explanation">清单约每 30 秒、日历约每 60 秒在后台检查更新，看板约每 10 秒刷新。服务限流、网络或授权异常时可能延迟。共同待办主清单可设为一份 Microsoft To Do 或 Google Tasks 清单。选择后，两位成员均可明确将家庭待办发布到该清单。</p>
    <p class="help">日历在原应用中编辑；同步任务可在看板新建、勾选完成或恢复，其他修改请回到原应用。Apple 日历里显示的 Google / Outlook 日历请连接对应账户；纯 iCloud 日历后续接入。</p>
    <div class="dialog-footer"><button class="btn secondary" id="account-refresh">刷新状态</button><button class="btn" data-action="close">完成</button></div>`, true);
  $('[id="account-refresh"]').onclick = () => accountsModal().catch(error => toast(error.message, true));
  document.querySelectorAll('[data-account-bind]').forEach(button => button.onclick = () => bindAccount(button.dataset.accountBind, button, context));
  document.querySelectorAll('[data-account-photos]').forEach(button => button.onclick = async () => {
    try { await accountViewCheck(context, button); window.ProductShell?.navigate('photos'); }
    catch (error) { toast(error.message, true); }
  });
  document.querySelectorAll('[data-account-select]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try { await accountViewCheck(context, button); await accountSourcesModal(accounts.find(account => account.id === button.dataset.accountSelect)); }
    catch (error) { toast(error.message, true); button.disabled = false; }
  });
  document.querySelectorAll('[data-account-sync]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try { await accountViewCheck(context, button); const result = await write('/accounts/' + encodeURIComponent(button.dataset.accountSync) + '/sync', 'POST'); await accountViewCheck(context, button); toast(result.queued ? '已安排后台检查，稍后点击刷新状态查看结果。' : '当前没有选中的来源，无需检查。'); }
    catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  });
  document.querySelectorAll('[data-account-disconnect]').forEach(button => button.onclick = async () => {
    if (!confirm('断开这个账户并移除它同步到看板的日程、任务和照片副本，同时收回照片的家庭共享与电视展示？原应用和 Google Photos 中的原始数据会保留。')) return;
    button.disabled = true;
    try { await accountViewCheck(context, button); await write('/accounts/' + encodeURIComponent(button.dataset.accountDisconnect), 'DELETE'); await accountViewCheck(context, button); await refresh(true); await accountViewCheck(context, button); await accountsModal(); toast('已断开账户绑定'); }
    catch (error) { toast(error.message, true); button.disabled = false; }
  });
}
async function accountSourcesModal(account) {
  if (!account) throw new Error('账户状态已改变，请重新打开设置');
  const {result, context} = await accountViewRead('选择共享内容 · ' + accountProviderName(account.provider), '/accounts/' + encodeURIComponent(account.id) + '/sources');
  const sources = result.sources || [];
  const selected = new Map((result.selected || []).map(source => [accountSourceKey(source), source]));
  const hasPrimary = [...selected.values()].some(source => source.primary);
  function sourceRow(source, index) {
    const saved = selected.get(accountSourceKey(source));
    const unavailable = source.writable === false && source.kind === 'tasks';
    return `<div class="account-source-choice"><label class="label-check"><input type="checkbox" name="source-${index}" ${saved && !unavailable ? 'checked' : ''} ${unavailable ? 'disabled' : ''}><span>${esc(source.name)}${unavailable ? '<small>此清单暂不可接入，请在原应用中查看</small>' : ''}</span></label>
      ${source.kind === 'calendar' ? selectField('所属日程', 'owner-' + index, ownerOptions(saved?.owner || user.id)) : `<small class="muted">任务将与伴侣共享</small>${source.writable !== false ? `<label class="label-check account-primary-choice"><input type="radio" name="primary" value="${index}" ${saved?.primary ? 'checked' : ''}>设为共同待办主清单</label>` : ''}`}</div>`;
  }
  openModal('选择共享内容 · ' + accountProviderName(account.provider), `<p class="help">${esc(account.name || account.email || '')}。默认不选择任何来源，保存后按所选范围自动同步。</p><form id="account-sources-form">
    ${['calendar', 'tasks'].map(kind => `<h3 class="section-label">${kind === 'calendar' ? '日历' : '任务清单'}</h3>${sources.some(source => source.kind === kind) ? sources.map((source, index) => source.kind === kind ? sourceRow(source, index) : '').join('') : '<p class="help">此账户暂未返回可用来源。</p>'}`).join('')}
    ${sources.some(source => source.kind === 'tasks' && source.writable !== false) ? `<label class="label-check"><input type="radio" name="primary" value="" ${hasPrimary ? '' : 'checked'}>不将此账户的清单设为主清单</label><p class="help">家庭仅使用一份主清单。同一账户内可以更换；若另一账户已有主清单，请先由其拥有者取消主清单设置。其他清单的任务不会自动复制过去。</p>` : ''}
    <label class="label-check source-consent"><input type="checkbox" name="consent" required>我确认将选中的完整日程标题、地点与任务展示给双方和已配对电视。</label><p class="help">取消选择会移除该来源在看板上的同步内容，不会删除原应用中的记录。</p><div class="error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" type="button" id="account-sources-back">返回</button><button class="btn" type="submit">保存共享范围</button></div></form>`, true);
  $('#account-sources-back').onclick = () => accountsModal().catch(error => toast(error.message, true));
  const form = $('#account-sources-form');
  form.onsubmit = async event => {
    event.preventDefault();
    const button = $('button[type="submit"]', form); button.disabled = true;
    $('.error', form).textContent = '';
    try {
      await accountViewCheck(context, form);
      const primary = form.elements.primary?.value ?? '';
      if (primary !== '' && !form.elements['source-' + primary]?.checked) throw new Error('请先勾选要设为主清单的来源');
      const chosen = sources.flatMap((source, index) => form.elements['source-' + index].checked ? [{remoteId:source.id,kind:source.kind,name:source.name,owner:source.kind === 'tasks' ? 'shared' : form.elements['owner-' + index].value,primary:primary !== '' && Number(primary) === index}] : []);
      const saved = await write('/accounts/' + encodeURIComponent(account.id) + '/sources', 'POST', {sources:chosen});
      await accountViewCheck(context, form); await refresh(true); await accountViewCheck(context, form);
      await accountsModal(); toast(saved.queued ? '共享范围已保存，后台将开始同步。' : '共享范围已保存，当前没有选中的来源。');
    } catch (error) { $('.error', form).textContent = error.message; button.disabled = false; }
  };
}
