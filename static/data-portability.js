/* Export responses belong to the original member, browser session and dialog. */
window.DataPortability = (() => {
  'use strict';
  let current = null, generation = 0;
  const urls = new Set();
  const permitted = () => !isDemo && !isTV && canEdit();
  const actor = () => ({id:user?.id, household:user?.householdId||'default', version:user?.auth_version, csrf});
  const matches = (owner, person, token) => person?.role==='member' && person.id===owner.id &&
    (person.householdId||'default')===owner.household && person.auth_version===owner.version && token===owner.csrf;
  const mounted = flow => current===flow && !flow.invalid && flow.generation===generation &&
    flow.route===location.href && flow.node.isConnected && document.querySelector('#dialog')?.open &&
    document.querySelector('#dialog .dialog-content')?.contains(flow.node);
  const identityError = () => Object.assign(new Error('登录状态已变化，请刷新页面后重新导出。'), {identityChanged:true});
  function active(flow) {
    if (!mounted(flow)) return false;
    if (!permitted() || !matches(flow.actor,user,csrf)) throw identityError();
    return true;
  }
  function invalidate() {
    if (!current) return;
    current.invalid=true;
    current.controller.abort(); // A server may already have accepted the request; guards remain authoritative.
    current=null;
    ++generation;
  }
  function neutral(flow) {
    if (!mounted(flow)) return;
    flow.node.innerHTML='<p role="status">登录状态已变化，请刷新页面后重新导出当前账户的数据。</p><a class="btn secondary" href="/">刷新页面</a>';
    flow.invalid=true;
    flow.controller.abort();
  }
  async function json(flow, path) {
    if (!active(flow)) return null;
    const response=await fetch('/api'+path, {credentials:'same-origin',cache:'no-store',signal:flow.controller.signal});
    if (!active(flow)) return null;
    let result;
    try { result=await response.json(); }
    catch (_) {
      if (!active(flow)) return null;
      throw Object.assign(new Error('服务暂时不可用，请稍后重试。'),{status:response.status});
    }
    if (!active(flow)) return null;
    if (!response.ok) throw Object.assign(new Error(result.error||'服务暂时不可用，请稍后重试。'),{status:response.status});
    return result;
  }
  async function verify(flow) {
    const identity=await json(flow,'/me');
    if (!active(flow)) return false;
    if (!identity || !matches(flow.actor,identity.user,identity.csrf)) throw identityError();
    return true;
  }
  async function failed(flow, error) {
    if (!mounted(flow)) return;
    if (error.identityChanged || error.status===401) { neutral(flow); return; }
    try { if (!await verify(flow)) return; }
    catch (check) {
      if (!mounted(flow)) return;
      if (check.identityChanged || check.status===401) { neutral(flow); return; }
      // An unavailable identity endpoint cannot authorize redisplaying private counts.
      flow.node.querySelector('.info-box')?.remove();
      error=new Error('暂时无法核对登录状态，请稍后重试。');
    }
    if (!mounted(flow)) return;
    flow.node.querySelector('.error').textContent=error.message||'导出未完成，请稍后重试。';
    const status=flow.node.querySelector('#portability-status');
    if (status) status.textContent='';
  }
  function render(flow, summary) {
    if (!active(flow)) return;
    flow.node.innerHTML='<p>下载一份属于你的数据副本，可在电脑上查看和留存。</p>'+
      '<div class="info-box">'+(Number(summary.personal.transactions)||0)+' 条账单与订单 · '+(Number(summary.personal.investments)||0)+' 项投资 · '+(Number(summary.personal.budgets)||0)+' 项预算 · '+(Number(summary.personal.inventoryItems)||0)+' 件本人物品</div>'+
      '<p class="help">包含本人财务基线、偏好、助理草案和物品记录；物品来源关联与操作摘要仅限本人。不含伴侣的私人财务与账号凭据。参考图片仅保留编号和尺寸。</p>'+
      '<form id="portability-form"><label class="label-check"><input type="checkbox" name="includeShared">附带双方已共享的日程、待办、采购、旅行、物品和共同资金记录</label>'+
      '<p class="help">ZIP 内含 JSON 完整文字与 CSV 表格。它是当前保存记录的副本，不能证明所有账户都已覆盖，也不会在下载后删除记录。</p>'+
      '<p class="error" role="alert"></p><button type="submit" class="btn">下载数据副本</button><p id="portability-status" role="status" aria-live="polite"></p></form>';
    flow.node.querySelector('#portability-form').onsubmit=event=>{event.preventDefault();void download(flow,event.currentTarget);};
  }
  async function download(flow, form) {
    if (!mounted(flow) || flow.busy || !flow.node.contains(form)) return;
    // Capture the user's choice once, before any identity request can yield.
    const includeShared=form.elements.includeShared.checked;
    const button=form.querySelector('[type=submit]'), checkbox=form.elements.includeShared, status=form.querySelector('#portability-status');
    flow.busy=true; button.disabled=true; checkbox.disabled=true;
    status.textContent='正在准备下载…'; form.querySelector('.error').textContent='';
    try {
      if (!await verify(flow)) return;
      const response=await fetch('/api/portability/export',{
        method:'POST',credentials:'same-origin',cache:'no-store',signal:flow.controller.signal,
        headers:{'Content-Type':'application/json','X-CSRF-Token':flow.actor.csrf},body:JSON.stringify({includeShared})
      });
      if (!active(flow)) return;
      if (!response.ok) {
        const failure=await response.json().catch(()=>({}));
        if (!active(flow)) return;
        throw Object.assign(new Error(failure.error||'导出未完成，请稍后重试。'),{status:response.status});
      }
      if (!/^application\/zip(?:\s*;|\s*$)/i.test(response.headers.get('content-type')||'')) throw new Error('下载格式不正确，请重试。');
      const blob=await response.blob();
      if (!active(flow) || !await verify(flow)) return;
      // No await between the last identity check and the synchronous download click.
      const url=URL.createObjectURL(blob), link=document.createElement('a');
      urls.add(url);
      let started=false;
      try {
        const match=/filename="?(family-data-[A-Za-z0-9_-]+\.zip)"?/.exec(response.headers.get('content-disposition')||'');
        link.href=url; link.download=match?.[1]||'family-data.zip'; document.body.appendChild(link);link.click();started=true;
      } finally {
        link.remove();
        if (started) setTimeout(()=>{URL.revokeObjectURL(url);urls.delete(url);},30000);
        else {URL.revokeObjectURL(url);urls.delete(url);}
      }
      status.textContent='已开始下载。文件含个人资料与财务内容，请保存在你控制的设备上。';
    } catch (error) { await failed(flow,error); }
    finally {
      flow.busy=false;
      if (mounted(flow) && flow.node.contains(form)) {button.disabled=false;checkbox.disabled=false;}
    }
  }
  async function open() {
    if (!permitted()) {toast('请登录后导出自己的数据');return;}
    invalidate();
    // Capture identity and install a neutral owned node before the first await.
    const owner=actor();
    openModal('导出我的数据','<section id="portability-loading"><p role="status">正在核对登录状态…</p><p class="error" role="alert"></p><button class="btn secondary" type="button" data-portability-retry>重试</button></section>',true);
    const flow={actor:owner,node:document.querySelector('#portability-loading'),generation:++generation,route:location.href,controller:new AbortController(),invalid:false,busy:false};
    current=flow;
    flow.node.querySelector('[data-portability-retry]').onclick=()=>{void open();};
    try {
      if (!await verify(flow)) return;
      const summary=await json(flow,'/portability/summary');
      if (!active(flow) || !await verify(flow)) return;
      render(flow,summary);
    } catch (error) { await failed(flow,error); }
  }
  document.addEventListener('click',event=>{if(event.target.closest('[data-portability-open]'))void open();});
  const dialog=document.querySelector('#dialog');
  if (dialog) {
    // A queued close event from an earlier dialog must not invalidate a newly opened one.
    dialog.addEventListener('close',()=>{if(!dialog.open)invalidate();});
    new MutationObserver(()=>{if(current&&!mounted(current))invalidate();}).observe(dialog,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});
  }
  window.addEventListener('popstate',()=>{if(current&&current.route!==location.href)invalidate();});
  window.addEventListener('hashchange',()=>{if(current&&current.route!==location.href)invalidate();});
  window.addEventListener('pagehide',()=>{invalidate();for(const url of urls)URL.revokeObjectURL(url);urls.clear();});
  return {open};
})();
