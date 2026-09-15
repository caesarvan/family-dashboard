/* Member-owned travel documents. Files are never fetched until an explicit download. */
window.JourneyDocuments = (() => {
  'use strict';
  let current=null, generation=0;
  const urls=new Set(), maxFile=5000000;
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const allowed=()=>!isDemo&&!isTV&&canEdit();
  const actor=()=>({id:user?.id,household:user?.householdId||'default',version:user?.auth_version,csrf});
  const matches=(a,u,c)=>u?.role==='member'&&a.id===u.id&&a.household===(u.householdId||'default')&&a.version===u.auth_version&&a.csrf===c;
  const owns=f=>current===f&&f.generation===generation&&f.route===location.href&&f.node.isConnected&&document.getElementById('dialog')?.open&&document.querySelector('#dialog .dialog-content')?.contains(f.node);
  const identityError=()=>Object.assign(new Error('identity'),{identityChanged:true});
  const button=(action,label,attrs='')=>`<button type="button" class="btn small secondary" data-jd="${action}" ${attrs}>${label}</button>`;
  const field=(label,name,value,attrs='')=>`<label class="field"><span>${label}</span><input name="${name}" value="${escape(value)}" ${attrs}></label>`;
  const bytes=n=>n>=1000000?(n/1000000).toFixed(1)+' MB':Math.ceil(n/1000)+' KB';
  const when=value=>{const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleDateString('zh-CN'):'日期待核对';};
  function clearUrls(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();}
  function neutral(f){if(!owns(f))return;f.node.innerHTML='<p role="alert">登录成员或家庭已变化，资料已收起。请刷新后重新进入。</p>';f.model=null;f.epoch++;}
  function message(f,text){if(owns(f)){let box=f.node.querySelector('[data-jd-message]');if(!box){f.node.insertAdjacentHTML('beforeend','<p class="jd-message" data-jd-message role="status"></p>');box=f.node.querySelector('[data-jd-message]');}box.textContent=text;}}
  const description=status=>status===409?'资料已有变化，或本次提交无法继续。草稿仍保留，请读取最新版本并核对后再保存。':status===413?'文件过大，请选择不超过 5 MB 的文件。':status===403?'你不能管理这份资料。':status===404?'这份资料或旅行已不存在，或当前成员不可见。':'暂时无法完成，请稍后重试。尚未确认成功的上传会沿用原请求核对，避免重复创建。';
  async function job(f,form,work,onFailure=null){
    if(!owns(f))return;
    const epoch=++f.epoch,version=form?._jdVersion||0;let bound=true;
    const active=()=>owns(f)&&epoch===f.epoch&&(!form||!bound||(form.isConnected&&f.node.contains(form)&&(form._jdVersion||0)===version));
    const local=()=>{if(!active())return false;if(!allowed()||!matches(f.actor,user,csrf))throw identityError();return true;};
    const check=async()=>{if(!local())return false;const me=await api('/me');if(!local())return false;if(!matches(f.actor,me.user,me.csrf))throw identityError();return true;};
    try{if(await check())await work({active,check,local,detach:()=>{bound=false;}});}
    catch(error){
      if(!active())return;
      if(error.identityChanged||error.status===401){neutral(f);return;}
      try{if(!await check())return;}catch(identity){if(!active())return;if(identity.identityChanged||identity.status===401){neutral(f);return;}if(f.confirmed){receipt(f,true);return;}message(f,'暂时无法核对登录状态；请稍后重新读取，尚未打开或下载资料。');return;}
      if(!active())return;
      if(f.confirmed){receipt(f,true);return;}
      if(onFailure)onFailure(error);else message(f,description(error.status));
    }
  }
  function contextPath(journeyId){return '/journey-documents'+(journeyId?'?journeyId='+encodeURIComponent(journeyId):'');}
  function valid(model){return model&&Array.isArray(model.documents)&&Array.isArray(model.journeys)&&Array.isArray(model.segments);}
  function card(doc){
    return `<article class="jd-card" data-document-id="${escape(doc.id)}"><div class="jd-card-type">${doc.mimeType==='application/pdf'?'PDF':'图片'}<span>${doc.visibility==='shared'?'家庭共享':'仅本人'}</span></div><h3>${escape(doc.title)}</h3><p>${escape(doc.filename)} · ${bytes(doc.bytes)}</p><p class="jd-card-meta">${escape(doc.owner===user.id?'我上传的':person(doc.owner)+'上传的')} · ${escape(when(doc.updatedAt))}${doc.unlinked?' · 未关联旅行':''}${doc.segmentMissing?' · 原细项已移除':''}</p><div class="jd-actions">${button('download','下载资料',`data-id="${escape(doc.id)}"`)}${doc.canManage?button('edit','管理',`data-id="${escape(doc.id)}"`):'<span class="jd-readonly">由上传者管理</span>'}</div></article>`;
  }
  function render(f){
    if(!owns(f))return;
    const model=f.model, segment=model.segments.find(s=>s.key===f.segmentKey);
    const selected=f.segmentKey?model.documents.filter(d=>d.segmentKey===f.segmentKey):model.documents;
    f.node.innerHTML=`<header class="jd-heading"><div><span class="jd-eyebrow">TRAVEL DOCUMENTS</span><h3>${escape(model.journey?.title||'我的旅行资料')}</h3><p>${model.journey?'只显示你上传或家人明确共享到这趟旅行的资料。':'你的全部资料，包括尚未关联或原旅行已移除的文件。'}</p></div>${button('refresh','刷新')}</header><div class="jd-toolbar"><div>${model.journey?button('back','返回旅行'):button('back','返回旅行列表')}${f.segmentKey?button('all','查看整趟旅行资料'):''}</div>${button('upload','＋ 添加资料')}</div>${f.segmentKey?`<p class="jd-filter">当前细项：${escape(segment?.title||'原细项已移除')} · ${selected.length} 份资料</p>`:''}<div class="jd-grid">${selected.map(card).join('')||'<div class="jd-empty"><span>▤</span><h3>把出行时要用的资料放在这里</h3><p>可保存 PDF 或图片。默认仅自己可见，需要家人使用时再明确共享。</p></div>'}</div><p class="jd-footnote">文件保存在家庭服务器，不会自动访问预订平台。PDF 只下载、不在页面内嵌；电视不能读取旅行资料。</p><p class="jd-message" data-jd-message role="status"></p>`;
  }
  async function refresh(f){
    if(!owns(f)||f.busy)return;
    f.node.innerHTML='<p class="jd-loading" role="status">正在核对身份并读取资料…</p>';
    await job(f,null,async j=>{const model=await api(contextPath(f.journeyId));if(!await j.check())return;if(!valid(model))throw new Error('invalid_response');f.model=model;f.confirmed=false;render(f);},()=>{f.node.innerHTML=`<div class="jd-empty"><h3>暂时无法读取资料</h3><p>未展示缓存的私人内容。</p>${button('refresh','重新读取')}</div><p data-jd-message role="status"></p>`;});
  }
  function options(model,selected){return '<option value="">暂不关联旅行 · 仅本人</option>'+model.journeys.map(j=>`<option value="${escape(j.id)}" ${selected===j.id?'selected':''}>${escape(j.title)}</option>`).join('');}
  function segmentOptions(segments,selected){return '<option value="">整趟旅行</option>'+segments.map(s=>`<option value="${escape(s.key)}" ${selected===s.key?'selected':''}>${escape(s.title)}</option>`).join('')+(selected&&!segments.some(s=>s.key===selected)?`<option value="${escape(selected)}" selected>原细项已移除 · 请重新选择</option>`:'');}
  function editor(f,doc=null,model=f.model){
    if(!owns(f))return;
    const journeyId=doc?.journeyId||f.journeyId||'',segmentKey=doc?.segmentKey||f.segmentKey||'';
    f.node.innerHTML=`<header class="jd-heading"><div><span class="jd-eyebrow">${doc?'SAVED DOCUMENT':'ADD A DOCUMENT'}</span><h3>${doc?'管理旅行资料':'添加旅行资料'}</h3><p>${doc?escape(doc.filename)+' · 文件内容保持不变':'选择一份出行所需的 PDF 或图片，填写一个方便查找的名称。'}</p></div>${button('cancel','返回资料夹')}</header><form id="journey-document-form">${field('资料名称','title',doc?.title||'','required maxlength="120"')}${!doc?'<label class="jd-file field"><span>选择本机文件 · 最大 5 MB</span><input type="file" name="file" required accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"><small data-jd-file-info>PDF 保留 PDF；图片须不超过 400 万像素，JPG / PNG / WebP 经服务器缩小净化后保存为 JPEG。</small></label>':''}<div class="jd-fields"><label class="field"><span>关联旅行</span><select name="journeyId">${options(model,journeyId)}</select></label><label class="field"><span>对应细项</span><select name="segmentKey" ${journeyId?'':'disabled'}>${segmentOptions(model.segments,segmentKey)}</select></label></div><label class="jd-sharing"><input type="checkbox" name="shared" ${doc?.visibility==='shared'?'checked':''} ${journeyId?'':'disabled'}><span><strong>明确共享给本家庭成员</strong><small>未勾选时仅本人可见；家人可以下载共享资料，只有上传者可以修改或删除。</small></span></label>${doc?.unlinked?'<p class="jd-warning">原旅行已移除或资料已解除关联。当前仅本人可见，可重新关联到现有旅行。</p>':''}<p class="jd-warning" data-jd-conflict hidden></p><div class="jd-actions"><button type="submit" class="btn">${doc?'保存资料设置':'上传并保存'}</button>${doc?button('delete','删除资料',`data-id="${escape(doc.id)}"`):''}</div><p class="jd-message" data-jd-message role="status"></p></form>`;
    const form=f.node.querySelector('form');form._document=doc;form._jdVersion=0;form._segments=model.segments;
    if(!doc){form.elements.journeyId.required=true;form.elements.journeyId.options[0].textContent='请选择一趟旅行';}
    form.onsubmit=event=>{event.preventDefault();void save(f,form);};
    form.addEventListener('input',()=>{form._jdVersion++;});
    form.addEventListener('change',event=>{
      form._jdVersion++;
      if(event.target.name==='file'){const file=event.target.files[0];form.querySelector('[data-jd-file-info]').textContent=file?`${file.name} · ${bytes(file.size)} · ${file.type==='application/pdf'?'提交 PDF，保留原格式':'提交原图片，服务器净化为 JPEG 后保存'}`:'请选择文件';}
      if(event.target.name==='journeyId'){form.elements.shared.checked=false;form.elements.shared.disabled=!event.target.value;form.elements.segmentKey.value='';void changeJourney(f,form);}
    });
  }
  async function changeJourney(f,form){
    form.elements.segmentKey.disabled=true;form._loadingSegments=true;
    const ticket={};form._segmentTicket=ticket;
    const selected=form.elements.journeyId.value;
    await job(f,form,async j=>{const model=await api(contextPath(selected));if(!await j.check())return;if(!valid(model))throw new Error('invalid_response');form._segments=model.segments;form.elements.segmentKey.innerHTML=segmentOptions(model.segments,'');form.elements.segmentKey.disabled=!selected;form._loadingSegments=false;message(f,'');},()=>{form._loadingSegments=false;message(f,'未能读取所选旅行的细项，请重新选择旅行后再保存。');form._segments=null;});
    if(owns(f)&&form.isConnected&&form._segmentTicket===ticket&&form._loadingSegments&&allowed()&&matches(f.actor,user,csrf)){form._loadingSegments=false;form._segments=null;message(f,'填写内容有变化，请重新选择关联旅行以读取细项；其他草稿保持不变。');}
  }
  function values(form){const journeyId=form.elements.journeyId.value||null;return {title:form.elements.title.value.trim(),journeyId,segmentKey:journeyId?form.elements.segmentKey.value:'',visibility:journeyId&&form.elements.shared.checked?'shared':'private'};}
  async function filePayload(file){
    if(!file||file.size>maxFile)throw Object.assign(new Error('file'),{status:413});
    const ext=file.name.split('.').pop().toLowerCase(),types={pdf:'application/pdf',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',webp:'image/webp'};
    if(!types[ext]||file.type&&file.type!==types[ext])throw Object.assign(new Error('file'),{status:400});
    const buffer=new Uint8Array(await file.arrayBuffer());let raw='';for(let i=0;i<buffer.length;i+=32768)raw+=String.fromCharCode(...buffer.subarray(i,i+32768));
    return {name:file.name,mimeType:types[ext],dataBase64:btoa(raw)};
  }
  function lock(form,value){for(const item of form.querySelectorAll('input,select,button')){if(value)item.dataset.jdDisabled=String(item.disabled);item.disabled=value||item.dataset.jdDisabled==='true';}}
  function receipt(f,failed=false){if(!owns(f))return;f.node.innerHTML=`<div class="jd-receipt"><span>✓</span><h3>已收到保存结果</h3><p>${failed?'最新资料列表暂未读回。请只重新读取，无需再次提交。':'正在读取最新资料列表…'}</p>${button('refresh','读取最新资料')}</div><p data-jd-message role="status"></p>`;}
  async function readAfterWrite(f,j){
    receipt(f);const model=await api(contextPath(f.journeyId));if(!await j.check())return;if(!valid(model))throw new Error('invalid_response');f.model=model;f.confirmed=false;render(f);message(f,'已保存并读取最新资料。');
  }
  async function save(f,form){
    if(!owns(f)||f.busy||form._loadingSegments||form._segments===null||!form.reportValidity())return;
    const data=values(form),doc=form._document,file=form.elements.file?.files[0];
    f.busy=true;lock(form,true);message(f,'正在核对并保存…');
    // Node ownership continues across the receipt rendering, while the original
    // locked form controls the write. No automatic resend after accepted JSON.
    await job(f,form,async j=>{
      const version=form._jdVersion;
      const original=()=>j.active()&&form.isConnected&&form._jdVersion===version;
      let payload;
      if(doc)payload={...data,revision:doc.revision};
      else{
        const signature=JSON.stringify(data),attempt=form._upload;
        if(attempt&&attempt.signature===signature&&attempt.file===file)payload=attempt.payload;
        else{const body=await filePayload(file);if(!original()||!await j.check())return;payload={...data,requestId:crypto.randomUUID().replaceAll('-',''),file:body};form._upload={signature,file,payload};}
      }
      if(!original()||!await j.check())return;
      const response=await write('/journey-documents'+(doc?'/'+encodeURIComponent(doc.id):''),doc?'PATCH':'POST',payload);
      if(!j.active())return;
      j.detach();
      f.confirmed=true; // A readback failure must never become another POST/PATCH.
      if(!await j.check())return;
      if(!response?.document)throw new Error('invalid_response');
      f.journeyId=data.journeyId||'';f.segmentKey=data.segmentKey;
      await readAfterWrite(f,j);
    },error=>{
      message(f,error.status===400?'文件或填写内容未通过检查：'+(error.message==='file'?'请选择格式与扩展名一致的 PDF、JPG、PNG 或 WebP。':error.message)+(error.message?.includes('400 万像素')?' 请先导出不超过 2000 × 2000 像素的图片，再重新选择。':'')+' 原表单已保留。':description(error.status));
      if(error.status===409&&doc){const box=form.querySelector('[data-jd-conflict]');box.hidden=false;box.innerHTML='服务器版本已变化。你的草稿没有覆盖最新设置。'+button('latest','读取最新设置供核对');}
    });
    f.busy=false;if(owns(f)&&form.isConnected&&matches(f.actor,user,csrf)&&allowed())lock(form,false);
  }
  async function manage(f,id){
    if(f.busy)return;
    f.node.innerHTML='<p role="status">正在读取这份资料的最新设置…</p>';
    await job(f,null,async j=>{const model=await api(contextPath(f.journeyId));if(!await j.check())return;const doc=model.documents?.find(d=>d.id===id);if(!doc||!doc.canManage)throw Object.assign(new Error('unavailable'),{status:404});const scope=doc.journeyId?await api(contextPath(doc.journeyId)):model;if(!await j.check())return;editor(f,doc,scope);},()=>{message(f,'资料暂时不可管理，请返回列表重新核对。');f.node.insertAdjacentHTML('beforeend',button('refresh','返回资料夹'));});
  }
  async function latest(f,form){
    if(f.busy)return;
    await job(f,form,async j=>{const model=await api('/journey-documents');if(!await j.check())return;const doc=model.documents.find(d=>d.id===form._document.id),box=form.querySelector('[data-jd-conflict]');box.hidden=false;if(!doc){box.textContent='资料已删除，草稿无法覆盖它。请返回资料夹。';return;}form._latest=doc;box.innerHTML=`<strong>最新：${escape(doc.title)} · ${doc.visibility==='shared'?'家庭共享':'仅本人'} · 版本 ${doc.revision}</strong><p>你的表单尚未改动。采用最新版本后才可重新修改。</p>${button('use-latest','放弃本地设置，采用最新版本')}`;});
  }
  async function remove(f,form,approved=false){
    if(f.busy||!form?._document)return;
    const doc=form._document;const confirmed=form.querySelector('[data-jd-delete-confirm]');
    if(!approved){if(!confirmed)form.insertAdjacentHTML('beforeend',`<div class="jd-delete" data-jd-delete-confirm><p>删除“${escape(doc.title)}”？此操作会移除文件，家人也不能再下载。</p>${button('confirm-delete','确认删除')}${button('cancel-delete','保留资料')}</div>`);return;}
    f.busy=true;lock(form,true);
    await job(f,form,async j=>{await write('/journey-documents/'+encodeURIComponent(doc.id),'DELETE',{revision:doc.revision});if(!j.active())return;j.detach();f.confirmed=true;if(!await j.check())return;await readAfterWrite(f,j);});
    f.busy=false;if(owns(f)&&form.isConnected&&matches(f.actor,user,csrf)&&allowed())lock(form,false);
  }
  async function download(f,id){
    if(f.busy)return;const doc=f.model?.documents.find(d=>d.id===id);if(!doc)return;
    f.busy=true;message(f,'正在核对并准备下载…');
    await job(f,null,async j=>{
      const response=await fetch('/api/journey-documents/'+encodeURIComponent(doc.id)+'/file',{credentials:'same-origin',cache:'no-store'});
      if(!j.local())return;if(!response.ok)throw Object.assign(new Error('download'),{status:response.status});
      if((response.headers.get('content-type')||'').split(';')[0]!==doc.mimeType)throw new Error('invalid_type');
      const blob=await response.blob();if(!j.active()||blob.size>maxFile||!await j.check())return;
      const url=URL.createObjectURL(blob);urls.add(url);const anchor=document.createElement('a');let started=false;
      try{anchor.href=url;anchor.download=doc.filename;document.body.appendChild(anchor);anchor.click();started=true;}
      finally{anchor.remove();if(started)setTimeout(()=>{URL.revokeObjectURL(url);urls.delete(url);},30000);else{URL.revokeObjectURL(url);urls.delete(url);}}
      message(f,'下载已开始，请在浏览器下载列表核对是否保存。');
    });f.busy=false;
  }
  async function open(options={}){
    if(!allowed())return;
    generation++;openModal('旅行资料','<section class="journey-documents" data-jd-root></section>',true);
    const f={node:document.querySelector('[data-jd-root]'),actor:actor(),generation,epoch:0,route:location.href,journeyId:options.journeyId||'',segmentKey:options.segmentKey||'',model:null,busy:false,confirmed:false};current=f;await refresh(f);
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('[data-jd]'),f=current;if(!target||!owns(f)||!f.node.contains(target)||f.busy)return;
    const action=target.dataset.jd,form=target.closest('form');
    if(action==='refresh'||action==='cancel'){void refresh(f);return;}
    if(action==='all'){f.segmentKey='';void refresh(f);return;}
    if(action==='download'){void download(f,target.dataset.id);return;}
    if(action==='edit'){void manage(f,target.dataset.id);return;}
    if(action==='latest'){void latest(f,form);return;}
    if(action==='cancel-delete'){form.querySelector('[data-jd-delete-confirm]')?.remove();return;}
    if(action==='delete'||action==='confirm-delete'){void remove(f,form,action==='confirm-delete');return;}
    if(action==='use-latest'){void manage(f,form._latest?.id);return;}
    if(action==='upload'){void job(f,null,async j=>{if(await j.check())editor(f);});return;}
    if(action==='back'){void job(f,null,async j=>{if(await j.check())await window.JourneyUI.open(f.journeyId,{segmentKey:f.segmentKey});});}
  });
  const cleanup=()=>{if(current&&!owns(current)){current.model=null;current=null;generation++;}};
  new MutationObserver(cleanup).observe(document.getElementById('dialog'),{childList:true,subtree:true});
  document.getElementById('dialog').addEventListener('close',cleanup);
  window.addEventListener('pagehide',()=>{current=null;generation++;clearUrls();});
  return {open};
})();
