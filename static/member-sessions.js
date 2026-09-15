/* Member-only browser sessions. No credentials or device fingerprints are stored here. */
(() => {
  'use strict';
  let current = null;
  const actor = () => ({id:user?.id, household:user?.householdId||'default', csrf});
  const matches = (owner, person, token) => person?.role==='member' && person.id===owner.id &&
    (person.householdId||'default')===owner.household && token===owner.csrf;
  const permitted = () => !isDemo && !isTV && canEdit();
  const owns = flow => current===flow && flow.node.isConnected &&
    document.querySelector('#dialog')?.open && document.querySelector('#dialog .dialog-content')?.contains(flow.node);
  const time = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '暂不可用' : new Intl.DateTimeFormat('zh-CN', {
      year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false
    }).format(date);
  };
  const neutral = flow => {
    if (!owns(flow)) return;
    ++flow.epoch;
    flow.sessions = [];
    flow.node.innerHTML = '<section class="ms-empty"><h3>登录状态已变化</h3><p>请刷新页面后，再查看当前账户的登录设备。</p><a class="btn secondary" href="/">刷新页面</a></section>';
  };
  async function verify(flow, active) {
    if (!active()) return false;
    if (!permitted() || !matches(flow.actor,user,csrf)) {
      const error = new Error('登录状态已变化'); error.identityChanged = true; throw error;
    }
    const identity = await api('/me');
    if (!active()) return false;
    if (!permitted() || !matches(flow.actor,user,csrf) || !matches(flow.actor,identity.user,identity.csrf)) {
      const error = new Error('登录状态已变化'); error.identityChanged = true; throw error;
    }
    return true;
  }
  function message(flow, text, bad=false) {
    const box = flow.node.querySelector('.ms-message');
    if (box) { box.textContent=text; box.classList.toggle('error',bad); }
  }
  async function operation(flow, button, work, writing=false) {
    if (!owns(flow)) return;
    const view = flow.node.firstElementChild, epoch = ++flow.epoch;
    const active = () => owns(flow) && flow.epoch===epoch && view?.isConnected && flow.node.contains(view);
    if (button) { button._memberSessionJob=epoch; button.disabled=true; }
    message(flow,'');
    let sent = false;
    try {
      if (!await verify(flow,active)) return;
      await work({active, verify:()=>verify(flow,active), sent:()=>{sent=true;}});
    } catch (error) {
      if (!active()) return;
      if (error.identityChanged || error.status===401) { neutral(flow); return; }
      try { if (!await verify(flow,active)) return; }
      catch (identityError) {
        if (!active()) return;
        // A failed identity check cannot authorize redisplaying cached device details.
        neutral(flow); return;
      }
      if (!active()) return;
      const suffix = writing && sent ? ' 请求可能已经执行；请刷新列表核对结果，已发送的请求不会因关闭窗口而取消。' : '';
      message(flow,(error.message||'暂时无法读取，请重试。')+suffix,true);
    } finally {
      // Each button releases its own job, including superseded requests on another button.
      if (button?.isConnected && button._memberSessionJob===epoch) button.disabled=false;
    }
  }
  const loading = () => '<section class="ms-empty"><span class="ms-symbol">'+icon('lock')+'</span><h3>正在核对登录状态</h3><p>仅显示当前账户的有效浏览器会话。</p><div class="ms-message" role="status" aria-live="polite"></div><button class="btn secondary" data-ms="refresh">重试</button></section>';
  function render(flow, note='') {
    const others=flow.sessions.filter(item=>!item.current).length;
    flow.node.innerHTML=`<section class="ms-view"><div class="ms-intro"><span class="ms-symbol">${icon('lock')}</span><div><h3>管理我的登录</h3><p>仅本人可见。退出不再使用的浏览器，让账户保持在自己手中。</p></div></div><div class="ms-toolbar"><span>${flow.sessions.length} 个有效会话</span><button class="btn small secondary" data-ms="refresh">刷新列表</button></div><div class="ms-list">${flow.sessions.map(item=>`<article class="ms-card ${item.current?'is-current':''}" data-ms-id="${esc(item.id)}"><div class="ms-card-heading"><h4>${esc(item.device||'浏览器会话')}</h4><span class="ms-badge ${item.current?'current':''}">${item.current?'当前浏览器':'其他会话'}</span></div><dl><div><dt>上次使用</dt><dd>${esc(time(item.lastSeenAt))}</dd></div><div><dt>登录时间</dt><dd>${esc(time(item.createdAt))}</dd></div><div><dt>到期时间</dt><dd>${esc(time(item.expiresAt))}</dd></div></dl>${item.current?'<p class="ms-current-note">退出当前浏览器，请使用设置页底部的「退出登录」。</p>':`<button class="btn small secondary ms-revoke" data-ms="review" data-ms-id="${esc(item.id)}">退出此会话</button>`}</article>`).join('')||'<p class="help">没有可显示的有效会话，请刷新页面重新登录。</p>'}</div><p class="ms-footnote">名称只概括浏览器和系统，不能精确识别物理设备。上次使用约每 ${Math.max(1,Math.round(flow.interval/60))} 分钟更新；时间按当前浏览器时区显示。</p><div class="ms-message" role="status" aria-live="polite">${esc(note)}</div><div class="ms-footer"><button class="btn secondary ms-revoke" data-ms="review-others" ${others?'':'disabled'}>退出其他全部会话${others?'（'+others+'）':''}</button></div></section>`;
  }
  async function read(flow, job, note='') {
    const result = await api('/sessions');
    if (!job.active() || !await job.verify()) return;
    flow.sessions = Array.isArray(result.sessions) ? result.sessions.slice().sort((a,b)=>Number(b.current)-Number(a.current)) : [];
    flow.interval = Number(result.lastSeenIntervalSeconds)||300;
    render(flow,note);
  }
  function refresh(flow, button) {
    return operation(flow,button,job=>read(flow,job));
  }
  function review(flow, button, all) {
    // Capture the original record before awaiting; never recover a target from a later view.
    const selected=all ? null : flow.sessions.find(item=>item.id===button.dataset.msId && !item.current);
    if (!all && !selected) return;
    const target=all?{all:true}:{all:false,id:selected.id,device:selected.device};
    return operation(flow,button,async job=>{
      if (!job.active()) return;
      flow.node.innerHTML=`<section class="ms-confirm"><span class="ms-symbol">${icon('exit')}</span><h3>${target.all?'退出其他全部会话？':'退出这个浏览器会话？'}</h3><p>${target.all?'当前浏览器继续保持登录，其他有效会话将需要重新登录。':`「${esc(target.device||'浏览器会话')}」将需要重新登录。当前浏览器不受影响。`}</p><p class="ms-footnote">操作只退出家庭看板，不会解绑 Microsoft 或 Google 账户。</p><div class="ms-message" role="status" aria-live="polite"></div><div class="ms-confirm-actions"><button class="btn secondary" data-ms="refresh">返回列表</button><button class="btn ms-danger" data-ms="confirm">确认退出</button></div></section>`;
      const confirm=flow.node.querySelector('[data-ms="confirm"]');
      confirm.addEventListener('click',()=>revoke(flow,confirm,target));
    });
  }
  function revoke(flow, button, target) {
    return operation(flow,button,async job=>{
      // Identity was freshly checked by operation before this exact original request is sent.
      job.sent();
      const result=await api(target.all?'/sessions/revoke-others':'/sessions/'+encodeURIComponent(target.id),{
        method:target.all?'POST':'DELETE',body:'{}',headers:{'X-CSRF-Token':flow.actor.csrf}
      });
      if (!job.active() || !await job.verify()) return;
      await read(flow,job,target.all?`已退出 ${Number(result.revoked)||0} 个其他会话。`:'已退出所选会话。');
    },true);
  }
  async function open() {
    if (!permitted()) return;
    openModal('登录设备','<div class="member-sessions">'+loading()+'</div>');
    const flow={actor:actor(),node:document.querySelector('#dialog .member-sessions'),epoch:0,sessions:[],interval:300};
    current=flow;
    await refresh(flow,null);
  }
  document.addEventListener('click',event=>{
    if (event.target.closest('[data-member-sessions-open]')) { void open(); return; }
    const button=event.target.closest('[data-ms]'), flow=current;
    if (!button || !flow || !owns(flow) || !flow.node.contains(button)) return;
    if (button.dataset.ms==='refresh') void refresh(flow,button);
    if (button.dataset.ms==='review') void review(flow,button,false);
    if (button.dataset.ms==='review-others') void review(flow,button,true);
  });
  window.MemberSessions={open};
})();
