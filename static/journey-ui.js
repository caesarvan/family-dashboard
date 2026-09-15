/* A travel plan becomes assigned preparation, procurement and calendar entries. */
'use strict';
window.JourneyUI = (() => {
  let current = null, draft = null, context = {}, preview = null, operationKey = '', requestNumber = 0, resolutions = {}, shiftImpact = null;
  let returnContext = null, draftSequence = 0;
  let execution = null, executionFilter = null;
  let segmentEditTarget = null, createEntry = null;
  const draftActors = new WeakMap();
  const identity = actor => actor?.role === 'member' ? `${actor.householdId || 'default'}:${actor.id}` : '';
  const actorSnapshot = () => ({identity: identity(user), csrf});
  const sameActor = actor => actor.identity === identity(user) && actor.csrf === csrf && canEdit();
  const assistantOwnsReturn = () => !!document.querySelector('#assistant-return-bar,#assistant-workspace');
  async function verifyActor(actor, active) {
    if (!active()) throw new Error('这次旅行读取已被新的页面替代');
    const me = await api('/me');
    if (!active()) throw new Error('这次旅行读取已被新的页面替代');
    if (!sameActor(actor) || identity(me.user) !== actor.identity || me.csrf !== actor.csrf
        || (actor.authVersion !== undefined && (user?.auth_version !== actor.authVersion || me.user?.auth_version !== actor.authVersion))) {
      const problem = new Error('登录成员或家庭已变化，请刷新看板后重新进入旅行。');
      problem.contextChanged = true; throw problem;
    }
  }
  const formSnapshot = form => JSON.stringify({fields: [...form.querySelectorAll('input,select,textarea')].map(input => [input.name,input.type,input.value,input.checked]),
    // ShoppingUI owns photoIds in its closure; image sources also capture photo-only drafts.
    photos: [...form.querySelectorAll('#shopping-photo-list img')].map(image => image.getAttribute('src'))});
  async function draftOperation(form, work, onFailure = null) {
    const sequence = ++draftSequence, number = requestNumber, actor = actorSnapshot(), demo = isDemo;
    const snapshot = formSnapshot(form), planContext = clone(context), choices = clone(resolutions);
    const active = () => sequence === draftSequence && number === requestNumber && demo === isDemo
      && form.isConnected && document.getElementById('dialog').open && formSnapshot(form) === snapshot;
    const check = async () => {
      if (!active()) return false;
      if (!demo) await verifyActor(actor, active);
      return active();
    };
    try {
      if (await check()) await work({check, planContext, choices, demo});
    } catch (problem) {
      if (!active()) return;
      // Failed reads also need a fresh identity check before showing their result.
      if (!problem.contextChanged && problem.status !== 401) {
        try { if (!await check()) return; } catch (identityProblem) { problem = identityProblem; }
      }
      if (!active()) return;
      if (problem.contextChanged || problem.status === 401) {
        draftSequence++; current = null; draft = null; preview = null; context = {};
        operationKey = ''; resolutions = {}; shiftImpact = null; returnContext = null;
        shell('请重新进入旅行', `<p class="journey-error error" role="alert">${esc(problem.message)}</p>`);
      } else { error(problem); if (onFailure) onFailure(); }
    }
  }
  async function readImportFile(form, file) {
    if (!file) return;
    const text = form.querySelector('#journey-import-json');
    await draftOperation(form, async ({check}) => {
      if (file.size > 200000) throw new Error('行程文件过大，请保持在 200 KB 以内');
      const content = await file.text();
      if (await check()) text.value = content;
    });
  }
  async function importPlan(target) {
    const form = target.closest('form'); if (!form) return;
    const raw = form.querySelector('#journey-import-json').value;
    target.disabled = true;
    try {
      await draftOperation(form, async ({check, planContext, demo}) => {
        if (raw.length > 200000) throw new Error('导入文本过大，请保持在 200 KB 以内');
        let incoming; try { incoming = JSON.parse(raw); } catch { throw new Error('JSON 格式有误，请检查引号、逗号和括号'); }
        if (incoming?.plan) incoming = incoming.plan;
        if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming) || !Array.isArray(incoming.destinations)) throw new Error('计划应包含 destinations 数组，可先查看示例');
        if (incoming.schemaVersion === 2 && !demo) {
          const result = await api('/journeys/templates');
          if (!await check()) return;
          if (!(result.supportedSchemaVersions || result.capabilities?.schemaVersions || []).includes(2)) throw new Error('当前服务不支持 v2，未提交该计划；原草稿仍保留');
        }
        // Parse and normalize through the existing preview, never accept an external receipt or target.
        const result = demo ? demoResult(incoming) : await write('/journeys/preview', 'POST', {...planContext, plan: incoming});
        if (!await check()) return;
        draft = clone(result.plan); resolutions = {}; shiftImpact = null; wizard();
      });
    } finally { if (target.isConnected) target.disabled = false; }
  }
  async function openDraft(incoming, options = {}) {
    // This bridge creates a fresh local draft only. It never accepts a journey
    // target, signed receipt, generated entity IDs or cloud publication options.
    if (!canEdit() || isDemo || isTV) throw new Error('请在已登录的手机或电脑创建旅行草稿');
    if (document.querySelector('#journey-form,#journey-review-form')) throw new Error('已有旅行草稿正在编辑，请先完成或关闭它；没有覆盖原草稿');
    const form=options.sourceForm, actor=options.expectedContext;
    if (!form?.isConnected || form.id!=='assistant-journey-form' || !actor || !sameActor(actor) || typeof options.isCurrent!=='function') throw new Error('旅行简报来源已变化，请重新进入');
    const number=++requestNumber, snapshot=formSnapshot(form);
    const active=()=>number===requestNumber && options.isCurrent() && form.isConnected
      && formSnapshot(form)===snapshot && document.getElementById('dialog').open && !document.querySelector('#journey-form,#journey-review-form');
    await verifyActor(actor,active);
    if (!active()) return false;
    if (!incoming || typeof incoming!=='object' || !Array.isArray(incoming.destinations)) throw new Error('旅行简报格式无效');
    const plan={schemaVersion:1,title:incoming.title,start:incoming.start,end:incoming.end,international:incoming.international,
      budget:incoming.budget,memberIds:incoming.memberIds,note:incoming.note,
      destinations:incoming.destinations.map((row,index)=>({key:'brief-stop-'+(index+1),country:row.country,city:row.city,arrival:row.arrival,departure:row.departure}))};
    const result=await write('/journeys/preview','POST',{plan});
    if (!active()) return false;
    await verifyActor(actor,active);
    if (!active()) return false;
    draftSequence++; current=null; context={}; preview=null; operationKey=''; resolutions={}; shiftImpact=null; returnContext=null;
    draft=clone(result.plan); wizard();
    return true;
  }
  function budgetStatus(total, paid, reserved) {
    const balance = total - paid - reserved;
    if (paid > total) return {kind:'paid',label:'已付款超预算',amount:paid-total,
      note:`已付款已超过总预算；已付与预留合计超额 ${money(-balance)}，其中预留 ${money(reserved)} 尚未付款。`};
    if (balance < 0) return {kind:'reserved',label:'已付 + 预留超额',amount:-balance,
      note:'超额来自预留安排，尚不是实际超支。预留未付没有计为新增付款。'};
    return {kind:'remaining',label:'还需准备',amount:balance,note:'按总预算减去已付款与预留未付计算。采购金额作为预算内分项单独核对，不重复累加。'};
  }
  const clone = value => JSON.parse(JSON.stringify(value));
  const shiftDate = (value, days) => new Date(Date.parse(value + 'T12:00:00Z') + days * 86400000).toISOString().slice(0, 10);
  const dayDiff = (a, b) => Math.round((Date.parse(a + 'T12:00:00Z') - Date.parse(b + 'T12:00:00Z')) / 86400000);
  const button = (action, label, attrs = '', secondary = true) => `<button type="button" class="btn small ${secondary ? 'secondary' : ''}" data-journey="${action}" ${attrs}>${label}</button>`;
  const input = (label, name, value, type = 'text', attrs = '') => `<label class="field"><span>${label}</span><input name="${name}" value="${esc(value ?? '')}" type="${type}" ${attrs}></label>`;
  const amountInput = (label, name, value, optional = false) => input(label, name, value === null || value === undefined ? '' : value / 100, 'number', `min="0" step="0.01" ${optional ? '' : 'required'}`);
  const selectors = selected => ownerOptions(selected || 'shared');
  const key = prefix => prefix + '-' + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
  const notice = '准备清单是规划建议。签证、入境和健康要求需要按本人证件、目的地和出行日期向官方渠道核实。';
  const kinds = {flight:'航班',stay:'住宿',activity:'活动',legacy_day:'日期级分段'};
  const bookings = {idea:'计划中',booked:'已订 · 人工确认',cancelled:'已取消'};
  const policies = {fixed:'固定日期',shift_with_trip:'允许随旅行迁期'};
  const select = (label,name,value,options,attrs='') => `<label class="field"><span>${label}</span><select name="${name}" ${attrs}>${Object.entries(options).map(([v,l])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
  const zoneInput = (label,name,value) => input(label,name,value,'text','required maxlength="80" list="journey-timezones" autocomplete="off" placeholder="例如 Asia/Tokyo"');
  const zoneList = '<datalist id="journey-timezones">'+['Asia/Shanghai','Asia/Tokyo','Asia/Seoul','Asia/Bangkok','Asia/Singapore','Asia/Kolkata','Asia/Kathmandu','Europe/Berlin','Europe/Paris','Europe/London','Atlantic/Reykjavik','Pacific/Honolulu','America/Los_Angeles','America/New_York'].map(zone=>`<option value="${zone}">`).join('')+'</datalist>';
  const isV2 = () => draft?.schemaVersion === 2;
  const stripDerived = point => {
    const copy={...point}; for(const name of ['instant','iso','isoWithOffset','utc','durationMinutes','nights'])delete copy[name];return copy;
  };
  function newSegment(kind='activity') {
    const zone=document.querySelector('#journey-form .journey-destination [name=timeZone]')?.value||draft?.destinations?.[0]?.timeZone||draft?.referenceTimezone||'Asia/Shanghai',start=document.querySelector('#journey-core-fields [name=start]')?.value||draft?.start||plusDays(30);
    const row={key:key('segment'),kind,title:'',location:'',note:'',bookingState:'idea',datePolicy:kind==='flight'?'fixed':'shift_with_trip'};
    if(kind==='flight')return {...row,flightNumber:'',departure:{airport:'',city:'',local:'',timeZone:zone},arrival:{airport:'',city:'',local:'',timeZone:zone}};
    if(kind==='stay')return {...row,propertyName:'',address:'',timeZone:zone,checkInDate:start,checkOutDate:shiftDate(start,1),checkInTime:'',checkOutTime:''};
    if(kind==='activity')return {...row,start:{local:start+'T10:00',timeZone:zone},end:{local:start+'T11:00',timeZone:zone}};
    return {...row,start,end:start};
  }
  function pointFields(label,prefix,point,airport=false) {
    return `<fieldset class="journey-time-point"><legend>${label}</legend><div class="journey-field-grid">${airport?input('机场代码 / 名称',prefix+'.airport',point?.airport,'text','required maxlength="80"')+input('城市',prefix+'.city',point?.city,'text','maxlength="80"'):''}${input('当地日期与时间',prefix+'.local',point?.local,'datetime-local','required step="1"')}${zoneInput('当地 IANA 时区',prefix+'.timeZone',point?.timeZone)}</div><details class="journey-offset"><summary>夏令时重复时刻：指定 UTC 偏移</summary><p class="help">仅在同一当地时间出现两次时选择。偏移以分钟填写，例如 UTC+02:00 为 120、UTC+01:00 为 60；服务器仍会核对时区。</p>${input('UTC 偏移分钟（通常留空）',prefix+'.offsetMinutes',point?.offsetMinutes,'number','min="-840" max="840" step="1"')}</details></fieldset>`;
  }
  function detailRow(row) {
    const kind=row.kind||'legacy_day',common=`${input('名称', 'title',row.title,'text','required maxlength="100"')}${select('预订状态','bookingState',row.bookingState||'idea',bookings)}${select('日期规则','datePolicy',row.datePolicy||'fixed',policies,row.bookingState==='booked'?'disabled':'')}`;
    let fields='';
    if(kind==='flight')fields=`${input('航班号（可选）','flightNumber',row.flightNumber,'text','maxlength="40"')}<div class="journey-time-pair">${pointFields('出发 · 当地时间','departure',row.departure,true)}${pointFields('抵达 · 当地时间','arrival',row.arrival,true)}</div><p class="help">跨日期线时，抵达当地日期可以更早；预览按真实时刻计算飞行时长。</p>`;
    if(kind==='stay')fields=`<div class="journey-field-grid">${input('住宿名称','propertyName',row.propertyName,'text','required maxlength="150"')}${zoneInput('住宿 IANA 时区','timeZone',row.timeZone)}${input('入住日期','checkInDate',row.checkInDate,'date','required')}${input('退房日期（当天不计住宿）','checkOutDate',row.checkOutDate,'date','required')}${input('已知入住时间（可选）','checkInTime',row.checkInTime,'time')}${input('已知退房时间（可选）','checkOutTime',row.checkOutTime,'time')}${input('地址','address',row.address,'text','maxlength="300"')}</div><details class="journey-offset"><summary>入住 / 退房夏令时偏移（仅重复时刻需选）</summary><div class="journey-field-grid">${input('入住 UTC 偏移分钟','checkInOffsetMinutes',row.checkInOffsetMinutes,'number','min="-840" max="840" step="1"')}${input('退房 UTC 偏移分钟','checkOutOffsetMinutes',row.checkOutOffsetMinutes,'number','min="-840" max="840" step="1"')}</div></details><p class="journey-stay-nights" aria-live="polite">${Number.isFinite(dayDiff(row.checkOutDate,row.checkInDate))?Math.max(0,dayDiff(row.checkOutDate,row.checkInDate)):'—'} 晚 · 未填时间不会生成假定时刻</p>`;
    if(kind==='activity')fields=`${select('时间方式','activityMode',row.dateRange?'date':'timed',{timed:'明确起止时刻',date:'仅知道日期'})}<div class="journey-activity-time">${row.dateRange?`<div class="journey-field-grid">${input('开始日期','dateRange.startDate',row.dateRange.startDate,'date','required')}${input('结束日期（不含当天）','dateRange.endDateExclusive',row.dateRange.endDateExclusive,'date','required')}${zoneInput('活动当地时区','timeZone',row.timeZone||draft.referenceTimezone)}</div>`:`<div class="journey-time-pair">${pointFields('开始 · 当地时间','start',row.start)}${pointFields('结束 · 当地时间','end',row.end)}</div>`}</div>`;
    if(kind==='legacy_day')fields=`<div class="journey-field-grid">${input('开始日期','start',row.start,'date','required')}${input('结束日期（包含当天）','end',row.end,'date','required')}</div><p class="help">沿用原日期级分段，不将它推定为住宿或航班。</p>${select('需要改为具体细项？保留原关联，先填写时间再预览','changeKind','legacy_day',kinds)}`;
    return `<article class="journey-v2-segment" data-key="${esc(row.key)}" data-kind="${kind}"><div class="journey-segment-head"><span class="journey-kind">${kind==='flight'?'↗':kind==='stay'?'⌂':kind==='activity'?'✦':'▦'} ${kinds[kind]}</span>${button('remove-detail','移除此项','aria-label="移除此旅行细项"')}</div><div class="journey-common-fields">${common}</div>${fields}<div class="journey-field-grid journey-detail-notes">${input('日历地点','location',row.location,'text','maxlength="200"')}<label class="field"><span>备注</span><textarea name="note" maxlength="500">${esc(row.note||'')}</textarea></label></div></article>`;
  }
  function readDetailRows(container) {
    return [...container.querySelectorAll('.journey-v2-segment')].map(element=>{
      const row={key:element.dataset.key,kind:element.dataset.kind};
      for(const field of element.querySelectorAll('input,select,textarea')){
        if(['activityMode','changeKind'].includes(field.name))continue;
        const parts=field.name.split('.');let target=row;
        for(const part of parts.slice(0,-1))target=target[part]||=( {} );
        if(/offsetMinutes$/i.test(field.name)&&field.value==='')continue;
        target[parts.at(-1)]=/offsetMinutes$/i.test(field.name)?Number(field.value):field.value;
      }
      if(row.bookingState==='booked')row.datePolicy='fixed';
      return row;
    });
  }
  function detailEditor() {
    return `<section class="journey-details-editor"><div class="journey-section-heading"><div><h3>航班、住宿与活动</h3><p class="help">每项保留自己的当地时间，先核对再生成日程。</p></div></div><div class="journey-add-types">${Object.entries(kinds).map(([kind,label])=>button('add-detail','+ '+label,`data-kind="${kind}"`)).join('')}</div><div id="journey-details">${(draft.segments||[]).map(detailRow).join('')}</div></section>`;
  }
  function shiftOptions(rows,previous=new Map()) {
    return rows.map(row=>{
      const eligible=row.datePolicy==='shift_with_trip'&&!['booked','cancelled'].includes(row.bookingState),old=previous.get(row.key),checked=eligible&&(!old||old.disabled||old.checked);
      return `<label class="journey-shift-option"><input type="checkbox" data-shift-key="${esc(row.key)}" ${eligible?(checked?'checked':''):'disabled'}><span>${esc(row.title||kinds[row.kind])}<small>${eligible?'可按当地日期平移':row.bookingState==='booked'?'已订，保持原日期':'固定 / 取消，保持原日期'}</small></span></label>`;
    }).join('')||'<p class="help">先添加行程细项，再选择可移动项目。</p>';
  }
  function refreshShiftOptions() {
    const options=document.querySelector('.journey-shift-options'),rows=document.getElementById('journey-details');if(!options||!rows)return;
    const previous=new Map([...options.querySelectorAll('[data-shift-key]')].map(input=>[input.dataset.shiftKey,{checked:input.checked,disabled:input.disabled}]));
    options.innerHTML=shiftOptions(readDetailRows(rows),previous);
  }
  function rescheduleTools() {
    return `<details class="journey-reschedule"><summary>整体迁期 · 先修改上方出发日期，再选择可移动项</summary><p class="help">只平移你勾选的“允许随旅行迁期”计划项，保留当地钟点并重新核对夏令时。已订、固定、取消项目不移动；这不会联系航司或酒店改订。</p><div class="journey-shift-options">${shiftOptions(draft.segments||[])}</div>${button('shift-details','按规则迁期所选项目','',false)}</details>`;
  }
  function shiftSegment(row,days) {
    const copy=clone(row),shiftPoint=point=>{const value=stripDerived(point);value.local=shiftDate(value.local.slice(0,10),days)+value.local.slice(10);delete value.offsetMinutes;return value;};
    if(copy.kind==='flight'){copy.departure=shiftPoint(copy.departure);copy.arrival=shiftPoint(copy.arrival);}
    else if(copy.kind==='stay'){copy.checkInDate=shiftDate(copy.checkInDate,days);copy.checkOutDate=shiftDate(copy.checkOutDate,days);delete copy.checkInOffsetMinutes;delete copy.checkOutOffsetMinutes;}
    else if(copy.kind==='activity'&&!copy.dateRange){copy.start=shiftPoint(copy.start);copy.end=shiftPoint(copy.end);}
    else if(copy.dateRange){copy.dateRange.startDate=shiftDate(copy.dateRange.startDate,days);copy.dateRange.endDateExclusive=shiftDate(copy.dateRange.endDateExclusive,days);}
    else {copy.start=shiftDate(copy.start,days);copy.end=shiftDate(copy.end,days);}
    return copy;
  }
  function impactSummary() {
    if(!shiftImpact)return '';
    const range=row=>row.kind==='flight'?`${row.departure.local} → ${row.arrival.local}`:row.kind==='stay'?`${row.checkInDate} → ${row.checkOutDate}`:row.dateRange?`${row.dateRange.startDate} → ${row.dateRange.endDateExclusive}`:typeof row.start==='object'?`${row.start.local} → ${row.end.local}`:`${row.start} → ${row.end}`;
    return `<section class="journey-impact"><h3>本次迁期草稿 · ${shiftImpact.days>0?'推迟':'提前'} ${Math.abs(shiftImpact.days)} 天</h3><p>移动 ${shiftImpact.moved.length} 项，保留 ${shiftImpact.kept.length} 项；尚未保存。</p><ul>${shiftImpact.moved.map(row=>`<li>移动：${esc(row.title||kinds[row.kind])}<br>${esc(range(row))}<br>改为 ${esc(range(shiftSegment(row,shiftImpact.days)))}</li>`).join('')}${shiftImpact.kept.map(row=>`<li>保留原日期：${esc(row.title||kinds[row.kind])}<br>${esc(range(row))}</li>`).join('')}</ul></section>`;
  }
  const offsetLabel = value => value===undefined?'':`UTC${value<0?'-':'+'}${String(Math.floor(Math.abs(value)/60)).padStart(2,'0')}:${String(Math.abs(value)%60).padStart(2,'0')}`;
  function actualSegment(original,event) {
    const timing=event?.travelTiming;if(!timing||timing.schemaVersion!==2)return {row:original,preserved:false};
    const row={...clone(original),kind:timing.kind,bookingState:timing.bookingState,datePolicy:timing.datePolicy};
    const point=(instant,zone,extra={})=>{
      const local=new Intl.DateTimeFormat('sv-SE',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(instant)).replace(' ','T');
      return {...extra,local,timeZone:zone,instant,offsetMinutes:Math.round((Date.parse(local+'Z')-Date.parse(instant))/60000)};
    };
    if(timing.kind==='flight'){row.departure=point(event.start,timing.startTimeZone,timing.departure);row.arrival=point(event.end,timing.endTimeZone,timing.arrival);row.flightNumber=timing.flightNumber;}
    else if(timing.kind==='stay')Object.assign(row,{propertyName:timing.propertyName,address:timing.address,timeZone:timing.timeZone,checkInDate:event.startDate||timing.startDate,checkOutDate:event.endDateExclusive||timing.endDateExclusive,checkInTime:timing.checkInTime,checkOutTime:timing.checkOutTime});
    else if(timing.kind==='activity'&&!event.allDay){delete row.dateRange;row.start=point(event.start,timing.startTimeZone);row.end=point(event.end,timing.endTimeZone);}
    else if(timing.kind==='activity'){delete row.start;delete row.end;row.dateRange={startDate:event.startDate||timing.startDate,endDateExclusive:event.endDateExclusive||timing.endDateExclusive};row.timeZone=timing.timeZone;}
    else {row.start=event.startDate||timing.startDate;row.end=shiftDate(event.endDateExclusive||timing.endDateExclusive,-1);}
    const signature=value=>JSON.stringify([value.kind,value.departure?.local,value.arrival?.local,value.departure?.timeZone,value.arrival?.timeZone,value.checkInDate,value.checkOutDate,value.checkInTime,value.checkOutTime,value.timeZone,value.dateRange,typeof value.start==='object'?[value.start.local,value.start.timeZone,value.start.instant]:value.start,typeof value.end==='object'?[value.end.local,value.end.timeZone,value.end.instant]:value.end,value.departure?.instant,value.arrival?.instant]);
    return {row,preserved:signature(original)!==signature(row)};
  }
  function localTime(point,reference) {
    if(!point?.local)return '';
    let family='';
    if(point.instant&&point.timeZone!==reference)try{family=`<small class="journey-home-time">家庭时间 ${new Intl.DateTimeFormat('zh-CN',{timeZone:reference,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(point.instant))} · ${esc(reference)}</small>`;}catch(_){}
    return `<strong>${esc(point.local.replace('T',' '))}</strong><small>${esc(point.timeZone)} ${esc(offsetLabel(point.offsetMinutes))}</small>${family}`;
  }
  function segmentSummary(row,reference='Asia/Shanghai',event=null,interactive=false) {
    const actual=actualSegment(row,event);row=actual.row;
    const kind=row.kind||'legacy_day';let timing='';
    if(kind==='flight'){
      const elapsed=row.departure?.instant&&row.arrival?.instant?(Date.parse(row.arrival.instant)-Date.parse(row.departure.instant))/60000:null;
      timing=`<div class="journey-flight-times"><div><span>${esc(row.departure?.airport||'出发')} · ${esc(row.departure?.city||'')}</span>${localTime(row.departure,reference)}</div><span class="journey-time-arrow">→</span><div><span>${esc(row.arrival?.airport||'抵达')} · ${esc(row.arrival?.city||'')}</span>${localTime(row.arrival,reference)}</div></div>${elapsed!==null?`<p class="help">真实飞行区间 ${Math.floor(elapsed/60)} 小时 ${elapsed%60} 分钟</p>`:''}`;
    }else if(kind==='stay')timing=`<p class="journey-stay-summary">${esc(row.propertyName)} · ${dayDiff(row.checkOutDate,row.checkInDate)} 晚</p><p>${esc(row.checkInDate)}${row.checkInTime?' '+esc(row.checkInTime):''} 入住 → ${esc(row.checkOutDate)}${row.checkOutTime?' '+esc(row.checkOutTime):''} 退房<br><small>${esc(row.timeZone)} · 退房日不计住宿${!row.checkInTime&&!row.checkOutTime?' · 入住退房时刻未填写':''}</small></p>`;
    else if(kind==='activity')timing=row.dateRange?`<p>${esc(row.dateRange.startDate)} → ${esc(row.dateRange.endDateExclusive)}（不含结束日）<br><small>${esc(row.timeZone)}</small></p>`:`<div class="journey-flight-times"><div>${localTime(row.start,reference)}</div><span class="journey-time-arrow">→</span><div>${localTime(row.end,reference)}</div></div>`;
    else timing=`<p>${esc(row.start)} — ${esc(row.end)} · 全天（含结束日）</p>`;
    const saved=`${kind==='flight'&&row.flightNumber?`<p class="journey-saved-field"><strong>航班号</strong> ${esc(row.flightNumber)}</p>`:''}${kind==='stay'&&row.address?`<p class="journey-saved-field"><strong>完整地址</strong> ${esc(row.address)}</p>`:''}${event?.note||row.note?`<div class="journey-saved-note"><strong>备注 / 集合信息</strong><p>${esc(event?.note??row.note)}</p></div>`:''}`;
    return `<article class="journey-itinerary-item ${row.bookingState==='cancelled'?'is-cancelled':''}" data-segment-key="${esc(row.key)}" tabindex="-1"><div class="journey-segment-head"><span class="journey-kind">${esc(kinds[kind])}</span><div class="journey-status-tags"><span>${esc(bookings[row.bookingState]||'计划中')}</span><span>${esc(policies[row.datePolicy]||'固定日期')}</span></div></div><h3>${esc(event?.title||row.title)}</h3>${actual.preserved?'<p class="journey-preserved-time">已保留当前日程的时间；以下显示实际保存值，与旅行草稿可能不同。</p>':''}${timing}<p class="help">${esc(event?.location??row.location??'')}</p>${saved}${row.bookingState==='cancelled'?'<p class="help">仅标记计划取消，保留日程与关联；不会向航司或住宿方取消预订。</p>':''}${interactive&&canEdit()&&!isDemo&&!isTV?`<div class="journey-segment-actions">${button('segment-documents','资料',`data-segment-key="${esc(row.key)}"`)}${button('segment-edit','编辑此项',`data-segment-key="${esc(row.key)}"`)}${button('copy-segment','复制已保存文字',`data-segment-key="${esc(row.key)}"`)}</div>`:''}</article>`;
  }

  function locateSegment(container,key,editing=false) {
    if(!key||!container)return;
    const node=[...container.querySelectorAll(editing?'.journey-v2-segment':'.journey-itinerary-item')].find(item=>(editing?item.dataset.key:item.dataset.segmentKey)===key);
    if(!node)return;
    node.classList.add('journey-segment-target');node.tabIndex=-1;node.focus({preventScroll:true});node.scrollIntoView({block:'start'});
  }

  function shell(title, html) {
    stopExecution();
    activeManager = '';
    openModal(title, `<div class="journey-workspace">${html}</div>`, true);
    document.getElementById('dialog').classList.add('journey-dialog');
  }

  function error(problem) {
    const message=typeof problem==='string'?problem:problem.message;
    const box = document.querySelector('#dialog .journey-error');
    if (box) {
      box.textContent = message;
      if(problem?.choices?.length)box.insertAdjacentHTML('beforeend',`<div class="journey-offset-choices"><p>这个当地时间有多种映射，请选定一次再预览：</p>${problem.choices.map(choice=>button('choose-offset',offsetLabel(choice.offsetMinutes)+` · ${esc(choice.instant||'')}`,`data-offset="${choice.offsetMinutes}" data-field="${esc(problem.field||'')}"`)).join('')}</div>`);
      if(problem?.status===409&&context.journeyId)box.insertAdjacentHTML('beforeend',`<p>你的草稿仍在当前表单。先查看另一端的最新计划，再决定是否用这份草稿重新预览。</p>${button('latest-draft','查看最新版本，保留草稿')}`);
      box.scrollIntoView({block: 'center'});
    }
    else toast(message, true);
  }

  const fieldLabels={timing:'日期、时间、时区及行程说明',title:'名称',note:'备注',location:'地点',owner:'负责人'};
  function conflictValue(value,group) {
    if(value===null||value===undefined)return '无历史基线';
    if(typeof value!=='object')return group==='owner'?person(value):String(value);
    if(group==='timing')return [value.allDay?'全天':'定时',value.startDate||value.start,value.endDateExclusive||value.end, value.travelTiming?.startTimeZone, value.travelTiming?.endTimeZone,value.note].filter(Boolean).join(' · ');
    return Object.entries(value).map(([name,content])=>`${fieldLabels[name]||name}：${typeof content==='object'?'已有时间资料':content}`).join('；');
  }
  function previewIssues() {
    const summary=preview.summary||{},issues=summary.timeIssues||summary.warnings||summary.issues||[];
    const conflicts=summary.conflicts||[],preserved=summary.preserved||[],holds=summary.cloudReviews||[];
    return `${issues.length?`<section class="journey-impact"><h3>时间与衔接提醒</h3><ul>${issues.map(issue=>`<li>${esc(typeof issue==='string'?issue:issue.message||issue.note||issue.code||'请核对日期与衔接')}</li>`).join('')}</ul></section>`:''}${holds.length?`<section class="journey-impact"><h3>${holds.length} 项云日历绑定需要再次核对</h3><p>本次修改改变时间语义。保存本地计划后，请到“同步到云日历”明确核对；原远端事项和关联仍保留，不自动覆盖。</p></section>`:''}${preserved.length?`<section class="journey-impact"><h3>保留手工修改</h3><ul>${preserved.map(item=>`<li>${esc(typeof item==='string'?item:(draft.segments.find(row=>'segment:'+row.key===item.itemKey)?.title||item.itemKey||'日程')+' · '+(fieldLabels[item.fieldGroup]||item.fieldGroup||'已有内容'))}</li>`).join('')}</ul><p class="help">仅修改旅行其他内容时，不覆盖单独编辑过的日程。</p></section>`:''}${conflicts.length?`<section class="journey-conflicts"><h3>两边都改过，请逐项核对</h3><p class="help">日期、时间与时区必须作为一组选择。选择后重新预览，确认前不会覆盖现有日程。</p>${conflicts.map(item=>`<article class="journey-conflict" data-conflict-item="${esc(item.itemKey)}"><h4>${esc(draft.segments.find(row=>'segment:'+row.key===item.itemKey)?.title||item.itemKey)} · ${esc(fieldLabels[item.fieldGroup]||item.fieldGroup)}</h4><div class="journey-conflict-values"><div><small>上次生成</small><p>${esc(conflictValue(item.base,item.fieldGroup))}</p></div><div><small>当前日程</small><p>${esc(conflictValue(item.current,item.fieldGroup))}</p></div><div><small>旅行草稿</small><p>${esc(conflictValue(item.proposed,item.fieldGroup))}</p></div></div>${select('本次采用','conflictResolution',resolutions[item.itemKey]?.[item.fieldGroup]||'',{'':'请选择，暂不覆盖',current:'保留当前日程',plan:'使用旅行草稿'},`data-conflict-key="${esc(item.itemKey)}" data-conflict-field="${esc(item.fieldGroup)}"`)}</article>`).join('')}</section>`:''}`;
  }

  function defaults() {
    return {title: '', start: plusDays(30), end: plusDays(34), international: false,
      memberIds: (data?.people || []).map(p => p.id), budget: 0, saved: 0, paid: 0, note: '',
      destinations: [{key: 'destination-1', country: '', city: '', arrival: plusDays(30), departure: plusDays(34)}], shopping: []};
  }

  function samplePlan() {
    const p = defaults();
    return {...p, title: '东京与京都 · 秋日旅行', international: true, budget: 2000000,
      destinations: [{key: 'tokyo', country: '日本', city: '东京', arrival: p.start, departure: plusDays(32)},
        {key: 'kyoto', country: '日本', city: '京都', arrival: plusDays(32), departure: p.end}],
      shopping: [{key: 'adapter', title: '核对后再采购所需转换插头', quantity: '1 件', owner: 'shared', budget: 10000, note: '先检查已有设备和插座规格。'}]};
  }

  function demoPoint(point) {
    if(!point?.local||!point.timeZone)throw new Error('请填写当地日期、时间和 IANA 时区');
    const formatter=new Intl.DateTimeFormat('sv-SE',{timeZone:point.timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
    const local=point.local.length===16?point.local+':00':point.local,wall=Date.parse(local+'Z'),matches=[];
    for(let offset=-840;offset<=840;offset+=15){const instant=new Date(wall-offset*60000);if(formatter.format(instant).replace(' ','T')===local)matches.push({offsetMinutes:offset,instant:instant.toISOString()});}
    const picked=point.offsetMinutes===undefined?(matches.length===1?matches[0]:null):matches.find(match=>match.offsetMinutes===point.offsetMinutes);
    if(!picked)throw new Error(matches.length>1?'当地时间在夏令时切换中重复，请指定 UTC 偏移分钟后重试':'当地时间不存在或偏移与时区不匹配，请核对');
    return {...point,local,...picked};
  }

  function demoResult(plan) {
    const value = clone(plan);
    value.checklist ||= [{key: 'entry', title: '核对证件及目的地准备要求', owner: 'member1', dueOffsetDays: -21, note: notice},
      {key: 'stay', title: '确认住宿与往返交通', owner: 'member2', dueOffsetDays: -14, note: ''},
      {key: 'pack', title: '核对行李与预订资料', owner: 'shared', dueOffsetDays: -2, note: ''}];
    value.checklist.forEach(row => { row.due ||= shiftDate(value.start, row.dueOffsetDays); });
    value.segments ||= value.destinations.map(row => ({key: row.key, title: row.city + ' · 停留', start: row.arrival, end: row.departure, location: row.country + ' · ' + row.city, note: ''}));
    if(value.schemaVersion===2)for(const row of value.segments){
      if(row.kind==='flight'){row.departure=demoPoint(row.departure);row.arrival=demoPoint(row.arrival);if(row.arrival.instant<=row.departure.instant)throw new Error('抵达真实时刻必须晚于出发');}
      if(row.kind==='activity'&&!row.dateRange){row.start=demoPoint(row.start);row.end=demoPoint(row.end);if(row.end.instant<=row.start.instant)throw new Error('活动结束必须晚于开始');}
      if(row.kind==='stay'&&dayDiff(row.checkOutDate,row.checkInDate)<1)throw new Error('退房日期须晚于入住日期');
    }
    return {plan: value, summary: {create: {trips: 1, tasks: value.checklist.length, shopping: value.shopping.length, events: value.segments.length + 1}, update: {}, detach: 0, policyNotice: notice}, previewToken: null};
  }

  async function create() {
    if (isTV || (!canEdit() && !isDemo)) return false;
    const dialog = document.getElementById('dialog');
    const existing = dialog.open && dialog.querySelector('#journey-form,#journey-review-form');
    if (existing) {
      const active = () => existing.isConnected && dialog.open;
      try {
        if (!isDemo) await verifyActor(draftActors.get(existing), active);
        if (active()) toast('已有旅行草稿，请先完成或关闭；当前内容已保留。');
      } catch (problem) {
        if (active() && problem.contextChanged) shell('请重新进入旅行', '<p class="journey-error error" role="alert">登录成员或家庭已变化，请刷新后重新进入。</p>');
        else if (active()) toast('暂时无法核对登录状态，当前草稿已保留。', true);
      }
      return false;
    }
    if (createEntry?.active()) return createEntry.promise;
    const number = ++requestNumber, actor = {...actorSnapshot(), authVersion:user?.auth_version};
    const route = location.pathname + location.search + location.hash;
    draftSequence++;
    shell('规划下一程', '<p class="journey-loading" id="journey-create-loading">正在准备旅行向导…</p>');
    const marker = document.getElementById('journey-create-loading');
    const flow = {active: () => number === requestNumber && marker.isConnected && dialog.open
      && route === location.pathname + location.search + location.hash && !isTV};
    createEntry = flow;
    flow.promise = (async () => {
      try {
        if (!isDemo) await verifyActor(actor, flow.active);
        if (!flow.active()) return false;
        current = null; context = {}; resolutions = {}; shiftImpact = null; preview = null;
        operationKey = ''; returnContext = null; segmentEditTarget = null; draft = defaults();
        wizard(); return true;
      } catch (problem) {
        if (flow.active()) shell('暂时无法开始旅行', `<p class="journey-error error" role="alert">${problem.contextChanged?'登录成员或家庭已变化，请刷新后重新进入。':'暂时无法核对登录状态，请重试；没有创建旅行。'}</p>${button('create','重新开始')}`);
        return false;
      } finally { if (createEntry === flow) createEntry = null; }
    })();
    return flow.promise;
  }

  async function open(id = '', options = {}) {
    returnContext = null;
    if (isTV) { shell('旅行工作台', '<p class="help">请在已登录的手机或电脑管理旅行。</p>'); return; }
    const number = ++requestNumber, actor = actorSnapshot();
    shell('旅行工作台', '<div class="journey-loading">正在整理旅行、准备事项和预算…</div>');
    const loading = document.querySelector('#dialog .journey-loading');
    // A new wizard/review can reuse the dialog without starting another open().
    const active = () => number === requestNumber && document.getElementById('dialog').open
      && loading.isConnected && loading.closest('#dialog') === document.getElementById('dialog');
    try {
      if (!isDemo && actor.identity) await verifyActor(actor, active);
      const journeys = isDemo ? [] : (await api('/journeys')).journeys;
      if (!isDemo && actor.identity) await verifyActor(actor, active);
      if (!active()) return;
      const found = journeys.find(item => item.id === id || item.tripId === id);
      if (found) { renderDetail(found,options); return; }
      if (id) {
        const trip = data.trips.find(item => item.id === id);
        if (trip) { createFromTrip(trip); return; }
      }
      const workflowTrips = new Set(journeys.map(item => item.tripId));
      const legacy = (data?.trips || []).filter(trip => !workflowTrips.has(trip.id));
      shell('旅行工作台', `<div class="journey-hero"><div><span class="journey-kicker">PLANS INTO EVERYDAY ACTIONS</span><h3>从想出发，到准备好。</h3><p>把目的地、负责人、采购和日程放进同一份计划。</p></div>${(canEdit() || isDemo) ? button('create', '+ 规划下一程', '', false) : ''}${canEdit() && !isDemo ? button('assistant-brief','用文字整理旅行需求') : ''}</div>
        ${canEdit()&&!isDemo&&!isTV?`<div class="journey-library-entry">${button('documents-library','我的旅行资料')}<p class="help">查看本人资料，包括尚未关联到现有旅行的文件。</p></div>`:''}${isDemo ? '<p class="journey-notice">演示空间 · 可以体验预览，所有操作均不会保存。</p>' : ''}
        <div class="journey-cards">${journeys.map(j => `<button class="journey-tile" data-journey="detail" data-id="${esc(j.id)}"><span class="journey-kicker">${esc(j.plan.destinations.map(d => d.city).join(' → '))}</span><h3>${esc(j.trip.title)}</h3><p>${esc(j.trip.start)} — ${esc(j.trip.end)}</p><div class="journey-tile-stats"><span>准备 ${j.progress.done} / ${j.progress.total}</span><strong>${money(j.budget.total)}</strong></div><div class="meter"><span style="width:${j.progress.total ? j.progress.done / j.progress.total * 100 : 0}%"></span></div></button>`).join('')}
        ${legacy.map(trip => `<article class="journey-tile legacy"><span class="journey-kicker">${esc(trip.destination)}</span><h3>${esc(trip.title)}</h3><p>${esc(trip.start)} — ${esc(trip.end)}</p><strong>${money(trip.budget)}</strong>${(canEdit() || isDemo) ? button('upgrade', '补全准备与日程 →', `data-id="${esc(trip.id)}"`) : ''}</article>`).join('')}</div>
        ${!journeys.length && !legacy.length ? '<div class="journey-empty"><span>✦</span><h3>下一段回忆，从这里开始</h3><p>先写下目的地和时间，准备清单与日程会一起生成。</p></div>' : ''}
        <div class="journey-error error" role="alert"></div>`);
    } catch (err) {
      if (!active()) return;
      current = null;
      shell('旅行工作台', `<p class="journey-error error" role="alert">${esc(err.message)}</p>${button('list', '重新加载')}`);
    }
  }

  async function editLinked(target) {
    const journey = current, number = requestNumber, actor = {...actorSnapshot(), authVersion: user?.auth_version};
    const active = () => number === requestNumber && current === journey && target.isConnected && document.getElementById('dialog').open;
    const kind = target.dataset.kind, id = target.dataset.id;
    if (!['tasks','shopping'].includes(kind) || !journey?.[kind]?.some(item => item.id === id)) return;
    try {
    await verifyActor(actor, active);
    // Stage the entire household snapshot until this exact editor entry and
    // member are verified. A delayed read must not repaint a newer workspace.
    const next = await api('/state');
    await verifyActor(actor, active);
    if (!Number.isInteger(next?.revision) || !Array.isArray(next[kind])) throw new Error('记录暂时不可用，请稍后重试。');
    if (!data || !Number.isInteger(data.revision) || next.revision > data.revision) { data = next; renderBoard(); }
    online = true; lastFetch = displayTime(new Date());
    const item = data[kind].find(item => item.id === id && item.tripId === journey.tripId);
    if (!item) throw new Error('这项记录已移除或不再属于这次旅行，请重新打开旅行核对。');
    const parentOwns = assistantOwnsReturn();
    editItem(kind, id);
    // An assistant-originated flow keeps its original return destination.
    if (parentOwns || assistantOwnsReturn()) { returnContext = null; return; }
    const form = document.querySelector('#dialog form');
    if (!form) return;
    returnContext = {...actor,journeyId:journey.id,kind,id,form,snapshot:formSnapshot(form),number};
    form.before(Object.assign(document.createElement('div'), {id:'journey-return-bar',className:'journey-return-bar',innerHTML:
      `${button('return-linked','← 返回这次旅行')}<small>保存或取消后，回到原来的${kind==='tasks'?'出发准备':'采购准备'}并更新结果。</small><p class="error" role="alert"></p>`}));
    } catch (err) {
      if (!active()) return;
      if (!err.contextChanged && err.status !== 401) {
        try { await verifyActor(actor, active); } catch (identityError) { err = identityError; }
      }
      if (!active()) return;
      if (err.contextChanged || err.status === 401) {
        current = null; returnContext = null;
        shell('请重新进入旅行', `<p class="journey-error error" role="alert">${esc(err.message)}</p>`);
      } else error(err);
    }
  }

  async function returnToJourney(force = false) {
    const prior = returnContext;
    if (!prior) return;
    if (assistantOwnsReturn()) { returnContext = null; return; }
    const problem = document.querySelector('#journey-return-bar .error');
    if (!force && prior.form?.isConnected) {
      if (prior.form.querySelector('button[type=submit]')?.disabled) {
        if (problem) problem.textContent = '表单正在保存或上传图片，请等待处理结果后再返回。'; return;
      }
      if (formSnapshot(prior.form) !== prior.snapshot) {
        if (problem) problem.textContent = '这个表单尚未保存。请先保存，或使用原表单的取消按钮返回。'; return;
      }
    }
    const number = ++requestNumber;
    const active = () => returnContext === prior && number === requestNumber && document.getElementById('dialog').open && !!document.getElementById('journey-return-pending') && !assistantOwnsReturn();
    // Never paint a cached title, item or budget before checking the server session.
    shell('返回旅行', '<div id="journey-return-pending"><p class="help">正在核对登录状态并读取旅行进度与预算…</p></div>');
    try {
      await verifyActor(prior, active);
      const latest = await api('/journeys/' + encodeURIComponent(prior.journeyId));
      await verifyActor(prior, active);
      if (!active()) return;
      returnContext = null; renderDetail(latest);
      if (execution) execution.returnTarget = {kind: prior.kind, id: prior.id};
      const section = document.querySelector(`[data-journey-region="${prior.kind}"]`);
      const row = [...(section?.querySelectorAll('[data-journey-item]') || [])].find(item => item.dataset.journeyItem === prior.id);
      const destination = row || section;
      section?.insertAdjacentHTML('afterbegin', `<p class="journey-return-result" role="status">${row?'已回到原事项，进度与预算已重新读取。':latest[prior.kind]?.some(item=>item.id===prior.id)?'原事项仍保留，当前负责人筛选未显示；进度与预算已重新读取。':'原事项已移除或解除关联；已回到原区域并重新读取结果。'}</p>`);
      if (destination) { destination.scrollIntoView({block:'center'}); (row?.querySelector('[data-journey="linked-edit"]') || section)?.focus({preventScroll:true}); }
    } catch (err) {
      if (!active()) return;
      current = null;
      if (err.contextChanged || err.status === 401) returnContext = null;
      shell('旅行结果尚未读回', `<div id="journey-return-pending"><p class="journey-error error" role="alert">${esc(err.message)}</p><p class="help">尚未展示缓存内容。保存结果需要重新读取核对，请勿重复提交。</p>${returnContext?button('retry-return','重新读取这次旅行'):''}</div>`);
    }
  }

  document.addEventListener('close', event => {
    if (event.target.id !== 'dialog' || !returnContext?.form?.isConnected) return;
    const prior = returnContext;
    if (assistantOwnsReturn()) { returnContext = null; return; }
    setTimeout(() => { if (returnContext === prior && !document.getElementById('dialog').open) returnToJourney(true); }, 0);
  }, true);

  function createFromTrip(trip) {
    context = isDemo ? {} : {tripId: trip.id, tripRevision: trip.revision};
    draft = {...defaults(), title: trip.title, start: trip.start, end: trip.end, budget: trip.budget, saved: trip.saved, paid: trip.paid, note: trip.note || '',
      destinations: [{key: 'destination-1', country: '', city: trip.destination || '', arrival: trip.start, departure: trip.end}]};
    // Existing preparation is adopted by stable key, without duplicating it.
    const tasks = (data.tasks || []).filter(item => item.tripId === trip.id);
    if (tasks.length) draft.checklist = tasks.map(task => ({key: 'existing-' + task.id, title: task.title,
      owner: task.owner, due: task.due || shiftDate(trip.start, -7),
      dueOffsetDays: task.due ? dayDiff(task.due, trip.start) : -7, note: task.note || ''}));
    wizard();
  }

  function destinationRow(row) {
    return `<div class="journey-destination ${isV2()?'v2':''}" data-key="${esc(row.key)}">${input('国家 / 地区', 'country', row.country, 'text', 'maxlength="60"')}${input('城市', 'city', row.city, 'text', 'required maxlength="80"')}${input('抵达', 'arrival', row.arrival, 'date', 'required')}${input('离开', 'departure', row.departure, 'date', 'required')}${isV2()?zoneInput('目的地时区 · 请核对','timeZone',row.timeZone):''}${button('remove-row', '移除', 'aria-label="移除此目的地"')}</div>`;
  }

  function wizard() {
    preview = null;
    shell(context.journeyId ? '调整旅行计划' : context.tripId ? '补全旅行工作流' : '规划下一程', `<div class="journey-steps"><strong>1 · 安排旅程</strong><span>2 · 核对联动</span><span>3 · 一起完成</span></div><form id="journey-form" data-shift-anchor="${esc(draft.start)}" data-shift-end="${esc(draft.end)}">
      <div class="fields" id="journey-core-fields">${input('旅行名称', 'title', draft.title, 'text', 'required maxlength="100"')}
        <label class="field"><span>旅行类型</span><select name="international"><option value="false" ${draft.international ? '' : 'selected'}>国内旅行</option><option value="true" ${draft.international ? 'selected' : ''}>境外旅行</option></select></label>
        ${input('出发日期', 'start', draft.start, 'date', 'required')}${input('返程日期（包含当天）', 'end', draft.end, 'date', 'required')}
        ${amountInput('总预算（元）', 'budget', draft.budget)}${amountInput('已付款（元）', 'paid', draft.paid)}${amountInput('已预留、尚未支付（元）', 'saved', draft.saved)}
        <div class="field"><span>出行成员</span><div class="journey-members">${(data.people || []).map(p => `<label class="label-check"><input type="checkbox" name="memberIds" value="${esc(p.id)}" ${(draft.memberIds || []).includes(p.id) ? 'checked' : ''}>${esc(p.name)}</label>`).join('')}</div></div></div>
      ${isV2()?`<div class="journey-v2-heading"><span class="journey-kind">时区细项已启用</span><p>日期级分段仍可保留；航班、住宿和活动使用各自的时间。</p></div>${zoneList}${zoneInput('家庭参考时区','referenceTimezone',draft.referenceTimezone)}`:`<div class="journey-upgrade-card"><div><strong>把航班、住宿与活动安排清楚</strong><p>启用当地时间与时区，保留已有日期级分段。升级将在预览确认后保存。</p></div>${button('enable-details','启用旅行细项','',false)}</div>`}
      <div class="journey-section-heading"><h3>目的地与停留</h3>${button('destination', '+ 下一站')}</div><div id="journey-destinations">${draft.destinations.map(destinationRow).join('')}</div>
      ${isV2()?detailEditor()+rescheduleTools()+impactSummary():''}
      <label class="field"><span>预订与行程备注</span><textarea id="journey-trip-note" name="note" maxlength="2000">${esc(draft.note)}</textarea></label>
      <details class="journey-import"><summary>已有行程？导入结构化计划</summary><p class="help">选择适合的示例，替换成自己的计划，再导入核对。下载只保存文件，不填写或创建旅行。</p>
      <div class="journey-example-downloads" aria-label="下载虚构旅行计划示例">
        <a class="journey-example-download" href="/static/examples/journey-plan-v1.json" download="journey-plan-v1.json" data-journey-example="1"><strong>v1 · 日期级行程</strong><span>多国多城市、准备待办与采购预算</span><b>下载 JSON ↓</b></a>
        <a class="journey-example-download" href="/static/examples/journey-plan-v2.json" download="journey-plan-v2.json" data-journey-example="2"><strong>v2 · 航班、住宿与活动</strong><span>分别填写当地时间、IANA 时区和预订状态</span><b>下载 JSON ↓</b></a>
      </div>
      <p class="help">示例为虚构的 2027 年东京、京都、巴黎行程。金额、航班时刻与住宿均需自行替换。</p>
      <details class="journey-import-format"><summary>格式说明 · 金额、日期和时区怎么填</summary>
        <dl><dt>选择版本与结构</dt><dd>一个 JSON 对象就是一份计划。<code>schemaVersion</code> 取 <code>1</code> 或 <code>2</code>；填写 <code>title</code>、<code>start</code>、<code>end</code> 和 <code>destinations</code>。v2 需要服务支持。</dd>
        <dt>金额统一用人民币整数分</dt><dd><code>budget</code> 是总预算，<code>saved</code> 是预留未付，<code>paid</code> 是已付款。80 元写 <code>8000</code>；采购预算未知写 <code>null</code>。采购属于旅行预算内分项。</dd>
        <dt>日期与结束日</dt><dd>日期用 <code>YYYY-MM-DD</code>。旅行、目的地和 v1 / <code>legacy_day</code> 的结束日期包含当天；住宿的 <code>checkOutDate</code> 和活动的 <code>endDateExclusive</code> 排除当天。</dd>
        <dt>航班与活动的当地时间</dt><dd>用 <code>local: "2027-10-01T09:00:00"</code> 配 <code>timeZone: "Asia/Shanghai"</code>。航班出发、抵达各填自己的时区；v2 还需 <code>referenceTimezone</code> 及每个目的地的 <code>timeZone</code>。当地时间不带 Z 或 UTC 偏移；活动填写起止时刻或日期区间，两者选一。夏令时重复时刻须按预览提示选择偏移。家庭参考时区不会更改全站日程时区。</dd>
        <dt>住宿与预订状态</dt><dd>住宿字段直接写在该 <code>segment</code> 内；未知入住 / 退房时刻留空。<code>bookingState</code> 为 <code>idea</code>、<code>booked</code> 或 <code>cancelled</code>，只是人工标记；<code>datePolicy</code> 为 <code>fixed</code> 或 <code>shift_with_trip</code>。</dd>
        <dt>准备事项与采购</dt><dd><code>checklist</code> 填准备事项，<code>dueOffsetDays: -14</code> 表示出发前 14 天；<code>shopping</code> 填采购。<code>owner: "shared"</code> 表示共同负责，导入后可在表单分配给本人或伴侣。省略准备清单会使用模板；空数组表示不生成准备待办。</dd>
        <dt>保留条目对应关系</dt><dd>每组 <code>key</code> 须唯一，使用 1–64 位字母、数字、下划线或短横线，调整顺序时保留原 key。示例没有服务器记录编号或授权凭据，导入后仍须审阅并明确确认。</dd></dl>
      </details><textarea id="journey-import-json" rows="7" aria-label="行程 JSON" placeholder="粘贴计划 JSON"></textarea><div class="journey-inline-actions"><input type="file" id="journey-import-file" accept="application/json,.json" aria-label="选择行程 JSON 文件">${button('import', '读取计划')}${button('sample', '填入示例')}</div></details>
      <p class="journey-notice">${esc(notice)}</p><p class="help">${isV2()?'修改旅行总日期不会自动改订航班或酒店。整体迁期时，只有明确允许随旅行迁期且尚未预订的项目可以移动，固定和已订项目保留。':'调整出发日期会移动准备事项截止日和已有分段；返程日期变化后，请核对每一站停留时间。'}</p>
      <div class="journey-error error" role="alert"></div><div class="dialog-footer">${button('list', '返回旅行工作台')}<button class="btn" type="submit">预览准备与日程 →</button></div></form>`);
    const form = document.getElementById('journey-form');
    draftActors.set(form, {...actorSnapshot(), authVersion:user?.auth_version});
    if(segmentEditTarget&&segmentEditTarget.journeyId===context.journeyId)locateSegment(form,segmentEditTarget.key,true);
    let previousStart = draft.start;
    form.querySelector('#journey-core-fields [name="start"]').addEventListener('change', () => {
      const delta = dayDiff(form.querySelector('#journey-core-fields [name="start"]').value, previousStart);
      if (!Number.isFinite(delta)) return;
      if(isV2())return;
      form.querySelectorAll('[name="arrival"],[name="departure"]').forEach(input => { if (input.value) input.value = shiftDate(input.value, delta); });
      form.querySelector('#journey-core-fields [name="end"]').value = shiftDate(form.querySelector('#journey-core-fields [name="end"]').value, delta);
      previousStart = form.querySelector('#journey-core-fields [name="start"]').value;
    });
    form.addEventListener('submit', async event => {
      event.preventDefault(); const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
      try { await previewDraft(form); } finally { if (submit.isConnected) submit.disabled = false; }
    });
    document.getElementById('journey-import-file').addEventListener('change', event => readImportFile(form, event.target.files[0]));
  }

  function readWizard(form) {
    const values = Object.fromEntries([...form.querySelectorAll('#journey-core-fields input,#journey-core-fields select')].map(field=>[field.name,field.value]));
    return {...clone(draft), title: values.title, start: values.start, end: values.end, international: values.international === 'true',
      budget: toCents(values.budget), saved: toCents(values.saved), paid: toCents(values.paid), note: form.querySelector('#journey-trip-note').value,
      memberIds: [...form.querySelectorAll('[name="memberIds"]:checked')].map(input => input.value),
      ...(isV2()?{referenceTimezone:form.querySelector('[name="referenceTimezone"]').value,segments:readDetailRows(form)}:{}),
      destinations: [...form.querySelectorAll('.journey-destination')].map(row => ({key: row.dataset.key,
        ...Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.name, input.value]))}))};
  }

  function taskRow(row) {
    return `<div class="journey-review-row task" data-key="${esc(row.key)}">${input('准备事项', 'title', row.title, 'text', 'required maxlength="100"')}<label class="field"><span>负责人</span><select name="owner">${selectors(row.owner)}</select></label>${input('截止日期', 'due', row.due, 'date', 'required')}${button('remove-row', '移除', 'aria-label="移除此准备事项"')}<p class="help">${esc(row.note || '')}</p></div>`;
  }

  function purchaseRow(row) {
    return `<div class="journey-review-row purchase" data-key="${esc(row.key)}">${input('采购物品', 'title', row.title, 'text', 'required maxlength="100"')}${input('数量', 'quantity', row.quantity, 'text', 'required maxlength="30"')}${amountInput('整项预算（元）', 'budget', row.budget, true)}<label class="field"><span>负责人</span><select name="owner">${selectors(row.owner)}</select></label>${button('remove-row', '移除', 'aria-label="移除此采购物品"')}</div>`;
  }

  function segmentRow(row) {
    return `<div class="journey-review-row segment" data-key="${esc(row.key)}">${input('行程', 'title', row.title, 'text', 'required maxlength="100"')}${input('开始', 'start', row.start, 'date', 'required')}${input('结束（包含当天）', 'end', row.end, 'date', 'required')}${input('地点', 'location', row.location, 'text', 'maxlength="200"')}${button('remove-row', '移除', 'aria-label="移除此分段行程"')}</div>`;
  }

  function review() {
    const summary = preview.summary;
    const counts = {tasks: draft.checklist.length, shopping: draft.shopping.length, events: draft.segments.length + 1};
    shell('核对旅行联动', `<div class="journey-steps"><span>1 · 安排旅程</span><strong>2 · 核对联动</strong><span>3 · 一起完成</span></div>
      <div class="journey-review-hero"><span class="journey-kicker">${esc(draft.start)} — ${esc(draft.end)}</span><h3>${esc(draft.title)}</h3><p>${esc(draft.destinations.map(row => row.city).join(' → '))}</p><div class="journey-metrics"><div><small>准备事项</small><strong>${counts.tasks}</strong></div><div><small>采购物品</small><strong>${counts.shopping}</strong></div><div><small>本地日程</small><strong>${counts.events}</strong></div><div><small>总预算</small><strong>${money(draft.budget)}</strong></div></div></div>
      <form id="journey-review-form"><div class="journey-section-heading"><h3>谁来准备，何时完成</h3>${button('task', '+ 准备事项')}</div><div id="journey-checklist">${draft.checklist.map(taskRow).join('')}</div>
      <div class="journey-section-heading"><h3>需要采购的物品</h3>${button('purchase', '+ 采购物品')}</div><p class="help">这些采购属于旅行总预算，不会自动计入账单；保存后可在采购清单补充图片与实付。</p><div id="journey-purchases">${draft.shopping.map(purchaseRow).join('') || '<p class="journey-no-items">暂未列入采购物品，可按需要添加。</p>'}</div>
      ${isV2()?`${zoneList}<section class="journey-preview-itinerary"><div class="journey-section-heading"><h3>核对当地时间与家庭时间</h3><span class="pill">${esc(draft.referenceTimezone)}</span></div>${draft.segments.map(row=>segmentSummary(row,draft.referenceTimezone)).join('')}</section>${impactSummary()}${detailEditor()}`:`<div class="journey-section-heading"><h3>日历上的每一站</h3>${button('segment', '+ 分段行程')}</div><p class="help">总行程会覆盖 ${esc(draft.start)} 至 ${esc(draft.end)}，另为下方每一站生成全天日程。云日历写入与文件导出可在保存后操作。</p><div id="journey-segments">${draft.segments.map(segmentRow).join('')}</div>`}
      ${previewIssues()}<p class="journey-notice">${esc(summary.policyNotice || notice)}</p>${summary.detach ? `<p class="help">${summary.detach} 项将移出工作流并保留为独立记录。</p>` : ''}
      <div class="journey-error error" role="alert"></div><p id="journey-preview-state" class="help" aria-live="polite">已核对：${Object.values(summary.create || {}).reduce((a, b) => a + b, 0)} 项新建，${Object.values(summary.update || {}).reduce((a, b) => a + b, 0)} 项更新。${isDemo ? '演示预览不会保存。' : '请确认后一起创建。'}</p>
      <div class="dialog-footer">${button('back', '返回安排')}${button('repreview', '更新预览')}<button class="btn" type="submit" id="journey-apply" ${isDemo || preview.canApply===false || !preview.previewToken ? 'disabled' : ''}>${context.journeyId ? '确认更新计划' : '确认生成计划'}</button></div></form>`);
    const form = document.getElementById('journey-review-form');
    draftActors.set(form, {...actorSnapshot(), authVersion:user?.auth_version});
    form.addEventListener('input', dirty);
    form.addEventListener('change', dirty);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!canEdit() || !preview?.previewToken) return;
      const submit = form.querySelector('#journey-apply'); submit.disabled = true;
      // An already sent apply is not cancelled. Keep the original receipt and key for safe retries.
      const receipt = preview.previewToken, operation = operationKey, segmentKey=segmentEditTarget&&segmentEditTarget.journeyId===context.journeyId?segmentEditTarget.key:'';
      await draftOperation(form, async ({check}) => {
        const result = await write('/journeys/apply', 'POST', {previewToken: receipt, idempotencyKey: operation});
        if (!await check()) return;
        // Stage the read locally; a late response must not refresh a different member or draft.
        const next = await api('/state');
        if (!await check()) return;
        data = next; online = true; lastFetch = displayTime(new Date()); renderBoard();
        await open(result.id,{segmentKey});
        if (current?.id === result.id && document.getElementById('dialog').open && document.querySelector('.journey-detail-top')) toast('旅行、准备事项、采购与本地日程已关联');
      }, () => { if (preview?.previewToken === receipt && operationKey === operation) submit.disabled = false; });
    });
  }

  async function previewDraft(form, revision = null) {
    if (form.id === 'journey-review-form') dirty();
    await draftOperation(form, async ({check, planContext, choices, demo}) => {
      const wizardForm = form.id === 'journey-form';
      const updated = wizardForm ? readWizard(form) : readReview();
      if (wizardForm && !isV2()) {
        const delta = dayDiff(updated.start, draft.start);
        if (updated.checklist) updated.checklist.forEach(row => { row.due = shiftDate(updated.start, row.dueOffsetDays ?? dayDiff(row.due, draft.start)); });
        if (updated.segments && delta) updated.segments.forEach(row => { row.start = shiftDate(row.start, delta); row.end = shiftDate(row.end, delta); });
      }
      const nextContext = revision === null ? planContext : {...planContext, revision};
      const nextChoices = revision === null ? choices : {};
      const result = demo ? demoResult(updated) : await write('/journeys/preview', 'POST', {
        ...nextContext, plan: updated, ...(Object.keys(nextChoices).length ? {conflictResolutions: nextChoices} : {})
      });
      if (!await check()) return;
      context = nextContext; resolutions = nextChoices; preview = result;
      draft = clone(result.plan); operationKey = key('journey'); review();
    });
  }

  function dirty() {
    const submit = document.getElementById('journey-apply');
    if (submit) submit.disabled = true;
    const label = document.getElementById('journey-preview-state');
    if (label) label.textContent = '内容有调整，请先点击“更新预览”再确认。';
  }

  function readReview() {
    const p = clone(draft);
    const read = (selector, collection) => [...document.querySelectorAll(selector)].map(row => ({...(p[collection].find(item => item.key === row.dataset.key) || {}),
      key: row.dataset.key, ...Object.fromEntries([...row.querySelectorAll('input,select')].map(input => [input.name, input.value]))}));
    p.checklist = read('#journey-checklist .journey-review-row', 'checklist').map(row => ({...row, dueOffsetDays: dayDiff(row.due, p.start)}));
    p.shopping = read('#journey-purchases .journey-review-row', 'shopping').map(row => ({...row, budget: row.budget === '' ? null : toCents(row.budget)}));
    p.segments = isV2()?readDetailRows(document.getElementById('journey-review-form')):read('#journey-segments .journey-review-row', 'segments');
    return p;
  }

  // The execution view owns one dialog node. No poll or write completion may
  // reopen it after an editor, another journey or a different member takes over.
  const executionActor = actor => JSON.stringify([actor?.role, actor?.householdId || 'default', actor?.id, actor?.auth_version]);
  const executionRoute = () => location.pathname + location.search + location.hash;
  function stopExecution() {
    if (!execution) return;
    clearTimeout(execution.timer); execution.observer?.disconnect(); execution = null;
  }
  function executionActive(flow, sequence = flow.sequence) {
    return execution === flow && sequence === flow.sequence && flow.node.isConnected
      && document.getElementById('dialog').open && flow.number === requestNumber
      && flow.route === executionRoute() && !isDemo && !isTV;
  }
  function executionIdentityProblem() { const problem = new Error('登录成员或家庭已变化，请刷新看板后重新进入旅行。'); problem.contextChanged = true; return problem; }
  async function checkExecution(flow, sequence) {
    if (!executionActive(flow, sequence)) return false;
    if (!canEdit() || flow.actor !== executionActor(user) || flow.csrf !== csrf) throw executionIdentityProblem();
    const me = await api('/me');
    if (!executionActive(flow, sequence)) return false;
    if (!canEdit() || flow.actor !== executionActor(user) || flow.csrf !== csrf
        || flow.actor !== executionActor(me.user) || flow.csrf !== me.csrf) throw executionIdentityProblem();
    return true;
  }
  function executionStatus(flow) {
    if (!executionActive(flow)) return;
    const status = flow.node.querySelector('#journey-execution-status');
    status.classList.toggle('is-stale', !!flow.failure);
    status.textContent = flow.failure || (flow.working ? '正在核对并保存当前事项…' : flow.busy ? '正在读取最新事项与发布状态…'
      : flow.checkedAt ? `已读取 ${new Date(flow.checkedAt).toLocaleTimeString('zh-CN')} · 打开详情时每 10 秒核对` : '正在读取发布状态…');
    flow.node.querySelector('[data-journey="refresh-execution"]').disabled = !!(flow.busy || flow.working);
  }
  function scheduleExecution(flow) {
    clearTimeout(flow.timer);
    if (executionActive(flow) && !document.hidden && !flow.working) flow.timer = setTimeout(() => refreshExecution(flow), 10000);
  }
  async function executionFailure(flow, sequence, problem, message) {
    if (!executionActive(flow, sequence)) return;
    if (!problem.contextChanged && problem.status !== 401) {
      try { if (!await checkExecution(flow, sequence)) return; }
      catch (identityError) { if (identityError.contextChanged || identityError.status === 401) problem = identityError; }
    }
    if (!executionActive(flow, sequence)) return;
    if (problem.contextChanged || problem.status === 401) {
      const node = flow.node; current = null; executionFilter = null; stopExecution();
      const title=document.getElementById('dialog-title'); if (title) title.textContent='请重新进入旅行';
      node.innerHTML = '<p class="journey-error error" role="alert">登录成员或家庭已变化。请刷新看板后重新进入旅行。</p>';
    } else { flow.failure = message; executionStatus(flow); }
  }
  function keepExecutionFilter(flow) { executionFilter = {actor: flow.actor, csrf: flow.csrf, id: flow.id, value: flow.filter}; }
  function executionRows(rows, flow) {
    if (!flow || flow.filter === 'all') return rows;
    return rows.filter(row => flow.filter === 'shared' ? row.owner === 'shared'
      : flow.filter === 'mine' ? row.owner === flow.memberId : row.owner !== flow.memberId && row.owner !== 'shared');
  }
  function publicationLabel(row) {
    if (row.reviewRequired || row.status === 'needs_review') return {text: '需要核对后继续', kind: 'attention'};
    const states = {needs_authorization:'需要重新授权',permission_denied:'需要写入权限',conflict:'有冲突 · 需要处理',uncertain:'结果待核对',
      disconnected:'连接已断开',remote_deleted:'远端事项已删除',local_deleted:'本地事项已删除',retry:'同步遇到问题',paused:'已暂停',
      pending:'等待同步',publishing:'正在同步'};
    if (states[row.status]) return {text:states[row.status],kind:['pending','publishing'].includes(row.status)?'waiting':'attention'};
    if (row.status === 'published') return row.localChangesPending === true ? {text:'本地有变更 · 等待同步',kind:'waiting'}
      : row.localChangesPending === false ? {text:'已连接 · 上次同步成功',kind:'connected'} : {text:'已连接 · 状态待核对',kind:'waiting'};
    return {text:'状态待核对',kind:'waiting'};
  }
  function taskPublicationMarkup(task, flow) {
    if (!flow) return '';
    const records = flow.tasks?.publications?.filter(row => row.entityId === task.id) || [];
    const stale = flow.taskStale ? '<small class="journey-execution-stale">状态读取失败 · 显示上次结果</small>' : '';
    if (!flow.tasks) return `<div data-journey-task-status="${esc(task.id)}" class="journey-publication-status">${flow.taskStale?'发布状态暂不可用':'发布状态读取中…'}</div>`;
    return `<div data-journey-task-status="${esc(task.id)}" class="journey-publication-status">${records.map(row => {
      const label = publicationLabel(row);
      return `<div><span class="journey-sync-badge ${label.kind}">${esc(label.text)}</span>${row.canManage ? button('task-publication','查看 / 处理',`data-id="${esc(task.id)}" data-publication-id="${esc(row.id)}"`) : '<small>由已连接成员或云账户持有人管理</small>'}</div>`;
    }).join('') || `<div><span class="journey-sync-badge">尚未连接云清单</span>${button('task-publication','选择清单并预览',`data-id="${esc(task.id)}"`)}</div>`}${stale}</div>`;
  }
  function calendarPublicationMarkup(journey, flow) {
    if (!flow) return '';
    const records = flow.calendar?.publications || [];
    return `<section id="journey-calendar-publications" class="journey-calendar-publications"><h4>我的日历发布</h4>
      ${flow.calendarStale?'<p class="journey-execution-stale">日历状态读取失败 · 上次显示可能已过期</p>':''}
      ${!flow.calendar?'<p class="help">'+(flow.calendarStale?'发布状态暂不可用':'正在读取本人发布状态…')+'</p>':records.length?`<ul>${records.map(row=>{
        const item=journey.events.find(event=>event.id===row.entityId), label=publicationLabel(row);
        return `<li data-journey-calendar-status="${esc(row.id)}"><div><strong>${esc(item?.title||'原日程已移除')}</strong><span class="journey-sync-badge ${label.kind}">${esc(label.text)}</span></div>${button('calendar-publication','查看 / 处理',`data-publication-id="${esc(row.id)}"`)}</li>`;
      }).join('')}</ul>`:'<p class="help">你尚未为这次旅行连接云日历。请先选择日历，预览并明确确认。</p>'}
      <p class="help">这里显示你的日历连接状态；最新修改仍需等待同步完成。</p></section>`;
  }
  function paintExecution(flow) {
    if (!executionActive(flow)) return;
    const title=flow.node.closest('#dialog')?.querySelector('#dialog-title'); if (title) title.textContent=current.trip.title;
    const body = flow.node.querySelector('#journey-detail-body'), html = detailMarkup(current, flow);
    if (flow.html !== html) {
      const focused = document.activeElement?.closest('[data-journey]');
      const focus = focused && body.contains(focused) ? {...focused.dataset} : null;
      const focusedRegion = body.contains(document.activeElement) ? document.activeElement?.dataset?.journeyRegion : null;
      const focusedSegment=body.contains(document.activeElement)?document.activeElement?.closest('.journey-itinerary-item')?.dataset.segmentKey:null;
      body.innerHTML = html; flow.html = html; placeTimeline(body, current);
      if(focusedSegment)locateSegment(body,focusedSegment);
      if (flow.returnTarget) {
        const {kind,id}=flow.returnTarget, section=body.querySelector(`[data-journey-region="${kind}"]`);
        const row=[...(section?.querySelectorAll('[data-journey-item]')||[])].find(item=>item.dataset.journeyItem===id);
        const exists=current[kind]?.some(item=>item.id===id);
        section?.insertAdjacentHTML('afterbegin',`<p class="journey-return-result" role="status">${row?'已回到原事项，进度与预算已重新读取。':exists?'原事项仍保留，当前负责人筛选未显示；进度与预算已重新读取。':'原事项已移除或解除关联；已回到原区域并重新读取结果。'}</p>`);
      }
      if (focus) [...body.querySelectorAll('[data-journey]')].find(node=>node.dataset.journey===focus.journey && node.dataset.id===focus.id
        && node.dataset.kind===focus.kind && node.dataset.publicationId===focus.publicationId && node.dataset.segmentKey===focus.segmentKey)?.focus({preventScroll:true});
      else if (focusedRegion) [...body.querySelectorAll('[data-journey-region]')].find(node=>node.dataset.journeyRegion===focusedRegion)?.focus({preventScroll:true});
    }
    executionStatus(flow);
  }
  async function refreshExecution(flow = execution) {
    if (!flow || !executionActive(flow) || flow.busy || flow.working) return;
    clearTimeout(flow.timer); flow.busy = true; const sequence = ++flow.sequence; executionStatus(flow);
    try {
      if (!await checkExecution(flow, sequence)) return;
      const results = await Promise.allSettled([api('/journeys/'+encodeURIComponent(flow.id)),
        api('/task-publish/state?journeyId='+encodeURIComponent(flow.id)),api('/calendar-publish/journeys/'+encodeURIComponent(flow.id))]);
      if (!await checkExecution(flow, sequence)) return;
      const unauthorized = results.find(result=>result.status==='rejected' && result.reason?.status===401);
      if (unauthorized) throw unauthorized.reason;
      if (results[0].status === 'rejected') throw results[0].reason;
      current = results[0].value.journey || results[0].value;
      if (current.id !== flow.id) throw new Error('unexpected_journey');
      flow.taskStale = results[1].status === 'rejected'; flow.calendarStale = results[2].status === 'rejected';
      if (!flow.taskStale) flow.tasks = results[1].value;
      if (!flow.calendarStale) flow.calendar = results[2].value;
      flow.checkedAt = Date.now(); flow.failure = flow.taskStale || flow.calendarStale ? '事项已更新，部分发布状态读取失败；上次状态可能已过期，可重试。' : '';
      paintExecution(flow);
    } catch (problem) {
      await executionFailure(flow, sequence, problem, '读取失败，保留上次显示；内容可能已过期，请刷新后核对。');
    } finally {
      if (executionActive(flow, sequence)) { flow.busy = false; executionStatus(flow); scheduleExecution(flow); }
    }
  }
  function startExecution(journey) {
    if (!canEdit() || isDemo || isTV) return;
    const node = document.getElementById('journey-execution');
    const actor = executionActor(user), remembered = executionFilter;
    const filter = remembered?.actor===actor && remembered.csrf===csrf && remembered.id===journey.id ? remembered.value : 'all';
    const flow = execution = {id:journey.id,memberId:user.id,actor,csrf,node,number:requestNumber,route:executionRoute(),filter,sequence:0,busy:false,working:false};
    node.querySelector('[data-journey-owner-filter]').value = filter;
    flow.observer = new MutationObserver(()=>{ if (execution===flow && !executionActive(flow)) stopExecution(); });
    flow.observer.observe(document.getElementById('dialog'),{childList:true,subtree:true});
    paintExecution(flow); refreshExecution(flow);
  }
  async function executionAction(target) {
    const flow = execution;
    if (!flow || !executionActive(flow) || !flow.node.contains(target) || flow.working) return;
    const action=target.dataset.journey, kind=target.dataset.kind, id=target.dataset.id;
    const original = action==='toggle' ? current[kind]?.find(row=>row.id===id) : null;
    clearTimeout(flow.timer); flow.busy=false; flow.working=true; const sequence=++flow.sequence; flow.failure=''; executionStatus(flow);
    try {
      if (!await checkExecution(flow,sequence)) return;
      if (action==='toggle') {
        if (!original || !['tasks','shopping'].includes(kind)) return;
        const response = await api('/journeys/'+encodeURIComponent(flow.id));
        if (!await checkExecution(flow,sequence)) return;
        current=response.journey||response; const item=current[kind]?.find(row=>row.id===id);
        paintExecution(flow);
        if (!item || item.revision!==original.revision) { flow.failure='事项已被其他操作更新，已读回最新内容；请核对后再点击完成。'; return; }
        await write('/items/'+kind+'/'+encodeURIComponent(id),'PATCH',{done:!original.done,revision:original.revision});
        if (!await checkExecution(flow,sequence)) return;
        const latest = await Promise.allSettled([api('/journeys/'+encodeURIComponent(flow.id)),api('/task-publish/state?journeyId='+encodeURIComponent(flow.id)),api('/calendar-publish/journeys/'+encodeURIComponent(flow.id))]);
        if (!await checkExecution(flow,sequence)) return;
        const unauthorized=latest.find(result=>result.status==='rejected' && result.reason?.status===401);
        if (unauthorized) throw unauthorized.reason;
        if (latest[0].status==='rejected') throw latest[0].reason;
        current=latest[0].value.journey||latest[0].value;
        flow.taskStale=latest[1].status==='rejected'; flow.calendarStale=latest[2].status==='rejected';
        if (!flow.taskStale) flow.tasks=latest[1].value;
        if (!flow.calendarStale) flow.calendar=latest[2].value;
        flow.failure=flow.taskStale||flow.calendarStale?'保存后部分发布状态读取失败，上次显示可能已过期；请刷新核对。':'';
        flow.checkedAt=Date.now(); paintExecution(flow);
      } else if (action==='linked-edit') {
        keepExecutionFilter(flow); await editLinked(target);
      } else if (action==='edit'||action==='segment-edit') { keepExecutionFilter(flow); editCurrent(target.dataset.segmentKey||''); }
      else if(action==='documents'||action==='segment-documents'){
        if(!window.JourneyDocuments?.open)throw new Error('document_module_unavailable');
        await window.JourneyDocuments.open({journeyId:flow.id,segmentKey:target.dataset.segmentKey||''});
      } else if(action==='copy-segment'){
        const key=target.dataset.segmentKey,row=current.plan.segments.find(item=>item.key===key);
        if(!row)return;
        const article=[...flow.node.querySelectorAll('.journey-itinerary-item')].find(item=>item.dataset.segmentKey===key);
        const text=[...article.children].filter(node=>!node.classList.contains('journey-segment-actions')).map(node=>node.innerText).join('\n');
        await navigator.clipboard.writeText(text);
        if(executionActive(flow,sequence))toast('已复制当前保存的行程文字');
      }
      else {
        keepExecutionFilter(flow);
        const expectedContext={identity:JSON.stringify([user.householdId||'default',user.id,user.auth_version]),csrf:flow.csrf};
        const tasks=action==='cloud-tasks'||action==='task-publication';
        const publisher=tasks?window.TaskPublish:window.CalendarPublish;
        if (!publisher?.open) throw new Error('publisher_unavailable');
        const publicationId=target.dataset.publicationId;
        if (tasks && publicationId && !flow.tasks?.publications?.some(row=>row.id===publicationId&&row.canManage)) return;
        const opening=publisher.open(tasks?{journeyId:flow.id}:flow.id,expectedContext);
        const dialog=document.getElementById('dialog'), loading=dialog.querySelector(tasks?'#task-publish-loading':'#calendar-publish-loading');
        let destination=null, replaced=false;
        const observer=new MutationObserver(()=>{
          if (!replaced && loading && !loading.isConnected) {
            replaced=true; destination=dialog.querySelector(tasks?'#task-publish-root':'#calendar-publish-root');
          }
        });
        observer.observe(dialog,{childList:true,subtree:true});
        try { await opening; } finally { observer.disconnect(); }
        // Publishers perform their own actor checks. Focus is a view operation;
        // it never chooses an entity, source or cloud action on the user's behalf.
        if (!destination?.isConnected || !dialog.open || flow.route!==executionRoute() || flow.number!==requestNumber
          || flow.actor!==executionActor(user) || flow.csrf!==csrf) return;
        const attr=tasks?'tp':'cp';
        const focus=publicationId?[...destination.querySelectorAll('[data-'+attr+'][data-id]')].find(node=>node.dataset.id===publicationId)
          :tasks&&id?[...destination.querySelectorAll('[name="entityId"]')].find(node=>node.value===id):null;
        if (focus) { const row=focus.closest('.fh-transaction,label')||focus; row.scrollIntoView({block:'center'}); focus.focus({preventScroll:true}); }
      }
    } catch (problem) {
      if (executionActive(flow,sequence) && problem.status===409) {
        try {
          const response=await api('/journeys/'+encodeURIComponent(flow.id));
          if (await checkExecution(flow,sequence)) { current=response.journey||response; paintExecution(flow); }
        } catch (_) { /* The fixed stale notice below preserves the last view. */ }
      }
      await executionFailure(flow,sequence,problem,problem.status===409?'事项有新的修改，已停止本次操作；请刷新并核对后重试。':'本次操作未完成核对，内容可能已过期；请刷新确认结果后再操作。');
    } finally {
      if (executionActive(flow,sequence)) { flow.working=false; executionStatus(flow); scheduleExecution(flow); }
    }
  }
  document.addEventListener('visibilitychange',()=>{ if (execution) { clearTimeout(execution.timer); if (!document.hidden) refreshExecution(execution); } });
  for (const name of ['hashchange','popstate']) window.addEventListener(name,()=>{ if (execution && !executionActive(execution)) stopExecution(); });
  document.getElementById('dialog').addEventListener('close',()=>{ if (!document.getElementById('dialog').open) stopExecution(); });
  function placeTimeline(container, journey) {
    if (journey.plan.schemaVersion!==2) return;
    const timeline=container.querySelector('.journey-timeline')?.closest('.journey-panel'), grid=container.querySelector('.journey-detail-grid');
    if (timeline && grid) { timeline.classList.add('journey-v2-timeline'); grid.before(timeline); }
  }
  function renderDetail(journey,options={}) {
    current = journey;
    const managed = canEdit() && !isDemo && !isTV;
    shell(journey.trip.title, `<section id="journey-execution" data-journey-id="${esc(journey.id)}">${managed?`<div class="journey-execution-toolbar"><label>准备事项负责人<select data-journey-owner-filter aria-label="准备事项负责人"><option value="all">全部</option><option value="mine">本人</option><option value="partner">另一位成员</option><option value="shared">共同</option></select></label>${button('refresh-execution','刷新执行状态')}</div><p id="journey-execution-status" role="status" aria-live="polite">正在读取最新事项与发布状态…</p><p class="journey-execution-help">按负责人筛选准备与采购，顶部进度仍统计整趟旅行。</p>`:''}<div id="journey-detail-body">${detailMarkup(journey,null)}</div></section>`);
    placeTimeline(document.getElementById('journey-detail-body'),journey); startExecution(journey);
    locateSegment(document.getElementById('journey-detail-body'),typeof options.segmentKey==='string'?options.segmentKey:'');
  }
  function detailMarkup(journey, flow) {
    const trip = journey.trip, progress = journey.progress, budget = journey.budget, status = budgetStatus(budget.total, budget.paid, budget.reserved);
    const toggle = (item, kind) => canEdit() ? `<button class="check ${item.done ? 'done' : ''}" data-journey="toggle" data-kind="${kind}" data-id="${esc(item.id)}" aria-label="${item.done ? '恢复' : '完成'}${esc(item.title)}" aria-pressed="${!!item.done}">${item.done ? icon('check') : ''}</button>` : `<span class="check ${item.done ? 'done' : ''}">${item.done ? icon('check') : ''}</span>`;
    return `<div class="journey-detail-top"><div><span class="journey-kicker">${esc(journey.plan.destinations.map(row => row.city).join(' → '))}</span><p>${esc(trip.start)} — ${esc(trip.end)} · ${journey.plan.memberIds.map(id => esc(person(id))).join('、')}</p></div><div class="journey-inline-actions">${button('list', '全部旅行')}${canEdit()&&!isDemo&&!isTV?button('documents','旅行资料'):''}${canEdit() ? button('edit', '调整计划') : ''}</div></div>
      ${journey.plan.schemaVersion===2?`<div class="journey-destination-zones">${journey.plan.destinations.map(row=>`<span>${esc(row.city)} · ${esc(row.timeZone)}</span>`).join('')}<span>家庭参考 · ${esc(journey.plan.referenceTimezone)}</span></div>`:''}<div class="journey-metrics"><div><small>旅行总预算</small><strong>${money(budget.total)}</strong></div><div><small>已付款</small><strong>${money(budget.paid)}</strong></div><div><small>预留未付</small><strong>${money(budget.reserved)}</strong></div><div class="journey-budget-status ${status.kind}" data-budget-status="${status.kind}"><small>${status.label}</small><strong>${money(status.amount)}</strong></div></div><p class="journey-budget-explanation ${status.kind}">${esc(status.note)}</p>
      <div class="journey-detail-grid"><section class="journey-panel" data-journey-region="tasks" tabindex="-1"><div class="journey-section-heading"><h3>出发准备</h3>${canEdit() ? button('cloud-tasks', '连接待办清单') : ''}<span class="pill">${progress.done} / ${progress.total}</span></div><div class="meter"><span style="width:${progress.total ? progress.done / progress.total * 100 : 0}%"></span></div><div class="journey-task-list">${executionRows(journey.tasks,flow).map(task => `<div data-journey-item="${esc(task.id)}" class="journey-linked-row ${task.done ? 'completed' : ''}">${toggle(task, 'tasks')}<div><strong>${esc(task.title)}</strong><small>${esc(person(task.owner))} · ${esc(task.due || '未设截止日期')}</small>${taskPublicationMarkup(task,flow)}</div>${canEdit() ? button('linked-edit', '编辑', `data-kind="tasks" data-id="${esc(task.id)}"`) : ''}</div>`).join('') || '<p class="help">当前筛选下没有准备事项；全部事项可在调整计划中管理。</p>'}</div></section>
      <section class="journey-panel" data-journey-region="shopping" tabindex="-1"><div class="journey-section-heading"><h3>采购准备</h3><span class="pill">${progress.purchased} / ${progress.purchaseCount}</span></div><p class="help">预算 ${money(budget.purchaseBudget)}${budget.unknownPurchaseBudgets ? ` · ${budget.unknownPurchaseBudgets} 件未填` : ''} · 已买实付 ${money(budget.purchaseActual)}${budget.unknownPurchaseActuals ? ` · ${budget.unknownPurchaseActuals} 件未填实付` : ''}</p>${executionRows(journey.shopping,flow).map(item => `<div data-journey-item="${esc(item.id)}" class="journey-linked-row ${item.done ? 'completed' : ''}">${toggle(item, 'shopping')}<div><strong>${esc(item.title)}</strong><small>${esc(item.quantity)} · ${item.budget === null ? '预算待填' : money(item.budget)} · ${esc(person(item.owner))}</small></div>${canEdit() ? button('linked-edit', '图片 / 详情', `data-kind="shopping" data-id="${esc(item.id)}"`) : ''}</div>`).join('') || '<p class="help">当前筛选下没有采购；全部物品可在调整计划中管理。</p>'}<p class="journey-footnote">${esc(budget.note)}</p></section></div>
      <section class="journey-panel"><div class="journey-section-heading"><h3>旅途时间线</h3>${canEdit() ? `<div class="journey-inline-actions">${button('cloud-calendar', '同步到云日历')}<a class="btn small secondary" href="${esc(journey.calendar.icsUrl)}" download>导出日历 .ics</a></div>` : ''}</div><div class="journey-timeline">${journey.plan.schemaVersion===2?journey.plan.segments.map(row=>segmentSummary(row,journey.plan.referenceTimezone,journey.events.find(event=>event.workflowKey==='segment:'+row.key),true)).join(''):journey.events.slice().sort((a,b)=>a.start.localeCompare(b.start)).map(event=>`<div><span class="journey-timeline-dot"></span><time>${esc(event.start.slice(0,10))} — ${esc(shiftDate(event.end.slice(0,10),-1))}</time><strong>${esc(event.title)}</strong><p>${esc(event.location)}</p></div>`).join('')}</div><div id="journey-cloud-calendar">${calendarPublicationMarkup(journey,flow)}</div><p class="help">本地日程已联动。选择本人已绑定的云日历，预览确认后发布；持续同步绑定会更新后续本地修改，远端冲突时暂停。ICS 为独立文件导出。</p></section>
      ${trip.note ? `<section class="journey-panel"><h3>行程备注</h3><p class="journey-note-text">${esc(trip.note)}</p></section>` : ''}<p class="journey-notice">${esc(journey.policyNotice)}</p><div class="journey-error error" role="alert"></div>`;
  }

  function editCurrent(segmentKey='') {
    segmentEditTarget=segmentKey?{journeyId:current.id,key:segmentKey}:null;
    context = {journeyId: current.id, revision: current.revision}; resolutions = {}; shiftImpact = null; draft = clone(current.plan);
    for (const name of ['title', 'start', 'end', 'budget', 'saved', 'paid', 'note']) draft[name] = current.trip[name];
    // Independent edits in the task/purchase managers remain authoritative.
    for (const [collection, rows, prefix] of [['checklist', current.tasks, 'task:'], ['shopping', current.shopping, 'shopping:']]) {
      draft[collection] = (draft[collection]||[]).map(row => {
        const latest = rows.find(item => item.workflowKey === prefix + row.key);
        if (!latest) return row;
        const merged = {...row};
        for (const property of ['title', 'owner', 'note', 'due', 'budget', 'quantity']) if (latest[property] !== undefined) merged[property] = latest[property];
        if (merged.due) merged.dueOffsetDays = dayDiff(merged.due, draft.start);
        return merged;
      });
    }
    wizard();
  }

  document.addEventListener('click', async event => {
    const target = event.target.closest('[data-journey]'); if (!target) return;
    const action = target.dataset.journey;
    if(action==='documents-library'){
      if(!canEdit()||isTV||isDemo)return;
      const actor={...actorSnapshot(),authVersion:user.auth_version},number=requestNumber;
      const active=()=>number===requestNumber&&target.isConnected&&document.getElementById('dialog').open;
      try{await verifyActor(actor,active);if(active())await window.JourneyDocuments.open();}
      catch(problem){if(active())error(problem);}
      return;
    }
    if (action === 'refresh-execution') { await refreshExecution(); return; }
    if (['toggle','linked-edit','edit','segment-edit','documents','segment-documents','copy-segment','cloud-tasks','cloud-calendar','task-publication','calendar-publication'].includes(action) && target.closest('#journey-execution')) {
      await executionAction(target); return;
    }
    try {
      if (action === 'return-linked' || action === 'retry-return') { await returnToJourney(action === 'retry-return'); return; }
      if (action === 'list') { await open(); return; }
      if (action === 'detail') { await open(target.dataset.id); return; }
      if (!canEdit() && !isDemo) return;
      if (action === 'create') { await create(); return; }
      if (action === 'upgrade') createFromTrip(data.trips.find(trip => trip.id === target.dataset.id));
      if (action === 'edit') editCurrent();
      if(action==='enable-details'){
        const form=document.getElementById('journey-form');target.disabled=true;
        await draftOperation(form, async ({check,demo}) => {
          const saved=readWizard(form), result=demo?{supportedSchemaVersions:[2]}:await api('/journeys/templates');
          if(!await check())return;
          if(!(result.supportedSchemaVersions||result.capabilities?.schemaVersions||[]).includes(2))throw new Error('当前服务尚未支持旅行细项，已保留日期级草稿；请等待前后端一起更新');
          draft={...saved,schemaVersion:2,referenceTimezone:'Asia/Shanghai',destinations:saved.destinations.map(row=>({...row,timeZone:row.timeZone||'Asia/Shanghai'})),
            segments:(saved.segments||saved.destinations.map(row=>({key:row.key,title:row.city+' · 停留',start:row.arrival,end:row.departure,location:row.city,note:''}))).map(row=>({...row,kind:'legacy_day',bookingState:'idea',datePolicy:'fixed'}))};
          wizard();
        });return;
      }
      if(action==='add-detail'){
        const rows=document.getElementById('journey-details');
        if(rows.children.length>=100)throw new Error('每趟旅行最多 100 项行程');
        rows.insertAdjacentHTML('beforeend',detailRow(newSegment(target.dataset.kind)));refreshShiftOptions();dirty();return;
      }
      if(action==='remove-detail'){target.closest('.journey-v2-segment').remove();refreshShiftOptions();dirty();return;}
      if(action==='shift-details'){
        const form=document.getElementById('journey-form'),next=readWizard(form),days=dayDiff(next.start,form.dataset.shiftAnchor);
        if(!Number.isFinite(days)||days===0)throw new Error('请先在上方修改出发日期；当前没有需要平移的天数');
        const selected=new Set([...form.querySelectorAll('[data-shift-key]:checked')].map(input=>input.dataset.shiftKey));
        const moved=[],kept=[];
        next.segments=next.segments.map(row=>{if(selected.has(row.key)&&row.datePolicy==='shift_with_trip'&&!['booked','cancelled'].includes(row.bookingState)){moved.push(row);return shiftSegment(row,days);}kept.push(row);return row;});
        if(!moved.length)throw new Error('没有选中可移动项目；已订、固定和取消项目会保持原日期');
        next.destinations=next.destinations.map(row=>({...row,arrival:shiftDate(row.arrival,days),departure:shiftDate(row.departure,days)}));
        if(next.end===form.dataset.shiftEnd)next.end=shiftDate(next.end,days);
        for(const row of next.checklist||[])if(row.dueRule?.anchor==='trip.start')row.due=shiftDate(next.start,row.dueRule.offsetDays||0);
        shiftImpact={days,moved,kept};draft=next;resolutions={};wizard();return;
      }
      if(action==='choose-offset'){
        const match=target.dataset.field.match(/^segments\[(\d+)\]\.(departure|arrival|start|end|checkInTime|checkOutTime)/);
        if(!match)throw new Error('请在对应行程的夏令时设置中填写 '+target.dataset.offset+' 分钟后重新预览');
        const row=document.querySelectorAll('.journey-v2-segment')[Number(match[1])],field=row?.querySelector(`[name="${match[2].startsWith('check')?match[2].replace('Time','OffsetMinutes'):match[2]+'.offsetMinutes'}"]`);
        if(!field)throw new Error('对应时间输入框已变化，请重新核对');
        field.value=target.dataset.offset;field.closest('details').open=true;field.focus();dirty();return;
      }
      if(action==='latest-draft'){
        const form=target.closest('form');target.disabled=true;
        await draftOperation(form, async ({check,planContext}) => {
          const latest=await api('/journeys/'+encodeURIComponent(planContext.journeyId));
          if(!await check())return;
          const value=latest.journey||latest,box=form.querySelector('.journey-error');
          if(!value.plan)throw new Error('最新版本暂时不可用，请稍后重试，草稿仍保留');
          box.innerHTML=`<strong>服务器版本 ${esc(value.revision)} · ${esc(value.plan.title)}</strong><p>${esc(value.plan.start)} — ${esc(value.plan.end)} · 预算 ${money(value.plan.budget)}</p><p>当前表单仍是你的草稿，重新预览后再确认保存。</p>${button('rebase-draft','以最新版本重新预览草稿',`data-revision="${value.revision}"`)}`;
        });return;
      }
      if(action==='rebase-draft'){
        const form=target.closest('form');if(!form.reportValidity())return;
        target.disabled=true;await previewDraft(form,Number(target.dataset.revision));return;
      }
      if (action === 'cloud-tasks') {
        if (!window.TaskPublish?.open) throw new Error('待办连接组件尚未加载，请刷新页面后重试');
        await window.TaskPublish.open({journeyId: current.id});
        return;
      }
      if (action === 'assistant-brief') {
        if (!window.HomeAssistant?.openJourney) throw new Error('旅行简报组件尚未加载，请刷新后重试');
        await HomeAssistant.openJourney(); return;
      }
      if (action === 'cloud-calendar') {
        if (!window.CalendarPublish?.open) throw new Error('云日历组件尚未加载，请刷新页面后重试');
        await window.CalendarPublish.open(current.id);
      }
      if (action === 'destination') document.getElementById('journey-destinations').insertAdjacentHTML('beforeend', destinationRow({key: key('destination'), country: '', city: '',timeZone:draft.referenceTimezone||'Asia/Shanghai', arrival: document.querySelector('#journey-form [name="start"]').value, departure: document.querySelector('#journey-form [name="end"]').value}));
      if (action === 'remove-row') { target.closest('.journey-destination,.journey-review-row').remove(); dirty(); }
      if (action === 'sample') document.getElementById('journey-import-json').value = JSON.stringify(samplePlan(), null, 2);
      if (action === 'import') { await importPlan(target); return; }
      if (action === 'task') { document.getElementById('journey-checklist').insertAdjacentHTML('beforeend', taskRow({key: key('task'), title: '', owner: 'shared', due: shiftDate(draft.start, -7), note: ''})); dirty(); }
      if (action === 'purchase') { document.querySelector('#journey-purchases .journey-no-items')?.remove(); document.getElementById('journey-purchases').insertAdjacentHTML('beforeend', purchaseRow({key: key('purchase'), title: '', quantity: '1 件', budget: null, owner: 'shared'})); dirty(); }
      if (action === 'segment') { document.getElementById('journey-segments').insertAdjacentHTML('beforeend', segmentRow({key: key('segment'), title: '', start: draft.start, end: draft.start, location: ''})); dirty(); }
      if (action === 'back') { draft = readReview(); wizard(); }
      if (action === 'repreview') {
        const form=document.getElementById('journey-review-form');if(!form.reportValidity())return;
        target.disabled=true;await previewDraft(form);return;
      }
    } catch (err) { error(err); } finally { if (target.isConnected) target.disabled = false; }
  });

  document.addEventListener('change',event=>{
    const field=event.target,row=field.closest('.journey-v2-segment');
    if (field.matches('[data-journey-owner-filter]')) {
      const flow=execution;
      if (!flow || !executionActive(flow) || !flow.node.contains(field)) return;
      if (flow.actor!==executionActor(user) || flow.csrf!==csrf) { executionFailure(flow,flow.sequence,executionIdentityProblem(),''); return; }
      flow.filter=['all','mine','partner','shared'].includes(field.value)?field.value:'all'; keepExecutionFilter(flow); paintExecution(flow); return;
    }
    if(field.dataset.conflictKey){(resolutions[field.dataset.conflictKey]||={})[field.dataset.conflictField]=field.value;dirty();return;}
    if(!row)return;
    if(field.name==='bookingState'){const policy=row.querySelector('[name=datePolicy]');policy.disabled=field.value==='booked';if(policy.disabled)policy.value='fixed';}
    if(field.name.endsWith('.local')||field.name.endsWith('.timeZone')){const offset=row.querySelector(`[name="${field.name.split('.')[0]}.offsetMinutes"]`);if(offset)offset.value='';}
    if(field.name==='activityMode'){
      const old=readDetailRows(row.parentElement).find(value=>value.key===row.dataset.key);
      if(field.value==='date'){old.timeZone=old.start?.timeZone||draft.referenceTimezone;old.dateRange={startDate:old.start?.local?.slice(0,10)||draft.start,endDateExclusive:shiftDate(old.end?.local?.slice(0,10)||draft.start,1)};delete old.start;delete old.end;}
      else {const day=old.dateRange?.startDate||draft.start;old.start={local:day+'T10:00',timeZone:draft.referenceTimezone};old.end={local:day+'T11:00',timeZone:draft.referenceTimezone};delete old.dateRange;delete old.timeZone;}
      row.outerHTML=detailRow(old);
    }
    if(field.name==='changeKind'&&field.value!=='legacy_day'){
      const old=readDetailRows(row.parentElement).find(value=>value.key===row.dataset.key),converted=newSegment(field.value);
      Object.assign(converted,{key:old.key,title:old.title,location:old.location,note:old.note,bookingState:old.bookingState,datePolicy:field.value==='flight'||old.bookingState==='booked'?'fixed':old.datePolicy});
      if(converted.kind==='stay'){converted.checkInDate=old.start;converted.checkOutDate=shiftDate(old.end,1);}
      if(converted.kind==='activity'){converted.start.local=old.start+'T10:00';converted.end.local=old.start+'T11:00';}
      if(converted.kind==='flight'){converted.departure.local='';converted.arrival.local='';}
      row.outerHTML=detailRow(converted);
    }
    if(row.dataset.kind==='stay'){for(const prefix of ['checkIn','checkOut'])if(field.name==='timeZone'||field.name===prefix+'Date'||field.name===prefix+'Time'){const offset=row.querySelector(`[name="${prefix}OffsetMinutes"]`);if(offset)offset.value='';}}
    if(field.name==='checkInDate'||field.name==='checkOutDate')row.querySelector('.journey-stay-nights').textContent=Math.max(0,dayDiff(row.querySelector('[name=checkOutDate]').value,row.querySelector('[name=checkInDate]').value))+' 晚 · 退房当天不计住宿';
    refreshShiftOptions();dirty();
  });

  return {open, openDraft, create, samplePlan, shiftDate, dayDiff};
})();
