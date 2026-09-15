/* Explicit calendar-write consent and durable journey publication status. */
'use strict';
window.CalendarPublish = (()=>{
  let journeyId='', state=null, pending=null, timer=null, conflict=null, view=0, context=null;
  const statuses={pending:'等待发布',publishing:'正在写入云日历',published:'已发布 · 持续同步',retry:'暂时失败 · 等待重试',needs_authorization:'等待日历写权限',permission_denied:'该日历无编辑权限',conflict:'云端变更 · 已暂停',error:'重试失败 · 需核对',paused:'已停止自动发布',local_deleted:'本地已删除 · 云端保留',needs_review:'旅行时间变化 · 待核对'};
  const providers={microsoft:'Microsoft',google:'Google'};
  const eventRange=event=>event.allDay?`${event.start.slice(0,10)} 至 ${new Date(Date.parse(event.end.slice(0,10)+'T12:00:00Z')-86400000).toISOString().slice(0,10)} · 全天`:`${displayDate(event.start)} ${displayTime(event.start)} → ${displayDate(event.end)} ${displayTime(event.end)}`;
  function stop(){clearTimeout(timer);timer=null}
  async function guardedWrite(path,method,payload){
    const ticket=view,ctx=context,content=document.querySelector('#dialog .dialog-content');
    await AccountsReturn.verify(ctx);
    if(ticket!==view||!content?.isConnected)throw new Error('页面已改变，请重新预览日程');
    const result=await write(path,method,payload);await AccountsReturn.verify(ctx);
    if(ticket!==view||!content.isConnected)throw new Error('页面已改变，请重新预览日程');
    return result;
  }
  async function open(id,expectedContext){
    if(!canEdit())return;stop();const ticket=++view;journeyId=id;pending=null;conflict=null;
    openModal('同步旅行到云日历','<p class="help" id="calendar-publish-loading">正在读取旅行日程与账户权限…</p>',true);
    const marker=document.querySelector('#calendar-publish-loading');
    try{const ctx=expectedContext||await AccountsReturn.capture();await AccountsReturn.verify(ctx);if(ticket!==view||!marker.isConnected)return;
      const result=await api('/calendar-publish/journeys/'+encodeURIComponent(id));await AccountsReturn.verify(ctx);if(ticket!==view||!marker.isConnected)return;
      context=ctx;state=result;render();schedule();
    }catch(err){if(ticket===view&&marker.isConnected)openModal('同步旅行到云日历',`<div class="error" role="alert">${esc(err.message)}</div>`,true)}
  }
  function publicationRows(){
    const names=Object.fromEntries(state.events.map(e=>[e.id,e.title]));
    return state.publications.length?state.publications.map(p=>`<article class="fh-transaction"><div class="fh-transaction-main"><strong>${esc(names[p.entityId]||'原日程已移除')}</strong><small>${esc(providers[p.provider]||p.provider)} · ${esc(statuses[p.status]||p.status)}</small>${p.error?`<p class="error">${esc(p.error)}</p>`:''}</div><div class="fh-transaction-value">${p.reviewRequired?`<button class="btn small secondary" data-cp="review-preview" data-id="${esc(p.id)}">核对旅行时间变化</button>`:''}${!p.reviewRequired&&['retry','error','needs_authorization','permission_denied','paused'].includes(p.status)?`<button class="btn small secondary" data-cp="${p.status==='paused'?'resume':'retry'}" data-id="${esc(p.id)}">${p.status==='paused'?'恢复持续同步':'重试'}</button>`:''}${!p.reviewRequired&&p.status==='conflict'?`<button class="btn small secondary" data-cp="conflict-preview" data-id="${esc(p.id)}">对比并处理</button>`:''}${p.status!=='paused'&&p.status!=='local_deleted'?`<button class="btn small secondary" data-cp="pause" data-id="${esc(p.id)}">停止同步</button>`:''}</div></article>`).join(''):'<p class="help">这份旅行尚未请求发布到云日历。</p>';
  }
  function render(){
    const accounts=[...new Map(state.sources.filter(s=>!s.writeAuthorized).map(s=>[s.accountId,s])).values()];
    openModal('同步旅行到云日历',`<div class="fh-workspace" id="calendar-publish-root" data-journey-id="${esc(journeyId)}"><div><div class="eyebrow">YOUR PLANS, CONNECTED</div><h3>让行程出现在每天使用的日历里</h3><p class="help">当前旅行有 ${state.events.length} 项日程。选择你本人绑定的日历，确认后会持续同步本地修改。</p></div>${state.sources.length?`<form id="calendar-publish-form"><label class="field"><span>发布到哪个日历</span><select name="sourceId">${state.sources.map(s=>`<option value="${esc(s.id)}">${esc(providers[s.provider])} · ${esc(s.accountName)} · ${esc(s.name)}${s.writeAuthorized?'':' · 需要写入授权'}</option>`).join('')}</select></label><button class="btn" type="submit">预览待发布日程</button></form>`:`<div class="info-box"><p>尚无可用的目标日历。连接本人账户并选择日历后，可返回这里重新预览旅行日程。</p><button class="btn secondary" data-cp="connect">连接账户或选择来源</button></div>`}${accounts.length?`<section class="fh-section"><h4>授权旅行日程写入</h4><p class="help">读取日历和创建日程使用不同权限。只有点击下方按钮，才会向平台请求额外的日历编辑授权；请使用原来绑定的同一个账户。</p>${accounts.map(s=>`<div class="fh-section-title"><span>${esc(providers[s.provider])} · ${esc(s.accountName)}</span><button class="btn small secondary" data-cp="authorize" data-account="${esc(s.accountId)}">开启日历写入</button></div>`).join('')}</section>`:''}<section><div class="fh-section-title"><h4>发布进度</h4><button class="btn small secondary" data-cp="refresh">刷新</button></div><div id="calendar-publications">${publicationRows()}</div></section><div class="error" id="calendar-publish-error" role="alert"></div><p class="fh-note">${esc(state.note)} 只创建你自己的日历事项，不添加参与者或发送邀请。</p><div><button class="btn secondary" data-cp="back">返回旅行计划</button></div></div>`,true);
    const form=document.querySelector('#calendar-publish-form');
    if(form)form.onsubmit=async e=>{
      e.preventDefault();const ticket=view,b=form.querySelector('button');b.disabled=true;
      try{
        pending={journeyId,sourceId:form.elements.sourceId.value};
        const p=await guardedWrite('/calendar-publish/preview','POST',pending);pending.previewToken=p.previewToken;stop();
        openModal('确认发布旅行日程',`<div class="fh-workspace"><h3>${esc(providers[p.source.provider])} · ${esc(p.source.name)}</h3>${p.source.writeAuthorized?'':`<div class="info-box">此账户尚未授予日历写权限。你可以先确认加入队列，授权完成后才会发布。</div>`}<div class="fh-ledger">${p.events.map(ev=>`<article class="fh-transaction"><div class="fh-transaction-main"><strong>${esc(ev.title)}</strong><small>${esc(eventRange(ev))}</small><small>${esc(ev.location)}</small></div></article>`).join('')}</div><p class="fh-note">${esc(p.note)}</p><div class="error" id="calendar-publish-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-cp="refresh">返回</button><button class="btn" data-cp="confirm">确认并加入发布队列</button></div></div>`,true);
      }catch(err){const box=document.querySelector('#calendar-publish-error');if(ticket===view&&form.isConnected&&box)box.textContent=err.message}
      finally{b.disabled=false}
    };
  }
  function schedule(){
    stop();const ticket=view,ctx=context;timer=setTimeout(async()=>{
      const root=document.querySelector('#calendar-publish-root');if(!root||ticket!==view||!canEdit())return;
      try{await AccountsReturn.verify(ctx);const result=await api('/calendar-publish/journeys/'+encodeURIComponent(journeyId));await AccountsReturn.verify(ctx);
        if(ticket!==view||!root.isConnected)return;state=result;const list=document.querySelector('#calendar-publications');if(list)list.innerHTML=publicationRows();schedule();
      }catch(err){const box=document.querySelector('#calendar-publish-error');if(ticket===view&&root.isConnected&&box)box.textContent=err.message}
    },5000);
  }
  document.querySelector('#dialog')?.addEventListener('close',()=>{stop();view++;pending=null;conflict=null});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-cp]');if(!b||!canEdit())return;let ticket=view;const content=b.closest('.dialog-content');
    try{
      const a=b.dataset.cp;
      if(a==='refresh'){await open(journeyId);return}
      if(a==='back'){stop();view++;if(window.JourneyUI?.open)await JourneyUI.open(journeyId);else closeModal();return}
      b.disabled=true;
      if(a==='connect'){stop();ticket=++view;pending=null;conflict=null;await AccountsReturn.begin({kind:'calendar',journeyId},context);return}
      if(a==='authorize'){
        const r=await guardedWrite('/calendar-publish/authorize','POST',{accountId:b.dataset.account});
        const u=new URL(r.url);if(u.protocol!=='https:'||!['login.microsoftonline.com','accounts.google.com'].includes(u.hostname))throw new Error('授权地址无效');
        const ticket=view;await AccountsReturn.prepareOAuth({kind:'calendar',journeyId},context);await AccountsReturn.verify(context);
        if(ticket!==view||!b.isConnected)throw new Error('页面已改变，请重新开启日历写入');
        location.assign(r.url);return;
      }
      if(a==='confirm'){
        if(!pending)throw new Error('请重新预览日程');
        const r=await guardedWrite('/calendar-publish/confirm','POST',pending);pending=null;await open(journeyId);toast(r.needsAuthorization?'已加入队列，完成日历写入授权后继续':'已加入发布队列，进度会自动更新');return;
      }
      if(a==='review-preview'){
        const r=await guardedWrite('/calendar-publish/publications/'+encodeURIComponent(b.dataset.id)+'/review-preview','POST',{});
        conflict={id:b.dataset.id,previewToken:r.previewToken,review:true};stop();
        const values=v=>v?`<h4>${esc(v.title)}</h4><p class="help">${esc(eventRange(v))}</p><p>${esc(v.location)}</p><p class="help">${esc(v.note)}</p>`:'<p class="help">目前未找到对应的云端事项。确认后将先核对原发布标识，再创建。</p>';
        openModal('核对旅行时间变化',`<div class="fh-workspace"><section class="fh-section"><h3>新的旅行日程</h3>${values(r.local)}</section><section class="fh-section"><h3>云端当前内容</h3>${values(r.remote)}</section>${r.previous?`<details class="fh-section"><summary>此前等待发布的内容</summary>${values(r.previous)}</details>`:''}<p class="fh-note">${esc(r.note)}</p><div class="error" id="calendar-publish-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-cp="pause" data-id="${esc(conflict.id)}">保留云端并停止同步</button><button class="btn" data-cp="review-confirm">确认变化并恢复发布</button></div></div>`,true);return;
      }
      if(a==='review-confirm'){
        if(!conflict?.review)throw new Error('请先核对旅行时间变化');
        await guardedWrite('/calendar-publish/publications/'+encodeURIComponent(conflict.id)+'/review-confirm','POST',{previewToken:conflict.previewToken});conflict=null;await open(journeyId);return;
      }
      if(a==='conflict-preview'){
        const r=await guardedWrite('/calendar-publish/publications/'+encodeURIComponent(b.dataset.id)+'/conflict-preview','POST',{});
        conflict={id:b.dataset.id,previewToken:r.previewToken};stop();
        const values=v=>`<h4>${esc(v.title)}</h4><p class="help">${esc(eventRange(v))}</p><p>${esc(v.location)}</p><p class="help">${esc(v.note)}</p>`;
        openModal('核对云端修改',`<div class="fh-workspace"><section class="fh-section"><h3>本地旅行计划</h3>${values(r.local)}</section><section class="fh-section"><h3>云端当前内容</h3>${values(r.remote)}</section><p class="fh-note">${esc(r.note)}</p><div class="error" id="calendar-publish-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-cp="pause" data-id="${esc(conflict.id)}">保留云端并停止同步</button><button class="btn" data-cp="conflict-confirm">确认以本地内容更新云端</button></div></div>`,true);return;
      }
      if(a==='conflict-confirm'){
        if(!conflict)throw new Error('请重新核对两边内容');
        await guardedWrite('/calendar-publish/publications/'+encodeURIComponent(conflict.id)+'/conflict-confirm','POST',{previewToken:conflict.previewToken});conflict=null;await open(journeyId);return;
      }
      if(a==='retry'||a==='pause'||a==='resume'){
        await guardedWrite('/calendar-publish/publications/'+encodeURIComponent(b.dataset.id)+'/'+a,'POST',{});await open(journeyId);return;
      }
    }catch(err){const error=document.querySelector('#calendar-publish-error');if(ticket===view&&content?.isConnected){if(error)error.textContent=err.message;else toast(err.message)}b.disabled=false}
  });
  return {open};
})();
