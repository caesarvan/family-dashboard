/* Local assets, no trackers. Shared APIs never return personal financial data. */
'use strict';
const $ = (q, el=document) => el.querySelector(q);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  plus:'M12 5v14M5 12h14', check:'m5 12 4 4L19 6', close:'m6 6 12 12M6 18 18 6', edit:'m15 5 4 4M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15v5Z',
  calendar:'M7 3v4m10-4v4M3 10h18M5 5h14a2 2 0 0 1 2 2v13H3V7a2 2 0 0 1 2-2Z',
  plane:'m22 2-8 20-3-9-9-3 20-8ZM11 13 22 2', pig:'M5 9C5 5 9 3 13 4c3 0 5 2 6 5h3v6h-3l-2 4h-3v-3H9v3H6l-2-5C1 14 1 10 4 10m10-2h.01M8 4 7 1l5 2',
  bag:'M5 7h14l1 14H4L5 7Zm3 0V5a4 4 0 0 1 8 0v2', list:'M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1',
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
  tv:'M3 5h18v13H3V5Zm5 17h8m-4-4v4', user:'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21v-2a8 8 0 0 1 16 0v2',
  lock:'M6 10h12v12H6V10Zm2 0V6a4 4 0 0 1 8 0v4m-4 5v3', upload:'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',
  wallet:'M3 5h17v15H3V5Zm0 0 13-3v3m-1 6h6v5h-6v-5', exit:'M9 3H3v18h6m5-14 5 5-5 5M8 12h11',
  coffee:'M4 9h12v6a6 6 0 0 1-12 0V9Zm12 1h3a3 3 0 0 1 0 6h-3M6 2v3m5-3v3M2 22h18',
  bottle:'M9 2h6v5l3 4v11H6V11l3-4V2Zm0 4h6M6 14h12', box:'m3 7 9-5 9 5-9 5-9-5Zm0 0v12l9 4 9-4V7M12 12v11',
};
const icon = (name, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.list}"/></svg>`;
const money = cents => '¥'+new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format((cents||0)/100);
const dateKey = (d=new Date()) => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
const displayDate = d => d ? new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(d.length===10?d+'T12:00:00+08:00':d)) : '';
const displayTime = d => new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'}).format(new Date(d));
const plusDays = n => dateKey(new Date(Date.now()+n*86400000));
const isDemo = location.pathname==='/demo';
let isTV = location.pathname==='/tv' || (isDemo && new URLSearchParams(location.search).get('tv')==='1');
let user=null, csrf='', data=null, online=true, lastFetch='', activeManager='', showDone=false;
let focus=localStorage.getItem('household_focus')||'member1';
let pollTimer=null, pairTimer=null, notifyTimer=null;
const canEdit=()=>!isDemo && user?.role==='member' && !isTV;
const person=id=>id==='shared'?'一起':(data?.people.find(p=>p.id===id)?.name||'成员');
const who=id=>id==='shared'?'共同':id===user?.id?'我':person(id);
const ownerOptions=selected=>[{id:'shared',name:'一起'},...(data?.people||[])].map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${esc(p.name)}</option>`).join('');
const empty=(title,description,action,label='添加',symbol='list')=>`<div class="empty">${icon(symbol)}<h3>${esc(title)}</h3><p>${esc(description)}</p>${canEdit()&&action?`<button class="btn small secondary" data-action="${action}">${icon('plus')}${label}</button>`:''}</div>`;
const addButton=(kind,label)=>canEdit()?`<button class="icon-button" title="${label}" aria-label="${label}" data-action="add" data-kind="${kind}">${icon('plus')}</button>`:'';
const editButton=(kind,item)=>canEdit()&&!item.sync?`<button class="icon-button row-edit" aria-label="编辑${esc(item.title)}" data-action="edit" data-kind="${kind}" data-id="${item.id}">${icon('edit')}</button>`:'';

function toast(message,bad=false){clearTimeout(notifyTimer);const t=$('#toast');t.textContent=message;t.className='show'+(bad?' bad':'');notifyTimer=setTimeout(()=>t.className='',4000)}
async function api(path,options={}){
  const headers={'Content-Type':'application/json',...(isTV?{'X-Display-Mode':'tv'}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...options.headers};
  let response;
  try{response=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',...options,headers})}catch(e){throw new Error('暂时无法连接服务器，请检查网络后重试')}
  let result;
  try { result=await response.json(); } catch (_) {const e=new Error('服务暂时不可用，请稍后重试');e.status=response.status;throw e;}
  if(!response.ok){const e=new Error(result.error||'操作失败，请重试');e.status=response.status;if(result.recoveryUrl==='/space/home')e.recoveryUrl=result.recoveryUrl;
    if(typeof result.code==='string'&&result.code.length<=80)e.code=result.code;
    if(typeof result.field==='string'&&result.field.length<=160)e.field=result.field;
    if(Array.isArray(result.choices)&&result.choices.length<=4)e.choices=result.choices.filter(c=>c&&Number.isInteger(c.offsetMinutes)&&Math.abs(c.offsetMinutes)<=840&&typeof c.instant==='string'&&c.instant.length<=40).map(c=>({offsetMinutes:c.offsetMinutes,instant:c.instant}));
    throw e}
  return result;
}
const write=(path,method,payload={})=>api(path,{method,body:JSON.stringify(payload)});

function demoData(){
  const today=dateKey(), stamp=t=>today+'T'+t+':00+08:00';
  return {people:[{id:'member1',name:'我'},{id:'member2',name:'伴侣'}],revision:1,
    events:[{id:'d1',title:'项目讨论',start:stamp('10:00'),end:stamp('11:00'),location:'办公室',owner:'member1',source:'Outlook'},
      {id:'d2',title:'运动时间',start:stamp('15:00'),end:stamp('16:00'),location:'健身房',owner:'member2',source:'Google'},
      {id:'d3',title:'一起吃晚饭',start:stamp('19:00'),end:stamp('20:30'),location:'街角餐厅',owner:'shared',source:'Apple'}],
    tasks:[{id:'t1',title:'预约周末保洁',due:plusDays(3),owner:'member1',done:false},
      {id:'t2',title:'确认旅行酒店',due:plusDays(5),owner:'member2',done:false,tripId:'trip-demo'},
      {id:'t3',title:'整理换季衣物',due:plusDays(6),owner:'shared',done:false},
      {id:'t4',title:'预订往返机票',owner:'shared',done:true,tripId:'trip-demo'},
      {id:'t5',title:'核对护照有效期',owner:'shared',done:true,tripId:'trip-demo'},
      {id:'t6',title:'确定旅行日期',owner:'shared',done:true,tripId:'trip-demo'},
      {id:'t7',title:'准备上网卡',owner:'shared',done:false,tripId:'trip-demo'},
      {id:'t8',title:'整理行李清单',owner:'shared',done:false,tripId:'trip-demo'}],
    shopping:[{id:'s1',title:'洗衣液',quantity:'1 瓶',done:false,owner:'shared'},{id:'s2',title:'厨房纸',quantity:'2 提',done:false,owner:'shared'},{id:'s3',title:'咖啡豆',quantity:'1 袋',done:false,owner:'shared'}],
    trips:[{id:'trip-demo',title:'京都 · 两个人的秋天',destination:'京都',start:plusDays(32),end:plusDays(36),budget:2000000,saved:1000000,paid:600000,note:''}],
    finance:{wallet:1840000,livingSpent:236000,livingBudget:620000,travelSaved:4500000,travelAnnualBudget:10400000,longterm:12800000,reserveTarget:1000000,upcomingPayments:0,contributionPercent:50,confirmedAt:new Date().toISOString(),revision:1},
    integrations:{calendar:'演示日程',finance:'演示数据'}};
}

function renderLogin(){
  document.body.className='';
  $('#app').innerHTML=`<main class="auth-screen"><section class="auth-story"><img class="brand-logo" src="/static/home.svg" alt=""><div class="eyebrow">OUR EVERYDAY, TOGETHER</div><h1>把日子放在一起。</h1><p>今天的安排，想去的地方，还有那些一起完成的小事。<br>属于两个人的家庭看板。</p><div class="auth-tags"><span class="pill">日程</span><span class="pill">家庭财务</span><span class="pill">共同待办</span><span class="pill">购物与旅行</span></div></section><section class="auth-card"><h2>欢迎回家</h2><p>登录后查看和维护你们的共同生活。</p><form id="login-form"><label class="field"><span>家庭成员</span><select name="username"><option value="member1">成员一 · member1</option><option value="member2">成员二 · member2</option></select></label><label class="field"><span>密码</span><input type="password" name="password" autocomplete="current-password" required placeholder="输入你的登录密码"></label><div class="error" role="alert"></div><button class="btn" type="submit">进入家庭看板</button></form><div id="account-login" class="account-login"><p class="help">正在读取账户登录状态…</p></div><div class="auth-links"><a href="/demo?tv=1">看看演示</a><a href="/tv">连接电视</a></div></section></main>`;
  $('#login-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,b=$('button',form);b.disabled=true;try{await write('/login','POST',Object.fromEntries(new FormData(form)));await boot()}catch(err){$('.error',form).textContent=err.message}finally{b.disabled=false}};
  renderAccountLogin();
}

async function boot(){
  clearInterval(pollTimer);clearInterval(pairTimer);
  if(isDemo){user={id:'member1',role:'demo'};data=demoData();renderBoard();return}
  try{
    const me=await api('/me');
    if(JSON.stringify([user?.role,user?.householdId,user?.id,user?.auth_version,csrf])!==JSON.stringify([me.user?.role,me.user?.householdId,me.user?.id,me.user?.auth_version,me.csrf||''])){window.JourneyMap?.notifyIdentityChanged();window.HouseholdMedia?.notifyIdentityChanged();window.MediaTV?.notifyIdentityChanged();window.InventoryUI?.notifyIdentityChanged();}
    user=me.user;csrf=me.csrf||'';
    if(!user){if(isTV){await startPair()}else renderLogin();showAccountAuthResult();return}
    if(user.role==='tv'){isTV=true;focus=user.focus||'member1'}else if(!localStorage.getItem('household_focus'))focus=user.id;
    await refresh(true);pollTimer=setInterval(()=>refresh(),10000);showAccountAuthResult();
  }catch(e){$('#app').innerHTML=`<main class="pair-screen"><h1>暂时无法打开看板</h1><p>${esc(e.message)}</p><button class="btn" data-action="reload">重试</button>${e.recoveryUrl?'<a class="btn secondary" href="/space/home">返回家庭入口</a>':''}</main>`}
}
async function refresh(force=false){
  if(document.hidden&&!force)return;
  try{const next=await api('/state');const changed=force||!data||next.revision!==data.revision;data=next;online=true;lastFetch=displayTime(new Date());if(changed)renderBoard();else {updateFooter();window.JourneyMap?.notifyStateChanged();window.HouseholdMedia?.notifyStateChanged();window.InventoryUI?.notifyStateChanged()}}
  catch(e){online=false;if(e.status===401){await boot();return}updateFooter();if(force)throw e}
}
function clockMarkup(){const d=new Date();return `<strong>${displayTime(d)}</strong><span>${new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(d)}</span>`}
function updateFooter(){
  // Freshness changes with time even when no entity revision changed. Preserve
  // the current workspace/editor and refresh its small read-only indicators.
  window.SyncHealth?.refreshIndicators();
  const c=$('#connection');if(!c)return;
  const s=data?.sync;
  if(window.SyncHealth){
    const health=s?.health;
    c.className='connection'+(!online||health?.state!=='current'?' offline':'');
    const sync=window.SyncHealth.summaryText(health);
    c.textContent=isDemo?'概念演示 · 所有金额和行程均为示例':online?`看板已连接 · ${lastFetch} 更新 · ${sync}`:'连接中断 · 正在显示上次获取的数据';
    return;
  }
  c.className='connection offline';
  c.textContent=isDemo?'概念演示 · 所有金额和行程均为示例':online?`看板已连接 · ${lastFetch} 更新 · 同步状态待核对`:'连接中断 · 正在显示上次获取的数据';
}

function renderBoard(){
  if(!data)return;
  if(user?.role==='tv' && data.display?.focus)focus=data.display.focus;
  document.body.className=(isTV?'tv ':'')+(isDemo?'demo-view':'');
  const selector=user?.role==='tv'?`<span class="pill">侧重 ${esc(person(focus))}</span>`:`<select id="focus" class="focus-select" aria-label="日程优先显示"><option value="member1" ${focus==='member1'?'selected':''}>侧重 ${esc(person('member1'))}</option><option value="member2" ${focus==='member2'?'selected':''}>侧重 ${esc(person('member2'))}</option></select>`;
  $('#app').innerHTML=`<div class="shell"><header class="topbar"><div class="brand"><img class="brand-logo" src="/static/home.svg" alt=""><div><h1>家庭看板</h1><small>OUR EVERYDAY, TOGETHER</small></div></div><nav class="nav" aria-label="主要功能"><button class="active" data-action="home">今天</button><button data-action="manage" data-kind="events">日程</button><button data-action="manage" data-kind="tasks">待办</button><button data-action="manage" data-kind="shopping">购物</button><button data-action="manage" data-kind="trips">旅行</button><button data-action="settings">设置</button></nav><div class="header-tools">${selector}${isDemo?'<span class="pill demo">概念原型 · 演示数据</span>':isTV?'<span class="pill">电视 · 只读</span>':''}<div class="clock" id="clock">${clockMarkup()}</div></div></header><main class="board">${calendarCard()}${financeCard()}${tasksCard()}${shoppingCard()}${travelCard()}</main><footer class="board-footer"><span id="connection" class="connection"></span><span>${isDemo?'<a href="/">登录并开始使用</a>':isTV?'在手机或电脑上编辑，电视自动更新':'日历与清单：设置中绑定账户 · 家庭财务：手动核对'}</span></footer></div>`;
  const f=$('#focus');if(f)f.onchange=()=>{focus=f.value;localStorage.setItem('household_focus',focus);renderBoard()};
  updateFooter();
}
function eventsToday(){const today=dateKey();return data.events.filter(e=>e.start.slice(0,10)<=today&&(e.allDay?e.end.slice(0,10)>today:e.end.slice(0,10)>=today)).sort((a,b)=>a.start.localeCompare(b.start)||(a.owner===focus?-1:1))}
function eventRow(e,nextId,manager=false){const passed=new Date(e.end)<new Date();return `<div class="event ${e.id===nextId?'next':''} ${passed?'past':''}"><time>${manager?`${displayDate(e.start)}<br>`:''}${e.allDay?'全天':displayTime(e.start)}</time><div class="track"><i class="dot ${e.owner}"></i></div><div class="copy"><span class="event-title" title="${esc(e.title)}">${esc(e.title)}${e.id===nextId?'<span class="next-tag">下一项</span>':''}</span><div class="event-sub" title="${esc(e.location)}">${esc(who(e.owner))}${e.location?' · '+esc(e.location):''}${manager?' · '+esc(e.source||'手动'):''}</div></div>${manager?editButton('events',e):''}</div>`}
function calendarCard(){return CalendarViews.renderCard()}
function walletCard(){const f=data.finance,known=!!f.confirmedAt,progress=f.livingBudget?Math.min(100,f.livingSpent/f.livingBudget*100):0,remaining=f.livingBudget-f.livingSpent;return `<section class="card finance-card"><div class="card-heading"><h2>家庭财务</h2><div class="card-actions"><span class="sub">共同资金</span>${canEdit()?`<button class="icon-button" aria-label="核对家庭财务" data-action="finance">${icon('edit')}</button>`:''}</div></div><div class="wallet"><div><div class="wallet-label">荷包余额</div><div class="wallet-amount">${known?`<small>¥</small>${money(f.wallet).slice(1)}`:'— —'}</div></div><div class="reserve">周转目标<strong>${money(f.reserveTarget)}</strong></div></div><div class="meter-labels"><span>本月日常支出</span><strong>${known?money(f.livingSpent):'待核对'} / ${money(f.livingBudget)}</strong></div><div class="meter ${remaining<0?'over':''}"><span style="width:${known?progress:0}%"></span></div><div class="meter-note">${known?(remaining>=0?'日常预算剩余 '+money(remaining):'已超出预算 '+money(-remaining)):'先核对余额与本月支出，再显示预算进度'}</div><div class="finance-mini"><div class="metric">${icon('plane')}<div><small>旅行准备金</small><strong>${known?money(f.travelSaved):'待核对'}</strong></div></div><div class="metric">${icon('pig')}<div><small>长期共同储蓄</small><strong>${known?money(f.longterm):'待核对'}</strong></div></div></div><div class="finance-status"><span>${isDemo?'演示数据':known?'手动核对 · '+displayDate(f.confirmedAt)+' '+displayTime(f.confirmedAt):'共同资金尚未核对'}</span><span>税后收入 ${f.contributionPercent}% 共同出资</span></div></section>`}
function financeCard(){return FinanceBaseline.decorateCard(walletCard())}
function sortedTasks(){return [...data.tasks].sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999')||(a.owner===focus?-1:1))}
function checkControl(kind,item){return canEdit()&&!item.sync?.readOnly?`<button class="check ${item.done?'done':''}" aria-label="${item.done?'恢复':'完成'}${esc(item.title)}" aria-pressed="${item.done}" data-action="toggle" data-kind="${kind}" data-id="${item.id}">${item.done?icon('check'):''}</button>`:`<span class="check ${item.done?'done':''}" ${item.sync?.readOnly?'title="此来源仅可查看，请在原应用中修改"':''}>${item.done?icon('check'):''}</span>`}
function listRow(kind,item,manager=false){
  if(kind==='shopping')return ShoppingUI.renderRow(item,manager);
  const isShopping=kind==='shopping',late=!item.done&&item.due&&item.due<dateKey();
  const symbol=/咖啡/.test(item.title)?'coffee':/液|水|洗/.test(item.title)?'bottle':'box';
  const source=item.sync?' · '+esc(accountProviderName(item.sync.provider))+(item.sync.readOnly?' · 只读':''):'';
  return `<div class="list-row ${item.done?'completed':''}">${isShopping&&!manager?`<span class="shopping-mark">${icon(symbol)}</span>`:checkControl(kind,item)}<div class="copy"><strong title="${esc(item.title)}">${esc(item.title)}</strong><small>${isShopping?esc(item.quantity)+(item.owner!=='shared'?' · '+esc(person(item.owner)):''):esc(who(item.owner))+(item.due?` · <span class="${late?'amber':''}">${late?'已逾期 · ':''}${displayDate(item.due)}</span>`:'')}${source}${manager&&item.note?' · '+esc(item.note):''}</small></div>${isShopping&&!manager&&canEdit()?checkControl(kind,item):''}${editButton(kind,item)}</div>`;
}
function tasksCard(){const tasks=sortedTasks().filter(t=>!t.done);return `<section class="card tasks-card"><div class="card-heading"><h2>共同待办</h2><div class="card-actions"><span class="sub">${tasks.length} 项</span>${addButton('tasks','添加待办')}</div></div><div class="compact-list">${tasks.length?tasks.slice(0,3).map(t=>listRow('tasks',t)).join(''):empty('一起，慢慢完成','把需要两个人记住的事放在这里。','add-task','添加待办')}</div>${tasks.length>3?canEdit()?`<button class="list-more" data-action="manage" data-kind="tasks">还有 ${tasks.length-3} 项待办 →</button>`:`<span class="list-more muted">还有 ${tasks.length-3} 项，手机上查看</span>`:''}</section>`}
function shoppingCard(){return ShoppingUI.renderCard()}
function travelCard(){const trip=[...data.trips].filter(t=>t.end>=dateKey()).sort((a,b)=>a.start.localeCompare(b.start))[0];const tasks=trip?data.tasks.filter(t=>t.tripId===trip.id):[],done=tasks.filter(t=>t.done).length,pending=tasks.find(t=>!t.done);let days=trip?Math.ceil((new Date(trip.start+'T00:00:00+08:00')-new Date(dateKey()+'T00:00:00+08:00'))/86400000):0;return `<section class="card travel-card"><div class="travel-bg"></div><div class="card-heading"><h2>下一趟旅行</h2><div class="card-actions">${trip&&canEdit()?`<button class="icon-button" aria-label="查看旅行计划" data-action="manage" data-kind="trips">${icon('list')}</button>`:addButton('trips','添加旅行')}</div></div>${trip?`<h3 class="travel-name">${esc(trip.title)}</h3><div class="travel-dates">${displayDate(trip.start)}—${displayDate(trip.end)}${trip.destination?' · '+esc(trip.destination):''}</div><div class="countdown">${icon('calendar')}${days>0?`<span>还有</span><strong>${days}</strong><span>天</span>`:'<strong>旅途中</strong>'}</div><div class="travel-progress"><div class="meter-labels"><span>准备进度 ${done} / ${tasks.length}</span></div><div class="meter"><span style="width:${tasks.length?done/tasks.length*100:0}%"></span></div></div><div class="trip-next">${pending?'待办：'+esc(pending.title):tasks.length?'准备就绪，期待出发':'添加准备事项，让期待一步步落地'}</div>`:empty('下一站，去哪里？','计划一次周末出走，或一段期待已久的旅程。','add-trip','计划旅行','plane')}</section>`}

function openModal(title,content,wide=false){const d=$('#dialog');d.className=wide?'wide':'';d.innerHTML=`<header class="dialog-header"><h2 id="dialog-title">${esc(title)}</h2><button class="icon-button" aria-label="关闭" data-action="close">${icon('close')}</button></header><div class="dialog-content">${content}</div>`;if(!d.open)d.showModal();}
function closeModal(){activeManager='';$('#dialog').close()}
const field=(label,name,value='',type='text',extra='')=>`<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
const selectField=(label,name,options)=>`<label class="field"><span>${label}</span><select name="${name}">${options}</select></label>`;
const noteField=(value='',label='备注')=>`<label class="field full"><span>${label}</span><textarea name="note" maxlength="2000">${esc(value)}</textarea></label>`;
const formFooter=(kind,item)=>`<div class="error" role="alert"></div><div class="dialog-footer">${item?`<button type="button" class="btn danger" data-action="delete" data-kind="${kind}" data-id="${item.id}">删除</button>`:''}<button type="button" class="btn secondary" data-action="close">取消</button><button class="btn" type="submit">保存</button></div>`;
function bindForm(callback){const form=$('#dialog form');form.onsubmit=async e=>{e.preventDefault();const button=$('button[type=submit]',form);button.disabled=true;$('.error',form).textContent='';try{await callback(Object.fromEntries(new FormData(form)),form);closeModal();await refresh(true);toast('已保存，两块看板会自动更新')}catch(err){$('.error',form).textContent=err.message;if(err.status===409)await refresh()}finally{button.disabled=false}}}
function editItem(kind,id='',extras={}){
  if(kind==='trips'&&!id){
    if(isTV||(!canEdit()&&!isDemo))return;
    if(typeof window.JourneyUI?.create!=='function'){toast('旅行规划组件尚未加载，请刷新后重试；没有创建旅行。',true);return}
    return window.JourneyUI.create();
  }
  if(kind==='shopping')return ShoppingUI.openEditor(id,extras);
  if(!canEdit())return;activeManager='';const item=data[kind].find(i=>i.id===id),v=item||extras;
  if(item?.sync){toast('同步内容请在原应用修改；可在看板勾选完成或恢复。');return}
  if(kind==='events'&&item?.travelTiming&&item?.journeyId&&window.JourneyUI){JourneyUI.open(item.journeyId,{segmentKey:item.travelTiming.segmentKey});return}
  const taskSources=(data.sync?.taskSources||[]).filter(source=>source.writable!==false);
  const useCloudTask=kind==='tasks'&&!item&&taskSources.length>0;
  const defaultTaskSource=v.tripId?'':(data.sync?.primaryTaskSource?.id||'');
  const label={tasks:'待办',shopping:'购物物品',events:'安排',trips:'旅行'}[kind];let fields=field('名称','title',v.title||'','text','required maxlength="100"');
  if(useCloudTask)fields+=selectField('保存到','sourceId',`<option value="" ${defaultTaskSource?'':'selected'}>家庭看板本地待办</option>`+taskSources.map(source=>`<option value="${esc(source.id)}" ${source.id===defaultTaskSource?'selected':''}>${esc(accountProviderName(source.provider))} · ${esc(source.name)}${source.id===data.sync?.primaryTaskSource?.id?' · 主清单':''}</option>`).join(''));
  if(kind==='tasks'||kind==='shopping'){
    fields+=`<div ${useCloudTask?'data-local-task-field':''}>`+selectField('负责人','owner',ownerOptions(v.owner||'shared'))+'</div>';
    if(kind==='shopping')fields+=field('数量','quantity',v.quantity||'1 件','text','required maxlength="30"');
    else{fields+=field('截止日期（可选）','due',v.due||'','date');fields+=`<div ${useCloudTask?'data-local-task-field':''}>`+selectField('关联旅行（可选）','tripId','<option value="">日常待办</option>'+data.trips.map(t=>`<option value="${t.id}" ${v.tripId===t.id?'selected':''}>${esc(t.title)}</option>`).join(''))+'</div>'}
    fields+=noteField(v.note);fields+=`<label class="label-check full" ${useCloudTask?'data-local-task-field':''}><input type="checkbox" name="done" ${v.done?'checked':''}>${kind==='shopping'?'已买到':'已完成'}</label>`;
    if(useCloudTask)fields+='<p class="help full" id="task-source-help"></p>';
  }else if(kind==='events'){
    fields+=selectField('所属日历','owner',ownerOptions(v.owner||focus));
    fields+=field('开始时间（北京时间）','start',(v.start||dateKey()+'T19:00').slice(0,16),'datetime-local','required');
    fields+=field('结束时间（北京时间）','end',(v.end||dateKey()+'T20:00').slice(0,16),'datetime-local','required');
    fields+=field('地点','location',v.location||'','text','maxlength="200"');
    fields+=`<label class="label-check"><input type="checkbox" name="allDay" ${v.allDay?'checked':''}>全天安排（结束日期不包含当天）</label>`;
  }else{
    fields+=field('目的地','destination',v.destination||'','text','maxlength="80"');
    fields+=field('出发日期','start',v.start||plusDays(30),'date','required');fields+=field('返程日期','end',v.end||plusDays(34),'date','required');
    fields+=field('两人总预算（元）','budget',(v.budget||0)/100,'number','min="0" step="0.01" required');
    fields+=field('已预留、尚未支付（元）','saved',(v.saved||0)/100,'number','min="0" step="0.01" required');
    fields+=field('已经付款（元）','paid',(v.paid||0)/100,'number','min="0" step="0.01" required');
    fields+=noteField(v.note,'行程与预订备注（酒店、航班、安排等）');
  }
  openModal((item?'编辑':'添加')+label,`<form><div class="fields">${fields}</div>${formFooter(kind,item)}</form>`);
  if(useCloudTask){const form=$('#dialog form'),selector=form.elements.sourceId;const update=()=>{const cloud=!!selector.value;form.querySelectorAll('[data-local-task-field]').forEach(el=>el.hidden=cloud);form.elements.note.maxLength=cloud?500:2000;$('#task-source-help').textContent=cloud?'保存成功后会写入所选清单，并与伴侣共享。标题、备注等后续修改请在原应用中完成。':'保存为看板本地待办，可关联旅行；不会自动复制到云端清单。'};selector.onchange=update;update()}
  bindForm(async(f,form)=>{if(kind==='tasks'||kind==='shopping')f.done=form.elements.done.checked;if(kind==='tasks'&&!item){f.sourceId=useCloudTask?form.elements.sourceId.value:'';if(f.sourceId){f.owner='shared';f.tripId='';f.done=false}}if(kind==='events'){f.allDay=form.elements.allDay.checked;f.start+=':00+08:00';f.end+=':00+08:00';if(item){f.source=item.source;f.imported=item.imported}}if(kind==='trips')for(const k of ['budget','saved','paid'])f[k]=toCents(f[k]);if(item)f.revision=item.revision;await write('/items/'+kind+(item?'/'+id:''),item?'PATCH':'POST',f)});
}
function toCents(v){const n=Number(v);if(!Number.isFinite(n)||n<0||n>1000000000)throw new Error('请输入有效的非负金额');return Math.round(n*100)}

