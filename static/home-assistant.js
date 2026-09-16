/* Shared-record action desk. Context stays in this tab and never enters localStorage. */
window.HomeAssistant = (() => {
  let state = null, bridge = null, observer = null, busy = false, sequence = 0, journeySequence = 0;
  let previewUrl = null, sourceTimer = null, sourceExpiry = null, sourceEpoch = 0;
  const sourceKinds = new Set(['media', 'places']);
  const allowedKinds = new Set(['tasks', 'shopping', 'events', 'trips']);
  const identity = actor => actor?.role === 'member' ? `${actor.householdId || 'default'}:${actor.id}` : '';
  const active = () => !!document.querySelector('#assistant-workspace');
  const action = (name, label, attrs = '') => `<button type="button" class="btn small secondary" data-assistant-action="${name}" ${attrs}>${label}</button>`;
  const targetAttrs = (kind, id) => `data-kind="${esc(kind)}" data-id="${esc(id)}"`;
  const source = item => item.sync ? `${item.sync.provider === 'microsoft' ? 'Microsoft' : item.sync.provider === 'google' ? 'Google' : '同步来源'} · ${item.sync.readOnly ? '只读' : '在原应用维护'}` : item.journeyId ? '旅行关联记录' : '家庭记录';
  const owner = item => `${esc(person(item.owner || 'shared'))} · ${esc(source(item))}`;
  const itemIn = (shared, kind, id) => (shared?.[kind] || []).find(item => item.id === id);
  const currentItem = (kind, id) => itemIn(state?.shared, kind, id);
  const sameContext = current => state === current && identity(user) === current.identity && csrf === current.csrf && canEdit();
  const explicitListCommand = prompt => /^(?:添加|新增|创建)?\s*(?:待办|任务|采购|购物|搜索|查找)\s*[：:]/.test(prompt.trimStart());
  const isSearch = prompt => /^(?:搜索|查找|找一下)/.test(prompt.trimStart());
  const requestsJourney = prompt => !isSearch(prompt) && !explicitListCommand(prompt)
    && (state?.journeyIntent || /旅行|旅游|行程|出发日期|返程日期/.test(prompt));
  const submitLabel = prompt => isSearch(prompt) ? '搜索本地记录' : requestsJourney(prompt)
    ? (state?.journeyDraft ? '按当前文字重新整理' : '整理旅行简报') : '生成可审阅方案';

  function blank() {
    return {identity: identity(user), csrf, brief: null, shared: null, prompt: '', useModel: false,
      includeContext: false, draft: null, selected: [], applied: null, notice: '', error: '',
      submittedTasks: new Set(), composerOpen: true, visible: true, journeyDraft: null, journeyIntent: false};
  }
  function clearSource() {
    sourceEpoch++; clearTimeout(sourceTimer); clearTimeout(sourceExpiry); sourceTimer = sourceExpiry = null;
    if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null;
    document.querySelector('#assistant-source-preview')?.remove();
    if (state) state.sourceDetail = null;
  }
  function clear() {
    clearSource();
    sequence++; journeySequence++; state = null; bridge = null; busy = false;
    observer?.disconnect(); observer = null;
  }
  function capture() {
    const form = document.querySelector('#assistant-form');
    if (!state || !form) return;
    state.prompt = form.elements.prompt.value;
    state.useModel = !!form.elements.useModel?.checked;
    state.includeContext = !!form.elements.includeHouseholdContext?.checked;
    state.selected = [...document.querySelectorAll('[data-plan-index]:checked')].map(input => Number(input.dataset.planIndex));
    state.composerOpen = !!document.querySelector('#assistant-composer')?.open;
  }
  function expired() {
    clear();
    openModal('请重新进入家庭助理', '<p class="help">登录成员或家庭已变化，旧页面内容已清除。请刷新看板后重新打开。</p>');
  }
  async function verify(current) {
    // A late request owns only its captured context, never a newer open/session.
    if (state !== current) throw new Error('这次读取已被新的助理页面替代');
    let me;
    try { me = await api('/me'); } catch (error) {
      if (state === current && [401,403].includes(error.status)) expired();
      throw error;
    }
    if (state !== current) throw new Error('这次读取已被新的助理页面替代');
    if (!sameContext(current) || identity(me.user) !== current.identity || me.csrf !== current.csrf) {
      expired(); throw new Error('登录状态已变化，请重新打开家庭助理');
    }
  }
  async function load(current) {
    await verify(current);
    const search = current.draft?.search; clearSource();
    if (search) current.draft = null;
    // These are shared endpoints; never query private finance or account data.
    const [brief, shared] = await Promise.all([api('/assistant/brief'), api('/state')]);
    await verify(current);
    if (search) {
      const result = await api('/assistant/search?' + new URLSearchParams({q:search.query,limit:search.limit,offset:search.offset}));
      await verify(current);
      current.draft = {id:null,actions:[],mode:'local',summary:`找到 ${result.total} 条当前可见记录。`,matches:result.matches,search:result};
    }
    current.brief = brief; current.shared = shared; current.loadedAt = new Date();
    current.submittedTasks.clear();
  }
  function group(key, title, symbol, rows, emptyText) {
    return `<section class="assistant-desk-group" id="assistant-group-${key}" tabindex="-1"><div class="assistant-group-heading">${icon(symbol)}<h3>${title}</h3><span>${rows.length}</span></div>${rows.length ? rows.join('') : `<p class="assistant-group-empty">${emptyText}</p>`}</section>`;
  }
  function recordRow(item, kind, reason, label = '打开记录', extra = '') {
    return `<article class="assistant-record" data-record-kind="${kind}" data-record-id="${esc(item.id)}"><div class="assistant-record-copy"><strong>${esc(item.title)}</strong><small>${owner(item)}</small><p>${esc(reason)}</p></div><div class="assistant-record-actions">${action('visit', label, targetAttrs(kind, item.id))}${extra}</div></article>`;
  }
  function desk() {
    const brief = state.brief, shared = state.shared;
    if (!brief || !shared) return '<div class="assistant-loading">正在读取这个家的待处理记录…</div>';
    const tasks = brief.tasks.filter(item => !item.done).map(item => recordRow(item, 'tasks',
      `${item.due < brief.today ? '已到期' : '截止'} · ${item.due}`,
      item.sync ? '查看同步记录' : '查看 / 调整', !item.sync ? action('complete', state.submittedTasks.has(item.id) ? '已提交 · 待读回' : '标记完成', `${targetAttrs('tasks', item.id)} ${state.submittedTasks.has(item.id) ? 'disabled' : ''}`) : ''));
    const conflicts = brief.conflicts.map(pair => {
      const items = [pair.first, pair.second].map(id => currentItem('events', id)).filter(Boolean);
      return `<article class="assistant-record assistant-conflict"><div class="assistant-record-copy"><strong>时间重叠 · ${esc(pair.day)}</strong><small>家庭日程 · 请核对两项安排</small>${items.map(item => `<p>${esc(item.title)} · ${esc(person(item.owner))}</p>`).join('')}</div><div class="assistant-record-actions">${items.map(item => action('visit', `查看 ${esc(item.title)}`, targetAttrs('events', item.id))).join('')}</div></article>`;
    });
    const shopping = (shared.shopping || []).filter(item => item.budget == null || (item.done && item.actual == null)).slice(0, 8).map(item => recordRow(item, 'shopping',
      item.done && item.actual == null ? '已买到，实际金额仍未填写；不会自动记为财务支出。' : '采购预算尚未填写，未知金额不按零计算。', item.done && item.actual == null ? '补实付 / 预算' : '填写预算'));
    const trips = brief.trips.map(trip => {
      const related = (shared.tasks || []).filter(item => item.tripId === trip.id), done = related.filter(item => item.done).length;
      return recordRow(trip, 'trips', `${trip.start} — ${trip.end} · 准备 ${done} / ${related.length}${related.length ? '' : ' · 尚无准备事项'}`, '打开这趟旅行');
    });
    const routines = (brief.routines?.items || []).map(item => {
      const reasons = {missing:'本期事项已删除，计划需要核对；不会自动重新创建。',capacity_blocked:'清单数量已达上限，下一期尚未生成。',exhausted:'下一期超出当前支持的日期范围，请核对计划。'};
      const reason = reasons[item.status] || `${item.scheduledOn < brief.today ? '本期已逾期' : '本期安排'} · ${item.scheduledOn}`;
      return `<article class="assistant-record" data-record-kind="routines" data-record-id="${esc(item.id)}"><div class="assistant-record-copy"><strong>${esc(item.title)}</strong><small>${esc(person(item.owner))} · ${item.kind==='shopping'?'例行采购':'例行待办'}</small><p>${esc(reason)}</p></div><div class="assistant-record-actions">${action('routine-plan','查看例行计划',`data-id="${esc(item.id)}"`)}</div></article>`;
    });
    const finance = shared.finance;
    const funds = finance && !finance.confirmedAt ? [`<article class="assistant-record" data-record-kind="finance"><div class="assistant-record-copy"><strong>公共资金尚未核对</strong><small>家庭共享快照 · 手工核对</small><p>先核对荷包余额与本月支出；这里不会连接银行、转账或读取个人账本。</p></div><div class="assistant-record-actions">${action('finance', '核对公共资金')}</div></article>`] : [];
    const shortcuts = [['tasks', '待办', tasks.length], ['events', '协调日程', conflicts.length], ['shopping', '采购', shopping.length], ['trips', '旅行', trips.length], ['finance', '资金核对', funds.length]];
    if (routines.length) shortcuts.push(['routines','例行计划',routines.length]);
    return `<nav class="assistant-quicknav" aria-label="选择待处理类别">${shortcuts.map(([key, label, count]) => action('jump', `${label} <span>${count}</span>`, `data-group="${key}"`)).join('')}${action('jump', '继续规划 ↓', 'data-group="composer"')}</nav><div class="assistant-desk-grid">${group('tasks', '到期待办', 'check', tasks, '返回范围内没有到期待办。')}${group('events', '需要协调的日程', 'calendar', conflicts, '返回范围内未发现时间重叠。')}${group('shopping', '采购金额待补', 'bag', shopping, '现有采购记录没有待补的金额。')}${group('trips', '近期旅行准备', 'plane', trips, '还没有近期旅行计划。')}${group('finance', '公共资金', 'wallet', funds, finance?.confirmedAt ? `已手工核对 · ${esc(displayDate(finance.confirmedAt))}。余额以原账户为准。` : '公共资金暂不可用。')}${routines.length?group('routines','例行事项与接续问题','calendar',routines,''):''}</div>
      <p class="assistant-coverage">近期范围 ${esc(brief.today)} — ${esc(brief.through)}，同时包含逾期待办；旅行按未结束日期筛选。到期待办最多显示 20 项、日程冲突最多 12 组、旅行最多 5 趟、采购待补最多 8 项、例行计划最多 8 项；例行内容是站内提示，不是系统通知。是已有记录的处理入口，不代表全量事务或来源覆盖。</p>`;
  }
  function resultMarkup() {
    const draft = state.draft;
    if (!draft) return '';
    const created = state.applied?.created || [];
    return `<section class="assistant-answer"><span class="pill">${draft.search ? '本地搜索 · 只读结果' : (draft.mode === 'model' ? 'AI 建议' : '本地规划') + ' · ' + (state.applied ? '已提交' : '待确认')}</span><p class="assistant-summary">${esc(draft.summary)}</p>
      ${draft.matches.map(item => allowedKinds.has(item.kind) || sourceKinds.has(item.kind) || item.kind === 'inventory' ? `<div class="assistant-search-record">${action(item.kind === 'inventory' ? 'inventory' : sourceKinds.has(item.kind) ? 'source' : 'visit', esc(item.title), targetAttrs(item.kind, item.id))}<small>${esc(item.kind === 'inventory' ? '家庭物品' + (item.variant ? ' · ' + item.variant : '') : item.kind === 'media' ? '照片说明' : item.kind === 'places' ? '地图地点' : item.start || item.due || '')}${item.journey ? ' · ' + esc(item.journey.title) : ''}</small></div>` : '').join('')}
      ${draft.search ? `<p class="help">本地搜索 · 当前可见 ${draft.search.total} 条 · 第 ${Math.floor(draft.search.offset / draft.search.limit) + 1} 页。不会把搜索词或结果发送给模型。</p>${draft.search.offset ? action('search-page', '上一页', `data-offset="${Math.max(0,draft.search.offset-draft.search.limit)}"`) : ''}${draft.search.nextOffset != null ? action('search-page', '下一页', `data-offset="${draft.search.nextOffset}"`) : ''}` : ''}
      ${sourceMarkup()}
      ${draft.actions.length ? `<h3>${state.applied ? '本次创建结果' : '准备创建'}</h3>${draft.actions.map((item, index) => `<label class="assistant-action"><input type="checkbox" data-plan-index="${index}" ${state.selected.includes(index) ? 'checked' : ''} ${state.applied ? 'disabled' : ''}><span><strong>${esc(item.data.title)}</strong><small>${item.kind === 'tasks' ? '待办' : '采购'} · ${esc(person(item.data.owner))}${item.data.due ? ' · ' + esc(item.data.due) : ''}</small></span></label>`).join('')}
      <p class="help">创建到本家庭共享清单。不会发送消息、下单或执行转账。</p><button class="btn" id="assistant-apply" data-assistant-action="apply" ${state.applied ? 'disabled' : ''}>${state.applied ? `已创建 ${created.length} 项` : '确认创建选中事项'}</button>` : ''}
      ${created.map(item => `<div class="assistant-created">${action('visit', `查看 ${esc(item.title)}`, targetAttrs(item.kind, item.id))}</div>`).join('')}
      ${created.some(item => item.kind === 'tasks') && window.TaskPublish ? action('publish', '将这些待办同步到主清单', 'id="assistant-publish-tasks"') : ''}</section>`;
  }
  function sourceMarkup() {
    const item = state.sourceDetail;
    if (!item) return '';
    return `<article class="assistant-readonly" id="assistant-source-detail"><h3>${esc(item.title)}</h3><p>${esc(item.description)}</p>${item.journey ? `<p>关联旅行 · ${esc(item.journey.title)}</p>` : ''}${previewUrl ? `<img id="assistant-source-preview" src="${esc(previewUrl)}" alt="精选照片展示副本" style="max-width:100%;max-height:360px;object-fit:contain">` : ''}<p class="help">仅展示当前仍有权读取的内容。地图坐标请在地图中查看。</p>${action('source-page', item.kind === 'media' ? '打开家庭相册' : '打开足迹地图')}${action('source-close','收起详情')}</article>`;
  }
  async function searchPage(offset) {
    const current = state, search = current.draft?.search;
    if (!search || !Number.isInteger(offset) || offset < 0 || offset > 20000) return;
    clearSource(); await verify(current);
    try {
      const result = await api('/assistant/search?' + new URLSearchParams({q:search.query,limit:search.limit,offset}));
      await verify(current);
      current.draft = {...current.draft, matches:result.matches, search:result}; render();
    } catch (error) { if (state === current) { current.draft = null; render(); } throw error; }
  }
  async function visitInventory(id) {
    const current = state;
    if (!/^[a-f0-9]{24}$/.test(id) || !current.draft?.matches.some(item => item.kind === 'inventory' && item.id === id)) return;
    await verify(current);
    if (!window.ProductShell?.openInventory) throw new Error('家庭物品组件暂未加载，请刷新重试');
    // Pass an identifier only. The destination reads current ACL and details.
    clearSource(); current.draft = null;
    await window.ProductShell.openInventory(id);
  }
  async function visitSource(kind, id) {
    const current = state;
    if (!sourceKinds.has(kind) || !/^[a-f0-9]{24}$/.test(id) || !current.draft?.matches.some(item=>item.kind===kind && item.id===id)) return;
    clearSource(); const epoch = sourceEpoch;
    const valid = () => state === current && sameContext(current) && sourceEpoch === epoch && current.visible && active() && !document.hidden;
    const route = kind === 'media' ? '/media/items/' : '/journey-places/';
    async function readDetail() {
      await verify(current);
      const result = await api(route + id); await verify(current);
      if (!valid()) throw new Error('详情已关闭，请重新打开');
      return kind === 'media' ? result.item : result.place;
    }
    try {
      const item = await readDetail();
      if (kind === 'media') {
        const path = '/api/media/items/' + id + '/preview';
        if (item.previewUrl !== path) throw new Error('照片预览地址无效');
        const response = await fetch(path, {credentials:'same-origin', cache:'no-store', redirect:'error'});
        if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'image/jpeg') throw new Error('照片预览暂不可用');
        const bytes = await response.arrayBuffer();
        if (!bytes.byteLength || bytes.byteLength > 2*1024*1024) throw new Error('照片预览大小无效');
        // A second authorized detail read fences a permission change during download.
        const latest = await readDetail();
        if (latest.revision !== item.revision) throw new Error('照片已变化，请重新打开');
        if (!valid()) return;
        previewUrl = URL.createObjectURL(new Blob([bytes], {type:'image/jpeg'}));
      }
      if (!valid()) return;
      current.sourceDetail = {kind,id,title:kind==='media' ? item.caption || '精选照片' : item.name,
        description:kind==='media' ? '照片说明 · '+(item.visibility==='private'?'仅本人':'已共享') : [item.country,item.city,{visited:'已明确确认到访',planned:'计划前往',wish:'愿望地点'}[item.status]].filter(Boolean).join(' · '), journey:item.journey};
      render(); document.getElementById('assistant-source-detail')?.scrollIntoView({block:'start'});
      const renew = () => {
        clearTimeout(sourceExpiry);
        sourceExpiry=setTimeout(() => {
          if (state===current && sourceEpoch===epoch) {
            clearSource(); current.draft=null; current.error='详情授权未能及时重新核验，请重新搜索。'; render();
          }
        },15000);
      };
      const refreshSource = async () => {
        if (!valid()) return;
        try { const latest=await readDetail(); if (latest.revision !== item.revision) throw new Error('内容已更新，请重新打开'); }
        catch (error) { if (state===current && sourceEpoch===epoch) { clearSource(); current.draft=null; current.error='详情已清除，请重新搜索：'+error.message; render(); } return; }
        if (valid()) { renew(); sourceTimer=setTimeout(refreshSource,10000); }
      };
      renew(); sourceTimer=setTimeout(refreshSource,10000);
    } catch (error) { if (state===current && sourceEpoch===epoch) { clearSource(); current.draft=null; render(); } throw error; }
  }
  function concealSource() {
    if (!state?.sourceDetail && !previewUrl) { sourceEpoch++; return; }
    clearSource(); if (state) { state.draft=null; state.error='详情已清除，请在恢复连接或返回页面后重新搜索。'; if (active()) render(); }
  }
  window.addEventListener('offline', concealSource);
  document.addEventListener('visibilitychange', () => { if (document.hidden) concealSource(); });
  function render() {
    if (!state || !sameContext(state) || !state.visible) return;
    activeManager = '';
    const brief = state.brief;
    openModal('家庭助理 · 本周待处理', `<div id="assistant-workspace"><div class="assistant-desk-intro"><div><span class="pill">${brief?.modelConfigured ? 'AI 可用 · 按需调用' : '本地规划助理'}</span><h3>从记挂，到处理好。</h3><p>打开原记录，核对后处理；每一步都有来处。</p></div>${action('refresh', '刷新待处理', 'id="assistant-refresh"')}</div>
      <p class="assistant-readback" role="status">${esc(state.notice || (state.loadedAt ? '已读取共享记录 · ' + displayTime(state.loadedAt) : ''))}</p><div class="assistant-desk-error error" role="alert">${esc(state.error)}</div>${desk()}
      <details id="assistant-composer" class="assistant-composer" ${state.composerOpen ? 'open' : ''}><summary>继续规划 · 旅行、清单与共享记录</summary><p class="help">${esc(brief?.coverage || '仅基于本家庭共享记录，不包含个人账单和投资账户。')}</p>
      <div class="assistant-suggestions">${action('prompt', '搜索记录', 'data-prompt="搜索：酒店"')}${action('prompt', '安排几件事', 'data-prompt="待办：明天预约保洁；确认旅行酒店"')}${action('prompt', '准备采购', 'data-prompt="采购：旅行转换插头；收纳袋"')}${action('journey', '规划一次旅行', 'id="assistant-journey"')}${!isDemo&&window.HouseholdRoutines?action('routines', '设置例行计划', 'id="assistant-routines"'):''}</div>
      <form id="assistant-form"><label class="field"><span>你想安排什么</span><textarea name="prompt" required maxlength="2000" rows="3" placeholder="说明想去的国家、城市、日期和预算；也可以输入 待办：明天预约保洁">${esc(state.prompt)}</textarea></label>
      ${brief?.modelConfigured ? `<label class="label-check"><input type="checkbox" name="useModel" ${state.useModel ? 'checked' : ''}>使用 AI 理解自由表达（自由表达将发送到已配置的 AI 服务；明确搜索始终在本地进行）</label><label class="label-check"><input type="checkbox" name="includeHouseholdContext" ${state.includeContext ? 'checked' : ''}>同时提供近期日程标题和待办（不包含财务数据）</label>` : '<p class="help">本地概览、搜索和清单指令直接可用；不需要配置模型。</p>'}
      ${state.journeyDraft ? '<p class="help">重新整理会使用当前文字，成功后替换已保留的简报。若想保留已填写的内容，请选择“继续已保留的旅行简报”。</p>' : ''}
      <p class="error" role="alert"></p><button class="btn" type="submit">${submitLabel(state.prompt)}</button>${action('journey-local', state.journeyDraft ? '继续已保留的旅行简报' : '分步填写旅行简报（不调用 AI）')}</form><div id="assistant-result" aria-live="polite">${resultMarkup()}</div></details></div>`, true);
    document.getElementById('dialog').classList.add('assistant-dialog');
    document.getElementById('assistant-form').onsubmit = plan;
    document.getElementById('assistant-form').elements.prompt.oninput = event => {
      event.currentTarget.form.querySelector('button[type=submit]').textContent = submitLabel(event.currentTarget.value);
    };
    document.getElementById('assistant-composer').ontoggle = event => { if (state) state.composerOpen = event.currentTarget.open; };
    setBusy(busy);
  }
  function setBusy(value) {
    busy = value;
    document.querySelectorAll('#assistant-workspace button').forEach(button => {
      button.disabled = value || (button.id === 'assistant-apply' && !!state?.applied) || (button.dataset.assistantAction === 'complete' && state?.submittedTasks.has(button.dataset.id));
    });
  }
  async function open() {
    if (isTV || user?.role === 'tv') { clear(); toast('电视仅展示共享看板，请在手机或电脑处理事项。'); return; }
    if (isDemo) {
      clear(); openModal('家庭助理 · 演示', '<div id="assistant-demo" class="info-box"><h3>本周待处理</h3><p>示例：确认周末保洁、填写转换插头预算、核对旅行准备。</p><p>这是虚构内容。演示不会请求家庭记录、创建事项或修改资金。</p></div>'); return;
    }
    if (!canEdit()) { clear(); toast('请先登录家庭后使用助理'); return; }
    capture(); clearSource(); state = state && sameContext(state) ? {...state} : blank();
    bridge = null; observer?.disconnect(); observer = null;
    const current = state, turn = ++sequence; current.visible = true; current.journeyIntent = false;
    // Never paint cached household content until this server session is verified.
    openModal('家庭助理 · 本周待处理', '<div id="assistant-workspace"><p class="help">正在核对登录状态并读取共享记录…</p></div>'); setBusy(true);
    try { await load(current); if (turn !== sequence) return; current.error = ''; render(); }
    catch (error) { if (state === current && current.visible && turn === sequence) {
      current.error = error.message;
      openModal('家庭助理 · 暂未读回', `<div id="assistant-workspace"><p class="error">${esc(error.message)}</p><p class="help">尚未展示缓存内容。规划上下文仍在本页内保留，重新读取后继续。</p>${action('refresh', '重新读取')}</div>`);
    } }
    finally { if (state === current) setBusy(false); }
  }
  async function openJourney() {
    const pending=open(), current=state, turn=sequence;
    await pending;
    if (!state || state!==current || turn!==sequence || !sameContext(state) || !document.getElementById('assistant-form')) return;
    state.journeyIntent=true; state.composerOpen=true; render();
    const form=document.getElementById('assistant-form');form.scrollIntoView({block:'start'});form.elements.prompt.focus();
  }
  function formSnapshot(form) {
    return JSON.stringify({fields: [...form.querySelectorAll('input,select,textarea')].map(input => [input.name, input.type, input.value, input.checked]),
      // ShoppingUI keeps its photoIds in a closure; rendered image sources are its stable public projection.
      photos: [...form.querySelectorAll('#shopping-photo-list img')].map(image => image.getAttribute('src'))});
  }

  async function journeyOperation(form, work) {
    const current = state, number = ++journeySequence, snapshot = formSnapshot(form);
    const live = () => state === current && number === journeySequence && current.visible && form.isConnected
      && document.getElementById('dialog').open && formSnapshot(form) === snapshot;
    const check = async () => {
      if (!live()) return false;
      const me = await api('/me');
      if (!live()) return false;
      if (!sameContext(current) || identity(me.user) !== current.identity || me.csrf !== current.csrf) {
        expired(); return false;
      }
      return true;
    };
    setBusy(true);
    try { if (await check()) await work({current, check, live}); }
    catch (error) {
      if (!live()) return;
      if (error.status === 401 || error.contextChanged) { expired(); return; }
      try { if (!await check()) return; } catch (problem) { if (!live()) return; if (problem.status === 401) { expired(); return; } }
      if (live()) form.querySelector('.error').textContent = error.message + '；简报与原需求仍保留，没有自动保存旅行。';
    } finally { if (state === current && number === journeySequence) setBusy(false); }
  }
  async function beginJourney(form, local = false) {
    if (!form) return;
    capture();
    await journeyOperation(form, async ({current, check}) => {
      // Resume is explicit. A new generation always uses the latest captured input;
      // the old editable brief survives until a response passes the context checks.
      if (!local || !current.journeyDraft) {
        const result = await write('/assistant/journey-brief', 'POST', {prompt: current.prompt, useModel: !local && current.useModel});
        if (!await check()) return;
        current.journeyDraft = {...result.brief, sourcePrompt: current.prompt, mode: result.mode, notice: result.notice,
          memberIds: (data.people || []).map(person => person.id), step: 1};
        if (!current.journeyDraft.destinations.length) current.journeyDraft.destinations.push({country:'',city:'',arrival:'',departure:''});
      }
      if (await check()) renderJourneyBrief();
    });
  }
  const briefInput = (label, name, value, type = 'text', attrs = '') => `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value ?? '')}" ${attrs}></label>`;
  function readJourneyBrief(form) {
    const draft = state.journeyDraft, fields = form.elements;
    if (draft.step === 1) {
      for (const name of ['title','start','end']) draft[name] = fields[name].value;
      draft.international = fields.international.value === '' ? null : fields.international.value === 'true';
    } else if (draft.step === 2) draft.destinations = [...form.querySelectorAll('.assistant-brief-stop')].map(row => Object.fromEntries(['country','city','arrival','departure'].map(name => [name, row.querySelector(`[name=${name}]`).value])));
    else {
      const amount = fields.budgetYuan.value;
      // Decimal text -> integer cents, never a floating point multiplication.
      draft.budgetCents = /^\d+(?:\.\d{1,2})?$/.test(amount) ? Number(amount.split('.')[0]) * 100 + Number((amount.split('.')[1] || '').padEnd(2,'0')) : null;
      draft.memberIds = [...form.querySelectorAll('[name=memberIds]:checked')].map(input => input.value);
      draft.note = fields.note.value;
    }
  }
  function renderJourneyBrief() {
    if (!state?.journeyDraft || !sameContext(state) || !state.visible) return;
    const draft = state.journeyDraft, step = draft.step;
    let fields;
    if (step === 1) fields = `<p class="help">先确认旅行范围。未明确提供的日期保持空白，不使用“今年”或自动推算的天数。</p><div class="fields">${briefInput('旅行名称','title',draft.title,'text','required maxlength="100"')}${briefInput('出发日期','start',draft.start,'date','required min="2000-01-01" max="2100-12-31"')}${briefInput('返程日期（包含当天）','end',draft.end,'date','required min="2000-01-01" max="2100-12-31"')}<label class="field"><span>旅行类型</span><select name="international" required><option value="">请确认</option><option value="false" ${draft.international===false?'selected':''}>国内旅行</option><option value="true" ${draft.international===true?'selected':''}>境外旅行</option></select></label></div>`;
    else if (step === 2) fields = `<p class="help">按抵达顺序填写每一站；这里的离开日期包含当天。日期可重叠以表示同日转场，仍需核对实际交通。</p><div id="assistant-brief-stops">${draft.destinations.map((row,index)=>`<fieldset class="assistant-brief-stop"><legend>第 ${index+1} 站</legend><div class="fields">${briefInput('国家 / 地区','country',row.country,'text','required maxlength="60"')}${briefInput('城市','city',row.city,'text','required maxlength="80"')}${briefInput('抵达日期','arrival',row.arrival,'date','required')}${briefInput('离开日期','departure',row.departure,'date','required')}</div><button class="btn small secondary" type="button" data-assistant-brief="remove" data-index="${index}">移除此站</button></fieldset>`).join('')}</div><button class="btn small secondary" type="button" data-assistant-brief="add" ${draft.destinations.length>=20?'disabled':''}>+ 下一站</button>`;
    else fields = `<div class="assistant-brief-review"><strong>${esc(draft.title)}</strong><p>${esc(draft.start)} — ${esc(draft.end)}</p><p>${draft.destinations.map(row=>esc(row.country+' / '+row.city+' '+row.arrival+' — '+row.departure)).join('<br>')}</p></div><p class="help">预算是你计划投入的总额，不是已核实的报价。未知请先留在简报中，明确后再进入旅行向导。</p>${briefInput('总预算（人民币元）','budgetYuan',draft.budgetCents===null?'':(draft.budgetCents/100).toFixed(2),'number','required min="0" max="1000000000" step="0.01"')}<div class="field"><span>出行成员 · 请确认</span><div class="journey-members">${(data.people||[]).map(person=>`<label class="label-check"><input type="checkbox" name="memberIds" value="${esc(person.id)}" ${draft.memberIds.includes(person.id)?'checked':''}>${esc(person.name)}</label>`).join('')}</div></div><label class="field"><span>带入旅行的备注</span><textarea name="note" rows="4" maxlength="2000">${esc(draft.note)}</textarea></label><label class="label-check"><input name="reviewed" type="checkbox" required>我已核对日期、每站停留、成员与预算；进入向导后仍需预览并确认保存。</label>`;
    openModal('旅行简报 · 从想法到安排', `<div id="assistant-workspace" class="assistant-journey-brief"><div class="assistant-brief-header"><span class="pill">${draft.mode==='model'?'AI 整理 · 待核对':'本地简报 · 逐项确认'}</span><h3>${step} / 3 · ${['','出行范围','目的地与停留','预算与成员'][step]}</h3><p class="help">${esc(draft.notice)}</p></div><details class="assistant-brief-source"><summary>原始需求（保留）</summary><p>${esc(draft.sourcePrompt || '尚未填写自由描述，可以直接完成下面的分步简报。')}</p></details><form id="assistant-journey-form">${fields}<p class="error" role="alert"></p><div class="assistant-brief-footer"><button class="btn secondary" type="button" data-assistant-brief="return">← 返回助理，保留简报</button>${step>1?'<button class="btn secondary" type="button" data-assistant-brief="previous">上一步</button>':''}<button class="btn" type="submit">${step===3?'核对并带入旅行向导 →':'下一步 →'}</button></div></form></div>`, true);
    const form = document.getElementById('assistant-journey-form'), renderedState=state;
    form.onsubmit = async event => {
      event.preventDefault(); if (busy || state!==renderedState || !form.isConnected || !form.reportValidity()) return;
      readJourneyBrief(form); const value = state.journeyDraft;
      if (step < 3) { await journeyOperation(form,async()=>{value.step++;renderJourneyBrief();}); return; }
      if (value.budgetCents === null || !Number.isSafeInteger(value.budgetCents) || !value.memberIds.length) { form.querySelector('.error').textContent='请填写准确预算，并选择至少一位出行成员。'; return; }
      await journeyOperation(form, async ({current, check, live}) => {
        if (!window.JourneyUI?.openDraft) throw new Error('旅行草稿组件尚未加载，请刷新后重试');
        const plan = {schemaVersion:1,title:value.title,start:value.start,end:value.end,international:value.international,
          budget:value.budgetCents,memberIds:[...value.memberIds],note:value.note,
          destinations:value.destinations.map((row,index)=>({...row,key:'brief-stop-'+(index+1)}))};
        const opened = await JourneyUI.openDraft(plan,{expectedContext:{identity:current.identity,csrf:current.csrf},sourceForm:form,isCurrent:live});
        if (opened && state===current && sameContext(current)) watchReturn({identity:current.identity,csrf:current.csrf,kind:'trips',id:'',title:value.title});
      });
    };
    form.addEventListener('input',()=>{if(state===renderedState && form.isConnected)readJourneyBrief(form);});
    form.addEventListener('change',()=>{if(state===renderedState && form.isConnected)readJourneyBrief(form);});
  }
  document.addEventListener('click', async event => {
    const button=event.target.closest('[data-assistant-brief]'),form=button?.closest('#assistant-journey-form');
    if(!form || busy || !state?.journeyDraft || !canEdit())return;
    readJourneyBrief(form);
    await journeyOperation(form,async({current,check})=>{
      const value=current.journeyDraft;
      if(button.dataset.assistantBrief==='return'){render();return;}
      if(button.dataset.assistantBrief==='previous')value.step--;
      if(button.dataset.assistantBrief==='add' && value.destinations.length<20)value.destinations.push({country:'',city:'',arrival:'',departure:''});
      if(button.dataset.assistantBrief==='remove')value.destinations.splice(Number(button.dataset.index),1);
      if(!value.destinations.length)value.destinations.push({country:'',city:'',arrival:'',departure:''});
      renderJourneyBrief();
    });
  });
  function attachReturn() {
    const dialog = document.getElementById('dialog');
    if (!bridge || active() || !dialog.open) return;
    const content = dialog.querySelector('.dialog-content'); if (!content) return;
    if (!content.querySelector('#assistant-return-bar')) content.insertAdjacentHTML('afterbegin', `<div id="assistant-return-bar" class="assistant-return-bar">${action('return', '← 返回本周待处理')}<small>在原页面保存；返回时重新读取处理结果。</small><p class="error" role="alert"></p></div>`);
    const form = content.querySelector('form');
    if (form && bridge.form !== form) { bridge.form = form; bridge.formSnapshot = formSnapshot(form); }
  }
  function watchReturn(context) {
    if (!document.getElementById('dialog').open) return;
    bridge = context; observer?.disconnect();
    observer = new MutationObserver(attachReturn);
    observer.observe(document.getElementById('dialog'), {childList: true, subtree: true}); attachReturn();
  }
  function readOnly(item) {
    openModal('查看共享记录', `<article class="assistant-readonly"><span class="pill">${esc(source(item))}</span><h3>${esc(item.title)}</h3><p>${owner(item)}</p>${item.start ? `<p>${esc(item.start)} — ${esc(item.end || '')}</p>` : item.due ? `<p>截止 · ${esc(item.due)}</p>` : ''}<p>${esc(item.location || '')}</p><p class="assistant-summary">${esc(item.note || '')}</p><p class="help">这项内容来自已选择的同步来源，请在原应用调整。这里不会重新创建或改写该记录。</p></article>`);
  }
  async function visit(kind, id) {
    const current = state; capture(); clearSource(); await verify(current);
    // Fetch current revision before the existing editor captures its CAS baseline.
    await refresh(true); await verify(current); if (!current.visible) return;
    const item = kind === 'finance' ? data.finance : itemIn(data, kind, id);
    if (!item) throw new Error('原记录已移除，请刷新待处理列表；没有创建替代记录');
    const context = {identity: current.identity, csrf: current.csrf, kind, id, revision: item.revision, title: kind === 'finance' ? '公共资金' : item.title};
    if (kind === 'finance') financeForm();
    else if (kind === 'trips' || (kind === 'events' && item.travelTiming && item.journeyId)) {
      if (!window.JourneyUI?.open) throw new Error('旅行组件暂不可用，请刷新后重试');
      await JourneyUI.open(item.journeyId || item.id);
    } else if (item.sync) readOnly(item);
    else editItem(kind, id);
    if (state === current && sameContext(current)) watchReturn(context);
  }
  async function returnDesk(force = false) {
    if (!bridge || !state) return;
    if (!force && bridge.form?.isConnected && bridge.form.querySelector('button[type=submit]')?.disabled) {
      document.querySelector('#assistant-return-bar .error').textContent = '表单正在保存或上传图片，请等待处理结果后再返回。'; return;
    }
    if (!force && bridge.form?.isConnected && formSnapshot(bridge.form) !== bridge.formSnapshot) {
      document.querySelector('#assistant-return-bar .error').textContent = '这个表单尚未保存。请先保存，或使用原表单的取消按钮返回。'; return;
    }
    const prior = bridge, current = state;
    bridge = null; observer?.disconnect(); observer = null;
    current.visible = true; current.notice = '正在重新读取原记录…'; current.error = '';
    // The browser cookie may have switched while the original editor was open.
    // Paint no cached record, prompt or selection until load verifies the server session.
    openModal('家庭助理 · 本周待处理', '<div id="assistant-workspace"><p class="help">正在核对登录状态并读取处理结果…</p></div>'); setBusy(true);
    try {
      await load(current);
      const item = prior.kind === 'finance' ? current.shared.finance : currentItem(prior.kind, prior.id);
      current.notice = !prior.id && prior.kind !== 'finance' ? '已返回并重新读取共享记录。' : !item ? `已读回：“${prior.title}”已移除。` : item.revision !== prior.revision ? `已读回：“${prior.title}”已更新，以下为最新记录。` : `已返回：“${prior.title}”没有发生保存变更。`;
      render();
    } catch (error) { if (state === current && current.visible) {
      current.error = '结果尚未读回：' + error.message + '。请刷新核对，不要重复提交。';
      openModal('家庭助理 · 暂未读回', `<div id="assistant-workspace"><p class="error">${esc(current.error)}</p><p class="help">尚未展示缓存内容。规划上下文仍在本页内保留，重新读取后继续。</p>${action('refresh', '重新读取')}</div>`);
    } }
    finally { if (state === current) setBusy(false); }
  }
  async function complete(id) {
    const current = state, item = currentItem('tasks', id);
    if (!item || item.done || item.sync || current.submittedTasks.has(id)) return;
    await verify(current);
    await write('/items/tasks/' + encodeURIComponent(id), 'PATCH', {done: true, revision: item.revision});
    current.submittedTasks.add(id);
    try { await load(current); current.notice = currentItem('tasks', id)?.done ? `已读回：“${item.title}”已完成。` : `已读回最新记录：“${item.title}”的当前状态已变化，请核对。`; }
    catch (error) { if (state === current) current.error = '已提交完成状态，结果尚未读回。请刷新核对，不要重复提交。'; }
    if (state === current) render();
  }
  async function plan(event) {
    event.preventDefault(); if (busy || !state) return;
    const originalForm=event.currentTarget;
    if (requestsJourney(originalForm.elements.prompt.value)) { await beginJourney(originalForm); return; }
    capture(); clearSource(); const current = state; setBusy(true);
    const errorBox = document.querySelector('#assistant-form .error'); errorBox.textContent = '';
    try {
      await verify(current);
      const draft = await write('/assistant/plan', 'POST', {prompt: current.prompt, useModel: current.useModel, includeHouseholdContext: current.includeContext});
      await verify(current);
      current.draft = draft; current.applied = null; current.selected = draft.actions.map((_, index) => index); current.composerOpen = true;
      render(); document.getElementById('assistant-result')?.scrollIntoView({block: 'start', behavior: 'smooth'});
    } catch (error) { if (state === current && errorBox.isConnected) errorBox.textContent = error.message; }
    finally { if (state === current) setBusy(false); }
  }
  async function applyDraft() {
    const current = state; if (!current.draft || current.applied) return;
    await verify(current);
    current.applied = await write('/assistant/plans/' + current.draft.id + '/apply', 'POST', {selected: current.selected});
    try {
      await load(current);
      const found = current.applied.created.filter(item => currentItem(item.kind, item.id)).length;
      current.notice = found === current.applied.created.length ? `已读回本次创建的 ${found} 项记录。` : `创建已提交，当前仍存在 ${found} / ${current.applied.created.length} 项，请核对原记录。`;
    }
    catch (error) { if (state === current) current.error = '创建已提交，结果尚未读回。请刷新核对，不要重复创建。'; }
    if (state === current) render();
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-assistant-action]'); if (!button) return;
    const name = button.dataset.assistantAction;
    if (name === 'return') { if (!busy) await returnDesk(); return; }
    if (busy || !state || !active() || !canEdit()) return;
    if (name === 'journey' || name === 'journey-local') { await beginJourney(document.getElementById('assistant-form'), name === 'journey-local'); return; }
    capture(); const current = state; current.error = ''; setBusy(true);
    try {
      if (name === 'refresh') { await load(current); current.notice = '已重新读取共享记录；规划文字与勾选保持不变。'; render(); }
      else if (name === 'jump') {
        const target = document.getElementById(button.dataset.group === 'composer' ? 'assistant-composer' : 'assistant-group-' + button.dataset.group);
        if (target) { if (target.tagName === 'DETAILS') target.open = true; target.scrollIntoView({block: 'start'}); target.focus({preventScroll: true}); }
      }
      else if (name === 'visit' && allowedKinds.has(button.dataset.kind)) await visit(button.dataset.kind, button.dataset.id);
      else if (name === 'inventory') await visitInventory(button.dataset.id);
      else if (name === 'source') await visitSource(button.dataset.kind, button.dataset.id);
      else if (name === 'search-page') await searchPage(Number(button.dataset.offset));
      else if (name === 'source-close') { clearSource(); render(); }
      else if (name === 'source-page' && current.sourceDetail) {
        await verify(current); const route=current.sourceDetail.kind==='media'?'photos':'map'; clearSource();
        closeModal(); window.ProductShell?.navigate(route);
      }
      else if (name === 'finance') await visit('finance', '');
      else if (name === 'complete') await complete(button.dataset.id);
      else if (name === 'apply') await applyDraft();
      else if (name === 'prompt') { current.prompt = button.dataset.prompt; current.journeyIntent=false; current.composerOpen = true; render(); document.querySelector('#assistant-form textarea').focus(); }
      else if (name === 'routine-plan' && !isDemo && window.HouseholdRoutines) {
        const planId=button.dataset.id;
        if (!(current.brief?.routines?.items || []).some(item=>item.id===planId)) throw new Error('例行计划已不在当前结果中，请刷新后查看');
        await verify(current); await HouseholdRoutines.open({planId});
        if (state === current && sameContext(current)) watchReturn({identity:current.identity,csrf:current.csrf,kind:'tasks',id:'',title:'家庭例行计划'});
      }
      else if (name === 'routines' && !isDemo && window.HouseholdRoutines) {
        await verify(current); await HouseholdRoutines.open();
        if (state === current && sameContext(current)) watchReturn({identity:current.identity,csrf:current.csrf,kind:'tasks',id:'',title:'家庭例行计划'});
      }
      else if (name === 'publish' && current.applied && window.TaskPublish) {
        await verify(current); await TaskPublish.open({entityIds: current.applied.created.filter(item => item.kind === 'tasks').map(item => item.id)});
        watchReturn({identity: current.identity, csrf: current.csrf, kind: 'tasks', id: '', title: '待办发布'});
      }
    } catch (error) {
      if (state !== current) return;
      if (error.status === 409) {
        try { await load(current); } catch (_) { /* Keep the last read snapshot; never retry a write. */ }
        current.error = '记录已变化，未覆盖他人的修改。请核对最新记录后再操作；规划上下文仍保留。';
      } else current.error = error.message + '；上下文仍保留，未自动重试。';
      if (sameContext(current)) render();
    } finally { if (state === current) setBusy(false); }
  });
  document.getElementById('dialog').addEventListener('close', event => {
    // A queued close event can arrive after another workflow has reopened the dialog.
    if (event.target.open) return;
    clearSource();
    const returning = bridge;
    if (returning) setTimeout(() => {
      if (!event.target.open && bridge === returning) void returnDesk(true);
    }, 0);
    else if (active() && state) { capture(); state.visible = false; sequence++; }
  });
  return {open, openJourney};
})();
