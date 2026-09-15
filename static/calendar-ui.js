/* Household calendar views. All dates are Beijing dates, independent of device timezone. */
(function (root) {
  'use strict';
  const DAY = 86400000;
  const ZONE = 'Asia/Shanghai';
  const MODES = new Set(['today', 'week', 'around']);
  const weekNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const dayFormatter = new Intl.DateTimeFormat('sv-SE', {timeZone:ZONE, year:'numeric', month:'2-digit', day:'2-digit'});
  const timeFormatter = new Intl.DateTimeFormat('zh-CN', {timeZone:ZONE, hour:'2-digit', minute:'2-digit', hour12:false});

  function dayKey(value = new Date()) { return dayFormatter.format(new Date(value)); }
  function dayStart(day) { return Date.parse(day + 'T00:00:00+08:00'); }
  function shiftDay(day, offset) { return dayKey(dayStart(day) + offset * DAY); }
  function weekday(day) { return new Date(day + 'T12:00:00Z').getUTCDay(); }
  function rangeDays(mode, anchor = dayKey()) {
    const first = mode === 'week' ? shiftDay(anchor, -((weekday(anchor) + 6) % 7)) : mode === 'around' ? shiftDay(anchor, -3) : anchor;
    return Array.from({length:mode === 'today' ? 1 : 7}, (_, i) => shiftDay(first, i));
  }
  function bounds(event) {
    const start = event.allDay ? dayStart(String(event.start).slice(0, 10)) : Date.parse(event.start);
    const end = event.allDay ? dayStart(String(event.end).slice(0, 10)) : Date.parse(event.end);
    return {start, end};
  }
  function overlapsDay(event, day) {
    const {start, end} = bounds(event), lower = dayStart(day), upper = lower + DAY;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return false;
    if (start === end) return !event.allDay && start >= lower && start < upper;
    return start < upper && end > lower;
  }
  function eventsForDay(events, day, focused = '') {
    return events.filter(event => overlapsDay(event, day)).sort((a, b) =>
      Number(!!b.allDay) - Number(!!a.allDay) ||
      Math.max(bounds(a).start, dayStart(day)) - Math.max(bounds(b).start, dayStart(day)) ||
      Number(b.owner === focused) - Number(a.owner === focused) || String(a.id).localeCompare(String(b.id)));
  }
  function unionMinutes(intervals) {
    const sorted = intervals.filter(([start, end]) => Number.isFinite(start) && end > start).sort((a, b) => a[0] - b[0]);
    let total = 0, lower = null, upper = null;
    for (const [start, end] of sorted) {
      if (lower === null) { lower = start; upper = end; }
      else if (start <= upper) upper = Math.max(upper, end);
      else { total += upper - lower; lower = start; upper = end; }
    }
    return (total + (lower === null ? 0 : upper - lower)) / 60000;
  }
  function daySummary(events, day, focused) {
    const visible = eventsForDay(events, day, focused), relevant = visible.filter(event => event.owner === focused || event.owner === 'shared');
    const lower = dayStart(day), upper = lower + DAY;
    return {day, events:visible, total:visible.length, focusedCount:relevant.length,
      allDay:relevant.filter(event => event.allDay).length,
      busyMinutes:unionMinutes(relevant.filter(event => !event.allDay).map(event => {
        const value = bounds(event); return [Math.max(lower, value.start), Math.min(upper, value.end)];
      }))};
  }
  function rangeSummary(events, days, focused) {
    const summaries = days.map(day => daySummary(events, day, focused));
    const selected = events.filter(event => days.some(day => overlapsDay(event, day)));
    return {days:summaries, total:selected.length, busyMinutes:summaries.reduce((sum, item) => sum + item.busyMinutes, 0),
      allDay:selected.filter(event => event.allDay && (event.owner === focused || event.owner === 'shared')).length};
  }
  function timeLabel(event, day) {
    if (event.allDay) return '全天';
    const {start, end} = bounds(event), lower = dayStart(day), upper = lower + DAY;
    const beginText = start < lower ? '00:00' : timeFormatter.format(new Date(start));
    const endText = end >= upper ? '24:00' : timeFormatter.format(new Date(end));
    return beginText + (end === start ? '' : '–' + endText);
  }
  function tvPage(events, day, cycle = 0, now = Date.now(), limit = 3) {
    let ordered = events;
    if (day === dayKey(now)) {
      const allDay = events.filter(event => event.allDay), timed = events.filter(event => !event.allDay);
      const first = timed.findIndex(event => bounds(event).end >= now);
      ordered = first < 0 ? events : [...allDay, ...timed.slice(first), ...timed.slice(0, first)];
    }
    const pages = Math.max(1, Math.ceil(ordered.length / limit)), page = Math.max(0, cycle) % pages;
    return {items:ordered.slice(page * limit, page * limit + limit), page:page + 1, pages};
  }
  const helpers = {dayKey, dayStart, shiftDay, weekday, rangeDays, bounds, overlapsDay, eventsForDay, unionMinutes, daySummary, rangeSummary, timeLabel, tvPage};
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  if (typeof document === 'undefined') return;

  let mode = 'today', anchor = null, identity = null, deviceMode = null, managerOpen = false;
  const TV_PAGE_MS = 20000;
  let tvCycle = 0, tvPlaybackStart = Date.now();
  function resetTVPlayback() { tvCycle = 0; tvPlaybackStart = Date.now(); }
  const shortDate = day => `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}`;
  const duration = minutes => minutes % 60 === 0 ? `${minutes / 60}h` : `${Number((minutes / 60).toFixed(1))}h`;
  const validMode = value => MODES.has(value) ? value : 'today';
  function storageKey() { return `household_calendar_view_${isDemo ? 'demo' + (isTV ? '_tv' : '') : (user?.householdId || 'default') + '_' + (user?.id || 'guest')}`; }
  function currentMode() {
    const nextIdentity = `${isTV ? 'tv:' : 'member:'}${isDemo ? 'demo' : (user?.householdId || 'default') + ':' + (user?.id || 'guest')}`;
    if (identity !== nextIdentity) {
      identity = nextIdentity; anchor = null; deviceMode = null; resetTVPlayback();
      try { mode = !isTV || isDemo ? validMode(localStorage.getItem(storageKey())) : 'today'; } catch (_) { mode = 'today'; }
    }
    if (isTV && !isDemo) {
      const serverMode = validMode(data?.display?.calendarView || user?.calendarView);
      if (serverMode !== deviceMode) { deviceMode = serverMode; mode = serverMode; anchor = null; resetTVPlayback(); }
    }
    return mode;
  }
  function daysForCurrent() { return rangeDays(currentMode(), anchor || dayKey()); }
  function rangeLabel(days) {
    if (days.length === 1) return `${days[0].slice(0,4)} 年 ${shortDate(days[0])} · ${weekNames[weekday(days[0])]}`;
    return `${days[0].slice(0,4)} 年 ${shortDate(days[0])}—${days[0].slice(0,4) !== days[6].slice(0,4) ? days[6].slice(0,4) + '/' : ''}${shortDate(days[6])}`;
  }
  function toolbar(days) {
    const mode = currentMode(), distance = mode === 'today' ? '一天' : '七天';
    return `<div class="cv-toolbar"><div class="cv-modes" role="group" aria-label="日程显示范围">${[['today','今日'],['week','本周'],['around','前后 3 天']].map(([value,label]) => `<button type="button" data-calendar-mode="${value}" aria-pressed="${mode === value}" class="${mode === value ? 'selected' : ''}">${label}</button>`).join('')}</div><div class="cv-navigation"><button type="button" data-calendar-move="-1" class="cv-arrow" aria-label="向前${distance}">‹</button><span class="cv-range" aria-live="polite">${esc(rangeLabel(days))}</span><button type="button" data-calendar-move="1" class="cv-arrow" aria-label="向后${distance}">›</button><button type="button" data-calendar-reset class="cv-reset" ${anchor === null ? 'disabled' : ''}>回到今天</button></div></div>`;
  }
  function legend() {
    return `<div class="legend cv-legend">${(data.people || []).map(member => `<span><i class="dot ${member.id === 'member2' ? 'member2' : ''}"></i>${esc(member.name)}</span>`).join('')}<span><i class="dot shared"></i>共同</span></div>`;
  }
  function summaryMarkup(summary, days) {
    return `<div class="cv-summary"><span>共 <strong>${summary.total}</strong> 项安排</span><span>${esc(person(focus))} + 共同 <strong>${duration(summary.busyMinutes)}</strong>${summary.allDay ? ` <span class="cv-all-day">· 全天 ${summary.allDay} 项</span>` : ''}</span><small>仅统计已选日历 · 重叠时段合并 · 全天不计入时长</small></div>`;
  }
  function eventMarkup(event, day, compact, editing = false) {
    const color = event.owner === 'member2' ? 'member2' : event.owner === 'shared' ? 'shared' : 'member1';
    const continuing = !event.allDay && bounds(event).start < dayStart(day);
    const now = Date.now(), active = bounds(event).start <= now && bounds(event).end > now;
    return `<article class="cv-event ${color}${active ? ' cv-current' : ''}${compact ? ' cv-compact' : ''}"><div class="cv-event-time"><time>${esc(timeLabel(event, day))}</time>${continuing ? '<span>跨日</span>' : active && !event.allDay ? '<span>进行中</span>' : ''}${editing ? editButton('events', event) : ''}</div><strong class="cv-event-title">${esc(event.title)}</strong><div class="cv-event-location">${esc(who(event.owner))}${event.location ? ' · ' + esc(event.location) : ''}</div>${editing ? `<small class="cv-event-source">${esc(event.source || '手动')}</small>` : ''}</article>`;
  }
  function previews(events, day, limit) {
    if (events.length <= limit || day !== dayKey()) return events.slice(0, limit);
    const next = events.findIndex(event => !event.allDay && bounds(event).end >= Date.now());
    // Keep ongoing all-day context, then the next timed appointments.
    const allDay = events.filter(event => event.allDay).slice(0, Math.min(1, limit));
    const timed = events.filter(event => !event.allDay);
    const first = timed.findIndex(event => bounds(event).end >= Date.now());
    const offset = first < 0 ? Math.max(0, timed.length - (limit - allDay.length)) : first;
    const chosen = [...allDay, ...timed.slice(offset, offset + limit - allDay.length)];
    return chosen.length ? chosen : events.slice(next < 0 ? 0 : next, (next < 0 ? 0 : next) + limit);
  }
  function gridMarkup(summary) {
    const peak = Math.max(60, ...summary.days.map(day => day.busyMinutes));
    return `<div class="cv-week-scroll" role="region" aria-label="七天日程，可左右滚动" tabindex="0"><div class="cv-week-grid">${summary.days.map(day => {
      const isToday = day.day === dayKey(), page = isTV ? tvPage(day.events, day.day, tvCycle) : null, preview = page ? page.items : previews(day.events, day.day, 4);
      return `<section class="cv-day ${isToday ? 'cv-today' : ''}"><button type="button" class="cv-day-heading" data-calendar-day="${day.day}" aria-label="查看 ${day.day} 的全部 ${day.total} 项安排"><span>${weekNames[weekday(day.day)]}${isToday ? '<small>今天</small>' : ''}</span><strong>${shortDate(day.day)}</strong></button><div class="cv-day-stats"><span>${day.total} 项</span><strong>${duration(day.busyMinutes)}</strong></div><div class="cv-load" aria-hidden="true"><span style="width:${Math.round(day.busyMinutes / peak * 100)}%"></span></div>${day.allDay ? `<div class="cv-day-all-day">全天 ${day.allDay} 项 · 不计时长</div>` : ''}<div class="cv-day-events" ${isTV ? 'data-calendar-autoscroll' : ''}>${preview.length ? preview.map(event => eventMarkup(event, day.day, true)).join('') : '<p class="cv-day-empty">暂无安排</p>'}</div>${page ? tvPagination(page) : day.total > preview.length ? `<button type="button" class="cv-more" data-calendar-day="${day.day}">查看全部 ${day.total} 项 →</button>` : ''}</section>`;
    }).join('')}</div></div><p class="cv-mobile-hint">左右滑动查看七天，点日期展开完整安排</p>`;
  }
  function todayMarkup(summary, day) {
    const page = isTV ? tvPage(summary.days[0].events, day, tvCycle) : null, preview = page ? page.items : previews(summary.days[0].events, day, 4);
    return `<div class="cv-today-events" ${isTV ? 'data-calendar-autoscroll' : ''}>${preview.length ? preview.map(event => eventMarkup(event, day, false)).join('') : `<div class="cv-empty"><span>${icon('calendar')}</span><h3>${day === dayKey() ? '今天，留一点空白' : '这天还没有安排'}</h3><p>切换到本周，看一眼接下来的安排。</p></div>`}</div>${page ? tvPagination(page) : summary.total > preview.length ? `<button type="button" class="cv-more" data-calendar-day="${day}">查看全部 ${summary.total} 项安排 →</button>` : ''}`;
  }
  function tvPagination(page) {
    return `<div class="cv-tv-pagination">${page.pages > 1 ? `<span>第 ${page.page}/${page.pages} 页 · 20 秒轮换</span>` : ''}<span class="cv-tv-auto-note" hidden>长内容自动滚动</span></div>`;
  }
  function playbackTick() {
    if (!isTV || !data || document.hidden || !document.querySelector('.cv-card')) return;
    // A hidden TV resumes at its first page. Data refreshes preserve the current page and position.
    const elapsed = Math.max(0, Date.now() - tvPlaybackStart), cycle = Math.floor(elapsed / TV_PAGE_MS);
    if (cycle !== tvCycle) { tvCycle = cycle; renderBoard(); return; }
    const phase = elapsed % TV_PAGE_MS;
    // Hold the top for 3 seconds and the bottom for 3 seconds to make complete titles readable.
    const fraction = Math.max(0, Math.min(1, (phase - 3000) / 14000));
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelectorAll('[data-calendar-autoscroll]').forEach(container => {
      const extra = Math.max(0, container.scrollHeight - container.clientHeight);
      const note = container.nextElementSibling?.querySelector('.cv-tv-auto-note');
      if (note) note.hidden = extra <= 1;
      // Reduced-motion users get four still positions instead of continuous panning.
      const position = reducedMotion ? Math.floor(fraction * 4) / 4 : fraction;
      const top = Math.round(extra * position);
      if (Math.abs(container.scrollTop - top) > 1) container.scrollTop = top;
    });
  }
  function renderCard() {
    const mode = currentMode(), days = daysForCurrent(), summary = rangeSummary(data.events || [], days, focus);
    document.body.classList.toggle('calendar-expanded', mode !== 'today');
    return `<section class="card calendar-card cv-card cv-${mode}"><div class="card-heading"><h2>${mode === 'today' ? '每日安排' : mode === 'week' ? '一周安排' : '七日安排'}</h2><div class="card-actions">${legend()}${addButton('events','添加安排')}</div></div>${toolbar(days)}${summaryMarkup(summary, days)}${mode === 'today' ? todayMarkup(summary, days[0]) : gridMarkup(summary)}</section>`;
  }
  function openManager(day = '') {
    const days = day ? [day] : daysForCurrent(), summary = rangeSummary(data.events || [], days, focus);
    managerOpen = true; activeManager = 'events';
    openModal(day ? `${shortDate(day)} ${weekNames[weekday(day)]} · 完整日程` : '日程总览', `<div class="cv-manager">${day ? `<button type="button" class="cv-back" data-calendar-overview>← 返回${currentMode() === 'today' ? '日程' : '七天'}总览</button>` : toolbar(days)}${summaryMarkup(summary, days)}${canEdit() ? `<div class="cv-manager-actions"><button class="btn small" data-action="add" data-kind="events">${icon('plus')}添加安排</button><button class="quiet" data-action="accounts">管理同步日历</button></div>` : ''}${summary.days.map(item => `<section class="cv-manager-day"><h3>${shortDate(item.day)} ${weekNames[weekday(item.day)]} <small>${item.total} 项 · ${duration(item.busyMinutes)}</small></h3>${item.events.length ? item.events.map(event => eventMarkup(event, item.day, false, canEdit())).join('') : '<p class="help">这天暂无安排。</p>'}</section>`).join('')}</div>`, true);
  }
  function update() {
    resetTVPlayback();
    try { if (!isTV || isDemo) localStorage.setItem(storageKey(), mode); } catch (_) { /* Storage can be unavailable in private browsers. */ }
    renderBoard();
    if (managerOpen && document.querySelector('#dialog')?.open) openManager();
  }
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-calendar-mode], [data-calendar-move], [data-calendar-reset], [data-calendar-day], [data-calendar-overview]');
    if (!control || !data) return;
    if (control.hasAttribute('data-calendar-mode')) { currentMode(); mode = validMode(control.dataset.calendarMode); update(); }
    else if (control.hasAttribute('data-calendar-move')) { anchor = shiftDay(anchor || dayKey(), Number(control.dataset.calendarMove) * (currentMode() === 'today' ? 1 : 7)); update(); }
    else if (control.hasAttribute('data-calendar-reset')) { anchor = null; update(); }
    else if (control.hasAttribute('data-calendar-day')) openManager(control.dataset.calendarDay);
    else openManager();
  });
  document.querySelector('#dialog')?.addEventListener('close', () => { managerOpen = false; });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && isTV) { resetTVPlayback(); if (data) renderBoard(); } });
  setInterval(playbackTick, 120);
  function setMode(value, options = {}) {
    currentMode();
    mode = validMode(value);
    anchor = null;
    resetTVPlayback();
    if (options.persist !== false && (!isTV || isDemo)) {
      try { localStorage.setItem(storageKey(), mode); } catch (_) {}
    }
    if (data) renderBoard();
  }
  root.CalendarViews = {currentMode, setMode, renderCard, openManager, bindControls() {}, helpers};
})(typeof window !== 'undefined' ? window : globalThis);