function manage(kind){
  if(kind==='events')return CalendarViews.openManager();
  if(kind==='shopping')return ShoppingUI.openManager();
  activeManager=kind;let list='';const titles={events:'全部日程',tasks:'共同待办',shopping:'购物清单',trips:'旅行计划'};
  if(kind==='events'){
    const events=[...data.events].filter(e=>showDone||e.end.slice(0,10)>=dateKey()).sort((a,b)=>a.start.localeCompare(b.start));
    list=events.map(e=>eventRow(e,null,true)).join('')||'<p class="help">还没有安排。在设置中绑定 Microsoft / Google 账户，选择日历后自动同步。</p>';
  }else if(kind==='trips'){
    list=[...data.trips].sort((a,b)=>a.start.localeCompare(b.start)).map(t=>{const tasks=data.tasks.filter(i=>i.tripId===t.id);return `<article class="trip-item"><header><h3>${esc(t.title)}</h3>${editButton('trips',t)}</header><p>${esc(t.destination)} · ${displayDate(t.start)}—${displayDate(t.end)}</p><div class="trip-stats"><span>总预算 <strong>${money(t.budget)}</strong></span><span>已付 <strong>${money(t.paid)}</strong></span><span>预留未付 <strong>${money(t.saved)}</strong></span><span>${t.paid>t.budget?'已付款超预算':t.paid+t.saved>t.budget?'已付 + 预留超额':'还需准备'} <strong>${money(t.paid>t.budget?t.paid-t.budget:Math.abs(t.budget-t.paid-t.saved))}</strong></span></div>${t.note?`<p class="trip-note">${esc(t.note)}</p>`:''}<div class="compact-list">${tasks.map(i=>listRow('tasks',i,true)).join('')}</div><button class="btn small secondary" data-action="trip-task" data-id="${t.id}">${icon('plus')}添加准备事项</button></article>`}).join('')||'<p class="help">还没有旅行计划，先写下下一次想去的地方。</p>';
  }else{const items=(kind==='tasks'?sortedTasks():data.shopping).filter(i=>showDone||!i.done);list=items.map(i=>listRow(kind,i,true)).join('')||'<p class="help">清单是空的，轻松一点。</p>'}
  openModal(titles[kind],`<div class="manager-toolbar">${kind!=='trips'?`<label class="label-check"><input id="show-done" type="checkbox" ${showDone?'checked':''}>${kind==='events'?'包含过去的日程':'显示已完成'}</label>`:'<span class="help">准备资金与准备事项，一起安排。</span>'}<button class="btn small" data-action="add" data-kind="${kind}">${icon('plus')}添加</button></div>${kind==='events'?'<p class="help">时间统一以北京时间展示。<button class="quiet" data-action="accounts">绑定日历账户 →</button><button class="quiet" data-action="import">文件导入（备用）</button></p>':''}<div class="manager-list">${list}</div>`,true);
  const c=$('#show-done');if(c)c.onchange=()=>{showDone=c.checked;manage(kind)};
}
function financeForm(){
  const f=data.finance,fields=[['荷包当前可支付余额','wallet'],['本月日常已支出','livingSpent'],['本月日常预算','livingBudget'],['周转金目标','reserveTarget'],['近期大额待付款（周转金之外）','upcomingPayments'],['全部旅行准备金（预留未支付）','travelSaved'],['年度旅行预算','travelAnnualBudget'],['长期共同储蓄 / 理财现值','longterm']];
  openModal('核对家庭财务',`<div class="info-box">这是手动核对快照，不会连接支付宝或执行转账。旅行准备金与长期储蓄按用途分别填写，不重复分配；转去理财仍属于家庭资产。</div><form><div class="fields">${fields.map(([label,k])=>field(label+'（元）',k,f[k]/100,'number','required min="0" step="0.01"')).join('')}${field('税后到账收入转入比例（%）','contributionPercent',f.contributionPercent,'number','required min="0" max="100" step="1"')}${noteField(f.note,'核对备注 / 理财持有人与可取用日期')}</div><p class="help">日常预算建议上限 ¥6,200；旅行年均预算基线 ¥104,000。旅行临近付款时需增加现金预留。默认金额可以按实际情况调整。</p>${formFooter('',null)}</form>`,true);
  bindForm(async v=>{const p={revision:f.revision,note:v.note,contributionPercent:Number(v.contributionPercent)};for(const [,k] of fields)p[k]=toCents(v[k]);await write('/finance','PUT',p)});
}
async function personalForm(){
  const f=await api('/private-finance');
  openModal('我的个人财务',`<div class="info-box">仅当前登录的成员可查看。不会出现在伴侣账户或任何电视上。</div><form><div class="fields">${field('月份','month',f.month,'month','required')}${field('税后到账收入（元）','income',f.income/100,'number','min="0" step="0.01" required')}${field('个人已支出（元）','spent',f.spent/100,'number','min="0" step="0.01" required')}${field('个人预算（元）','budget',f.budget/100,'number','min="0" step="0.01" required')}</div><p class="help">第一版保存最近一次月度快照；完整个人账本仍保留在你们各自的数据源中。</p>${formFooter('',null)}</form>`);
  bindForm(v=>write('/private-finance','PUT',{month:v.month,income:toCents(v.income),spent:toCents(v.spent),budget:toCents(v.budget),revision:f.revision}));
}
function settings(){
  const choices=[['accounts','calendar','账户与自动同步','Microsoft / Google 日历与清单'],['profile','user','我的家庭账户','显示名称与密码'],['personal','lock','个人月度收支','仅本人可见'],['wealth-private','wallet','我的资产明细','已导入的资产、负债与收入基础'],['finance','wallet','家庭财务','手动核对公共资金'],['pair','tv','连接电视','输入电视显示的配对码'],['devices','settings','已连接电视','查看或撤销只读设备']];
  openModal('家庭设置',`<div class="settings-grid">${choices.map(([action,symbol,title,sub])=>`<button class="setting-button" data-action="${action}">${icon(symbol)}<span>${title}<small>${sub}</small></span></button>`).join('')}</div><p class="help" style="margin-top:24px">你和伴侣分别绑定各自的账户，并选择共享到看板的日历与清单。家庭财务继续手动核对，荷包同步后续接入。</p><div class="dialog-footer"><a class="btn secondary" href="/demo?tv=1">演示预览</a><button class="btn secondary" data-action="logout">退出登录</button></div>`);
}
function profileForm(){openModal('我的账户',`<form>${field('显示名称','name',user.name,'text','required maxlength="20"')}<p class="help">修改密码时填写以下两项。仅更新名称时留空。</p>${field('当前密码','currentPassword','','password','autocomplete="current-password"')}${field('新密码（至少 12 个字符）','password','','password','autocomplete="new-password" minlength="12" maxlength="128"')}${formFooter('',null)}</form>`);bindForm(async v=>{await write('/profile','POST',v);const me=await api('/me');user=me.user;csrf=me.csrf})}
function importForm(){openModal('导入日历文件',`<div class="info-box">在对应日历中导出 .ics 文件后导入。导入近 30 天至未来一年，展开重复日程；同一成员的相同 UID 与开始时间会更新合并。导入不是实时同步，源日历删除的安排需手动移除。</div><form>${selectField('日历来源','source',['Apple','Google','Outlook'].map(s=>`<option>${s}</option>`).join(''))}${selectField('日程属于','owner',ownerOptions(focus))}<label class="field"><span>选择 .ics 文件（最大 500 KB）</span><input type="file" name="file" accept=".ics,text/calendar" required></label><p class="help">完整标题和地点会共享给双方和已配对电视；导入前请确认文件范围。</p>${formFooter('',null)}</form>`);bindForm(async(v,form)=>{const file=form.elements.file.files[0];if(!file||file.size>500000)throw new Error('请选择不超过 500 KB 的 .ics 文件');const result=await write('/calendar/import','POST',{source:v.source,owner:v.owner,ics:await file.text()});toast(result.note)})}
async function pairForm(){
  if(!canEdit())return;
  const owner={id:user.id,household:user.householdId||'default',csrf},matches=(u,t)=>u?.role==='member'&&u.id===owner.id&&(u.householdId||'default')===owner.household&&t===owner.csrf;
  openModal('连接电视','<section class="tv-pair-flow"><p class="help">正在核对登录状态…</p></section>');
  const node=$('#dialog .tv-pair-flow'),owns=()=>node.isConnected&&$('#dialog').open&&$('#dialog .dialog-content')?.contains(node);
  let epoch=0;
  const neutral=()=>{if(owns()){++epoch;node.innerHTML='<p class="help" role="alert">无法确认当前家庭的登录状态。请刷新页面后重新连接电视。</p><a class="btn secondary" href="/">刷新页面</a>'}};
  const verify=async active=>{
    if(!active())return false;
    if(!canEdit()||!matches(user,csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e}
    const identity=await api('/me');
    if(!active())return false;
    if(!canEdit()||!matches(user,csrf)||!matches(identity.user,identity.csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e}
    return true;
  };
  try{
    if(!await verify(owns))return;
    // Do not reuse member names from a different household while boot is refreshing.
    const people=data?.household?.id===owner.household?data.people:[{id:'member1',name:'成员一'},{id:'member2',name:'成员二'}];
    const options=[{id:'shared',name:'一起'},...(people||[])].map(p=>`<option value="${esc(p.id)}" ${p.id===focus?'selected':''}>${esc(p.name)}</option>`).join('');
    node.innerHTML=`<p class="help">先在电视浏览器打开 <strong>${esc(location.origin)}/tv</strong>，再在下方输入电视显示的 8 位配对码。配对码 10 分钟有效，成功后电视会自动进入只读看板；访问可随时撤销。</p><form id="tv-pair-form">${field('电视配对码','code','','text','required minlength="8" maxlength="10" autocomplete="off" autocapitalize="characters" placeholder="例如 A2B3 C4D5"')}${field('电视名称','name','客厅电视','text','required maxlength="30"')}${selectField('优先显示谁的日程','focus',options)}${selectField('电视日程视图','calendarView',viewOptions('today'))}${formFooter('',null)}</form>`;
    const form=$('form',node),button=$('button[type=submit]',form);button.textContent='确认连接';
    form.onsubmit=async event=>{
      event.preventDefault();
      const ticket=++epoch,payload=Object.fromEntries(new FormData(form)),snapshot=JSON.stringify(payload);
      const active=()=>owns()&&epoch===ticket&&form.isConnected&&node.contains(form)&&JSON.stringify(Object.fromEntries(new FormData(form)))===snapshot;
      button.disabled=true;button._tvPairJob=ticket;$('.error',form).textContent='';let sent=false;
      try{
        if(!await verify(active))return;
        sent=true;await api('/pair/approve',{method:'POST',body:JSON.stringify(payload),headers:{'X-CSRF-Token':owner.csrf}});
        if(!active()||!await verify(active))return;
        await devicesModal({owner,notice:'电视已连接。电视会自动显示只读看板。'});
      }catch(error){
        if(!active())return;
        if(error.identityChanged||error.status===401){neutral();return}
        try{if(!await verify(active))return}catch(_){if(active())neutral();return}
        if(active())$('.error',form).textContent=(error.message||'连接失败，请重试。')+(sent&&(!error.status||error.status>=500)?' 请求可能已完成，请先返回电视列表核对；关闭窗口不会取消已经发送的请求。':'');
      }finally{if(button.isConnected&&button._tvPairJob===ticket)button.disabled=false}
    };
  }catch(error){
    if(!owns())return;
    if(error.identityChanged||error.status===401){neutral();return}
    node.innerHTML='<p class="help" role="alert">暂时无法确认登录状态，请重试。</p><button class="btn secondary" data-action="pair">重试连接</button>';
  }
}
const viewOptions=selected=>[['today','今日'],['week','本周'],['around','前后 3 天']].map(([v,label])=>`<option value="${v}" ${v===selected?'selected':''}>${label}</option>`).join('');
async function devicesModal({owner:previousOwner,notice=''}={}){
  if(!canEdit())return;
  const owner=previousOwner||{id:user.id,household:user.householdId||'default',csrf};
  const matches=(u,t)=>u?.role==='member'&&u.id===owner.id&&(u.householdId||'default')===owner.household&&t===owner.csrf;
  if(!matches(user,csrf))return;
  openModal('已连接的电视','<section class="tv-devices-flow"><p class="help">正在读取当前家庭的电视…</p></section>');
  const node=$('#dialog .tv-devices-flow'),active=()=>node.isConnected&&$('#dialog').open&&$('#dialog .dialog-content')?.contains(node);
  const neutral=()=>{if(active())node.innerHTML='<p class="help" role="alert">无法确认当前家庭的登录状态。请刷新页面后查看电视列表。</p><a class="btn secondary" href="/">刷新页面</a>'};
  const verify=async()=>{
    if(!active())return false;
    if(!canEdit()||!matches(user,csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e}
    const identity=await api('/me');
    if(!active())return false;
    if(!canEdit()||!matches(user,csrf)||!matches(identity.user,identity.csrf)){const e=new Error('登录状态已变化');e.identityChanged=true;throw e}
    return true;
  };
  try{
    if(!await verify())return;
    const devices=await api('/devices');
    if(!active()||!await verify())return;
    const label=id=>id==='shared'?'一起':data?.household?.id===owner.household?person(id):id===owner.id?'我':'另一位成员';
    node.innerHTML=(notice?`<p class="help" role="status">${esc(notice)}</p>`:'')+(devices.length?'<p class="help">在这里选择各台电视的侧重成员和日程视图，电视约 10 秒内自动更新。</p>'+devices.map(d=>`<div class="device-row"><div>${esc(d.name)}<small>侧重：${esc(label(d.focus))} · ${{today:'今日',week:'本周',around:'前后 3 天'}[d.calendarView]||'今日'} · 只读</small></div><div class="device-actions"><button class="btn small secondary" data-action="device-edit" data-id="${esc(d.id)}">显示设置</button><button class="btn small secondary" data-action="revoke" data-id="${esc(d.id)}">撤销访问</button></div></div>`).join(''):'<div class="empty">'+icon('tv')+'<h3>连接第一块电视</h3><p>在电视浏览器打开 /tv 页面，取得配对码后，点击下方按钮在手机或电脑上输入。</p></div>')+`<div class="dialog-footer"><button class="btn" data-action="pair">${icon('plus')}${devices.length?'再连接一块电视':'连接第一块电视'}</button></div>`;
  }catch(error){
    if(!active())return;
    if(error.identityChanged||error.status===401){neutral();return}
    try{if(!await verify())return}catch(_){if(active())neutral();return}
    if(active())node.innerHTML='<p class="help" role="alert">暂时无法读取电视列表，请重试。</p><button class="btn secondary" data-action="devices">重试读取</button>';
  }
}
async function deviceForm(id){return window.TVDisplay.openDevice(id)}
async function startPair(){
  $('#app').innerHTML='<main class="pair-screen"><h1>正在准备电视配对…</h1></main>';
  const p=await write('/pair/start','POST');const expiresAt=Date.now()+p.expiresIn*1000;
  $('#app').innerHTML=`<main class="pair-screen"><img class="brand-logo" src="/static/home.svg" alt=""><h1>把家庭看板放上大屏</h1><p>手机或电脑登录后，打开「设置 → 连接电视」</p><div class="pair-code">${esc(p.code.slice(0,4))} ${esc(p.code.slice(4))}</div><p>访问地址：${esc(location.origin)}</p><span class="pill" id="pair-status">配对码 10 分钟内有效 · 电视仅可查看公共信息</span><a href="/demo?tv=1">先看演示效果</a></main>`;
  pairTimer=setInterval(async()=>{if(Date.now()>expiresAt){clearInterval(pairTimer);$('#pair-status').innerHTML='配对码已过期，请刷新页面重试';return}try{const r=await write('/pair/poll','POST',{secret:p.secret});if(r.approved){clearInterval(pairTimer);await boot()}}catch(e){$('#pair-status').textContent=e.message}},5000);
}

document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action]');if(!b)return;const action=b.dataset.action,kind=b.dataset.kind,id=b.dataset.id;
  try{
    if(action==='close'){closeModal();return}if(action==='reload'){location.reload();return}if(action==='home'){closeModal();window.scrollTo({top:0,behavior:'smooth'});return}
    if((action==='add'&&kind==='trips')||action==='add-trip'){await editItem('trips');return}
    if(!canEdit()){if(isDemo)toast('这是演示预览。登录后即可维护真实内容。');return}
    if(action==='add'){editItem(kind);return}if(action==='edit'){editItem(kind,id);return}
    if(action==='manage'){manage(kind);return}
    if(action.startsWith('add-')){editItem({'add-task':'tasks','add-shopping':'shopping','add-event':'events','add-trip':'trips'}[action]);return}
    if(action==='toggle'){
      const item=data[kind].find(i=>i.id===id);if(!item)return;b.disabled=true;await write('/items/'+kind+'/'+id,'PATCH',{done:!item.done,revision:item.revision});await refresh(true);if(activeManager)manage(activeManager);toast(item.done?'已恢复到清单':kind==='shopping'?'已记为买到':'又完成了一件事');return;
    }
    if(action==='delete'){
      const item=data[kind].find(i=>i.id===id);if(!item)return;
      if(!confirm('确定删除“'+item.title+'”？'))return;
      await write('/items/'+kind+'/'+id,'DELETE',{revision:item.revision});closeModal();await refresh(true);toast('已删除');return;
    }
    if(action==='trip-task'){editItem('tasks','',{tripId:id});return}
    if(action==='wealth-private'){await FinanceBaseline.openPrivate();return}if(action==='finance'){financeForm();return}if(action==='personal'){await personalForm();return}
    if(action==='settings'){settings();return}if(action==='profile'){profileForm();return}if(action==='import'){importForm();return}
    if(action==='accounts'||action==='calendar-sync'){await accountsModal();return}
    if(action==='device-edit'){await deviceForm(id);return}if(action==='pair'){pairForm();return}if(action==='devices'){await devicesModal();return}
    if(action==='revoke'){if(confirm('撤销后，这台电视将需要重新配对。继续？')){await write('/devices/'+id,'DELETE');await devicesModal()}return}
    if(action==='logout'){await write('/logout','POST');closeModal();location.href='/';return}
  }catch(err){toast(err.message,true);if(err.status===409)await refresh(true);if(b)b.disabled=false}
});
$('#dialog').addEventListener('close',()=>activeManager='');
$('#dialog').addEventListener('click',e=>{if(e.target===$('#dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal()}});
setInterval(()=>{const clock=$('#clock');if(clock)clock.innerHTML=clockMarkup()},1000);
setInterval(()=>{if(data&&!document.hidden)renderBoard()},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!isDemo&&user)refresh(true)});
document.addEventListener('DOMContentLoaded',()=>boot(),{once:true});
