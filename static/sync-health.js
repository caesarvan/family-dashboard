/* Read-only freshness and publication guidance. Never starts a sync or cloud write. */
(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const states = ['current','waiting','delayed','error','needs_authorization','unknown'];
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const date = value => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value) : null;
  const time = value => date(value) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date(value)) : '暂无可靠记录';
  const providers = {microsoft:'Microsoft',google:'Google'};
  const sourceLabels = {current:'最近已更新',waiting:'等待首次同步',delayed:'更新已超过 5 分钟',error:'后台同步失败',needs_authorization:'需要重新授权',unknown:'更新时间待核对',not_selected:'尚未选择来源'};
  const reasons = {reauth_required:'账户授权需要更新。请到账户管理重新授权。',client_configuration_changed:'连接应用配置已变化，需要重新核对授权。',sync_failed:'后台读取没有成功，请到账户管理查看连接情况。',awaiting_first_success:'还没有首次成功记录，暂不能判断内容是否完整。',invalid_success_time:'成功时间缺失或无法核对，暂不能确认新鲜度。',stale_success:'距离上次成功已超过 5 分钟，画面可能尚未包含最近修改。',none_selected:'选择要共享的日历或清单后，才会开始同步。'};
  const publicationLabels = {pending:'等待后台处理',publishing:'正在发布',retry:'暂时失败 · 已排队重试',needs_authorization:'需要补充授权',permission_denied:'目标拒绝写入',conflict:'两边内容变化 · 待处理',error:'发布失败 · 待核对',paused:'已暂停',local_deleted:'本地已删除 · 云端保留',remote_deleted:'云端已删除 · 本地保留',disconnected:'来源已断开',uncertain:'创建结果尚未确认',needs_review:'修改需要再次核对'};
  const publicationNotes = {pending:'等待后台读取队列；进入管理页可查看进度。',publishing:'写入可能已发出，请到管理页核对结果。',retry:'后台按已排定的时间重试；这里的刷新只读取状态。',needs_authorization:'到原发布页核对目标及所需权限。',permission_denied:'请核对原目标是否允许当前账户编辑。',conflict:'请对比两边内容，再明确选择处理方式。',error:'请到原发布页核对原因和处理方式。',paused:'自动发布已暂停；打开管理页不会自行恢复。',local_deleted:'原本地事项已移除，云端内容没有被自动删除。',remote_deleted:'原云端事项已移除，本地内容仍保留。',disconnected:'本地内容保留；请在原发布页核对重连目标。',uncertain:'先核对原创建结果，避免重复创建。',needs_review:'请核对变化，再明确确认后续发布。'};
  let current = null;

  // These two public formatters accept either /state.sync.health or {household: health}.
  // They read no DOM, session, clock or private data, and never mutate their input.
  function summary(health) {
    const h = health?.household || health;
    const unknown = {tone:'unknown',title:'同步状态待核对',detail:'尚未取得完整的来源状态。',h:null};
    if (!h || typeof h !== 'object') return unknown;
    const selected=count(h.selectedSources), accounts=count(h.connectedAccounts), reauth=count(h.reauthAccounts);
    const counts=states.map(state=>count(h.sourceCounts?.[state]));
    if (selected===null || accounts===null || reauth===null || counts.some(value=>value===null) || counts.reduce((a,b)=>a+b,0)!==selected) return unknown;
    const c=h.sourceCounts, shared={h};
    if (h.state==='not_connected' && accounts===0 && selected===0 && reauth===0) return {...shared,tone:'neutral',title:'尚未连接日历与清单',detail:'连接账户并选择来源后，才会开始同步。'};
    if (h.state==='not_selected' && accounts>0 && selected===0 && reauth===0) return {...shared,tone:'neutral',title:'已连接账户，尚未选择来源',detail:'请选择要展示的日历或清单。'};
    if (reauth || c.error || c.needs_authorization || c.delayed || c.unknown) {
      const parts=[];
      if(c.error)parts.push(`${c.error} 个来源读取失败`);
      if(c.delayed)parts.push(`${c.delayed} 个来源超过 5 分钟未更新`);
      if(c.unknown)parts.push(`${c.unknown} 个来源时间待核对`);
      if(reauth || c.needs_authorization)parts.push('有授权需要处理');
      if(c.waiting)parts.push(`${c.waiting} 个来源等待首次同步`);
      return {...shared,tone:'attention',title:'部分同步需要关注',detail:parts.join('；')+'。'};
    }
    if (h.state==='waiting' && selected>0 && c.waiting>0) return {...shared,tone:'waiting',title:'等待来源首次同步',detail:`${c.current} / ${selected} 个来源已有近期成功记录；其余仍在等待。`};
    if (h.state==='current' && selected>0 && c.current===selected && date(h.lastCompleteSuccess)) return {...shared,tone:'current',title:`全部 ${selected} 个来源最近已更新`,detail:`覆盖全部来源的成功时间：${time(h.lastCompleteSuccess)}（北京时间）。`};
    return unknown;
  }
  function summaryText(health) { return summary(health).title; }
  function summaryMarkup(health, options={}) {
    const state=summary(health), demo=options.demo===true, offline=options.online===false;
    const tone=demo?'neutral':offline?'unknown':state.tone;
    const title=demo?'演示模式 · 不读取真实同步状态':offline?'连接中断 · 显示上次状态':state.title;
    const detail=demo?'账户和发布队列需要登录后查看。':offline?`上次记录：${state.title}。恢复连接后请重新核对。`:state.detail;
    return `<div class="sh-summary" data-sync-tone="${tone}"><span class="sh-signal" aria-hidden="true"></span><div><strong>${escape(title)}</strong><p>${escape(detail)}</p></div>${options.showAction&&!demo?'<button type="button" class="btn small secondary" data-sync-health-open>查看同步与问题</button>':''}</div>`;
  }
  function refreshIndicators() {
    const health=typeof data!=='undefined'?data?.sync?.health:null;
    const options={showAction:typeof canEdit==='function'&&canEdit(),demo:typeof isDemo!=='undefined'&&isDemo,online:typeof online==='undefined'||online};
    const markup=summaryMarkup(health,options);
    for(const node of document.querySelectorAll('[data-sync-health-summary]')) {
      // checkedAt and a single source's latestSuccess do not change this semantic markup.
      if(node._syncHealthMarkup===markup || node.innerHTML===markup){node._syncHealthMarkup=markup;continue;}
      const focused=node.contains(document.activeElement)&&document.activeElement?.hasAttribute('data-sync-health-open');
      node.innerHTML=markup;node._syncHealthMarkup=markup;
      if(focused)node.querySelector('[data-sync-health-open]')?.focus({preventScroll:true});
    }
  }

  const actor=()=>({id:user?.id,household:user?.householdId||'default',version:user?.auth_version,csrf});
  const matches=(owner,person,token)=>person?.role==='member'&&person.id===owner.id&&(person.householdId||'default')===owner.household&&person.auth_version===owner.version&&token===owner.csrf;
  const permitted=()=>!isDemo&&!isTV&&canEdit();
  const owns=flow=>current===flow&&flow.node.isConnected&&document.querySelector('#dialog')?.open&&document.querySelector('#dialog .dialog-content')?.contains(flow.node);
  function neutral(flow, uncertain=false) {
    if(!owns(flow))return;
    ++flow.epoch;flow.health=null;
    flow.node.innerHTML=`<section class="sh-empty"><span class="sh-symbol" aria-hidden="true">?</span><h3>${uncertain?'暂时无法核对登录状态':'登录或家庭已变化'}</h3><p>请刷新页面，再查看当前成员的同步状态。</p><a class="btn secondary" href="/">刷新页面</a></section>`;
  }
  async function verify(flow,active) {
    if(!active())return false;
    if(!permitted()||!matches(flow.actor,user,csrf))throw Object.assign(new Error('identity'),{identityChanged:true});
    const me=await api('/me');
    if(!active())return false;
    if(!permitted()||!matches(flow.actor,user,csrf)||!matches(flow.actor,me.user,me.csrf))throw Object.assign(new Error('identity'),{identityChanged:true});
    return true;
  }
  function loading() {
    return '<section class="sh-empty"><span class="sh-symbol sh-breathe" aria-hidden="true">↻</span><h3>正在核对同步状态</h3><p>先确认当前成员，再读取来源和发布队列。</p><div data-sh-message role="status" aria-live="polite"></div><button class="btn secondary" type="button" data-sh="refresh">重新读取</button></section>';
  }
  function message(flow,text) {const node=flow.node.querySelector('[data-sh-message]');if(node)node.textContent=text;}
  async function operation(flow,button,work,onFailure) {
    if(!owns(flow))return;
    const epoch=++flow.epoch,view=flow.node.firstElementChild;
    const active=()=>owns(flow)&&flow.epoch===epoch&&view?.isConnected&&flow.node.contains(view);
    if(button){button._syncHealthJob=epoch;button.disabled=true;}
    try {
      if(!await verify(flow,active))return;
      await work({active,verify:()=>verify(flow,active)});
    } catch(error) {
      if(!active())return;
      if(error.identityChanged||error.status===401){neutral(flow);return;}
      try {if(!await verify(flow,active))return;}
      catch(identityError){if(active())neutral(flow,!identityError.identityChanged&&identityError.status!==401);return;}
      if(active()){if(onFailure)onFailure();else message(flow,'暂时无法打开管理页面，请稍后重试。');}
    } finally {if(button?.isConnected&&button._syncHealthJob===epoch)button.disabled=false;}
  }
  function age(value) {
    if(!Number.isFinite(value)||value<0)return '距今时间待核对';
    if(value<60)return '距该次核对不足 1 分钟';
    if(value<3600)return `距该次核对 ${Math.floor(value/60)} 分钟`;
    if(value<86400)return `距该次核对 ${Math.floor(value/3600)} 小时`;
    return `距该次核对 ${Math.floor(value/86400)} 天`;
  }
  function sourceMarkup(source) {
    const state=states.includes(source.state)?source.state:'unknown';
    const reason=reasons[source.reasonCode]||(state==='current'?'本次核对时，最近成功记录在 5 分钟内。':state==='unknown'?reasons.invalid_success_time:'请在账户管理核对来源状态。');
    return `<li class="sh-source" data-sh-source-state="${state}"><div class="sh-source-top"><strong>${escape(source.name||'未命名来源')}</strong><span class="sh-badge" data-sync-tone="${state==='current'?'current':state==='waiting'?'waiting':'attention'}">${escape(sourceLabels[state])}</span></div><div class="sh-source-kind">${source.kind==='calendar'?'日历':source.kind==='tasks'?'待办清单':'同步来源'}${source.primary?' · 家庭主清单':''}</div><p>${escape(reason)}</p><dl><div><dt>上次成功</dt><dd>${escape(time(source.lastSuccess))}</dd></div>${date(source.lastSuccess)?`<div><dt>记录新鲜度</dt><dd>${escape(age(source.ageSeconds))}</dd></div>`:''}${date(source.nextAttemptAt)?`<div><dt>下次已排定检查</dt><dd>${escape(time(source.nextAttemptAt))}</dd></div>`:''}</dl></li>`;
  }
  function accountMarkup(account) {
    const state=Object.hasOwn(sourceLabels,account.state)?account.state:'unknown';
    const sources=Array.isArray(account.sources)?account.sources:[];
    return `<article class="sh-account"><header><span class="sh-provider" aria-hidden="true">${account.provider==='google'?'G':account.provider==='microsoft'?'M':'↻'}</span><div><h4>${escape(providers[account.provider]||'云账户')}</h4><p>${escape(account.label||'本人绑定的账户')}</p></div><span class="sh-badge" data-sync-tone="${state==='current'?'current':state==='not_selected'?'neutral':'attention'}">${escape(sourceLabels[state])}</span></header>${reasons[account.reasonCode]?`<p class="sh-account-note">${escape(reasons[account.reasonCode])}</p>`:''}${sources.length?`<ul class="sh-sources">${sources.map(sourceMarkup).join('')}</ul>`:'<div class="sh-inline-empty">此账户还没有选择可同步的来源。</div>'}</article>`;
  }
  function publicationMarkup(item,kind,index) {
    const status=item.reviewRequired?'needs_review':item.status;
    const actionable=item.action?.kind===kind&&typeof item.action.target==='string'&&item.action.target.length>0;
    return `<article class="sh-publication" data-sh-publication-status="${escape(status||'unknown')}"><div class="sh-publication-top"><span class="sh-badge">${kind==='calendar'?'旅行日历':'待办发布'}</span><span>${escape(publicationLabels[status]||'状态需要核对')}</span></div><h4>${escape(item.title||'原事项暂不可用')}</h4><p>${escape(publicationNotes[status]||'请在原管理页面核对发布状态。')}</p>${date(item.nextAttemptAt)?`<p class="sh-caption">下次已排定处理：${escape(time(item.nextAttemptAt))}</p>`:''}${actionable?`<button type="button" class="btn small secondary" data-sh="publication" data-sh-kind="${kind}" data-sh-index="${index}">${kind==='calendar'?'查看原旅行发布':'查看原待办发布'}</button>`:'<p class="sh-caption">原事项或管理入口已不可用，此处不重新创建。</p>'}</article>`;
  }
  function render(flow,stale=false) {
    const health=flow.health,h=health.household;
    const groups=['calendar','tasks'].map(kind=>({kind,...health.publications[kind]}));
    const issues=groups.reduce((total,group)=>total+group.items.length,0);
    const published=groups.reduce((total,group)=>total+(count(group.counts?.published)||0),0);
    flow.node.innerHTML=`<section class="sh-view"><header class="sh-intro"><div><div class="sh-eyebrow">SYNC & CONNECTIONS</div><h3>知道哪些已更新，哪些需要处理</h3><p>来源读取与日程、待办发布分开核对。查看状态不会触发同步或云端写入。</p></div><button class="btn secondary" type="button" data-sh="refresh">刷新状态</button></header>${stale?'<div class="sh-stale" role="status">本次刷新失败 · 下方保留上次成功读取的状态，可能已经过时。请稍后重新读取。</div>':''}<div class="sh-family"><div class="sh-section-heading"><h4>家庭来源概况</h4><span>仅聚合状态</span></div>${summaryMarkup(h,{online:!stale})}<div class="sh-metrics"><div><b>${escape(count(h.selectedSources)??'—')}</b><span>已选来源</span></div><div><b>${escape(count(h.sourceCounts?.current)??'—')}</b><span>5 分钟内成功</span></div><div><b>${escape(count(h.sourceCounts?.waiting)??'—')}</b><span>等待首次同步</span></div></div><p class="sh-caption">家庭摘要包含双方来源；伴侣的账户和来源详情不在这里展示。来源成功读取不代表发布队列已完成。</p></div><div class="sh-columns"><section><div class="sh-section-heading"><h4>我的账户与来源</h4><span>${health.accounts.length} 个账户</span></div><div class="sh-account-list">${health.accounts.map(accountMarkup).join('')||'<div class="sh-inline-empty"><h4>你还没有连接账户</h4><p>先连接 Microsoft 或 Google，再选择日历和清单。伴侣已连接的账户不会显示在你的详情中。</p></div>'}</div><button class="btn secondary sh-manage" type="button" data-sh="accounts">${health.accounts.length?'管理我的账户与来源':'连接我的账户'}</button></section><section><div class="sh-section-heading"><h4>发布状态与问题</h4><span>${issues} 项待核对或处理中</span></div><p class="sh-caption sh-publication-scope">仅显示本人可管理的项目；${published} 项已发布。打开原管理页后，仍由你明确决定是否处理。</p><div class="sh-publications">${groups.map(group=>group.items.map((item,index)=>publicationMarkup(item,group.kind,index)).join('')).join('')||'<div class="sh-inline-empty"><h4>当前没有需处理的发布项</h4><p>此处只检查本人可管理的队列，不代表伴侣的发布队列状态。</p></div>'}</div>${groups.some(group=>group.truncated)?'<p class="sh-caption">部分项目未在此展开，请进入对应管理页继续核对。</p>':''}</section></div><footer class="sh-footnote">此次读取：${escape(time(health.checkedAt))}（北京时间）。来源超过 5 分钟没有成功记录会标记为延迟；这不是服务时效保证。弹窗不会自动刷新。</footer><div class="sh-message" data-sh-message role="status" aria-live="polite"></div></section>`;
  }
  async function refresh(flow) {
    if(!owns(flow))return;
    // Do not leave private cached detail visible while a cross-tab identity check is pending.
    flow.node.innerHTML=loading();
    return operation(flow,null,async job=>{
      const result=await api('/sync-health');
      if(!job.active()||!await job.verify())return;
      if(result?.version!==1||!result.household||!Array.isArray(result.accounts)||!['calendar','tasks'].every(kind=>Array.isArray(result.publications?.[kind]?.items)))throw new Error('invalid_response');
      flow.health=result;render(flow);
    },()=>{
      if(flow.health)render(flow,true);
      else message(flow,'暂时无法读取同步状态。尚未取得结果，不能确认各来源是否正常。请重新读取。');
    });
  }
  function navigate(flow,button) {
    const kind=button.dataset.shKind,index=Number(button.dataset.shIndex);
    const item=kind&&flow.health?.publications?.[kind]?.items?.[index];
    const target=['calendar','tasks'].includes(kind)&&item?.action?.kind===kind&&typeof item.action.target==='string'?item.action.target:null;
    const action=button.dataset.sh;
    if(action==='publication'&&(!target||!['calendar','tasks'].includes(kind)))return;
    return operation(flow,button,async job=>{
      if(!job.active())return;
      const expectedContext={identity:JSON.stringify([flow.actor.household,flow.actor.id,flow.actor.version]),csrf:flow.actor.csrf};
      if(action==='accounts'&&typeof accountsModal==='function'){await accountsModal();return;}
      if(kind==='calendar'&&window.CalendarPublish?.open){await window.CalendarPublish.open(target,expectedContext);return;}
      if(kind==='tasks'&&window.TaskPublish?.open){await window.TaskPublish.open({entityIds:[target]},expectedContext);return;}
      message(flow,'管理模块暂时不可用，请刷新页面后重试。');
    });
  }
  async function open() {
    if(!permitted())return;
    openModal('同步新鲜度与问题中心','<div class="sync-health" data-sync-health-root>'+loading()+'</div>',true);
    const flow={actor:actor(),node:document.querySelector('#dialog [data-sync-health-root]'),epoch:0,health:null};
    current=flow;await refresh(flow);
  }
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-sync-health-open]')){void open();return;}
    const button=event.target.closest('[data-sh]'),flow=current;
    if(!button||!flow||!owns(flow)||!flow.node.contains(button))return;
    if(button.dataset.sh==='refresh')void refresh(flow);
    else if(['accounts','publication'].includes(button.dataset.sh))void navigate(flow,button);
  });
  document.querySelector('#dialog')?.addEventListener('close',()=>{
    // A queued close event from the previous dialog must not invalidate a newly opened flow.
    if(!document.querySelector('#dialog')?.open&&current){current.epoch++;current.health=null;current=null;}
  });
  window.SyncHealth={open,summaryMarkup,summaryText,refreshIndicators};
})();
