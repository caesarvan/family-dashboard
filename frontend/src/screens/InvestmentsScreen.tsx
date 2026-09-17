import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import { filterInvestments, formatInvestmentCents, investmentDraft, investmentIntent, newInvestmentRequestId, readInvestmentAck, readInvestmentList, readInvestmentReceipt, sumInvestments,
  type Investment, type InvestmentDraft, type InvestmentIntent, type InvestmentList, type InvestmentReceipt } from '../lib/investments';
import type { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import InvestmentImportPanel from './InvestmentImportPanel';

type Editor = { original: Investment | null; draft: InvestmentDraft; conflict: boolean; latest?: Investment | null };
type Removal = { original: Investment; conflict: boolean; latest?: Investment | null };
type Pending = { intent: InvestmentIntent; uncertain: boolean; notFound: boolean; revisionRejected: boolean; receipt?: InvestmentReceipt };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const foreground = () => typeof document === 'undefined' || !document.hidden;
const errorText = (e: unknown) => e instanceof Error ? e.message : '暂时无法完成，请重新核对。';
const timeText = (s: string) => s.replace('T', ' ').replace(/\.\d+/, '');
const actionName = { create: '新增', update: '修改', delete: '删除' } as const;
const fields: { key: keyof InvestmentDraft; label: string; max: number; multiline?: boolean }[] = [
  { key: 'name', label: '持仓名称', max: 120 }, { key: 'institution', label: '持仓机构', max: 120 },
  { key: 'assetType', label: '资产类型', max: 60 }, { key: 'currency', label: '持仓币种', max: 3 },
  { key: 'quantity', label: '持仓数量', max: 24 }, { key: 'cost', label: '持仓成本', max: 16 },
  { key: 'value', label: '持仓估值', max: 16 }, { key: 'asOf', label: '估值核对日期', max: 10 },
  { key: 'note', label: '持仓备注', max: 1000, multiline: true },
];
function HoldingAmounts({ row }: { row: Investment }) {
  const styles = useStyles();
  return <View style={styles.stackSmall}><Text>原币成本 · {formatInvestmentCents(row.costCents, row.currency)}</Text><Text variant="titleMedium">{row.valueCents === null ? '估值未知' : `已知估值 · ${formatInvestmentCents(row.valueCents, row.currency)}`}</Text><Text>核对日期 · {row.asOf}</Text></View>;
}
export default function InvestmentsScreen(props: ScreenProps) {
  const household = useHousehold();
  if (props.user.role !== 'member') return <EmptyState title="持仓仅本人查看" description="请用成员账户登录。电视无法读取个人持仓。" />;
  return <InvestmentWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function InvestmentWorkspace(props: ScreenProps & { identityKey: string }) {
  const styles = useStyles();
  const household = useHousehold(), theme = useTheme(), { height } = useWindowDimensions();
  const latest = useRef(household); latest.current = household;
  const alive = useRef(false), active = useRef(false), focused = useRef(false), denied = useRef(false), running = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), epoch = useRef(0);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  const [data, setData] = useState<InvestmentList | null>(null), [visible, setVisible] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [filters, setFilters] = useState({ name: '', institution: '', currency: '' });
  const [selected, setSelected] = useState<string | null>(null), selectedRef = useRef<string | null>(null);
  const [editor, setEditorState] = useState<Editor | null>(null), editorRef = useRef<Editor | null>(null);
  const [removal, setRemovalState] = useState<Removal | null>(null), removalRef = useRef<Removal | null>(null);
  const [pending, setPendingState] = useState<Pending | null>(null), pendingRef = useRef<Pending | null>(null);
  const [importing, setImporting] = useState<{ sourceName?: string } | null>(null);
  const current = () => alive.current && active.current && focused.current && appActive.current && !denied.current && latest.current.identityKey === props.identityKey && latest.current.online && online() && foreground();
  const select = (value: string | null) => { selectedRef.current = value; setSelected(value); };
  const setEditor = (value: Editor | null) => { editorRef.current = value; setEditorState(value); };
  const setRemoval = (value: Removal | null) => { removalRef.current = value; setRemovalState(value); };
  const setPending = (value: Pending | null) => { pendingRef.current = value; setPendingState(value); };
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate();
    if (running.current && pendingRef.current) setPending({ ...pendingRef.current, uncertain: true, revisionRejected: false });
    running.current = false; setVisible(false); setData(null); setBusy(false);
    if (clear) { select(null); setEditor(null); setRemoval(null); setPending(null); setImporting(null); setFilters({ name: '', institution: '', currency: '' }); setError(''); setNotice(''); }
  }
  function failure(caught: unknown) {
    if (!current()) return;
    if (caught instanceof PhotoReadDiscarded && caught.message !== 'identity') return;
    if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) {
      conceal(true); denied.current = true; setError('身份已变化，请重新打开持仓页面。'); void latest.current.refresh(); return;
    }
    setError(errorText(caught));
  }
  async function guarded<T>(load: () => Promise<T>, ticket = epoch.current): Promise<T> { return fence.current.read(load, () => current() && epoch.current === ticket); }
  async function fetchList(ticket = epoch.current): Promise<InvestmentList> { return readInvestmentList(await guarded(() => request<unknown>('/finance-hub/investments'), ticket)); }
  function install(next: InvestmentList) {
    setData(next);
    if (selectedRef.current && !next.investments.some(v => v.id === selectedRef.current)) { select(null); setNotice('该持仓当前已不存在，已显示最新列表。'); }
    const e = editorRef.current;
    if (e?.original) { const row = next.investments.find(v => v.id === e.original!.id) ?? null; if (row?.revision !== e.original.revision) setEditor({ ...e, conflict: true, latest: row }); }
    const r = removalRef.current;
    if (r) { const row = next.investments.find(v => v.id === r.original.id) ?? null; if (row?.revision !== r.original.revision) setRemoval({ ...r, conflict: true, latest: row }); }
  }
  async function receiptFor(intent: InvestmentIntent, ticket: number): Promise<InvestmentReceipt | null> {
    try { return readInvestmentReceipt(await guarded(() => request<unknown>('/finance-hub/investments/operations/' + intent.requestId), ticket), intent); }
    catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 404 && caught.code === 'investment_operation_not_found')) throw caught;
      // Failed GETs skip the fence's post-read check; preserve the original epoch.
      await guarded(async () => true, ticket); return null;
    }
  }
  async function recover(value: Pending, ticket: number): Promise<void> {
    const receipt = value.receipt || await receiptFor(value.intent, ticket);
    if (!current() || epoch.current !== ticket) return;
    if (receipt) setPending({ ...value, receipt, notFound: false });
    else setPending({ ...value, notFound: true });
    const next = await fetchList(ticket);
    if (!current() || epoch.current !== ticket) return;
    install(next); setVisible(true);
    if (!receipt) { setNotice('暂未找到本次操作回执。原请求可能仍在处理；当前列表不能证明之前没有提交。请继续核对或使用原请求重试。'); return; }
    setPending(null); setEditor(null); setRemoval(null); setError('');
    const exists = next.investments.some(v => v.id === receipt.recordId);
    if (receipt.kind !== 'delete' && exists) select(receipt.recordId);
    setNotice(`原${actionName[receipt.kind]}操作已于 ${timeText(receipt.completedAt)} 确认。下方已读取当前持仓；后续的修改或删除不会被历史回执恢复。`);
  }
  async function reload() {
    if (!current() || running.current) return;
    running.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try {
      if (pendingRef.current) await recover(pendingRef.current, ticket);
      else { const next = await fetchList(ticket); if (current() && epoch.current === ticket) { install(next); setVisible(true); } }
    } catch (caught) { if (epoch.current === ticket) { failure(caught); setVisible(false); setData(null); } }
    finally { if (epoch.current === ticket) { running.current = false; if (alive.current) setBusy(false); } }
  }
  function enter() { if (!alive.current || active.current || !focused.current || denied.current || !appActive.current || !online() || !foreground() || !latest.current.online) return; active.current = true; void reload(); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(true); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => foreground() ? enter() : conceal();
    const disconnect = () => { conceal(); setError('网络已断开，私有持仓暂时隐藏。'); };
    const connect = () => enter();
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', disconnect); window.addEventListener('online', connect); }
    const subscription = AppState.addEventListener('change', state => { appActive.current = state === 'active'; if (appActive.current) enter(); else conceal(); });
    const timer = setInterval(() => { if (current() && !running.current) void guarded(async () => true).catch(failure); }, 15000);
    return () => { if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', disconnect); window.removeEventListener('online', connect); } subscription.remove(); clearInterval(timer); };
  }, [props.identityKey]);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  async function send(value: Pending) {
    if (!current() || running.current) return;
    running.current = true; setBusy(true); setError(''); setNotice(''); const ticket = epoch.current;
    setPending({ ...value, notFound: false, revisionRejected: false });
    try {
      const result = await guarded(() => latest.current.mutate<unknown>(value.intent.path, value.intent.method, value.intent.payload), ticket);
      readInvestmentAck(result, value.intent);
      await recover({ ...value, uncertain: false, notFound: false, revisionRejected: false }, ticket);
    } catch (caught) {
      if (!current() || ticket !== epoch.current) return;
      const rejected = !value.uncertain && caught instanceof ApiError && caught.status === 409 && caught.code === 'revision_conflict';
      const next = { ...value, uncertain: !rejected, notFound: false, revisionRejected: rejected };
      setPending(next); failure(caught);
      if (current()) {
        try { await recover(next, ticket); }
        catch (followup) { if (ticket === epoch.current) { failure(followup); setVisible(false); setData(null); } }
      }
    } finally { if (epoch.current === ticket) { running.current = false; if (alive.current) setBusy(false); } }
  }
  function saveEditor() {
    const e = editorRef.current;
    if (!current() || running.current || pendingRef.current || !e || e.conflict) return;
    try {
      const intent = investmentIntent(e.original ? 'update' : 'create', e.draft, newInvestmentRequestId(), e.original || undefined);
      void send({ intent, uncertain: false, notFound: false, revisionRejected: false });
    } catch (caught) { failure(caught); }
  }
  function deleteRecord() {
    const r = removalRef.current;
    if (!current() || running.current || pendingRef.current || !r || r.conflict) return;
    try { void send({ intent: investmentIntent('delete', null, newInvestmentRequestId(), r.original), uncertain: false, notFound: false, revisionRejected: false }); }
    catch (caught) { failure(caught); }
  }
  async function refreshConflict() {
    if (!current() || running.current || pendingRef.current && !pendingRef.current.revisionRejected) return;
    running.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try {
      const p = pendingRef.current;
      if (p) { const receipt = await receiptFor(p.intent, ticket); if (receipt) { await recover({ ...p, receipt }, ticket); return; } }
      const next = await fetchList(ticket);
      if (!current() || epoch.current !== ticket) return;
      install(next); setVisible(true);
      if (p?.revisionRejected && !p.uncertain) {
        const currentRow = next.investments.find(v => v.id === p.intent.recordId) ?? null;
        const priorRevision = p.intent.payload.revision;
        if (currentRow && currentRow.revision === priorRevision) { setNotice('当前版本尚未变化，请继续核对原操作。'); return; }
        setPending(null);
      }
      const e = editorRef.current; if (e?.original) setEditor({ ...e, conflict: true, latest: next.investments.find(v => v.id === e.original!.id) ?? null });
      const r = removalRef.current; if (r) setRemoval({ ...r, conflict: true, latest: next.investments.find(v => v.id === r.original.id) ?? null });
      setNotice('已读取最新记录，原输入仍保留。请核对差异后明确选择最新版本，再提交。');
    } catch (caught) { if (ticket === epoch.current) failure(caught); }
    finally { if (ticket === epoch.current) { running.current = false; if (alive.current) setBusy(false); } }
  }
  const locked = busy || !!pending;
  const privateVisible = visible && current();
  const rows = data ? filterInvestments(data.investments, filters) : [];
  const totals = sumInvestments(rows), detail = data?.investments.find(v => v.id === selected);
  const dialogStyle = { backgroundColor: theme.colors.surfaceVariant, borderRadius: 24, width: '92%' as const, maxWidth: 680, maxHeight: height * .88, alignSelf: 'center' as const, marginHorizontal: 0 };
  function pendingControls() { return pending ? <View testID="investment-operation-pending" style={styles.stackSmall}>
    <Text variant="titleMedium">{pending.receipt ? '原操作已确认，当前列表待刷新' : '核对本次操作'}</Text>
    <Text>{pending.receipt ? '回执是历史结果，继续读取当前持仓。' : '操作结果尚未确认；重复核对只读取回执，不会新增持仓。'}</Text>
    {!!pending.notFound && <Text>暂未找到回执，原请求可能仍在处理；不能据此认定未提交。</Text>}
    <Button disabled={busy} onPress={() => void reload()}>核对操作结果</Button>
    {!pending.receipt && pending.notFound && <Button disabled={busy} onPress={() => { if (pendingRef.current) void send(pendingRef.current); }}>使用原请求重试</Button>}
    {pending.revisionRejected && <Button disabled={busy} onPress={() => void refreshConflict()}>读取最新版本</Button>}
  </View> : null; }
  function comparison(value: Investment | null | undefined) { return value === undefined ? <Text>请先读取最新版本。</Text> : value === null ? <Text>当前持仓已不存在。原输入保留，但不能覆盖或自动重建记录。</Text> : <View style={styles.white}><Text variant="titleMedium">最新记录 · {value.name}</Text><Text>{value.institution} · {value.assetType}</Text><HoldingAmounts row={value} /><Text>数量 · {value.quantity ?? '未记录'}</Text><Text>更新 · {timeText(value.updatedAt)}</Text><Text>{value.note || '无备注'}</Text></View>; }
  return <View style={styles.page}>
    {!privateVisible ? <SectionCard title="我的持仓"><Text>{denied.current ? '身份已变化，请重新进入此页面。' : !online() || !household.online ? '连接恢复后将重新核对身份，私有内容暂不显示。' : '正在核对身份与持仓…'}</Text><Button disabled={busy || denied.current} onPress={() => current() ? void reload() : enter()}>重新核对身份</Button>{busy && <ActivityIndicator />}</SectionCard> : <>
      <PageHeader title={detail ? detail.name : '我的持仓'} description="仅本人可见。记录本地持仓，不执行购买、赎回或卖出。" action={<View style={styles.controls}>
        <Button icon="refresh" accessibilityLabel="刷新持仓" disabled={busy} onPress={() => void reload()}>刷新持仓</Button>
        {!detail && <><Button icon="file-upload-outline" accessibilityLabel="导入持仓" disabled={locked} onPress={() => setImporting({})}>导入持仓</Button><Button mode="contained" icon="plus" accessibilityLabel="新增持仓" disabled={locked || (data?.investments.length ?? 0) >= 300} onPress={() => { setError(''); setEditor({ original: null, draft: investmentDraft(), conflict: false }); }}>新增持仓</Button></>}
      </View>} />
      {!!error && !editor && !removal && <SectionCard title="需要核对"><Text accessibilityLiveRegion="polite">{error}</Text></SectionCard>}
      {!!notice && <Text accessibilityLiveRegion="polite" style={styles.muted}>{notice}</Text>}
      {!editor && !removal && pendingControls()}
      {detail ? <>
        <View style={styles.controls}><Button disabled={locked} onPress={() => select(null)}>返回持仓列表</Button><Button mode="contained" disabled={locked} onPress={() => { setError(''); setEditor({ original: detail, draft: investmentDraft(detail), conflict: false }); }}>编辑这条持仓</Button><Button disabled={locked} onPress={() => { setError(''); setRemoval({ original: detail, conflict: false }); }}>删除这条持仓</Button></View>
        <SectionCard title="持仓详情"><View testID={`investment-detail-${detail.id}`} style={styles.stack}><Text>{detail.institution} · {detail.assetType}</Text><HoldingAmounts row={detail} /><Text>数量 · {detail.quantity ?? '未记录'}</Text><Text>{detail.valueCents === null ? '估值未知，不纳入已知部分浮盈亏。' : `已知部分浮盈亏 · ${formatInvestmentCents(BigInt(detail.valueCents) - BigInt(detail.costCents), detail.currency)}`}</Text><Divider /><Text>估值提供方式 · {detail.valuationSource === 'file_import' ? '本人文件导入' : '本人手动核对'}</Text><Text>最近更新 · {timeText(detail.updatedAt)}</Text><Text>来源 · {detail.source?.sourceName || '手动记录，未关联文件来源'}</Text>{!!detail.source && <Text>来源持仓键 · {detail.source.holdingKey}</Text>}<Text>{detail.note || '未填写备注'}</Text></View></SectionCard>
      </> : <>
        <SectionCard title="查找持仓"><View style={styles.controls}><TextInput mode="outlined" label="搜索持仓名称" accessibilityLabel="搜索持仓名称" value={filters.name} maxLength={120} style={styles.filter} onChangeText={name => setFilters(v => ({ ...v, name }))} /><TextInput mode="outlined" label="筛选持仓机构" accessibilityLabel="筛选持仓机构" value={filters.institution} maxLength={120} style={styles.filter} onChangeText={institution => setFilters(v => ({ ...v, institution }))} /><TextInput mode="outlined" label="筛选持仓币种" accessibilityLabel="筛选持仓币种" value={filters.currency} maxLength={3} autoCapitalize="characters" style={styles.filter} onChangeText={currency => setFilters(v => ({ ...v, currency }))} /></View><Text style={styles.muted}>显示 {rows.length} / {data?.investments.length ?? 0} 项 · 筛选在本人完整列表中进行，最多 300 项。</Text>{Object.values(filters).some(Boolean) && <Button onPress={() => setFilters({ name: '', institution: '', currency: '' })}>清除筛选</Button>}</SectionCard>
        {!!totals.length && <SectionCard title="当前筛选汇总"><View style={styles.stack}>{totals.map(total => <View key={total.currency} testID={`investment-total-${total.currency}`} style={styles.white}><Text variant="titleMedium">{total.currency} · {total.count} 项</Text><Text>原币总成本 · {formatInvestmentCents(total.costCents, total.currency)}</Text><Text>已知估值 · {total.knownCount ? formatInvestmentCents(total.knownValueCents, total.currency) : '未知'}</Text><Text>已估值部分浮盈亏 · {total.knownCount ? formatInvestmentCents(total.knownGainCents, total.currency) : '未知'}</Text><Text style={styles.muted}>已估值 {total.knownCount} 项 · 未估值 {total.unknownCount} 项</Text></View>)}<Text style={styles.muted}>币种分别计算，不换汇。浮盈亏只比较已估值持仓的成本与估值，不代表完整资产、账户净值或历史收益。</Text></View></SectionCard>}
        <SectionCard title="本人持仓"><View style={styles.stack}>{rows.length ? rows.map(row => <View key={row.id} testID={`investment-${row.id}`} style={styles.white}><Text variant="titleMedium" style={styles.wrap}>{row.name}</Text><Text style={styles.muted}>{row.institution} · {row.assetType}</Text><HoldingAmounts row={row} /><Button accessibilityLabel={`查看持仓 ${row.name}`} disabled={locked} onPress={() => select(row.id)}>查看详情</Button></View>) : <EmptyState title={data?.investments.length ? '没有符合筛选的持仓' : '还没有持仓记录'} description={data?.investments.length ? '调整名称、机构或币种，现有记录未改变。' : '可手动添加一条，或导入整理好的本人持仓表。'} />}</View></SectionCard>
        {!!data?.sources.length && <SectionCard title="已关联文件来源"><View style={styles.stack}>{data.sources.map(source => <View key={source.sourceName} style={styles.white}><Text variant="titleMedium">{source.sourceName}</Text><Text>当前持仓 {source.holdingCount} 项 · 已删除关联 {source.deletedCount} 项</Text><Text style={styles.muted}>更新 · {timeText(source.updatedAt)}</Text><Button disabled={locked} accessibilityLabel={`更新来源 ${source.sourceName}`} onPress={() => setImporting({ sourceName: source.sourceName })}>更新此来源</Button></View>)}</View></SectionCard>}
      </>}
    </>}
    <Portal>
      <Dialog visible={privateVisible && !!editor} onDismiss={() => { if (!locked) setEditor(null); }} style={dialogStyle}>
        <Dialog.Title>{editor?.original ? '编辑持仓' : '新增持仓'}</Dialog.Title>
        <Dialog.ScrollArea style={styles.scrollArea}><ScrollView contentContainerStyle={styles.dialogBody} keyboardShouldPersistTaps="handled">
          {privateVisible && editor && <><Text>只保存本人本地记录，不向银行或券商下单。成本与估值均为整项持仓的原币总额。</Text>{fields.map(field => <View key={field.key}><TextInput mode="outlined" label={field.label} accessibilityLabel={field.label} value={editor.draft[field.key]} maxLength={field.max} multiline={field.multiline} disabled={locked} outlineStyle={styles.inputOutline} onChangeText={value => { const latestEditor = editorRef.current; if (latestEditor) setEditor({ ...latestEditor, draft: { ...latestEditor.draft, [field.key]: value } }); }} />{field.key === 'value' && <Text style={styles.muted}>留空为未知，填写 0 为明确零估值。</Text>}{field.key === 'quantity' && <Text style={styles.muted}>可留空；最多 15 位整数、8 位小数，不用数量自动推算估值。</Text>}</View>)}
          {!!editor.original?.source && <Text>来源关联保留：{editor.original.source.sourceName} / {editor.original.source.holdingKey}。本次值将标为本人手动核对。</Text>}
          {!!error && <Text accessibilityLiveRegion="polite" style={{ color: theme.colors.error }}>{error}</Text>}{pendingControls()}
          {editor.conflict && <View style={styles.stackSmall}><Text variant="titleMedium">记录已变化，原输入已保留</Text>{comparison(editor.latest)}{!pending && <Button disabled={busy} onPress={() => void refreshConflict()}>读取最新版本</Button>}{!pending && !!editor.latest && <Button disabled={busy} onPress={() => { const e = editorRef.current; if (e?.latest && current()) { setEditor({ original: e.latest, draft: e.draft, conflict: false }); setError(''); } }}>保留草稿并使用最新版本</Button>}</View>}</>}
        </ScrollView></Dialog.ScrollArea>
        <Dialog.Actions style={styles.controls}><Button disabled={locked} onPress={() => setEditor(null)}>取消</Button><Button mode="contained" disabled={locked || !!editor?.conflict} onPress={saveEditor}>保存当前记录</Button></Dialog.Actions>
      </Dialog>
      <Dialog visible={privateVisible && !!removal} onDismiss={() => { if (!locked) setRemoval(null); }} style={dialogStyle}>
        <Dialog.Title>删除本地持仓记录？</Dialog.Title><Dialog.ScrollArea style={styles.scrollArea}><ScrollView contentContainerStyle={styles.dialogBody}>
          {privateVisible && removal && <><Text variant="titleMedium">{removal.original.name}</Text><HoldingAmounts row={removal.original} /><Text>只删除本人看板中的这条持仓，不卖出、赎回或修改银行／券商资产。文件来源的删除关联继续保留，旧文件不会自动重建它。</Text>{!!error && <Text accessibilityLiveRegion="polite" style={{ color: theme.colors.error }}>{error}</Text>}{pendingControls()}{removal.conflict && <View style={styles.stackSmall}><Text>这条持仓已变化，请重新核对。</Text>{comparison(removal.latest)}{!pending && <Button disabled={busy} onPress={() => void refreshConflict()}>读取最新版本</Button>}{!pending && !!removal.latest && <Button disabled={busy} onPress={() => { const r = removalRef.current; if (r?.latest && current()) { setRemoval({ original: r.latest, conflict: false }); setError(''); } }}>使用最新版本重新确认删除</Button>}</View>}</>}
        </ScrollView></Dialog.ScrollArea><Dialog.Actions style={styles.controls}><Button disabled={locked} onPress={() => setRemoval(null)}>保留记录</Button><Button mode="contained" disabled={locked || !!removal?.conflict} onPress={deleteRecord}>确认删除本地记录</Button></Dialog.Actions>
      </Dialog>
      {!!importing && <InvestmentImportPanel user={props.user} identityKey={props.identityKey} initialSourceName={importing.sourceName} onDismiss={() => setImporting(null)} onImported={() => { setImporting(null); setNotice('已确认原导入结果，正在读取当前持仓。'); void reload(); }} />}
    </Portal>
  </View>;
}
function useStyles() {
  const theme = useTheme();
  return StyleSheet.create({
    page: { gap: 20, minWidth: 0 }, stack: { gap: 16 }, stackSmall: { gap: 8 },
    controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
    filter: { flexGrow: 1, flexShrink: 1, flexBasis: 200, minWidth: 0, backgroundColor: theme.colors.surface, marginBottom: 12 },
    white: { backgroundColor: theme.colors.surface, borderRadius: 16, padding: 16, gap: 10, minWidth: 0 },
    muted: { color: theme.colors.onSurfaceVariant, fontSize: 13, lineHeight: 20 }, wrap: { flexShrink: 1 },
    scrollArea: { paddingHorizontal: 0, flexShrink: 1 }, dialogBody: { paddingHorizontal: 24, paddingVertical: 18, gap: 16 }, inputOutline: { borderRadius: 8 },
  });
}
