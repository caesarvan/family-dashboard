/* Explicit projection of an owner's payment into shared shopping actual/done. */
'use strict';
window.ShoppingSettlement = (() => {
  const endpoint='/finance-hub/shopping-settlements';
  let current=null;
  const allowed=()=>!isDemo&&!isTV&&user?.role==='member'&&canEdit();
  const actor=()=>({id:user?.id,household:user?.householdId||'default',csrf});
  const matches=(saved,person,token)=>person?.role==='member'&&person.id===saved.id&&
    (person.householdId||'default')===saved.household&&token===saved.csrf;
  const owns=f=>current===f&&f.node.isConnected&&document.querySelector('#dialog')?.open&&f.node.closest('.dialog-content')===f.container;
  const moneyText=n=>Number.isSafeInteger(n)?`¥${(n/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}`:'未填写';
  const numberText=n=>Number.isSafeInteger(n)?(n/100).toFixed(2):'';
  const escId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value)?value:'';
  const reasonLabels={not_payment:'这条记录不是付款',not_expense:'这条记录不是消费付款',duplicate:'已确认重复，不作为付款来源',unsupported_currency:'仅支持人民币付款',missing_source:'付款来源已删除',source_changed:'原付款、退款或对账关系后来有变化',source_missing:'原付款已删除',source_ineligible:'原付款已不符合核对条件',shopping_changed:'采购后来已修改，请重新核对',shopping_missing:'原采购已删除'};
  const reason=code=>reasonLabels[code]||'记录状态需要重新核对';
  const stateLabel=value=>({current:'与本次核对一致',needs_review:'需要重新核对',revoked:'已解除关联'}[value]||'状态待核对');
  const doneText=value=>value?'已买到':'尚未标为买到';
  const snapshot=node=>JSON.stringify([...node.querySelectorAll('input,select,textarea')].map(input=>[input.name,input.value,input.checked]));
  const button=(action,label,extra='',className='secondary')=>`<button type="button" class="btn ${className}" data-ss="${action}" ${extra}>${label}</button>`;
  const errorBox=()=>'<p class="ss-error error" role="alert" tabindex="-1"></p>';
  const notes=items=>(Array.isArray(items)?items:[]).filter(value=>typeof value==='string').map(value=>`<p class="ss-warning">${esc(value)}</p>`).join('');
  const message=(f,text)=>{const target=f.node.querySelector('.ss-error');if(target)target.textContent=text;};
  const scrollTop=f=>{f.container.scrollTop=0;};
  function neutral(f){
    if(!owns(f))return;
    ++f.epoch;f.context=null;f.preview=null;f.receipt=null;f.draft=null;
    f.node.innerHTML='<section class="ss-view"><h3>请重新核对登录状态</h3><p>本次私人付款与预览已关闭。刷新页面后，再从本人的账本或采购清单进入。</p><a class="btn secondary" href="/">刷新页面</a></section>';
  }
  async function verify(f,active){
    if(!active())return false;
    if(!allowed()||!matches(f.actor,user,csrf))throw Object.assign(new Error('登录状态已变化'),{identityChanged:true});
    const me=await api('/me');
    if(!active())return false;
    if(!allowed()||!matches(f.actor,user,csrf)||!matches(f.actor,me.user,me.csrf))
      throw Object.assign(new Error('登录成员或家庭已变化'),{identityChanged:true});
    return true;
  }
  async function job(f,control,work,{writing=false}={}){
    if(!owns(f)||control?.disabled||(writing&&f.writing))return;
    const epoch=++f.epoch,view=f.node.firstElementChild,stamp=snapshot(view);
    const active=()=>owns(f)&&epoch===f.epoch&&view?.isConnected&&f.node.contains(view)&&snapshot(view)===stamp;
    let sent=false;
    if(writing)f.writing=true;
    if(control){control._ssJob=epoch;control.disabled=true;}
    message(f,'');
    try{
      if(await verify(f,active))await work({active,check:()=>verify(f,active),sent:()=>{sent=true;}});
    }catch(error){
      if(!active())return;
      if(error.identityChanged||error.status===401||error.status===403){neutral(f);return;}
      try{if(!await verify(f,active))return;}catch(_){if(active())neutral(f);return;}
      if(!active())return;
      if(error.status===409){f.preview=null;f.receipt=null;disableConfirmation(f);}
      message(f,(error.message||'暂时无法读取，请稍后重试。')+(error.status===409?' 数据已变化，原预览不可再确认。请保留草稿，读取最新记录后重新预览。':
        sent?' 确认请求已发出，关闭页面不会撤销；保留本次预览重试，或重新读取关联状态。':''));
    }finally{
      if(writing)f.writing=false;
      if(control?.isConnected&&control._ssJob===epoch)control.disabled=false;
      if(owns(f)&&matches(f.actor,user,csrf))syncConfirm(f);
    }
  }
  function disableConfirmation(f){
    const ack=f.node.querySelector('[name=shareAck]');if(ack){ack.checked=false;ack.disabled=true;}
    syncConfirm(f);
  }
  function syncConfirm(f){
    const control=f.node.querySelector('[data-ss=confirm]');
    if(control)control.disabled=!!f.writing||!f.preview?.previewToken||!f.node.querySelector('[name=shareAck]')?.checked;
  }
  function amount(value){
    const raw=String(value).trim();
    if(!/^\d+(?:\.\d{1,2})?$/.test(raw))throw new Error('请填写整项实付，使用非负金额，最多两位小数。');
    const [yuan,fraction='']=raw.split('.'),cents=Number(yuan)*100+Number(fraction.padEnd(2,'0'));
    if(!Number.isSafeInteger(cents)||cents>100000000000)throw new Error('整项实付超出允许范围。');
    return cents;
  }
  function query(f,extra={}){
    const params=new URLSearchParams();
    const focus={...f.focus,...extra};
    // A saved link remains inspectable after its payment or shopping was deleted.
    if(focus.linkId){delete focus.transactionId;delete focus.shoppingId;}
    for(const key of ['shoppingId','transactionId','linkId'])if(escId(focus[key]))params.set(key,focus[key]);
    params.set('q',f.q);params.set('page',String(f.page));
    return endpoint+'/context?'+params;
  }
  function selectedQuery(f){
    const extra={};
    if(f.draft?.shoppingId)extra.shoppingId=f.draft.shoppingId;
    if(f.draft?.paymentId&&f.context?.transaction?.kind!=='orders')extra.transactionId=f.draft.paymentId;
    if(f.linkId)extra.linkId=f.linkId;
    return query(f,extra);
  }
  function readDraft(f){
    const form=f.node.querySelector('#shopping-settlement-form');
    if(!form)return f.draft;
    const values=new FormData(form);
    f.draft={paymentId:String(values.get('paymentId')||f.draft?.paymentId||''),shoppingId:String(values.get('shoppingId')||f.draft?.shoppingId||''),
      amount:String(values.get('amount')??''),done:form.elements.done.checked};
    return f.draft;
  }
  function initialSelection(f){
    const context=f.context;
    if(!f.draft){
      const link=f.focus.linkId&&context.links.find(value=>value.id===f.focus.linkId&&value.status==='active');
      const payment=context.transaction?.kind==='payments'?context.payments.find(value=>value.id===context.transaction.id):null;
      const shopping=context.shopping.find(value=>value.id===(link?.shoppingId||f.focus.shoppingId));
      f.linkId=link?.id||'';
      f.draft={paymentId:link?.paymentId||payment?.id||'',shoppingId:link?.shoppingId||shopping?.id||'',amount:link?numberText(link.amountCents):'',done:shopping?.done||false};
    }
  }
  function intro(){return '<div class="ss-intro"><span class="eyebrow">PAYMENT → SHOPPING</span><h3>让采购实付有据可核对</h3><p>从本人的付款中核对金额，只把明确确认的整项实付和“已买到”状态写入共享采购。</p><span class="ss-private">付款标题、来源与关联记录仅本人可见</span></div>';}
  function linkCards(f){
    return f.context.links.map(link=>{
      const shopping=f.context.shopping.find(value=>value.id===link.shoppingId);
      return `<article class="ss-link" data-ss-link="${esc(link.id)}"><div><span class="ss-state ${link.state==='needs_review'?'warning':''}">${esc(stateLabel(link.state))}</span><h4>${shopping?esc(shopping.title):'原采购已不可用'}</h4><p>上次确认整项实付 ${moneyText(link.amountCents)}</p>${(link.reviewReasons||[]).map(code=>`<p class="ss-warning">${esc(reason(code))}</p>`).join('')}</div>${link.status==='active'?`<div class="ss-link-actions">${button('update','重新核对这项',`data-link-id="${esc(link.id)}"`)}${button('revoke','解除关联',`data-link-id="${esc(link.id)}"`,'secondary')}</div>`:''}</article>`;
    }).join('');
  }
  function renderSelection(f){
    ++f.epoch;f.preview=null;f.receipt=null;
    initialSelection(f);
    const context=f.context,draft=f.draft,link=f.linkId&&context.links.find(value=>value.id===f.linkId&&value.status==='active');
    const paymentCards=context.payments.map(payment=>`<label class="ss-choice ${payment.eligible?'':'unavailable'}"><input type="radio" name="paymentId" value="${esc(payment.id)}" ${draft.paymentId===payment.id?'checked':''} ${!payment.eligible||link&&link.paymentId!==payment.id?'disabled':''}><span><strong>${esc(payment.title)}</strong><small>${esc(payment.date)} · ${moneyText(payment.amountCents)}${payment.refundedCents?' · 已退款 '+moneyText(payment.refundedCents):''}</small><small>净付款 ${moneyText(payment.netCents)} · 可核对 ${moneyText(payment.availableCents)}</small>${payment.reservedCents?`<small>已有核对占用 ${moneyText(payment.reservedCents)}</small>`:''}${!payment.eligible?`<small class="ss-warning">${esc(reason(payment.reasonCode))}</small>`:''}</span></label>`).join('');
    const shoppingCards=context.shopping.map(shopping=>`<label class="ss-choice"><input type="radio" name="shoppingId" value="${esc(shopping.id)}" ${draft.shoppingId===shopping.id?'checked':''} ${link&&link.shoppingId!==shopping.id?'disabled':''}><span><strong>${esc(shopping.title)}</strong><small>当前实付 ${moneyText(shopping.actual)} · ${doneText(shopping.done)}</small></span></label>`).join('');
    const pageInfo=context.pageInfo||{},more=pageInfo.paymentsMore||pageInfo.shoppingMore||pageInfo.linksMore;
    f.node.innerHTML=`<section class="ss-view">${intro()}${notes(context.warnings)}${context.links.length?`<details class="ss-links" ${f.focus.linkId?'open':''}><summary>本人的已关联记录 · 本页 ${context.links.length} 项</summary>${linkCards(f)}</details>`:''}<form id="shopping-settlement-search" class="ss-search"><label class="field"><span>查找付款或采购</span><input name="q" maxlength="80" value="${esc(f.q)}" placeholder="输入标题关键词"></label><button class="btn secondary" type="submit">查找</button></form><div class="ss-pagination">${button('previous','上一页',f.page===0?'disabled':'')}<span>第 ${f.page+1} 页 · 每类最多 40 项，已选项另保留</span>${button('next','下一页',more?'':'disabled')}</div><form id="shopping-settlement-form"><div class="ss-section-heading"><h4>${link?'更新原关联':'1. 选择付款与采购'}</h4>${link?button('new','选择其他付款，建立新关联') :''}</div>${link?'<p class="help">更新保留原付款与采购。需要换付款时，先明确解除原关联，再新建。</p>':''}<div class="ss-columns"><section><h4>本人人民币付款</h4><div class="ss-choices">${paymentCards||'<p class="ss-empty">未找到可核对的本人付款。先导入并核对人民币消费付款，再回到这里。</p>'}</div>${context.transaction?.kind==='orders'?`<p class="help">这里只列出这笔订单已核对关联的付款，订单金额本身不证明已经付款。</p>${button('reconcile','核对这笔订单的付款')}`:''}</section><section><h4>共享采购</h4><div class="ss-choices">${shoppingCards||'<p class="ss-empty">未找到采购物品。可以先在采购清单建立物品，再回来选择。</p>'}</div></section></div><section class="ss-total"><h4>2. 填写整项实付</h4><label class="field"><span>整项实际总价 · 人民币元</span><input name="amount" inputmode="decimal" type="text" maxlength="20" value="${esc(draft.amount)}" placeholder="例如 128.00；不是在原金额上累加" required></label><label class="label-check"><input type="checkbox" name="done" ${draft.done?'checked':''}>已买到</label><p class="help">金额会替换整项实付；“已买到”独立选择。付款已发生不等于物品已到手。不会修改预算、旅行已付款、原账本或共同消费分类。</p></section>${errorBox()}<div class="dialog-footer">${button('back-shopping','返回采购清单')}${button('back-ledger','返回本人账本')}<button class="btn" type="submit">预览共享变化</button></div></form></section>`;
    scrollTop(f);
    const form=f.node.querySelector('#shopping-settlement-form');
    form.addEventListener('input',()=>{++f.epoch;f.preview=null;readDraft(f);});
    form.addEventListener('change',event=>{
      if(event.target.name==='shoppingId'){
        const shopping=f.context.shopping.find(value=>value.id===event.target.value);
        form.elements.done.checked=!!shopping?.done;
      }
      ++f.epoch;readDraft(f);
    });
    form.addEventListener('submit',event=>{event.preventDefault();void previewApply(f,form.querySelector('[type=submit]'));});
    f.node.querySelector('#shopping-settlement-search').addEventListener('submit',event=>{
      event.preventDefault();readDraft(f);f.q=event.currentTarget.elements.q.value.trim();f.page=0;void reload(f,event.currentTarget.querySelector('button'));
    });
  }
  async function reload(f,control){
    readDraft(f);
    await job(f,control,async operation=>{
      const context=await api(selectedQuery(f));if(!await operation.check())return;
      f.context=context;renderSelection(f);
    });
  }
  async function previewApply(f,control){
    const draft={...readDraft(f)};
    f.preview=null;
    await job(f,control,async operation=>{
      if(!escId(draft.shoppingId)||!escId(draft.paymentId))throw new Error('请选择一笔本人付款和一件共享采购。');
      const shopping=f.context.shopping.find(value=>value.id===draft.shoppingId);
      if(!shopping)throw new Error('所选采购不在当前结果中，请读取最新记录。');
      const link=f.linkId&&f.context.links.find(value=>value.id===f.linkId&&value.status==='active');
      const payload=link?{operation:'update',linkId:link.id,revision:link.revision,shoppingRevision:shopping.revision,amountCents:amount(draft.amount),done:draft.done}:
        {operation:'apply',paymentId:draft.paymentId,shoppingId:shopping.id,shoppingRevision:shopping.revision,amountCents:amount(draft.amount),done:draft.done};
      const preview=await write(endpoint+'/preview','POST',payload);if(!await operation.check())return;
      f.preview=preview;f.receipt=null;renderPreview(f);
    });
  }
  function renderPreview(f){
    ++f.epoch;
    const preview=f.preview,before=preview.before,after=preview.after;
    const shopping=f.context.shopping.find(value=>value.id===(after?.shoppingId||before?.shoppingId));
    f.node.innerHTML=`<section class="ss-view ss-review"><span class="eyebrow">REVIEW BEFORE SHARING</span><h3>${preview.operation==='revoke'?'确认解除关联':'确认共享采购变化'}</h3><p>${shopping?esc(shopping.title):'原采购已不可用'}</p><div class="ss-comparison"><section><small>当前采购</small><strong>${before?moneyText(before.actual):'无可更新采购'}</strong><p>${before?doneText(before.done):'不改其他采购'}</p></section><span aria-hidden="true">→</span><section><small>确认后</small><strong>${after?moneyText(after.actual):'仅解除本人关联'}</strong><p>${after?doneText(after.done):'不修改采购金额或状态'}</p></section></div>${preview.payment?`<p class="help">付款净额 ${moneyText(preview.payment.netCents)} · 扣除其他核对后的可用额 ${moneyText(preview.payment.availableCents)}</p>`:''}${notes(preview.warnings)}<div class="ss-sharing"><strong>共享范围仅为采购整项实付和“已买到”</strong><p>付款标题、账户、交易编号和本人关联记录不会写入共享采购。原始账本、预算统计和旅行已付款保持原值。</p></div><label class="label-check"><input type="checkbox" name="shareAck">我已核对金额和买到状态，确认上述变化</label><p class="help">预览约 10 分钟有效。记录变化后必须重新预览。确认请求发出后，关闭页面不会取消已经完成的写入。</p>${errorBox()}<div class="dialog-footer">${button('edit','返回修改')}${button('reload','保留草稿，读取最新')}${button('confirm','确认这次变化','disabled','')}</div></section>`;
    scrollTop(f);
    f.node.querySelector('[name=shareAck]').addEventListener('change',()=>syncConfirm(f));
  }
  function renderRevoke(f,link){
    ++f.epoch;f.preview=null;f.receipt=null;f.revokeId=link.id;
    f.node.innerHTML=`<section class="ss-view"><span class="eyebrow">UNLINK WITH CARE</span><h3>解除本人付款与采购的关联</h3><p>不会删除原始付款，也不会撤销真实交易。</p><form id="shopping-settlement-revoke"><label class="ss-choice"><input type="radio" name="mode" value="detach_keep_current" ${f.revokeMode!=='restore_if_unchanged'?'checked':''}><span><strong>保留采购当前值</strong><small>只解除关联；保留成员目前记录的实付和买到状态。</small></span></label><label class="ss-choice"><input type="radio" name="mode" value="restore_if_unchanged" ${f.revokeMode==='restore_if_unchanged'?'checked':''}><span><strong>安全恢复核对前的采购值</strong><small>仅在采购仍是当时写入的版本、实付和状态完全匹配时允许。后来有人改过则拒绝，不覆盖他人修改。</small></span></label>${errorBox()}<div class="dialog-footer">${button('edit','返回核对')}${button('reload','保留草稿，读取最新')}<button type="submit" class="btn">预览解除影响</button></div></form></section>`;
    scrollTop(f);
    const form=f.node.querySelector('form');
    form.addEventListener('change',()=>{++f.epoch;f.preview=null;f.revokeMode=form.elements.mode.value;});
    form.addEventListener('submit',event=>{
      event.preventDefault();const mode=form.elements.mode.value;
      void job(f,form.querySelector('[type=submit]'),async operation=>{
        const currentLink=f.context.links.find(value=>value.id===link.id);
        if(!currentLink||currentLink.status!=='active')throw new Error('关联状态已变化，请重新读取。');
        const shopping=f.context.shopping.find(value=>value.id===currentLink.shoppingId);
        const payload={operation:'revoke',linkId:currentLink.id,revision:currentLink.revision,shoppingRevision:shopping?.revision??null,mode};
        const preview=await write(endpoint+'/preview','POST',payload);if(!await operation.check())return;
        f.preview=preview;renderPreview(f);
      });
    });
  }
  async function readback(f,operation,receipt){
    const extra={linkId:receipt.link?.id||f.linkId,shoppingId:receipt.shopping?.id||f.draft?.shoppingId};
    const context=await api(query(f,extra));if(!await operation.check())return;
    const nextState=await api('/state');if(!await operation.check())return;
    f.context=context;f.receipt=receipt;f.preview=null;
    if(receipt.link?.id){f.focus.linkId=receipt.link.id;f.linkId=receipt.link.status==='active'?receipt.link.id:'';}
    data=nextState;renderBoard();
    if(!operation.active())return;
    renderResult(f,receipt,nextState);
  }
  async function confirmPreview(f,control){
    const preview=f.preview;if(!preview?.previewToken||!f.node.querySelector('[name=shareAck]')?.checked)return;
    const receipt=f.receipt,payload={previewToken:preview.previewToken};
    await job(f,control,async operation=>{
      let result=receipt;
      if(!result){operation.sent();result=await write(endpoint+'/confirm','POST',payload);if(!await operation.check())return;f.receipt=result;}
      await readback(f,operation,result);
    },{writing:true});
  }
  function renderResult(f,receipt,nextState){
    ++f.epoch;
    const id=receipt.shopping?.id||f.draft?.shoppingId,shopping=(nextState.shopping||[]).find(value=>value.id===id);
    const link=f.context.links.find(value=>value.id===receipt.link?.id);
    f.node.innerHTML=`<section class="ss-view ss-result"><span class="ss-state">已重新读取服务器记录</span><h3>${receipt.operation==='revoke'?'关联已解除':'采购实付已核对'}</h3>${receipt.replayed?'<p class="help">这次确认读取了原操作回执，没有重复写入。下方是刚读取的当前采购，不把历史回执当作最新状态。</p>':''}${shopping?`<div class="ss-result-item"><h4>${esc(shopping.title)}</h4><strong>${moneyText(shopping.actual)}</strong><p>${doneText(shopping.done)}</p></div>`:'<p class="help">原采购目前已不可用；请回采购清单核对。未创建替代物品。</p>'}${link?.state==='needs_review'?notes((link.reviewReasons||[]).map(reason)):''}<p class="help">账本、预算分类与旅行已付款没有因这次核对重复计入。</p>${errorBox()}<div class="dialog-footer">${shopping?button('open-shopping','查看原采购',`data-shopping-id="${esc(shopping.id)}"`):''}${button('reload','查看关联状态')}${button('back-ledger','返回本人账本')}</div></section>`;
    scrollTop(f);
  }
  async function navigation(f,control,action){
    await job(f,control,async operation=>{
      if(action==='reconcile'){
        if(!f.context?.transaction?.id||!window.FinanceHub?.openReconciliation)throw new Error('对账入口尚未就绪，请重新打开本人账本。');
        const id=f.context.transaction.id,shoppingId=f.draft?.shoppingId||f.focus.shoppingId;
        if(!await operation.check())return;
        window.FinanceHub.openReconciliation(id,{shoppingId});return;
      }
      if(action==='back-ledger'){
        if(!window.FinanceHub?.open)throw new Error('账本入口尚未就绪。');
        if(await operation.check())window.FinanceHub.open('ledger');return;
      }
      const state=await api('/state');if(!await operation.check())return;
      const id=escId(control?.dataset.shoppingId)||f.draft?.shoppingId||f.focus.shoppingId;
      if(action==='open-shopping'&&!(state.shopping||[]).some(value=>value.id===id))throw new Error('原采购已删除，未打开其他物品。');
      data=state;renderBoard();
      if(!operation.active())return;
      if(action==='open-shopping')window.ShoppingUI.openEditor(id);else window.ShoppingUI.openManager();
    });
  }
  async function open(options={}){
    if(!allowed())return;
    const focus={};for(const key of ['shoppingId','transactionId','linkId'])if(escId(options[key]))focus[key]=options[key];
    activeManager='';
    openModal('核对采购实付','<div data-shopping-settlement><section class="ss-view"><h3>正在读取本人的核对资料…</h3><p>私人付款仅在本人主动打开后读取。</p>'+errorBox()+button('reload','重试读取')+'</section></div>',true);
    const node=document.querySelector('[data-shopping-settlement]');
    const f={node,container:node.closest('.dialog-content'),actor:actor(),epoch:0,focus,q:'',page:0,draft:null,context:null,linkId:'',preview:null,receipt:null,writing:false};
    current=f;
    await job(f,null,async operation=>{const context=await api(query(f));if(!await operation.check())return;f.context=context;renderSelection(f);});
  }
  document.addEventListener('click',event=>{
    const control=event.target.closest('[data-ss]'),f=current;
    if(!control||!f||!owns(f)||!f.node.contains(control)||!allowed())return;
    const action=control.dataset.ss;
    if(action==='confirm'){void confirmPreview(f,control);return;}
    if(['back-shopping','back-ledger','open-shopping','reconcile'].includes(action)){void navigation(f,control,action);return;}
    if(action==='reload'){void reload(f,control);return;}
    if(action==='previous'||action==='next'){if(control.disabled)return;readDraft(f);f.page=Math.max(0,f.page+(action==='next'?1:-1));void reload(f,control);return;}
    void job(f,control,async operation=>{
      if(!await operation.check())return;
      if(action==='edit'){
        const link=f.preview?.operation==='revoke'&&f.context.links.find(value=>value.id===f.revokeId&&value.status==='active');
        if(link)renderRevoke(f,link);else renderSelection(f);return;
      }
      if(action==='new'){f.linkId='';f.focus.linkId='';f.draft={paymentId:'',shoppingId:f.draft?.shoppingId||'',amount:'',done:!!f.draft?.done};renderSelection(f);return;}
      const link=f.context?.links.find(value=>value.id===control.dataset.linkId&&value.status==='active');
      if(!link)throw new Error('关联记录已变化，请读取最新状态。');
      if(action==='update'){
        f.linkId=link.id;f.focus.linkId=link.id;
        const shopping=f.context.shopping.find(value=>value.id===link.shoppingId);
        f.draft={paymentId:link.paymentId,shoppingId:link.shoppingId,amount:numberText(link.amountCents),done:!!shopping?.done};
        const context=await api(query(f,{linkId:link.id}));if(!await operation.check())return;f.context=context;renderSelection(f);return;
      }
      if(action==='revoke'){f.revokeMode='detach_keep_current';renderRevoke(f,link);}
    });
  });
  document.addEventListener('close',event=>{if(event.target.id==='dialog'&&!event.target.open&&current){++current.epoch;current=null;}},true);
  return {open};
})();
