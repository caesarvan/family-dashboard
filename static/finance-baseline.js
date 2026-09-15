/* Shared recorded subtotals; account and income records are fetched only on the owner's page. */
'use strict';
window.FinanceBaseline = (() => {
  const value = (cents, currency='CNY') => Number.isSafeInteger(cents) ? new Intl.NumberFormat('zh-CN', {style:'currency',currency,maximumFractionDigits:2}).format(cents/100) : '待核对';
  const range = b => `${b.balanceAsOfStart || b.asOf} 至 ${b.balanceAsOfEnd || b.asOf}`;
  function strip(b) {
    return `<div class="wealth-strip"><div class="wealth-label">${esc(person(b.owner))} · 已导入资产基线</div><div class="wealth-values"><div><small>已记录资产</small><strong>${value(b.recordedAssetCents)}</strong></div><div><small>已记录负债</small><strong>${value(b.recordedLiabilityCents)}</strong></div></div><div class="wealth-caption"><span>净资产待完整核对 · ${esc(range(b))}</span>${!isTV?'<button type="button" data-wealth-summary>查看范围</button>':''}</div></div>`;
  }
  function decorateCard(html) {
    const baselines = data.wealth || [];
    if (!baselines.length) return html;
    return html.replace('card finance-card','card finance-card finance-has-baseline').replace('<div class="finance-status">', baselines.map(strip).join('')+'<div class="finance-status">');
  }
  function openSummary() {
    const baselines = data.wealth || [];
    openModal('共享资产基线', baselines.map(b=>`<section class="wealth-summary">${strip(b)}<p class="help">${esc(b.coverageNote || '不同日期的已记录小计，尚未覆盖全部资产和负债；不能据此计算完整净资产。')}</p><p class="help">来源截至 ${esc(b.asOf)}。账户、收入与消费明细仅所属成员可见。</p></section>`).join('') || '<p class="help">还没有导入资产基线。</p>');
  }
  const statuses = {dated_record:'已记录 · 历史余额',dated_record_receiving_balance_pending:'转入余额待核对',missing:'余额缺失',valuation_missing:'现值待补',repaid_not_reconciled:'已还款 · 待对账',statement_balance_pending:'账单余额待核对',contract:'合同约定',historical_source_record:'历史记录',user_provided_estimate:'个人估算'};
  function records(title, rows, income=false) {
    if (!Array.isArray(rows) || !rows.length) return '';
    return `<details class="wealth-records" ${income?'':'open'}><summary>${title}<span>${rows.length} 项</span></summary>${rows.map(r=>`<article class="wealth-record"><div><strong>${esc(r.label)}</strong><small>${esc(r.period || r.asOf || '日期待补')} · ${esc(statuses[r.status] || r.status || '待核对')}${!income && r.includedInRecordedSubtotal===false?' · 未计入共享小计':''}</small></div><b>${esc(value(r.amountCents,r.currency || 'CNY'))}</b>${r.note?`<p>${esc(r.note)}</p>`:''}</article>`).join('')}</details>`;
  }
  let privateGeneration=0;
  async function openPrivate() {
    if (isTV || isDemo || !canEdit()) return;
    const number=++privateGeneration, original={id:user?.id,household:user?.householdId||'default',version:user?.auth_version,csrf};
    openModal('我的资产与消费观察','<div id="finance-private-root"><p>正在核对本人登录状态…</p></div>',true);
    const node=document.getElementById('finance-private-root');
    const owns=()=>number===privateGeneration&&node.isConnected&&document.getElementById('dialog')?.open&&document.querySelector('#dialog .dialog-content')?.contains(node);
    const matches=(u,c)=>u?.role==='member'&&u.id===original.id&&(u.householdId||'default')===original.household&&u.auth_version===original.version&&c===original.csrf;
    const verify=async()=>{if(!owns())return false;if(isTV||isDemo||!matches(user,csrf))throw new Error('identity');const me=await api('/me');if(!owns())return false;if(!matches(user,csrf)||!matches(me.user,me.csrf))throw new Error('identity');return true;};
    let baseline;
    try { if(!await verify())return;baseline=await api('/finance-baseline/private');if(!await verify())return; }
    catch(_){if(owns())node.innerHTML='<p class="help">暂时无法核对当前成员。请刷新页面后重新打开，未显示缓存的私人记录。</p>';return;}
    const show=html=>{if(owns())node.innerHTML=html;};
    const sourceButton = !isDemo && !isTV ? '<div class="wealth-private-footer"><span>从已核对的来源包更新，先预览日期与变化。</span><button type="button" class="btn secondary" data-finance-source-open>更新财务来源</button></div>' : '';
    if (!baseline) {show('<p class="help">你的账户尚未导入个人财务基线。</p>'+sourceButton);return}
    const spending = baseline.spending || {}, months = spending.monthly || [];
    const monthly = months.length ? `<details class="wealth-records"><summary>历史消费观察<span>${months.length} 条月份／币种</span></summary><p class="help" data-spending-dates>报告生成：${esc(spending.generatedAt || '日期待核对')}<br>覆盖：${esc(spending.requestedStart || '待核对')} — ${esc(spending.requestedEnd || '待核对')}。首尾月份可能不完整，币种分别展示，不与账本相加。</p>${spending.quality ? `<p class="help">覆盖缺口 ${Number(spending.quality.knownGapsCount)||0}；不可读对账单 ${Number(spending.quality.unreadableStatementsCount)||0}；渠道补记 ${spending.quality.channelOnlyAdded?'有':'无'}；订单补记 ${spending.quality.orderOnlyAdded?'有':'无'}。</p>` : ''}${(baseline.spendingObservation?.warnings||[]).map(w=>`<p class="help">${esc(w)}</p>`).join('')}<p class="help">${esc(spending.note || '来自已识别记录，可能存在缺漏，不能替代完整对账。')}</p>${months.map(r=>`<article class="wealth-record"><div><strong>${esc(r.period)}</strong><small>已识别消费减退款 · ${esc(r.transactionCount)} 笔</small></div><b>${esc(value(r.netSpendCents,r.currency || 'CNY'))}</b></article>`).join('')}</details>` : '';
    show(`<div class="info-box">仅本人可见。共享看板只显示已记录资产、负债小计。来源版本 ${esc(baseline.asOf)}，余额记录日期 ${esc(range(baseline))}。最近接收时间 ${esc(baseline.importedAt || '待补')}。</div>${sourceButton}<p class="help">收入记录中的合同金额、历史收入和估算分别标注，不作为本月实际到账收入。公共荷包余额需单独核对。</p><div class="wealth-private">${records('资产账户',baseline.assets)}${records('负债账户',baseline.liabilities)}${records('收入基础',baseline.income,true)}${monthly}<div class="wealth-private-footer"><span>个人月度预算：${value(baseline.monthlyBudgetCents)}</span><button class="btn small secondary" data-action="personal">核对本月收入与预算</button></div></div>`);
  }
  document.addEventListener('click', event=>{
    if (event.target.closest('[data-wealth-summary]') && !isTV) openSummary();
  });
  return {decorateCard,openSummary,openPrivate};
})();
