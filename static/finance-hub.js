/* Dated personal finance workspace. Platform connections are explicit CSV imports. */
'use strict';
window.FinanceHub = (() => {
  let model=null, tab='overview', month='', pending=null;
  let importEpoch=0,pendingActor=null,shoppingReturn=null,ledger=null;
  const modelActors=new WeakMap();
  const relationLabels={order_payment:'订单关联付款',refund_payment:'退款关联原付款',duplicate:'确认重复记录'};
  const labels={expense:'支出',income:'收入',refund:'退款',transfer:'转账 / 理财划转',unknown:'待核对',excluded:'不计入'};
  const sources={alipay:'支付宝',wechat:'微信',taobao:'淘宝',pinduoduo:'拼多多',generic:'通用模板'};
  const fmt=(c,cur='CNY')=>c===null?'待估值':`${cur} ${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(c/100)}`;
  const buttons=(name)=>`<button class="btn small secondary" type="button" data-fh="${name}">返回财务中枢</button>`;
  const field=(name,label,value='',extra='')=>`<label class="field"><span>${label}</span><input name="${name}" value="${esc(value)}" ${extra}></label>`;
  const option=(value,label,selected)=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`;
  const message=text=>`<p class="fh-note">${esc(text)}</p>`;
  // Source item text is private context, never additional payments or a remote resource.
  function orderItems(row){
    return row?.kind==='orders'&&row.orderGroup?.format==='taobao-merged-v1'&&Array.isArray(row.orderItems)?row.orderItems:[];
  }
  function orderItemsMarkup(row){
    const items=orderItems(row);if(!items.length)return '';
    const sourceText=(label,value)=>value===undefined||value===null||value===''?'':`<div><dt>${label}</dt><dd>${esc(String(value))}</dd></div>`;
    return `<details class="fh-order-items" data-fh-order-items><summary>商品明细 · ${items.length} 项</summary><p class="fh-note">订单金额只计一次。数量、商品金额和运费为来源原文，不相乘、不分摊，也不另计实付。</p>${row.orderGroup.shippingAmountText?`<p class="fh-order-shipping">运费（原文）：${esc(String(row.orderGroup.shippingAmountText))}</p>`:''}<ol>${items.map(item=>`<li data-fh-order-item><strong>${esc(item.title||'未提供商品名称')}</strong><dl>${sourceText('规格',item.variant)}${sourceText('数量（原文）',item.quantityText)}${sourceText('商品金额（原文）',item.listedAmountText)}${sourceText('商品地址（仅文本，可选择复制）',item.productUrl)}${sourceText('原工作表行',item.sourceLine)}</dl></li>`).join('')}</ol></details>`;
  }
  function orderPreviewSummary(rows){
    const groups=rows.filter(row=>orderItems(row).length),count=groups.reduce((sum,row)=>sum+orderItems(row).length,0);
    if(!groups.length)return '';
    return `<p class="fh-note fh-order-summary" data-fh-order-summary>预览共 ${rows.length} 个订单 · ${count} 项商品明细${groups.length<rows.length?`；另有 ${rows.length-groups.length} 单未提供商品明细`:''}。展开各订单可核对全部商品；重复订单会跳过。</p>`;
  }
  const importActor=()=>({id:user?.id,household:user?.householdId||'default',csrf});
  const matchesActor=(actor,person,token)=>person?.role===(isDemo?'demo':'member')&&person.id===actor.id&&(person.householdId||'default')===actor.household&&token===actor.csrf;
  async function importJob(node,work,actor=importActor()){
    const epoch=++importEpoch,active=()=>epoch===importEpoch&&node.isConnected&&document.querySelector('#dialog').open;
    const check=async()=>{
      if(!active())return false;
      const me=await api('/me');
      if(!active())return false;
      if(!matchesActor(actor,user,csrf)||!matchesActor(actor,me.user,me.csrf)){
        const error=new Error('登录成员或家庭已变化，请刷新后重新选择文件。');error.contextChanged=true;throw error;
      }
      return true;
    };
    try{if(await check())await work(check,active)}catch(error){
      if(!active())return;
      if(!error.contextChanged&&error.status!==401&&error.status!==403){try{if(!await check())return}catch(identityError){error=identityError}}
      if(!active())return;
      if(error.contextChanged||error.status===401||error.status===403){pending=null;pendingActor=null;++importEpoch;node.innerHTML=`<p class="error" role="alert">${esc(error.message)}</p>`;return}
      const target=node.querySelector('.error');if(target)target.textContent=error.message||'无法读取文件，请重新选择';
    }
  }

  const importReceipts=new WeakMap();
  function monthChoices(values,action='month',selected=month){
    return `<div class="fh-month-choices" aria-label="有记录的月份">${(values||[]).map(item=>`<button class="btn small secondary" type="button" data-fh="${action}" data-month="${esc(item.month)}" aria-pressed="${item.month===selected}">${esc(item.month)}<span>${item.recordCount} 条</span></button>`).join('')}</div>`;
  }
  function receiptMarkup(receipt,waiting=false){
    return `<section class="fh-import-receipt" data-fh-import-receipt role="status"><h4>导入确认已完成</h4><p>新增 ${receipt.imported} 条 · 跳过 ${receipt.duplicates} 条重复${receipt.conflicts?` · ${receipt.conflicts} 条冲突保留原记录`:''}</p><details><summary>回执与当前账本的区别</summary><p>以下月份与条数为本次确认时实际保留的唯一记录；编号冲突按原记录的日期定位。当前账本以重新读取的结果为准。</p></details>${monthChoices(receipt.resultMonths,waiting?'receipt-month':'month')}${waiting?'<p class="fh-note" data-fh-receipt-status>正在读取当前账本。确认已经完成；重新读取只发送查询，不会再次导入。</p><p id="fh-confirm-error" class="error" role="alert"></p><div class="fh-actions"><button type="button" class="btn" data-fh="receipt-retry">重新读取账本</button><button type="button" class="btn secondary" data-fh="back-import">导入另一份文件</button></div>':''}</section>`;
  }
  function emptyLedger(){
    if(model.totalRecordCount)return message('这个月没有记录。你的其他月份已有账本，可选择下面的月份查看。')+monthChoices(model.availableMonths);
    if(importReceipts.has(model))return message('当前账本中已没有记录。确认回执保留的是当时结果，记录可能已被移除；不会自动重新导入。');
    return message('这个月还没有导入记录。');
  }
  async function navigateMonth(button){
    const original=model,actor=original&&modelActors.get(original),node=button.closest('.fh-workspace');
    const target=button.dataset.month;if(!actor||!node||!/^\d{4}-\d{2}$/.test(target))return;
    if(!node.querySelector('.error'))node.insertAdjacentHTML('beforeend','<p class="error" role="alert"></p>');
    await importJob(node,async check=>{
      const next=await api('/finance-hub/overview?month='+encodeURIComponent(target));if(!await check())return;
      const receipt=importReceipts.get(original);if(receipt)importReceipts.set(next,receipt);
      model=next;month=next.month;tab='ledger';render();
    },actor);
  }
  async function confirmImport(button){
    const node=button.closest('#fh-import-preview');if(!node)return;
    let flow=node._fhImportResult;
    if(!flow){if(!pending?.previewToken)return;flow=node._fhImportResult={actor:pendingActor,payload:pending,receipt:null,inFlight:false,target:null};}
    if(flow.inFlight)return;
    flow.inFlight=true;button.disabled=true;
    try{await importJob(node,async(check,active)=>{
      if(!flow.receipt){
        const result=await write('/finance-hub/imports/confirm','POST',flow.payload);
        // Keep a known successful response even if the following identity/readback GET fails.
        // It belongs only to this original node; a later page never inherits its payload.
        if(!active())return;flow.receipt=result;flow.target=result.resultMonths?.[0]?.month||month;
      }
      if(!await check())return;
      node.innerHTML=receiptMarkup(flow.receipt,true);
      node.querySelectorAll('[data-fh=receipt-retry],[data-fh=receipt-month]').forEach(item=>item.disabled=true);
      const next=await api('/finance-hub/overview?month='+encodeURIComponent(flow.target));
      if(!await check())return;
      pending=null;pendingActor=null;model=next;month=next.month;tab='ledger';importReceipts.set(next,flow.receipt);render();
      toast(`已导入 ${flow.receipt.imported} 条，跳过 ${flow.receipt.duplicates} 条重复${flow.receipt.conflicts?'；'+flow.receipt.conflicts+' 条编号或原文件行金额冲突需核对':''}`);
    },flow.actor)}finally{
      flow.inFlight=false;
      if(node.isConnected&&node._fhImportResult===flow&&matchesActor(flow.actor,user,csrf)){
        if(flow.receipt){
          const retry=node.querySelector('[data-fh=confirm]');
          if(retry){retry.dataset.fh='receipt-retry';retry.textContent='确认已完成 · 重新读取账本';retry.disabled=false;}
          node.querySelectorAll('[data-fh=receipt-retry],[data-fh=receipt-month]').forEach(item=>item.disabled=false);
          const status=node.querySelector('[data-fh-receipt-status]');if(status)status.textContent='确认已经完成。当前账本尚未读回；重新读取只发送查询，不会再次导入。';
        }else if(button.isConnected)button.disabled=!pending?.previewToken;
      }
    }
  }

  async function open(next='overview'){
    if(isTV||(!canEdit()&&!isDemo))return;
    shoppingReturn=null;tab=isDemo&&!['overview','ledger'].includes(next)?'ledger':next;month=month||dateKey().slice(0,7);
    if(isDemo){++importEpoch;model=demoModel();render();return}
    openModal('财务中枢', '<div class="fh-loading"><p class="help">正在读取你的财务记录…</p><p class="error" role="alert"></p></div>', true);
    const node=document.querySelector('.fh-loading'),selectedMonth=month;
    await importJob(node,async check=>{const nextModel=await api('/finance-hub/overview?month='+encodeURIComponent(selectedMonth));if(!await check())return;model=nextModel;render()});
  }
  function shell(content){
    return `<div class="fh-workspace"><div class="fh-intro"><div><div class="eyebrow">MONEY, WITH CLARITY</div><h3>让每一笔都有来处</h3><p>本人账本 · 投资记录 · 共同消费核对</p></div><label class="field fh-month"><span>查看月份</span><input type="month" id="fh-month" value="${esc(month)}"></label></div><nav class="fh-tabs" aria-label="财务功能">${[['overview','月度概览'],['ledger','账单与订单'],['investments','投资账户'],['import','导入数据']].filter(([id])=>!isDemo||['overview','ledger'].includes(id)).map(([id,title])=>`<button type="button" class="${tab===id?'active':''}" data-fh-tab="${id}" aria-pressed="${tab===id}">${title}</button>`).join('')}</nav>${importReceipts.has(model)?receiptMarkup(importReceipts.get(model)):''}${content}<div class="fh-footer">个人账单、订单和投资仅你可见。逐笔确认的共同消费只共享汇总。<br>资金余额仍以原账户为准，导入不会覆盖公共荷包。</div></div>`;
  }
  async function modelEntry(button,action){
    const original=model,actor=original&&modelActors.get(original),node=button.closest('.fh-workspace');
    if(!actor){requireModelActor();return}
    if(!node)return;
    if(!node.querySelector('.error')){
      const error=document.createElement('p');error.className='error';error.setAttribute('role','alert');node.append(error);
    }
    if(isDemo){if(requireModelActor())action();return}
    await reconciliationJob(node,actor,async()=>{if(model===original)action()},button);
  }
  function requireModelActor(){
    const actor=model&&modelActors.get(model);
    if(actor&&matchesActor(actor,user,csrf))return true;
    ++importEpoch;model=null;pending=null;pendingActor=null;
    openModal('财务中枢','<div class="fh-workspace"><p class="error" role="alert">登录成员或家庭已变化，请刷新后重新打开财务中枢。</p>'+buttons('back')+'</div>',true);
    return false;
  }
  function render(){
    if(!model)return;
    if(!modelActors.has(model))modelActors.set(model,importActor());
    if(!requireModelActor())return;
    prepareLedger();
    openModal('财务中枢',shell(tab==='import'?importPanel():tab==='ledger'?ledgerPanel():tab==='investments'?investmentPanel():overviewPanel()),true);
    const selector=document.querySelector('#fh-month');
    if(selector)selector.onchange=()=>{month=selector.value;open(tab)};
    if(tab==='import')bindImport();
    if(tab==='ledger'){bindLedger();if(!ledger.result&&!ledger.error&&!ledger.loading)void loadLedger({fresh:true,refreshTotals:false})}
  }
  function overviewPanel(){
    const cards=model.totals.length?model.totals.map(t=>`<section class="fh-currency"><div class="fh-section-title"><h4>${esc(t.currency)} · 已导入流水</h4><span class="pill">${t.count} 条</span></div><div class="fh-metrics"><div><small>消费减退款</small><strong>${esc(fmt(t.netSpendCents,t.currency))}</strong></div><div><small>已记录收入</small><strong>${esc(fmt(t.incomeCents,t.currency))}</strong></div><div><small>转账 / 理财划转</small><strong>${esc(fmt(t.transferCents,t.currency))}</strong></div></div>${t.duplicateCount?message(`已确认 ${t.duplicateCount} 条重复记录，共 ${fmt(t.duplicateCents,t.currency)}，保留原始记录但不重复计入。`):''}${t.unknownCents?message(`另有 ${fmt(t.unknownCents,t.currency)} 待核对，尚未计入收支。`):''}${t.orderCents?message(`采购订单 ${fmt(t.orderCents,t.currency)} 单列展示，不与支付支出相加。`):''}</section>`).join(''):model.totalRecordCount?`<div class="fh-empty"><span>◎</span><h3>本月尚无记录</h3><p>账本中已有 ${model.totalRecordCount} 条记录，选择有记录的月份继续查看。</p>${monthChoices(model.availableMonths)}</div>`:importReceipts.has(model)?emptyLedger():`<div class="fh-empty"><span>◎</span><h3>从一份账单开始</h3><p>导入支付宝、微信或整理后的 CSV，先核对，再形成你的月度财务视图。</p><button class="btn" data-fh-tab="import">导入第一份账单</button></div>`;
    if(isDemo)return cards+message('以下为虚构演示记录；搜索与翻页完全在此设备内进行，不读取真实账本。');
    const budgets=model.budgets.map(b=>`<article class="fh-budget"><div><strong>${esc(b.category)} · ${esc(b.currency)}</strong><small>${esc(fmt(b.spentCents,b.currency))} / ${esc(fmt(b.amountCents,b.currency))}</small></div><b class="${b.remainingCents<0?'fh-negative':''}">${b.remainingCents<0?'超出':'剩余'} ${esc(fmt(Math.abs(b.remainingCents),b.currency))}</b><button class="btn small secondary" data-fh="edit-budget" data-currency="${esc(b.currency)}" data-category="${esc(b.category)}">调整</button></article>`).join('');
    return `${cards}<section class="fh-section"><div class="fh-section-title"><h4>本月预算</h4><button class="btn small secondary" data-fh="budget">设置预算</button></div>${budgets||message('可按币种设置总预算，或分别为餐饮、旅行、采购等分类设定预算。总预算和分类预算分别比较，不相加。')}</section><div class="fh-actions"><button class="btn secondary" data-fh="shared">查看共同消费汇总</button><button class="btn secondary" data-fh="baseline">个人财务基线</button></div>${message(model.coverage)}${model.imports.length?`<details class="fh-history"><summary>最近导入记录</summary>${model.imports.map(b=>`<p>${esc(sources[b.source]||b.source)} · ${b.importedCount} 条 · ${esc(new Date(b.createdAt).toLocaleString('zh-CN'))}</p>`).join('')}</details>`:''}`;
  }
  function prepareLedger(){
    const actor=modelActors.get(model);
    if(!ledger||ledger.month!==month||!matchesActor(ledger.actor,user,csrf))ledger={actor,month,q:'',draft:'',page:1,pageSize:50,result:null,error:'',loading:false,request:0};
    if(ledger.model!==model){ledger.model=model;ledger.result=null;ledger.error='';ledger.loading=false;ledger.snapshot=''}
  }
  function transactionRecord(id){return ledger?.result?.transactions.find(row=>row.id===id)||model?.transactions.find(row=>row.id===id)}
  function demoModel(){
    const transactions=Array.from({length:123},(_,i)=>({id:'demo-ledger-'+String(i).padStart(3,'0'),revision:1,title:['虚构早餐','虚构旅行采购','虚构交通费'][i%3],date:month+'-'+String(1+i%28).padStart(2,'0'),category:['餐饮','采购','交通'][i%3],externalId:'DEMO-'+i,kind:'payments',source:'generic',flow:'expense',amountCents:1000+i*100,currency:'CNY',visibility:'private'})).sort((a,b)=>b.date.localeCompare(a.date)||b.id.localeCompare(a.id));
    return {month,transactions,transactionCount:transactions.length,totalRecordCount:transactions.length,availableMonths:[{month,recordCount:transactions.length}],totals:[{currency:'CNY',count:transactions.length,netSpendCents:transactions.reduce((sum,row)=>sum+row.amountCents,0),incomeCents:0,transferCents:0}],budgets:[],imports:[],investments:[],investmentTotals:[]};
  }
  function localLedger(state){
    const q=state.q.toLocaleLowerCase(),rows=model.transactions.filter(row=>[row.title,row.category,row.externalId,row.merchantOrderId,row.paymentId,row.originalTransactionId,...orderItems(row).flatMap(item=>[item.title,item.variant])].some(value=>String(value||'').toLocaleLowerCase().includes(q)));
    const totalPages=Math.max(1,Math.ceil(rows.length/state.pageSize)),page=Math.min(state.page,totalPages);
    return {month,q:state.q,page,pageSize:state.pageSize,transactionCount:model.transactionCount,filteredCount:rows.length,totalPages,hasNext:page<totalPages,hasPrevious:page>1,snapshot:'0'.repeat(64),transactions:rows.slice((page-1)*state.pageSize,page*state.pageSize)};
  }
  async function loadLedger({fresh=false,q=ledger.q,page=ledger.page,refreshTotals=fresh}={}){
    if(!requireModelActor()||tab!=='ledger')return;
    const state=ledger,actor=modelActors.get(model),ticket=++state.request;
    state.q=q.trim();state.page=page;state.error='';state.loading=true;
    const snapshot=fresh?'':state.snapshot;state.result=null;
    render();
    if(isDemo){state.result=localLedger(state);state.page=state.result.page;state.snapshot=state.result.snapshot;state.loading=false;render();return}
    const node=document.querySelector('#dialog .fh-workspace');
    try{await importJob(node,async check=>{
      try{
        let overview=null;
        if(refreshTotals){overview=await api('/finance-hub/overview?month='+encodeURIComponent(month));if(!await check())return}
        const params=new URLSearchParams({month:state.month,q:state.q,page:String(state.page),pageSize:String(state.pageSize)});
        if(snapshot)params.set('snapshot',snapshot);
        const result=await api('/finance-hub/transactions?'+params);if(!await check())return;
        if(overview){const receipt=importReceipts.get(model);if(receipt)importReceipts.set(overview,receipt);modelActors.set(overview,actor);model=overview;state.model=model}
        state.result=result;state.page=result.page;state.q=result.q;state.snapshot=result.snapshot;
      }catch(error){
        if(error.status!==409||error.code!=='ledger_changed')throw error;
        if(!await check())return;
        state.error='账本已变化，请刷新账本后继续。搜索内容会保留。';state.snapshot='';
      }
    },actor)}finally{
      // Closed dialogs, newer requests and changed identities must never repaint old rows.
      if(state===ledger&&ticket===state.request&&node.isConnected&&document.querySelector('#dialog').open&&node.querySelector('#fh-ledger-search')){
        state.loading=false;
        if(!state.result&&!state.error)state.error=node.querySelector('.error')?.textContent||'账本暂时未读回，请刷新后重试。';
        render();
      }
    }
  }
  function bindLedger(){
    const form=document.querySelector('#fh-ledger-search');
    form.elements.q.oninput=()=>{ledger.draft=form.elements.q.value};
    form.onsubmit=event=>{event.preventDefault();void loadLedger({fresh:true,q:form.elements.q.value,page:1})};
  }
  function ledgerPanel(){
    const state=ledger,result=state.result,rows=result?.transactions||[];
    const count=result?.transactionCount??model.transactionCount,start=result?.filteredCount?(result.page-1)*result.pageSize+1:0,end=result?Math.min(result.page*result.pageSize,result.filteredCount):0;
    const empty=result?(result.transactionCount===0?emptyLedger():message('没有匹配的记录。试试其他关键词，或清除搜索查看整月账本。')):'';
    return `<section id="fh-ledger-panel" aria-busy="${state.loading}"><div class="fh-section-title"><h4>${esc(month)} · 全月 ${count} 条记录</h4>${isDemo?'':`<button class="btn small" data-fh-tab="import">导入账单 / 订单</button>`}</div><form id="fh-ledger-search" role="search"><label class="field"><span>搜索本月账本</span><input name="q" type="search" maxlength="160" value="${esc(state.draft)}" placeholder="名称、分类、交易编号、商品或规格"></label><div class="fh-actions"><button class="btn" type="submit">搜索</button><button class="btn secondary" type="button" data-fh="ledger-clear">清除搜索</button><button class="btn secondary" type="button" data-fh="ledger-refresh">刷新账本</button></div></form>${message('月度概览始终按全月记录计算；搜索只筛选明细，不改变月度支出。')}${isDemo?message('虚构演示 · 不读取真实账户，也不保存修改。'):message('在每笔记录的“核对 → 关联与对账”中匹配订单、付款和部分退款，或确认跨文件重复支付。')}<p class="error" role="alert">${esc(state.error)}</p><p class="fh-ledger-status" role="status" aria-live="polite">${state.loading?'正在读取账本…':result?`${state.q?'筛选“'+esc(state.q)+'” · ':''}${result.filteredCount} 条${state.q?'匹配':'记录'} · 显示 ${start}–${end} 条 · 第 ${result.page} / ${result.totalPages} 页`:''}</p><div class="fh-ledger">${rows.map(t=>`<article class="fh-transaction"><div class="fh-transaction-icon">${t.kind==='orders'?'▣':t.flow==='income'?'↙':t.flow==='refund'?'↩':'↗'}</div><div class="fh-transaction-main"><strong>${esc(t.title)}</strong><small>${esc(t.date)} · ${esc(sources[t.source]||t.source)} · ${esc(t.category)}</small><div class="fh-tags"><span>${t.kind==='orders'?'采购订单':esc(labels[t.flow])}</span>${t.visibility==='shared'?'<span class="fh-shared">共同汇总</span>':''}${t.checkedAt?'<span>已核对</span>':''}${t.reconciliation?.duplicateOf?'<span>已确认重复 · 不计入</span>':''}${t.reconciliation?.relationCount?'<span>'+t.reconciliation.relationCount+' 项关联</span>':''}</div>${orderItemsMarkup(t)}</div><div class="fh-transaction-value"><strong>${esc(fmt(t.amountCents,t.currency))}</strong>${isDemo?'':`<button class="btn small secondary" data-fh="transaction" data-id="${esc(t.id)}">核对</button>`}${!isDemo&&window.ShoppingSettlement&&t.currency==='CNY'&&(t.kind==='orders'||t.flow==='expense')?`<button class="btn small secondary" data-fh="shopping-settlement" data-id="${esc(t.id)}">关联采购</button>`:''}</div></article>`).join('')||empty}</div><nav class="fh-ledger-pages" aria-label="账本分页"><button class="btn secondary" type="button" data-fh="ledger-previous" ${!result?.hasPrevious||state.loading?'disabled':''}>上一页</button><span>${result?`${result.page} / ${result.totalPages}`:'—'}</span><button class="btn secondary" type="button" data-fh="ledger-next" ${!result?.hasNext||state.loading?'disabled':''}>下一页</button></nav></section>`;
  }
  function investmentPanel(){
    const groups=model.investmentTotals.map(t=>`<section class="fh-currency"><h4>${esc(t.currency)} · 投资组合</h4><div class="fh-metrics"><div><small>已估值部分</small><strong>${esc(fmt(t.valueCents,t.currency))}</strong></div><div><small>对应持仓账面盈亏</small><strong class="${t.unrealizedGainCents<0?'fh-negative':''}">${esc(fmt(t.unrealizedGainCents,t.currency))}</strong></div><div><small>未估值项目</small><strong>${t.unvaluedCount} 项</strong></div></div><div class="fh-allocation">${t.allocation.map(a=>`<span>${esc(a.assetType)} ${a.percent===null?'—':a.percent+'%'}</span>`).join('')}</div></section>`).join('');
    return `<div class="fh-section-title"><h4>我的投资账户</h4><div class="fh-actions"><button class="btn small secondary" data-investment-import-open>导入 / 更新持仓</button><button class="btn small" data-fh="investment">添加资产</button></div></div>${message('按币种汇总已核对的持仓成本与现值。盈亏为已估值持仓的现值减成本，不含分红、已实现收益、税费或汇率变化。此处不会与历史资产基线自动相加。')}${groups}<div class="fh-ledger">${model.investments.map(i=>`<article class="fh-transaction"><div class="fh-transaction-main"><strong>${esc(i.name)}</strong><small>${esc(i.institution)} · ${esc(i.assetType)}${i.quantity!==null?' · 数量 '+esc(i.quantity):''}</small><small>${i.valuationSource==='file_import'?'文件核对':'手动核对'} ${esc(i.asOf)}</small></div><div class="fh-transaction-value"><strong>${esc(fmt(i.valueCents,i.currency))}</strong><small>成本 ${esc(fmt(i.costCents,i.currency))}</small><button class="btn small secondary" data-fh="investment" data-id="${esc(i.id)}">编辑</button></div></article>`).join('')||message('添加国内或海外账户中的资产；现值未知时留空，系统会保留待估值状态。')}</div><details class="fh-history"><summary>机构连接状态</summary><p>银行、券商及理财机构：当前使用手动记录或持仓整理表导入。机构名称可自行填写（如微众银行、工商银行、建设银行或海外机构）。自动账户连接与实时行情尚未接入。</p></details>`;
  }
  function importPanel(){
    return `<div class="fh-import-head"><span class="fh-step">01 选择文件</span><span class="fh-step">02 检查预览</span><span class="fh-step">03 确认入账</span></div><form id="fh-import-form"><div class="form-grid"><label class="field"><span>数据来源</span><select name="source">${Object.entries(sources).map(([id,label])=>option(id,label,'alipay')).join('')}</select></label><label class="field"><span>记录类型</span><select name="kind"><option value="payments">支付账单（计入收支）</option><option value="orders">购物订单（单独统计）</option></select></label><label class="field"><span>CSV 文件编码</span><select name="encoding"><option value="auto">自动识别 UTF-8 / GB18030</option><option value="utf-8">UTF-8</option><option value="gb18030">GB18030 / GBK</option></select></label><label class="field"><span>CSV / XLSX 文件</span><input type="file" name="file" accept=".csv,.txt,.xlsx,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required></label><label class="field"><span>XLSX 工作表名称（可选）</span><input name="sheet" maxlength="100" placeholder="留空先选择工作表"></label></div>${message('文件最多 2 MB；CSV 最多 5000 条记录，XLSX 最多 5000 行、80 列且展开后不超过 8 MB。支持常见中文列名与通用模板。文件只用于本次导入，不保存原始附件。')}${message('请选择无宏、无公式、无外部链接的 XLSX；加密文件及旧版 XLS 需要先在本机解密或另存。读取成功后仍需核对日期、币种、收支与编号。')}<div class="info-box">所有导入默认仅你可见。确认导入后，可逐笔标为共同消费。这里不需要输入支付密码或平台登录凭证。</div><div class="error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" type="button" data-fh="template">下载 CSV 模板</button><button class="btn" type="submit">读取并预览</button></div></form>`;
  }
  function bindImport(){
    const form=document.querySelector('#fh-import-form');
    pending=null;pendingActor=null;
    const invalidate=()=>{++importEpoch;pending=null;pendingActor=null};
    form.addEventListener('input',invalidate);form.addEventListener('change',invalidate);
    form.elements.source.onchange=()=>{form.elements.kind.value=['taobao','pinduoduo'].includes(form.elements.source.value)?'orders':'payments'};
    form.onsubmit=async e=>{
      e.preventDefault();const b=form.querySelector('[type=submit]');b.disabled=true;form.querySelector('.error').textContent='';
      const actor=importActor(),source=form.elements.source.value,kind=form.elements.kind.value,encoding=form.elements.encoding.value,sheet=form.elements.sheet.value.trim();
      try{await importJob(form,async check=>{
        const file=form.elements.file.files[0];if(!file)throw new Error('请选择文件');
        if(file.size>2*1024*1024)throw new Error('文件最多 2 MB，请拆分后导入');
        if(!/\.(csv|txt|xlsx)$/i.test(file.name))throw new Error('请选择 CSV、TXT 或 XLSX 文件；旧版 XLS 与宏文件不支持');
        const bytes=new Uint8Array(await file.arrayBuffer()),parts=[];
        if(!await check())return;
        for(let offset=0;offset<bytes.length;offset+=32768)parts.push(String.fromCharCode(...bytes.subarray(offset,offset+32768)));
        const payload={source,kind,file:{name:file.name,contentBase64:btoa(parts.join('')),encoding,sheet}};
        if(/\.xlsx$/i.test(file.name)&&!sheet)payload.inspectSheets=true;
        if(new Blob([JSON.stringify(payload)]).size>2900000)throw new Error('文件内容较大，请按月份拆分');
        const preview=await write('/finance-hub/imports/preview','POST',payload);
        if(!await check())return;
        pending={...payload,previewToken:preview.previewToken};pendingActor=actor;
        previewPanel(preview);
      },actor)}
      finally{b.disabled=false}
    };
  }
  function amountPanel(p){
    const selection=p.amountSelection;if(!selection)return '';
    const chosen=selection.columns.find(column=>column.index===selection.selectedIndex);
    const origin=chosen?message(`金额来源：${chosen.columnLabel} 列 · ${chosen.label}（表头第 ${selection.headerLine} 行）`):'';
    if(!selection.required)return `<div class="fh-amount-origin">${origin}</div>`;
    return `<section class="fh-amount-selection">${origin}<form id="fh-amount-form"><fieldset><legend>${p.requiresAmountSelection?'请选择本次使用的金额列':'核对本次使用的金额列'}</legend><p class="fh-note">识别到多个金额列，列名不能证明实付口径。请按原文件选择；只使用所选列，不把各列相加。</p>${selection.columns.map(column=>`<label class="fh-amount-option"><input type="radio" name="amountColumn" value="${column.index}" ${column.index===selection.selectedIndex?'checked':''} required><span><strong>${esc(column.columnLabel)} 列</strong><span>${esc(column.label)}</span></span></label>`).join('')}</fieldset><p class="fh-note" id="fh-amount-state">${p.requiresAmountSelection?'选择金额列后才能生成入账预览。':'更改金额列后需要重新预览。'}</p><button class="btn secondary" type="submit">按所选金额列重新预览</button></form></section>`;
  }
  function previewPanel(p){
    const info=p.fileInfo;
    const awaitingChoice=p.requiresAmountSelection||p.requiresSheetSelection;
    const isOrders=pending?.kind==='orders',unit=isOrders?' 单':' 条';
    const fileNote=info?message(`${info.name} · ${info.format.toUpperCase()} · ${info.encoding}`)+message(info.note)+(info.format==='xlsx'?`<section class="fh-sheet-selection"><label class="field"><span>${p.requiresSheetSelection?'请选择账单工作表':'只读取所选工作表，可切换后重新预览'}</span><select id="fh-sheet-select">${p.requiresSheetSelection?'<option value="" selected disabled>请选择工作表</option>':''}${info.sheets.map(name=>option(name,name,info.sheet)).join('')}</select></label><p class="fh-note" id="fh-sheet-state">${info.sheet?'当前预览工作表：'+esc(info.sheet):'尚未解析记录；工作表名称不代表其中的单元格已通过校验。'}</p><button type="button" class="btn small secondary" id="fh-sheet-retry" ${info.sheet?'':'disabled'}>读取所选工作表</button></section>`:''):'';
    openModal(p.requiresSheetSelection?'选择账单工作表':'确认导入预览',`<div class="fh-workspace" id="fh-import-preview">${p.requiresSheetSelection?fileNote:''}${amountPanel(p)}<div class="fh-metrics"><div><small>准备导入</small><strong>${awaitingChoice?'待选择':p.newCount+unit}</strong></div><div><small>重复跳过</small><strong>${awaitingChoice?'待预览':p.duplicateCount+unit}</strong></div><div><small>需要修正</small><strong>${awaitingChoice?'待预览':p.errorCount+' 行'}</strong></div></div>${p.requiresSheetSelection?'':fileNote}${p.warnings.map(message).join('')}${p.errors.map(e=>`<div class="error">第 ${e.line} 行：${esc(e.message)}</div>`).join('')}${p.conflictCount?`<p class="fh-note fh-order-summary" data-fh-import-conflicts>${esc(p.conflictCount)}${unit}与原记录不同 · 保留原记录。确认不会覆盖原金额或内容。</p>`:''}${orderPreviewSummary(p.rows)}<div class="fh-preview-scroll"><table class="fh-table"><thead><tr><th>日期 / 名称</th><th>${isOrders?'订单金额':'金额'}</th><th>识别结果</th></tr></thead><tbody>${p.rows.slice(0,100).map(r=>`<tr data-fh-preview-row><td>${esc(r.date)}<br>${esc(r.title)}</td><td>${esc(fmt(r.amountCents,r.currency))}</td><td>${r.conflict?'与原记录不同 · 保留原记录':r.duplicate?'重复 · 跳过':esc(r.kind==='orders'?'采购订单':labels[r.flow])}</td></tr>${orderItems(r).length?`<tr class="fh-order-items-row"><td colspan="3">${orderItemsMarkup(r)}</td></tr>`:''}`).join('')}</tbody></table></div>${p.rows.length>100?message(isOrders?'预览表展示前 100 个订单，确认将处理全部有效订单；商品明细不会另计订单实付。':'预览表展示前 100 行，确认将处理全部有效行。'):''}${message('尚未写入账本。预览有效期 20 分钟；有错误行时需修正整个文件后再导入。')}<div class="error" id="fh-confirm-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-fh="back-import">重新选文件</button><button class="btn" data-fh="confirm" ${p.errorCount||!p.previewToken?'disabled':''}>确认导入 · 仅本人</button></div></div>`,true);
    const node=document.querySelector('#fh-import-preview'),actor=pendingActor;
    document.querySelector('#dialog').scrollTop=0;
    node.closest('.dialog-content').scrollTop=0;
    const repreview=async payload=>{
      const confirm=node.querySelector('[data-fh=confirm]');confirm.disabled=true;
      await importJob(node,async check=>{const result=await write('/finance-hub/imports/preview','POST',payload);if(!await check())return;pending={...payload,previewToken:result.previewToken};pendingActor=actor;previewPanel(result)},actor);
    };
    const amountForm=node.querySelector('#fh-amount-form');
    if(amountForm){
      amountForm.onchange=()=>{++importEpoch;pending={...pending,previewToken:null};node.querySelector('[data-fh=confirm]').disabled=true;node.querySelector('#fh-amount-state').textContent='金额列已变化，请重新预览。'};
      amountForm.onsubmit=async event=>{event.preventDefault();const b=amountForm.querySelector('[type=submit]');b.disabled=true;try{await repreview({...pending,amountColumn:Number(amountForm.elements.amountColumn.value),previewToken:null})}finally{b.disabled=false}};
    }
    const selector=node.querySelector('#fh-sheet-select');
    if(selector){
      const retry=node.querySelector('#fh-sheet-retry'),state=node.querySelector('#fh-sheet-state');
      const invalidateSheet=()=>{
        ++importEpoch;
        pending={...pending,file:{...pending.file,sheet:selector.value},previewToken:null};delete pending.amountColumn;delete pending.inspectSheets;
        node.querySelector('[data-fh=confirm]').disabled=true;
        node.querySelector('.fh-amount-selection')?.remove();
        node.querySelector('.fh-amount-origin')?.remove();
        node.querySelector('.fh-table tbody').replaceChildren();
        node.querySelectorAll('.fh-metrics strong').forEach(item=>item.textContent='待预览');
        node.querySelectorAll('.error').forEach(item=>item.textContent='');
        state.textContent='工作表已变化，尚未生成有效预览。';retry.disabled=!selector.value;
      };
      const readSheet=async()=>{
        if(!selector.value)return;
        invalidateSheet();retry.disabled=true;state.textContent='正在读取所选工作表，请等待预览。';
        const payload=pending,requestEpoch=importEpoch+1;
        try{await repreview(payload)}finally{
          if(selector.isConnected&&importEpoch===requestEpoch){retry.disabled=false;state.textContent='工作表尚未生成有效预览，可重新读取、换表或修正文件。'}
        }
      };
      selector.oninput=invalidateSheet;selector.onchange=readSheet;retry.onclick=readSheet;
    }
  }
  function bindEditor(action){
    const form=document.querySelector('#fh-editor');
    const actor=modelActors.get(model);form._fhActor=actor;
    form.onsubmit=async e=>{e.preventDefault();await reconciliationJob(form,actor,async(check,markSent)=>{markSent();await action(Object.fromEntries(new FormData(form)));if(!await check())return;await open(tab);toast('已保存')},form.querySelector('[type=submit]'))};
  }
  function editorFooter(deleteAction='',id=''){
    return `<div class="error" role="alert"></div><div class="dialog-footer">${deleteAction?`<button type="button" class="btn danger" data-fh="${deleteAction}" data-id="${esc(id)}">删除</button>`:''}<button class="btn secondary" type="button" data-fh="back">返回</button><button class="btn" type="submit">保存</button></div>`;
  }
  function transactionEditor(id){
    if(!requireModelActor())return;
    const t=transactionRecord(id);if(!t)return;
    openModal('核对账单',`<form id="fh-editor"><h3>${esc(t.title)}</h3>${message(`${t.date} · ${fmt(t.amountCents,t.currency)} · ${sources[t.source]} · ${t.externalId||'无交易编号'}`)}${orderItemsMarkup(t)}${field('category','预算分类',t.category,'maxlength="60" required')}<label class="field"><span>收支方向</span><select name="flow">${Object.entries(labels).map(([v,l])=>option(v,l,t.flow)).join('')}</select></label><label class="field"><span>可见范围</span><select name="visibility">${option('private','仅本人',t.visibility)}${t.kind==='payments'?option('shared','共同消费汇总（不共享明细）',t.visibility):''}</select></label>${message('转账、充值、还款和理财划转不作为消费或工资收入；有退款状态的原消费请核对是否为独立退款记录。')}${editorFooter('delete-transaction',id)}</form>`);
    bindEditor(v=>write('/finance-hub/transactions/'+id,'PATCH',{...v,revision:t.revision}));
    const form=document.querySelector('#fh-editor');
    form._fhActor=modelActors.get(model);
    const link=document.createElement('button');link.type='button';link.className='btn secondary fh-reconcile-entry';link.dataset.fh='reconcile';link.dataset.id=id;link.textContent='关联与对账 · 订单 / 支付 / 退款';form.prepend(link);
  }

  function reconciliationRecord(t,label=''){
    if(!t)return `<div class="fh-match-record">${message('原记录已删除；历史关系已撤销。')}</div>`;
    const ids=[['编号',t.externalId],['商户订单号',t.merchantOrderId],['支付号',t.paymentId],['原交易号',t.originalTransactionId]].filter(([,value])=>value);
    return `<div class="fh-match-record">${label?`<small>${esc(label)}</small>`:''}<strong>${esc(t.title)}</strong><b>${esc(fmt(t.amountCents,t.currency))}</b><small>${esc(t.date)} · ${esc(sources[t.source]||t.source)} · ${esc(t.kind==='orders'?'购物订单':labels[t.flow])}</small>${ids.map(([name,value])=>`<small>${name}：${esc(value)}</small>`).join('')}${orderItemsMarkup(t)}</div>`;
  }

  function reconciliationSnapshot(node){
    return JSON.stringify([...node.querySelectorAll('input,select,textarea')].map(input=>[input.name,input.value,input.checked]));
  }
  async function reconciliationJob(node,actor,work,button){
    if(!node||!actor||!node.isConnected||!document.querySelector('#dialog').open||button?.disabled)return;
    const epoch=++importEpoch,snapshot=reconciliationSnapshot(node),container=node.closest('.dialog-content');
    const active=()=>epoch===importEpoch&&node.isConnected&&node.closest('.dialog-content')===container&&document.querySelector('#dialog').open&&snapshot===reconciliationSnapshot(node);
    let sent=false;
    if(button){button._fhReconciliationJob=epoch;button.disabled=true}
    const check=async()=>{
      if(!active())return false;
      if(!matchesActor(actor,user,csrf)){const error=new Error('登录成员或家庭已变化，请刷新后重新打开财务中枢。');error.contextChanged=true;throw error}
      const me=await api('/me');
      if(!active())return false;
      if(!matchesActor(actor,user,csrf)||!matchesActor(actor,me.user,me.csrf)){
        const error=new Error('登录成员或家庭已变化，请刷新后重新打开财务中枢。');error.contextChanged=true;throw error;
      }
      return true;
    };
    try{
      if(await check())await work(check,()=>{sent=true});
    }catch(error){
      if(!active())return;
      if(!error.contextChanged&&![401,403].includes(error.status)){
        try{if(!await check())return}catch(identityError){error=identityError}
      }
      if(!active())return;
      if(error.contextChanged||[401,403].includes(error.status)){
        ++importEpoch;pending=null;pendingActor=null;
        container.innerHTML='<p class="error" role="alert">登录成员或家庭已变化，请刷新后重新打开财务中枢。</p>'+buttons('back');return;
      }
      const target=container.querySelector('.error');
      if(target)target.textContent=(error.message||'无法核对，请重试。')+(sent?' 请求已经发出，关闭页面不会撤销；请重试核对结果。':'');
    }finally{
      if(button?.isConnected&&button._fhReconciliationJob===epoch)button.disabled=false;
    }
  }
  async function openReconciliation(id,query='',node,button){
    node=node||document.querySelector('#dialog .dialog-content');
    const actor=node?._fhActor||node?.closest('.fh-workspace')?._fhActor;
    await reconciliationJob(node,actor,async check=>{
      const result=await api('/finance-hub/reconciliation?transactionId='+encodeURIComponent(id)+'&q='+encodeURIComponent(query));
      if(!await check())return;
      renderReconciliation(result,id,query,actor);
    },button);
  }
  async function openReconciliationEntry(id,options={}){
    if(!canEdit()||isTV||isDemo||typeof id!=='string'||!id||id.length>160)return;
    const actor=importActor();
    shoppingReturn={actor,transactionId:id};
    if(typeof options?.shoppingId==='string'&&options.shoppingId&&options.shoppingId.length<=160)shoppingReturn.shoppingId=options.shoppingId;
    ++importEpoch;pending=null;pendingActor=null;activeManager='';
    openModal('关联与对账','<div class="fh-workspace fh-reconciliation-entry"><p class="help">正在读取本人记录…</p><p class="error" role="alert"></p></div>',true);
    const node=document.querySelector('#dialog .fh-reconciliation-entry');
    node._fhActor=actor;
    await openReconciliation(id,'',node);
  }
  function renderReconciliation(reconciliation,id,query,actor){
    const t=reconciliation.transaction,state=t.reconciliation;
    const status=state.duplicateOf?'此原始记录已确认为重复，当前不计入收支。':t.kind==='orders'?`已关联付款 ${fmt(state.allocatedCents,t.currency)}；待关联 ${fmt(state.unallocatedCents,t.currency)}。`:t.flow==='refund'?`已关联原付款 ${fmt(state.allocatedCents,t.currency)}；未分配退款 ${fmt(state.unallocatedCents,t.currency)}。`:t.flow==='expense'?`已关联退款 ${fmt(state.refundedCents,t.currency)}；原付款减已关联退款 ${fmt(state.remainingAfterRefundCents,t.currency)}。`:'此方向不参与订单付款或退款关联，请先核对收支方向。';
    const relations=reconciliation.relations.map(r=>`<article class="fh-match"><div class="fh-section-title"><strong>${esc(relationLabels[r.kind])} · ${r.status==='active'?'已确认':'已撤销'}</strong><span>${esc(fmt(r.amountCents,t.currency))}</span></div><div class="fh-match-pair">${reconciliationRecord(r.left,r.kind==='duplicate'?'原始重复记录':'关联来源')}${reconciliationRecord(r.right,r.kind==='duplicate'?'保留记录':'原付款')}</div><div class="fh-actions">${[r.left,r.right].filter(v=>v&&v.id!==id).map(v=>`<button class="btn small secondary" data-fh="reconcile" data-id="${esc(v.id)}">查看另一条记录的关联</button>`).join('')}${r.status==='active'?`<button class="btn small secondary" data-fh="revoke-reconciliation" data-id="${esc(r.id)}">撤销这项关系</button>`:''}</div></article>`).join('');
    const candidates=reconciliation.candidates.map((c,index)=>`<article class="fh-match"><div class="fh-section-title"><strong>${esc(relationLabels[c.kind])}</strong><span class="pill">${c.identifierMatch?'编号相符 · 待核实':'可能相关 · 待核实'}</span></div><div class="fh-match-pair">${reconciliationRecord(c.left,c.kind==='duplicate'?'确认后排除这条':'订单 / 退款')}${reconciliationRecord(c.right,c.kind==='duplicate'?'确认后保留这条':'对应付款')}</div>${message(c.reasons.join('；'))}${message(c.uncertainty[0])}<button class="btn small secondary" data-fh="choose-reconciliation" data-index="${index}">核对这组候选</button></article>`).join('');
    openModal('关联与对账',`<div class="fh-workspace"><div class="fh-section-title"><h3>${esc(t.title)}</h3>${buttons('back')}</div>${message(status)}${orderItemsMarkup(t)}${message(reconciliation.note)}<section class="fh-section"><h4>已确认与撤销记录</h4>${relations||message('尚未建立关联。确认前不会改变账本或预算。')}</section><section class="fh-section"><h4>查找候选</h4><form id="fh-match-search"><label class="field"><span>另一条记录的标题或原始编号</span><input name="query" maxlength="160" value="${esc(query)}" placeholder="留空按日期、金额和编号推荐"></label><button class="btn secondary" type="submit">查找</button></form>${candidates||message('没有可分配的候选。可以按标题或原始编号查找；其他币种或其他成员的记录不会出现。')}${reconciliation.truncated?message(`找到 ${reconciliation.candidateCount} 组，展示前 40 组；请输入更具体的编号筛选。`):''}</section><div class="error" id="fh-reconciliation-error" role="alert"></div></div>`,true);

    const node=document.querySelector('#dialog .fh-workspace'),form=node.querySelector('#fh-match-search');
    node._fhActor=actor;node._fhReconciliation={data:reconciliation,focus:id,actor};
    if(shoppingReturn&&JSON.stringify(shoppingReturn.actor)===JSON.stringify(actor)&&window.ShoppingSettlement){
      node._fhShoppingReturn=shoppingReturn;
      const back=document.createElement('button');back.type='button';back.className='btn secondary';
      back.dataset.fh='return-shopping-settlement';back.textContent='返回采购实付核对';node.append(back);
    }
    form._fhActor=actor;
    form.onsubmit=async event=>{
      event.preventDefault();await openReconciliation(id,form.elements.query.value,form,form.querySelector('button'));
    };
  }
  async function chooseReconciliation(index,node,button){
    const state=node?._fhReconciliation,c=state?.data?.candidates[index];if(!c)return;
    await reconciliationJob(node,state.actor,async()=>{
      renderReconciliationChoice(c,state.focus,state.actor);
    },button);
  }
  function renderReconciliationChoice(c,focus,actor){
    openModal('核对关联金额',`<form id="fh-reconciliation-form" class="fh-workspace"><h3>${esc(relationLabels[c.kind])}</h3><div class="fh-match-pair">${reconciliationRecord(c.left,c.kind==='duplicate'?'将从统计中排除':'订单 / 退款')}${reconciliationRecord(c.right,c.kind==='duplicate'?'将保留计入统计':'对应付款')}</div>${c.reasons.map(message).join('')}${c.uncertainty.map(message).join('')}${field('amount',c.kind==='duplicate'?'重复金额（整条）':'本次分配金额 · '+c.left.currency,String(c.suggestedAmountCents/100),'type="number" min="0.01" step="0.01" max="'+(c.maxAmountCents/100)+'" required'+(c.kind==='duplicate'?' readonly':''))}${message('可分配上限 '+fmt(c.maxAmountCents,c.left.currency)+'。原始记录金额保持不变。')}<div class="error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" type="button" data-fh="reconcile" data-id="${esc(focus)}">返回候选</button><button class="btn" type="submit">预览影响</button></div></form>`,true);

    const form=document.querySelector('#fh-reconciliation-form');form._fhActor=actor;
    form.onsubmit=async event=>{
      event.preventDefault();
      const payload={kind:c.kind,leftId:c.left.id,rightId:c.right.id,amount:form.elements.amount.value};
      await reconciliationJob(form,actor,async check=>{
        const result=await write('/finance-hub/reconciliation/preview','POST',payload);
        if(!await check())return;
        showReconciliationPreview(result,focus,actor);
      },form.querySelector('[type=submit]'));
    };
  }
  function showReconciliationPreview(p,focus,actor){
    openModal('确认对账关系',`<div class="fh-workspace"><h3>${esc(relationLabels[p.kind])} · ${esc(fmt(p.amountCents,p.left.currency))}</h3><div class="fh-match-pair">${reconciliationRecord(p.left,p.kind==='duplicate'?'排除重复':'关联来源')}${reconciliationRecord(p.right,p.kind==='duplicate'?'保留记录':'原付款')}</div><div class="info-box">${esc(p.effect)}</div>${p.uncertainty.map(message).join('')}${message('请核对原账单。确认后可撤销；预览 20 分钟有效，记录变化后需重新预览。')}<div class="error" id="fh-reconciliation-error" role="alert"></div><div class="dialog-footer"><button class="btn secondary" data-fh="reconcile" data-id="${esc(focus)}">返回候选</button><button class="btn" data-fh="confirm-reconciliation">确认这项关系</button></div></div>`,true);
    const node=document.querySelector('#dialog .fh-workspace');
    node._fhActor=actor;node._fhReconciliation={preview:p,focus,actor};
  }
  async function writeReconciliation(action,id,node,button){
    const state=node?._fhReconciliation;if(!state)return;
    const preview=state.preview,relation=state.data?.relations.find(value=>value.id===id);
    if(action==='confirm-reconciliation'&&!preview?.previewToken)return;
    if(action==='revoke-reconciliation'&&!relation)return;
    if(action==='revoke-reconciliation'&&!confirm('撤销这项关系？重复记录会重新计入统计，退款会恢复原分类；原始账单保留。'))return;
    const url=action==='confirm-reconciliation'?'/finance-hub/reconciliation/confirm':'/finance-hub/reconciliation/'+relation.id+'/revoke';
    const payload=action==='confirm-reconciliation'?{previewToken:preview.previewToken}:{revision:relation.revision};
    const {focus,actor}=state;
    await reconciliationJob(node,actor,async(check,markSent)=>{
      markSent();await write(url,'POST',payload);
      if(!await check())return;
      const result=await api('/finance-hub/reconciliation?transactionId='+encodeURIComponent(focus)+'&q=');
      if(!await check())return;
      renderReconciliation(result,focus,'',actor);
      toast(action==='confirm-reconciliation'?'已确认关系，汇总与预算已更新':'关系已撤销');
    },button);
  }
  function investmentEditor(id){
    if(!requireModelActor())return;
    const i=model.investments.find(r=>r.id===id)||{};
    const decimal=c=>c===undefined||c===null?'':String(c/100);
    openModal(id?'更新投资记录':'添加投资资产',`<form id="fh-editor"><div class="form-grid">${field('name','资产 / 产品名称',i.name,'maxlength="120" required')}${field('institution','机构名称',i.institution,'maxlength="120" required placeholder="银行、券商或理财机构"')}${field('assetType','资产类型',i.assetType||'存款','maxlength="60" required list="fh-asset-types"')}<datalist id="fh-asset-types"><option value="存款"><option value="理财"><option value="股票"><option value="基金"><option value="债券"><option value="保险"><option value="其他"></datalist>${field('currency','币种',i.currency||'CNY','maxlength="3" pattern="[A-Za-z]{3}" required')}${field('quantity','数量（可选）',i.quantity||'','inputmode="decimal"')}${field('cost','持仓总成本',decimal(i.costCents),'type="number" min="0" step="0.01" required')}${field('value','当前总估值（未知可留空）',decimal(i.valueCents),'type="number" min="0" step="0.01"')}${field('asOf','估值 / 核对日期',i.asOf||dateKey(),'type="date" required')}</div><label class="field"><span>备注</span><textarea name="note" maxlength="1000">${esc(i.note||'')}</textarea></label>${message('填写总成本与总估值；数量仅作记录，不会从行情网站推算价格。仅本人可见。')}${editorFooter(id?'delete-investment':'',id||'')}</form>`,true);
    bindEditor(v=>write('/finance-hub/investments'+(id?'/'+id:''),id?'PATCH':'POST',{...v,...(id?{revision:i.revision}:{})}));
  }
  function budgetEditor(currency='',category=''){
    if(!requireModelActor())return;
    const b=model.budgets.find(r=>r.currency===currency&&r.category===category);
    openModal('本月预算',`<form id="fh-editor">${field('currency','币种',currency||'CNY','required maxlength="3" pattern="[A-Za-z]{3}"'+(b?' readonly':''))}${field('category','分类（全部表示本月总预算）',category||'全部','required maxlength="60"'+(b?' readonly':''))}${field('amount','预算金额',b?b.amountCents/100:'','type="number" min="0" step="0.01" required')}${message('预算仅与当前月份同币种的已导入消费减退款比较。若导入覆盖不完整，剩余预算也只是已记录口径。')}${editorFooter()}</form>`);
    bindEditor(v=>write('/finance-hub/budgets','PUT',{...v,month,revision:b?.revision||0}));
  }
  async function sharedPanel(){
    const s=await api('/finance-hub/shared?month='+encodeURIComponent(month));
    openModal('共同消费汇总',`<div class="fh-workspace"><h3>${esc(month)}</h3>${s.totals.map(t=>`<section class="fh-currency"><h4>${esc(t.currency)}</h4><div class="fh-metrics"><div><small>共同消费减退款</small><strong>${esc(fmt(t.netSpendCents,t.currency))}</strong></div><div><small>已确认记录</small><strong>${t.count} 条</strong></div></div></section>`).join('')||message('还没有成员将本月消费确认为共同消费。')}${message(s.note)}${buttons('back')}</div>`,true);
  }
  document.addEventListener('click',async e=>{
    const tabButton=e.target.closest('[data-fh-tab]');
    if(tabButton&&!isTV&&(canEdit()||isDemo)){const nextTab=tabButton.dataset.fhTab;await modelEntry(tabButton,()=>{tab=nextTab;render()});return}
    const b=e.target.closest('[data-fh]');if(!b||isTV||(!canEdit()&&!isDemo)||b.disabled)return;
    const a=b.dataset.fh,id=b.dataset.id;
    try{
      if(a.startsWith('ledger-')){
        if(a==='ledger-clear'){ledger.draft='';await loadLedger({fresh:true,q:'',page:1})}
        else if(a==='ledger-refresh')await loadLedger({fresh:true,q:ledger.draft});
        else if(a==='ledger-next'||a==='ledger-previous')await loadLedger({page:ledger.page+(a==='ledger-next'?1:-1)});
        return;
      }
      if(isDemo)return;
      if(a==='shopping-settlement'){
        if(window.ShoppingSettlement)await modelEntry(b,()=>window.ShoppingSettlement.open({transactionId:id}));
        return;
      }
      if(a==='return-shopping-settlement'){
        const node=b.closest('.fh-workspace'),target=node?._fhShoppingReturn;
        if(target&&window.ShoppingSettlement)await reconciliationJob(node,target.actor,async()=>{
          shoppingReturn=null;await window.ShoppingSettlement.open({transactionId:target.transactionId,...(target.shoppingId?{shoppingId:target.shoppingId}:{})});
        },b);
        return;
      }
      if(a==='open'||a==='back'){await open(tab);return}
      if(a==='baseline'){await FinanceBaseline.openPrivate();return}
      if(a==='back-import'){pending=null;await open('import');return}
      if(a==='transaction'){await modelEntry(b,()=>transactionEditor(id));return}
      if(a==='reconcile'){await openReconciliation(id,'',b.closest('#fh-editor,.fh-workspace'),b);return}
      if(a==='choose-reconciliation'){await chooseReconciliation(Number(b.dataset.index),b.closest('.fh-workspace'),b);return}
      if(a==='confirm-reconciliation'||a==='revoke-reconciliation'){await writeReconciliation(a,id,b.closest('.fh-workspace'),b);return}
      if(a==='investment'){await modelEntry(b,()=>investmentEditor(id));return}
      if(a==='budget'||a==='edit-budget'){await modelEntry(b,()=>budgetEditor(b.dataset.currency,b.dataset.category));return}
      if(a==='shared'){await sharedPanel();return}
      if(a==='template'){
        const kind=document.querySelector('#fh-import-form')?.elements.kind.value||'payments';
        const r=await api('/finance-hub/template?kind='+kind);const url=URL.createObjectURL(new Blob(['\ufeff'+r.csv],{type:'text/csv;charset=utf-8'}));
        const link=document.createElement('a');link.href=url;link.download=r.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
      }
      if(a==='month'){await navigateMonth(b);return}
      if(a==='confirm'||a==='receipt-retry'||a==='receipt-month'){
        if(a==='receipt-month'){const flow=b.closest('#fh-import-preview')?._fhImportResult;if(!flow||flow.inFlight)return;flow.target=b.dataset.month}
        await confirmImport(b);return;
      }
      if(a==='delete-transaction'||a==='delete-investment'){
        if(!requireModelActor())return;
        const investment=a==='delete-investment',r=investment?model.investments.find(t=>t.id===id):transactionRecord(id);if(!r)return;
        if(!confirm('删除这条记录？此操作仅影响本人的看板记录。'))return;
        await reconciliationJob(b.closest('#fh-editor,.fh-workspace'),modelActors.get(model),async(check,markSent)=>{markSent();await write('/finance-hub/'+(investment?'investments/':'transactions/')+id,'DELETE',{revision:r.revision});if(!await check())return;await open(tab);toast('已删除')},b);return;
      }
    }catch(err){const error=document.querySelector('#fh-confirm-error,#fh-reconciliation-error,#fh-editor .error');if(error)error.textContent=err.message;else toast(err.message);b.disabled=false}
  });
  return {open,openReconciliation:openReconciliationEntry};
})();
