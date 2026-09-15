/* Owner-only investment files. Selection, review and confirmation are separate steps. */
'use strict';
window.InvestmentImport = (() => {
  let current = null;
  const endpoint = '/finance-hub/investments/imports/';
  const permitted = () => !isDemo && !isTV && canEdit();
  const actor = () => ({id:user?.id,household:user?.householdId||'default',csrf});
  const matches = (owner,person,token) => person?.role==='member' && person.id===owner.id &&
    (person.householdId||'default')===owner.household && token===owner.csrf;
  const owns = flow => current===flow && flow.node.isConnected && document.querySelector('#dialog')?.open;
  const amount = (value,currency) => Number.isSafeInteger(value)
    ? `${currency} ${new Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}).format(value/100)}` : '待估值';
  const footer = () => '<button type="button" class="btn secondary" data-ii="back">返回投资账户</button>';
  const errorBox = () => '<p class="ii-message error" role="alert" tabindex="-1"></p>';
  const notice = (flow,text) => { const node=flow.node.querySelector('.ii-message'); if(node)node.textContent=text; };
  const resetView = flow => { for(const selector of ['.dialog-content','#dialog']){ const node=flow.node.closest(selector); if(node)node.scrollTop=0; } };
  function forget(flow) { ++flow.epoch; flow.payload=null; flow.preview=null; flow.sourceName=''; }
  function neutral(flow) {
    if (!owns(flow)) return;
    forget(flow);
    flow.node.innerHTML='<section class="ii-view"><h3>请重新核对登录状态</h3><p>本次文件和预览已关闭。刷新页面后，再打开本人的投资账户。</p><a class="btn secondary" href="/">刷新页面</a></section>';
  }
  async function verify(flow,active) {
    if (!active()) return false;
    if (!permitted() || !matches(flow.actor,user,csrf)) throw Object.assign(new Error('登录状态已变化'),{identityChanged:true});
    const me=await api('/me');
    if (!active()) return false;
    if (!permitted() || !matches(flow.actor,user,csrf) || !matches(flow.actor,me.user,me.csrf))
      throw Object.assign(new Error('登录成员或家庭已变化'),{identityChanged:true});
    return true;
  }
  async function operation(flow,button,work,{writing=false}={}) {
    if (!owns(flow) || button?.disabled) return;
    const epoch=++flow.epoch,view=flow.node.firstElementChild;
    const active=()=>owns(flow)&&flow.epoch===epoch&&view?.isConnected&&flow.node.contains(view);
    if(button){button._investmentJob=epoch;button.disabled=true;}
    notice(flow,'');
    let sent=false;
    try {
      if (!await verify(flow,active)) return;
      await work({active,verify:()=>verify(flow,active),sent:()=>{sent=true;}});
    } catch (error) {
      if (!active()) return;
      if(error.identityChanged||error.status===401||error.status===403){neutral(flow);return;}
      try { if(!await verify(flow,active))return; }
      catch (_) { if(active())neutral(flow);return; }
      if(!active())return;
      if(error.status===409)invalidatePreview(flow);
      const suffix=writing&&sent?' 请求可能已执行；保留同一预览重试，或返回投资账户核对。':'';
      notice(flow,(error.message||'暂时无法处理，请重试。')+(error.status===409?' 请重新预览并再次确认。':suffix));
    } finally {
      if(button?.isConnected&&button._investmentJob===epoch){button.disabled=false;}
      if(owns(flow))syncConfirm(flow);
    }
  }
  function syncConfirm(flow) {
    const button=flow.node.querySelector('[data-ii="confirm"]'),ack=flow.node.querySelector('[name="ack"]');
    if(button)button.disabled=!!flow.confirming||!flow.preview?.previewToken||!ack?.checked;
  }
  function invalidatePreview(flow) {
    flow.preview=null;
    const ack=flow.node.querySelector('[name="ack"]');
    if(ack){ack.checked=false;ack.disabled=true;}
    syncConfirm(flow);
  }
  function selection(flow) {
    flow.preview=null;
    const file=flow.payload?.file;
    flow.node.innerHTML=`<section class="ii-view"><div class="ii-intro"><span class="eyebrow">MY INVESTMENTS</span><h3>一次整理，多次更新</h3><p>把各账户的持仓整理成文件，先比较变化，再确认更新。仅本人可见。</p></div><ol class="ii-steps" aria-label="导入步骤"><li class="current">1 选择来源和文件</li><li>2 核对变化</li><li>3 确认保存</li></ol><form id="investment-import-form"><div class="form-grid"><label class="field"><span>来源名称</span><input name="sourceName" maxlength="80" required value="${esc(flow.sourceName)}" placeholder="例如：我的基金账户"></label><label class="field"><span>CSV 文件编码</span><select name="encoding"><option value="auto">自动识别 UTF-8 / GB18030</option><option value="utf-8">UTF-8</option><option value="gb18030">GB18030 / GBK</option></select></label><label class="field"><span>持仓整理表</span><input name="file" type="file" accept=".csv,.txt,.xlsx,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ${file?'':'required'}></label><label class="field"><span>XLSX 工作表名称（可选）</span><input name="sheet" maxlength="100" value="${esc(file?.sheet||'')}" placeholder="留空先选择工作表"></label></div><p class="help ii-selected">${file?`已选择 ${esc(file.name)}；不另选文件时继续使用本次文件。`:'文件最多 2 MB、300 项持仓；不会保存原始附件。'}</p><div class="info-box">后续更新请保持来源名称和持仓编号不变。缺少的行不会删除原持仓；已有项目的估值留空、日期倒退或疑似重复时，需要先核对。</div><details class="ii-format"><summary>如何准备整理表</summary><p>使用标准列 holdingKey、name、institution、assetType、currency、quantity、cost、value、asOf、note；recordId 用于明确关联已存在的本人记录。金额填持仓总成本和总估值，日期填 YYYY-MM-DD。</p><p>第一次可下载虚构示例；已有手工记录请填写来源名称后「导出现有持仓」，编辑文件再导入。不要把普通账单或交易流水直接当作持仓表。</p></details>${errorBox()}<div class="ii-template-actions"><button type="button" class="btn small secondary" data-ii="sample">下载虚构示例</button><button type="button" class="btn small secondary" data-ii="export">导出现有持仓</button></div><div class="dialog-footer">${footer()}<button type="submit" class="btn">读取并预览</button></div></form></section>`;
    resetView(flow);
    const form=flow.node.querySelector('form');
    form.elements.encoding.value=file?.encoding||'auto';
    form.addEventListener('input',()=>{
      ++flow.epoch; flow.preview=null; flow.sourceName=form.elements.sourceName.value;
      form.querySelector('[type="submit"]').disabled=false;
    });
    form.elements.file.addEventListener('change',()=>{
      ++flow.epoch; flow.payload=null; form.elements.file.required=true;
      flow.node.querySelector('.ii-selected').textContent='新文件尚未读取。点击预览后再核对变化。';
    });
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const chosen=form.elements.file.files[0],sourceName=form.elements.sourceName.value.trim();
      const encoding=form.elements.encoding.value,sheet=form.elements.sheet.value.trim(),existing=flow.payload?.file;
      void operation(flow,form.querySelector('[type="submit"]'),async job=>{
        if(!sourceName)throw new Error('请填写来源名称，后续更新沿用同一名称。');
        let file=existing;
        if(chosen){
          if(!chosen.size||chosen.size>2_000_000)throw new Error('请选择非空且不超过 2 MB 的持仓整理表。');
          const bytes=new Uint8Array(await chosen.arrayBuffer());
          if(!job.active())return;
          let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
          file={name:chosen.name,contentBase64:btoa(binary)};
        }
        if(!file)throw new Error('请先选择持仓整理表。');
        flow.sourceName=sourceName;
        flow.payload={sourceName,file:{...file,encoding,sheet}};
        await preview(flow,job);
      });
    });
  }
  async function preview(flow,job) {
    const payload=structuredClone(flow.payload);
    const response=await api(endpoint+'preview',{method:'POST',body:JSON.stringify(payload),headers:{'X-CSRF-Token':flow.actor.csrf}});
    if(!job.active()||!await job.verify())return;
    if(response.requiresSheetSelection){sheets(flow,response);return;}
    flow.preview=response;
    review(flow,response);
  }
  function sheets(flow,response) {
    flow.preview=null;
    const names=response.fileInfo?.sheets||response.sheets||[];
    flow.node.innerHTML=`<section class="ii-view"><h3>选择持仓工作表</h3><p>${esc(flow.payload.file.name)} · ${esc(flow.sourceName)}</p><p class="help">目前只读取了工作表名称，尚未生成持仓预览或保存投资记录。</p><form id="investment-sheet-form"><label class="field"><span>要读取的工作表</span><select name="sheet" required><option value="">请选择工作表</option>${names.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('')}</select></label>${errorBox()}<div class="dialog-footer"><button type="button" class="btn secondary" data-ii="choose">重新选文件</button><button type="submit" class="btn">预览这张表</button></div></form></section>`;
    resetView(flow);
    const form=flow.node.querySelector('form');
    form.elements.sheet.addEventListener('change',()=>{++flow.epoch;flow.preview=null;form.querySelector('[type="submit"]').disabled=false;});
    form.addEventListener('submit',event=>{
      event.preventDefault();const sheet=form.elements.sheet.value;
      void operation(flow,form.querySelector('[type="submit"]'),async job=>{
        if(!sheet)throw new Error('请先选择工作表。');
        flow.payload={...flow.payload,file:{...flow.payload.file,sheet}};
        await preview(flow,job);
      });
    });
  }
  function holding(value,label) {
    if(!value)return `<div class="ii-holding"><small>${esc(label)}</small><span>—</span></div>`;
    return `<div class="ii-holding"><small>${esc(label)}</small><strong>${esc(value.name||'')}</strong><span>${esc(value.institution||'')} · ${esc(value.assetType||'')} · ${esc(value.currency||'')}</span><span>成本 ${esc(amount(value.costCents,value.currency))}</span><span>估值 ${esc(amount(value.valueCents,value.currency))}</span><span>核对日期 ${esc(value.asOf||'待补')}</span><span>数量 ${value.quantity!==null&&value.quantity!==undefined?esc(value.quantity):'未记录'}</span>${value.note?`<small>${esc(value.note)}</small>`:''}</div>`;
  }
  function review(flow,p) {
    const counts=p.counts||{},labels={create:'新增',update:'更新',unchanged:'保持原样'};
    flow.node.innerHTML=`<section class="ii-view"><div class="ii-intro"><span class="eyebrow">REVIEW BEFORE SAVING</span><h3>核对这次持仓变化</h3><p>${esc(flow.sourceName)} · ${esc(flow.payload.file.name)}${flow.payload.file.sheet?' · '+esc(flow.payload.file.sheet):''}</p></div><div class="ii-counts">${[['create','新增'],['update','更新'],['unchanged','不变']].map(([key,label])=>`<div><small>${label}</small><strong>${Number(counts[key])||0}</strong></div>`).join('')}</div><p class="help">尚未修改持仓。核对来源、编号、成本、估值和日期后，再确认保存。</p>${(p.warnings||[]).map(text=>`<p class="ii-warning">${esc(text)}</p>`).join('')}${(p.errors||[]).map(item=>`<p class="error">${item.line?'第 '+esc(item.line)+' 行：':''}${esc(item.message)}</p>`).join('')}<div class="ii-review-list">${(p.rows||[]).map(row=>`<article class="ii-row"><header><strong>${esc(row.holdingKey||'')}</strong><span class="ii-badge ${esc(row.action||'')}">${esc(labels[row.action]||'需核对')}</span></header><div class="ii-comparison">${holding(row.before,'当前记录')}${holding(row.after,'本次文件')}</div>${(row.warnings||[]).map(text=>`<p class="ii-warning">${esc(text)}</p>`).join('')}</article>`).join('')||'<p class="help">当前没有需要展开的持仓差异，请查看上方核对结果。</p>'}</div><label class="label-check"><input type="checkbox" name="ack" ${p.errorCount||!p.previewToken?'disabled':''}>我已核对本人的持仓、金额和更新日期</label>${errorBox()}<div class="dialog-footer"><button type="button" class="btn secondary" data-ii="choose">返回文件</button><button type="button" class="btn secondary" data-ii="preview">重新预览</button><button type="button" class="btn" data-ii="confirm" disabled>确认更新 · 仅本人</button></div></section>`;
    resetView(flow);
    flow.node.querySelector('[name="ack"]').addEventListener('change',()=>syncConfirm(flow));
  }
  function confirmed(flow,result) {
    flow.payload=null;flow.preview=null;
    flow.node.innerHTML=`<section class="ii-view ii-success"><span class="ii-success-mark">✓</span><h3>${result.replayed?'这次导入已经保存':'持仓已更新'}</h3><p>新增 ${Number(result.created)||0} 项，更新 ${Number(result.updated)||0} 项，保持原样 ${Number(result.unchanged)||0} 项。</p><p class="help">结果已保存在本人的投资账户中。没有改变公共荷包或共享资产基线。</p>${errorBox()}<div class="dialog-footer"><button class="btn secondary" type="button" data-ii="choose">导入另一份文件</button>${footer()}</div></section>`;
    resetView(flow);
  }
  async function template(flow,button,existing) {
    const form=flow.node.querySelector('#investment-import-form'),sourceName=form?.elements.sourceName.value.trim()||'';
    await operation(flow,button,async job=>{
      if(existing&&!sourceName)throw new Error('请先填写来源名称，再导出现有持仓。');
      const query=existing?'?mode=current&sourceName='+encodeURIComponent(sourceName):'';
      const result=await api(endpoint+'template'+query);
      if(!job.active()||!await job.verify())return;
      const url=URL.createObjectURL(new Blob(['\ufeff'+result.csv.replace(/^\ufeff/,'')],{type:'text/csv;charset=utf-8'}));
      const link=document.createElement('a');link.href=url;link.download=result.filename;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      notice(flow,(result.warnings||[]).join(' ')||(existing?'已导出现有持仓；编辑后用同一来源名称导入。':'已下载虚构示例，请替换示例内容后再导入。'));
    });
  }
  async function open() {
    if(!permitted())return;
    openModal('导入投资持仓','<div class="investment-import"><section class="ii-view"><p>正在核对当前账户…</p>'+errorBox()+'<button class="btn secondary" data-ii="start">重试</button></section></div>',true);
    const flow={actor:actor(),node:document.querySelector('.investment-import'),epoch:0,payload:null,preview:null,sourceName:'',confirming:false};
    current=flow;
    await operation(flow,null,async()=>selection(flow));
  }
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-investment-import-open]')){void open();return;}
    const button=event.target.closest('[data-ii]'),flow=current;
    if(!button||!flow||!owns(flow)||!flow.node.contains(button)||button.disabled)return;
    const action=button.dataset.ii;
    if(action==='start'){void open();return;}
    if(action==='sample'||action==='export'){void template(flow,button,action==='export');return;}
    if(action==='back'){forget(flow);current=null;void FinanceHub.open('investments');return;}
    if(action==='choose'){void operation(flow,button,async()=>selection(flow));return;}
    if(action==='preview'){
      invalidatePreview(flow);
      void operation(flow,button,job=>preview(flow,job));return;
    }
    if(action==='confirm'&&flow.preview?.previewToken&&flow.node.querySelector('[name="ack"]')?.checked){
      const token=flow.preview.previewToken;
      flow.confirming=true;
      void operation(flow,button,async job=>{
        job.sent();
        const result=await api(endpoint+'confirm',{method:'POST',body:JSON.stringify({previewToken:token}),headers:{'X-CSRF-Token':flow.actor.csrf}});
        if(!job.active()||!await job.verify())return;
        confirmed(flow,result);
      },{writing:true}).finally(()=>{flow.confirming=false;if(owns(flow))syncConfirm(flow);});
    }
  });
  document.querySelector('#dialog')?.addEventListener('close',()=>{if(current)forget(current);current=null;});
  new MutationObserver(()=>{if(current&&!owns(current)){forget(current);current=null;}})
    .observe(document.querySelector('#dialog'),{childList:true});
  return {open};
})();
