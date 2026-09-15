/* Shopping estimates and photos stay separate from the household cash ledger. */
'use strict';
window.ShoppingUI = (() => {
  const validAmount = value => Number.isSafeInteger(value) && value >= 0;
  const amount = value => validAmount(value) ? money(value) : '未填写';
  const photosOf = item => Array.isArray(item.photoIds) ? item.photoIds.filter(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id)).slice(0, 3) : [];
  const photoURL = id => '/api/photos/' + encodeURIComponent(id);
  let includeBought = false;
  const tvStartedAt = Date.now();
  let displayedTVCycle = 0;

  function summarize(items) {
    const pending = items.filter(item => !item.done), bought = items.filter(item => item.done);
    const total = (list, key) => list.reduce((sum, item) => sum + (validAmount(item[key]) ? item[key] : 0), 0);
    return {
      pendingCount: pending.length, boughtCount: bought.length,
      pendingBudget: total(pending, 'budget'), pendingUnknown: pending.filter(item => !validAmount(item.budget)).length,
      boughtBudget: total(bought, 'budget'), boughtBudgetUnknown: bought.filter(item => !validAmount(item.budget)).length,
      boughtActual: total(bought, 'actual'), boughtActualUnknown: bought.filter(item => !validAmount(item.actual)).length,
    };
  }

  function renderRow(item, manager = false) {
    const ids = photosOf(item), editable = canEdit();
    const check = editable ? `<button class="shopping-check ${item.done ? 'done' : ''}" aria-label="${item.done ? '恢复' : '完成'}${esc(item.title)}" aria-pressed="${!!item.done}" data-action="toggle" data-kind="shopping" data-id="${esc(item.id)}"><span>${item.done ? icon('check') : ''}</span></button>` : `<span class="shopping-check readonly ${item.done ? 'done' : ''}"><span>${item.done ? icon('check') : ''}</span></span>`;
    const picture = ids.length ? (isTV ? `<span class="shopping-thumbnail"><img src="${photoURL(ids[0])}" alt="${esc(item.title)}参考图片" loading="lazy"></span>` : `<button class="shopping-thumbnail" type="button" data-shopping-photo="${esc(item.id)}" aria-label="查看${esc(item.title)}的 ${ids.length} 张图片"><img src="${photoURL(ids[0])}" alt="" loading="lazy">${ids.length > 1 ? `<small>${ids.length}</small>` : ''}</button>`) : '';
    const settlement = manager && editable && !isTV && !isDemo && window.ShoppingSettlement ? `<button class="btn small secondary shopping-settlement-entry" type="button" data-shopping-settlement-shopping="${esc(item.id)}">核对实付</button>` : '';
    const owner = item.owner && item.owner !== 'shared' ? ' · ' + esc(person(item.owner)) : '';
    const prices = `<span>预算 ${amount(item.budget)}</span>${item.done ? `<span class="${validAmount(item.actual) && validAmount(item.budget) && item.actual > item.budget ? 'amber' : ''}">实付 ${amount(item.actual)}</span>` : ''}`;
    return `<div class="list-row shopping-row ${item.done ? 'completed' : ''}">${check}${picture}<div class="copy"><strong title="${esc(item.title)}">${esc(item.title)}</strong><small>${esc(item.quantity || '1 件')}${owner}</small><div class="shopping-row-prices">${prices}</div>${manager && item.note ? `<p class="shopping-item-note">${esc(item.note)}</p>` : ''}${settlement}</div>${editable ? `<button class="icon-button row-edit shopping-edit" aria-label="编辑${esc(item.title)}" data-action="edit" data-kind="shopping" data-id="${esc(item.id)}">${icon('edit')}</button>` : ''}</div>`;
  }

  function pendingLabel(summary) {
    if (!summary.pendingCount) return '待买预算 ' + money(0);
    if (summary.pendingUnknown === summary.pendingCount) return '待买预算待填写';
    return '待买预算 ' + money(summary.pendingBudget) + (summary.pendingUnknown ? ` · ${summary.pendingUnknown} 件未填` : '');
  }

  function renderCard() {
    const items = (data.shopping || []).filter(item => !item.done), summary = summarize(data.shopping || []);
    const limit = isTV ? 3 : 4, pages = Math.max(1, Math.ceil(items.length / limit));
    displayedTVCycle = Math.floor(Math.max(0, Date.now() - tvStartedAt) / 20000);
    const page = isTV ? displayedTVCycle % pages : 0;
    const selected = items.slice(page * limit, (page + 1) * limit);
    const more = isTV && pages > 1 ? `<div class="shopping-tv-pagination">${page + 1} / ${pages} 页 · 20 秒轮换</div>` : items.length > limit ? canEdit() ? `<button class="list-more" data-action="manage" data-kind="shopping">查看全部 ${items.length} 件 →</button>` : `<span class="list-more muted">还有 ${items.length - limit} 件待买</span>` : '';
    return `<section class="card shopping-card"><div class="card-heading"><h2>采购清单</h2><div class="card-actions"><span class="sub">${items.length} 件待买</span>${canEdit() ? `<button class="icon-button" aria-label="添加采购物品" data-action="add" data-kind="shopping">${icon('plus')}</button>` : ''}</div></div>${items.length ? `<div class="shopping-budget-line">${pendingLabel(summary)}</div><div class="compact-list">${selected.map(item => renderRow(item)).join('')}</div>` : `<div class="empty shopping-empty">${icon('bag')}<h3>下次，一起带回家</h3><p>记录要买的东西、预算和参考图片。</p>${canEdit() ? `<button class="btn small secondary" data-action="add" data-kind="shopping">${icon('plus')}添加物品</button>` : ''}</div>`}${more}</section>`;
  }

  function openManager() {
    activeManager = 'shopping';
    const all = data.shopping || [], summary = summarize(all);
    const items = all.filter(item => includeBought || !item.done).sort((a, b) => Number(a.done) - Number(b.done));
    const boughtActual = summary.boughtCount && summary.boughtActualUnknown === summary.boughtCount ? '待填写' : money(summary.boughtActual);
    const boughtBudget = summary.boughtCount && summary.boughtBudgetUnknown === summary.boughtCount ? '待填写' : money(summary.boughtBudget);
    const bought = summary.boughtCount ? `<div class="shopping-total"><small>已买实付 · ${summary.boughtCount} 件</small><strong>${boughtActual}</strong><span>原预算 ${boughtBudget}${summary.boughtBudgetUnknown ? `（${summary.boughtBudgetUnknown} 件未填）` : ''}</span>${summary.boughtActualUnknown ? `<span>${summary.boughtActualUnknown} 件待补实付</span>` : ''}</div>` : '';
    openModal('采购清单', `<div class="shopping-manager"><div class="shopping-totals"><div class="shopping-total"><small>待买预算 · ${summary.pendingCount} 件</small><strong>${summary.pendingCount && summary.pendingUnknown === summary.pendingCount ? '待填写' : money(summary.pendingBudget)}</strong><span>${summary.pendingUnknown ? `${summary.pendingUnknown} 件尚未填写预算` : '按整项预计总价汇总'}</span></div>${bought}</div><div class="manager-toolbar"><label class="label-check"><input id="shopping-show-bought" type="checkbox" ${includeBought ? 'checked' : ''}>显示已买到</label>${canEdit() ? `<button class="btn small" data-action="add" data-kind="shopping">${icon('plus')}添加物品</button>` : ''}</div><div class="manager-list">${items.length ? items.map(item => renderRow(item, true)).join('') : '<p class="help">清单里还没有待买物品。</p>'}</div><p class="help shopping-ledger-note">这里记录采购估价和实付，家庭收支仍以财务核对结果为准。</p></div>`, true);
    document.getElementById('shopping-show-bought').onchange = event => { includeBought = event.target.checked; openManager(); };
  }

  function parseAmount(value) {
    const raw = String(value ?? '').trim();
    if (raw === '') return null;
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) throw new Error('金额请填写不超过两位小数的非负数字');
    const [yuan, fraction = ''] = raw.split('.');
    const cents = Number(yuan) * 100 + Number(fraction.padEnd(2, '0'));
    if (!Number.isSafeInteger(cents) || cents > 100000000000) throw new Error('金额超出可填写范围');
    return cents;
  }

  async function compressPhoto(file) {
    const accepted = /^(image\/(jpeg|png|webp))$/i.test(file.type) || (!file.type && /\.(jpe?g|png|webp)$/i.test(file.name));
    if (!accepted) throw new Error('请选择 JPG、PNG 或 WebP 图片；HEIC 图片请先转成 JPG');
    if (!file.size || file.size > 20 * 1024 * 1024) throw new Error('请选择小于 20 MB 的图片');
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error('图片无法读取，请换一张 JPG、PNG 或 WebP 图片')); });
      if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 80000000) throw new Error('图片尺寸过大，请裁剪后再上传');
      const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('浏览器暂时无法处理图片，请换一个浏览器重试');
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const result = canvas.toDataURL('image/jpeg', 0.84);
      if (result.length > 7 * 1024 * 1024) throw new Error('处理后的图片仍然太大，请裁剪后再上传');
      return result;
    } finally { URL.revokeObjectURL(url); }
  }

  function openEditor(id = '', extras = {}) {
    if (!canEdit()) return;
    activeManager = '';
    const item = (data.shopping || []).find(entry => entry.id === id), value = item || extras;
    if (id && !item) { toast('这件物品已被删除，请刷新后重试', true); return; }
    const photoIds = [...photosOf(value)];
    const amountValue = key => validAmount(value[key]) ? (value[key] / 100).toFixed(2) : '';
    openModal(item ? '编辑采购物品' : '添加采购物品', `<form class="shopping-form"><div class="fields">${field('物品名称', 'title', value.title || '', 'text', 'required maxlength="100"')}${field('数量', 'quantity', value.quantity || '1 件', 'text', 'required maxlength="30"')}${selectField('负责人', 'owner', ownerOptions(value.owner || 'shared'))}${field('预计总价（元，选填）', 'budget', amountValue('budget'), 'number', 'min="0" max="1000000000" step="0.01" inputmode="decimal" placeholder="整项预算，不是单价"')}${field('实际总价（元，选填）', 'actual', amountValue('actual'), 'number', 'min="0" max="1000000000" step="0.01" inputmode="decimal" placeholder="买到后填写实际金额"')}<label class="label-check shopping-done-label"><input type="checkbox" name="done" ${value.done ? 'checked' : ''}>已买到</label>${noteField(value.note, '规格、购买链接或备注')}<div class="field full shopping-photo-field"><span>参考图片 · 最多 3 张</span><div id="shopping-photo-list" class="shopping-photo-list"></div><label class="btn secondary shopping-upload-label">${icon('upload')}<span>添加图片</span><input id="shopping-photo-input" type="file" accept="image/jpeg,image/png,image/webp" multiple aria-label="上传采购参考图片"></label><small id="shopping-photo-status" aria-live="polite">支持 JPG、PNG、WebP；图片会自动压缩。</small><p class="shopping-upload-error" role="alert"></p></div></div><p class="help">预算按整项总价填写；实付在勾选“已买到”后计入采购汇总。保存的图片将与伴侣及已配对电视共享。</p>${formFooter('shopping', item)}</form>`);
    const form = document.querySelector('#dialog .shopping-form'), input = form.querySelector('#shopping-photo-input');
    form.elements.note.maxLength = 500;
    const list = form.querySelector('#shopping-photo-list'), status = form.querySelector('#shopping-photo-status');
    const uploadError = form.querySelector('.shopping-upload-error'), save = form.querySelector('button[type=submit]');
    let uploading = false;
    const drawPhotos = () => {
      list.innerHTML = photoIds.map((photoId, index) => `<div class="shopping-photo-chip"><img src="${photoURL(photoId)}" alt="参考图片 ${index + 1}"><button class="shopping-photo-remove" type="button" data-photo-remove="${index}" aria-label="移除第 ${index + 1} 张参考图片">${icon('close')}</button></div>`).join('');
      input.disabled = uploading || photoIds.length >= 3;
      input.closest('label').classList.toggle('disabled', input.disabled);
      if (!uploading) status.textContent = `${photoIds.length} / 3 张 · 支持 JPG、PNG、WebP；自动压缩。`;
    };
    list.onclick = event => {
      const button = event.target.closest('[data-photo-remove]');
      if (!button || uploading) return;
      photoIds.splice(Number(button.dataset.photoRemove), 1); drawPhotos();
    };
    input.onchange = async () => {
      const files = Array.from(input.files || []); input.value = '';
      if (!files.length || uploading) return;
      uploadError.textContent = '';
      if (files.length > 3 - photoIds.length) { uploadError.textContent = '每件物品最多 3 张图片，请减少选择的数量'; return; }
      uploading = true; save.disabled = true; drawPhotos();
      let uploaded = 0;
      try {
        for (const file of files) {
          if (!form.isConnected) break;
          status.textContent = `正在处理第 ${uploaded + 1} / ${files.length} 张图片…`;
          const dataUrl = await compressPhoto(file);
          if (!form.isConnected) break;
          const result = await write('/photos', 'POST', { dataUrl });
          if (!result.id || !/^[A-Za-z0-9_-]{1,128}$/.test(result.id)) throw new Error('图片上传结果异常，请重新尝试');
          if (!form.isConnected) break;
          photoIds.push(result.id); uploaded++; drawPhotos();
        }
      } catch (error) {
        uploadError.textContent = `${uploaded ? `已保留 ${uploaded} 张成功上传的图片。` : ''}${error.message}。可重新选择图片，或先保存文字。`;
      } finally { uploading = false; save.disabled = false; drawPhotos(); }
    };
    drawPhotos();
    bindForm(async (values, currentForm) => {
      if (uploading) throw new Error('图片上传中，请稍等后保存');
      const payload = { title: values.title, quantity: values.quantity, owner: values.owner, note: values.note, done: currentForm.elements.done.checked, budget: parseAmount(values.budget), actual: parseAmount(values.actual), photoIds: [...photoIds] };
      if (item) payload.revision = item.revision;
      await write('/items/shopping' + (item ? '/' + encodeURIComponent(id) : ''), item ? 'PATCH' : 'POST', payload);
    });
  }

  document.addEventListener('click', event => {
    const settlement = event.target.closest('[data-shopping-settlement-shopping]');
    if (settlement && canEdit() && !isTV && !isDemo && window.ShoppingSettlement) {
      event.preventDefault();
      void window.ShoppingSettlement.open({shoppingId: settlement.dataset.shoppingSettlementShopping});
      return;
    }
    const button = event.target.closest('[data-shopping-photo]');
    if (!button || isTV) return;
    const item = (data?.shopping || []).find(entry => entry.id === button.dataset.shoppingPhoto);
    if (!item) return;
    activeManager = '';
    openModal(item.title + ' · 参考图片', `<div class="shopping-gallery">${photosOf(item).map((id, index) => `<figure><img src="${photoURL(id)}" alt="${esc(item.title)}参考图片 ${index + 1}"><figcaption>图片 ${index + 1} / ${photosOf(item).length}</figcaption></figure>`).join('')}</div>`, true);
  });
  setInterval(() => {
    if (!isTV || !data || document.hidden) return;
    const cycle = Math.floor(Math.max(0, Date.now() - tvStartedAt) / 20000);
    const card = document.querySelector('.shopping-card');
    if (card && cycle !== displayedTVCycle) card.outerHTML = renderCard();
  }, 1000);
  return { renderCard, renderRow, openEditor, openManager, summarize };
})();
