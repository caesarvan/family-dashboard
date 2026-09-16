/* Per-screen presentation. Preview content is illustrative; no private data is fetched. */
(() => {
  'use strict';
  const KEYS=['calendar','finance','tasks','shopping','trips'];
  const LABELS={calendar:'日程安排',finance:'家庭财务',tasks:'共同待办',shopping:'采购清单',trips:'下一趟旅行'};
  const SELECTORS={calendar:'.calendar-card',finance:'.finance-card',tasks:'.tasks-card',shopping:'.shopping-card',trips:'.travel-card'};
  const defaults=()=>({order:[...KEYS],hidden:[],theme:'forest',density:'comfortable'});
  const copy=value=>JSON.parse(JSON.stringify(value));
  let current=null;
  function layout(value) {
    const base=defaults();
    if(!value||!Array.isArray(value.order)||value.order.length!==5||new Set(value.order).size!==5||value.order.some(k=>!KEYS.includes(k)))return base;
    const hidden=Array.isArray(value.hidden)?[...new Set(value.hidden)].filter(k=>KEYS.includes(k)):[];
    return {order:[...value.order],hidden:hidden.length<5?hidden:[],theme:['forest','light','ocean'].includes(value.theme)?value.theme:'forest',density:value.density==='compact'?'compact':'comfortable'};
  }
  const permitted=()=>!isDemo&&!isTV&&canEdit();
  const actor=()=>({id:user.id,household:user.householdId||'default',csrf});
  const matches=(a,u,t)=>u?.role==='member'&&u.id===a.id&&(u.householdId||'default')===a.household&&t===a.csrf;
  const owns=f=>current===f&&f.node.isConnected&&document.querySelector('#dialog')?.open&&document.querySelector('#dialog .dialog-content')?.contains(f.node);
  const model=d=>({name:d.name,focus:d.focus,calendarView:d.calendarView||'today',layout:layout(d.layout)});
  function draft(f) {
    const form=f.node.querySelector('#tv-display-form');
    if(!form)return copy(f.draft);
    const values=new FormData(form);
    const shown=[...form.querySelectorAll('input[name="visible"]')].filter(input=>input.checked).map(input=>input.value);
    return {name:String(values.get('name')||''),focus:String(values.get('focus')||'shared'),calendarView:String(values.get('calendarView')||'today'),layout:{order:[...f.draft.layout.order],hidden:KEYS.filter(k=>!shown.includes(k)),theme:String(values.get('theme')),density:String(values.get('density'))}};
  }
  function note(f,text,bad=false) {
    const box=f.node.querySelector('[data-tv-message]');
    if(box){box.textContent=text;box.classList.toggle('error',bad);}
  }
  function neutral(f) {
    if(!owns(f))return;
    ++f.epoch;f.device=null;f.draft=null;f.latest=null;
    f.node.innerHTML='<section class="tvd-neutral"><h3>暂时无法确认当前家庭</h3><p>请刷新页面后重新打开电视设置。旧家庭的设置已隐藏。</p><a class="btn secondary" href="/">刷新页面</a></section>';
  }
  async function verify(f,active) {
    if(!active())return false;
    if(!permitted()||!matches(f.actor,user,csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e;}
    const me=await api('/me');
    if(!active())return false;
    if(!permitted()||!matches(f.actor,user,csrf)||!matches(f.actor,me.user,me.csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e;}
    return true;
  }
  async function operation(f,button,work,{snapshot=true,writing=false}={}) {
    if(!owns(f))return;
    const view=f.node.firstElementChild,form=f.node.querySelector('#tv-display-form'),before=form&&snapshot?JSON.stringify(draft(f)):null,epoch=++f.epoch;
    const active=()=>owns(f)&&epoch===f.epoch&&view?.isConnected&&f.node.contains(view)&&(!form||(form.isConnected&&f.node.contains(form)))&&(before===null||JSON.stringify(draft(f))===before);
    if(button){button.disabled=true;button._tvDisplayJob=epoch;}
    note(f,'');let sent=false;
    try {
      if(!await verify(f,active))return;
      await work({active,verify:()=>verify(f,active),sent:()=>{sent=true;}});
    }catch(e){
      if(!active())return;
      if(e.identityChanged||e.status===401){neutral(f);return;}
      try{if(!await verify(f,active))return;}catch(_){if(active())neutral(f);return;}
      if(!active())return;
      if(e.status===409){f.conflict=true;f.latest=null;conflict(f);note(f,'这台电视已被另一设备修改。你的草稿仍在，请读取最新设置后决定如何继续。',true);}
      else note(f,(e.message||'读取失败，请重试。')+(writing&&sent?' 请求可能已经保存；请读取最新设置核对。关闭窗口不会取消已发送的请求。':''),true);
    }finally{if(button?.isConnected&&button._tvDisplayJob===epoch)button.disabled=button.dataset.tvDisplayAction==='save'&&(f.conflict||f.saving);}
  }
  function grid(board,order,hidden) {
    const visible=order.filter(k=>!hidden.includes(k));
    board.dataset.tvCount=String(visible.length);
    for(const key of order){const card=board.querySelector(`[data-tv-card="${key}"]`);if(card){card.hidden=hidden.includes(key);board.append(card);}}
    // The same spans drive the editor's 16:9 preview and the actual television.
    visible.forEach((key,i)=>{const card=board.querySelector(`[data-tv-card="${key}"]`);if(card)card.dataset.tvSpan=String(visible.length===1?12:visible.length===3&&i===0?12:visible.length===5&&i>1?4:6);});
  }
  function preview(f) {
    const value=draft(f),box=f.node.querySelector('[data-tv-preview]');
    if(!box)return;
    box.dataset.tvTheme=value.layout.theme;box.dataset.tvDensity=value.layout.density;
    box.querySelector('[data-tv-preview-name]').textContent=value.name||'这块电视';
    box.querySelector('[data-tv-preview-view]').textContent=({today:'今日',week:'本周',around:'前后 3 天'})[value.calendarView]||'今日';
    grid(box.querySelector('.tvd-preview-grid'),value.layout.order,value.layout.hidden);
    const count=value.layout.order.length-value.layout.hidden.length;
    f.node.querySelector('[data-tv-visible-count]').textContent=`显示 ${count} / 5 张`;
    f.node.querySelectorAll('[data-tv-card-row]').forEach((row,i)=>{
      const k=row.dataset.tvCardRow,show=!value.layout.hidden.includes(k);
      row.classList.toggle('is-hidden',!show);
      row.querySelector('input').disabled=show&&count===1;
      row.querySelector('[data-tv-display-action="up"]').disabled=i===0;
      row.querySelector('[data-tv-display-action="down"]').disabled=i===4;
    });
  }
  function conflict(f) {
    const box=f.node.querySelector('[data-tv-conflict]');if(!box)return;
    box.hidden=!f.conflict;
    box.innerHTML=f.latest?'<strong>已读取最新设置</strong><p>选择采用服务器设置，或以最新版本为基础保留当前草稿。后者仍需再次点击保存，会替换这台电视的全部显示设置。</p><div><button type="button" class="btn small secondary" data-tv-display-action="use-latest">采用最新设置</button><button type="button" class="btn small secondary" data-tv-display-action="keep-draft">用最新版本保留我的草稿</button></div>':'<strong>设置版本有变化</strong><p>读取不会覆盖你的草稿。</p><button type="button" class="btn small secondary" data-tv-display-action="reload">读取最新设置</button>';
    const save=f.node.querySelector('[data-tv-display-action="save"]');if(save)save.disabled=!!f.conflict||!!f.saving;
  }
  function render(f,message='') {
    const value=f.draft,l=value.layout;
    const people=data?.household?.id===f.actor.household?data.people:[{id:'member1',name:'成员一'},{id:'member2',name:'成员二'}];
    const options=[{id:'shared',name:'一起'},...(people||[])].map(p=>`<option value="${esc(p.id)}" ${value.focus===p.id?'selected':''}>${esc(p.name)}</option>`).join('');
    f.node.innerHTML=`<form id="tv-display-form"><div class="tvd-intro"><span>${icon('tv')}</span><div><h3>让这块屏幕，适合这个家</h3><p>设置只作用于所选电视，手机和另一台电视保持各自布局。</p></div></div><div class="tvd-editor-grid"><section class="tvd-controls"><div class="fields">${field('电视名称','name',value.name,'text','required maxlength="30"')}${selectField('侧重成员','focus',options)}${selectField('日程视图','calendarView',viewOptions(value.calendarView))}${selectField('内容密度','density',`<option value="comfortable" ${l.density==='comfortable'?'selected':''}>舒适 · 留白更多</option><option value="compact" ${l.density==='compact'?'selected':''}>紧凑 · 内容更密</option>`)}</div><fieldset class="tvd-themes"><legend>屏幕主题</legend>${[['forest','森林'],['light','晴日'],['ocean','海岸']].map(([key,label])=>`<label class="tvd-theme" data-theme-choice="${key}"><input type="radio" name="theme" value="${key}" ${key===l.theme?'checked':''}><i aria-hidden="true"></i><span>${label}</span></label>`).join('')}</fieldset><div class="tvd-list-heading"><h4>卡片顺序与显示</h4><span data-tv-visible-count></span></div><p class="tvd-hint">顺序按从左到右、从上到下排列。至少保留一张。</p><div class="tvd-card-list">${l.order.map(key=>`<div class="tvd-card-row" data-tv-card-row="${key}"><label><input type="checkbox" name="visible" value="${key}" ${l.hidden.includes(key)?'':'checked'}><span>${LABELS[key]}</span></label><div><button class="tvd-move" type="button" data-tv-display-action="up" data-key="${key}" aria-label="上移${LABELS[key]}">↑</button><button class="tvd-move" type="button" data-tv-display-action="down" data-key="${key}" aria-label="下移${LABELS[key]}">↓</button></div></div>`).join('')}</div><button class="tvd-reset" type="button" data-tv-display-action="reset">恢复默认布局与外观</button></section><aside class="tvd-preview-column"><div class="tvd-preview-caption"><span>屏幕预览</span><small>16:9 · 布局示意</small></div><div class="tvd-preview" data-tv-preview><header><b data-tv-preview-name></b><span data-tv-preview-view></span></header><div class="tvd-preview-grid">${KEYS.map(key=>`<section data-tv-card="${key}"><b>${LABELS[key]}</b><div class="tvd-sample-lines" aria-hidden="true"><i></i><i></i><i></i></div></section>`).join('')}</div><footer>只读显示 · 自动更新</footer></div><p class="tvd-hint">预览与电视使用相同排布和主题，内容为示意，不读取个人财务。电视按实际屏幕宽度调整字号；长日程和采购仍自动翻页。</p><div class="tvd-live-note">${icon('check')}保存后约 10 秒同步到这台电视。</div></aside></div><div class="tvd-conflict" data-tv-conflict hidden></div><div data-tv-message role="status" aria-live="polite">${esc(message)}</div><div class="tvd-footer"><button type="button" class="btn secondary" data-tv-display-action="back">返回电视列表</button><button type="button" class="btn secondary" data-tv-display-action="reload">读取最新设置</button><button type="submit" class="btn" data-tv-display-action="save">保存到这台电视</button></div></form>`;
    preview(f);conflict(f);
    f.node.querySelector('form').addEventListener('input',()=>{if(!matches(f.actor,user,csrf)){neutral(f);return;}f.draft=draft(f);preview(f);});
    f.node.querySelector('form').addEventListener('submit',event=>{event.preventDefault();void save(f,event.submitter||f.node.querySelector('[data-tv-display-action="save"]'));});
    f.mediaCleanup?.();
    if(window.MediaTV){const control=document.createElement('section');f.node.append(control);f.mediaCleanup=window.MediaTV.mountControls(control,f.id,{getIdentity:()=>({user,csrf,isTV,isDemo})});}
  }
  async function readDevice(f,job) {
    const devices=await api('/devices');
    if(!job.active()||!await job.verify())return null;
    const device=devices.find(d=>d.id===f.id);
    if(!device){const e=new Error('这台电视已撤销，请返回电视列表。');e.status=404;throw e;}
    return device;
  }
  function reload(f,button,initial=false) {
    return operation(f,button,async job=>{
      const device=await readDevice(f,job);if(!device||!job.active())return;
      if(initial){f.device=device;f.draft=model(device);render(f);}
      else {f.latest=device;f.conflict=true;conflict(f);note(f,'最新设置已读取，你的草稿未被替换。');}
    });
  }
  async function save(f,button) {
    if(f.saving||f.conflict||!f.device)return;
    const payload={...draft(f),revision:f.device.revision};
    const snapshot=JSON.stringify(draft(f));let sent=false,completed=false;
    // One outstanding save per editor, including identity checks and readback. Editing does not cancel a sent PATCH.
    f.saving=true;
    try {
      await operation(f,button,async job=>{
        job.sent();sent=true;await api('/devices/'+encodeURIComponent(f.id),{method:'PATCH',body:JSON.stringify(payload),headers:{'X-CSRF-Token':f.actor.csrf}});
        if(!job.active()||!await job.verify())return;
        const device=await readDevice(f,job);if(!device||!job.active())return;
        completed=true;f.device=device;f.draft=model(device);f.latest=null;f.conflict=false;render(f,'已保存并读取服务器设置，电视将在约 10 秒内更新。');
      },{writing:true});
    }finally{
      f.saving=false;
      if(owns(f)&&f.draft){
        if(!permitted()||!matches(f.actor,user,csrf)){neutral(f);return;}
        if(sent&&!completed&&JSON.stringify(draft(f))!==snapshot){f.conflict=true;f.latest=null;note(f,'原保存请求已经发送，当前草稿仍保留。请读取最新设置核对，再决定是否保存这些新修改。');}
        conflict(f);
      }
    }
  }
  async function openDevice(id) {
    if(!permitted())return;
    openModal('电视显示设置','<div data-tv-display><section class="tvd-neutral"><h3>正在读取这台电视的设置</h3><p>先核对当前家庭，再显示设备信息。</p><div data-tv-message role="status"></div><button class="btn secondary" data-tv-display-action="initial">重试</button></section></div>',true);
    const f={id:String(id),actor:actor(),node:document.querySelector('[data-tv-display]'),epoch:0,device:null,draft:null,latest:null,conflict:false};current=f;
    await reload(f,null,true);
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-tv-display-action]'),f=current;
    if(!button||!f||!owns(f)||!f.node.contains(button)||button.disabled)return;
    const action=button.dataset.tvDisplayAction;if(action==='save')return;
    if(!matches(f.actor,user,csrf)){neutral(f);return;}
    if(action==='initial'){void reload(f,button,true);return;}
    if(action==='reload'){void reload(f,button);return;}
    if(action==='back'){void operation(f,button,async job=>{const changed=JSON.stringify(draft(f))!==JSON.stringify(model(f.device));if((changed||f.saving)&&!confirm(f.saving?'保存仍在处理中；返回不会撤销已经发送的保存。仍要离开当前草稿？':'还有未保存的设置，放弃草稿并返回电视列表？'))return;if(job.active())await devicesModal({owner:f.actor});});return;}
    if(action==='use-latest'||action==='keep-draft'){
      if(!f.latest)return;
      void operation(f,button,async job=>{if(!job.active())return;const keep=draft(f);f.device=f.latest;f.latest=null;f.conflict=false;f.draft=action==='keep-draft'?keep:model(f.device);render(f,action==='keep-draft'?'已保留草稿，点击保存后才会覆盖电视设置。':'已采用最新设置。');});return;
    }
    f.draft=draft(f);++f.epoch;
    if(action==='reset'){f.draft.layout=defaults();render(f,'已恢复默认布局与外观，点击保存后生效。');return;}
    if(action==='up'||action==='down'){
      const list=f.draft.layout.order,index=list.indexOf(button.dataset.key),next=index+(action==='up'?-1:1);
      if(index<0||next<0||next>=list.length)return;
      [list[index],list[next]]=[list[next],list[index]];
      const rows=f.node.querySelector('.tvd-card-list');for(const key of list)rows.append(rows.querySelector(`[data-tv-card-row="${key}"]`));
      preview(f);button.focus();
    }
  });
  function applyBoard() {
    window.MediaTV?.ensureDisplay();
    if(!isTV||!data)return;
    const board=document.querySelector('#app .board');if(!board)return;
    const value=layout(data.display?.layout);
    document.body.classList.add('tv-display');document.body.dataset.tvTheme=value.theme;document.body.dataset.tvDensity=value.density;
    for(const key of KEYS){const card=board.querySelector(SELECTORS[key]);if(card)card.dataset.tvCard=key;}
    grid(board,value.order,value.hidden);
  }
  window.TVDisplay={openDevice,applyBoard};
})();
