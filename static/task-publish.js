/* Consent-bound publishing of selected local tasks. Demo never calls an API. */
'use strict';
window.TaskPublish=(()=>{
  let scope={},state=null,pending=null,conflict=null,timer=null,view=0,context=null;
  const labels={pending:'等待同步',publishing:'正在写入',published:'已连接 · 持续同步',retry:'暂时失败 · 自动重试',uncertain:'创建结果待核对',needs_review:'需要再次核对',needs_authorization:'待办权限待授权',permission_denied:'清单拒绝访问',conflict:'两边内容变化 · 等待处理',paused:'已暂停',disconnected:'来源已断开 · 本地保留',remote_deleted:'云端已删除 · 本地保留',local_deleted:'本地已删除 · 云端保留'};
  const providers={microsoft:'Microsoft To Do',google:'Google Tasks'};
  const stop=()=>{clearTimeout(timer);timer=null};
  function query(){const p=new URLSearchParams();if(scope.journeyId)p.set('journeyId',scope.journeyId);else if(scope.entityIds?.length)p.set('entityIds',scope.entityIds.join(','));return '/task-publish/state?'+p}
  function error(err){const box=document.querySelector('#task-publish-error');if(box)box.textContent=err.message;else toast(err.message)}
  async function guardedWrite(path,method,payload){
    const ticket=view,ctx=context,content=document.querySelector('#dialog .dialog-content');
    await AccountsReturn.verify(ctx);
    if(ticket!==view||!content?.isConnected)throw new Error('页面已改变，请重新预览待办');
    const result=await write(path,method,payload);await AccountsReturn.verify(ctx);
    if(ticket!==view||!content.isConnected)throw new Error('页面已改变，请重新预览待办');
    return result;
  }
  async function open(options={},expectedContext){
    if(!canEdit()&&!(typeof isDemo!=='undefined'&&isDemo))return;stop();const ticket=++view;scope=typeof options==='string'?{journeyId:options}:structuredClone(options||{});pending=null;conflict=null;
    if(typeof isDemo!=='undefined'&&isDemo){openModal('连接待办主清单','<div class="info-box">演示模式展示旅行与待办流程。登录家庭空间后，可以选择本人已绑定的 Microsoft To Do 或 Google Tasks 清单，预览确认后同步；这里不会连接或写入真实账户。</div>',true);return}
    openModal('连接待办主清单','<p class="help" id="task-publish-loading">正在读取待办与已授权清单…</p>',true);
    const marker=document.querySelector('#task-publish-loading'),path=query();
    try{const ctx=expectedContext||await AccountsReturn.capture();await AccountsReturn.verify(ctx);if(ticket!==view||!marker.isConnected)return;
      const result=await api(path);await AccountsReturn.verify(ctx);if(ticket!==view||!marker.isConnected)return;
      context=ctx;state=result;render();schedule();
    }catch(err){if(ticket===view&&marker.isConnected)openModal('连接待办主清单',`<div class="error" role="alert">${esc(err.message)}</div>`,true)}
  }
  function rows(){
    const names=Object.fromEntries(state.tasks.map(t=>[t.id,t.title]));
    return state.publications.map(p=>`<article class="fh-transaction"><div class="fh-transaction-main"><strong>${esc(names[p.entityId]||'已关联待办')}</strong><small>${esc(providers[p.provider])} · ${esc(labels[p.status]||p.status)}</small>${p.error?`<p class="error">${esc(p.error)}</p>`:''}</div>${p.canManage?`<div class="fh-transaction-value">${['retry','uncertain','needs_review','needs_authorization','permission_denied','disconnected'].includes(p.status)?`<button class="btn small secondary" data-tp="retry" data-id="${esc(p.id)}">${['uncertain','needs_review'].includes(p.status)?'再次核对':'重试'}</button>`:''}${p.status==='paused'?`<button class="btn small secondary" data-tp="resume" data-id="${esc(p.id)}">恢复同步</button>`:''}${p.status==='conflict'?`<button class="btn small secondary" data-tp="conflict-preview" data-id="${esc(p.id)}">对比并处理</button>`:''}${!['paused','local_deleted','remote_deleted','disconnected'].includes(p.status)?`<button class="btn small secondary" data-tp="pause" data-id="${esc(p.id)}">暂停</button>`:''}</div>`:'<small>由确认成员或账户拥有者管理</small>'}</article>`).join('')||'<p class="help">尚未连接任何待办。仅勾选并确认的项目会同步。</p>';
  }
  function render(){
    const linked=new Set(state.publications.map(p=>p.entityId));
    const emptyStart=!scope.journeyId && !scope.entityIds?.length && !state.tasks.length;
    const start=`<div class="info-box" data-task-start><h4>从第一件待办开始</h4><p>先把要做的事记在家庭清单里，暂不连接账户也能使用。${state.sources.length?'已有可用清单；保存本地待办后，可再选择要同步的项目。':'也可以先设置常用清单，再回来安排。'}</p><div class="dialog-footer"><button type="button" class="btn" data-tp="add-first">添加第一件待办</button><button type="button" class="btn secondary" data-tp="task-setup">${state.sources.length?'管理常用清单':'先设置常用清单'}</button></div><p class="help">本地待办由家人共同查看；同步到云端仍需选择、预览和确认。</p></div>`;
    openModal('连接待办主清单',`<div class="fh-workspace" id="task-publish-root"><div><div class="eyebrow">YOUR TASKS, CONNECTED</div><h3>把准备事项带到常用清单</h3><p class="help">本人已绑定清单可作为目标。家庭主清单由该账户拥有者明确开放给双方使用；看板负责人保留，不会转换成云端指派。</p></div>${emptyStart?start:state.sources.length?`<form id="task-publish-form"><label class="field"><span>同步到哪份清单</span><select name="sourceId">${state.sources.map(s=>`<option value="${esc(s.id)}">${esc(providers[s.provider])} · ${esc(s.name)}${s.primary?' · 家庭主清单':''}${!s.writeAuthorized?' · 需重新授权':''}</option>`).join('')}</select></label><p class="help">请勾选本次需要同步的项目。已连接项目保留原绑定。</p><div class="fh-ledger">${state.tasks.map(t=>`<label class="fh-transaction"><input type="checkbox" name="entityId" value="${esc(t.id)}" ${linked.has(t.id)?'disabled':''}><div class="fh-transaction-main"><strong>${esc(t.title)}</strong><small>${esc(person(t.owner))} · ${esc(t.due||'未设截止日期')} · ${t.done?'已完成':'未完成'}${linked.has(t.id)?(state.publications.find(p=>p.entityId===t.id)?.status==='disconnected'?' · 来源已断开，可勾选重连原清单':' · 已连接'):''}</small></div></label>`).join('')||'<p class="help">当前没有可选的本地待办。</p>'}</div><button class="btn" type="submit">预览选中待办</button></form>`:'<div class="info-box"><p>尚无可用的目标清单。连接本人账户并选择来源后，可返回这里重新选择待办；伴侣也可明确开放家庭主清单。</p><button class="btn secondary" data-tp="connect">连接账户或选择来源</button></div>'}<section><div class="fh-section-title"><h4>同步进度</h4><button class="btn small secondary" data-tp="refresh">刷新</button></div><div id="task-publications">${rows()}</div></section><div class="error" id="task-publish-error" role="alert"></div><p class="fh-note">${esc(state.note)}</p>${scope.journeyId?'<button class="btn secondary" data-tp="back">返回旅行计划</button>':''}</div>`,true);
    const form=document.querySelector('#task-publish-form');
    if(form){
      const updateChoices=()=>{for(const input of form.querySelectorAll('[name=entityId]')){const p=state.publications.find(p=>p.entityId===input.value);input.disabled=!!p&&!p.reconnectSourceIds?.includes(form.elements.sourceId.value);if(input.disabled)input.checked=false}};
      form.elements.sourceId.onchange=updateChoices;updateChoices();
    }
    if(form)form.onsubmit=async e=>{
      e.preventDefault();const ticket=view,b=form.querySelector('button[type=submit]');b.disabled=true;
      try{
        const entityIds=[...form.querySelectorAll('[name=entityId]:checked')].map(i=>i.value);
        if(!entityIds.length)throw new Error('请先勾选本次要连接的待办');
        const p=await guardedWrite('/task-publish/preview','POST',{sourceId:form.elements.sourceId.value,entityIds});pending=p.previewToken;stop();
        openModal('确认连接选中待办',`<div class="fh-workspace"><h3>${esc(providers[p.source.provider])} · ${esc(p.source.name)}${p.source.primary?' · 家庭主清单':''}</h3>${!p.source.writeAuthorized?'<div class="info-box">账户缺少待办写权限。可以先确认，账户拥有者重新绑定后再重试；授权前不会写入。</div>':''}<div class="fh-ledger">${p.tasks.map(t=>`<article class="fh-transaction"><div class="fh-transaction-main"><strong>${esc(t.title)}</strong><small>${esc(person(t.owner))} · ${esc(t.due||'未设截止日期')} · ${t.done?'已完成':'未完成'}${t.reconnect?' · 重新连接原清单（保留已有云端任务）':''}</small><p class="help">${esc(t.note)}</p></div></article>`).join('')}</div><p class="fh-note">${esc(p.note)}</p><div class="error" id="task-publish-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-tp="refresh">返回选择</button><button class="btn" data-tp="confirm">确认连接这 ${p.tasks.length} 项待办</button></div></div>`,true);
      }catch(err){if(ticket===view&&form.isConnected)error(err)}finally{b.disabled=false}
    };
  }
  function schedule(){stop();const ticket=view,ctx=context;timer=setTimeout(async()=>{
    const root=document.querySelector('#task-publish-root');if(!root||!canEdit()||ticket!==view)return;
    try{await AccountsReturn.verify(ctx);const result=await api(query());await AccountsReturn.verify(ctx);if(ticket!==view||!root.isConnected)return;
      state=result;const list=document.querySelector('#task-publications');if(list)list.innerHTML=rows();schedule();
    }catch(err){if(ticket===view&&root.isConnected)error(err)}
  },5000)}
  document.querySelector('#dialog')?.addEventListener('close',()=>{stop();view++;pending=null;conflict=null});
  document.addEventListener('click',async e=>{
    if(e.target.closest('[data-task-publish-open]')){await open();return}
    const b=e.target.closest('[data-tp]');if(!b||!canEdit()||b.disabled)return;let ticket=view;const content=b.closest('.dialog-content');
    try{
      const action=b.dataset.tp;b.disabled=true;
      if(action==='refresh'){await open(scope);return}
      if(action==='add-first' || action==='task-setup'){
        stop();ticket=++view;pending=null;conflict=null;
        const choices=[...content.querySelectorAll('[data-tp=add-first],[data-tp=task-setup]')];
        choices.forEach(button=>button.disabled=true);
        try {
          if(action==='add-first') await ProductShell.openTasks({create:true,originNode:b},context);
          else await AccountsReturn.begin({kind:'task-setup'},context);
        } finally {
          if(ticket===view && content.isConnected) choices.forEach(button=>button.disabled=false);
        }
        return;
      }
      if(action==='back'){stop();view++;await JourneyUI.open(scope.journeyId);return}
      if(action==='connect'){stop();ticket=++view;pending=null;conflict=null;
        const target=scope.journeyId?{kind:'tasks',journeyId:scope.journeyId}:{kind:'tasks',entityIds:scope.entityIds?.length?[...scope.entityIds]:state.tasks.map(t=>t.id)};
        await AccountsReturn.begin(target,context);return;
      }
      if(action==='confirm'){
        if(!pending)throw new Error('请重新预览待办');
        await guardedWrite('/task-publish/confirm','POST',{previewToken:pending});pending=null;await open(scope);toast('已连接选中待办，同步进度会自动更新');return;
      }
      if(action==='conflict-preview'){
        const p=await guardedWrite('/task-publish/publications/'+encodeURIComponent(b.dataset.id)+'/conflict-preview','POST',{});conflict={id:b.dataset.id,previewToken:p.previewToken};stop();
        const fields=v=>`<h4>${esc(v.title)}</h4><p>${esc(v.due||'未设截止日期')} · ${v.done?'已完成':'未完成'}</p><p class="help">${esc(v.note)}</p>`;
        openModal('核对两边待办内容',`<div class="fh-workspace"><div class="journey-detail-grid"><section class="journey-panel"><h3>看板本地</h3>${fields(p.local)}</section><section class="journey-panel"><h3>云端清单</h3>${fields(p.remote)}</section></div><p class="help">只有确认后才会更新。采用云端内容仍保留本地负责人、旅行关联和原任务 ID。</p><div class="error" id="task-publish-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-tp="refresh">暂不处理</button><button class="btn secondary" data-tp="resolve" data-resolution="remote">采用云端内容</button><button class="btn" data-tp="resolve" data-resolution="local">确认以本地更新云端</button></div></div>`,true);return;
      }
      if(action==='resolve'){
        if(!conflict)throw new Error('请重新对比待办');
        await guardedWrite('/task-publish/publications/'+encodeURIComponent(conflict.id)+'/conflict-confirm','POST',{previewToken:conflict.previewToken,resolution:b.dataset.resolution});conflict=null;await refresh();await open(scope);return;
      }
      if(['pause','resume','retry'].includes(action)){await guardedWrite('/task-publish/publications/'+encodeURIComponent(b.dataset.id)+'/'+action,'POST',{});await open(scope)}
    }catch(err){if(ticket===view&&content?.isConnected)error(err)}finally{b.disabled=false}
  });
  return {open};
})();
