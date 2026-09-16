/* Member photo workspace. Provider URLs never become image sources. */
window.HouseholdMedia = (() => {
  'use strict';
  let current = null;
  const CONSENT = 'media-v1';
  const terminal = new Set(['confirmed','cancelled','expired','failed','create_unknown']);
  const labels = {queued:'正在准备',creating:'正在连接 Google',waiting_selection:'等待你选择照片',listing:'正在读取本次选择',staging:'正在准备预览',awaiting_confirmation:'等待你确认保存',confirmed:'保存结果',cancelled:'已取消',expired:'选择已过期',failed:'导入未完成',create_unknown:'连接结果待确认'};
  // Only local fixed text is rendered for per-photo errors, never provider text.
  const resultErrors = {
    input_too_large:'输入图片超过 8 MiB 上限。',
    unsupported_format:'图片格式不支持；当前支持内容与类型一致的 JPEG、PNG 和 WebP。',
    invalid_image:'图片不完整或无法安全解码。', multiple_frames:'暂不支持动图或多帧图片。',
    too_many_pixels:'图片像素超过 2000 万像素上限。', output_too_large:'净化后的展示图片超过 2 MiB 上限。',
    unsafe_decoder_configuration:'当前解码配置无法安全处理图片。', invalid_input:'图片字节或媒体类型无效。',
    unsupported_type:'本次仅处理照片，已跳过非照片媒体。', result_unknown:'旧记录未保存此项的具体处理原因。',
    unsupported_media:'此媒体格式暂不支持。', unsupported_image:'这张照片无法安全生成展示副本，具体原因未记录。',
    too_large:'所选媒体超过处理上限。', unavailable:'这张照片暂时无法读取。',
    worker_error:'这张照片处理失败，具体原因未记录。', timeout:'处理这张照片时，媒体服务未及时响应。',
    rate_limited:'媒体服务繁忙，这张照片未完成处理。', remote_error:'媒体服务暂时不可用。',
    bad_response:'媒体服务返回的内容无法使用。', network:'处理这张照片时连接中断。',
    redirect:'媒体服务返回了不支持的跳转。', not_selected:'这张照片不在本次可读取的选择范围内。',
    not_found:'这张照片已无法读取。', expired:'本次照片选择已过期。',
    selection_changed:'Google Photos 中的本次选择已变化。', quota:'照片数量或存储额度已达上限。',
    reauth:'照片来源的授权已失效。', invalid_token:'照片来源的授权已失效。',
    forbidden:'这张照片的读取权限不可用。'
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const id = value => typeof value === 'string' && /^[a-f0-9]{24}$/.test(value);
  const actor = () => JSON.stringify([user?.role,user?.householdId,user?.id,user?.auth_version,csrf,isTV,isDemo]);
  const permitted = () => !isTV && !isDemo && canEdit();
  const button = (action, text, attrs = '') => `<button type="button" class="hm-button" data-hm="${action}" ${attrs}>${text}</button>`;
  const option = (value, text, selected) => `<option value="${escape(value)}" ${String(value) === String(selected ?? '') ? 'selected' : ''}>${escape(text)}</option>`;
  const key = () => crypto.randomUUID();
  const preview = item => id(item?.id) && item.previewUrl === `/api/media/items/${item.id}/preview` ? item.previewUrl : '';
  function providerLink(value, origin) {
    try {
      const url = new URL(value);
      return url.origin === origin && !url.username && !url.password && !url.hash ? url.href : '';
    } catch (_) { return ''; }
  }
  function unmount(message = '') {
    const f = current;
    if (!f) return;
    current = null; f.dead = true; f.epoch++;
    clearTimeout(f.timer); f.observer.disconnect();
    f.node.removeEventListener('click', f.click);
    f.node.removeEventListener('change', f.change);
    f.node.removeEventListener('input', f.input);
    f.node.removeEventListener('submit', f.submit);
    document.removeEventListener('visibilitychange', f.visibility);
    window.removeEventListener('online', f.online);
    window.removeEventListener('offline', f.offline);
    f.node.replaceChildren();
    if (message) {const p = document.createElement('p'); p.setAttribute('role','alert'); p.textContent = message; f.node.append(p);}
    f.items = []; f.accounts = []; f.journeys = []; f.devices = []; f.imports = [];
    f.importResult = null; f.editor = null; f.createPending = null; f.confirmPending = null; f.confirmConflict = false;
    f.selection.clear();
  }
  const notifyIdentityChanged = () => unmount('登录成员或家庭已变化，相册已收起。请重新打开。');
  function alive(f) {
    if (current !== f || f.dead || !f.node.isConnected) return false;
    if (!permitted() || actor() !== f.actor) {notifyIdentityChanged(); return false;}
    return true;
  }
  async function verify(f, epoch) {
    if (!alive(f) || epoch !== f.epoch) return false;
    const me = await api('/me');
    if (!alive(f) || epoch !== f.epoch) return false;
    const value = JSON.stringify([me.user?.role,me.user?.householdId,me.user?.id,me.user?.auth_version,me.csrf,isTV,isDemo]);
    if (value !== f.actor) {notifyIdentityChanged(); return false;}
    return true;
  }
  async function job(f, work, {quiet = false} = {}) {
    if (!alive(f) || f.busy) return;
    f.busy = true; const epoch = ++f.epoch;
    const check = () => verify(f, epoch);
    const valid = () => alive(f) && epoch === f.epoch;
    if (!quiet) {f.error = ''; render(f);}
    try {if (await check()) await work(check);}
    catch (error) {
      if (!valid()) return;
      if (error.status === 401) {notifyIdentityChanged(); return;}
      try {if (!await check()) return;}
      catch (_) {if (valid()) f.error = '暂时无法核对连接，草稿仍保留。恢复网络后再试。';}
      if (valid() && [403,404].includes(error.status)) {
        f.items = []; f.editor = null;
        if (quiet) render(f);
      }
      if (valid() && !f.error) f.error = error.message || '暂时未能完成，请重试。';
    } finally {
      if (valid()) {
        f.busy = false;
        if (!quiet) render(f); else {renderImport(f); renderMessage(f);}
        schedule(f);
      }
    }
  }
  async function gallery(f, check) {
    const query = new URLSearchParams({scope:f.scope,offset:String(f.offset),limit:'24'});
    if (f.journeyId) query.set('journeyId',f.journeyId);
    const result = await api('/media/items?' + query);
    if (!await check()) return;
    f.items = result.items || []; f.total = result.total || 0; f.hasMore = !!result.hasMore;
  }
  async function visibleState(f, check) {
    await gallery(f,check);
    if (!await check()) return;
    f.freshAt = Date.now();
    if (!f.editor) return;
    const editor = f.editor;
    try {
      const {item} = await api('/media/items/' + encodeURIComponent(editor.item.id));
      if (!await check()) return;
      if (editor.item.revision !== item.revision) {clearSuggestions(editor,'照片已更新，请重新读取照片和推荐。'); if (item.canManage) editor.conflict = true;}
      if (!item.canManage) editor.item = item;
    } catch (error) {
      if (!await check()) return;
      if ([403,404,410].includes(error.status)) {f.editor = null; f.notice = '这张照片已移除或不再共享。';}
      else throw error;
    }
  }
  async function readImport(f, importId, check) {
    const result = await api('/media/imports/' + encodeURIComponent(importId));
    if (!await check()) return;
    if (f.importResult?.import?.id !== result.import?.id) {
      f.selection.clear(); f.persist = false; f.confirmPending = null; f.confirmConflict = false;
    }
    f.importResult = result;
    const available = new Set((result.items || []).map(item => item.id));
    f.selection = new Set([...f.selection].filter(itemId => available.has(itemId)));
  }
  async function refresh(f) {
    await job(f, async check => {
      const [accounts,journeys,devices,imports] = await Promise.all([
        api('/accounts'),api('/journeys'),api('/devices'),api('/media/imports?limit=10&offset=0')]);
      if (!await check()) return;
      f.accounts = (accounts.accounts || []).filter(account => account.provider === 'google');
      f.journeys = journeys.journeys || []; f.devices = Array.isArray(devices) ? devices : [];
      f.imports = imports.items || [];
      if (!f.accounts.some(account => account.id === f.accountId)) f.accountId = f.accounts.find(account => account.capabilities?.photos && !account.needsReauth)?.id || f.accounts[0]?.id || '';
      await visibleState(f,check);
      if (!await check()) return;
      const latest = f.importResult?.import?.id || f.imports.find(item => !terminal.has(item.state))?.id;
      if (latest) await readImport(f,latest,check);
      if (!await check()) return;
      f.loaded = true;
    });
  }
  function schedule(f) {
    clearTimeout(f.timer);
    if (!alive(f) || document.hidden) return;
    const item = f.importResult?.import;
    const active = item && !terminal.has(item.state);
    f.timer = setTimeout(() => {
      if (f.busy) {schedule(f); return;}
      const refreshLibrary = Date.now() - f.freshAt >= 15000;
      void job(f, async check => {
        if (active) await readImport(f,item.id,check);
        if (refreshLibrary) await visibleState(f,check);
      }, {quiet:!refreshLibrary});
    }, active ? Math.max(4000, Math.min(15000, Date.parse(item.nextPollAt) - Date.now() || 4000)) : 15000);
  }
  function imageMarkup(item) {
    const url = preview(item);
    return url ? `<img src="${escape(url)}" alt="${escape(item.caption || '照片预览')}" loading="lazy" referrerpolicy="no-referrer">` : '<span class="hm-photo-unavailable">预览暂不可用</span>';
  }
  function renderMessage(f) {
    const node = f.node.querySelector('[data-hm-message]');
    if (node) node.innerHTML = `${!navigator.onLine ? '<p class="hm-warning">网络已断开，连接恢复后可继续。</p>' : ''}${f.error ? `<p class="hm-warning" role="alert">${escape(f.error)}</p>` : ''}${f.notice ? `<p class="hm-notice" role="status">${escape(f.notice)}</p>` : ''}`;
  }
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  function savedSummary(item) {
    const saved = count(item?.counts?.saved);
    const text = saved === null ? '本次保存数量未记录' : `已保存 ${saved} 张`;
    return item?.resultsState === 'known' ? text : `${text}；本次其他处理结果未记录`;
  }
  function selectionSummary(f) {
    const selected = f.confirmPending ? f.confirmPending.itemIds.length : f.selection.size;
    const available = (f.importResult?.items || []).length;
    return `仅将当前勾选的 ${selected} 张保存到私密相册。可保存照片中还有 ${Math.max(0,available-selected)} 张未勾选，不会保存。`;
  }
  function resultsMarkup(item) {
    const counts = item.counts || {}, known = item.resultsState === 'known';
    if (!known) {
      return `<p class="hm-warning" data-hm-results-summary>${escape(item.state === 'confirmed' ? savedSummary(item) : terminal.has(item.state) ? '本次处理结果未记录，无法确定成功、失败或未勾选的数量。' : '本次处理结果尚未取得，请等待状态更新。')}</p>`;
    }
    const selected = count(counts.selected), pending = count(counts.pending);
    const display = value => count(value) === null ? '未记录' : `${value} 张`;
    const stats = [['ready','处理成功'],['failed','处理失败'],['skipped','跳过'],['pending','待处理 / 处理中']];
    if (item.state === 'confirmed') stats.push(['saved','已保存'],['unselected','成功但未勾选']);
    const rows = (Array.isArray(item.results) ? item.results : []).slice(0,20);
    const statuses = {pending:'待处理 / 处理中',successful:'处理成功',duplicate:'已在相册，可复用',skipped:'已跳过',failed:'处理失败'};
    return `<div class="hm-results-summary" data-hm-results-summary role="status" aria-live="polite"><p><strong>${selected === null ? '本次选择数量未记录' : `本次选择 ${selected} 张`}${item.state === 'confirmed' ? ` · ${escape(savedSummary(item))}` : ''}</strong></p><dl class="hm-result-counts">${stats.map(([name,label]) => `<div data-hm-count="${name}"><dt>${label}</dt><dd>${display(counts[name])}</dd></div>`).join('')}</dl>${selected > 0 && pending !== null && pending <= selected ? `<label class="hm-progress">已处理 ${selected-pending} / ${selected} 张<progress max="${selected}" value="${selected-pending}"></progress></label>` : ''}</div>
      ${item.state === 'confirmed' ? '<p class="hm-muted">处理成功不等于全部保存；仅本次勾选确认的照片会留下。已保存数量包含复用的照片，未勾选的已有照片也不会从相册删除。</p>' : '<p class="hm-muted">处理成功的照片（含已有照片的复用）仍需勾选并确认保存。</p>'}
      ${rows.length ? `<section class="hm-results" aria-label="本次逐项处理结果"><h4>本次处理明细</h4><p class="hm-muted">序号仅对应本次返回的选片清单，不代表原图库顺序。</p><ol>${rows.map(row => {
        const number = count(row.position);
        const status = Object.hasOwn(statuses,row.status) ? row.status : 'unknown';
        const problem = status === 'failed' || status === 'skipped';
        const message = Object.hasOwn(resultErrors,row.error?.code) ? resultErrors[row.error.code] : '这张照片未能完成处理，具体原因未记录。';
        return `<li class="hm-result ${problem ? 'hm-result-problem' : ''}"><strong>${number && number <= 20 ? `第 ${number} 张` : '本次照片'}</strong><span>${statuses[status] || '结果未记录'}</span>${problem ? `<p>${escape(message)}</p>` : ''}</li>`;
      }).join('')}</ol></section>` : ''}`;
  }
  function importMarkup(f) {
    const result = f.importResult, item = result?.import;
    if (!item) return '<div class="hm-import-idle"><strong>只挑选想留下的回忆</strong><p>在 Google Photos 中选择照片，再回到这里确认。不会自动读取你的整个图库。</p></div>';
    const link = providerLink(item.pickerUri,'https://photos.google.com');
    const candidates = result.items || [];
    const busy = f.busy ? 'disabled' : '';
    if (item.state === 'confirmed') {
      return `<div class="hm-import-heading"><h3>本次保存结果</h3></div>${resultsMarkup(item)}<p class="hm-muted">已确认的照片可以在下方相册查看；原图仍保留在 Google Photos。</p>${button('poll','刷新状态',busy)}`;
    }
    if (!terminal.has(item.state) && Date.parse(item.expiresAt) <= Date.now()) {
      return `<h3>本次临时预览已过期</h3>${resultsMarkup(item)}<p class="hm-muted">未确认的预览不再展示。可以从 Google Photos 重新选择。</p>${button('poll','刷新状态',busy)}`;
    }
    return `<div class="hm-import-heading"><div><span class="hm-kicker">本次选择</span><h3>${escape(labels[item.state] || '等待状态更新')}</h3></div></div>
      ${resultsMarkup(item)}${item.expiresAt && !terminal.has(item.state) ? `<p class="hm-muted">临时预览有效至 ${escape(new Date(item.expiresAt).toLocaleString('zh-CN'))}</p>` : ''}
      ${item.state === 'waiting_selection' && link ? `<a class="hm-button primary" href="${escape(link)}" target="_blank" rel="noopener noreferrer">打开 Google Photos 选片 ↗</a><p class="hm-muted">选完后回到此页，预览会自动更新。</p>` : ''}
      ${item.state === 'create_unknown' ? '<p class="hm-warning">Google 可能已创建选片页面，但连接中断，未取得结果。不会自动重复创建；可取消这次记录，再开始一次选择。</p>' : ''}
      ${item.error ? `<p class="hm-warning">${escape(item.error.message || '这次选择未能完整处理，请刷新核对。重新授权不一定能解决服务配置或会话问题。')}</p>` : ''}
      ${item.state === 'awaiting_confirmation' ? `<div class="hm-candidates">${candidates.map(candidate => `<label class="hm-candidate">${imageMarkup(candidate.item)}<span><input type="checkbox" data-hm-candidate="${escape(candidate.id)}" ${f.selection.has(candidate.id) ? 'checked' : ''} ${f.confirmPending || f.busy ? 'disabled' : ''}>${candidate.status === 'duplicate' ? '已保存，可复用' : '保留这张'}</span></label>`).join('')}</div><p class="hm-selection-summary" data-hm-selection-summary role="status" aria-live="polite">${selectionSummary(f)}</p><label class="hm-consent"><input type="checkbox" data-hm-persist ${f.persist ? 'checked' : ''} ${f.confirmPending ? 'disabled' : ''}><span>将勾选照片的预览保存到我的私密相册。原图仍在 Google Photos，之后可分别设置家庭共享和电视展示。</span></label>${f.confirmConflict ? '<p class="hm-warning">本次选择已更新，原保存请求不能继续重试。请读取最新状态，重新核对后确认。</p>'+button('recheck-confirm','重新核对本次选择',busy) : button('confirm',f.confirmPending ? '重试同一次保存' : '保存选中照片',busy)}<p class="hm-muted">只保存你确认的照片；临时预览最迟 24 小时后清理。当前支持照片，不包含视频播放。</p>` : ''}
      <div class="hm-actions">${button('poll','刷新状态',busy)}${['failed','cancelled','expired'].includes(item.state) ? button('new-selection','重新选片',`${busy} ${f.createPending ? 'disabled' : ''}`) : ''}${!terminal.has(item.state) || item.state === 'create_unknown' ? button('cancel-import','取消本次选择',busy) : ''}</div>`;
  }
  function renderImport(f) {
    const node = f.node.querySelector('[data-hm-import]');
    if (node) node.innerHTML = importMarkup(f);
  }
  function editorMarkup(f) {
    const editor = f.editor;
    if (!editor) return '';
    const item = editor.item, draft = editor.draft, busy = f.busy ? 'disabled' : '';
    const grantIds = editor.grants || [];
    return `<aside class="hm-detail" aria-label="照片详情"><div class="hm-detail-head"><h2>这一刻</h2>${button('close-detail','关闭')}</div><div class="hm-detail-image">${imageMarkup(item)}</div>
      ${item.canManage ? `<form data-hm-editor><label>照片说明<input name="caption" ${busy} maxlength="200" value="${escape(draft.caption)}" placeholder="给这段回忆写一句话"></label><label>关联旅行<select name="journeyId" ${busy}>${option('','暂不关联',draft.journeyId)}${f.journeys.map(journey => option(journey.id,journey.trip?.title || journey.plan?.title || '旅行',draft.journeyId)).join('')}</select></label><label>谁能查看<select name="visibility" ${busy}>${option('private','仅我自己',draft.visibility)}${option('shared','家庭成员',draft.visibility)}</select></label><p class="hm-muted">共享后，家庭成员可查看照片和说明。取消旅行关联会收回共享与电视展示。</p>${editor.conflict ? `<p class="hm-warning">照片已在其他设备上更新，你的修改仍保留。先读取最新状态，再核对并保存。</p>${button('reload-detail','读取最新状态，保留我的修改',busy)}` : ''}<button class="hm-button primary" type="submit" ${busy}>保存修改</button></form>` : `<h3>${escape(item.caption || '家庭共享照片')}</h3><p class="hm-muted">共享照片由上传者管理。</p>`}
      ${item.journey ? `<div class="hm-travel-link"><span>关联旅行 · ${escape(item.journey.title)}</span>${button('open-journey','查看行程 →')}</div>` : ''}
      ${item.canManage ? `<section class="hm-tv-settings"><h3>在家里的电视上展示</h3><p class="hm-muted">先保存为家庭共享，再明确选择屏幕。未勾选的电视无法播放这张照片。</p>${f.devices.length ? f.devices.map(device => `<label class="hm-consent"><input type="checkbox" data-hm-device="${escape(device.id)}" ${grantIds.includes(device.id) ? 'checked' : ''} ${item.visibility !== 'shared' || f.busy ? 'disabled' : ''}><span>${escape(device.name || '家庭电视')}</span></label>`).join('') : '<p>还没有配对的电视。请在设置中连接设备。</p>'}<label class="hm-consent"><input type="checkbox" data-hm-tv-consent ${editor.tvConsent ? 'checked' : ''} ${item.visibility !== 'shared' ? 'disabled' : ''}><span>允许选中的电视展示这张照片。</span></label>${button('save-grants','保存电视范围',`${busy} ${item.visibility !== 'shared' ? 'disabled' : ''}`)}${button('revoke-grants','收回全部电视展示',busy)}</section><div class="hm-danger-zone">${button('delete','从看板移除这张照片',busy)}<p class="hm-muted">只移除看板副本，Google Photos 原图保留。</p></div>` : ''}</aside>`;
  }
  const revision = value => Number.isSafeInteger(value) && value > 0;
  function clearSuggestions(editor, message = '') {
    if (!editor) return;
    editor.suggestionEpoch = (editor.suggestionEpoch || 0) + 1;
    editor.suggestions = null; editor.suggestionMessage = message;
  }
  function hasPhotoDraft(editor) {
    return editor.draft.caption !== (editor.item.caption || '') || editor.draft.visibility !== editor.item.visibility
      || editor.draft.journeyId !== (editor.item.journey?.id || '');
  }
  function suggestionData(value, item) {
    if (!value || value.photoId !== item.id || value.photoRevision !== item.revision
        || value.currentJourneyId !== (item.journey?.id || null) || !revision(value.photoRevision)
        || !['known','unknown'].includes(value.sourceTimeState) || value.limit !== 20
        || (value.sourceTimeState === 'known' && (typeof value.sourceCreatedAt !== 'string' || value.sourceCreatedAt.length > 100))
        || typeof value.hasMore !== 'boolean' || !Array.isArray(value.suggestions) || value.suggestions.length > 20
        || !['date_overlap','source_time_unknown','no_matching_journeys'].includes(value.reason?.code)
        || (value.sourceTimeState === 'unknown' && (value.sourceCreatedAt !== null || value.suggestions.length))) throw new Error('照片或推荐已变化，请重新读取后核对。');
    const ids = new Set();
    for (const row of value.suggestions) {
      if (!id(row.journeyId) || ids.has(row.journeyId) || !revision(row.journeyRevision) || !revision(row.tripRevision)
          || typeof row.title !== 'string' || row.title.length > 500 || typeof row.alreadyLinked !== 'boolean'
          || row.alreadyLinked !== (row.journeyId === value.currentJourneyId) || row.reason?.code !== 'date_overlap'
          || !['plan','legacy_default'].includes(row.referenceTimezoneSource) || typeof row.referenceTimezone !== 'string'
          || row.referenceTimezone.length > 100 || ![row.start,row.end,row.sourceDate].every(day => typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day))) throw new Error('推荐暂时无法核对，请重新读取。');
      ids.add(row.journeyId);
    }
    return value;
  }
  function renderSuggestions(f) {
    f.node.querySelector('[data-hm-suggestions]')?.remove();
    const editor = f.editor;
    if (!editor?.item.canManage || f.mapVisit) return;
    const journeySelect = f.node.querySelector('[data-hm-editor] [name=journeyId]');
    if (journeySelect && editor.draft.journeyId && ![...journeySelect.options].some(option => option.value === editor.draft.journeyId)) {
      journeySelect.add(new Option(editor.item.journey?.title || '当前关联旅行',editor.draft.journeyId));
      journeySelect.value = editor.draft.journeyId;
    }
    const value = editor.suggestions, busy = f.busy ? 'disabled' : '', dirty = hasPhotoDraft(editor);
    const reason = value?.sourceTimeState === 'unknown' ? '这张照片没有已记录的来源创建时间，无法按日期建议旅行。请手动核对关联。'
      : value && !value.suggestions.length ? '照片时间没有匹配当前旅行日期，请手动核对关联。' : '';
    f.node.querySelector('.hm-detail-image')?.insertAdjacentHTML('afterend',`<section class="hm-journey-suggestions" data-hm-suggestions aria-label="按照片时间推荐">
      <h3>按照片时间推荐</h3><p class="hm-muted">照片时间仅作线索，请核对行程。确认只关联这张照片，不改变共享、到访或电视许可。</p>
      ${editor.suggestionMessage ? `<p class="hm-warning" role="status">${escape(editor.suggestionMessage)}</p>` : ''}
      ${reason ? `<p role="status">${escape(reason)}</p>` : ''}
      ${dirty ? '<p class="hm-warning">有未保存的照片编辑，请先保存，再确认推荐。</p>' : ''}
      ${(value?.suggestions || []).map(row => `<article class="hm-journey-option"><h4>${escape(row.title)}</h4><p>${escape(row.start)} — ${escape(row.end)}</p><p class="hm-muted">照片日期 ${escape(row.sourceDate)} · 按旅行时区 ${escape(row.referenceTimezone)}${row.referenceTimezoneSource === 'legacy_default' ? '（旧旅行使用默认时区）' : ''}</p>${button('confirm-journey',row.alreadyLinked ? '已关联这次旅行' : '确认关联这次旅行',`data-journey="${escape(row.journeyId)}" ${busy} ${dirty || row.alreadyLinked ? 'disabled' : ''}`)}</article>`).join('')}
      ${value?.hasMore ? '<p class="hm-muted">仅显示前 20 条推荐，还有其他匹配旅行。可在下方手动关联中核对。</p>' : ''}
      ${button('journey-suggestions',value || editor.suggestionMessage ? '重新读取照片和推荐' : '查看推荐',busy)}</section>`);
  }
  async function loadSuggestions(f) {
    const editor = f.editor;
    if (!editor?.item.canManage || f.mapVisit) return;
    clearSuggestions(editor);
    const epoch = editor.suggestionEpoch;
    const active = () => f.editor === editor && editor.suggestionEpoch === epoch;
    await job(f,async check => {
      try {
        const {item} = await api('/media/items/' + editor.item.id);
        if (!await check() || !active()) return;
        if (!item?.canManage) {f.editor = null; return;}
        const dirty = hasPhotoDraft(editor);
        if (item.revision !== editor.item.revision && dirty) editor.conflict = true;
        editor.item = item;
        if (!dirty) editor.draft = {caption:item.caption || '',visibility:item.visibility,journeyId:item.journey?.id || ''};
        const value = await api('/media/items/' + item.id + '/journey-suggestions');
        if (!await check() || !active()) return;
        editor.suggestions = suggestionData(value,item);
      } catch (error) {
        if (active()) {
          clearSuggestions(editor,'无法读取推荐，请稍后重新读取或手动核对关联。');
          if ([403,404,410].includes(error.status)) f.editor = null;
        }
        throw error;
      }
    });
  }
  async function confirmJourney(f, journeyId) {
    const editor = f.editor, value = editor?.suggestions;
    const row = value?.suggestions.find(row => row.journeyId === journeyId);
    if (!editor?.item.canManage || f.mapVisit || !row || row.alreadyLinked || hasPhotoDraft(editor)) return;
    const payload = {revision:value.photoRevision,journeyId:row.journeyId,
      expectedJourneyRevision:row.journeyRevision,expectedTripRevision:row.tripRevision};
    clearSuggestions(editor,'关联结果待核对，请重新读取照片和推荐。');
    await job(f,async check => {
      try {
        const {item} = await write('/media/items/' + editor.item.id,'PATCH',payload);
        if (!await check() || f.editor !== editor) return;
        if (!item?.canManage || item.id !== editor.item.id) throw new Error('关联结果尚未核对，请重新读取。');
        editor.item = item; editor.draft = {caption:item.caption || '',visibility:item.visibility,journeyId:item.journey?.id || ''};
        editor.conflict = false; editor.tvConsent = false;
        clearSuggestions(editor,'关联已保存。共享范围和电视许可保持原设置。');
        await gallery(f,check);
      } catch (error) {
        if (f.editor === editor) {
          clearSuggestions(editor,error.status === 409 ? '照片或旅行已更新。请重新读取照片和推荐，核对后再次明确确认。' : '关联结果尚未核对。请重新读取照片和推荐；不会自动重发关联。');
          if ([403,404,410].includes(error.status)) f.editor = null;
        }
        throw error;
      }
    });
  }
  function render(f) {
    if (!alive(f)) return;
    const focused = f.node.contains(document.activeElement) ? document.activeElement : null;
    const focusName = focused?.name;
    const selection = focused && typeof focused.selectionStart === 'number' ? [focused.selectionStart,focused.selectionEnd] : null;
    const busy = f.busy ? 'disabled' : '';
    f.node.classList.add('hm-workspace');
    f.node.innerHTML = `<div data-hm-message aria-live="polite"></div><section class="hm-source"><div><span class="hm-kicker">FAMILY MEMORIES</span><h2>把值得回看的日子，留在一起。</h2><p>你选择哪些照片留下，也决定与谁分享。</p></div><div class="hm-source-actions"><label>照片来源<select data-hm-account ${busy} ${f.createPending ? 'disabled' : ''}>${f.accounts.length ? f.accounts.map(account => option(account.id,`${account.name || account.email || 'Google 账户'}${account.capabilities?.photos && !account.needsReauth ? ' · 已连接' : ' · 需授权照片'}`,f.accountId)).join('') : option('','尚未连接 Google Photos','')}</select></label>${button('connect','连接 / 更新 Google Photos 授权',busy)}</div><label class="hm-consent"><input type="checkbox" data-hm-temporary ${f.temporary ? 'checked' : ''} ${f.createPending ? 'disabled' : ''}><span>允许临时处理我在 Google 选择的照片，供我预览确认；未确认内容会在 24 小时内清理。</span></label>${button('create',f.createPending ? '重试本次选择请求' : '从 Google Photos 选择照片',busy)}</section>
      <section class="hm-import" data-hm-import aria-label="照片导入进度"></section>
      ${f.imports.length ? `<details class="hm-history"><summary>最近的选择记录</summary>${f.imports.map(item => button('resume',`${escape(labels[item.state] || item.state)} · ${escape(new Date(item.createdAt).toLocaleString('zh-CN'))}`,`data-id="${escape(item.id)}" ${busy}`)).join('')}</details>` : ''}
      <div class="hm-library-head"><div><span class="hm-kicker">YOUR COLLECTION</span><h2>我们的相册 <small>${f.total} 张</small></h2></div>${button('refresh','刷新',busy)}</div><form class="hm-filters" data-hm-filters><label>查看范围<select name="scope">${option('mine','我的照片',f.scope)}${option('visible','我能查看的',f.scope)}${option('shared','家人分享给我',f.scope)}</select></label><label>旅行<select name="journeyId">${option('','全部旅行',f.journeyId)}${f.journeys.map(journey => option(journey.id,journey.trip?.title || journey.plan?.title || '旅行',f.journeyId)).join('')}</select></label><button class="hm-button" type="submit" ${busy}>查看</button></form>
      <div class="hm-library-layout ${f.editor ? 'has-detail' : ''}"><div><div class="hm-grid">${f.items.length ? f.items.map(item => `<button type="button" class="hm-card" data-hm="detail" data-id="${escape(item.id)}">${imageMarkup(item)}<span class="hm-card-caption"><strong>${escape(item.caption || item.journey?.title || '一段生活的片刻')}</strong><span>${item.visibility === 'shared' ? '家庭共享' : '仅我自己'}${item.journey ? ' · '+escape(item.journey.title) : ''}</span></span></button>`).join('') : `<div class="hm-empty"><span aria-hidden="true">▧</span><h3>${f.loaded ? '回忆，从你挑选的第一张开始' : '正在打开相册…'}</h3><p>${f.loaded ? '从 Google Photos 选择照片，确认保存后会出现在这里。也可以换个范围查看家庭共享照片。' : '正在核对照片和连接状态。'}</p></div>`}</div><div class="hm-pagination">${button('previous','上一页',`${busy} ${f.offset === 0 ? 'disabled' : ''}`)}<span>第 ${Math.floor(f.offset/24)+1} 页</span>${button('next','下一页',`${busy} ${!f.hasMore ? 'disabled' : ''}`)}</div></div>${editorMarkup(f)}</div>`;
    renderImport(f); renderMessage(f); renderSuggestions(f);
    if (focusName) {
      const input = [...f.node.querySelectorAll('[name]')].find(node => node.name === focusName && (focused.closest('[data-hm-editor]') ? node.closest('[data-hm-editor]') : !node.closest('[data-hm-editor]')));
      input?.focus({preventScroll:true});
      if (input && selection && input.setSelectionRange) input.setSelectionRange(...selection);
    }
  }
  async function detail(f,itemId,preserve = false) {
    await job(f,async check => {
      const {item} = await api('/media/items/' + encodeURIComponent(itemId));
      if (!await check()) return;
      const result = item.canManage ? await api(`/media/items/${encodeURIComponent(itemId)}/tv-grants`) : {deviceIds:[]};
      if (!await check()) return;
      const draft = preserve && f.editor?.item.id === itemId ? f.editor.draft : {caption:item.caption || '',visibility:item.visibility,journeyId:item.journey?.id || ''};
      f.editor = {item,draft,grants:result.deviceIds || [],tvConsent:false,conflict:false};
    });
  }
  async function mutate(f,path,method,payload,after) {
    await job(f,async check => {
      try {
        const result = await write(path,method,payload);
        if (!await check()) return;
        await after(result,check);
      } catch (error) {
        if (error.status === 409 && f.editor) f.editor.conflict = true;
        if (path.endsWith('/confirm') && [409,410].includes(error.status)) f.confirmConflict = true;
        throw error;
      }
    });
  }
  async function act(f,action,target) {
    if (!alive(f) || f.busy) return;
    f.notice = '';
    if (action === 'refresh') return refresh(f);
    if (action === 'detail') return detail(f,target.dataset.id);
    if (action === 'reload-detail') return detail(f,f.editor.item.id,true);
    if (action === 'journey-suggestions') return loadSuggestions(f);
    if (action === 'confirm-journey') return confirmJourney(f,target.dataset.journey);
    if (action === 'close-detail') {f.editor = null; render(f); return;}
    if (action === 'open-journey') {const journey = f.editor?.item.journey; if (journey?.tripId) f.openJourney?.(journey.tripId,{returnTo:'photos'}); return;}
    if (action === 'resume') return job(f,check => readImport(f,target.dataset.id,check));
    if (action === 'poll') return job(f,check => readImport(f,f.importResult.import.id,check));
    if (action === 'recheck-confirm') return job(f,async check => {
      await readImport(f,f.importResult.import.id,check);
      if (!await check()) return;
      f.confirmPending = null; f.confirmConflict = false; f.persist = false;
      f.notice = f.importResult.import.state === 'confirmed' ? savedSummary(f.importResult.import) : '已读取最新状态，请重新核对照片并确认保存。';
      await gallery(f,check);
    });
    if (action === 'next' || action === 'previous') {f.offset = Math.max(0,f.offset+(action === 'next' ? 24 : -24)); return job(f,check => gallery(f,check));}
    if (action === 'connect') return job(f,async check => {
      const result = await write('/accounts/google-photos/bind','POST',f.accountId ? {accountId:f.accountId} : {});
      if (!await check()) return;
      const url = providerLink(result.url,'https://accounts.google.com');
      if (!url) throw new Error('授权链接不可用，请刷新后重试。');
      location.assign(url);
    });
    if (action === 'new-selection') {
      if (f.createPending) return;
      f.importResult = null; f.selection.clear(); f.persist = false; f.temporary = false;
      f.confirmPending = null; f.confirmConflict = false; f.notice = '请重新确认临时处理，再点击“从 Google Photos 选择照片”。';
      render(f); f.node.querySelector('[data-hm-temporary]')?.focus(); return;
    }
    if (action === 'create') {
      if (!f.createPending) {
        const account = f.accounts.find(value => value.id === f.accountId);
        if (!account?.capabilities?.photos || account.needsReauth) {f.error = '请先连接 Google Photos 并完成照片授权。'; renderMessage(f); return;}
        if (!f.temporary) {f.error = '请先确认临时处理说明，再开始选片。'; renderMessage(f); return;}
        f.createPending = {requestId:key(),accountId:f.accountId,consentVersion:CONSENT,allowTemporaryProcessing:true};
        if (f.importResult?.import?.state === 'create_unknown') {
          if (!confirm('上次 Google 可能已创建选片页面，但未能取得结果。确认仍要新建一次选择？')) {f.createPending = null; return;}
          f.createPending.previousUnknownImportId = f.importResult.import.id;
          f.createPending.acknowledgePossibleExistingSession = true;
        }
      }
      return mutate(f,'/media/imports','POST',f.createPending,async (result,check) => {
        const item = result.import || result;
        f.createPending = null; f.selection.clear(); f.persist = false; f.confirmPending = null;
        await readImport(f,item.id,check);
      });
    }
    if (action === 'confirm') {
      if (f.confirmConflict) return;
      if (!f.confirmPending) {
        if (!f.persist || !f.selection.size) {f.error = '请勾选照片，并确认保存到私密相册。'; renderMessage(f); return;}
        f.confirmPending = {revision:f.importResult.import.revision,confirmRequestId:key(),itemIds:[...f.selection],consentVersion:CONSENT,persistSelected:true};
      }
      return mutate(f,`/media/imports/${f.importResult.import.id}/confirm`,'POST',f.confirmPending,async (_,check) => {
        f.confirmPending = null; f.confirmConflict = false; f.selection.clear(); f.persist = false;
        await readImport(f,f.importResult.import.id,check);
        if (!await check()) return;
        f.notice = f.importResult.import.state === 'confirmed' ? savedSummary(f.importResult.import) : '保存请求已返回，请核对本次处理结果。';
        await gallery(f,check);
      });
    }
    if (action === 'cancel-import') {
      if (!confirm('取消这次选择并清理临时预览？Google Photos 原图会保留。')) return;
      return mutate(f,`/media/imports/${f.importResult.import.id}`,'DELETE',{revision:f.importResult.import.revision},async (_,check) => {
        f.confirmPending = null; f.confirmConflict = false; f.selection.clear(); f.persist = false;
        await readImport(f,f.importResult.import.id,check);
      });
    }
    const editor = f.editor;
    if (!editor?.item.canManage) return;
    if (action === 'save-grants' || action === 'revoke-grants') {
      const deviceIds = action === 'revoke-grants' ? [] : editor.grants;
      if (deviceIds.length && !editor.tvConsent) {f.error = '请确认允许选中的电视展示这张照片。'; renderMessage(f); return;}
      return mutate(f,`/media/items/${editor.item.id}/tv-grants`,'PUT',{revision:editor.item.revision,deviceIds,consentVersion:CONSENT,allowTvDisplay:!!deviceIds.length},async (_,check) => {
        const {item} = await api('/media/items/' + editor.item.id);
        if (!await check()) return;
        editor.item = item; editor.grants = [...deviceIds]; editor.tvConsent = false;
        f.notice = deviceIds.length ? '电视展示范围已保存。' : '已收回全部电视展示。';
      });
    }
    if (action === 'delete') {
      if (!confirm('从看板移除照片，同时收回家庭共享和电视展示？Google Photos 原图会保留。')) return;
      return mutate(f,`/media/items/${editor.item.id}`,'DELETE',{revision:editor.item.revision},async (_,check) => {f.editor = null; f.notice = '已移除看板副本。'; await gallery(f,check);});
    }
  }
  async function mount(node,{openJourney} = {}) {
    unmount();
    if (!permitted()) {node.textContent = '请在手机或电脑上登录，管理自己的相册。'; return;}
    const f = {node,openJourney,actor:actor(),dead:false,epoch:0,busy:false,loaded:false,freshAt:Date.now(),error:'',notice:'',scope:'mine',journeyId:'',offset:0,total:0,hasMore:false,items:[],accounts:[],journeys:[],devices:[],imports:[],accountId:'',temporary:false,persist:false,selection:new Set(),importResult:null,editor:null,createPending:null,confirmPending:null,confirmConflict:false};
    current = f;
    f.click = event => {const target = event.target.closest('[data-hm]'); if (target) {event.preventDefault(); void act(f,target.dataset.hm,target);}};
    f.input = event => {if (event.target.closest('[data-hm-editor]') && f.editor && event.target.name) {
      if (f.editor.draft[event.target.name] !== event.target.value) clearSuggestions(f.editor);
      f.editor.draft[event.target.name] = event.target.value; renderSuggestions(f);
    }};
    f.change = event => {
      if (!alive(f) || f.busy) return;
      const target = event.target;
      if (target.matches('[data-hm-account]')) f.accountId = target.value;
      if (target.matches('[data-hm-temporary]')) f.temporary = target.checked;
      if (target.matches('[data-hm-persist]')) f.persist = target.checked;
      if (target.matches('[data-hm-candidate]')) {if (target.checked) f.selection.add(target.dataset.hmCandidate); else f.selection.delete(target.dataset.hmCandidate);}
      if (target.matches('[data-hm-candidate]')) {
        const summary = f.node.querySelector('[data-hm-selection-summary]');
        if (summary) summary.textContent = selectionSummary(f);
      }
      if (target.matches('[data-hm-tv-consent]') && f.editor) f.editor.tvConsent = target.checked;
      if (target.matches('[data-hm-device]') && f.editor) {const values = new Set(f.editor.grants); if (target.checked) values.add(target.dataset.hmDevice); else values.delete(target.dataset.hmDevice); f.editor.grants = [...values];}
      f.input(event);
    };
    f.submit = event => {
      event.preventDefault(); if (!alive(f) || f.busy) return;
      if (event.target.matches('[data-hm-filters]')) {clearSuggestions(f.editor); const values = new FormData(event.target); f.scope = values.get('scope'); f.journeyId = values.get('journeyId'); f.offset = 0; void job(f,check => gallery(f,check));}
      if (event.target.matches('[data-hm-editor]') && f.editor?.item.canManage) {
        const editor = f.editor;
        const payload = {revision:editor.item.revision,caption:editor.draft.caption,visibility:editor.draft.visibility,journeyId:editor.draft.journeyId || null};
        void mutate(f,`/media/items/${editor.item.id}`,'PATCH',payload,async (_,check) => {
          const {item} = await api('/media/items/' + editor.item.id);
          if (!await check()) return;
          editor.item = item; editor.draft = {caption:item.caption || '',visibility:item.visibility,journeyId:item.journey?.id || ''}; editor.conflict = false; editor.tvConsent = false;
          const grants = await api(`/media/items/${editor.item.id}/tv-grants`);
          if (!await check()) return;
          editor.grants = grants.deviceIds || []; f.notice = '照片信息已保存。'; await gallery(f,check);
        });
      }
    };
    f.visibility = () => {if (document.hidden) clearTimeout(f.timer); else if (alive(f)) void job(f,async check => {if (f.importResult) await readImport(f,f.importResult.import.id,check); await visibleState(f,check);});};
    f.online = () => {if (alive(f)) {f.error = ''; renderMessage(f); schedule(f);}};
    f.offline = () => {if (alive(f)) {clearSuggestions(f.editor); renderSuggestions(f); renderMessage(f);}};
    f.observer = new MutationObserver(() => {if (current === f && !f.node.isConnected) unmount();});
    f.observer.observe(document.body,{childList:true,subtree:true});
    node.addEventListener('click',f.click); node.addEventListener('input',f.input); node.addEventListener('change',f.change); node.addEventListener('submit',f.submit);
    document.addEventListener('visibilitychange',f.visibility); window.addEventListener('online',f.online); window.addEventListener('offline',f.offline);
    render(f); await refresh(f);
  }
  return {mount,unmount,notifyIdentityChanged,notifyStateChanged:() => {if (current && !alive(current)) unmount();}};
})();
