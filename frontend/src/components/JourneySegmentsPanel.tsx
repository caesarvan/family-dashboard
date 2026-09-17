import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';
import { applyTimeChoice, checkedSegmentWrite, createSegmentIntent, detailFingerprint, editSegmentDraft, failedSegmentIntent, newDestination, newSegment,
  previewPayload, readCapabilities, readJourneyDetail, readSegmentOperation, readSegmentPreview, readSegmentReceipt, readTimeIssue,
  rebaseSegmentDraft, segmentRequest, SegmentDiscarded, SegmentError, SegmentFence, SegmentRejected, upgradeToV2,
  type JourneyPlanV2, type Segment, type SegmentDraft, type SegmentSession } from '../lib/journeySegments';
import { bookingNames, SegmentFields, SegmentInput, segmentKindNames, segmentText } from './JourneySegmentFields';

type Props = { journeyId: string; onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Detail = ReturnType<typeof readJourneyDetail>;
type Preview = ReturnType<typeof readSegmentPreview>;
type Intent = ReturnType<typeof createSegmentIntent>;
type Receipt = ReturnType<typeof readSegmentReceipt>;
type Capabilities = ReturnType<typeof readCapabilities>;
type TimeIssue = ReturnType<typeof readTimeIssue>;
type Choices = Record<string, Record<string, 'current' | 'plan'>>;
type Model = { source: Detail | null; draft: SegmentDraft | null; capabilities: Capabilities | null; dirty: boolean;
  preview: Preview | null; choices: Choices; unknown: Intent | null; receipt: Receipt | null; review: Detail | null; blocked: boolean; missing: boolean };
const empty = (): Model => ({ source: null, draft: null, capabilities: null, dirty: false, preview: null, choices: {}, unknown: null, receipt: null, review: null, blocked: false, missing: false });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const isPending = (m: Model) => m.dirty || !!m.unknown;
const version = detailFingerprint;
const PAGE = 5;
function Paged({ label, page, count, onChange, disabled = false }: { label: string; page: number; count: number; onChange: (page: number) => void; disabled?: boolean }) {
  const pages = Math.ceil(count / PAGE);
  if (pages <= 1) return null;
  return <View style={styles.actions}><Button contentStyle={styles.touch} disabled={disabled || page === 0} accessibilityLabel={`${label}上一页`} onPress={() => onChange(page - 1)}>上一页</Button>
    <Text>{page + 1} / {pages}</Text><Button contentStyle={styles.touch} disabled={disabled || page + 1 >= pages} accessibilityLabel={`${label}下一页`} onPress={() => onChange(page + 1)}>下一页</Button></View>;
}
const groupNames: Record<string, string> = { timing: '日期、时间与时区', title: '标题', location: '地点', note: '备注' };
const valueNames: Record<string, string> = { start: '开始', end: '结束', title: '标题', location: '地点', note: '备注', allDay: '全天',
  startDate: '开始日期', endDateExclusive: '结束日期（不含当天）', travelTiming: '当地时间', local: '当地时刻', timeZone: '时区',
  startLocal: '开始当地时刻', endLocal: '结束当地时刻', startTimeZone: '开始时区', endTimeZone: '结束时区',
  startOffsetMinutes: '开始 UTC 偏移分钟', endOffsetMinutes: '结束 UTC 偏移分钟', offsetMinutes: 'UTC 偏移分钟', instant: 'UTC 时刻',
  departure: '起飞', arrival: '抵达', airport: '机场', city: '城市', flightNumber: '航班号', propertyName: '住宿名称', address: '地址',
  checkInTime: '入住时间', checkOutTime: '退房时间', nights: '晚数', bookingState: '预订标记', datePolicy: '日期规则', kind: '类型' };
function valueText(value: unknown, depth = 0): string {
  if (value === null || value === undefined || value === '') return '未填写';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return ({ ...bookingNames, ...segmentKindNames, fixed: '固定日期', shift_with_trip: '可选择联动' } as Record<string, string>)[value] || value;
  if (typeof value === 'number') return String(value);
  if (typeof value === 'object' && depth < 4) return Object.entries(value).filter(([key]) => key in valueNames).map(([key, item]) => `${valueNames[key]}：${valueText(item, depth + 1)}`).join('\n') || '无额外内容';
  return '请核对当前内容';
}
export default function JourneySegmentsPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户编辑行程" />;
  if (!/^[a-f0-9]{24}$/.test(props.journeyId)) return <EmptyState title="旅行编号无法核对" action={<Button onPress={props.onBack}>返回旅行</Button>} />;
  return <Workspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  const [reference, setReference] = useState(''), [zones, setZones] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<'cities' | 'segments'>('segments'), [selected, setSelected] = useState(''), [city, setCity] = useState('');
  const [pages, setPages] = useState({ cities: 0, segments: 0, saved: 0, preview: 0, previewCities: 0, comparisons: 0, conflicts: 0, warnings: 0, upgrade: 0, links: 0 });
  const [issue, setIssue] = useState<TimeIssue | null>(null), [leaving, setLeaving] = useState(false), [removing, setRemoving] = useState<{ kind: 'cities' | 'segments'; key: string } | null>(null);
  const alive = useRef(false), active = useRef(false), focused = useRef(false), denied = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const flight = useRef<AbortController | null>(null), fence = useRef(new SegmentFence(props.identityKey));
  const previewExpires = useRef(0);
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && !denied.current && ticket === epoch.current
    && latest.current.household.identityKey === props.identityKey && latest.current.household.online && online() && (typeof document === 'undefined' || !document.hidden);
  function notify() { latest.current.props.onPendingChange?.(working.current || isPending(live.current)); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; flight.current?.abort(); flight.current = null; fence.current.invalidate();
    setVisible(false); setBusy(false); working.current = false; setError(''); setMessage(''); setIssue(null); setLeaving(false); setRemoving(null);
    if (clear) { live.current = empty(); setReference(''); setZones({}); setSelected(''); setCity(''); }
    else live.current = { ...live.current, preview: null, choices: {} };
    setModel(live.current); notify();
  }
  function failed(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof SegmentDiscarded) {
      if (e.message === 'identity') { denied.current = true; conceal(true); setError('登录身份已变化，请重新打开旅行。'); void latest.current.household.refresh(); }
      return;
    }
    if (e instanceof SegmentError && [401, 403].includes(e.status)) { conceal(); setError('身份或权限需要重新核对，行程已隐藏。'); void latest.current.household.refresh(); return; }
    setError(e instanceof Error ? e.message : '暂时无法核对行程。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (e) { failed(e, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, operation: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await segmentRequest('/me', signal) as SegmentSession, operation, () => current(ticket));
  const read = <T,>(ticket: number, signal: AbortSignal, operation: () => Promise<T>) => checkedSegmentWrite(job => guard(ticket, signal, job), operation);
  async function load(ticket: number, signal: AbortSignal) {
    const caps = readCapabilities(await read(ticket, signal, () => segmentRequest('/journeys/templates', signal)));
    let detail: Detail;
    try { detail = await read(ticket, signal, async () => readJourneyDetail(await segmentRequest('/journeys/' + props.journeyId, signal), props.journeyId)); }
    catch (e) {
      if (e instanceof SegmentRejected && e.status === 404 && current(ticket)) {
        install({ capabilities: caps, source: null, review: null, preview: null, choices: {}, blocked: true, missing: true }); setVisible(true);
        setMessage('旅行当前不可读取。旧草稿与历史回执不会重新创建旅行。'); return;
      } throw e;
    }
    if (!current(ticket)) return;
    const old = live.current;
    if (old.dirty && old.source && (old.blocked || version(old.source) !== version(detail))) {
      install({ capabilities: caps, review: detail, blocked: true, missing: false, preview: null, choices: {} });
    } else if (old.dirty || old.unknown) install({ capabilities: caps, source: detail, missing: false, preview: null, choices: {} });
    else install({ capabilities: caps, source: detail, draft: editSegmentDraft(detail), missing: false, blocked: false, review: null, preview: null, choices: {} });
    setVisible(true);
  }
  function enter() {
    if (!alive.current || active.current || !focused.current || !foreground.current || denied.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(load);
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; flight.current?.abort(); fence.current.invalidate(); live.current = empty(); latest.current.props.onPendingChange?.(false); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, offline = () => conceal(), connected = () => enter(), hide = () => conceal();
    const show = (e: PageTransitionEvent) => { if (e.persisted) { conceal(); enter(); } };
    const unload = (e: BeforeUnloadEvent) => { if (working.current || isPending(live.current)) { e.preventDefault(); e.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  const locked = busy || !visible || !!model.unknown || !!model.receipt || model.blocked || model.missing || !model.capabilities?.canWriteV2;
  function change(draft: SegmentDraft) {
    if (!current() || working.current || live.current.unknown || live.current.receipt || live.current.blocked || live.current.missing || !live.current.capabilities?.canWriteV2) return;
    install({ draft, dirty: true, preview: null, choices: {} }); setIssue(null); setError(''); setMessage('');
  }
  function changePlan(patch: Partial<JourneyPlanV2>) {
    const d = live.current.draft; if (!d || d.plan.schemaVersion !== 2) return;
    change({ ...d, plan: { ...d.plan, ...patch } });
  }
  function upgrading() {
    const { draft, capabilities } = live.current; if (!draft || !capabilities || locked) return;
    try { change(upgradeToV2(draft, reference, zones, capabilities)); setMessage('已在本页准备升级，尚未保存。原日期段保持原含义；请编辑并预览后明确确认。'); }
    catch (e) { setError(e instanceof Error ? e.message : '请填写参考时区和每座城市的时区。'); }
  }
  function add(kind: 'city' | 'flight' | 'stay' | 'activity') {
    const plan = live.current.draft?.plan; if (locked || !plan || plan.schemaVersion !== 2) return;
    try {
      if (kind === 'city') { if (plan.destinations.length >= 20) return; const row = newDestination(); changePlan({ destinations: [...plan.destinations, row] }); setCity(row.key); setPages(p => ({ ...p, cities: Math.floor(plan.destinations.length / PAGE) })); }
      else { if (plan.segments.length >= 100) return; const row = newSegment(kind); changePlan({ segments: [...plan.segments, row] }); setSelected(row.key); setPages(p => ({ ...p, segments: Math.floor(plan.segments.length / PAGE), links: 0 })); }
    } catch (e) { setError(e instanceof Error ? e.message : '暂时无法添加行程，请保留已有草稿。'); }
  }
  async function preview() {
    const { draft, capabilities, choices } = live.current; if (!draft || !capabilities || locked) return;
    let payload: ReturnType<typeof previewPayload>;
    try { payload = previewPayload(draft, capabilities, latest.current.household.state?.people.map(person => person.id) ?? [], choices); }
    catch (e) { setError(e instanceof Error ? e.message : '请核对行程字段。'); return; }
    await job(async (ticket, signal) => {
      install({ preview: null }); setIssue(null);
      try {
        const detail = await read(ticket, signal, async () => readJourneyDetail(await segmentRequest('/journeys/' + props.journeyId, signal), props.journeyId));
        if (!current(ticket)) return;
        if (detailFingerprint(detail) !== draft.observed) {
          install({ review: detail, blocked: true, choices: {} }); setMessage('旅行或关联事项已更新，输入仍保留。请先核对最新记录。'); return;
        }
        const started = performance.now();
        const result = await guard(ticket, signal, async csrf => readSegmentPreview(await segmentRequest('/journeys/preview', signal, { method: 'POST', payload, csrf })));
        if (current(ticket)) { previewExpires.current = started + result.expiresIn * 1000; install({ preview: result }); setPages(p => ({ ...p, preview: 0, previewCities: 0, comparisons: 0, conflicts: 0, warnings: 0 })); setSelected(''); setCity(''); }
      } catch (e) {
        if (current(ticket) && e instanceof SegmentError) {
          if (e.status === 409) install({ blocked: true, review: null, choices: {} });
          if (e.status === 400) { try { const issue = readTimeIssue(e.body, draft); setIssue(issue);
            const match = /^segments\[(\d+)\]/.exec(issue.field), row = match ? draft.plan.segments[Number(match[1])] : null;
            if (row) { setTab('segments'); setSelected(row.key); setPages(p => ({ ...p, segments: Math.floor(Number(match![1]) / PAGE) })); }
          } catch { /* Other validation errors have no structured time choices. */ } }
        } throw e;
      }
    });
  }
  async function accepted(receipt: Receipt, ticket: number, signal: AbortSignal) {
    if (!current(ticket)) return;
    install({ source: null, draft: null, preview: null, dirty: false, unknown: null, receipt, choices: {}, review: null, blocked: false, missing: false });
    setPages(p => ({ ...p, cities: 0, segments: 0, saved: 0, links: 0 }));
    setSelected(''); setCity(''); setIssue(null); setMessage('保存已确认。回执只代表这次历史操作，当前行程会重新读取。');
    await load(ticket, signal); if (current(ticket)) void latest.current.household.refresh();
  }
  async function confirm(retry = false) {
    const m = live.current; if (!current() || working.current || !retry && (locked || !m.preview?.canApply || !m.draft)) return;
    if (!retry && performance.now() >= previewExpires.current) { install({ preview: null, choices: {} }); setError('这份预览已过期。草稿仍保留，请重新预览后确认。'); return; }
    let intent: Intent;
    try { intent = retry ? m.unknown! : createSegmentIntent(m.preview!, m.draft!); if (!intent) return; }
    catch (e) { setError(e instanceof Error ? e.message : '请重新预览。'); return; }
    await job(async (ticket, signal) => {
      try {
        const receipt = await checkedSegmentWrite(operation => guard(ticket, signal, operation), async csrf => {
          install({ unknown: { ...intent, uncertain: true } });
          return readSegmentReceipt(await segmentRequest('/journeys/apply', signal, { method: 'POST', payload: intent.body, csrf }), intent);
        });
        await accepted(receipt, ticket, signal);
      } catch (e) {
        if (!current(ticket)) return;
        // Only an actual attempted write can become uncertain. A failed /me
        // before the callback leaves the editable draft and token untouched.
        if (live.current.unknown) {
          const retained = failedSegmentIntent(intent, e); install({ unknown: retained });
          if (!retained) { install({ preview: null, choices: {}, blocked: true, review: null }); setMessage('本次请求未保存，草稿保留。请读取最新内容，再重新预览。'); }
          else setMessage('保存结果尚未核实。原凭据与操作编号仍保留，请核对或明确重试原请求。');
        } throw e;
      }
    });
  }
  async function recover() {
    const intent = live.current.unknown; if (!intent) return;
    await job(async (ticket, signal) => {
      try { const receipt = await read(ticket, signal, async () => readSegmentOperation(await segmentRequest('/journeys/operations/' + intent.body.idempotencyKey, signal), intent)); await accepted(receipt, ticket, signal); }
      catch (e) { if (current(ticket) && e instanceof SegmentRejected && e.status === 404 && e.body && typeof e.body === 'object' && 'code' in e.body && e.body.code === 'operation_not_found') { setMessage('暂未查到原操作。它仍可能已保存或正在处理，不能据此创建新操作；可再次核对或明确按原请求重试。'); return; } throw e; }
    });
  }
  function chooseLatest(keep: boolean) {
    const { review, draft } = live.current; if (!current() || working.current || !review || !draft || live.current.unknown) return;
    try { const next = keep && draft.plan.schemaVersion === 2 ? rebaseSegmentDraft(draft, review) : editSegmentDraft(review);
      install({ source: review, draft: next, dirty: keep, review: null, blocked: false, missing: false, preview: null, choices: {} });
      if (!keep) { setReference(''); setZones({}); }
      else if (draft.plan.schemaVersion !== 2) setZones(previous => Object.fromEntries(next.plan.destinations.filter(row => previous[row.key] !== undefined).map(row => [row.key, previous[row.key]])));
      setPages(p => ({ ...p, cities: 0, segments: 0, upgrade: 0, links: 0 }));
      setSelected(''); setCity(''); setIssue(null); setError(''); setMessage(keep ? '已保留本页输入，其他金额、成员与清单采用最新记录。请重新核对并预览。' : '已采用最新记录，没有再次保存。'); }
    catch (e) { setError(e instanceof Error ? e.message : '无法合并，请采用最新记录重新编辑。'); }
  }
  function remove() {
    const d = live.current.draft; if (!removing || !d || d.plan.schemaVersion !== 2 || locked) return;
    if (removing.kind === 'cities' && d.plan.destinations.length <= 1) return;
    if (removing.kind === 'segments') { changePlan({ segments: d.plan.segments.filter(row => row.key !== removing.key) }); setSelected(''); }
    else { changePlan({ destinations: d.plan.destinations.filter(row => row.key !== removing.key), segments: d.plan.segments.map(row => {
      if (row.destinationKey !== removing.key) return row; const { destinationKey: _key, ...remaining } = row; return remaining;
    }) }); setCity(''); }
    setRemoving(null); setPages(p => ({ ...p, cities: 0, segments: 0, links: 0 }));
  }
  function back() { if (working.current || live.current.unknown) return; if (isPending(live.current)) setLeaving(true); else exit(); }
  function exit() { if (working.current || live.current.unknown) return; conceal(true); latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
  const action = (label: string, onPress: () => void, disabled = false, mode: 'text' | 'outlined' | 'contained' = 'text') =>
    <Button accessibilityLabel={label} contentStyle={styles.touch} style={styles.button} disabled={disabled} mode={mode} onPress={onPress}>{label}</Button>;
  const page = (name: keyof typeof pages, count: number) => <Paged label={name === 'cities' ? '城市' : name === 'segments' ? '分段' : name === 'saved' ? '当前分段' : name === 'preview' ? '预览分段' : name === 'previewCities' ? '预览城市' : name === 'comparisons' ? '保留与采用内容' : name === 'conflicts' ? '日程冲突' : name === 'upgrade' ? '升级城市' : name === 'links' ? '关联城市' : '提醒'} page={pages[name]} count={count} disabled={busy} onChange={value => setPages(p => ({ ...p, [name]: value }))} />;
  const dialogs = <Portal>
    <Dialog visible={leaving && visible && !model.unknown} onDismiss={() => setLeaving(false)} dismissable={!busy}><Dialog.Title>放弃本页未保存修改？</Dialog.Title><Dialog.Content><Text>已保存的旅行保持，尚未确认的城市、时间与选择会关闭。</Text></Dialog.Content><Dialog.Actions style={styles.actions}>{action('继续编辑行程', () => setLeaving(false))}{action('放弃修改并返回旅行', exit, busy)}</Dialog.Actions></Dialog>
    <Dialog visible={!!removing && visible && !model.unknown} onDismiss={() => setRemoving(null)} dismissable={!busy}><Dialog.Title>{removing?.kind === 'cities' ? '移除这座城市？' : '移除这段行程？'}</Dialog.Title><Dialog.Content><Text>{removing?.kind === 'cities' ? '关联分段会解除城市关联并保留，时间不会自动改变。至少保留一座城市。' : '确认保存后，此分段对应的既有日程会解除旅行关联，保留为独立记录；不会删除历史、资料或照片。'}</Text><Text>这里只调整本页草稿，仍需预览并确认保存。</Text></Dialog.Content><Dialog.Actions style={styles.actions}>{action('保留此项', () => setRemoving(null))}{action('确认移出草稿', remove, locked)}</Dialog.Actions></Dialog>
  </Portal>;
  if (!visible) return <View style={{ gap: density.pageGap }}><ActivityIndicator animating={busy} /><Text accessibilityRole={error ? 'alert' : undefined}>{error || '正在核对旅行与登录身份…'}</Text>
    {isPending(model) && <Text>本次未保存的内容和原操作仍在内存中，身份核对前不会显示。</Text>}
    {action('重新读取行程', () => active.current ? void job(load) : enter(), busy || !household.online || !online())}{action('返回旅行', back, busy || !!model.unknown)}{dialogs}</View>;
  const d = model.draft, plan = d?.plan, v2 = plan?.schemaVersion === 2 ? plan : null;
  const editingSegment = v2?.segments.find(row => row.key === selected), editingCity = v2?.destinations.find(row => row.key === city);
  const p = model.preview;
  return <View testID="journey-segments-panel" style={{ gap: density.pageGap }}>
    <PageHeader title="编辑详细行程" description={model.source?.plan.title || d?.plan.title} />
    {action('返回旅行', back, busy || !!model.unknown)}
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}{!!message && <Text accessibilityLiveRegion="polite">{message}</Text>}{busy && <ActivityIndicator accessibilityLabel="正在核对详细行程" />}
    {!model.capabilities?.canWriteV2 && <Text>当前服务尚未提供完整详细行程编辑能力。内容仅供查看，请更新服务后重新读取；不会降级提交。</Text>}
    {model.unknown && <SectionCard title="先核对这次保存"><View testID="journey-segments-unknown" style={{ gap: density.pageGap }}><Text>原预览和操作编号仍保留。只读查询无回执不代表未保存；不会换新编号或自动重复提交。</Text>
      <View style={styles.actions}>{action('核对行程保存结果', () => void recover(), busy, 'contained')}{action('按原行程请求重试', () => void confirm(true), busy, 'outlined')}</View></View></SectionCard>}
    {model.receipt && <SectionCard title="行程保存已确认"><View testID="journey-segments-receipt" style={{ gap: density.pageGap }}><Text>这份回执只证明原操作成功。日历云端、预订平台和随后发生的修改需分别核对。</Text>
      {model.source ? <><Text>已读取当前旅行：{model.source.plan.title}</Text>{action('继续编辑详细行程', () => install({ receipt: null }), busy, 'outlined')}{action('返回旅行详情', back, busy, 'contained')}</>
        : <><Text>当前详情尚未读取，旧草稿和操作按钮已关闭。</Text>{action('读取当前行程', () => void job(load), busy, 'contained')}</>}
    </View></SectionCard>}
    {model.receipt && model.source && <SectionCard title="当前已保存行程"><View testID="journey-segments-current" style={{ gap: density.pageGap }}>
      <Text>以下来自刚读取的当前详情；单独编辑的日程可能与旅行计划不同，分别列出供核对。</Text>
      {model.source.plan.segments.slice(pages.saved * PAGE, (pages.saved + 1) * PAGE).map(row => { const event = model.source!.events.find(item => item.workflowKey === 'segment:' + row.key); return <View key={row.key} style={styles.row}>
        <Text variant="titleSmall">{row.title}</Text><Text>旅行计划：{'kind' in row ? segmentText(row) : `${row.start} → ${row.end}（包含结束日）`}</Text>
        <Text>当前日程：{event ? valueText(event) : '关联日程当前不存在，没有据旧计划重建'}</Text>
      </View>; })}{page('saved', model.source.plan.segments.length)}
    </View></SectionCard>}
    {model.missing && <Text>旅行当前不可读取。未保存草稿仍保留，可明确放弃；历史回执不会重建旅行。</Text>}
    {model.blocked && !model.unknown && !model.receipt && <SectionCard title="内容已变化，草稿仍保留"><View testID="journey-segments-conflict" style={{ gap: density.pageGap }}>
      <Text>需要核对当前旅行和关联事项；读取不会静默覆盖你的输入。</Text>{action('读取最新行程', () => void job(load), busy, 'outlined')}
      {model.review && <><Text>当前旅行：{model.review.plan.title}</Text><Text>采用最新会放弃本页修改；保留草稿只合入本页的城市、分段和参考时区，其他内容采用最新记录。</Text>
        <View style={styles.actions}>{action('采用最新行程', () => chooseLatest(false), busy)}{action('保留草稿重新核对行程', () => chooseLatest(true), busy, 'contained')}</View></>}
    </View></SectionCard>}
    {plan && !model.unknown && !model.receipt && <>
      <SectionCard title="本次只调整城市与分段"><Text>{plan.start} → {plan.end}</Text><Text>总日期、金额、出行成员、准备与采购清单保持现有内容。要整体调整日期，请返回旅行使用「调整日期」。</Text></SectionCard>
      {!v2 ? <SectionCard title="启用详细行程"><View testID="journey-segments-upgrade" style={{ gap: density.pageGap }}>
        <Text>原日期行程会原样保留为「原日期段」。请明确每座城市与参考时区，升级后再添加航班、住宿或活动；不会自动推测当地时刻，保存后不能降回旧结构。</Text>
        <SegmentInput label="旅行参考时区" value={reference} onChange={value => { if (locked) return; setReference(value); install({ dirty: true }); }} disabled={locked} placeholder="例如 Asia/Shanghai" />
        {plan.destinations.slice(pages.upgrade * PAGE, (pages.upgrade + 1) * PAGE).map(row => <View key={row.key} style={{ gap: 8 }}><Text>{row.city} · {row.arrival} → {row.departure}</Text>
          <SegmentInput label={`城市时区：${row.city}`} value={zones[row.key] || ''} onChange={value => { if (locked) return; setZones(z => ({ ...z, [row.key]: value })); install({ dirty: true }); }} disabled={locked} placeholder="IANA 时区" /></View>)}
        {page('upgrade', plan.destinations.length)}{action('明确升级为详细行程', upgrading, locked, 'contained')}
      </View></SectionCard> : <>
        <SegmentInput label="旅行参考时区" value={v2.referenceTimezone} onChange={referenceTimezone => changePlan({ referenceTimezone })} disabled={locked} placeholder="IANA 时区" />
        <View accessibilityRole="radiogroup" accessibilityLabel="详细行程编辑内容" style={styles.actions}><SelectionRow kind="radio" label={`城市（${v2.destinations.length}）`} accessibilityLabel="编辑城市" checked={tab === 'cities'} disabled={busy} onPress={() => { setTab('cities'); setSelected(''); }} />
          <SelectionRow kind="radio" label={`分段（${v2.segments.length}）`} accessibilityLabel="编辑行程分段" checked={tab === 'segments'} disabled={busy} onPress={() => { setTab('segments'); setCity(''); }} /></View>
        {tab === 'cities' ? <SectionCard title="按行程顺序排列城市"><View style={{ gap: density.pageGap }}>
          {v2.destinations.slice(pages.cities * PAGE, (pages.cities + 1) * PAGE).map(row => <View key={row.key} style={styles.row}><Text variant="titleSmall">{row.city || '未命名城市'}</Text><Text>{row.country} · {row.arrival} → {row.departure} · {row.timeZone}</Text>
            <View style={styles.actions}>{action(`编辑城市：${row.city || '未命名城市'}`, () => setCity(row.key), locked)}{action(`移除城市：${row.city || '未命名城市'}`, () => setRemoving({ kind: 'cities', key: row.key }), locked || v2.destinations.length <= 1)}</View></View>)}
          {page('cities', v2.destinations.length)}{action('添加城市', () => add('city'), locked || v2.destinations.length >= 20, 'outlined')}
        </View></SectionCard> : <SectionCard title="航班、住宿与活动"><View style={{ gap: density.pageGap }}>
          {!v2.segments.length && <Text>尚无分段。根据实际资料添加，不会自动创建预订。</Text>}
          {v2.segments.slice(pages.segments * PAGE, (pages.segments + 1) * PAGE).map(row => <View key={row.key} style={styles.row}><Text variant="titleSmall">{row.title || '未命名分段'} · {segmentKindNames[row.kind]}</Text><Text>{segmentText(row)}</Text><Text>{bookingNames[row.bookingState]}</Text>
            <View style={styles.actions}>{action(`编辑分段：${row.title || '未命名分段'}`, () => { setSelected(row.key); setPages(p => ({ ...p, links: 0 })); }, locked)}{action(`移出分段：${row.title || '未命名分段'}`, () => setRemoving({ kind: 'segments', key: row.key }), locked)}</View></View>)}
          {page('segments', v2.segments.length)}<View style={styles.actions}>{(['flight', 'stay', 'activity'] as const).map(kind => <React.Fragment key={kind}>{action(`添加${segmentKindNames[kind]}`, () => add(kind), locked || v2.segments.length >= 100, 'outlined')}</React.Fragment>)}</View>
        </View></SectionCard>}
        {editingCity && <SectionCard title="编辑这座城市"><View testID="journey-city-editor" style={{ gap: density.pageGap }}>
          {([['city', '城市名称'], ['country', '国家或地区（可留空）'], ['arrival', '抵达日期'], ['departure', '离开日期（包含当天）'], ['timeZone', '城市当地时区']] as const).map(([key, label]) =>
            <SegmentInput key={key} label={label} value={editingCity[key]} disabled={locked} onChange={value => changePlan({ destinations: v2.destinations.map(row => row.key === editingCity.key ? { ...row, [key]: value } : row) })} />)}
          <View style={styles.actions}>{(['up', 'down'] as const).map(direction => { const index = v2.destinations.findIndex(row => row.key === editingCity.key), target = index + (direction === 'up' ? -1 : 1); return <React.Fragment key={direction}>{action(direction === 'up' ? '城市向前移动' : '城市向后移动', () => { const rows = [...v2.destinations]; [rows[index], rows[target]] = [rows[target], rows[index]]; changePlan({ destinations: rows }); setPages(p => ({ ...p, cities: Math.floor(target / PAGE) })); }, locked || target < 0 || target >= v2.destinations.length)}</React.Fragment>; })}</View>
          {action('收起城市编辑', () => setCity(''), busy)}
        </View></SectionCard>}
        {editingSegment && <SectionCard title={`编辑${segmentKindNames[editingSegment.kind]}`}><View testID="journey-segment-editor" style={{ gap: density.pageGap }}>
          <SegmentFields segment={editingSegment} disabled={locked} onChange={value => changePlan({ segments: v2.segments.map(row => row.key === value.key ? value : row) })} />
          <View accessibilityRole="radiogroup" accessibilityLabel="分段关联城市"><SelectionRow kind="radio" label="不关联城市" checked={!editingSegment.destinationKey} disabled={locked} onPress={() => { const { destinationKey: _key, ...rest } = editingSegment; changePlan({ segments: v2.segments.map(row => row.key === rest.key ? rest : row) }); }} />
            {v2.destinations.slice(pages.links * PAGE, (pages.links + 1) * PAGE).map(row => <SelectionRow key={row.key} kind="radio" label={row.city || '未命名城市'} accessibilityLabel={`关联城市：${row.city || '未命名城市'}`} checked={editingSegment.destinationKey === row.key} disabled={locked} onPress={() => changePlan({ segments: v2.segments.map(item => item.key === editingSegment.key ? { ...item, destinationKey: row.key } : item) })} />)}
          </View>{page('links', v2.destinations.length)}<View style={styles.actions}>{(['up', 'down'] as const).map(direction => { const index = v2.segments.findIndex(row => row.key === editingSegment.key), target = index + (direction === 'up' ? -1 : 1); return <React.Fragment key={direction}>{action(direction === 'up' ? '分段向前移动' : '分段向后移动', () => { const rows = [...v2.segments]; [rows[index], rows[target]] = [rows[target], rows[index]]; changePlan({ segments: rows }); setPages(p => ({ ...p, segments: Math.floor(target / PAGE) })); }, locked || target < 0 || target >= v2.segments.length)}</React.Fragment>; })}</View>
          {action('收起分段编辑', () => setSelected(''), busy)}
        </View></SectionCard>}
        {issue && <SectionCard title="请核对当地时间"><View testID="journey-segment-time-issue" style={{ gap: density.pageGap }}><Text>{issue.error}</Text><Text>修改对应分段的当地时间或时区后，再预览。若同一时刻出现两次，请选择实际 UTC 偏移。</Text>
          <View style={{ gap: density.pageGap }}>{issue.choices.map(choice => <View key={choice.offsetMinutes}><Text>对应真实时刻：{choice.instant}</Text>{action(`采用 UTC 偏移 ${choice.offsetMinutes} 分钟`, () => {
            try { const next = applyTimeChoice(d!, issue, choice.offsetMinutes); change(next); setMessage('已记录你的时间选择，请重新预览。'); }
            catch (e) { setError(e instanceof Error ? e.message : '时间已变化，请重新预览。'); }
          }, locked, 'outlined')}</View>)}</View></View></SectionCard>}
        {action('预览详细行程', () => void preview(), locked, 'contained')}
      </>}
      {p && <SectionCard title="核对后再保存"><View testID="journey-segments-preview" style={{ gap: density.pageGap }}>
        <Text>本次仅预览，尚未写入。当地时刻、偏移和 UTC 以服务器本次规范化结果为准。</Text>
        <Text>参考时区：{model.source?.plan.schemaVersion === 2 ? model.source.plan.referenceTimezone : '原日期结构'} → {p.plan.referenceTimezone}</Text>
        <Text variant="titleSmall">城市与停留</Text>
        {p.plan.destinations.slice(pages.previewCities * PAGE, (pages.previewCities + 1) * PAGE).map(row => { const before = model.source?.plan.destinations.find(item => item.key === row.key); return <View key={row.key} style={styles.row}>
          <Text>{row.city} · {row.country}</Text><Text>原计划：{before ? `${before.city} · ${before.arrival} → ${before.departure}${'timeZone' in before ? ' · ' + before.timeZone : ''}` : '新增城市'}</Text>
          <Text>保存后：{row.arrival} → {row.departure}（包含离开日） · {row.timeZone}</Text></View>; })}{page('previewCities', p.plan.destinations.length)}
        <Text variant="titleSmall">每段日期与当地时刻</Text>
        {p.plan.segments.slice(pages.preview * PAGE, (pages.preview + 1) * PAGE).map(row => <View key={row.key} style={styles.row}><Text variant="titleSmall">{row.title}</Text>
          <Text>保存后的计划：{segmentText(row)}</Text><Text>原计划：{(() => { const before = model.source?.plan.segments.find(item => item.key === row.key); return before ? 'kind' in before ? segmentText(before) : `${before.start} → ${before.end}（包含结束日）` : '新增分段'; })()}</Text>
          <Text>{bookingNames[row.bookingState]} · {row.datePolicy === 'fixed' ? '固定日期' : '可在改期时选择联动'}{row.destinationKey ? ' · ' + (p.plan.destinations.find(city => city.key === row.destinationKey)?.city || '关联城市') : ''}</Text>
          <Text>{row.location}</Text><Text>{row.note}</Text></View>)}{page('preview', p.plan.segments.length)}
        {!!p.summary.detach && <Text>{p.summary.detach} 项将解除旅行关联，保留为独立记录，不删除历史。</Text>}
        {!!p.summary.cloudReviews.length && <Text>{p.summary.cloudReviews.length} 项云日历绑定需要另行核对。保存本地行程不会直接覆盖远端日历。</Text>}
        {!!p.summary.preserved.length && <Text>{p.summary.preserved.length} 组单独编辑过的日程内容会保留。旅行计划与当前日程可能不同。</Text>}
        {[...p.summary.preserved, ...p.summary.resolved].slice(pages.comparisons * PAGE, (pages.comparisons + 1) * PAGE).map(row => <View key={row.itemKey + row.fieldGroup} style={styles.row}>
          <Text variant="titleSmall">{v2?.segments.find(item => 'segment:' + item.key === row.itemKey)?.title || '旅行日程'} · {groupNames[row.fieldGroup]}</Text>
          <Text>{row.resolution === 'plan' ? '明确采用本页计划：' : '保留当前日程：'}{valueText(row.resolution === 'plan' ? row.proposed : row.current)}</Text>
        </View>)}{page('comparisons', p.summary.preserved.length + p.summary.resolved.length)}
        {p.summary.warnings.slice(pages.warnings * PAGE, (pages.warnings + 1) * PAGE).map((warning, index) => <Text key={`${pages.warnings}-${index}`}>{warning.message}</Text>)}{page('warnings', p.summary.warnings.length)}
        {p.summary.conflicts.slice(pages.conflicts * PAGE, (pages.conflicts + 1) * PAGE).map(conflict => <View key={conflict.itemKey + conflict.fieldGroup} testID={`segment-conflict-${conflict.itemKey}-${conflict.fieldGroup}`} style={styles.row}>
          <Text variant="titleSmall">{v2?.segments.find(row => 'segment:' + row.key === conflict.itemKey)?.title || '旅行日程'} · {groupNames[conflict.fieldGroup] || '内容'}</Text>
          <Text>原来：{valueText(conflict.base)}</Text><Text>当前日程：{valueText(conflict.current)}</Text><Text>本页计划：{valueText(conflict.proposed)}</Text>
          <View accessibilityRole="radiogroup" accessibilityLabel="日程冲突选择">{(['current', 'plan'] as const).map(choice => <SelectionRow key={choice} kind="radio" label={choice === 'current' ? '保留当前日程' : '使用本页计划'}
            accessibilityLabel={`${choice === 'current' ? '保留当前日程' : '使用本页计划'}：${v2?.segments.find(row => 'segment:' + row.key === conflict.itemKey)?.title || '旅行日程'}：${groupNames[conflict.fieldGroup]}`} checked={model.choices[conflict.itemKey]?.[conflict.fieldGroup] === choice} disabled={locked}
            onPress={() => { if (!current() || locked) return; install({ choices: { ...live.current.choices, [conflict.itemKey]: { ...live.current.choices[conflict.itemKey], [conflict.fieldGroup]: choice } } }); }} />)}</View>
        </View>)}{page('conflicts', p.summary.conflicts.length)}
        {!!p.summary.conflicts.length && action('按选择重新预览行程', () => void preview(), locked, 'contained')}
        {p.canApply && action('确认保存详细行程', () => void confirm(), locked, 'contained')}
        {action('返回修改详细行程', () => install({ preview: null, choices: {} }), locked)}
      </View></SectionCard>}
    </>}{dialogs}
  </View>;
}
const styles = StyleSheet.create({ actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }, touch: { minHeight: 44 }, button: { alignSelf: 'flex-start', maxWidth: '100%' }, row: { gap: 8, paddingVertical: 10, minWidth: 0 } });
