import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Checkbox, Dialog, Divider, List, Portal, RadioButton, Searchbar, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { dayKey } from '../lib/calendar';
import { useHousehold } from '../lib/household';
import type { ScreenProps } from '../lib/types';
import { Acquisition, InventoryDiscarded, InventoryFence, InventoryItem, InventoryPage, InventoryResult, InventorySession, Movement, MovementKind, afterSalesLabels, inventoryDate, inventoryRequestId, isInventoryId, movementConfirmations, movementLabels, orderLabels, quantityInput, validateAcquisition, validateItem, validateMovement, validatePage, validateResult } from '../lib/inventory';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Props = ScreenProps & { inventoryRequest?: { key: number; id?: string } };
type ItemDraft = { type: 'item'; id?: string; title: string; unit: string; variant: string; location: string; visibility: 'private' | 'shared'; reorderPoint: string };
type BatchDraft = { type: 'batch'; id?: string; kind: 'purchase' | 'opening'; orderedQty: string; orderState: keyof typeof orderLabels; orderedOn: string; expectedOn: string; warrantyUntil: string; afterSalesState: keyof typeof afterSalesLabels; shoppingId: string; note: string };
type MovementDraft = { type: 'movement'; kind: MovementKind | 'reverse'; movement?: Movement; quantity: string; occurredOn: string; reason: string; confirmed: boolean };
type Draft = ItemDraft | BatchDraft | MovementDraft;
type Intent = { path: string; method: string; body: Record<string, unknown>; requestId: string; itemId?: string; acquisitionId?: string; state: 'unknown' | 'rejected' };
const emptyPage = <T,>(limit: number): InventoryPage<T> => ({ items: [], total: 0, offset: 0, limit, nextOffset: null });
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法完成操作，请稍后再试。';
const blankItem = (): ItemDraft => ({ type: 'item', title: '', unit: '件', variant: '', location: '', visibility: 'private', reorderPoint: '' });
const itemDraft = (item: InventoryItem): ItemDraft => ({ type: 'item', id: item.id, title: item.title, unit: item.unit, variant: item.variant, location: item.location, visibility: item.visibility, reorderPoint: item.reorderPoint === null ? '' : String(item.reorderPoint) });
const batchDraft = (kind: 'purchase' | 'opening', batch?: Acquisition): BatchDraft => ({ type: 'batch', id: batch?.id, kind, orderedQty: batch ? String(batch.orderedQty) : '', orderState: batch?.orderState || (kind === 'opening' ? 'closed' : 'planned'), orderedOn: batch?.orderedOn || '', expectedOn: batch?.expectedOn || '', warrantyUntil: batch?.warrantyUntil || '', afterSalesState: batch?.afterSalesState || 'none', shoppingId: batch?.shoppingId || '', note: batch?.note || '' });

export default function InventoryScreen(props: Props) {
  const household = useHousehold();
  if (props.user.role !== 'member') return <EmptyState title="请用成员账户管理家庭物品" description="电视不读取家庭物品和操作历史。" />;
  return <InventoryWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}

function InventoryWorkspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme();
  const latest = useRef(household); latest.current = household;
  const alive = useRef(false), active = useRef(false), routeFocused = useRef(false), working = useRef(false), generation = useRef(0);
  const fence = useRef(new InventoryFence(() => request<InventorySession>('/me'), props.identityKey));
  const requestKey = useRef<number | undefined>(undefined);
  const [visible, setVisible] = useState(false), [denied, setDenied] = useState(false), [busy, setBusy] = useState(false), [loading, setLoading] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [scope, setScope] = useState('all'), [query, setQuery] = useState(''), [search, setSearch] = useState('');
  const [page, setPage] = useState<InventoryPage<InventoryItem>>(emptyPage(24));
  const [item, setItem] = useState<InventoryItem | null>(null), [batch, setBatch] = useState<Acquisition | null>(null);
  const [batches, setBatches] = useState<InventoryPage<Acquisition>>(emptyPage(12));
  const [history, setHistory] = useState<InventoryPage<Movement>>(emptyPage(12)), [historyOpen, setHistoryOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null), [pending, setPending] = useState<Intent | null>(null);
  const [decision, setDecision] = useState<'discard' | 'archive' | null>(null);
  const state = useRef({ item, batch, draft, pending, page, batches, history, historyOpen, scope, search });
  state.current = { item, batch, draft, pending, page, batches, history, historyOpen, scope, search };
  const current = () => alive.current && active.current && (typeof document === 'undefined' || !document.hidden);
  const locked = busy || loading || !!pending || !household.online;
  const navigationLocked = locked || !!draft;

  function clearPrivate() {
    setPage(emptyPage(24)); setItem(null); setBatch(null); setBatches(emptyPage(12)); setHistory(emptyPage(12)); setHistoryOpen(false);
    setDraft(null); setPending(null); setDecision(null); setQuery(''); setSearch(''); setScope('all'); setError(''); setNotice('');
    state.current = { item: null, batch: null, draft: null, pending: null, page: emptyPage(24), batches: emptyPage(12), history: emptyPage(12), historyOpen: false, scope: 'all', search: '' };
  }
  function invalidate() {
    active.current = false; ++generation.current; fence.current.invalidate(); clearPrivate();
    setVisible(false); setBusy(false); setLoading(false); working.current = false;
  }
  function fail(caught: unknown) {
    if (!current()) return;
    if (caught instanceof InventoryDiscarded && caught.message !== 'identity') return;
    if (caught instanceof InventoryDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) {
      invalidate(); setDenied(true); void latest.current.refresh(); return;
    }
    if (caught instanceof ApiError && [404, 410].includes(caught.status)) {
      // A stale shared item may also remain in the list: clear every projection.
      clearPrivate(); setError('这件物品已归档或不再对你可见，旧详情和草稿已清空。'); return;
    }
    setError(message(caught));
  }
  async function read<T>(path: string, valid = () => true): Promise<T> {
    return fence.current.run(() => request<T>(path), () => current() && valid());
  }
  async function readItems(nextScope = state.current.scope, nextSearch = state.current.search, offset = 0) {
    const data = await read<InventoryPage<InventoryItem>>(`/inventory/items?scope=${nextScope}&q=${encodeURIComponent(nextSearch)}&limit=24&offset=${offset}`);
    return validatePage(data, 24, validateItem);
  }
  async function readItem(id: string) {
    const data = await read<{ item: InventoryItem }>(`/inventory/items/${id}`);
    if (validateItem(data.item).id !== id) throw new Error('物品已变化，请重新读取。'); return data.item;
  }
  async function readBatch(id: string) {
    const data = await read<{ item: InventoryItem; acquisition: Acquisition }>(`/inventory/acquisitions/${id}`);
    validateItem(data.item); validateAcquisition(data.acquisition);
    if (data.acquisition.id !== id || data.acquisition.itemId !== data.item.id || data.acquisition.itemRevision !== data.item.revision) throw new Error('批次正在更新，请重新读取。');
    return data;
  }
  async function readBatches(id: string, offset = 0) {
    const data = validatePage(await read<InventoryPage<Acquisition>>(`/inventory/items/${id}/acquisitions?limit=12&offset=${offset}`), 12, validateAcquisition);
    if (data.items.some(row => row.itemId !== id)) throw new Error('批次数据无法核对。'); return data;
  }
  async function readHistory(id: string, offset = 0) {
    const data = validatePage(await read<InventoryPage<Movement>>(`/inventory/acquisitions/${id}/movements?limit=12&offset=${offset}`), 12, validateMovement);
    if (data.items.some(row => row.acquisitionId !== id)) throw new Error('变动历史无法核对。'); return data;
  }
  async function runRead(action: () => Promise<void>) {
    if (working.current || !current()) return;
    working.current = true; const ticket = generation.current; setLoading(true); setError('');
    try { await action(); } catch (caught) { fail(caught); }
    finally { if (ticket === generation.current) { working.current = false; if (current()) setLoading(false); } }
  }
  async function refreshView() {
    const saved = state.current;
    const values = await readItems(saved.scope, saved.search, saved.page.offset);
    let detail = saved.item ? await readItem(saved.item.id) : null;
    const records = detail ? await readBatches(detail.id, saved.batches.offset) : emptyPage<Acquisition>(12);
    const selected = saved.batch ? await readBatch(saved.batch.id) : null;
    if (selected) detail = selected.item;
    const movements = saved.batch && saved.historyOpen ? await readHistory(saved.batch.id, saved.history.offset) : emptyPage<Movement>(12);
    if (!current()) return;
    setPage(values); setItem(detail); setBatches(records); setBatch(selected?.acquisition || null); setHistory(movements);
  }
  function enter() {
    if (!alive.current || active.current || !routeFocused.current || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; setVisible(true); setDenied(false);
    fence.current = new InventoryFence(() => request<InventorySession>('/me'), props.identityKey);
    void runRead(async () => { const values = await readItems('all', '', 0); if (current()) setPage(values); });
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++generation.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => {
    routeFocused.current = true; enter();
    return () => { routeFocused.current = false; invalidate(); };
  }, [props.identityKey]));
  useEffect(() => {
    const onVisibility = () => { if (document.hidden) invalidate(); else enter(); };
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility);
    const subscription = AppState.addEventListener('change', value => { if (value === 'active') enter(); else invalidate(); });
    return () => { if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility); subscription.remove(); };
  }, [props.identityKey]);
  useEffect(() => {
    if (!visible || denied) return;
    const timer = setInterval(() => {
      if (!current() || working.current || state.current.draft || state.current.pending) return;
      void runRead(refreshView);
    }, 15000);
    return () => clearInterval(timer);
  }, [visible, denied]);
  useEffect(() => {
    const incoming = props.inventoryRequest;
    if (!visible || loading || busy || !incoming || incoming.key === requestKey.current) return;
    requestKey.current = incoming.key;
    if (state.current.draft || state.current.pending) { setNotice('请先完成或取消当前编辑，再打开另一件物品。'); return; }
    if (incoming.id) { if (isInventoryId(incoming.id)) void openItem(incoming.id); else setError('物品链接无效，请在列表中查找。'); }
    else { setItem(null); setBatch(null); setHistoryOpen(false); }
  }, [props.inventoryRequest?.key, visible, loading, busy]);

  async function openItem(id: string) {
    if (navigationLocked) return;
    await runRead(async () => {
      const detail = await readItem(id), records = await readBatches(id);
      if (!current()) return; setItem(detail); setBatches(records); setBatch(null); setHistory(emptyPage(12)); setHistoryOpen(false); setNotice('');
    });
  }
  async function openBatch(id: string) {
    if (navigationLocked) return;
    await runRead(async () => { const data = await readBatch(id); if (!current()) return; setItem(data.item); setBatch(data.acquisition); setHistoryOpen(false); setHistory(emptyPage(12)); setNotice(''); });
  }
  function begin(value: Draft) {
    if (navigationLocked || working.current) return; setDraft(value); setError(''); setNotice('');
  }
  function change(patch: Record<string, unknown>) { if (!locked && !working.current) setDraft(previous => previous ? { ...previous, ...patch } as Draft : null); }
  function beginMovement(kind: MovementKind | 'reverse', movement?: Movement) {
    begin({ type: 'movement', kind, movement, quantity: '', occurredOn: dayKey(), reason: '', confirmed: false });
  }
  async function accept(result: InventoryResult) {
    if (!current()) return;
    setDraft(null); setPending(null); setDecision(null); setError('');
    if (result.operation.deleted) {
      setItem(null); setBatch(null); setBatches(emptyPage(12)); setHistory(emptyPage(12)); setHistoryOpen(false);
      setNotice('物品已归档，原操作历史由系统保留。');
    } else {
      setItem(result.item!); setBatch(result.acquisition || null); setHistoryOpen(false); setHistory(emptyPage(12));
      setNotice(result.operation.replayed ? '已核对原操作，没有重复记录。' : '已保存。库存数量以实际记录为准。');
    }
    // The receipt is already confirmed. A later list read failure must not turn
    // the successful write into an unknown write or re-enable its old request.
    try {
      const values = await readItems(state.current.scope, state.current.search, 0);
      const records = result.item ? await readBatches(result.item.id) : emptyPage<Acquisition>(12);
      if (current()) { setPage(values); setBatches(records); }
    } catch (caught) { fail(caught); }
    void latest.current.refresh();
  }
  async function send(intent: Intent, recover = false) {
    if (working.current || !current()) return;
    working.current = true; const ticket = generation.current; setBusy(true); setError(''); setPending(intent);
    let submitted = false;
    try {
      if (recover) {
        try {
          const receipt = await read<InventoryResult>(`/inventory/operations/${intent.requestId}`);
          await accept(validateResult(receipt, intent.itemId, intent.acquisitionId)); return;
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 404) throw caught;
          // No readable receipt can also mean access was withdrawn. Recheck the
          // target before sending the exact original intent, never new versions.
          if (intent.acquisitionId) await readBatch(intent.acquisitionId);
          else if (intent.itemId) await readItem(intent.itemId);
        }
      }
      const result = await fence.current.run(csrf => {
        submitted = true;
        return request<InventoryResult>(intent.path, { method: intent.method, body: JSON.stringify(intent.body) }, csrf);
      }, current);
      await accept(validateResult(result, intent.itemId, intent.acquisitionId));
    } catch (caught) {
      if (!current()) return;
      if (caught instanceof InventoryDiscarded || caught instanceof ApiError && [401, 403, 404, 410].includes(caught.status)) { fail(caught); return; }
      const rejected = caught instanceof ApiError && caught.status >= 400 && caught.status < 500;
      setPending({ ...intent, state: rejected && submitted ? 'rejected' : 'unknown' });
      setError(rejected && submitted ? message(caught) + ' 输入仍保留，请重新核对后再确认。' : '本次保存结果尚未确定。请核对原操作，不要重新创建或重复登记。');
    } finally {
      if (ticket === generation.current) { working.current = false; if (current()) setBusy(false); }
    }
  }
  function makeIntent(path: string, method: string, body: Record<string, unknown>, itemId?: string, acquisitionId?: string): Intent {
    const requestId = inventoryRequestId(); return { path, method, body: { ...body, requestId }, requestId, itemId, acquisitionId, state: 'unknown' };
  }
  function save() {
    if (!draft || locked || working.current) return;
    try {
      if (draft.type === 'item') {
        const data = { title: draft.title.trim(), unit: draft.unit.trim(), variant: draft.variant.trim(), location: draft.location.trim(), visibility: draft.visibility, reorderPoint: draft.reorderPoint.trim() ? quantityInput(draft.reorderPoint, false, true) : null };
        if (!data.title || !data.unit) throw new Error('请填写物品名称和计量单位。');
        if (draft.id) {
          if (!item?.canManage || item.id !== draft.id) throw new Error('请重新打开物品后再编辑。');
          void send(makeIntent(`/inventory/items/${item.id}`, 'PATCH', { revision: item.revision, patch: data }, item.id));
        } else void send(makeIntent('/inventory/items', 'POST', { data }));
      } else if (draft.type === 'batch') {
        if (!item?.canMutate) throw new Error('请重新打开物品后再添加批次。');
        const values: Record<string, unknown> = {
          kind: draft.kind, orderedQty: quantityInput(draft.orderedQty), orderState: draft.kind === 'opening' ? 'closed' : draft.orderState,
          orderedOn: draft.kind === 'opening' ? null : inventoryDate(draft.orderedOn), expectedOn: draft.kind === 'opening' ? null : inventoryDate(draft.expectedOn),
          warrantyUntil: inventoryDate(draft.warrantyUntil), afterSalesState: draft.afterSalesState, shoppingId: draft.kind === 'opening' ? null : draft.shoppingId || null, note: draft.note.trim(),
        };
        if (draft.id) {
          if (!batch?.canMutate || batch.id !== draft.id) throw new Error('请重新打开批次后再编辑。');
          const patch = Object.fromEntries(Object.entries(values).filter(([key]) => key !== 'kind' && batch.editableFields.includes(key)));
          void send(makeIntent(`/inventory/acquisitions/${batch.id}`, 'PATCH', { itemRevision: item.revision, revision: batch.revision, patch }, item.id, batch.id));
        } else void send(makeIntent(`/inventory/items/${item.id}/acquisitions`, 'POST', { itemRevision: item.revision, data: values }, item.id));
      } else {
        if (!item?.canMutate || !batch?.canMutate) throw new Error('请重新打开批次后再操作。');
        if (!draft.confirmed) throw new Error('请先核对实际物品和数量。');
        const date = inventoryDate(draft.occurredOn, true), reason = draft.reason.trim();
        if (draft.kind !== 'receive' && !reason) throw new Error('请填写操作原因，便于以后核对。');
        const common = { itemRevision: item.revision, revision: batch.revision };
        if (draft.kind === 'reverse') {
          if (!draft.movement || !draft.movement.canReverse || draft.movement.acquisitionId !== batch.id) throw new Error('请重新核对要撤销的记录。');
          void send(makeIntent(`/inventory/acquisitions/${batch.id}/movements/${draft.movement.id}/reverse`, 'POST', { ...common, data: { occurredOn: date, reason }, confirmReversal: true }, item.id, batch.id));
        } else {
          const quantity = quantityInput(draft.quantity, draft.kind === 'adjust');
          void send(makeIntent(`/inventory/acquisitions/${batch.id}/movements`, 'POST', { ...common, data: { kind: draft.kind, quantity, occurredOn: date, reason }, [movementConfirmations[draft.kind]]: true }, item.id, batch.id));
        }
      }
    } catch (caught) { setError(message(caught)); }
  }
  async function rebase() {
    if (!pending || pending.state !== 'rejected') return;
    const intent = pending;
    await runRead(async () => {
      const saved = state.current;
      if (intent.acquisitionId) {
        const fresh = await readBatch(intent.acquisitionId); if (!current()) return; setItem(fresh.item); setBatch(fresh.acquisition);
        if (saved.draft?.type === 'movement' && saved.draft.kind === 'reverse') {
          // Keep the original target. The server checks whether it was already
          // reversed; do not substitute another event from a newer history page.
          setHistory(emptyPage(12)); setHistoryOpen(false);
        }
      } else if (intent.itemId) { const fresh = await readItem(intent.itemId); if (current()) setItem(fresh); }
      else await read<InventorySession>('/me');
      if (!current()) return;
      setDraft(previous => previous?.type === 'movement' ? { ...previous, confirmed: false } : previous);
      setPending(null); setError(''); setNotice('已读取最新数量和权限，输入仍保留。请核对后再次明确保存。');
    });
  }
  function archive() {
    setDecision(null);
    if (!item?.canManage || navigationLocked) return;
    try { void send(makeIntent(`/inventory/items/${item.id}`, 'DELETE', { revision: item.revision, confirmArchive: true }, item.id)); }
    catch (caught) { setError(message(caught)); }
  }
  function applyFilter(nextScope: string, nextSearch: string) {
    if (navigationLocked) return;
    void runRead(async () => { const values = await readItems(nextScope, nextSearch); if (current()) { setScope(nextScope); setSearch(nextSearch); setPage(values); } });
  }
  function pageTo(kind: 'items' | 'batches' | 'history', offset: number) {
    if (navigationLocked) return;
    void runRead(async () => {
      if (kind === 'items') { const values = await readItems(scope, search, offset); if (current()) setPage(values); }
      if (kind === 'batches' && item) { const values = await readBatches(item.id, offset); if (current()) setBatches(values); }
      if (kind === 'history' && batch) { const values = await readHistory(batch.id, offset); if (current()) setHistory(values); }
    });
  }
  const field = (label: string, value: string, name: string, limit: number, numeric = false, multiline = false) => <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} label={label} accessibilityLabel={label} value={value} onChangeText={text => change({ [name]: text })} maxLength={limit} disabled={locked} keyboardType={numeric ? 'numbers-and-punctuation' : 'default'} multiline={multiline} />;
  const pager = <T,>(values: InventoryPage<T>, title: string, kind: 'items' | 'batches' | 'history') => values.total > values.limit || values.offset > 0 ? <View style={styles.pager}>
    <Button accessibilityLabel={title + '上一页'} disabled={navigationLocked || values.offset === 0} onPress={() => pageTo(kind, Math.max(0, values.offset - values.limit))}>上一页</Button>
    <Text variant="bodySmall">第 {Math.floor(values.offset / values.limit) + 1} 页 · {values.total} 条</Text>
    <Button accessibilityLabel={title + '下一页'} disabled={navigationLocked || values.nextOffset === null} onPress={() => pageTo(kind, values.nextOffset!)}>下一页</Button>
  </View> : null;
  const choices = (value: string, name: string, labels: Record<string, string>) => <RadioButton.Group value={value} onValueChange={next => change({ [name]: next })}><View style={styles.wrap}>{Object.entries(labels).map(([key, label]) => <RadioButton.Item key={key} value={key} label={label} accessibilityLabel={label} disabled={locked} position="leading" labelStyle={styles.choiceText} />)}</View></RadioButton.Group>;
  const stat = (label: string, quantity: number) => <View style={styles.stat}><Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{label}</Text><Text variant="headlineSmall">{quantity.toLocaleString('zh-CN')} <Text variant="bodyMedium">{item?.unit}</Text></Text></View>;
  const editable = (name: string) => draft?.type === 'batch' && (!draft.id || !!batch?.editableFields.includes(name));

  if (denied) return <EmptyState title="正在核对登录身份" description="旧账户的家庭物品和草稿已清空。" />;
  if (!visible) return null;
  return <View style={styles.page}>
    <PageHeader title="家庭物品" description="知道家里有什么，到货后顺手记一下。" action={<Button mode="contained" icon="plus" disabled={navigationLocked} onPress={() => begin(blankItem())}>新增物品</Button>} />
    <View style={styles.wrap}>
      {item && <Button icon="arrow-left" disabled={navigationLocked} onPress={() => { setItem(null); setBatch(null); setBatches(emptyPage(12)); setHistory(emptyPage(12)); setHistoryOpen(false); }}>返回物品列表</Button>}
      {batch && <Button disabled={navigationLocked} onPress={() => { setBatch(null); setHistory(emptyPage(12)); setHistoryOpen(false); }}>返回物品详情</Button>}
      <Button icon="refresh" disabled={navigationLocked} onPress={() => void runRead(refreshView)}>刷新物品</Button>
    </View>
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {!household.online && <Text accessibilityRole="alert">连接暂时不可用，恢复网络后可继续核对。未保存内容仅留在本页。</Text>}
    {(busy || loading) && <ActivityIndicator accessibilityLabel={busy ? '正在保存物品' : '正在读取物品'} />}
    {pending && <SectionCard title={pending.state === 'unknown' ? '先核对本次操作' : '请核对最新记录'}>
      <Text>当前输入仍保留。核对期间请留在此页，不要另建相同记录。</Text>
      <Button mode="contained" disabled={busy || loading || !household.online} onPress={() => pending.state === 'unknown' ? void send(pending, true) : void rebase()}>{pending.state === 'unknown' ? '核对并重试本次操作' : '重新核对并修改草稿'}</Button>
    </SectionCard>}

    {draft ? <SectionCard title={draft.type === 'item' ? draft.id ? '编辑物品' : '新增物品' : draft.type === 'batch' ? draft.id ? '编辑批次' : draft.kind === 'opening' ? '登记家中已有' : '添加采购批次' : draft.kind === 'reverse' ? '撤销原记录' : '记录' + movementLabels[draft.kind]}>
      <View style={styles.fields}>
        {draft.type === 'item' && <>
          {field('物品名称', draft.title, 'title', 100)}
          <View style={styles.columns}><View style={styles.column}>{field('计量单位', draft.unit, 'unit', 20)}</View><View style={styles.column}>{field('规格', draft.variant, 'variant', 200)}</View></View>
          {field('存放位置', draft.location, 'location', 100)}
          {choices(draft.visibility, 'visibility', { private: '仅本人可见', shared: '与家庭共享' })}
          <Text variant="bodySmall">共享后，家庭成员可以记录收货、使用等实物变化；只有你能改物品信息和共享范围。</Text>
          <List.Accordion title="补货提醒" description="可选；只提醒，不自动下单"><View style={styles.fields}>{field('补货提醒数量', draft.reorderPoint, 'reorderPoint', 7, true)}<Text variant="bodySmall">现有与在途数量合计低于此数时提醒，留空则关闭。</Text></View></List.Accordion>
        </>}
        {draft.type === 'batch' && <>
          <Text>{item?.title} · {draft.kind === 'opening' ? '家中已有物品' : '采购记录'}</Text>
          <Text variant="bodySmall">保存批次不会增加库存。保存后点击“收货”，明确登记实际收到或已在家中的数量。</Text>
          {editable('orderedQty') ? field('批次数量', draft.orderedQty, 'orderedQty', 7, true) : <Text>批次数量：{batch?.orderedQty} {item?.unit}（由物品拥有者或登记人修改）</Text>}
          {draft.kind === 'purchase' && editable('orderState') && choices(draft.orderState, 'orderState', orderLabels)}
          {draft.kind === 'purchase' && editable('expectedOn') && field('预计到货日期（YYYY-MM-DD）', draft.expectedOn, 'expectedOn', 10)}
          {editable('note') && field('批次备注', draft.note, 'note', 500, false, true)}
          <List.Accordion title="日期、售后与采购关联" description="按需填写"><View style={styles.fields}>
            {draft.kind === 'purchase' && editable('orderedOn') && field('下单日期（YYYY-MM-DD）', draft.orderedOn, 'orderedOn', 10)}
            {editable('warrantyUntil') && field('保修截止（YYYY-MM-DD）', draft.warrantyUntil, 'warrantyUntil', 10)}
            {editable('afterSalesState') && choices(draft.afterSalesState, 'afterSalesState', afterSalesLabels)}
            {draft.kind === 'purchase' && editable('shoppingId') && <><Text variant="titleSmall">关联采购清单</Text><RadioButton.Group value={draft.shoppingId} onValueChange={value => change({ shoppingId: value })}>
              <RadioButton.Item value="" label="不关联采购" disabled={locked} />
              {props.state.shopping.map(row => <RadioButton.Item key={row.id} value={row.id} label={row.title} accessibilityLabel={'关联采购 ' + row.title} disabled={locked} labelStyle={styles.choiceText} />)}
              {!!draft.shoppingId && !props.state.shopping.some(row => row.id === draft.shoppingId) && <RadioButton.Item value={draft.shoppingId} label="原采购（待核对）" disabled />}
            </RadioButton.Group><Text variant="bodySmall">只关联家庭采购清单，不改采购完成状态，也不会记入支出。</Text></>}
          </View></List.Accordion>
        </>}
        {draft.type === 'movement' && <>
          <Text>{item?.title} · {batch?.kind === 'opening' ? '家中已有批次' : '采购批次'} · 当前 {batch?.onHandQty} {item?.unit}</Text>
          {draft.kind === 'reverse' ? <Text>撤销 {draft.movement?.occurredOn} 的{movementLabels[draft.movement!.kind]}记录（{draft.movement!.deltaQty > 0 ? '+' : ''}{draft.movement?.deltaQty} {item?.unit}）。将保留原记录并追加相反变化。</Text> : field('本次数量', draft.quantity, 'quantity', 8, true)}
          {draft.kind === 'adjust' && <Text variant="bodySmall">填写需要增加或减少的数量，例如 +2 或 -1；不是最终库存总量。</Text>}
          {draft.kind === 'return' && <Text variant="bodySmall">这里只记录实物退回，不代表已收到退款，也不会重新增加待收数量。</Text>}
          {field('发生日期（YYYY-MM-DD）', draft.occurredOn, 'occurredOn', 10)}
          {field('操作原因', draft.reason, 'reason', 300, false, true)}
          {draft.kind === 'receive' && <Text variant="bodySmall">收货原因可留空；其他实物变化必须填写原因。</Text>}
          <Checkbox.Item label="我已核对实际物品和数量" accessibilityLabel="我已核对实际物品和数量" status={draft.confirmed ? 'checked' : 'unchecked'} position="leading" onPress={() => change({ confirmed: !draft.confirmed })} disabled={locked} labelStyle={styles.choiceText} />
        </>}
        <View style={styles.wrap}>
          <Button mode="contained" disabled={locked || draft.type === 'movement' && !draft.confirmed} onPress={save}>{draft.type === 'item' ? '保存物品' : draft.type === 'batch' ? '保存批次' : draft.kind === 'reverse' ? '确认撤销原记录' : '确认实物变动'}</Button>
          <Button disabled={busy || loading || !!pending} onPress={() => setDecision('discard')}>取消编辑</Button>
        </View>
        <Text variant="bodySmall">未保存的输入只保留在当前页面。离开、切换家庭或将应用放到后台会清空。</Text>
      </View>
    </SectionCard> : item ? <>
      <SectionCard title="物品详情" action={item.canManage ? <Button disabled={navigationLocked} onPress={() => begin(itemDraft(item))}>编辑物品</Button> : undefined}>
        <View style={styles.fields}>
          <Text variant="headlineSmall">{item.title}</Text><Text>{[item.variant, item.location, item.visibility === 'shared' ? '家庭共享' : '仅本人可见'].filter(Boolean).join(' · ')}</Text>
          <View style={styles.wrap}>{stat('家中现有', item.onHandQty)}{stat('已下单待到货', item.inTransitQty)}{stat('计划采购', item.plannedQty)}</View>
          {item.belowThreshold && <Text>该补货了：提醒数量 {item.reorderPoint} {item.unit}。仍需自行决定和下单。</Text>}
          {item.canMutate && <View style={styles.wrap}><Button mode="contained" icon="plus" disabled={navigationLocked} onPress={() => begin(batchDraft('purchase'))}>添加采购批次</Button><Button mode="outlined" disabled={navigationLocked} onPress={() => begin(batchDraft('opening'))}>登记家中已有</Button></View>}
          {item.canManage && <List.Accordion title="物品管理"><View style={styles.fields}><Text>库存为零，且所有批次已结束或取消时，可以归档。原操作历史会保留。</Text><Button disabled={navigationLocked} onPress={() => setDecision('archive')}>归档物品</Button></View></List.Accordion>}
        </View>
      </SectionCard>
      {batch ? <SectionCard title="批次详情" action={batch.canMutate ? <Button disabled={navigationLocked} onPress={() => begin(batchDraft(batch.kind, batch))}>编辑批次</Button> : undefined}>
        <View style={styles.fields}>
          <Text variant="titleMedium">{batch.kind === 'opening' ? '家中已有' : orderLabels[batch.orderState]} · {batch.orderedQty} {item.unit}</Text>
          <View style={styles.wrap}>{stat('此批现有', batch.onHandQty)}{stat('累计已收', batch.receivedQty)}{stat('实物退回', batch.returnedQty)}</View>
          <Text variant="bodySmall">剩余待收 {batch.remainingExpectedQty} {item.unit}{batch.expectedOn ? ' · 预计 ' + batch.expectedOn + ' 到货' : ''}</Text>
          {!!batch.note && <Text>{batch.note}</Text>}
          {!!batch.orderedOn && <Text variant="bodySmall">下单日期：{batch.orderedOn}</Text>}{!!batch.warrantyUntil && <Text variant="bodySmall">保修截止：{batch.warrantyUntil}</Text>}
          {batch.afterSalesState !== 'none' && <Text>{afterSalesLabels[batch.afterSalesState]}</Text>}
          {batch.canMutate && <>
            <Button mode="contained" icon="package-variant-closed-check" disabled={navigationLocked || batch.kind === 'purchase' && ['closed', 'cancelled'].includes(batch.orderState)} onPress={() => beginMovement('receive')}>收货</Button>
            <List.Accordion title="更多实物操作"><View style={styles.wrap}>
              <Button disabled={navigationLocked} onPress={() => beginMovement('consume')}>记录使用</Button><Button disabled={navigationLocked} onPress={() => beginMovement('dispose')}>记录报损</Button><Button disabled={navigationLocked} onPress={() => beginMovement('return')}>记录退回</Button><Button disabled={navigationLocked} onPress={() => beginMovement('adjust')}>更正余量</Button>
            </View></List.Accordion>
          </>}
          <Button disabled={navigationLocked} onPress={() => void runRead(async () => { const data = await readHistory(batch.id); if (current()) { setHistory(data); setHistoryOpen(true); } })}>查看变动历史</Button>
          {historyOpen && <View style={styles.fields}><Divider /><Text variant="titleMedium" accessibilityRole="header">变动历史</Text>
            {!history.items.length && <EmptyState title="还没有实物变化" description="保存批次不会增加库存，请在核对实物后登记收货。" />}
            {history.items.map(movement => <View key={movement.id} style={styles.historyRow}><Text variant="titleSmall">{movementLabels[movement.kind]} · {movement.deltaQty > 0 ? '+' : ''}{movement.deltaQty} {item.unit}</Text><Text variant="bodySmall">{movement.occurredOn}</Text>{!!movement.reason && <Text>{movement.reason}</Text>}{movement.canReverse && batch.canMutate && <Button accessibilityLabel={'撤销这条记录 ' + movement.id} disabled={navigationLocked} onPress={() => beginMovement('reverse', movement)}>撤销这条记录</Button>}</View>)}
            {pager(history, '历史', 'history')}
          </View>}
        </View>
      </SectionCard> : <SectionCard title="采购与已有批次"><View style={styles.fields}>
        {!batches.items.length && !loading && <EmptyState title="先登记一批物品" description="可以记录新采购，或把家里已经有的物品补进来。" />}
        {batches.items.map((row, index) => <View key={row.id} style={styles.listRow}><View style={styles.rowBody}><Text variant="titleMedium">第 {batches.offset + index + 1} 批 · {row.kind === 'opening' ? '家中已有' : orderLabels[row.orderState]}</Text><Text>现有 {row.onHandQty} {item.unit} · 累计已收 {row.receivedQty} / {row.orderedQty} {item.unit}</Text>{!!row.note && <Text variant="bodySmall">{row.note}</Text>}</View><Button accessibilityLabel={'打开批次 ' + row.id} disabled={navigationLocked} onPress={() => void openBatch(row.id)}>查看批次</Button></View>)}
        {pager(batches, '批次', 'batches')}
      </View></SectionCard>}
    </> : <>
      <SectionCard title="我的与家庭共享物品"><View style={styles.fields}>
        <Searchbar placeholder="搜索名称、规格或位置" accessibilityLabel="搜索物品" value={query} onChangeText={setQuery} onSubmitEditing={() => applyFilter(scope, query.trim())} maxLength={100} editable={!navigationLocked} />
        <View style={styles.wrap}><Button disabled={navigationLocked} onPress={() => applyFilter(scope, query.trim())}>搜索</Button>{[['all', '全部'], ['mine', '我的'], ['shared', '已共享']].map(([key, label]) => <Button key={key} mode={scope === key ? 'contained' : 'text'} disabled={navigationLocked} onPress={() => applyFilter(key, query.trim())}>{label}</Button>)}</View>
        {!page.items.length && !loading && <EmptyState title={search ? '没有找到匹配物品' : '把家里的物品记下来'} description={search ? '试试名称、规格或存放位置。' : '新物品默认仅你可见，需要时再与家庭共享。'} />}
        {page.items.map(row => <View key={row.id} style={styles.listRow}><View style={styles.rowBody}><Text variant="titleMedium">{row.title}</Text><Text variant="bodySmall">{[row.variant, row.location, row.visibility === 'shared' ? '家庭共享' : '仅本人可见'].filter(Boolean).join(' · ')}</Text><Text>现有 {row.onHandQty} {row.unit} · 在途 {row.inTransitQty} {row.unit}</Text>{row.belowThreshold && <Text variant="bodySmall">低于补货提醒数量</Text>}</View><Button accessibilityLabel={'查看物品 ' + row.title} disabled={navigationLocked} onPress={() => void openItem(row.id)}>查看</Button></View>)}
        {pager(page, '物品', 'items')}
      </View></SectionCard>
    </>}
    <Portal><Dialog visible={!!decision} dismissable={!busy && !loading} onDismiss={() => setDecision(null)} style={styles.dialog}>
      <Dialog.Title>{decision === 'archive' ? '归档这件物品？' : '放弃这次编辑？'}</Dialog.Title>
      <Dialog.Content><Text>{decision === 'archive' ? '仅当库存为零、所有批次都已结束或取消时才能归档。不会删除原操作历史或财务记录。' : '本次尚未保存的输入将清空。已保存的物品保持不变。'}</Text></Dialog.Content>
      <Dialog.Actions><Button onPress={() => setDecision(null)}>继续保留</Button><Button onPress={() => { if (decision === 'archive') archive(); else { setDraft(null); setDecision(null); setError(''); } }}>{decision === 'archive' ? '确认归档' : '放弃这次编辑'}</Button></Dialog.Actions>
    </Dialog></Portal>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 18 }, fields: { gap: 16 }, wrap: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10 },
  columns: { flexDirection: 'row', flexWrap: 'wrap', gap: 14 }, column: { flexGrow: 1, flexBasis: 200, minWidth: 0 },
  stat: { flexGrow: 1, flexBasis: 170, minWidth: 0, gap: 4, paddingVertical: 10 },
  listRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, paddingVertical: 14 },
  rowBody: { flexGrow: 1, flexShrink: 1, flexBasis: 220, gap: 6, minWidth: 0 },
  historyRow: { gap: 8, paddingVertical: 10 }, choiceText: { flexShrink: 1, textAlign: 'left', fontSize: 14 },
  pager: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  dialog: { borderRadius: 24, maxWidth: 480, width: '90%', alignSelf: 'center' },
});
