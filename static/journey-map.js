/* Member-only place map. Same-origin data; no map SDK, tiles or geocoding. */
window.JourneyMap = (() => {
  'use strict';
  let current = null, serial = 0, landPromise = null;
  const statuses = {visited:'已到访', planned:'已计划', wish:'心愿'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const actor = () => ({id:user?.id, household:user?.householdId || 'default', version:user?.auth_version, csrf});
  const same = (a, u, token) => u?.role === 'member' && a.id === u.id && a.household === (u.householdId || 'default') && a.version === u.auth_version && a.csrf === token;
  const permitted = () => !isTV && !isDemo && canEdit();
  const connected = f => current === f && !f.dead && f.node.isConnected && (!f.dialog || f.dialog.open) && location.href === f.route;
  const button = (action, label, extra = '') => `<button type="button" class="jm-button" data-jm="${action}" ${extra}>${label}</button>`;
  const option = (value, label, chosen) => `<option value="${escape(value)}" ${String(chosen ?? '') === String(value) ? 'selected' : ''}>${escape(label)}</option>`;
  const point = c => c && Number.isFinite(c.latitude) && Number.isFinite(c.longitude) && Math.abs(c.latitude) <= 90 && Math.abs(c.longitude) <= 180;
  const xy = c => [(c.longitude + 180) / 360 * 1000, (90 - c.latitude) / 180 * 500];
  const coordinates = c => point(c) ? `${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)}` : '不显示坐标';
  // Navigation keeps only query values and IDs, never place DTOs or coordinates.
  function viewState(value = {}) {
    const filters = {scope:'visible'};
    for (const key of ['scope','status','year','owner','journeyId']) {
      if (typeof value.filters?.[key] === 'string' && value.filters[key].length <= 100) filters[key] = value.filters[key];
    }
    return {filters,offset:Number.isInteger(value.offset) && value.offset >= 0 && value.offset <= 3000 ? value.offset : 0,
      selected:typeof value.selected === 'string' && /^[a-f0-9]{24}$/.test(value.selected) ? value.selected : null};
  }

  function unmount(message = '') {
    const f = current;
    if (!f) return;
    current = null; serial++; f.dead = true; f.epoch++;
    f.observer?.disconnect(); f.resize?.disconnect();
    f.node.removeEventListener('click', f.click); f.node.removeEventListener('input', f.input);
    f.node.removeEventListener('change', f.change); f.node.removeEventListener('submit', f.submit);
    f.node.removeEventListener('keydown', f.keydown);
    f.dialog?.removeEventListener('close',f.close);
    window.removeEventListener('offline',f.offline); window.removeEventListener('online',f.online);
    f.node.replaceChildren();
    if (message) {const p = document.createElement('p'); p.setAttribute('role','alert'); p.textContent = message; f.node.append(p);}
    if (f.editor) {
      // In-flight callbacks may still hold this object; release its private data too.
      if (f.editor.pending) f.editor.pending.body = {};
      f.editor.draft = {}; f.editor.original = null; f.editor.conflict = null; f.editor.pending = null;
      f.editor.requestId = ''; f.editor.savedId = null;
    }
    f.items = []; f.people = []; f.journeys = []; f.editor = null; f.selected = null; f.filters = {};
  }
  const notifyIdentityChanged = () => {current?.options.onIdentityChanged?.(); unmount('登录成员或家庭已变化，地点已收起。请重新进入地图。');};
  function local(f) {
    if (!connected(f)) return false;
    if (!permitted() || !same(f.actor, user, csrf)) {notifyIdentityChanged(); return false;}
    return true;
  }
  function notifyStateChanged() {
    if (current && (!current.node.isConnected || !local(current))) unmount();
  }
  async function verify(f, epoch) {
    if (!local(f) || epoch !== f.epoch) return false;
    if (!navigator.onLine) throw new Error('网络已断开，请恢复连接后重新读取。');
    const me = await api('/me');
    if (!local(f) || epoch !== f.epoch) return false;
    if (!same(f.actor, me.user, me.csrf)) {notifyIdentityChanged(); return false;}
    return true;
  }
  async function job(f, work, failure) {
    if (!local(f)) return;
    const epoch = ++f.epoch;
    const active = () => local(f) && epoch === f.epoch;
    const check = () => verify(f, epoch);
    try {if (await check()) await work({active, check});}
    catch (error) {
      if (!active()) return;
      if (error.status === 401) {notifyIdentityChanged(); return;}
      try {if (!await check()) return;} catch (_) {
        if (active()) failure(new Error('暂时无法核对登录状态，已有草稿仍保留。请恢复连接后重试。'));
        return;
      }
      if (active()) failure(error);
    }
  }

  async function land() {
    if (!landPromise) landPromise = (async () => {
      const response = await fetch('/static/journey-map-land.geojson', {credentials:'same-origin', cache:'force-cache'});
      if (!response.ok) throw new Error('底图暂不可用');
      const value = await response.json();
      if (value?.type !== 'FeatureCollection' || !Array.isArray(value.features) || value.features.length > 1000) throw new Error('底图格式无效');
      let vertices = 0;
      return value.features.map(feature => {
        const geometry = feature.geometry;
        const polygons = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : [];
        return polygons.flatMap(polygon => polygon.map(ring => ring.map((coordinate, index) => {
          if (++vertices > 100000 || !Array.isArray(coordinate) || !point({longitude:coordinate[0],latitude:coordinate[1]})) throw new Error('底图坐标无效');
          const [x,y] = xy({longitude:coordinate[0],latitude:coordinate[1]});
          return `${index ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
        }).join('') + 'Z')).join('');
      }).join('');
    })().catch(error => {landPromise = null; throw error;});
    return landPromise;
  }

  function filtersMarkup(f) {
    const labels = Object.entries(statuses).map(([key,label]) => option(key,label,f.filters.status)).join('');
    return `<form class="jm-filters" data-jm-filters>
      <label>状态<select name="status">${option('','全部状态',f.filters.status)}${labels}</select></label>
      <label>年份<input name="year" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" placeholder="全部年份" value="${escape(f.filters.year)}"></label>
      <label>记录成员<select name="owner">${option('','全部成员',f.filters.owner)}${f.people.map(p => option(p.id,p.name,f.filters.owner)).join('')}</select></label>
      <label>旅行<select name="journeyId">${option('','全部旅行',f.filters.journeyId)}${f.journeys.map(j => option(j.id,j.trip?.title || j.plan?.title || '旅行',f.filters.journeyId)).join('')}</select></label>
      <label>可见范围<select name="scope">${option('visible','我能查看的',f.filters.scope)}${option('mine','我记录的',f.filters.scope)}${option('shared','家庭共享',f.filters.scope)}</select></label>
      <button class="jm-button" type="submit" ${f.busy ? 'disabled' : ''}>应用筛选</button>${button('reset','清除筛选',f.busy ? 'disabled' : '')}${button('refresh','重新读取',f.busy || f.editor?.busy ? 'disabled' : '')}</form>`;
  }

  function mapMarkup(f) {
    const picking = f.editor?.picking;
    const scale = 1000 / Math.max(280, f.node.querySelector('.jm-map')?.clientWidth || 700);
    const markers = f.items.filter(p => point(p.coordinates)).map(p => {
      const [x,y] = xy(p.coordinates), r = 6 * scale;
      const shape = p.status === 'planned' ? `<path d="M0,${-r} L${r},${r} L${-r},${r} Z"/>` : p.status === 'wish' ? `<path d="M0,${-r} L${r},0 L0,${r} L${-r},0 Z"/>` : `<circle r="${r}"/>`;
      return `<g class="jm-marker jm-${escape(p.status)} ${f.selected === p.id ? 'is-selected' : ''}" transform="translate(${x},${y})" ${picking ? '' : `role="button" tabindex="0" data-jm="select" data-id="${escape(p.id)}" aria-label="${escape(p.name)}，${escape(statuses[p.status] || '')}"`}><circle class="jm-hit" r="${22 * scale}"/>${shape}</g>`;
    }).join('');
    const cursor = f.editor?.cursor || {latitude:0,longitude:0}, [cx,cy] = xy(cursor);
    return `<div class="jm-map" data-jm-map><svg viewBox="0 0 1000 500" ${picking ? 'tabindex="0" role="application" aria-label="选择地点坐标。方向键移动，Shift加速，Enter选定，Escape退出选择。"' : 'role="group" aria-label="世界概览，地点详情可在下方列表访问"'}>
      <rect class="jm-water" width="1000" height="500"/><path class="jm-graticule" d="M0,250H1000 M500,0V500 M0,125H1000 M0,375H1000"/>
      ${f.landPath ? `<path class="jm-land" d="${f.landPath}"/>` : ''}${markers}
      ${picking ? `<g class="jm-cursor" transform="translate(${cx},${cy})"><path d="M-14,0H14 M0,-14V14"/><circle r="9"/></g>` : ''}</svg></div>
      <p class="jm-map-note">${picking ? '点选地图，或用方向键移动、Enter选定。世界概览只能粗略选点，请核对经纬度。' : '地图仅显示当前筛选、本页已取得的地点。无坐标地点仍可在列表查看。'}</p>
      <p class="jm-map-note">Natural Earth · 公共领域海陆底图 · 世界概览，不提供街道导航或自动地理编码。${f.landError ? '底图暂不可用，地点列表与录入仍可使用。' : ''}</p>`;
  }

  function detailMarkup(f) {
    const p = f.items.find(item => item.id === f.selected);
    if (!p) return '<section class="jm-detail"><h3>选择一个地点</h3><p>从地图或列表查看地点、共享范围与关联旅行，也可以记录一个心愿目的地。</p></section>';
    const precision = p.coordinatePrecision === 'approximate' ? '约略坐标（0.1°网格，不是城市定位）' : p.coordinatePrecision === 'exact' ? '精确坐标' : p.coordinatePrecision === 'hidden' ? '坐标未共享' : '尚未填写坐标';
    return `<section class="jm-detail"><span class="jm-badge">${escape(statuses[p.status])}</span><h3>${escape(p.name)}</h3><p>${escape([p.country,p.city].filter(Boolean).join(' · ') || '国家与城市待补充')}</p>
      <dl><dt>日期</dt><dd>${escape(p.startDate || '未排期')}${p.endDate ? ' — '+escape(p.endDate) : ''}</dd><dt>记录成员</dt><dd>${escape(f.people.find(v => v.id === p.owner)?.name || '家庭成员')}</dd><dt>可见范围</dt><dd>${p.visibility === 'private' ? '仅自己' : '家庭共享'}</dd><dt>${precision}</dt><dd>${escape(coordinates(p.coordinates))}</dd></dl>
      ${p.canManage ? `<p class="jm-help">其他成员看到：${escape(coordinates(p.sharedCoordinates))}${p.sharedCoordinatePrecision === 'approximate' ? '（约略网格）' : ''}${p.visibility === 'private' ? '；目前仅自己可见。' : '。'}</p>` : '<p class="jm-help">这是家庭成员共享的地点，仅记录者可以修改或删除。</p>'}
      ${p.status === 'visited' ? `<p class="jm-help">到访已由成员明确确认${p.visitedConfirmedAt ? ' · '+escape(p.visitedConfirmedAt.slice(0,10)) : ''}。</p>` : ''}
      <div class="jm-actions">${p.canManage ? button('edit','编辑地点') : ''}${p.journey ? button('journey','打开关联旅行') : ''}${p.journey && typeof f.options.openPhotos === 'function' ? button('photos','查看这次旅行的照片') : ''}</div></section>`;
  }

  const input = (label, name, value, attrs = '') => `<label>${label}<input name="${name}" value="${escape(value)}" ${attrs}></label>`;
  function editorMarkup(f) {
    const e = f.editor, d = e.draft;
    const locked = e.busy || !!e.pending || !!e.savedId || !!e.conflict;
    return `<section class="jm-detail"><h3>${e.original ? '编辑地点' : '记录新地点'}</h3><form data-jm-editor><fieldset ${locked ? 'disabled' : ''}>
      ${input('地点名称','name',d.name,'required maxlength="160"')}
      <div class="jm-fields">${input('国家 / 地区','country',d.country,'maxlength="100"')}${input('城市','city',d.city,'maxlength="100"')}</div>
      <label>状态<select name="status">${Object.entries(statuses).map(([key,label]) => option(key,label,d.status)).join('')}</select></label>
      <div class="jm-fields">${input('开始日期','startDate',d.startDate,'type="date"')}${input('结束日期','endDate',d.endDate,'type="date"')}</div>
      <label>关联旅行<select name="journeyId">${option('','不关联旅行',d.journeyId)}${d.journeyId && !f.journeys.some(j => j.id === d.journeyId) ? option(d.journeyId,e.original?.journey?.title || '已关联旅行（选项暂未取得）',d.journeyId) : ''}${f.journeys.map(j => option(j.id,j.trip?.title || j.plan?.title || '旅行',d.journeyId)).join('')}</select></label>
      <div class="jm-fields">${input('纬度（-90 至 90）','latitude',d.latitude,'type="number" min="-90" max="90" step="0.000001"')}${input('经度（-180 至 180）','longitude',d.longitude,'type="number" min="-180" max="180" step="0.000001"')}</div>
      <div class="jm-actions">${button('pick',e.picking ? '结束地图选点' : '在地图上选位置')}${button('clear-coordinates','清空坐标')}</div>
      <label>谁能查看<select name="visibility">${option('private','仅自己（默认）',d.visibility)}${option('shared','同家庭成员',d.visibility)}</select></label>
      <label>共享时的位置精度<select name="coordinateDisclosure">${option('hidden','隐藏坐标（默认）',d.coordinateDisclosure)}${option('coarse','约略位置（0.1°网格）',d.coordinateDisclosure)}${option('exact','精确坐标',d.coordinateDisclosure)}</select></label>
      <p class="jm-help" data-jm-preview></p><p class="jm-help">共享地点的名称、国家、城市和日期也会公开；这些文字中的住址不会自动隐藏。此版本不向电视开放地点。</p>
      <label class="jm-check" data-jm-visited ${d.status === 'visited' ? '' : 'hidden'}><input name="confirmVisited" type="checkbox" ${d.confirmVisited ? 'checked' : ''}>我确认确实到访过此地点，不能仅凭预订、照片或过去的日期认定到访。</label>
      </fieldset><p class="jm-error" role="alert">${escape(e.error || '')}</p><p class="jm-notice" role="status">${escape(e.notice || '')}</p>
      ${e.conflict ? `<div class="jm-conflict"><h4>服务器上的最新记录</h4><p>${escape(e.conflict.name)} · ${escape(statuses[e.conflict.status])} · 版本 ${e.conflict.revision}</p>${button('use-latest','使用最新记录')}${button('keep-draft','保留草稿，按最新版本再保存')}<p>不会自动覆盖；保留草稿后仍须再次保存。</p></div>` : ''}
      <div class="jm-actions">${e.savedId ? button('read-saved','重新读取已保存地点',e.busy || f.busy ? 'disabled' : '') : e.pending ? button('retry-pending',e.pending.method === 'PATCH' || e.conflictWanted ? '读取当前记录' : '核对原提交',e.busy || f.busy ? 'disabled' : '') : `<button class="jm-button jm-primary" type="submit" ${e.busy || f.busy || e.conflict ? 'disabled' : ''}>${e.busy ? '正在核对…' : '保存地点'}</button>`}
      ${button('cancel','返回地点',e.busy ? 'disabled' : '')}${e.original && !locked ? button('delete','删除地点') : ''}</div>
      ${e.deleteConfirm ? `<div class="jm-conflict"><p>删除“${escape(e.original.name)}”？只删除这条地点记录，关联旅行保留。已发送的请求不能通过关闭页面取消。</p>${button('confirm-delete','确认删除')}${button('cancel-delete','保留地点')}</div>` : ''}</form></section>`;
  }

  function sharedPreview(f) {
    const e = f.editor, box = f.node.querySelector('[data-jm-preview]');
    if (!e || !box) return;
    const d = e.draft;
    if (d.visibility === 'private') box.textContent = '共享预览：目前仅自己可见，其他成员看不到这条地点。';
    else if (!d.latitude || !d.longitude || d.coordinateDisclosure === 'hidden') box.textContent = '共享预览：其他成员可看地点文字，不显示坐标。';
    else if (d.coordinateDisclosure === 'coarse') box.textContent = '共享预览：其他成员仅获得约略的 0.1° 网格坐标；保存后显示服务器实际投影。自己保留原坐标。';
    else box.textContent = `共享预览：其他成员可看精确经纬度 ${d.latitude}, ${d.longitude}，以及地点文字。`;
    const visited = f.node.querySelector('[data-jm-visited]');
    if (visited) visited.hidden = d.status !== 'visited';
  }

  function render(f) {
    if (!local(f)) return;
    const focused = f.node.contains(document.activeElement) ? document.activeElement : null;
    const field = focused?.name, start = focused?.selectionStart, end = focused?.selectionEnd;
    const focusedForm = focused?.closest('[data-jm-editor]') ? '[data-jm-editor]' : '[data-jm-filters]';
    const focusedId = focused?.dataset.id, focusedAction = focused?.dataset.jm;
    const noCoordinates = f.items.filter(p => !point(p.coordinates)).length;
    f.node.classList.add('journey-map');
    f.node.innerHTML = `<header class="jm-heading"><div><span class="jm-kicker">家庭足迹</span><h2>去过的地方，想去的下一站。</h2><p>把已到访、已计划和心愿地点放在同一张地图里。</p></div>${button('new','记录地点',f.busy || f.editor?.busy ? 'disabled' : '')}</header>
      ${filtersMarkup(f)}<p class="jm-status" role="status">${f.busy ? '正在读取地点…' : `共 ${f.total} 条符合条件；本页 ${f.items.length} 条，其中 ${noCoordinates} 条无可见坐标。`}${f.notice ? ' '+escape(f.notice) : ''}</p>
      ${f.error ? `<p class="jm-error" role="alert">${escape(f.error)} 请使用“重新读取”重试。</p>` : ''}${f.contextError ? '<p class="jm-help">成员或旅行选项暂未完整取得，可重试读取后再关联。</p>' : ''}
      <div class="jm-workspace"><section class="jm-overview">${mapMarkup(f)}<div class="jm-legend"><span>● 已到访</span><span>▲ 已计划</span><span>◆ 心愿</span></div>
      <div class="jm-list" aria-label="本页地点">${f.items.length ? f.items.map(p => `<button class="jm-place ${f.selected === p.id ? 'is-selected' : ''}" type="button" data-jm="select" data-id="${escape(p.id)}" aria-pressed="${f.selected === p.id}"><span class="jm-badge">${escape(statuses[p.status])}</span><strong>${escape(p.name)}</strong><small>${escape([p.country,p.city].filter(Boolean).join(' · ') || '地点待补充')} · ${p.visibility === 'private' ? '仅自己' : '家庭共享'}${!point(p.coordinates) ? ' · 无可见坐标' : ''}</small></button>`).join('') : `<div class="jm-empty"><h3>${f.busy ? '地点读取中' : '这里还没有地点'}</h3><p>${f.busy ? '请稍候。' : '调整筛选，或记录第一个心愿目的地。不会从照片或预订自动认定到访。'}</p></div>`}</div>
      <div class="jm-pagination">${button('previous','上一页',f.busy || f.offset === 0 ? 'disabled' : '')}<span>第 ${Math.floor(f.offset / 100) + 1} 页</span>${button('next','下一页',f.busy || !f.hasMore ? 'disabled' : '')}</div><p class="jm-help">每页最多 100 条；数据变化后请重新读取，分页不代表同一时刻的历史快照。</p></section>
      ${f.editor ? editorMarkup(f) : detailMarkup(f)}</div>`;
    sharedPreview(f);
    resizeMarkers(f);
    if (field) {const target = f.node.querySelector(`${focusedForm} [name="${CSS.escape(field)}"]`); if (target) {target.focus({preventScroll:true}); if (start !== null && ['text','textarea',''].includes(target.type)) try {target.setSelectionRange(start,end);} catch (_) {}}}
    else if (focusedAction) f.node.querySelector(`[data-jm="${CSS.escape(focusedAction)}"]${focusedId ? `[data-id="${CSS.escape(focusedId)}"]` : ''}`)?.focus({preventScroll:true});
  }
  function resizeMarkers(f) {
    const width = f.node.querySelector('.jm-map')?.clientWidth;
    if (width) f.node.querySelectorAll('.jm-marker .jm-hit').forEach(hit => hit.setAttribute('r',String(22 * 1000 / width)));
  }

  async function load(f, context = false) {
    if (!local(f) || f.editor?.busy) return;
    f.busy = true; f.error = ''; f.items = []; f.total = 0; f.hasMore = false; render(f);
    await job(f, async flow => {
      const query = new URLSearchParams({limit:'100',offset:String(f.offset)});
      for (const [key,value] of Object.entries(f.filters)) if (value) query.set(key,value);
      const jobs = [api('/journey-places?' + query)];
      if (context) jobs.push(api('/state'),api('/journeys'),land());
      const results = await Promise.allSettled(jobs);
      if (!await flow.check()) return;
      if (results[0].status === 'rejected') throw results[0].reason;
      const result = results[0].value;
      if (!Array.isArray(result?.items) || !Number.isInteger(result.total)) throw new Error('地点返回格式无效，请重试。');
      f.items = [...new Map(result.items.map(p => [p.id,p])).values()]; f.total = result.total; f.hasMore = result.hasMore === true; f.busy = false;
      if (context) {
        if (results[1].status === 'fulfilled') f.people = results[1].value.people || [];
        if (results[2].status === 'fulfilled') f.journeys = results[2].value.journeys || [];
        f.contextError = results[1].status === 'rejected' || results[2].status === 'rejected';
        f.landPath = results[3].status === 'fulfilled' ? results[3].value : '';
        f.landError = results[3].status === 'rejected';
      }
      if (!f.items.some(p => p.id === f.selected)) f.selected = null;
      render(f);
    }, error => {f.busy = false; f.error = error.message || '地点暂时无法读取，请重试。'; render(f);});
  }

  function discard(f) {
    if (f.editor?.busy) return false;
    return !f.editor || (!f.editor.dirty && !f.editor.pending) || window.confirm('放弃当前地点草稿？已经发送的请求不会被取消，返回后请重新读取核对。');
  }
  function edit(f, original = null) {
    if (!discard(f) || (original && !original.canManage)) return;
    f.navigationIntent++;
    const p = original || {};
    f.editor = {original, requestId:crypto.randomUUID(), dirty:false, busy:false, draft:{
      name:p.name || '', country:p.country || '', city:p.city || '', status:p.status || 'wish',
      startDate:p.startDate || '', endDate:p.endDate || '', journeyId:p.journeyId || '',
      latitude:point(p.coordinates) ? String(p.coordinates.latitude) : '', longitude:point(p.coordinates) ? String(p.coordinates.longitude) : '',
      visibility:p.visibility || 'private', coordinateDisclosure:p.coordinateDisclosure || 'hidden', confirmVisited:false}};
    render(f); f.node.querySelector('[name=name]')?.focus();
  }
  function payload(e) {
    const d = e.draft, lat = d.latitude.trim(), lon = d.longitude.trim();
    if (!!lat !== !!lon) throw new Error('纬度和经度需要一起填写，或一起留空。');
    const c = lat ? {latitude:Number(lat),longitude:Number(lon)} : null;
    if (c && !point(c)) throw new Error('请填写有效的经纬度。');
    if (d.endDate && (!d.startDate || d.endDate < d.startDate)) throw new Error('结束日期不能早于开始日期，且需要先填写开始日期。');
    const value = {name:d.name.trim(),country:d.country.trim(),city:d.city.trim(),status:d.status,
      startDate:d.startDate || null,endDate:d.endDate || null,journeyId:d.journeyId || null,coordinates:c,
      visibility:d.visibility,coordinateDisclosure:d.coordinateDisclosure,confirmVisited:d.status === 'visited' && d.confirmVisited === true};
    const changedVisit = !e.original || e.original.status !== 'visited' || ['name','country','city','startDate','endDate','journeyId','coordinates'].some(key => JSON.stringify(value[key]) !== JSON.stringify(e.original[key] ?? null));
    if (value.status === 'visited' && changedVisit && !value.confirmVisited) throw new Error('请明确确认已经到访，不能仅凭日期或预订认定。');
    return value;
  }
  async function readSaved(f) {
    const e = f.editor;
    if (!e?.savedId || e.busy || f.busy) return;
    e.busy = true; e.error = ''; render(f);
    await job(f, async flow => {
      const result = await api('/journey-places/' + encodeURIComponent(e.savedId));
      if (!await flow.check()) return;
      if (!result?.place || result.place.id !== e.savedId) throw new Error('地点读回格式无效。');
      e.busy = false; e.notice = '已保存并读取确认。'; e.pending = null; e.dirty = false;
      e.original = result.place; f.selected = result.place.id;
      f.items = [result.place,...f.items.filter(p => p.id !== result.place.id)];
      // Refresh the actual filter/page before claiming its count or map scope.
      f.notice = '地点已保存并读取确认。'; f.editor = null; await load(f, true);
    }, error => {e.busy = false; e.error = '提交已成功，但读回暂未完成。这里只会重新读取，不会再次创建。' + (error.status === 404 ? '记录目前已不可访问。' : ''); render(f);});
  }
  async function readConflict(f) {
    const e = f.editor;
    if (!e?.original || e.busy || f.busy) return;
    e.busy = true; e.error = ''; render(f);
    await job(f, async flow => {
      const result = await api('/journey-places/' + encodeURIComponent(e.original.id));
      if (!await flow.check()) return;
      if (!result?.place || result.place.id !== e.original.id || !result.place.canManage) throw new Error('当前记录无法编辑，请重新读取列表核对权限。');
      e.busy = false; e.pending = null; e.conflictWanted = false; e.conflict = result.place; e.notice = '已读取当前版本，请与草稿核对。'; render(f);
    }, error => {e.busy = false; e.error = error.message || '当前记录暂不可读取，草稿仍保留。'; render(f);});
  }
  async function submit(f, pending = null) {
    const e = f.editor;
    if (!e || e.busy || f.busy || e.savedId || e.conflict) return;
    let request = pending;
    if (!request) {
      try {const value = payload(e); request = {method:e.original ? 'PATCH' : 'POST', path:'/journey-places' + (e.original ? '/'+encodeURIComponent(e.original.id) : ''), body:e.original ? {...value,revision:e.original.revision} : {...value,requestId:e.requestId}};}
      catch (error) {e.error = error.message; render(f); return;}
    }
    e.busy = true; e.error = ''; e.pending = request; e.deleteConfirm = false; render(f);
    await job(f, async flow => {
      // request captures the exact payload and ID for an uncertain result retry.
      const result = await api(request.path, {method:request.method,body:JSON.stringify(request.body)});
      if (!await flow.check()) return;
      e.busy = false;
      if (request.method === 'DELETE') {
        if (result?.deleted !== true || result.id !== e.original.id) throw new Error('删除结果尚未确认，请核对原提交。');
        e.pending = null; f.notice = '地点已删除，关联旅行保留。'; f.editor = null; f.selected = null; await load(f, true); return;
      }
      if (!result?.place?.id) throw new Error('保存结果尚未确认，请核对原提交。');
      e.pending = null;
      e.savedId = result.place.id; await readSaved(f);
    }, error => {
      e.busy = false; e.error = error.message || '结果尚未确认，请核对原提交。';
      if (error.status && error.status < 500) e.pending = null;
      if (error.status === 409 && e.original) {e.notice = '记录已有变化。先读取当前记录，再明确选择保留草稿或使用最新记录。'; e.pending = request; e.conflictWanted = true;}
      if (error.status === 410) e.notice = '这次创建曾成功但记录已经删除，不会用原请求重新创建。请返回并重新读取。';
      render(f);
    });
  }

  function pick(f, coordinate) {
    const e = f.editor;
    if (!e?.picking || e.busy) return;
    e.draft.latitude = String(Number(coordinate.latitude.toFixed(6))); e.draft.longitude = String(Number(coordinate.longitude.toFixed(6)));
    e.draft.confirmVisited = false; e.picking = false; e.dirty = true; render(f); f.node.querySelector('[name=latitude]')?.focus();
  }
  async function click(f, event) {
    if (!local(f)) return;
    const target = event.target.closest('[data-jm]');
    if (!target && f.editor?.picking) {
      const svg = event.target.closest('[data-jm-map] svg');
      if (svg) {const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY; const coordinate = p.matrixTransform(svg.getScreenCTM().inverse()); pick(f,{longitude:Math.max(-180,Math.min(180,coordinate.x / 1000 * 360 - 180)),latitude:Math.max(-90,Math.min(90,90 - coordinate.y / 500 * 180))});}
      return;
    }
    if (!target || !f.node.contains(target) || target.disabled) return;
    const action = target.dataset.jm, e = f.editor;
    if (action === 'new') {edit(f); return;}
    if (action === 'select') {if (!discard(f)) return; f.navigationIntent++; f.editor = null; f.selected = target.dataset.id; render(f); return;}
    if (action === 'edit') {edit(f,f.items.find(p => p.id === f.selected)); return;}
    if (action === 'journey') {const p = f.items.find(item => item.id === f.selected); if (p?.journey && typeof f.options.openJourney === 'function') await job(f,async flow => {if (await flow.check()) await f.options.openJourney(p.journey.id,{placeId:p.id});}, error => {f.error=error.message;render(f);}); return;}
    if (action === 'photos') {
      const selected = f.selected;
      if (f.busy || !selected || typeof f.options.openPhotos !== 'function') return;
      const intent = ++f.navigationIntent;
      const wanted = () => f.navigationIntent === intent && f.selected === selected && !f.editor;
      await job(f,async flow => {
        const {place} = await api('/journey-places/' + encodeURIComponent(selected));
        if (!wanted() || !await flow.check() || !wanted()) return;
        if (!place?.journey?.id) {await load(f,true); return;}
        f.options.openPhotos(place.journey.id,viewState(f));
      },error => {if (!wanted()) return; f.items = []; f.total = 0; f.hasMore = false; f.selected = null; f.error = error.message; render(f);});
      return;
    }
    if (action === 'refresh' || action === 'reset' || action === 'next' || action === 'previous') {
      if (f.busy || e?.busy) return;
      if (action === 'reset') {f.filters = {scope:'visible'}; f.offset = 0;}
      if (action === 'next') f.offset += 100;
      if (action === 'previous') f.offset = Math.max(0,f.offset-100);
      await load(f,action === 'refresh'); return;
    }
    if (!e || e.busy) return;
    if (action === 'cancel') {if (discard(f)) {f.editor = null; render(f);} return;}
    if (action === 'read-saved') {await readSaved(f); return;}
    if (action === 'retry-pending') {if (e.conflictWanted || e.pending?.method === 'PATCH' || e.error && e.original && !e.pending) await readConflict(f); else if (e.pending) await submit(f,e.pending); return;}
    if (action === 'use-latest') {const p = e.conflict; e.dirty = false; e.pending = null; edit(f,p); return;}
    if (action === 'keep-draft') {e.original = e.conflict; e.conflict = null; e.pending = null; e.error = ''; e.notice = '草稿已保留，请核对后再次保存。'; render(f); return;}
    if (action === 'delete') {e.deleteConfirm = true; render(f); return;}
    if (action === 'cancel-delete') {e.deleteConfirm = false; render(f); return;}
    if (action === 'confirm-delete') {await submit(f,{method:'DELETE',path:'/journey-places/'+encodeURIComponent(e.original.id),body:{revision:e.original.revision}}); return;}
    if (action === 'clear-coordinates') {e.draft.latitude = ''; e.draft.longitude = ''; e.draft.confirmVisited = false; e.dirty = true; render(f); return;}
    if (action === 'pick') {e.picking = !e.picking; e.cursor = point({latitude:Number(e.draft.latitude),longitude:Number(e.draft.longitude)}) ? {latitude:Number(e.draft.latitude),longitude:Number(e.draft.longitude)} : {latitude:0,longitude:0}; render(f); if (e.picking) f.node.querySelector('[data-jm-map] svg')?.focus();}
  }

  function mount(node, options = {}) {
    unmount();
    if (!(node instanceof HTMLElement)) return null;
    if (!permitted()) {node.textContent = isTV ? '地点仅可由登录的家庭成员在手机或电脑查看，电视没有访问权限。' : '请登录家庭成员后查看地图；演示空间不保存地点。'; return null;}
    const f = {node,options,actor:actor(),route:location.href,serial:++serial,epoch:0,navigationIntent:0,dead:false,items:[],people:[],journeys:[],filters:{scope:'visible'},offset:0,total:0,hasMore:false,selected:null,editor:null,landPath:''};
    Object.assign(f,viewState(options.initialView));
    current = f;
    f.dialog = node.closest('dialog'); f.close = () => {if (current === f) unmount();}; f.dialog?.addEventListener('close',f.close);
    f.click = event => {void click(f,event);};
    f.input = event => {
      if (!local(f) || !f.editor || f.editor.busy || f.editor.pending || !event.target.closest('[data-jm-editor]')) return;
      const name = event.target.name;
      if (Object.hasOwn(f.editor.draft,name)) {
        f.editor.draft[name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
        if (name === 'status' && f.editor.draft.status !== 'visited') {
          f.editor.draft.confirmVisited = false;
          f.node.querySelector('[name=confirmVisited]').checked = false;
        }
        f.editor.dirty = true; sharedPreview(f);
      }
    };
    f.change = f.input;
    f.submit = event => {
      if (!local(f)) return;
      if (event.target.matches('[data-jm-editor]')) {event.preventDefault(); if (!f.editor?.pending && !f.editor?.savedId) void submit(f);}
      if (event.target.matches('[data-jm-filters]')) {event.preventDefault(); if (f.busy || f.editor?.busy) return; f.filters = Object.fromEntries(new FormData(event.target)); f.offset = 0; void load(f);}
    };
    f.keydown = event => {
      if (!local(f)) return;
      const marker = event.target.closest('[data-jm=select]');
      if (marker && event.target instanceof SVGElement && ['Enter',' '].includes(event.key)) {event.preventDefault(); void click(f,{target:marker}); return;}
      if (!f.editor?.picking || !event.target.matches('[data-jm-map] svg')) return;
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter','Escape'].includes(event.key)) return;
      event.preventDefault(); const e = f.editor, step = event.shiftKey ? 10 : 1;
      if (event.key === 'Enter') {pick(f,e.cursor); return;}
      if (event.key === 'Escape') {e.picking = false; render(f); f.node.querySelector('[data-jm=pick]')?.focus(); return;}
      if (event.key === 'ArrowLeft') e.cursor.longitude = Math.max(-180,e.cursor.longitude-step);
      if (event.key === 'ArrowRight') e.cursor.longitude = Math.min(180,e.cursor.longitude+step);
      if (event.key === 'ArrowUp') e.cursor.latitude = Math.min(90,e.cursor.latitude+step);
      if (event.key === 'ArrowDown') e.cursor.latitude = Math.max(-90,e.cursor.latitude-step);
      render(f); f.node.querySelector('[data-jm-map] svg')?.focus();
    };
    node.addEventListener('click',f.click); node.addEventListener('input',f.input); node.addEventListener('change',f.change);
    node.addEventListener('submit',f.submit); node.addEventListener('keydown',f.keydown);
    f.observer = new MutationObserver(() => {if (current === f && !node.isConnected) unmount();});
    f.observer.observe(document.body,{childList:true,subtree:true});
    f.resize = new ResizeObserver(() => {if (current === f) resizeMarkers(f);}); f.resize.observe(node);
    f.offline = () => {if (!local(f) || f.editor) return; f.epoch++; f.busy = false; f.items = []; f.total = 0; f.hasMore = false; f.people = []; f.journeys = []; f.error = '网络已断开，地点已收起。恢复连接后重新读取。'; render(f);};
    f.online = () => {if (local(f) && !f.editor) void load(f,true);};
    window.addEventListener('offline',f.offline); window.addEventListener('online',f.online);
    void load(f,true);
    return {refresh:() => load(f,true),unmount:() => {if (current === f) unmount();}};
  }
  function openView(options = {}) {
    if (isTV) return;
    openModal('家庭足迹','<div data-journey-map-host></div>',true);
    return mount(document.querySelector('[data-journey-map-host]'),options);
  }
  window.addEventListener('hashchange',() => {if (current && current.route !== location.href) unmount();});
  window.addEventListener('popstate',() => {if (current && current.route !== location.href) unmount();});
  return {mount,openView,unmount,notifyIdentityChanged,notifyStateChanged};
})();
