/* Product navigation and appearance. Load last, after the individual feature modules. */
(function (root) {
  'use strict';
  const THEMES = {forest:'暖绿森林', light:'晨光白', ocean:'海岸蓝'};
  const DEFAULTS = {theme:'forest', density:'comfortable', homeView:'today'};
  const HOME_CARDS = {calendar:['日程安排','calendar'],finance:['家庭财务','wallet'],tasks:['共同待办','check'],shopping:['采购清单','bag'],trips:['旅行计划','plane']};
  const defaultLayout = () => ({revision:0,order:Object.keys(HOME_CARDS),hidden:[]});
  let dashboardLayout=defaultLayout(), layoutIdentity='', layoutLoadedAt=0, layoutPromise=null;
  const ROUTES = {
    home:['今日概览','home','把日子放在一起，让生活有条不紊。'],
    calendar:['日程','calendar','看看今天，也为接下来的七天留好时间。'],
    tasks:['共同待办','check','把记挂的小事，变成一起完成的事。'],
    shopping:['采购','bag','从想买到买到，每一笔都心中有数。'],
    inventory:['家庭物品','bag','记录家中余量，收货与使用都由你确认。'],
    trips:['旅行','plane','从一个目的地，走到下一段共同的回忆。'],
    map:['足迹地图','map','记下去过的地方，也为下一站留个位置。'],
    photos:['家庭相册','photos','由你挑选回忆，决定与谁分享。'],
    finance:['家庭财务','wallet','共同资金一起看，个人明细自己管。'],
    assistant:['家庭助理','spark','让安排、清单和计划自然连接。'],
    connections:['连接中心','link','把日历与清单接进来，让更新自然发生。'],
    settings:['设置','settings','按照你们的习惯，安排这个家。'],
    household:['家庭空间','people','每个家，都有自己的日常与边界。']
  };
  const ICONS = {
    home:'m3 11 9-8 9 8M5 10v11h14V10M9 21v-7h6v7',
    calendar:'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm3-2v5m8-5v5M3 10h18M8 14h2m4 0h2m-8 4h2',
    check:'m5 12 4 4L19 6M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z',
    bag:'M5 7h14l2 14H3L5 7Zm3 0V5a4 4 0 0 1 8 0v2',
    plane:'m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13',
    map:'m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Zm6-3v15m6-12v15',
    photos:'M3 3h18v18H3V3Zm0 13 6-6 6 6 3-3 3 3M16 6h.01',
    wallet:'M3 6h17v15H3V6Zm0 0 15-4v4m-3 6h7v5h-7v-5Z',
    spark:'m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z',
    link:'m10 13 4-4m-7 7-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 11a4 4 0 0 0 6 0l4-4a4 4 0 0 0-6-6l-1 1',
    settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm-2-6h4l1 3 3 2 3 1v4l-3 2-1 3-2 4h-4l-1-3-3-2-3-1v-4l3-2 1-3 2-4Z',
    people:'M8 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm9-1a3 3 0 1 0 0-6M1 22v-4a7 7 0 0 1 14 0v4m3-8a5 5 0 0 1 5 5v3',
    search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 7 7',
    plus:'M12 4v16M4 12h16', more:'M5 12h.01M12 12h.01M19 12h.01',
    arrow:'M5 12h14m-6-6 6 6-6 6', sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2',
    lock:'M5 10h14v12H5V10Zm3 0V6a4 4 0 0 1 8 0v4m-4 5v3',
    tv:'M2 3h20v14H2V3Zm5 19h10m-5-5v5', leaf:'M20 3C4 2 1 11 6 17c6 5 15-1 14-14ZM5 20 16 9',
  };
  let currentRoute = 'home', prefs = {...DEFAULTS}, prefIdentity = '', preferencesPromise = null;
  let applyingView = false, searchText = '', taskFilter = 'pending', shoppingFilter = 'pending';
  let navExpanded = false, preferencesLoadedAt = 0, spaceName = '我们的家', spaceLoaded = false;
  let mapIdentity = '', mapContainer = null;
  let mediaContainer = null;
  let mapPhotoContext = null;
  let inventoryContainer = null;
  const mapActor = () => JSON.stringify([user?.role,user?.householdId,user?.id,user?.auth_version,csrf,isTV,isDemo]);
  const clearMapPhotoContext = () => {mapPhotoContext = null;};
  function openMapPhotos(journeyId, view) {
    if (currentRoute !== 'map' || isTV || isDemo || !canEdit() || mapIdentity !== mapActor()) return;
    if (typeof journeyId !== 'string' || !/^[a-f0-9]{24}$/.test(journeyId)) return;
    mapPhotoContext = {actor:mapActor(),journeyId,view};
    navigate('photos');
  }
  const glyph = name => `<svg class="ps-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name] || ICONS.home}"/></svg>`;
  const validPreferences = value => ({theme:Object.hasOwn(THEMES,value?.theme)?value.theme:'forest',density:value?.density==='compact'?'compact':'comfortable',homeView:['today','week','around'].includes(value?.homeView)?value.homeView:'today'});
  const storageKey = () => 'household_preferences_' + (isDemo?'demo':user?.id || 'guest');
  const routeFromLocation = () => Object.hasOwn(ROUTES,location.hash.slice(1))?location.hash.slice(1):'home';
  const pending = kind => (data?.[kind] || []).filter(item=>!item.done);
  const actionButton = (route,label,iconName='arrow',className='') => `<button type="button" class="ps-button ${className}" data-ps-route="${route}">${glyph(iconName)}<span>${label}</span></button>`;
  const focusPicker = () => `<select class="ps-focus-picker" data-ps-focus aria-label="日程侧重成员">${(data?.people||[]).map(p=>`<option value="${esc(p.id)}" ${focus===p.id?'selected':''}>侧重 ${esc(p.name)}</option>`).join('')}</select>`;
  const memberLayoutIdentity = () => isDemo?'demo':`${user?.householdId || 'default'}:${user?.id || 'guest'}`;
  function normalizedLayout(value) {
    const keys=Object.keys(HOME_CARDS), known=Array.isArray(value?.order)?value.order.filter(k=>keys.includes(k)):[];
    const order=[...new Set([...known,...keys])], hidden=[...new Set((Array.isArray(value?.hidden)?value.hidden:[]).filter(k=>keys.includes(k)))];
    if(hidden.length===keys.length) hidden.splice(hidden.indexOf('calendar'),1);
    return {revision:Number.isInteger(value?.revision)?value.revision:0,order,hidden};
  }
  function initializeLayout() {
    const identity=memberLayoutIdentity();
    if(isTV || identity===layoutIdentity) return;
    layoutIdentity=identity;dashboardLayout=defaultLayout();layoutLoadedAt=0;layoutPromise=null;
    if(isDemo) {try {dashboardLayout=normalizedLayout(JSON.parse(localStorage.getItem('household_demo_layout')));}catch(_){}return;}
    if(user?.role==='member') void refreshLayout(true).catch(()=>{});
  }
  async function refreshLayout(force=false) {
    if(isTV || isDemo || user?.role!=='member') return dashboardLayout;
    if(layoutPromise) return layoutPromise;
    if(!force && Date.now()-layoutLoadedAt<60000) return dashboardLayout;
    const identity=memberLayoutIdentity();
    const pending=(async()=>{
      try {
        const result=normalizedLayout(await api('/dashboard-layout'));
        if(identity!==memberLayoutIdentity() || isTV) return dashboardLayout;
        if(result.revision>=dashboardLayout.revision) {
          const changed=JSON.stringify(result)!==JSON.stringify(dashboardLayout);
          dashboardLayout=result;
          if(changed && currentRoute==='home') renderBoard();
        }
        return dashboardLayout;
      } finally {if(identity===memberLayoutIdentity())layoutLoadedAt=Date.now();}
    })();
    layoutPromise=pending;
    try {return await pending;} finally {if(layoutPromise===pending)layoutPromise=null;}
  }
  function homeCards() {
    const renderers={calendar:calendarCard,finance:financeCard,tasks:tasksCard,shopping:shoppingCard,trips:travelCard};
    return dashboardLayout.order.filter(key=>!dashboardLayout.hidden.includes(key)).map(key=>renderers[key]().replace(/^(\s*<\w+)/,`$1 data-dashboard-card="${key}"`)).join('');
  }
  function setTheme(next) {
    prefs = validPreferences(next);
    document.documentElement.dataset.theme = prefs.theme;
    document.documentElement.dataset.density = prefs.density;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',prefs.theme==='light'?'#f5f5ef':prefs.theme==='ocean'?'#0e2030':'#101d1c');
  }
  function applyDefaultView() {
    if (isTV || applyingView || !data || !root.CalendarViews) return;
    applyingView = true;
    try {
      if (CalendarViews.currentMode() !== prefs.homeView) {
        if (typeof CalendarViews.setMode === 'function') CalendarViews.setMode(prefs.homeView,{persist:false});
        else document.querySelector(`[data-calendar-mode="${prefs.homeView}"]`)?.click();
      }
    } finally { applyingView = false; }
  }
  async function refreshPreferences(force=false) {
    if (!user || isTV || isDemo) return;
    if (preferencesPromise) return preferencesPromise;
    if (!force && Date.now()-preferencesLoadedAt < 60000) return;
    const identity = user.id;
    preferencesPromise = (async()=>{
      try {
        const result = await api('/preferences');
        if (user?.id !== identity || isTV) return;
        const next = validPreferences(result.preferences || result);
        const changed = JSON.stringify(next)!==JSON.stringify(prefs);
        setTheme(next);
        try { localStorage.setItem(storageKey(),JSON.stringify(next)); } catch (_) {}
        preferencesLoadedAt = Date.now();
        if (changed) { renderBoard(); applyDefaultView(); }
      } catch (_) {
        // Retain the last known appearance. Explicit saving reports errors in its form.
        preferencesLoadedAt = Date.now();
      } finally { preferencesPromise = null; }
    })();
    return preferencesPromise;
  }
  function initializePreferences() {
    const identity = isTV?'tv':isDemo?'demo':user?.id || 'guest';
    if (identity === prefIdentity) return;
    prefIdentity = identity; preferencesLoadedAt = 0; currentRoute=routeFromLocation(); searchText='';taskFilter='pending';shoppingFilter='pending';
    let cached = DEFAULTS;
    if (!isTV && user) try { cached=JSON.parse(localStorage.getItem(storageKey())) || DEFAULTS; } catch (_) {}
    setTheme(cached);
    if (!isTV && !isDemo && user?.role==='member') void refreshPreferences(true);
  }
  async function refreshSpaceName() {
    if (isDemo || isTV || spaceLoaded) return;
    spaceLoaded=true;
    try {
      const current=await api('/spaces/current');
      if (current?.name && typeof current.name==='string') {
        spaceName=current.name;
        if (data && user && !isTV) renderBoard();
        const label=document.querySelector('.ps-login-space-name');
        if (label) label.textContent=spaceName;
      }
    } catch (_) { spaceLoaded=false; }
  }
  function counts() {
    const today = dateKey();
    const events = root.CalendarViews ? CalendarViews.helpers.eventsForDay(data.events || [],today,focus) : eventsToday();
    const tasks = pending('tasks'), shopping = pending('shopping');
    const due = tasks.filter(t=>t.due && t.due<=today);
    const trip = [...(data.trips || [])].filter(t=>t.end>=today).sort((a,b)=>a.start.localeCompare(b.start))[0];
    return {events,tasks,shopping,due,trip};
  }
  function navigationItem(route,small=false) {
    const [title,symbol] = ROUTES[route], n=route==='tasks'?pending('tasks').length:route==='shopping'?pending('shopping').length:0;
    return `<button type="button" class="ps-nav-item ${currentRoute===route?'is-active':''}" data-ps-route="${route}" ${currentRoute===route?'aria-current="page"':''}>${glyph(symbol)}<span>${title}</span>${n&&!small?`<b>${n}</b>`:''}</button>`;
  }
  function sidebar() {
    return `<aside class="ps-sidebar" aria-label="家庭中枢导航"><a href="#home" class="ps-brand" data-ps-route="home"><span class="ps-brand-mark">${glyph('home')}</span><span>家庭中枢<small>EVERYDAY, TOGETHER</small></span></a><button class="ps-space-switch" data-ps-route="household"><span class="ps-space-avatar">${glyph('people')}</span><span>${esc(spaceName)}<small>${isDemo?'演示家庭':esc((data.people || []).map(p=>p.name).join(' · '))}</small></span><b>⌄</b></button><div class="ps-nav-label">生活工作台</div><nav class="ps-nav">${['home','calendar','tasks','shopping','inventory','trips','map','photos','finance'].map(r=>navigationItem(r)).join('')}</nav><div class="ps-nav-label">为生活多想一步</div><nav class="ps-nav">${['assistant','connections'].map(r=>navigationItem(r)).join('')}</nav><div class="ps-sidebar-end"><div class="ps-together-note">${glyph('leaf')}<p>让生活轻一点，<br>把时间留给彼此。</p></div>${navigationItem('settings')}<button class="ps-profile" data-ps-route="settings"><span class="ps-avatar">${esc((user?.name || person(focus)).slice(0,1))}</span><span>${esc(user?.name || person(focus))}<small>${isDemo?'演示空间 · 示例数据':'个人与家庭，清晰分开'}</small></span>${glyph('more')}</button></div></aside>`;
  }
  function bottomNavigation() {
    return `<nav class="ps-bottom-nav" aria-label="手机主要功能">${['home','calendar','tasks','assistant'].map(r=>navigationItem(r,true)).join('')}<button class="ps-nav-item ${navExpanded?'is-active':''}" type="button" data-ps-more aria-expanded="${navExpanded}" aria-controls="ps-more-menu">${glyph('more')}<span>更多</span></button></nav>${navExpanded?`<div class="ps-mobile-menu" id="ps-more-menu"><div class="ps-nav-label">所有功能</div>${['shopping','inventory','trips','map','photos','finance','connections','household','settings'].map(r=>navigationItem(r,true)).join('')}</div>`:''}`;
  }
  function topbar() {
    return `<header class="ps-topbar"><div class="ps-breadcrumb"><span>${esc(spaceName)}</span><i>/</i><strong>${ROUTES[currentRoute][0]}</strong></div><div class="ps-top-actions"><button class="ps-search-trigger" data-ps-search>${glyph('search')}<span>搜索日程、清单与旅行</span><kbd>Ctrl K</kbd></button><button class="ps-round" data-ps-preferences aria-label="主题与布局">${glyph('sun')}</button><button class="ps-round ps-mobile-brand" data-ps-route="household" aria-label="家庭空间">${glyph('home')}</button><button class="ps-avatar" data-ps-route="settings" aria-label="我的设置">${esc((user?.name || person(focus)).slice(0,1))}</button></div></header>`;
  }
  function hero() {
    const c=counts(), hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hour12:false}).format(new Date()));
    const greeting=hour<6?'夜深了':hour<11?'早上好':hour<14?'中午好':hour<18?'下午好':'晚上好';
    const name = user?.name || person(focus), date = new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date());
    return `<section class="ps-welcome"><div class="ps-welcome-copy"><div class="ps-eyebrow"><span class="ps-live-dot"></span>${esc(date)}<span class="ps-demo-label">${isDemo?'演示家庭':''}</span></div><h1>${greeting}，${esc(name)}<span>把今天过成喜欢的样子。</span></h1><p>${c.events.length?`今天有 ${c.events.length} 项安排`: '今天的日程还很轻盈'}${c.due.length?`，${c.due.length} 件到期待办值得先看一眼。`:'，别忘了为彼此留一点时间。'}</p><div class="ps-welcome-actions">${actionButton('assistant','和家庭助理聊聊','spark','primary')}${canEdit()?`<button class="ps-button subtle" data-ps-create>${glyph('plus')}记一件事</button>`:''}</div></div><div class="ps-home-art" aria-hidden="true"><span class="ps-orbit ps-orbit-one"></span><span class="ps-orbit ps-orbit-two"></span><div class="ps-art-sun"></div><div class="ps-art-roof"></div><div class="ps-art-house"><span class="ps-art-window"></span><span class="ps-art-door"></span></div><div class="ps-art-plant">${glyph('leaf')}</div><div class="ps-art-ground"></div><span class="ps-art-caption">HOME IS A FEELING.</span></div></section><section class="ps-pulse" aria-label="家庭概览">${[
      ['calendar','今天的安排',c.events.length,'项日程','calendar'],
      ['tasks','一起完成',c.tasks.length,'项待办','check'],
      ['shopping','采购清单',c.shopping.length,'件待采购','bag'],
      ['finance','共同荷包',data.finance?.confirmedAt?money(data.finance.wallet):'待核对',data.finance?.confirmedAt?'已核对余额':'','wallet']
    ].map(([route,label,value,unit,symbol])=>`<button data-ps-route="${route}" class="ps-pulse-item"><span class="ps-pulse-icon ${route}">${glyph(symbol)}</span><span><small>${label}</small><strong>${esc(value)}<em>${esc(unit)}</em></strong></span>${glyph('arrow')}</button>`).join('')}</section>`;
  }
  function pageHeading(route,action='') {
    return `<div class="ps-page-heading"><div><div class="ps-eyebrow">OUR EVERYDAY</div><h1>${ROUTES[route][0]}</h1><p>${ROUTES[route][2]}</p></div>${action}</div>`;
  }
  function listWorkspace(kind) {
    const shopping=kind==='shopping', route=shopping?'shopping':'tasks', filter=shopping?shoppingFilter:taskFilter;
    const all=data[kind] || [], list=[...all].filter(item=>(filter==='all'||(filter==='done'?item.done:!item.done))&&(!searchText||(item.title+' '+(item.note||'')).toLocaleLowerCase().includes(searchText.toLocaleLowerCase()))).sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999'));
    const add=canEdit()?`<button class="ps-button primary" data-action="add" data-kind="${kind}">${glyph('plus')}${shopping?'添加采购':'添加待办'}</button>`:'';
    const known=shopping?all.filter(i=>!i.done&&Number.isInteger(i.budget)):[], unknown=shopping?all.filter(i=>!i.done&&!Number.isInteger(i.budget)):[];
    return `${pageHeading(route,add)}${shopping?`<div class="ps-shopping-totals"><div><small>待采购预算 · 已填写部分</small><strong>${money(known.reduce((sum,i)=>sum+i.budget,0))}</strong></div><p>${unknown.length?`另有 ${unknown.length} 件尚未填写预算`:'每一笔预算，都为共同生活做准备。'}</p><span>${glyph('lock')}共享采购</span></div>`:''}<section class="ps-workspace-panel"><div class="ps-list-toolbar"><div class="ps-filter-tabs" role="group" aria-label="清单状态">${[['pending',shopping?'待采购':'待完成'],['done',shopping?'已买到':'已完成'],['all','全部']].map(([value,label])=>`<button data-ps-filter="${value}" data-ps-kind="${kind}" aria-pressed="${filter===value}" class="${filter===value?'selected':''}">${label}<span>${value==='all'?all.length:all.filter(i=>value==='done'?i.done:!i.done).length}</span></button>`).join('')}</div>${canEdit()&&!isDemo?`<button type="button" class="ps-button subtle" data-ps-module="HouseholdRoutines">${glyph('calendar')}例行计划</button>`:''}${!shopping&&canEdit()?`<button type="button" class="ps-button subtle ps-task-publish-trigger" data-task-publish-open="1">${glyph('link')}${all.length?'同步本地待办':'开始安排待办'}</button>`:''}<label class="ps-inline-search">${glyph('search')}<input data-ps-list-search placeholder="搜索${shopping?'采购':'待办'}" aria-label="搜索${shopping?'采购':'待办'}" value="${esc(searchText)}"></label></div><div class="ps-full-list manager-list">${list.length?list.map(item=>listRow(kind,item,true)).join(''):`<div class="ps-empty-state">${glyph(shopping?'bag':'check')}<h2>${searchText?'没有找到匹配内容':filter==='done'?'还没有完成记录':shopping?'需要什么，就记在这里':'这一刻，清单很轻盈'}</h2><p>${searchText?'换个关键词再试试。':shopping?'添加预算、数量和参考图片，让采购更省心。':'从一个小任务开始，给共同生活留个提醒。'}</p></div>`}</div></section>`;
  }
  function tripsWorkspace() {
    const trips=[...(data.trips || [])].sort((a,b)=>a.start.localeCompare(b.start));
    return `${pageHeading('trips',`<div class="ps-page-controls"><button class="ps-button subtle" data-ps-route="map">${glyph('map')}足迹地图</button><button class="ps-button subtle" data-ps-route="photos">${glyph('photos')}旅行相册</button><button class="ps-button primary" data-action="add" data-kind="trips">${glyph('spark')}规划一趟旅行</button></div>`)}<div class="ps-trip-grid">${trips.length?trips.map(t=>{const tasks=(data.tasks||[]).filter(i=>i.tripId===t.id), done=tasks.filter(i=>i.done).length;return `<article class="ps-trip-card"><div class="ps-trip-cover">${glyph('plane')}<span>${t.end<dateKey()?'美好回忆':t.start<=dateKey()?'正在旅途':'即将出发'}</span><h2>${esc(t.destination || t.title)}</h2></div><div class="ps-trip-body"><h3>${esc(t.title)}</h3><p>${displayDate(t.start)} — ${displayDate(t.end)}</p><div class="ps-trip-facts"><span>旅行预算<strong>${money(t.budget)}</strong></span><span>准备进度<strong>${done} / ${tasks.length}</strong></span></div><div class="meter"><span style="width:${tasks.length?done/tasks.length*100:0}%"></span></div><div class="ps-trip-actions"><button class="ps-button subtle" data-ps-module="JourneyUI" data-ps-id="${esc(t.id)}">查看行程 ${glyph('arrow')}</button>${canEdit()?`<button class="ps-round" data-action="edit" data-kind="trips" data-id="${esc(t.id)}" aria-label="编辑${esc(t.title)}">${glyph('more')}</button>`:''}</div></div></article>`}).join(''):`<section class="ps-workspace-panel ps-empty-state">${glyph('plane')}<h2>下一站，想去哪里？</h2><p>从目的地和出发日期开始，把行程、采购和准备清单连起来。</p><button class="ps-button primary" data-action="add" data-kind="trips">开始计划 ${glyph('arrow')}</button></section>`}</div>`;
  }
  function financeWorkspace() {
    return `${pageHeading('finance',`<button class="ps-button primary" data-ps-module="FinanceHub">${glyph('wallet')}账单与投资</button>`)}<div class="ps-finance-layout">${financeCard()}<section class="ps-workspace-panel ps-finance-links"><div class="ps-section-head"><h2>财务工作台</h2>${glyph('wallet')}</div><p>让收入、消费、账户与未来的计划，有迹可循。</p>${[
      ['FinanceHub','账单与订单','导入账单、核对分类，梳理日常消费。','wallet','ledger'],
      ['FinanceHub','投资与资产','查看账户与持仓，以真实来源为基础。','leaf','investments']
    ].map(([module,title,desc,symbol,tab])=>`<button class="ps-feature-link" data-ps-module="${module}" data-ps-id="${tab}">${glyph(symbol)}<span>${title}<small>${desc}</small></span>${glyph('arrow')}</button>`).join('')}${canEdit()?`<button class="ps-feature-link" data-action="wealth-private">${glyph('lock')}<span>我的财务基线<small>仅本人可见的账户、负债与收入记录。</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-action="personal">${glyph('wallet')}<span>我的月度预算<small>核对本月个人收入、支出与预算。</small></span>${glyph('arrow')}</button>`:''}<div class="ps-privacy-note">${glyph('lock')}公共账户与已批准的资产、负债汇总共同可见；个人明细始终按账户隔离。</div></section></div>`;
  }
  function connectionsWorkspace() {
    return `${pageHeading('connections',canEdit()?`<button class="ps-button primary" data-action="accounts">${glyph('plus')}管理账户与来源</button>`:'')}<section class="ps-sync-summary" data-sync-health-summary>${root.SyncHealth?.summaryMarkup(data.sync?.health,{showAction:canEdit(),demo:isDemo,online})||'<p>同步状态待核对，请刷新页面。</p>'}</section><div class="ps-provider-grid">${[
      ['Microsoft','M','Outlook 日历 · Microsoft To Do','把工作与生活的日历放在一起，待办可创建与勾选回写。','microsoft'],
      ['Google','G','Google Calendar · Google Tasks','按日历和清单选择共享范围，自动获取最新安排。','google']
    ].map(([name,letter,sub,description,cls])=>`<section class="ps-workspace-panel ps-provider"><span class="ps-provider-logo ${cls}">${letter}</span><h2>${name}</h2><small>${sub}</small><p>${description}</p>${canEdit()?`<button class="ps-button subtle" data-action="accounts">管理连接 ${glyph('arrow')}</button>`:'<span class="ps-status">支持日历与清单</span>'}</section>`).join('')}<section class="ps-workspace-panel ps-provider"><span class="ps-provider-logo">${glyph('wallet')}</span><h2>账单与订单</h2><small>财务导入中心</small><p>从账单文件开始归集消费，导入前预览，再确认计入账本。</p><button class="ps-button subtle" data-ps-module="FinanceHub">进入导入中心 ${glyph('arrow')}</button></section><section class="ps-workspace-panel ps-provider"><span class="ps-provider-logo">${glyph('tv')}</span><h2>家里的大屏</h2><small>电视只读看板</small><p>每个家各有侧重，手机上修改，客厅的屏幕自动更新。</p>${canEdit()?'<button class="ps-button subtle" data-action="devices">管理显示设备</button>':'<a class="ps-button subtle" href="/demo?tv=1">打开大屏演示</a>'}</section></div><p class="ps-footnote">日历与清单会定期检查更新；财务文件导入不代表银行或购物平台已实时连接。</p>`;
  }
  function assistantWorkspace() {
    const c=counts(), suggestions=[['trips','规划下一趟旅行','从目的地到行程、准备事项和采购。','plane'],['tasks','梳理我们的待办',`${c.tasks.length} 件待办${c.due.length?'，其中 '+c.due.length+' 件已到期':'，一起安排轻重缓急'}。`,'check'],['finance','看看家庭的财务','核对公共预算、账单与个人资产。','wallet']];
    return `${pageHeading('assistant',canEdit()&&!isDemo?`<button type="button" class="ps-button subtle" data-ps-module="HouseholdRoutines">${glyph('calendar')}家庭例行计划</button>`:'')}<section class="ps-assistant-intro"><span class="ps-assistant-orb">${glyph('spark')}</span><div class="ps-eyebrow">A LITTLE HELP, EVERY DAY</div><h2>生活里多一个<br>替你想着的人。</h2><p>从一句话开始，把需要记住的事变成可以执行的计划。</p><button class="ps-assistant-prompt" data-ps-module="HomeAssistant"><span>告诉助理，今天想一起完成什么…</span><b>${glyph('arrow')}</b></button><small>涉及新增或修改的计划，先看内容，再确认执行。</small></section><div class="ps-suggestion-grid">${suggestions.map(([route,title,description,symbol])=>`<button class="ps-workspace-panel ps-suggestion" data-ps-route="${route}">${glyph(symbol)}<h3>${title}</h3><p>${description}</p><span>打开工作台 ${glyph('arrow')}</span></button>`).join('')}</div>`;
  }
  function settingsWorkspace() {
    return `${pageHeading('settings')}<div class="ps-settings-grid"><section class="ps-workspace-panel"><div class="ps-section-head"><h2>我的工作台</h2>${glyph('sun')}</div><button class="ps-feature-link" data-ps-preferences>${glyph('sun')}<span>主题与显示<small>${THEMES[prefs.theme]} · ${prefs.density==='compact'?'紧凑':'舒适'}密度 · 手机电脑同步</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-ps-layout>${glyph('settings')}<span>首页卡片布局<small>调整顺序和显示内容，保存为我的工作台。</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-ps-route="household">${glyph('people')}<span>家庭空间<small>管理家庭和成员，选择当前空间。</small></span>${glyph('arrow')}</button>${canEdit()?`<button class="ps-feature-link" data-portability-open>${glyph('wallet')}<span>导出我的数据<small>下载个人数据，可选附带共同安排。</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-member-sessions-open>${glyph('lock')}<span>登录设备<small>查看本人登录会话，退出其他浏览器。</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-action="profile">${glyph('lock')}<span>我的账户<small>修改显示名称与登录密码。</small></span>${glyph('arrow')}</button>`:''}</section><section class="ps-workspace-panel"><div class="ps-section-head"><h2>家庭连接</h2>${glyph('link')}</div>${[['connections','连接中心','Microsoft 与 Google 的日历和清单','link'],['finance','财务工作台','账单、预算与本人账户明细','wallet']].map(([route,title,desc,symbol])=>`<button class="ps-feature-link" data-ps-route="${route}">${glyph(symbol)}<span>${title}<small>${desc}</small></span>${glyph('arrow')}</button>`).join('')}${canEdit()?`<button class="ps-feature-link" data-action="pair">${glyph('tv')}<span>连接一块电视<small>输入电视上的配对码即可开始。</small></span>${glyph('arrow')}</button><button class="ps-feature-link" data-action="devices">${glyph('tv')}<span>管理电视<small>按设备调整卡片、主题、密度与日程范围。</small></span>${glyph('arrow')}</button>`:''}</section></div><section class="ps-settings-bottom"><a class="ps-button subtle" href="/demo?tv=1">${glyph('tv')}预览大屏</a>${canEdit()?'<button class="ps-button subtle" data-action="logout">退出登录</button>':'<a class="ps-button primary" href="/">登录家庭空间</a>'}</section>`;
  }
  function householdWorkspace() {
    return `${pageHeading('household',`<button class="ps-button primary" data-ps-module="HouseholdSpaces">${glyph('people')}管理家庭空间</button>`)}<section class="ps-household-cover"><span class="ps-brand-mark">${glyph('home')}</span><div><h2>${esc(spaceName)}</h2><p>共享生活，也尊重每个人自己的空间。</p></div></section><div class="ps-member-grid">${(data.people||[]).map((p,i)=>`<article class="ps-workspace-panel ps-member"><span class="ps-avatar ${i?'partner':''}">${esc(p.name.slice(0,1))}</span><h2>${esc(p.name)}</h2><p>${p.id===user?.id?'我':'家庭成员'}</p><span class="ps-status">日程与清单共同可见</span></article>`).join('')}</div><div class="ps-privacy-note">${glyph('lock')}家庭资料按空间隔离。共享范围之外的个人账户和消费明细，只由本人查看。</div>`;
  }
  function content() {
    if (currentRoute==='home') return `${hero()}<div class="ps-board-heading"><h2>一起过好每一天</h2><div class="ps-page-controls">${focusPicker()}<button class="ps-text-button ps-layout-trigger" data-ps-layout>${glyph('settings')}<span>编辑首页</span></button></div></div><main class="board ps-home-board" data-layout-count="${dashboardLayout.order.length-dashboardLayout.hidden.length}">${homeCards()}</main>`;
    if (currentRoute==='calendar') return `${pageHeading('calendar',`<div class="ps-page-controls">${focusPicker()}${canEdit()?`<button class="ps-button primary" data-action="add" data-kind="events">${glyph('plus')}添加安排</button>`:''}</div>`)}<main class="board ps-calendar-workspace">${calendarCard()}</main>`;
    if (currentRoute==='tasks'||currentRoute==='shopping') return listWorkspace(currentRoute);
    if (currentRoute==='trips') return tripsWorkspace();
    if (currentRoute==='map') return `${pageHeading('map')}<section id="ps-map-workspace" aria-label="足迹地图">${isDemo?'<p class="help">登录后，可记录自己的到访地点、旅行计划和心愿；演示不会读取或保存真实地点。</p><a class="ps-button primary" href="/">登录并记录地点</a>':'<p class="help">正在打开地图…</p>'}</section>`;
    if (currentRoute==='photos') return `${pageHeading('photos')}<section id="ps-media-workspace" aria-label="家庭相册">${isDemo?'<p class="help">登录后，可连接 Google Photos 并选择照片；演示不会读取真实相册。</p><a class="ps-button primary" href="/">登录并选择照片</a>':'<p class="help">正在打开相册…</p>'}</section>`;
    if (currentRoute==='inventory') return `${pageHeading('inventory')}<section id="ps-inventory-workspace" aria-label="家庭物品">${isDemo?'<p class="help">登录后，可登记自己的物品、明确共享并核对实物数量；演示不会读取真实库存。</p><a class="ps-button primary" href="/">登录并管理物品</a>':'<p class="help">正在打开家庭物品…</p>'}</section>`;
    if (currentRoute==='finance') return financeWorkspace();
    if (currentRoute==='connections') return connectionsWorkspace();
    if (currentRoute==='assistant') return assistantWorkspace();
    if (currentRoute==='household') return householdWorkspace();
    return settingsWorkspace();
  }
  const originalRenderBoard = renderBoard;
  renderBoard = function () {
    if (!data) return;
    const identity = mapActor();
    if (identity !== mapIdentity) {
      clearMapPhotoContext();
      root.JourneyMap?.notifyIdentityChanged(); mapContainer = null; mapIdentity = identity;
      root.HouseholdMedia?.notifyIdentityChanged(); mediaContainer = null;
      root.InventoryUI?.notifyIdentityChanged(); inventoryContainer = null;
    }
    if (currentRoute !== 'map' || isDemo || isTV) {
      root.JourneyMap?.unmount(); mapContainer = null;
    }
    if (currentRoute !== 'photos' || isDemo || isTV) {
      root.HouseholdMedia?.unmount(); mediaContainer = null;
    }
    if (currentRoute !== 'inventory' || isDemo || isTV) {
      root.InventoryUI?.unmount(); inventoryContainer = null;
    }
    const inventoryFocus = inventoryContainer?.contains(document.activeElement) ? document.activeElement : null;
    const inventorySelection = inventoryFocus && typeof inventoryFocus.selectionStart === 'number'
      ? [inventoryFocus.selectionStart,inventoryFocus.selectionEnd] : null;
    const mediaFocus = mediaContainer?.contains(document.activeElement) ? document.activeElement : null;
    const mediaSelection = mediaFocus && typeof mediaFocus.selectionStart === 'number'
      ? [mediaFocus.selectionStart,mediaFocus.selectionEnd] : null;
    const mapFocus = mapContainer?.contains(document.activeElement) ? document.activeElement : null;
    const mapSelection = mapFocus && typeof mapFocus.selectionStart === 'number'
      ? [mapFocus.selectionStart,mapFocus.selectionEnd] : null;
    initializePreferences();
    initializeLayout();
    void refreshSpaceName();
    if (isTV) { originalRenderBoard(); document.body.classList.add('product-tv'); root.TVDisplay?.applyBoard(); return; }
    document.body.className = 'product-shell'+(isDemo?' demo-view':'');
    document.title = `${ROUTES[currentRoute][0]} · 家庭中枢`;
    const selected = document.activeElement?.matches('[data-ps-list-search]'), selection = selected?document.activeElement.selectionStart:null;
    document.querySelector('#app').innerHTML = `${sidebar()}<div class="ps-main">${topbar()}<div class="ps-page" id="ps-page" data-ps-page="${currentRoute}">${content()}<footer class="board-footer"><span id="connection" class="connection"></span><span>${isDemo?'所有内容均为示例，操作不会修改真实数据':'一起计划，一起完成。'}</span></footer></div></div>${bottomNavigation()}`;
    updateFooter();
    if (currentRoute === 'map' && !isDemo && !isTV) {
      const slot = document.querySelector('#ps-map-workspace');
      if (mapContainer) {
        // Preserve the same node synchronously through a board refresh. The
        // module's pending request guards and unsaved form keep their identity.
        slot.replaceWith(mapContainer);
        if (mapFocus?.isConnected) {
          mapFocus.focus({preventScroll:true});
          if (mapSelection) mapFocus.setSelectionRange(...mapSelection);
        }
        root.JourneyMap?.notifyStateChanged();
      } else if (root.JourneyMap) {
        mapContainer = slot;
        const initialView = mapPhotoContext?.actor === identity ? mapPhotoContext.view : undefined;
        clearMapPhotoContext();
        void root.JourneyMap.mount(slot, {openJourney:(id,options)=>root.JourneyUI.open(id,options),
          openPhotos:openMapPhotos,initialView,onIdentityChanged:clearMapPhotoContext});
      } else slot.textContent = '地图组件暂未加载，请刷新重试。原旅行记录仍可从旅行页面打开。';
    }
    if (currentRoute === 'photos' && !isDemo && !isTV) {
      const slot = document.querySelector('#ps-media-workspace');
      if (mediaContainer) {
        slot.replaceWith(mediaContainer);
        if (mediaFocus?.isConnected) {
          mediaFocus.focus({preventScroll:true});
          if (mediaSelection) mediaFocus.setSelectionRange(...mediaSelection);
        }
        root.HouseholdMedia?.notifyStateChanged();
      } else if (root.HouseholdMedia) {
        mediaContainer = slot;
        const context = mapPhotoContext?.actor === identity ? mapPhotoContext : null;
        void root.HouseholdMedia.mount(slot,{openJourney:(id,options)=>root.JourneyUI.open(id,options),
          initialJourneyId:context?.journeyId,onIdentityChanged:clearMapPhotoContext,
          returnToMap:context ? () => {
            if (mapPhotoContext === context && context.actor === mapActor() && currentRoute === 'photos') navigate('map');
          } : undefined});
      } else slot.textContent = '相册组件暂未加载，请刷新重试。';
    }
    if (currentRoute === 'inventory' && !isDemo && !isTV) {
      const slot = document.querySelector('#ps-inventory-workspace');
      if (inventoryContainer) {
        slot.replaceWith(inventoryContainer);
        if (inventoryFocus?.isConnected) {
          inventoryFocus.focus({preventScroll:true});
          if (inventorySelection) inventoryFocus.setSelectionRange(...inventorySelection);
        }
        root.InventoryUI?.notifyStateChanged();
      } else if (root.InventoryUI) {
        inventoryContainer = slot;
        void root.InventoryUI.mount(slot,{});
      } else slot.textContent = '家庭物品组件暂未加载，请刷新重试。';
    }
    if (!isDemo && user?.role==='member') root.HouseholdRoutines?.notifyStateChanged();
    if (selected) { const input=document.querySelector('[data-ps-list-search]');input?.focus();input?.setSelectionRange(selection,selection); }
  };
  const originalRenderLogin = renderLogin;
  renderLogin = function () {
    clearMapPhotoContext();
    root.JourneyMap?.notifyIdentityChanged(); mapContainer = null; mapIdentity = '';
    root.HouseholdMedia?.notifyIdentityChanged(); mediaContainer = null;
    root.InventoryUI?.notifyIdentityChanged(); inventoryContainer = null;
    currentRoute='home'; prefIdentity=''; layoutIdentity='';dashboardLayout=defaultLayout();setTheme(DEFAULTS); originalRenderLogin();
    document.body.classList.add('product-auth');
    const story=document.querySelector('.auth-story');
    if (story) story.insertAdjacentHTML('beforeend','<div class="ps-auth-promise"><span>01 <b>把安排放在一起</b></span><span>02 <b>把计划变成行动</b></span><span>03 <b>把时间留给彼此</b></span></div>');
    document.querySelector('.auth-card')?.insertAdjacentHTML('beforeend',`<div class="ps-auth-spaces"><span class="ps-login-space-name">${esc(spaceName)}</span><button type="button" data-household-open>切换家庭</button><button type="button" data-household-redeem>使用邀请码创建家庭</button></div>`);
    void refreshSpaceName();
  };
  function navigate(route,remember=true) {
    if (!Object.hasOwn(ROUTES,route)||!data||isTV) return;
    if (!['map','photos'].includes(route) || mapPhotoContext?.actor !== mapActor()) clearMapPhotoContext();
    currentRoute=route; searchText=''; navExpanded=false;
    if (remember && location.hash!=='#'+route) history.pushState(null,'','#'+route);
    if (document.querySelector('#dialog')?.open) closeModal();
    activeManager='';
    renderBoard();
    window.scrollTo({top:0,behavior:'instant'});
  }
  function openPreferences() {
    if (isTV) return;
    openModal('让这里更像你们的家',`<form id="ps-preferences-form"><p class="help">选择喜欢的氛围与信息密度。${isDemo?'演示设置仅保存在本机。':'保存后会同步到你的手机与电脑。电视使用各自的显示设置。'}</p><div class="ps-preference-label">空间主题</div><div class="ps-theme-grid">${Object.entries(THEMES).map(([value,label])=>`<label class="ps-theme-choice"><input type="radio" name="theme" value="${value}" ${prefs.theme===value?'checked':''}><span class="ps-theme-preview ${value}"><i></i><i></i><i></i></span><strong>${label}</strong><small>${{forest:'沉静、温暖，适合每个夜晚',light:'轻盈、明亮，让思绪舒展',ocean:'清透、平静，像靠近海边'}[value]}</small></label>`).join('')}</div><div class="fields"><label class="field"><span>信息密度</span><select name="density"><option value="comfortable" ${prefs.density==='comfortable'?'selected':''}>舒适 · 留一些呼吸空间</option><option value="compact" ${prefs.density==='compact'?'selected':''}>紧凑 · 一眼看到更多</option></select></label><label class="field"><span>默认日程范围</span><select name="homeView">${[['today','今日'],['week','本周'],['around','前后 3 天']].map(([value,label])=>`<option value="${value}" ${prefs.homeView===value?'selected':''}>${label}</option>`).join('')}</select></label></div><div class="error" role="alert"></div><div class="dialog-footer"><button type="button" class="ps-button subtle" data-action="close">取消</button><button type="submit" class="ps-button primary">${isDemo?'应用演示外观':'保存并同步'}</button></div></form>`,true);
    const form=document.querySelector('#ps-preferences-form');
    form.onsubmit=async event=>{
      event.preventDefault(); const button=form.querySelector('[type=submit]'), error=form.querySelector('.error'), next=validPreferences(Object.fromEntries(new FormData(form)));button.disabled=true;error.textContent='';
      try {
        if (!isDemo) { if (!canEdit()) throw new Error('请登录后保存个人偏好'); await write('/preferences','PUT',next); }
        setTheme(next);try { localStorage.setItem(storageKey(),JSON.stringify(next)); } catch (_) {}
        preferencesLoadedAt=Date.now();closeModal();renderBoard();applyDefaultView();toast(isDemo?'演示外观已更新':'外观已保存，其他设备会自动读取');
      } catch(err) { error.textContent=err.message; } finally { button.disabled=false; }
    };
  }
  async function openLayout() {
    if(isTV || (!isDemo && !canEdit())) return;
    openModal('安排我的首页',`<form id="ps-layout-form"><p class="help">把常用内容放在前面。隐藏后仍可从导航打开，不会删除数据。${isDemo?'演示调整只保存在这台设备。':'只调整你的手机与电脑首页，伴侣和电视保持各自设置。'}</p><fieldset class="ps-layout-fields" disabled><div class="ps-layout-summary"><strong data-layout-count-label></strong><button type="button" class="ps-text-button" data-layout-reset>恢复默认</button></div><div class="ps-layout-list" role="list" aria-label="首页卡片顺序"></div><p class="ps-layout-keyboard">使用上下移按钮，或聚焦卡片后按 Alt + ↑ / ↓ 调整顺序。</p></fieldset><div class="ps-layout-live" aria-live="polite" aria-atomic="true"></div><div class="error" role="alert"></div><div class="ps-layout-conflict" hidden></div><div class="dialog-footer ps-layout-footer"><button type="button" class="ps-button subtle" data-action="close">取消</button><button type="button" class="ps-button subtle" data-layout-retry hidden>重新加载</button><button type="submit" class="ps-button primary" disabled>${isDemo?'应用演示布局':'保存首页布局'}</button></div></form>`,true);
    const form=document.querySelector('#ps-layout-form'), fields=form.querySelector('fieldset'), error=form.querySelector('.error'), live=form.querySelector('.ps-layout-live'), conflict=form.querySelector('.ps-layout-conflict'), submit=form.querySelector('[type=submit]');
    let draft=null, saving=false;
    const snapshot=()=>normalizedLayout(draft);
    function draw(focusKey='',message='') {
      form.querySelector('[data-layout-count-label]').textContent=`${draft.order.length-draft.hidden.length} 张卡片显示在首页`;
      form.querySelector('.ps-layout-list').innerHTML=draft.order.map((key,index)=>`<div class="ps-layout-row ${draft.hidden.includes(key)?'is-hidden':''}" data-layout-card="${key}" tabindex="0" role="listitem" aria-label="${HOME_CARDS[key][0]}，第 ${index+1} 项"><span class="ps-layout-position">${index+1}</span><span class="ps-layout-symbol">${glyph(HOME_CARDS[key][1])}</span><div class="ps-layout-name"><strong>${HOME_CARDS[key][0]}</strong><small>${draft.hidden.includes(key)?'已从首页隐藏':'显示在首页'}</small></div><label class="ps-layout-visibility"><input type="checkbox" data-layout-visible="${key}" ${draft.hidden.includes(key)?'':'checked'} aria-label="在首页显示${HOME_CARDS[key][0]}"><span>显示</span></label><div class="ps-layout-move"><button type="button" data-layout-move="-1" data-layout-key="${key}" aria-label="上移${HOME_CARDS[key][0]}" ${index===0?'disabled':''}>↑</button><button type="button" data-layout-move="1" data-layout-key="${key}" aria-label="下移${HOME_CARDS[key][0]}" ${index===draft.order.length-1?'disabled':''}>↓</button></div></div>`).join('');
      live.textContent=message;
      if(focusKey) form.querySelector(`[data-layout-card="${focusKey}"]`)?.focus({preventScroll:true});
    }
    function move(key,delta) {
      if(saving || !draft)return;
      const index=draft.order.indexOf(key), next=index+delta;
      if(index<0 || next<0 || next>=draft.order.length)return;
      [draft.order[index],draft.order[next]]=[draft.order[next],draft.order[index]];
      draw(key,`${HOME_CARDS[key][0]}已移至第 ${next+1} 项`);
    }
    async function load() {
      error.textContent='';form.querySelector('[data-layout-retry]').hidden=true;
      try {
        const latest=isDemo?dashboardLayout:await refreshLayout(true);
        if(!form.isConnected)return;
        draft=normalizedLayout(latest);draw();fields.disabled=false;submit.disabled=false;
      } catch(err) {if(form.isConnected){error.textContent=err.message;form.querySelector('[data-layout-retry]').hidden=false;}}
    }
    form.addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button || saving)return;
      if(button.hasAttribute('data-layout-move'))move(button.dataset.layoutKey,Number(button.dataset.layoutMove));
      if(button.hasAttribute('data-layout-reset') && draft){draft={...defaultLayout(),revision:draft.revision};draw('', '已恢复默认顺序，保存后生效');}
      if(button.hasAttribute('data-layout-retry'))void load();
    });
    form.addEventListener('change',event=>{
      const key=event.target.dataset.layoutVisible;if(!key || !draft || saving)return;
      if(!event.target.checked && draft.hidden.length===draft.order.length-1){event.target.checked=true;error.textContent='首页至少保留一张可见卡片';return;}
      error.textContent='';draft.hidden=event.target.checked?draft.hidden.filter(x=>x!==key):[...draft.hidden,key];
      draw('',`${HOME_CARDS[key][0]}${event.target.checked?'已显示':'已隐藏'}，保存后生效`);
      form.querySelector(`[data-layout-visible="${key}"]`)?.focus({preventScroll:true});
    });
    form.addEventListener('keydown',event=>{
      if(event.altKey && ['ArrowUp','ArrowDown'].includes(event.key)){
        const row=event.target.closest('[data-layout-card]');if(row){event.preventDefault();move(row.dataset.layoutCard,event.key==='ArrowUp'?-1:1);}
      }
    });
    form.onsubmit=async event=>{
      event.preventDefault();if(!draft || saving)return;
      saving=true;fields.disabled=true;submit.disabled=true;error.textContent='';conflict.hidden=true;
      try {
        const next=snapshot(), saved=isDemo?next:await write('/dashboard-layout','PUT',next);
        if(!form.isConnected)return;
        dashboardLayout=normalizedLayout(saved);layoutLoadedAt=Date.now();
        if(isDemo)try{localStorage.setItem('household_demo_layout',JSON.stringify(dashboardLayout));}catch(_){}
        closeModal();renderBoard();toast(isDemo?'演示首页已更新':'首页布局已保存，其他设备会自动读取');
      } catch(err) {
        if(!form.isConnected)return;
        error.textContent=err.message;
        if(err.status===409){
          conflict.hidden=false;conflict.innerHTML='<p>你的草稿仍保留。查看另一台设备保存的布局，再选择如何继续。</p><button type="button" class="ps-button subtle" data-layout-compare>查看最新布局</button>';
          conflict.querySelector('button').onclick=async()=>{
            try {
              const latest=normalizedLayout(await api('/dashboard-layout'));if(!form.isConnected)return;
              conflict.innerHTML=`<strong>另一台设备的首页</strong><ol>${latest.order.filter(k=>!latest.hidden.includes(k)).map(k=>`<li>${HOME_CARDS[k][0]}</li>`).join('')}</ol><div class="ps-layout-conflict-actions"><button type="button" class="ps-button subtle" data-layout-use-latest>使用最新布局</button><button type="button" class="ps-button primary" data-layout-keep-draft>保留我的草稿</button></div><p>保留草稿后仍需点击保存，不会自动覆盖。</p>`;
              conflict.querySelector('[data-layout-use-latest]').onclick=()=>{draft=latest;draw('', '已载入最新布局');conflict.hidden=true;error.textContent='';};
              conflict.querySelector('[data-layout-keep-draft]').onclick=()=>{draft.revision=latest.revision;conflict.hidden=true;error.textContent='已保留草稿，请检查后再次保存';};
            }catch(loadError){error.textContent=loadError.message;}
          };
        }
      } finally {saving=false;if(form.isConnected){fields.disabled=false;submit.disabled=false;}}
    };
    await load();
  }
  let taskStartSequence = 0;
  async function openTasks({create=false,originNode}={}, expectedContext) {
    // A return belongs to its original dialog button, not a later page or draft.
    const ticket=++taskStartSequence, owns=()=>ticket===taskStartSequence && originNode?.isConnected && document.querySelector('#dialog')?.open;
    if (isTV || isDemo || !canEdit() || !owns()) throw new Error('页面已变化，请从待办重新进入。');
    const context=expectedContext || await AccountsReturn.capture();
    await AccountsReturn.verify(context);
    if (!owns()) throw new Error('页面已变化，请从待办重新进入。');
    const latest=await api('/state');
    await AccountsReturn.verify(context);
    if (!owns()) throw new Error('页面已变化，请从待办重新进入。');
    if (!data || latest.revision>=data.revision) data=latest;
    navigate('tasks');
    if (create) {
      editItem('tasks');
      // The first item is local even if setup selected a default cloud list.
      const selector=document.querySelector('#dialog form')?.elements.sourceId;
      if (selector) {selector.value='';selector.dispatchEvent(new Event('change',{bubbles:true}));}
    }
  }
  function openCreate() {
    if (!canEdit()) return;
    openModal('记一件事',`<p class="help">无论一件小事，还是一段旅程，都从这里开始。</p><div class="ps-create-grid">${[['events','日程安排','calendar','留好时间与地点'],['tasks','共同待办','check','分工，把事情往前推'],['shopping','采购计划','bag','数量、预算与参考图片'],['trips','旅行计划','plane','下一站，和你一起']].map(([kind,title,symbol,desc])=>`<button class="ps-feature-link" data-action="add" data-kind="${kind}">${glyph(symbol)}<span>${title}<small>${desc}</small></span>${glyph('arrow')}</button>`).join('')}</div>`);
  }
  function openSearch() {
    if (!data||isTV) return;
    openModal('搜索这个家的日常',`<label class="ps-global-search">${glyph('search')}<input id="ps-search-input" type="search" placeholder="日程标题、采购名称、目的地…" autocomplete="off" aria-label="搜索日程、任务、采购和旅行"></label><p class="help">仅搜索当前家庭的共享日程、待办、采购与旅行。个人财务明细不会出现在这里。</p><div id="ps-search-results" class="ps-search-results"><p class="help">输入关键词，快速找到要处理的事。</p></div>`,true);
    const input=document.querySelector('#ps-search-input');input.focus();
    input.oninput=()=>{
      const query=input.value.trim().toLocaleLowerCase(), rows=[];
      if (query) for (const [kind,route] of [['events','calendar'],['tasks','tasks'],['shopping','shopping'],['trips','trips']]) for (const item of data[kind]||[]) {
        if ((item.title+' '+(item.location||'')+' '+(item.destination||'')+' '+(item.note||'')).toLocaleLowerCase().includes(query)) rows.push({kind,route,item});
      }
      document.querySelector('#ps-search-results').innerHTML=!query?'<p class="help">输入关键词，快速找到要处理的事。</p>':rows.length?rows.slice(0,40).map(({kind,route,item})=>`<button class="ps-search-result" data-ps-result="${kind}" data-ps-result-id="${esc(item.id)}" data-ps-route-target="${route}">${glyph(ROUTES[route][1])}<span><strong>${esc(item.title)}</strong><small>${ROUTES[route][0]}${item.start?' · '+displayDate(item.start):item.due?' · '+displayDate(item.due):''}${item.location?' · '+esc(item.location):''}</small></span>${glyph('arrow')}</button>`).join('')+(rows.length>40?'<p class="help">显示前 40 项，请缩小关键词范围。</p>':''):'<div class="ps-empty-state"><h2>还没有找到</h2><p>换个关键词，或去对应工作台添加一项。</p></div>';
    };
  }
  async function openModule(moduleName,id='') {
    if (isTV) return;
    if (isDemo && ['JourneyUI','HomeAssistant'].includes(moduleName) && typeof root[moduleName]?.open==='function') {await root[moduleName].open(id || undefined);return;}
    if (isDemo) {
      if (moduleName==='JourneyUI') { manage('trips');return; }
      if (moduleName==='FinanceHub') {if(!isTV&&window.FinanceHub)await FinanceHub.open(id||'ledger');return; }
      if (moduleName==='HomeAssistant') { openModal('家庭助理 · 演示',`<div class="ps-empty-state">${glyph('spark')}<h2>从想法，走到下一步</h2><p>登录后，把日程、旅行和采购的想法告诉助理，先审阅计划，再确认执行。</p><a href="/" class="ps-button primary">登录并开始</a></div>`);return; }
      if (moduleName==='HouseholdSpaces') {openModal('家庭空间 · 演示','<p class="help">演示使用虚构的双成员家庭。登录后可管理自己的家庭空间。</p>');return;}
    }
    if (moduleName==='HouseholdRoutines' && !isDemo && root.HouseholdRoutines) { await root.HouseholdRoutines.open({planId:id || undefined});return; }
    if (root[moduleName] && typeof root[moduleName].open==='function') { await root[moduleName].open(id || undefined);return; }
    if (moduleName==='JourneyUI') {manage('trips');return;}
    if (moduleName==='FinanceHub') {await FinanceBaseline.openPrivate();return;}
    // Explicitly unavailable until the independent feature is installed; no simulated write.
    openModal(moduleName==='HouseholdSpaces'?'家庭空间':'家庭助理','<p class="help">这个工作台尚未加载完成。刷新页面后重试，已有日程、待办和采购仍可正常使用。</p>');
  }
  document.addEventListener('click',async event=>{
    const target=event.target.closest('[data-ps-route],[data-ps-preferences],[data-ps-layout],[data-ps-search],[data-ps-create],[data-ps-more],[data-ps-filter],[data-ps-module],[data-ps-result]');
    if (!target || isTV) return;
    event.preventDefault();
    try {
      if (target.hasAttribute('data-ps-route')) navigate(target.dataset.psRoute);
      else if (target.hasAttribute('data-ps-preferences')) openPreferences();
      else if (target.hasAttribute('data-ps-layout')) await openLayout();
      else if (target.hasAttribute('data-ps-search')) openSearch();
      else if (target.hasAttribute('data-ps-create')) openCreate();
      else if (target.hasAttribute('data-ps-more')) {navExpanded=!navExpanded;renderBoard();}
      else if (target.hasAttribute('data-ps-filter')) {if(target.dataset.psKind==='shopping')shoppingFilter=target.dataset.psFilter;else taskFilter=target.dataset.psFilter;renderBoard();}
      else if (target.hasAttribute('data-ps-module')) await openModule(target.dataset.psModule,target.dataset.psId || '');
      else if (target.hasAttribute('data-ps-result')) {const item=(data[target.dataset.psResult]||[]).find(i=>i.id===target.dataset.psResultId);navigate(target.dataset.psRouteTarget);if(item&&target.dataset.psResult==='events')CalendarViews.openManager(dateKey(item.start));else if(item&&canEdit()&&!item.sync)editItem(target.dataset.psResult,item.id);}
    } catch (err) { toast(err.message || '暂时无法打开，请稍后重试',true); }
  });
  document.addEventListener('input',event=>{if(event.target.matches('[data-ps-list-search]')){searchText=event.target.value;renderBoard();}});
  document.addEventListener('change',event=>{if(event.target.matches('[data-ps-focus]') && (data?.people||[]).some(p=>p.id===event.target.value)){focus=event.target.value;try{localStorage.setItem('household_focus',focus)}catch(_){}renderBoard();}});
  document.addEventListener('keydown',event=>{
    if ((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'&&data&&!isTV) {event.preventDefault();openSearch();}
    if (event.key==='Escape'&&navExpanded) {navExpanded=false;renderBoard();}
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&user&&!isTV&&!isDemo){void refreshPreferences(true);void refreshLayout(true).catch(()=>{});}});
  window.addEventListener('popstate',()=>{if(data&&!isTV)navigate(routeFromLocation(),false);});
  setInterval(()=>{if(!document.hidden&&user&&!isTV&&!isDemo){void refreshPreferences();void refreshLayout().catch(()=>{});}},60000);
  setTheme(DEFAULTS);
  root.ProductShell={navigate,openTasks,openPreferences,openLayout,openSearch,refreshPreferences,refreshLayout,getLayout:()=>normalizedLayout(dashboardLayout),refresh(){renderBoard();},getPreferences:()=>({...prefs}),getRoute:()=>currentRoute};
})(window);
