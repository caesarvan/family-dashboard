/* Manual inventory workspace; API owns quantities, ACL and durable receipts. */
window.InventoryUI = (() => {
  'use strict';
  let current = null;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const identity = () => JSON.stringify([user?.role,user?.householdId,user?.id,user?.auth_version,csrf,isTV,isDemo]);
  const allowed = () => !isTV && !isDemo && canEdit();
  const requestId = () => crypto.randomUUID().replaceAll('-','');
  const date = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  const orderNames = {planned:'计划采购',ordered:'已下单',in_transit:'运输中',closed:'已关闭',cancelled:'已取消'};
  const moveNames = {receive:'收货入库',consume:'使用消耗',dispose:'报损丢弃',return:'实物退回',adjust:'更正余量',reverse:'反转记录'};
  const confirmations = {receive:'confirmReceived',consume:'confirmConsumed',dispose:'confirmDisposed',return:'confirmReturned',adjust:'confirmCorrection'};
  const button = (a,text,attrs='') => `<button type="button" class="iv-button" data-iv="${a}" ${attrs}>${text}</button>`;
  const options = (map,value) => Object.entries(map).map(([key,label]) => `<option value="${esc(key)}" ${key===String(value??'')?'selected':''}>${esc(label)}</option>`).join('');
  const pageData = () => ({items:[],total:0,offset:0,nextOffset:null});

  function unmount(message='') {
    const f=current; if (!f) return;
    current=null; f.dead=true; f.epoch++; clearTimeout(f.timer); f.observer.disconnect();
    for (const kind of ['click','input','change','submit']) f.node.removeEventListener(kind,f[kind]);
    document.removeEventListener('visibilitychange',f.visibility);
    f.node.replaceChildren();
    if (message) {const p=document.createElement('p');p.setAttribute('role','alert');p.textContent=message;f.node.append(p);}
    f.items=[];f.item=null;f.acquisition=null;f.batches=pageData();f.movements=pageData();f.form=null;f.pending=null;
  }
  const notifyIdentityChanged = () => unmount('成员或家庭已变化，库存与草稿已收起。请重新打开。');
  function alive(f) {
    if (current!==f || f.dead || !f.node.isConnected) return false;
    if (!allowed() || identity()!==f.identity) {notifyIdentityChanged();return false;}
    return true;
  }
  async function verify(f,epoch) {
    if (!alive(f) || epoch!==f.epoch) return false;
    const me=await api('/me');
    if (!alive(f) || epoch!==f.epoch) return false;
    if (JSON.stringify([me.user?.role,me.user?.householdId,me.user?.id,me.user?.auth_version,me.csrf,isTV,isDemo])!==f.identity) {notifyIdentityChanged();return false;}
    return true;
  }
  function conceal(f) {
    f.items=[];f.total=0;f.item=null;f.acquisition=null;f.batches=pageData();f.movements=pageData();f.form=null;f.pending=null;
  }
  async function job(f,work,{quiet=false}={}) {
    if (!alive(f) || f.busy) return;
    f.busy=true;const epoch=++f.epoch;
    const valid=()=>alive(f)&&epoch===f.epoch;
    const check=()=>verify(f,epoch);
    if (!quiet) {f.error='';render(f);}
    try {if (await check()) await work(check);}
    catch (e) {
      if (!valid()) return;
      if (e.status===401) {notifyIdentityChanged();return;}
      try {if (!await check()) return;} catch (_) {if (!valid()) return;}
      if ([403,404,410].includes(e.status)) {conceal(f);f.notice='记录已归档或不再可见，旧详情已收起。';render(f);}
      f.error=e.message || '连接暂时不可用，草稿仍保留。';
    } finally {if (valid()) {f.busy=false;if (!quiet) render(f);else message(f);schedule(f);}}
  }
  async function read(f,check,path) {const value=await api('/inventory'+path);return await check()?value:null;}
  async function list(f,check) {
    const v=await read(f,check,'/items?'+new URLSearchParams({scope:f.scope,q:f.q,limit:'24',offset:String(f.offset)}));
    if (v) {f.items=v.items;f.total=v.total;f.nextOffset=v.nextOffset;f.loaded=true;}
  }
  async function details(f,check,itemId,acquisitionId=null) {
    const v=await read(f,check,'/items/'+encodeURIComponent(itemId));if (!v) return;
    f.item=v.item;
    const b=await read(f,check,`/items/${itemId}/acquisitions?limit=12&offset=${f.batches.offset}`);if (!b) return;
    f.batches=b;
    if (acquisitionId) {
      const a=await read(f,check,'/acquisitions/'+encodeURIComponent(acquisitionId));if (!a) return;
      f.item=a.item;f.acquisition=a.acquisition;
      const m=await read(f,check,`/acquisitions/${acquisitionId}/movements?limit=12&offset=${f.movements.offset}`);if (m) f.movements=m;
    } else {f.acquisition=null;f.movements=pageData();}
  }
  async function refresh(f) {return job(f,async check=>{await list(f,check);if (f.item) await details(f,check,f.item.id,f.acquisition?.id);});}
  function schedule(f) {
    clearTimeout(f.timer);if (!alive(f)||document.hidden) return;
    f.timer=setTimeout(()=>{
      if (f.busy||f.form||f.pending) {schedule(f);return;}
      void job(f,async check=>{if (f.item) await read(f,check,'/items/'+f.item.id);},{quiet:true});
    },15000);
  }
  function field(f,name,label,{type='text',required=false,max=100,choices=null,disabled=false}={}) {
    const value=f.form.values[name]??'';
    const control=choices?`<select name="${name}" ${disabled?'disabled':''}>${options(choices,value)}</select>`:
      `<input name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='text'?`maxlength="${max}"`:''} ${type==='number'?'step="1" min="-1000000" max="1000000"':''} ${disabled?'disabled':''}>`;
    return `<label>${label}${control}</label>`;
  }
  function formMarkup(f) {
    const form=f.form;if (!form) return '';
    const locked=f.busy||!!f.pending;let fields='',title='',help='';
    if (form.kind==='item') {
      title=form.edit?'编辑物品':'添加物品';help='数量从批次和实物记录计算；同名物品不会自动合并。';
      fields=field(f,'title','物品名称',{required:true})+field(f,'unit','计数单位（如个、盒）',{required:true,max:20})+
        field(f,'variant','规格',{max:200})+field(f,'location','存放位置')+field(f,'reorderPoint','补货提醒线（可空）',{type:'number'})+
        field(f,'visibility','谁能查看与操作',{choices:{private:'仅我自己',shared:'本家庭成员'}});
    } else if (form.kind==='batch') {
      title=form.edit?'编辑批次':'添加批次';help='已付款不代表收货；保存批次不会增加实物库存。';
      const editable=name=>form.edit && !(f.acquisition.editableFields||[]).includes(name);
      fields=field(f,'kind','批次类型',{choices:{purchase:'采购批次',opening:'家中已有'},disabled:form.edit})+
        field(f,'orderedQty','本批次数量',{type:'number',required:true,disabled:editable('orderedQty')})+
        field(f,'orderState','采购状态',{choices:orderNames,disabled:form.values.kind==='opening'||editable('orderState')})+
        field(f,'orderedOn','下单日期',{type:'date',disabled:form.values.kind==='opening'||editable('orderedOn')})+
        field(f,'expectedOn','预计到货',{type:'date',disabled:form.values.kind==='opening'||editable('expectedOn')})+
        field(f,'warrantyUntil','保修截止',{type:'date',disabled:editable('warrantyUntil')})+
        field(f,'afterSalesState','售后状态',{choices:{none:'无售后',open:'处理中',closed:'已结束'},disabled:editable('afterSalesState')})+
        field(f,'note','批次备注',{max:500,disabled:editable('note')});
    } else {
      title=form.kind==='reverse'?'反转这条实物记录':'记录实物变动';
      help=form.kind==='reverse'?'保留原记录，并追加数量完全相反的记录。不是删除历史。':'只记录实际发生的数量；退回不会自动退款，也不会修改财务或采购完成状态。';
      if (form.kind==='movement') fields=field(f,'kind','变动类型',{choices:Object.fromEntries(Object.entries(moveNames).filter(([k])=>k!=='reverse'))})+field(f,'quantity','本次实际数量',{type:'number',required:true});
      else fields=`<p class="iv-wide">将反转：${esc(moveNames[form.movement.kind])} ${esc(form.movement.deltaQty)} ${esc(f.item.unit)}</p>`;
      fields+=field(f,'occurredOn','实际日期',{type:'date',required:true})+field(f,'reason','原因 / 说明',{required:form.kind==='reverse'||form.values.kind!=='receive',max:300});
      fields+=`<label class="iv-check iv-wide"><input type="checkbox" name="confirmed" ${form.confirmed?'checked':''}>${form.kind==='reverse'?'我确认反转这条记录':`我确认本次${esc(moveNames[form.values.kind])}实际发生，数量无误`}</label>`;
    }
    return `<section class="iv-panel iv-edit"><div class="iv-heading"><h3>${title}</h3>${button('cancel-form','取消',locked?'disabled':'')}</div><p class="iv-muted">${help}</p><form data-iv-form><fieldset ${locked?'disabled':''}>${fields}<button class="iv-button primary iv-wide" type="submit">${form.edit?'保存修改':'确认保存'}</button></fieldset></form></section>`;
  }
  const quantities = item => `<dl class="iv-quantities"><div><dt>现有库存</dt><dd>${esc(item.onHandQty)} <small>${esc(item.unit||'')}</small></dd></div><div><dt>待到货</dt><dd>${esc(item.inTransitQty??item.remainingExpectedQty)}</dd></div><div><dt>${item.plannedQty===undefined?'已收货':'计划采购'}</dt><dd>${esc(item.plannedQty??item.receivedQty)}</dd></div></dl>`;
  function pager(kind,page,blocked) {
    return `<div class="iv-pages">${button(kind+'-previous','上一页',`${blocked?'disabled':''} ${page.offset===0?'disabled':''}`)}<span>${page.total} 条 · 第 ${Math.floor(page.offset/(kind==='items'?24:12))+1} 页</span>${button(kind+'-next','下一页',`${blocked?'disabled':''} ${page.nextOffset===null?'disabled':''}`)}</div>`;
  }
  function detailMarkup(f) {
    const item=f.item;if (!item) return '';
    const locked=f.busy||!!f.pending||!!f.form,attr=locked?'disabled':'';
    const a=f.acquisition;
    return `<section class="iv-panel iv-detail"><div class="iv-heading"><div><span class="iv-kicker">ITEM DETAILS</span><h2>${esc(item.title)}</h2></div>${button('close-detail','收起',attr)}</div><p class="iv-muted">${esc(item.variant||'未填规格')} · ${esc(item.location||'未填位置')} · ${item.visibility==='shared'?'本家庭共享':'仅本人'}</p>${quantities(item)}
      <div class="iv-actions">${item.canManage?button('edit-item','编辑 / 共享',attr):'<p class="iv-muted">共享物品：你可记录实物动作；可见范围由拥有者管理。</p>'}${item.canMutate?button('new-batch','添加批次',attr):''}${item.canManage?button('archive','归档物品',attr):''}</div>
      <h3>采购与已有批次</h3><div class="iv-batches">${f.batches.items.length?f.batches.items.map(b=>`<button class="iv-batch ${a?.id===b.id?'selected':''}" data-iv="select-batch" data-id="${esc(b.id)}" ${attr}><strong>${b.kind==='opening'?'家中已有':esc(orderNames[b.orderState])} · ${esc(b.orderedQty)} ${esc(item.unit)}</strong><span>现有 ${esc(b.onHandQty)} · 已收 ${esc(b.receivedQty)} · 待收 ${esc(b.remainingExpectedQty)}</span><small>${esc(b.expectedOn?'预计 '+b.expectedOn:b.note||'未填到货日期')}</small></button>`).join(''):'<p class="iv-muted">先建立一个批次，再明确登记收货或家中已有数量。</p>'}</div>${pager('batches',f.batches,locked)}
      ${a?`<section class="iv-batch-detail"><div class="iv-heading"><h3>本批次实物记录</h3>${a.canMutate?button('edit-batch','编辑批次',attr):''}</div><p>本批现有 <strong>${esc(a.onHandQty)}</strong> ${esc(item.unit)} · 累计退回 ${esc(a.returnedQty)} · 待收 ${esc(a.remainingExpectedQty)}</p><p class="iv-muted">${esc(a.note||'暂无备注')}${a.warrantyUntil?' · 保修至 '+esc(a.warrantyUntil):''}</p>${a.canMutate?button('new-movement',a.kind==='opening'?'登记已有 / 数量变动':'分次收货 / 数量变动',attr):''}<ol class="iv-movements">${f.movements.items.map(m=>`<li><div><strong>${esc(moveNames[m.kind])} ${m.deltaQty>0?'+':''}${esc(m.deltaQty)} ${esc(item.unit)}</strong><small>${esc(m.occurredOn)} · ${esc(m.reason||'实物收货')}</small></div>${m.canReverse?button('reverse','反转',`${attr} data-id="${esc(m.id)}"`):'<span class="iv-muted">已保留</span>'}</li>`).join('')}</ol>${pager('movements',f.movements,locked)}</section>`:''}</section>`;
  }
  function message(f) {
    const node=f.node.querySelector('[data-iv-message]');if (!node) return;
    node.innerHTML=`${f.error?`<p role="alert" class="iv-warning">${esc(f.error)}</p>`:''}${f.notice?`<p role="status" class="iv-notice">${esc(f.notice)}</p>`:''}${f.pending?`<div class="iv-warning"><strong>${f.pending.phase==='unknown'?'操作结果尚未确认':'本次操作未能提交'}</strong><p>${f.pending.phase==='unknown'?'草稿和原请求已保留。先查回执，再按原内容重试，避免重复收货。':'请明确重新核对当前记录；保留草稿后再次确认，不会自动覆盖。'}</p>${button(f.pending.phase==='unknown'?'retry':'recheck',f.pending.phase==='unknown'?'核对并重试本次操作':'重新核对并修改草稿',f.busy?'disabled':'')}</div>`:''}`;
  }
  function render(f) {
    if (!alive(f)) return;
    const locked=f.busy||!!f.pending||!!f.form;
    f.node.innerHTML=`<header class="iv-intro"><div><span class="iv-kicker">EVERYDAY ESSENTIALS</span><h2>家里的物品，心中有数。</h2><p>已下单、已到货、真正用完，分别记清楚。</p></div>${button('new-item','添加物品',`${locked?'disabled':''} data-primary`)}</header><div data-iv-message aria-live="polite"></div>
      <form class="iv-filters" data-iv-filters><label>查看范围<select name="scope" ${locked?'disabled':''}>${options({all:'全部可见',mine:'我的物品',shared:'已共享'},f.scope)}</select></label><label class="iv-search">搜索物品<input name="q" maxlength="100" value="${esc(f.q)}" placeholder="名称、规格或位置" ${locked?'disabled':''}></label><button class="iv-button" type="submit" ${locked?'disabled':''}>搜索</button>${button('refresh','刷新',locked?'disabled':'')}</form>
      ${formMarkup(f)}<div class="iv-layout ${f.item?'has-detail':''}"><section><div class="iv-grid">${f.items.length?f.items.map(item=>`<button class="iv-card" data-iv="select-item" data-id="${esc(item.id)}" ${locked?'disabled':''}><div class="iv-card-top"><span>${item.visibility==='shared'?'家庭共享':'仅本人'}</span>${item.belowThreshold?'<span class="iv-threshold">低于提醒线</span>':''}</div><h3>${esc(item.title)}</h3><p>${esc([item.variant,item.location].filter(Boolean).join(' · ')||'未填位置')}</p>${quantities(item)}</button>`).join(''):`<div class="iv-empty"><span aria-hidden="true">□</span><h3>${f.loaded?'还没有符合条件的物品':'正在核对库存…'}</h3><p>从一件常用物品开始，添加批次后明确登记实物数量。</p></div>`}</div>${pager('items',{total:f.total,offset:f.offset,nextOffset:f.nextOffset},locked)}</section>${detailMarkup(f)}</div>`;
    message(f);
  }
  function itemValues(item={}) {return {title:item.title||'',unit:item.unit||'个',variant:item.variant||'',location:item.location||'',reorderPoint:item.reorderPoint??'',visibility:item.visibility||'private'};}
  function batchValues(a={}) {return {kind:a.kind||'purchase',orderedQty:a.orderedQty??1,orderState:a.orderState||'planned',orderedOn:a.orderedOn||'',expectedOn:a.expectedOn||'',warrantyUntil:a.warrantyUntil||'',afterSalesState:a.afterSalesState||'none',note:a.note||''};}
  function integer(v,{optional=false,signed=false}={}) {
    if (v===''&&optional) return null;
    if (!/^-?\d+$/.test(String(v))) throw Error('数量必须是整数。');
    const n=Number(v);if (!Number.isSafeInteger(n)||Math.abs(n)>1000000||(!signed&&n<0)) throw Error('数量超出允许范围。');return n;
  }
  function payload(f) {
    const form=f.form,v=form.values;let path,method='POST',body={requestId:requestId()};
    if (form.kind==='item') {
      const data={...v,reorderPoint:integer(v.reorderPoint,{optional:true})};path='/items';
      if (form.edit) {path+='/'+f.item.id;method='PATCH';body={...body,revision:f.item.revision,patch:data};} else body.data=data;
    } else if (form.kind==='batch') {
      const data={...v,orderedQty:integer(v.orderedQty),orderedOn:v.orderedOn||null,expectedOn:v.expectedOn||null,warrantyUntil:v.warrantyUntil||null};
      if (data.orderedQty<1) throw Error('批次数量至少为 1。');
      if (v.kind==='opening') {data.orderState='closed';data.orderedOn=null;data.expectedOn=null;}
      body.itemRevision=f.item.revision;
      if (form.edit) {delete data.kind;body.patch=Object.fromEntries(Object.entries(data).filter(([key])=>f.acquisition.editableFields.includes(key)));body.revision=f.acquisition.revision;path='/acquisitions/'+f.acquisition.id;method='PATCH';}
      else {body.data=data;path='/items/'+f.item.id+'/acquisitions';}
    } else {
      if (!form.confirmed) throw Error('请明确确认本次实物动作和数量。');
      body.itemRevision=f.item.revision;body.revision=f.acquisition.revision;
      body.data={occurredOn:v.occurredOn,reason:v.reason};path='/acquisitions/'+f.acquisition.id+'/movements';
      if (form.kind==='reverse') {path+='/'+form.movement.id+'/reverse';body.confirmReversal=true;}
      else {body.data.kind=v.kind;body.data.quantity=integer(v.quantity,{signed:v.kind==='adjust'});if (!body.data.quantity) throw Error('本次数量不能为零。');body[confirmations[v.kind]]=true;}
    }
    return {path,method,body,phase:'unknown'};
  }
  async function accept(f,result,check) {
    f.pending=null;f.form=null;f.notice=result.operation?.replayed?'已查回原操作，不会重复记账。':'已保存实物记录。';
    f.item=result.item||null;f.acquisition=result.acquisition||null;f.batches=pageData();f.movements=pageData();
    await list(f,check);if (f.item) await details(f,check,f.item.id,f.acquisition?.id);
  }
  async function sendPending(f,check) {
    const p=f.pending;
    try {const result=await write('/inventory'+p.path,p.method,p.body);if (await check()) await accept(f,result,check);}
    catch (e) {if (!await check()) return;if ([400,409].includes(e.status)) p.phase='rejected';throw e;}
  }
  async function act(f,action,target) {
    if (!alive(f)||f.busy) return;
    if (action==='retry'&&f.pending?.phase==='unknown') return job(f,async check=>{
      try {const result=await read(f,check,'/operations/'+f.pending.body.requestId);if (result) await accept(f,result,check);}
      catch (e) {if (e.status!==404) throw e;if (await check()) await sendPending(f,check);}
    });
    if (action==='recheck'&&f.pending?.phase==='rejected') return job(f,async check=>{
      if (f.item) await details(f,check,f.item.id,f.acquisition?.id);
      if (!await check()) return;
      f.pending=null;if (f.form) f.form.confirmed=false;f.notice='已读取当前版本，草稿保留。请核对后重新确认。';
    });
    if (f.pending) return;
    if (action==='cancel-form') {f.form=null;f.error='';render(f);return;}
    if (f.form) return;
    if (action==='new-item') f.form={kind:'item',edit:false,values:itemValues()};
    if (action==='edit-item'&&f.item?.canManage) f.form={kind:'item',edit:true,values:itemValues(f.item)};
    if (action==='new-batch'&&f.item?.canMutate) f.form={kind:'batch',edit:false,values:batchValues()};
    if (action==='edit-batch'&&f.acquisition?.canMutate) f.form={kind:'batch',edit:true,values:batchValues(f.acquisition)};
    if (action==='new-movement'&&f.acquisition?.canMutate) f.form={kind:'movement',confirmed:false,values:{kind:'receive',quantity:1,occurredOn:date(),reason:''}};
    if (action==='reverse') {const movement=f.movements.items.find(m=>m.id===target.dataset.id&&m.canReverse);if (movement) f.form={kind:'reverse',movement,confirmed:false,values:{occurredOn:date(),reason:''}};}
    if (action==='close-detail') {f.item=null;f.acquisition=null;}
    if (action==='refresh') return refresh(f);
    if (action==='select-item') return job(f,async check=>{f.batches=pageData();f.movements=pageData();await details(f,check,target.dataset.id);});
    if (action==='select-batch') return job(f,async check=>{f.movements=pageData();await details(f,check,f.item.id,target.dataset.id);});
    if (action==='archive'&&f.item?.canManage) {
      if (!confirm('仅当所有批次关闭且库存为零才可归档。确定归档此物品？历史记录会保留。')) return;
      f.pending={path:'/items/'+f.item.id,method:'DELETE',body:{requestId:requestId(),revision:f.item.revision,confirmArchive:true},phase:'unknown'};
      return job(f,async check=>{const p=f.pending;try {await write('/inventory'+p.path,p.method,p.body);if (await check()) {conceal(f);f.notice='物品已归档，历史记录保留。';await list(f,check);}}catch(e){if (await check()&&[400,409].includes(e.status)) p.phase='rejected';throw e;}});
    }
    const page=/^(items|batches|movements)-(previous|next)$/.exec(action);
    if (page) {
      const kind=page[1],state=kind==='items'?f:f[kind],size=kind==='items'?24:12;
      const offset=page[2]==='next'?state.nextOffset:Math.max(0,state.offset-size);if (offset===null) return;
      state.offset=offset;return kind==='items'?job(f,check=>list(f,check)):job(f,check=>details(f,check,f.item.id,f.acquisition?.id));
    }
    f.error='';render(f);
  }
  async function mount(node,context={}) {
    if (current?.node===node&&alive(current)) return;
    unmount();node.classList.add('iv-workspace');
    if (!allowed()) {node.textContent='库存仅供已登录成员在手机或电脑管理，不向电视展示明细。';return;}
    const f={node,context,identity:identity(),epoch:0,dead:false,busy:false,loaded:false,scope:'all',q:'',offset:0,total:0,nextOffset:null,items:[],item:null,acquisition:null,batches:pageData(),movements:pageData(),form:null,pending:null,error:'',notice:''};current=f;
    f.click=e=>{const target=e.target.closest('[data-iv]');if (target) {e.preventDefault();void act(f,target.dataset.iv,target);}};
    f.input=e=>{if (alive(f)&&!f.busy&&!f.pending&&f.form&&e.target.closest('[data-iv-form]')&&e.target.name) {if (e.target.name==='confirmed') f.form.confirmed=e.target.checked;else f.form.values[e.target.name]=e.target.value;}};
    f.change=e=>{f.input(e);if (f.form&&!f.pending&&!f.busy&&e.target.name==='kind') {f.form.confirmed=false;if (f.form.kind==='batch'&&f.form.values.kind==='opening') {f.form.values.orderState='closed';f.form.values.orderedOn='';f.form.values.expectedOn='';}render(f);}};
    f.submit=e=>{e.preventDefault();if (!alive(f)||f.busy||f.pending) return;
      if (e.target.matches('[data-iv-filters]')&&!f.form) {const data=new FormData(e.target);f.scope=data.get('scope');f.q=data.get('q').trim();f.offset=0;void job(f,check=>list(f,check));}
      if (e.target.matches('[data-iv-form]')&&f.form) {try {f.pending=payload(f);void job(f,check=>sendPending(f,check));}catch(error){f.error=error.message;message(f);}}
    };
    f.visibility=()=>{if (document.hidden) clearTimeout(f.timer);else if (alive(f)) schedule(f);};
    f.observer=new MutationObserver(()=>{if (current===f&&!node.isConnected) unmount();});f.observer.observe(document.body,{childList:true,subtree:true});
    for (const kind of ['click','input','change','submit']) node.addEventListener(kind,f[kind]);document.addEventListener('visibilitychange',f.visibility);
    render(f);await refresh(f);
  }
  return {mount,unmount,notifyIdentityChanged,notifyStateChanged:()=>{if (current) alive(current);}};
})();
