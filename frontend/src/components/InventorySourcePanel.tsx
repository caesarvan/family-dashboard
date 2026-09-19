import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Text } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { InventoryDiscarded, InventoryFence, inventoryRequestId, validateAcquisition, validateItem, type Acquisition, type InventoryItem, type InventorySession } from '../lib/inventory';
import { canManageSource, orderSourcesPath, readAcquisitionSource, readOrderSources, readSourcePreview, readSourceReceipt, type AcquisitionSource, type OrderSources, type SourceIntent, type SourcePreview } from '../lib/inventorySources';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Props = { acquisitionId: string; orderId?: string; lineKey?: string; onBack: () => void; onSaved: () => void; onPendingChange?: (message: string | null) => void };
type Context = { item: InventoryItem; acquisition: Acquisition; source: AcquisitionSource; order: OrderSources | null };
type Intent = { input: SourceIntent; preview: SourcePreview };
const message = (e: unknown) => e instanceof Error ? e.message : '暂时无法核对，请稍后重试。';
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;

export default function InventorySourcePanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="订单来源仅本人查看" />;
  return <Workspace key={household.identityKey + ':' + props.acquisitionId} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef({ household, props }); latest.current = { household, props };
  const alive = useRef(false), focused = useRef(false), active = useRef(false), working = useRef(false), epoch = useRef(0), denied = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new InventoryFence(() => request<InventorySession>('/me'), props.identityKey));
  const [context, setContext] = useState<Context | null>(null), [preview, setPreview] = useState<Intent | null>(null), [unknown, setUnknown] = useState<Intent | null>(null);
  const live = useRef({ context, preview, unknown }); live.current = { context, preview, unknown };
  const [busy, setBusy] = useState(false), [visible, setVisible] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && foreground.current && ticket === epoch.current
    && latest.current.household.identityKey === props.identityKey && latest.current.household.online && online() && (typeof document === 'undefined' || !document.hidden);
  function notify() { props.onPendingChange?.(working.current ? '正在核对订单来源，请稍候。' : live.current.unknown ? '请先核对本次来源关联结果，再离开。' : live.current.preview ? '请先确认或取消来源预览，再离开。' : null); }
  function install(patch: Partial<typeof live.current>) { live.current = { ...live.current, ...patch }; if ('context' in patch) setContext(patch.context!); if ('preview' in patch) setPreview(patch.preview!); if ('unknown' in patch) setUnknown(patch.unknown!); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); working.current = false; setBusy(false); setVisible(false);
    install({ context: null, preview: null, ...(clear ? { unknown: null } : {}) }); setError(''); setNotice('');
  }
  function fail(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof InventoryDiscarded && e.message !== 'identity') return;
    if (e instanceof InventoryDiscarded || e instanceof ApiError && [401, 403, 404, 410].includes(e.status)) {
      conceal(true); denied.current = true; setError('订单来源或批次已不可访问，旧资料已隐藏。请返回后重新打开。'); void latest.current.household.refresh(); return;
    }
    setError(message(e));
  }
  async function guarded<T>(action: (csrf: string) => Promise<T>, ticket = epoch.current): Promise<T> { return fence.current.run(action, () => current(ticket)); }
  async function readContext(ticket: number) {
    const raw = await guarded(() => request<{ item: InventoryItem; acquisition: Acquisition }>(`/inventory/acquisitions/${props.acquisitionId}`), ticket);
    const item = validateItem(raw.item), acquisition = validateAcquisition(raw.acquisition);
    if (acquisition.id !== props.acquisitionId || acquisition.itemId !== item.id || acquisition.itemRevision !== item.revision || !canManageSource(acquisition)) throw new Error('只有这批物品的登记人可以管理自己的订单来源。');
    const source = readAcquisitionSource(await guarded(() => request(`/inventory/acquisitions/${props.acquisitionId}/source`), ticket), item.id, acquisition.id);
    let order: OrderSources | null = null;
    if (props.orderId && props.lineKey && source.link?.status !== 'active') {
      const index = props.lineKey.startsWith('item:') ? Number(props.lineKey.slice(5)) : 0, offset = Math.floor(index / 50) * 50;
      try { order = readOrderSources(await guarded(() => request(orderSourcesPath(props.orderId!, offset)), ticket), props.orderId, offset); }
      catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e; }
    }
    if (current(ticket)) install({ context: { item, acquisition, source, order } });
  }
  async function job(action: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current; working.current = true; setBusy(true); setError(''); notify();
    try { await action(ticket); } catch (e) { fail(e, ticket); }
    finally { if (ticket === epoch.current) { working.current = false; setBusy(false); notify(); } }
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || denied.current || !foreground.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true;
    void job(async ticket => { if (live.current.unknown) await guarded(async () => true, ticket); else await readContext(ticket); if (current(ticket)) setVisible(true); });
  }
  const lifecycle = useRef({ enter, conceal }); lifecycle.current = { enter, conceal };
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); latest.current.props.onPendingChange?.(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; lifecycle.current.enter(); return () => { focused.current = false; lifecycle.current.conceal(true); }; }, [props.identityKey]));
  useEffect(() => {
    const sync = () => { if (typeof document !== 'undefined' && document.hidden || !online()) lifecycle.current.conceal(); else lifecycle.current.enter(); };
    const app = AppState.addEventListener('change', state => { foreground.current = state === 'active'; if (foreground.current) lifecycle.current.enter(); else lifecycle.current.conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', sync);
    if (typeof window !== 'undefined') { window.addEventListener('offline', sync); window.addEventListener('online', sync); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', sync); if (typeof window !== 'undefined') { window.removeEventListener('offline', sync); window.removeEventListener('online', sync); } };
  }, []);
  useEffect(() => { if (!household.online) lifecycle.current.conceal(); else lifecycle.current.enter(); }, [household.online]);
  async function prepare(operation: 'attach' | 'detach') {
    await job(async ticket => {
      await readContext(ticket); const c = live.current.context; if (!c || !current(ticket)) return;
      const selected = c.order?.lines.find(row => row.lineKey === props.lineKey), linked = c.source.link;
      const common = { requestId: inventoryRequestId(), acquisitionId: c.acquisition.id, itemRevision: c.item.revision, revision: c.acquisition.revision };
      let input: SourceIntent;
      if (operation === 'attach') {
        if (!c.order || !selected || selected.linkState !== 'none' || linked?.status === 'active') throw new Error('这行订单或当前批次已有来源，请先核对现有关联。');
        input = { ...common, operation, orderId: c.order.order.id, lineKey: selected.lineKey, orderRevision: c.order.order.revision };
      } else { if (!linked || linked.status !== 'active') throw new Error('当前没有可以解除的来源。'); input = { ...common, operation, sourceLinkId: linked.id, sourceRevision: linked.revision }; }
      const raw = await guarded(csrf => request('/inventory/sources/preview', { method: 'POST', body: JSON.stringify(input) }, csrf), ticket);
      const preview = readSourcePreview(raw, input, c.item.id);
      if (current(ticket)) install({ preview: { input, preview } });
    });
  }
  async function confirm(intent: Intent, recover = false) {
    await job(async ticket => {
      install({ unknown: intent, preview: null });
      try {
        let result: unknown;
        if (recover) {
          try { result = await guarded(() => request(`/inventory/operations/${intent.input.requestId}`), ticket); }
          catch (e) {
            if (!(e instanceof ApiError && e.status === 404)) throw e;
            // A missing receipt is not proof of failure. Validate current ACL,
            // then retry only the original signed request and original key.
            await readContext(ticket);
          }
        }
        if (!result) result = await guarded(csrf => request('/inventory/sources/confirm', { method: 'POST', body: JSON.stringify({ requestId: intent.input.requestId, previewToken: intent.preview.previewToken, confirmSource: true }) }, csrf), ticket);
        readSourceReceipt(result, intent.preview.item.id, props.acquisitionId);
      } catch (e) {
        if (!current(ticket)) return;
        if (e instanceof ApiError && [400, 409].includes(e.status)) { install({ unknown: null }); setNotice('本次关联未获确认。请读取最新来源，再重新预览；已保存的批次保留。'); await readContext(ticket); }
        else if (!(e instanceof InventoryDiscarded) && !(e instanceof ApiError && [401, 403, 404, 410].includes(e.status))) setError('保存结果尚未确定，请核对原操作，不要新建相同批次。');
        throw e;
      }
      if (!current(ticket)) return;
      install({ unknown: null }); setNotice(intent.input.operation === 'attach' ? '订单来源已关联。批次已保存，实际到货后请另行登记收货。' : '订单来源已解除，原库存和财务记录保持。'); props.onSaved();
      // A failed refresh after a confirmed receipt must never resend confirm.
      await readContext(ticket);
    });
  }
  const locked = busy || !!unknown || !household.online;
  const back = <Button icon="arrow-left" disabled={busy || !!preview || !!unknown} onPress={props.onBack}>返回库存批次</Button>;
  if (!visible) return <EmptyState title={denied.current ? '来源暂时不可访问' : '正在核对本人订单来源'} description={error || '已保存的物品和批次会保留。'} action={<View style={styles.row}>{back}{!denied.current && <Button disabled={busy} onPress={() => active.current ? void job(async ticket => { await readContext(ticket); if (current(ticket)) setVisible(true); }) : enter()}>重新读取来源</Button>}</View>} />;
  return <View style={styles.page}>
    <PageHeader title="本人订单来源" description="只为这批物品留下私人来源，收到实物后再登记收货。" action={back} />
    {!!error && <Text accessibilityRole="alert">{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}{busy && <ActivityIndicator />}
    {unknown ? <SectionCard title="核对原来源操作"><View testID="inventory-source-pending" style={styles.page}><Text>原操作编号：{unknown.input.requestId}</Text><Text>保存结果不明。已保存的批次保持，请核对原结果。</Text><Button mode="contained" disabled={busy || !household.online} onPress={() => void confirm(unknown, true)}>核对原来源操作</Button></View></SectionCard> : preview ? <SectionCard title={preview.input.operation === 'attach' ? '预览关联订单来源' : '预览解除订单来源'}><View testID="inventory-source-preview" style={styles.page}>
      <Text>{preview.preview.item.title} · {preview.preview.acquisition.orderedQty} {preview.preview.item.unit}</Text>
      {preview.preview.line && <Text>{preview.preview.line.title}{preview.preview.line.variant ? ' · ' + preview.preview.line.variant : ''}</Text>}
      <Text>来源明细仅你可见。此操作不增加实物数量，不确认付款或退款。</Text>
      <View style={styles.row}><Button disabled={locked} onPress={() => install({ preview: null })}>取消来源预览</Button><Button mode="contained" disabled={locked} onPress={() => void confirm(preview)}>{preview.input.operation === 'attach' ? '确认关联订单来源' : '确认解除订单来源'}</Button></View>
    </View></SectionCard> : context && <>
      <SectionCard title="已保存的库存批次"><Text>{context.item.title} · {context.acquisition.orderedQty} {context.item.unit}</Text><Text>当前实物 {context.acquisition.onHandQty} {context.item.unit}；取消关联也会保留这个批次。</Text></SectionCard>
      <SectionCard title="当前订单来源"><View testID="inventory-source-current" style={styles.page}>
        {context.source.link ? <><Text>{context.source.link.state === 'current' ? '来源已关联' : context.source.link.state === 'detached' ? '来源已解除' : '原订单来源待核对'}</Text>
          {context.source.link.state === 'needs_review' && <Text>{context.source.link.reviewReasons.includes('source_missing') ? '原订单已删除或不可用。' : '原订单已变化，原商品对应关系需要重新核对。'} 实物记录保持，可以明确解除旧来源。</Text>}
          {context.source.link.order && <Text>{context.source.link.order.title} · {context.source.link.order.date}</Text>}{context.source.link.line && <Text>{context.source.link.line.title} · 数量原文：{context.source.link.line.quantityText || '未记录'}</Text>}
          {context.source.link.status === 'active' && <Button mode="outlined" disabled={locked} onPress={() => void prepare('detach')}>预览解除订单来源</Button>}
        </> : <Text>这个批次尚未关联订单来源。</Text>}
        <Text>订单内容只在本人页面显示；共享物品的家人不能查看这些来源明细。</Text>
      </View></SectionCard>
      {context.order && (!context.source.link || context.source.link.status === 'detached') && <SectionCard title="选中的订单商品"><View style={styles.page}>
        <Text>{context.order.lines.find(row => row.lineKey === props.lineKey)?.title || '原商品行不可用，请返回重新选择。'}</Text>
        <Text>请核对商品与当前批次。批次数量和单位以你手动填写的库存为准。</Text>
        <Button mode="contained" disabled={locked || context.order.lines.find(row => row.lineKey === props.lineKey)?.linkState !== 'none'} onPress={() => void prepare('attach')}>预览关联订单来源</Button>
      </View></SectionCard>}
      {!props.orderId && (!context.source.link || context.source.link.status === 'detached') && <Text>需要关联其他订单时，从「家庭资金 → 本人账本 → 订单详情 → 登记或查看订单库存」选择商品，再选择这个批次。</Text>}
      <Button disabled={locked} onPress={() => void job(readContext)}>刷新订单来源</Button>
    </>}
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, row: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 } });
