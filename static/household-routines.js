/* Household calendar-anchored routines. Preview and explicit confirmation only. */
'use strict';
window.HouseholdRoutines = (() => {
  let current=null,returnBridge=null;
  const permitted=()=>!isDemo&&!isTV&&canEdit()&&user?.role==='member';
  const actor=()=>({id:user?.id,household:user?.householdId||'default',csrf});
  const matches=(saved,person,token)=>person?.role==='member'&&person.id===saved.id&&
    (person.householdId||'default')===saved.household&&token===saved.csrf;
  const owns=f=>current===f&&f.node.isConnected&&document.querySelector('#dialog')?.open&&
    f.node.closest('.dialog-content')===f.container;
  const safeId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)?value:'';
  const snapshot=node=>JSON.stringify([...node.querySelectorAll('input,select,textarea')].map(v=>[v.name,v.value,v.checked]));
  const moneyText=value=>Number.isSafeInteger(value)?`¥${(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}`:'预算待填写';
  const budgetValue=value=>Number.isSafeInteger(value)?(value/100).toFixed(2):'';
  const dateText=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?value:'日期待核对';
  const stateText=state=>({active:'进行中',paused:'已暂停',archived:'已归档'}[state]||'状态待核对');
  const statusText=status=>({pending:'本期等待处理',completed:'本期已完成，等待生成下一期',missing:'本期事项已删除，待处理',paused:'计划已暂停',archived:'计划已归档',capacity_blocked:'清单容量已满，待处理',exhausted:'已到日期范围末尾'}[status]||'状态待核对');
  const occurrenceText=state=>({pending:'待处理',completed:'已完成',missing:'原事项已删除',skipped:'已跳过，未记为完成'}[state]||'状态待核对');
  const unit=frequency=>({daily:'天',weekly:'周',monthly:'个月'}[frequency]||'期');
  const scheduleText=schedule=>`每 ${schedule.interval} ${unit(schedule.frequency)} · 锚点 ${dateText(schedule.anchor)}`;
  const operationText=operation=>({create:'创建计划',update:'更新未来模板',pause:'暂停计划',resume:'恢复计划',skip:'跳过本期并保留现有事项',archive:'归档计划'}[operation]||'核对计划');
  const control=(action,label,extra='',primary=false)=>`<button type="button" class="btn ${primary?'':'secondary'}" data-hr="${action}" ${extra}>${label}</button>`;
  const feedback=()=>'<p class="hr-stale" data-hr-stale role="status"></p><p class="hr-error" role="alert"></p>';
  const notes=values=>(Array.isArray(values)?values:[]).filter(v=>typeof v==='string').map(v=>`<p class="hr-warning">${esc(v)}</p>`).join('');
  function message(f,value){const box=f.node.querySelector('.hr-error');if(box)box.textContent=value;}
  function invalidatePreview(f){
    f.preview=null;f.receipt=null;
    const ack=f.node.querySelector('[name=confirmAck]');if(ack){ack.checked=false;ack.disabled=true;}
    syncConfirm(f);
  }
  function syncConfirm(f){
    const button=f.node.querySelector('[data-hr=confirm]');
    if(button)button.disabled=!!f.writing||!f.preview?.previewToken||!f.node.querySelector('[name=confirmAck]')?.checked;
  }
  function neutral(f){
    if(!owns(f))return;
    ++f.epoch;f.context=null;f.plan=null;f.draft=null;f.preview=null;f.receipt=null;
    f.node.innerHTML='<section class="hr-view hr-empty"><h3>请重新核对登录状态</h3><p>原家庭的计划和草稿已关闭。刷新后再进入当前家庭。</p><a class="btn secondary" href="/">刷新页面</a></section>';
  }
  async function verify(f,active){
    if(!active())return false;
    if(!permitted()||!matches(f.actor,user,csrf))throw Object.assign(new Error('登录状态已变化'),{identityChanged:true});
    const me=await api('/me');
    if(!active())return false;
    if(!permitted()||!matches(f.actor,user,csrf)||!matches(f.actor,me.user,me.csrf))
      throw Object.assign(new Error('登录成员或家庭已变化'),{identityChanged:true});
    return true;
  }
  async function job(f,button,work,{writing=false}={}){
    if(!owns(f)||button?.disabled||(writing&&f.writing))return;
    const epoch=++f.epoch,node=f.node.firstElementChild,stamp=snapshot(node);
    const active=()=>owns(f)&&f.epoch===epoch&&node?.isConnected&&f.node.contains(node)&&snapshot(node)===stamp;
    if(writing)f.writing=true;
    if(button){button._hrJob=epoch;button.disabled=true;}
    message(f,'');let sent=false;
    try{
      if(await verify(f,active))await work({active,check:()=>verify(f,active),sent:()=>{sent=true;}});
    }catch(error){
      if(!active())return;
      if(error.identityChanged||error.status===401||error.status===403){neutral(f);return;}
      try{if(!await verify(f,active))return;}catch(_){if(active())neutral(f);return;}
      if(!active())return;
      if(error.status===409)invalidatePreview(f);
      message(f,(error.message||'暂时无法读取，请重试。')+(error.status===409?' 记录已变化，保留草稿后读取最新计划，再重新预览。':
        sent?' 确认请求已经发出，关闭窗口不会取消。请保留本次预览重试，或读取最新计划核对；不会自动再次发送。':''));
    }finally{
      if(writing)f.writing=false;
      if(button?.isConnected&&button._hrJob===epoch)button.disabled=false;
      if(owns(f)){
        if(!permitted()||!matches(f.actor,user,csrf))neutral(f);else syncConfirm(f);
      }
    }
  }
  function query(f,id=f.planId){
    const values=new URLSearchParams({page:String(f.page),includeArchived:String(f.filter==='archived'||f.filter==='all')});
    if(safeId(id))values.set('planId',id);
    return '/routines/context?'+values;
  }
  function captureContext(f,result){
    f.context=result;f.stateRevision=data?.revision;
    f.plan=f.planId?result.plans.find(p=>p.id===f.planId)||null:null;
  }
  function intro(){return `<div class="hr-intro"><span class="hr-symbol">${icon('calendar')}</span><div class="hr-intro-copy"><span class="eyebrow">OUR EVERYDAY RHYTHM</span><h3>把日常小事，安排成习惯</h3><p>固定日历节奏，逐期生成待办或采购。完成后推进下一期；不会启用系统通知或自动发布到云清单。</p></div></div>`;}
  function datesMarkup(dates,label='尚未生成的近期安排'){
    return `<section class="hr-upcoming"><h4>${esc(label)}</h4><div class="hr-schedule">${(dates||[]).slice(0,3).map((date,index)=>`<div class="hr-date"><small>第 ${index+1} 个日期</small><strong>${esc(dateText(date))}</strong></div>`).join('')||'<p class="help">当前规则下没有可显示的后续日期。</p>'}</div><p class="help">按北京时间（Asia/Shanghai）的日历日期计算。完成得早或晚，都不改变固定锚点。</p></section>`;
  }
  function view(f,html,stage){
    ++f.epoch;f.stage=stage;f.node.innerHTML=html;f.container.scrollTop=0;
  }
  function renderList(f,note=''){
    f.planId='';f.plan=null;f.draft=null;f.dirty=false;invalidatePreview(f);
    const plans=f.context.plans.filter(plan=>f.filter==='all'||plan.state===f.filter);
    const pageInfo=f.context.pageInfo||{};
    view(f,`<section class="hr-view hr-list-view">${intro()}<div class="hr-toolbar"><div class="hr-filters" aria-label="计划状态">${[['active','进行中'],['paused','暂停'],['archived','归档'],['all','全部']].map(([value,label])=>`<button type="button" data-hr="filter" data-filter="${value}" aria-pressed="${f.filter===value}">${label}</button>`).join('')}</div><div class="hr-list-header-actions">${control('refresh','刷新计划')}${control('create','新建例行计划','',true)}</div></div><p class="help">本页符合筛选的 ${plans.length} 项 · 每页最多 40 个计划。筛选针对当前页，其他计划可用下一页查看。</p>${note?`<p class="hr-note">${esc(note)}</p>`:''}<div class="hr-list">${plans.map(plan=>`<article class="hr-card" data-hr-plan="${esc(plan.id)}"><div class="hr-card-top"><span class="hr-kind">${icon(plan.kind==='shopping'?'bag':'list')}${plan.kind==='shopping'?'采购计划':'待办计划'}</span><span class="hr-badge ${esc(plan.state)}">${esc(stateText(plan.state))}</span></div><h4>${esc(plan.template.title)}</h4><p>${esc(scheduleText(plan.schedule))}</p><p>${esc(person(plan.template.owner))} · ${esc(statusText(plan.status))}</p>${plan.current?`<p class="hr-current-date">本期 ${esc(dateText(plan.current.scheduledOn))}</p>`:''}${control('details','查看计划',`data-plan-id="${esc(plan.id)}"`)}</article>`).join('')}</div>${!plans.length?`<div class="hr-empty"><span class="hr-symbol">${icon('list')}</span><h3>${f.context.plans.length?'本页没有这类计划':'给共同生活一个固定节奏'}</h3><p>${f.context.plans.length?'可以换个筛选，或继续翻页查看其他计划。':'例如每周预约保洁、每月补充日用品。先核对三期日期，再确认创建。'}</p>${control('create','建立第一个计划','',true)}</div>`:''}<div class="hr-pagination">${control('previous','上一页',f.page===0?'disabled':'')}<span>第 ${f.page+1} 页</span>${control('next','下一页',pageInfo.more?'':'disabled')}</div>${feedback()}</section>`,'list');
  }
  function renderDetails(f,note=''){
    const plan=f.plan;if(!plan){renderList(f,'原计划暂不可用，请在列表中核对。');return;}
    f.draft=null;f.dirty=false;invalidatePreview(f);
    const item=plan.current,entity=item?.entity;
    const actions=plan.state==='active'?control('edit','编辑未来模板')+control('pause','暂停计划')+control('skip','跳过本期并保留现有事项',item?'':'disabled')+control('archive','归档计划'):
      plan.state==='paused'?control('edit','编辑未来模板')+control('resume','恢复计划')+control('archive','归档计划'):'';
    view(f,`<section class="hr-view hr-detail-view" data-hr-plan="${esc(plan.id)}"><div class="hr-intro"><div class="hr-intro-copy"><span class="hr-badge ${esc(plan.state)}">${esc(stateText(plan.state))}</span><h3>${esc(plan.template.title)}</h3><p>${plan.kind==='shopping'?'采购':'待办'} · ${esc(scheduleText(plan.schedule))}</p></div>${control('list','全部计划')}</div>${note?`<p class="hr-note">${esc(note)}</p>`:''}<div class="hr-overview"><section class="hr-panel"><h4>当前事项</h4><span class="hr-badge ${plan.status==='missing'||plan.status==='capacity_blocked'?'paused':''}">${esc(statusText(plan.status))}</span>${item?`<div class="hr-current-title">${esc(entity?.title||'原事项已不可用')}</div><p>本期日期 ${esc(dateText(item.scheduledOn))} · ${esc(occurrenceText(item.state))}</p>${entity&&plan.kind==='shopping'?`<p>${esc(entity.quantity||'')} · ${moneyText(entity.budget)}<br>实付 ${Number.isSafeInteger(entity.actual)?moneyText(entity.actual):'尚未记录'}</p>`:''}${entity?`<div class="hr-current-actions">${control('open-item','打开原事项',`data-entity-id="${esc(item.entityId)}"`)}${plan.kind==='tasks'?control('publish-item','同步这项待办',`data-entity-id="${esc(item.entityId)}"`):''}</div>`:'<p class="hr-warning">删除不会重新创建原事项。计划进行中时，可明确跳过本期，再按固定节奏继续。</p>'}`:'<p class="help">暂无当前事项。请刷新确认计划状态。</p>'}</section><section class="hr-panel"><h4>未来事项使用的模板</h4><dl class="hr-detail-fields"><dt>负责人</dt><dd>${esc(person(plan.template.owner))}</dd>${plan.kind==='shopping'?`<dt>数量</dt><dd>${esc(plan.template.quantity)}</dd><dt>预算</dt><dd>${moneyText(plan.template.budget)}</dd>`:''}<dt>备注</dt><dd>${esc(plan.template.note||'未填写')}</dd><dt>时区</dt><dd>Asia/Shanghai</dd></dl><p class="help">修改模板不改当前事项；新采购不复制实付、图片、交易或旅行关联。</p></section></div>${datesMarkup(plan.nextDates)}<section class="hr-history"><h4>最近 ${Math.min(10,(plan.history||[]).length)} 期记录</h4><p class="help">包含当前期，最多显示最近 10 期。跳过保留原事项，不等于完成。</p><ul class="hr-history-list">${(plan.history||[]).slice(0,10).map(occ=>`<li class="hr-history-row"><div><strong>${esc(dateText(occ.scheduledOn))} · ${esc(occurrenceText(occ.state))}</strong><small>${esc(occ.entity?.title||'原事项已不可用')}</small></div>${occ.entity?control('open-item','打开',`data-entity-id="${esc(occ.entityId)}"`):''}</li>`).join('')||'<li class="help">尚无期次记录。</li>'}</ul></section>${feedback()}<div class="hr-footer">${control('refresh','刷新状态')}${actions}</div></section>`,'detail');
  }
  function newDraft(f){return {kind:'tasks',title:'',owner:'shared',note:'',quantity:'1 件',budget:'',frequency:'weekly',interval:'1',anchor:f.context.today};}
  function planDraft(plan){return {kind:plan.kind,title:plan.template.title,owner:plan.template.owner,note:plan.template.note||'',quantity:plan.template.quantity||'1 件',budget:budgetValue(plan.template.budget),frequency:plan.schedule.frequency,interval:String(plan.schedule.interval),anchor:plan.schedule.anchor};}
  function readDraft(f){
    const form=f.node.querySelector('#household-routine-form');if(!form)return f.draft;
    const values=new FormData(form);f.draft={...f.draft,...Object.fromEntries(values)};return f.draft;
  }
  function renderForm(f){
    invalidatePreview(f);
    const draft=f.draft,editing=!!f.planId;
    view(f,`<section class="hr-view hr-form-view"><span class="eyebrow">${editing?'FUTURE TEMPLATE':'A SHARED ROUTINE'}</span><h3>${editing?'修改未来的安排':'建立家庭例行计划'}</h3><p>${editing?'本次修改只影响尚未生成的期次。当前事项和已有完成记录保持原样。':'先填写固定节奏，再预览近期三期。确认后立即生成一条当日或未来的当前事项。'}</p><form id="household-routine-form"><div class="hr-form-grid"><label class="field hr-full"><span>事项名称</span><input name="title" maxlength="100" required value="${esc(draft.title)}" placeholder="例如：预约本周保洁"></label><label class="field"><span>计划类型</span><select name="kind" ${editing?'disabled':''}><option value="tasks" ${draft.kind==='tasks'?'selected':''}>共同待办</option><option value="shopping" ${draft.kind==='shopping'?'selected':''}>家庭采购</option></select></label><label class="field"><span>负责人</span><select name="owner">${ownerOptions(draft.owner)}</select></label><label class="field hr-shopping-field" ${draft.kind==='shopping'?'':'hidden'}><span>采购数量</span><input name="quantity" maxlength="30" value="${esc(draft.quantity)}" ${draft.kind==='shopping'?'required':''}></label><label class="field hr-shopping-field" ${draft.kind==='shopping'?'':'hidden'}><span>每期预算 · 人民币元</span><input name="budget" type="text" inputmode="decimal" maxlength="20" value="${esc(draft.budget)}" placeholder="留空表示尚未估算"><small class="help">预算不等于实付；0 表示明确零预算。</small></label><label class="field"><span>重复频率</span><select name="frequency"><option value="daily" ${draft.frequency==='daily'?'selected':''}>按天</option><option value="weekly" ${draft.frequency==='weekly'?'selected':''}>按周</option><option value="monthly" ${draft.frequency==='monthly'?'selected':''}>按月</option></select></label><label class="field"><span>每隔几个<span data-hr-interval-unit>${esc(unit(draft.frequency))}</span></span><input name="interval" type="number" min="1" max="${({daily:365,weekly:52,monthly:12})[draft.frequency]}" step="1" required value="${esc(draft.interval)}"></label><label class="field hr-full"><span>起始日期（固定节奏）</span><input name="anchor" type="date" min="2000-01-01" max="2100-12-31" required value="${esc(draft.anchor)}"><small class="help">北京时间（Asia/Shanghai）。可以用过去日期确定节奏，不补建历史；每月 31 日遇短月落到月底，之后仍回到 31 日。下一期不会按实际完成日期重新起算。</small></label><label class="field hr-full"><span>每期备注</span><textarea name="note" maxlength="500">${esc(draft.note)}</textarea></label></div><p class="hr-note">生成本地家庭事项。新采购仅带名称、负责人、数量、预算和备注；实付留空、未买到、无图片或私人来源及旅行关联。只有待办可另行进入云发布流程；不发送系统通知。</p>${feedback()}<div class="hr-footer">${control('cancel-edit','返回计划')}${editing?control('reload-draft','保留草稿，读取最新'):''}<button type="submit" class="btn">预览近期三期</button></div></form></section>`,'edit');
    const form=f.node.querySelector('form');
    form.addEventListener('input',()=>{readDraft(f);f.dirty=true;++f.epoch;invalidatePreview(f);});
    form.addEventListener('change',event=>{
      readDraft(f);f.dirty=true;++f.epoch;invalidatePreview(f);
      if(event.target.name==='kind'){
        for(const field of form.querySelectorAll('.hr-shopping-field'))field.hidden=f.draft.kind!=='shopping';
        form.elements.quantity.required=f.draft.kind==='shopping';
      }
      if(event.target.name==='frequency'){
        form.elements.interval.max=({daily:365,weekly:52,monthly:12})[f.draft.frequency];
        form.querySelector('[data-hr-interval-unit]').textContent=unit(f.draft.frequency);
      }
    });
    form.addEventListener('submit',event=>{event.preventDefault();void previewTemplate(f,form.querySelector('[type=submit]'));});
  }
  function amount(value){
    const raw=String(value).trim();if(!raw)return null;
    if(!/^\d+(?:\.\d{1,2})?$/.test(raw))throw new Error('预算使用非负人民币金额，最多两位小数，或留空。');
    const [yuan,decimal='']=raw.split('.'),cents=Number(yuan)*100+Number(decimal.padEnd(2,'0'));
    if(!Number.isSafeInteger(cents)||cents>100000000000)throw new Error('预算超出允许范围。');return cents;
  }
  function templatePayload(f,draft){
    const template={title:draft.title.trim(),owner:draft.owner,note:draft.note.trim()};
    if(draft.kind==='shopping'){template.quantity=draft.quantity.trim();template.budget=amount(draft.budget);}
    const interval=Number(draft.interval),maximum=({daily:365,weekly:52,monthly:12})[draft.frequency];
    if(!/^\d+$/.test(draft.interval)||!Number.isInteger(interval)||interval<1||interval>maximum)throw new Error('请填写当前频率允许的整数间隔。');
    const schedule={frequency:draft.frequency,interval,anchor:draft.anchor,timeZone:'Asia/Shanghai',monthEnd:'clamp'};
    return f.planId?{operation:'update',planId:f.planId,revision:f.plan.revision,template,schedule}:{operation:'create',kind:draft.kind,template,schedule};
  }
  const post=(f,path,payload)=>api('/routines/'+path,{method:'POST',body:JSON.stringify(payload),headers:{'X-CSRF-Token':f.actor.csrf}});
  async function previewTemplate(f,button){
    const draft={...readDraft(f)};invalidatePreview(f);
    await job(f,button,async operation=>{
      const payload=templatePayload(f,draft);
      const preview=await post(f,'preview',payload);if(!await operation.check())return;
      f.preview=preview;f.receipt=null;f.previewOperation=payload.operation;renderPreview(f);
    });
  }
  async function previewAction(f,button,action){
    const plan=f.plan;if(!plan)return;
    invalidatePreview(f);
    await job(f,button,async operation=>{
      const payload={operation:action,planId:plan.id,revision:plan.revision};
      const preview=await post(f,'preview',payload);if(!await operation.check())return;
      f.preview=preview;f.receipt=null;f.previewOperation=action;renderPreview(f);
    });
  }
  function renderPreview(f){
    const preview=f.preview,after=preview.after;
    view(f,`<section class="hr-view hr-review"><span class="eyebrow">REVIEW BEFORE CONFIRMING</span><h3>${esc(operationText(preview.operation))}</h3><p class="hr-preview-title">${esc(after.template.title)}</p><p>${esc(scheduleText(after.schedule))} · ${esc(person(after.template.owner))}</p><div class="hr-comparison"><section class="hr-panel"><h4>当前计划</h4><p>${preview.before?esc(stateText(preview.before.state)):'尚未创建'}</p><p>${preview.before?.current?'已有事项 '+esc(dateText(preview.before.current.scheduledOn)):'暂无已生成事项'}</p></section><section class="hr-panel"><h4>确认后</h4><p>${esc(stateText(after.state))}</p><p>${preview.willGenerate?'立即生成当前事项：'+esc(dateText(preview.willGenerate.scheduledOn)):'本次不生成新事项'}</p></section></div>${preview.operation==='skip'?'<p class="hr-warning">跳过本期并保留现有事项。旧事项不会删除、不会勾选完成；以后手动完成旧事项，也不会将“已跳过”历史改为完成。</p>':''}${preview.operation==='update'?'<p class="hr-note">仅更新未来模板。当前事项的名称、负责人、完成、预算、实付和照片不随模板修改。</p>':''}${preview.operation==='archive'?'<p class="hr-warning">归档后不再生成后续期次，不能直接恢复；历史和现有事项继续保留。</p>':''}${preview.operation==='pause'?'<p class="hr-note">暂停期间不生成下一期，当前事项仍可处理；恢复时会重新核对其状态。</p>':''}${after.kind==='shopping'?`<p class="help">未来采购数量 ${esc(after.template.quantity)} · ${moneyText(after.template.budget)}。新期不复制实付、完成状态、图片或私人来源。</p>`:''}${datesMarkup(preview.nextDates,'本次操作预览的近期三期')}${notes(preview.warnings)}<label class="hr-ack"><input type="checkbox" name="confirmAck">我已核对日期及上述影响，确认${esc(operationText(preview.operation))}</label><p class="help">预览约 10 分钟有效。没有自动通知或云发布。确认发出后，关闭窗口不能取消已经执行的写入。</p>${feedback()}<div class="hr-footer">${control('back-preview','返回修改')}${control('repreview','重新预览')}${control('confirm','确认这次安排','disabled',true)}</div></section>`,'review');
    f.node.querySelector('[name=confirmAck]').addEventListener('change',()=>syncConfirm(f));
  }
  async function repreview(f,button){
    const action=f.previewOperation;
    // Disable the old receipt before /me or preview starts; 503 must not revive it.
    invalidatePreview(f);
    if(action==='create'||action==='update')await previewTemplate(f,button);else await previewAction(f,button,action);
  }
  async function confirm(f,button){
    const preview=f.preview;if(!preview?.previewToken||!f.node.querySelector('[name=confirmAck]')?.checked)return;
    const payload={previewToken:preview.previewToken},knownReceipt=f.receipt;
    await job(f,button,async operation=>{
      let result=knownReceipt;
      if(!result){operation.sent();result=await post(f,'confirm',payload);if(!await operation.check())return;f.receipt=result;}
      const id=safeId(result.plan?.id);if(!id)throw new Error('确认已返回，请刷新列表核对计划。');
      const resultContext=await api(query(f,id));if(!await operation.check())return;
      const nextState=await api('/state');if(!await operation.check())return;
      f.planId=id;data=nextState;captureContext(f,resultContext);renderBoard();
      if(!operation.active())return;
      renderDetails(f,result.replayed?'已读取原确认回执，没有重复执行；下方为刚读取的当前计划。':'已保存并读取当前计划。');
    },{writing:true});
  }
  async function load(f,button,{keepDraft=false,toList=false}={}){
    const saved=keepDraft?{...readDraft(f)}:null;
    if(keepDraft)invalidatePreview(f);
    await job(f,button,async operation=>{
      const context=await api(query(f,toList?'':f.planId));if(!await operation.check())return;
      if(toList)f.planId='';captureContext(f,context);
      if(keepDraft&&saved){
        if(f.planId&&!f.plan)throw new Error('原计划已不可用，草稿保留但不能更新该计划。');
        f.draft=saved;renderForm(f);f.dirty=true;message(f,'已读取最新版本，保留你的草稿。请核对后重新预览。');
      }else if(f.planId)renderDetails(f);else renderList(f);
    });
  }
  function discardAllowed(f){return !f.dirty||window.confirm('还有未保存的模板修改。返回将放弃这份草稿，是否继续？');}
  const editorSnapshot=node=>JSON.stringify({fields:snapshot(node),images:[...node.querySelectorAll('img')].map(img=>img.getAttribute('src'))});
  function attachPlanReturn(f,target){
    if(current!==f||!target?.isConnected||target.closest('.dialog-content')!==document.querySelector('#dialog .dialog-content')||!permitted()||!matches(f.actor,user,csrf))return;
    const bridge={f,target,actor:f.actor,planId:f.plan.id,form:target.matches('form')?target:target.querySelector('form')};
    bridge.snapshot=bridge.form?editorSnapshot(bridge.form):null;
    const bar=document.createElement('aside');bar.className='hr-return';bar.dataset.hrReturn='';
    bar.innerHTML='<button type="button" class="btn secondary" data-hr-return-plan>← 返回这个例行计划</button><small>先保存原事项；未保存的修改和图片不会由返回按钮丢弃。</small><p class="hr-error" role="alert"></p>';
    target.before(bar);bridge.bar=bar;returnBridge=bridge;
    bar.querySelector('button').addEventListener('click',()=>{void returnToPlan(bridge);});
  }
  async function returnToPlan(bridge){
    const active=()=>returnBridge===bridge&&current===bridge.f&&bridge.target.isConnected&&bridge.bar.isConnected&&document.querySelector('#dialog')?.open;
    if(!active())return;
    const output=bridge.bar.querySelector('.hr-error'),form=bridge.form;
    if(!permitted()||!matches(bridge.actor,user,csrf)){
      returnBridge=null;openModal('家庭例行计划','<p class="help">登录状态已变化，请刷新后重新进入当前家庭。</p>');return;
    }
    if(form?.isConnected&&form.querySelector('button[type=submit]:disabled')){output.textContent='表单正在保存、上传或预览，请等待处理结果后再返回。';return;}
    if(form?.isConnected&&editorSnapshot(form)!==bridge.snapshot){output.textContent='这个表单尚未保存。请先保存，或使用原表单的取消按钮；返回不会丢弃修改或图片。';return;}
    if(bridge.target.querySelector('[data-tp]:disabled')){output.textContent='原发布操作正在处理，请等待结果后再返回。已发送的请求不会因返回而取消。';return;}
    // Explicit return only. An outer assistant remains the owner of dialog-close returns.
    const saved=bridge.actor,id=bridge.planId;
    returnBridge=null;
    openModal('家庭例行计划','<div data-hr-return-loading><p class="help">正在核对登录状态并读取原计划…</p><p class="hr-error" role="alert"></p></div>',true);
    const loading=document.querySelector('[data-hr-return-loading]');
    const live=()=>current===bridge.f&&loading.isConnected&&document.querySelector('#dialog')?.open;
    try{
      const me=await api('/me');if(!live())return;
      if(!permitted()||!matches(saved,user,csrf)||!matches(saved,me.user,me.csrf))throw new Error('登录成员或家庭已变化，请刷新后重新进入。');
      await open({planId:id});
    }catch(error){if(live())loading.querySelector('.hr-error').textContent=error.message||'暂时无法读回。请从例行计划入口重新读取；没有显示旧计划缓存。';}
  }
  async function openPublishedItem(f,id){
    const promise=window.TaskPublish.open({entityIds:[id]});
    const dialog=document.querySelector('#dialog'),loading=dialog.querySelector('#task-publish-loading');
    if(!loading){await promise;return;}
    let target=null,valid=true;
    const inspect=records=>{for(const record of records)for(const node of record.addedNodes){
      if(node.nodeType!==1||!node.matches('.dialog-content'))continue;
      const next=node.querySelector('#task-publish-root');
      if(target||!next)valid=false;else target=next;
    }};
    const observer=new MutationObserver(inspect);observer.observe(dialog,{childList:true});
    try{await promise;inspect(observer.takeRecords());if(valid&&target)attachPlanReturn(f,target);}
    finally{observer.disconnect();}
  }
  async function navigate(f,button,publish=false){
    const plan=f.plan,id=safeId(button.dataset.entityId);if(!plan||!id)return;
    await job(f,button,async operation=>{
      const state=await api('/state');if(!await operation.check())return;
      const entity=(state[plan.kind]||[]).find(item=>item.id===id);
      if(!entity)throw new Error('原事项已删除，没有打开其他记录。请刷新计划后核对。');
      data=state;f.stateRevision=state.revision;renderBoard();if(!operation.active())return;
      if(publish){if(plan.kind!=='tasks'||!window.TaskPublish?.open)throw new Error('任务发布入口暂不可用。');await openPublishedItem(f,id);}
      else if(plan.kind==='shopping'){if(!window.ShoppingUI?.openEditor)throw new Error('采购编辑器暂不可用。');window.ShoppingUI.openEditor(id);attachPlanReturn(f,document.querySelector('#dialog .shopping-form'));}
      else{editItem('tasks',id);attachPlanReturn(f,document.querySelector('#dialog form'));}
    });
  }
  function notifyStateChanged(){
    const f=current;if(!f||!owns(f))return;
    if(!permitted()||!matches(f.actor,user,csrf)){neutral(f);return;}
    if(data?.revision!==f.stateRevision){
      const box=f.node.querySelector('[data-hr-stale]');
      if(box)box.textContent='家庭事项状态可能已变化。刷新可重新核对；当前草稿会保留，不会自动提交。';
    }
  }
  function refresh(){const f=current;if(!f||!owns(f)||!permitted())return;return load(f,null,{keepDraft:f.stage==='edit'||f.stage==='review'&&!!f.draft});}
  async function open(options={}){
    if(!permitted())return;
    if(current&&owns(current)&&matches(current.actor,user,csrf)&&!discardAllowed(current))return;
    activeManager='';openModal('家庭例行计划',`<div data-household-routines><section class="hr-view hr-empty"><span class="hr-symbol">${icon('calendar')}</span><h3>正在核对家庭计划</h3><p>固定节奏，逐期安排。读取不会创建事项。</p>${feedback()}${control('refresh','重新读取')}</section></div>`,true);
    const node=document.querySelector('#dialog [data-household-routines]');
    const f={node,container:node.closest('.dialog-content'),actor:actor(),epoch:0,context:null,plan:null,planId:safeId(options?.planId),page:0,filter:'active',draft:null,dirty:false,preview:null,receipt:null,previewOperation:'',writing:false,stage:'loading',stateRevision:data?.revision};
    current=f;await load(f,null);
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-hr]'),f=current;
    if(!button||!f||!owns(f)||!f.node.contains(button)||button.disabled)return;
    const action=button.dataset.hr;
    if(!permitted()||!matches(f.actor,user,csrf)){neutral(f);return;}
    if(action==='confirm'){void confirm(f,button);return;}
    if(action==='repreview'){void repreview(f,button);return;}
    if(action==='refresh'){void load(f,button,{keepDraft:f.stage==='edit'||f.stage==='review'&&!!f.draft});return;}
    if(action==='reload-draft'){void load(f,button,{keepDraft:true});return;}
    if(action==='open-item'||action==='publish-item'){void navigate(f,button,action==='publish-item');return;}
    if(['pause','resume','skip','archive'].includes(action)){void previewAction(f,button,action);return;}
    void job(f,button,async operation=>{
      if(action==='filter'||action==='previous'||action==='next'||action==='list'){
        if(!discardAllowed(f))return;
        const nextFilter=action==='filter'?button.dataset.filter:f.filter;
        const nextPage=action==='filter'?0:action==='previous'||action==='next'?Math.max(0,f.page+(action==='next'?1:-1)):f.page;
        const context=await api(query({...f,filter:nextFilter,page:nextPage},''));if(!await operation.check())return;
        f.filter=nextFilter;f.page=nextPage;
        f.planId='';captureContext(f,context);renderList(f);return;
      }
      if(action==='details'){
        const id=safeId(button.dataset.planId);if(!id)return;
        const context=await api(query(f,id));if(!await operation.check())return;
        f.planId=id;captureContext(f,context);renderDetails(f);return;
      }
      if(action==='create'){
        if(!discardAllowed(f))return;
        f.planId='';f.plan=null;f.draft=newDraft(f);f.dirty=false;renderForm(f);return;
      }
      if(action==='edit'){
        if(!f.plan||f.plan.state==='archived')return;
        f.draft=planDraft(f.plan);f.dirty=false;renderForm(f);return;
      }
      if(action==='back-preview'){
        if(f.draft)renderForm(f);else renderDetails(f);return;
      }
      if(action==='cancel-edit'){
        if(!discardAllowed(f))return;
        if(f.plan)renderDetails(f);else renderList(f);
      }
    });
  });
  document.addEventListener('close',event=>{if(event.target.id==='dialog'&&!event.target.open&&current){++current.epoch;current=null;returnBridge=null;}},true);
  return {open,refresh,notifyStateChanged};
})();
