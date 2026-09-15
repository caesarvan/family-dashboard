/* Explicit owner-only source preview. No background financial upload. */
'use strict';
window.FinanceSourceUI=(()=>{
 const MODE='spending_observation';let current=null;
 const allowed=()=>!isDemo&&!isTV&&canEdit();
 const actor=()=>({id:user?.id,household:user?.householdId||'default',version:user?.auth_version,csrf});
 const matches=(a,u,c)=>u?.role==='member'&&a.id===u.id&&a.household===(u.householdId||'default')&&a.version===u.auth_version&&a.csrf===c;
 const owns=f=>current===f&&f.node.isConnected&&document.getElementById('dialog')?.open&&document.querySelector('#dialog .dialog-content')?.contains(f.node);
 const dates=v=>[v?.balanceAsOfStart||'待补',v?.balanceAsOfEnd||'待补'].join(' — ');
 const amount=(n,c='CNY')=>Number.isSafeInteger(n)?new Intl.NumberFormat('zh-CN',{style:'currency',currency:c}).format(n/100):'待核对';
 const errors='<div id="finance-source-error" class="error" role="alert" tabindex="-1"></div>';
 const render=(f,html)=>{if(owns(f)){++f.epoch;f.node.innerHTML='<section class="fs-view">'+html+'</section>';}};
 const error=(f,t)=>{const e=f.node.querySelector('#finance-source-error');if(e){e.textContent=t;e.focus();}};
 function neutral(f,uncertain=false){if(!owns(f))return;f.candidate=null;f.preview=null;render(f,'<h3>'+(uncertain?'暂时无法核对登录状态':'登录或家庭已变化')+'</h3><p>请刷新页面后重新打开来源更新。</p><a class="btn" href="/">刷新页面</a>');}
 async function verify(f,active){
  if(!active())return false;
  if(!allowed()||!matches(f.actor,user,csrf))throw {identityChanged:true};
  let me;try{me=await api('/me');}catch(_){throw {identityUnknown:true};}
  if(!active())return false;
  if(!allowed()||!matches(f.actor,user,csrf)||!matches(f.actor,me.user,me.csrf))throw {identityChanged:true};
  return true;
 }
 async function job(f,button,work){
  if(!owns(f)||f.busy)return;
  f.busy=true;const epoch=++f.epoch,view=f.node.firstElementChild;
  const active=()=>owns(f)&&f.epoch===epoch&&view?.isConnected&&f.node.contains(view);
  const controls=[...f.node.querySelectorAll('input,select,textarea')].map(el=>[el,el.disabled]);
  controls.forEach(([el])=>{el.disabled=true;});
  if(button)button.disabled=true;
  try{if(await verify(f,active))await work({active,verify:()=>verify(f,active)});}
  catch(e){
   if(!active())return;
   if(e.identityChanged||e.identityUnknown){neutral(f,!!e.identityUnknown);return;}
   try{if(!await verify(f,active))return;}catch(check){if(active())neutral(f,!!check.identityUnknown);return;}
   if(e.status===409){f.preview=null;const ack=f.node.querySelector('#finance-source-ack');if(ack){ack.checked=false;ack.disabled=true;}f.node.querySelector('[data-fs=confirm]')?.setAttribute('disabled','');}
   error(f,e.status===409?'来源、覆盖或版本需要重新核对。文件仍保留，请重新预览。':e.status>=500?'来源服务暂时不可用。文件和预览仍保留，请稍后重试。':e.message||'来源更新失败，请核对文件后重试。');
  }finally{f.busy=false;if(owns(f)&&allowed()&&matches(f.actor,user,csrf)){controls.forEach(([el,disabled])=>{if(el.isConnected&&f.node.contains(el))el.disabled=el.id==='finance-source-ack'&&!f.preview?true:disabled;});if(button?.isConnected)button.disabled=button.dataset.fs==='confirm'&&!f.preview;}}
 }
 const statusUrl=f=>'/finance-baseline/imports/status'+(f.mode===MODE?'?mode='+MODE:'');
 async function open(options={}){
  if(!allowed())return;
  openModal('更新我的财务来源','<div class="finance-source-workspace" id="finance-source-root"><section><p>正在核对当前成员与来源版本…</p>'+errors+'</section></div>',true);
  const f={node:document.getElementById('finance-source-root'),actor:actor(),epoch:0,busy:false,mode:options.mode===MODE?MODE:'baseline',candidate:null,preview:null,filename:'',status:null};current=f;
  await job(f,null,async j=>{const status=await api(statusUrl(f));if(!await j.verify())return;f.status=status;choose(f);});
 }
 function choose(f){
  const observation=f.mode===MODE,st=f.status,b=observation?st?.baseline:st?.current;
  render(f,'<h3>先核对变化，再明确更新</h3><p class="help">消费观察可独立更新；完整财产基线仍需逐项来源映射。</p><form id="finance-source-form"><label class="field"><span>更新范围</span><select name="sourceMode"><option value="baseline" '+(!observation?'selected':'')+'>完整财产基线</option><option value="'+MODE+'" '+(observation?'selected':'')+'>仅更新消费观察</option></select></label><div class="info-box">资产余额核对日期：'+esc(dates(b))+(observation?'<br>消费报告生成时间：'+esc(st?.spending?.generatedAt||'尚无可比较日期')+'<br>报告覆盖：'+esc(st?.spending?.requestedStart||'待核对')+' — '+esc(st?.spending?.requestedEnd||'待核对'):'')+'</div><label class="field"><span>来源更新包（JSON，小于 1.95 MB）</span><input type="file" name="candidateFile" accept="application/json,.json" '+(f.candidate?'':'required')+'></label><p class="help" id="finance-source-selected">'+(f.filename?'已选择：'+esc(f.filename):'选择本机工具生成的更新包；选择文件不会上传。')+'</p>'+(observation?'<p class="help">选择由个人财务报告生成的消费观察更新包；预览并确认后才保存。</p>':'')+(observation&&st?.requiresUnknownCoverageAcknowledgement?'<label class="label-check"><input type="checkbox" name="unknownCoverage">旧消费覆盖无法比较：我确认保留旧快照，不推断旧日期，仅核对新报告明确的覆盖。</label>':'')+errors+'<div class="dialog-footer"><button type="button" class="btn secondary" data-fs="private">返回我的资产</button><button type="submit" class="btn">预览来源更新</button></div></form>');
  const form=f.node.querySelector('form');
  form.addEventListener('input',()=>{++f.epoch;f.preview=null;});
  form.elements.candidateFile.onchange=()=>{++f.epoch;f.candidate=null;f.preview=null;f.filename='';form.elements.candidateFile.required=true;f.node.querySelector('#finance-source-selected').textContent='文件只会在点击预览后读取。';};
  form.elements.sourceMode.onchange=async()=>{const mode=form.elements.sourceMode.value;++f.epoch;f.mode=mode;f.candidate=null;f.preview=null;f.filename='';await job(f,null,async j=>{const status=await api(statusUrl(f));if(!await j.verify())return;f.status=status;choose(f);});};
  form.onsubmit=async e=>{e.preventDefault();await job(f,form.querySelector('[type=submit]'),async j=>{
   const file=form.elements.candidateFile.files[0],ack=form.elements.unknownCoverage?.checked===true;
   if(file){if(!file.size||file.size>=1950000)throw new Error('请选择非空且小于 1.95 MB 的来源包');const raw=await file.text();if(!await j.verify())return;let candidate;
    try{candidate=JSON.parse(raw.replace(/^\uFEFF/,''));}catch(_){throw new Error('无法读取 JSON，请重新生成来源包');}
    if(!candidate||typeof candidate!=='object'||Array.isArray(candidate))throw new Error('来源包格式不正确');
    if((candidate.kind===MODE)!==(f.mode===MODE))throw new Error('文件与更新范围不一致，请选择正确范围后重新预览');
    f.candidate=candidate;f.filename=file.name;
   }
   if(!f.candidate)throw new Error('请先选择来源更新包');f.unknownAck=ack;await preview(f,j);
  });};
 }
 async function preview(f,j){
  const status=await api(statusUrl(f));if(!await j.verify())return;f.status=status;
  const payload=f.mode===MODE?{mode:MODE,candidate:f.candidate,...status.expected,acknowledgeUnknownPreviousCoverage:f.unknownAck===true}:{candidate:f.candidate,expectedRevision:status.current?.revision||0,expectedSourceDigest:status.current?.sourceDigest||null};
  const result=await write('/finance-baseline/imports/preview','POST',payload);if(!await j.verify())return;f.preview=result;showPreview(f);
 }
 function showPreview(f){
  const p=f.preview,c=p.changes||{},observation=f.mode===MODE,s=p.spending||{};
  const details=observation?(s.monthly||[]).map(r=>'<article class="wealth-record"><div><strong>'+esc(r.period)+' · '+esc(r.currency)+'</strong><small>'+r.transactionCount+' 条来源观察</small></div><b>'+esc(amount(r.netSpendCents,r.currency))+'</b></article>').join(''):[['assets','资产'],['liabilities','负债'],['income','收入']].map(([kind,label])=>'<h4>'+label+'</h4>'+(p.private?.[kind]||[]).map(r=>'<article class="wealth-record"><div><strong>'+esc(r.label)+'</strong><small>'+esc(r.asOf)+' · '+esc(r.status)+'</small></div><b>'+esc(amount(r.amountCents,r.currency))+'</b></article>').join('')).join('');
  render(f,'<h3>'+(observation?'核对本次消费观察':'核对本次财产基线')+'</h3><p class="help">当前仅为预览，尚未保存。</p><div class="finance-source-dates"><div><small>'+(observation?'消费报告生成时间':'财产来源版本')+'</small><strong>'+esc(observation?s.generatedAt:p.asOf)+'</strong></div><div><small>资产余额核对日期'+(observation?'（保持不变）':'')+'</small><strong>'+esc(dates(p.baseline||p.private||p))+'</strong></div></div>'+(observation?'<div class="info-box">消费观察覆盖 '+esc(s.requestedStart)+' — '+esc(s.requestedEnd)+'。完整保留原资产、负债、收入与共享汇总。</div>':'<section class="finance-source-shared"><h4>确认后家庭可见的小计</h4><div class="wealth-values"><div><small>已记录资产</small><strong>'+esc(amount(p.shared?.recordedAssetCents))+'</strong></div><div><small>已记录负债</small><strong>'+esc(amount(p.shared?.recordedLiabilityCents))+'</strong></div></div></section>')+'<div class="finance-source-counts"><span>新增 <b>'+(c.added||0)+'</b></span><span>更新 <b>'+(c.updated||0)+'</b></span><span>保留 <b>'+(c.preserved||0)+'</b></span></div>'+(observation?'<p class="help" data-spending-removed>移出观察窗口：'+((c.removedMonths||[]).map(r=>esc(r.period+' '+r.currency)).join('、')||'无')+'。原基线快照仍保留。</p>':'')+'<ul class="finance-source-warnings">'+(p.warnings||[]).map(w=>'<li>'+esc(w)+'</li>').join('')+'</ul><details class="wealth-records"><summary>查看本人'+(observation?'月度观察':'记录')+'</summary>'+details+'</details><label class="label-check"><input id="finance-source-ack" type="checkbox">'+(observation?'我已核对日期、覆盖和移出窗口月份，仅更新消费观察':'我已核对来源日期、变化和共享小计')+'</label>'+errors+'<div class="dialog-footer"><button type="button" class="btn secondary" data-fs="choose">返回选择</button><button type="button" class="btn secondary" data-fs="preview">重新预览</button><button type="button" class="btn" data-fs="confirm" disabled>'+(observation?'确认更新消费观察':'确认更新基线')+'</button></div>');
  f.node.querySelector('#finance-source-ack').onchange=e=>{f.node.querySelector('[data-fs=confirm]').disabled=!e.target.checked||f.busy;};
 }
 async function confirm(f,j){
  if(!f.preview||!f.node.querySelector('#finance-source-ack')?.checked)throw new Error('请先核对并确认预览');
  const payload={candidate:f.candidate,previewToken:f.preview.previewToken};if(f.mode===MODE)payload.mode=MODE;
  const result=await write('/finance-baseline/imports/confirm','POST',payload);if(!await j.verify())return;
  const observation=f.mode===MODE;f.candidate=null;f.preview=null;f.filename='';
  render(f,'<div class="info-box" id="finance-source-success">'+(result.status==='unchanged'||result.replayed?'这份来源已经接受，没有重复更新。':observation?'消费观察已更新。':'财务基线已更新。')+'</div><p class="help">已保存版本 '+result.revision+'。'+(observation?'原财产基线和共享汇总保持原样；实付账本没有变化。':'共享看板仅更新批准的小计。')+'</p>'+errors+'<div class="dialog-footer"><button class="btn secondary" data-fs="open">选择另一份来源</button><button class="btn" data-fs="private">查看我的资产与消费观察</button></div>');
 }
 document.addEventListener('click',async e=>{
  if(e.target.closest('[data-finance-source-open]')){await open();return;}
  const button=e.target.closest('[data-fs]'),f=current;if(!button||!f||!owns(f)||!f.node.contains(button))return;
  const action=button.dataset.fs;
  if(action==='choose'&&!f.busy){f.preview=null;choose(f);return;}
  await job(f,button,async j=>{
   if(action==='preview')await preview(f,j);
   else if(action==='confirm')await confirm(f,j);
   else if(action==='open'){if(await j.verify())await open({mode:f.mode});}
   else if(action==='private'){if(await j.verify()){current=null;++f.epoch;await FinanceBaseline.openPrivate();}}
  });
 });
 document.getElementById('dialog')?.addEventListener('close',()=>{if(!document.getElementById('dialog').open){if(current)++current.epoch;current=null;}});
 return {open};
})();
