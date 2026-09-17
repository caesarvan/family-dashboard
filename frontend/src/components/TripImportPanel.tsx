import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { type JourneyPlan, type Segment, type TimePoint } from '../lib/journeySegments';
import { amountText } from '../lib/trips';
import { MAX_TRIP_IMPORT_BYTES, parseTripImport, decodeTripImportFile, tripImportVersions, tripImportPreviewBody, readTripImportPreview, createTripImportIntent,
  failedTripImportIntent, readTripImportReceipt, readTripImportOperation, readTripImportCurrent, readTripImportList, tripImportActor, TripImportRecoveryMemory,
  canEndTripImport, missingTripImportReceipt, importOperationKey, tripImportRequest, TripImportFence, TripImportError, TripImportDiscarded, checkedTripImportWrite,
  type TripImportSession, type ImportPreview, type ImportIntent, type ImportReceipt, type ImportListItem, type ImportEndProof } from '../lib/tripImport';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';

type Props = { onBack: () => void; onSaved: (ids: { journeyId: string; tripId: string }) => void | Promise<void>; onPendingChange?: (pending: boolean) => void };
const recovery = new TripImportRecoveryMemory();
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
type Model = { raw: string; filename: string; visible: boolean; versions: (1 | 2)[]; preview: ImportPreview | null; intent: ImportIntent | null;
  operation: string | null; receipt: ImportReceipt | null; lastKey: string; lookup: string; checked: boolean; list: ImportListItem[] | null; proof: ImportEndProof | null;
  error: string; message: string; leave: boolean; ending: boolean };
const initial = (handle: { key: string; pending: boolean } | null): Model => ({ raw: '', filename: '', visible: false, versions: [], preview: null, intent: null,
  operation: handle?.pending ? handle.key : null, receipt: null, lastKey: handle?.key || '', lookup: '', checked: false, list: null, proof: null, error: '', message: '', leave: false, ending: false });

export default function TripImportPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户导入旅行" action={<Button contentStyle={styles.touch} onPress={props.onBack}>返回旅行计划</Button>} />;
  return <Workspace key={household.identityKey} {...props} identity={household.identityKey} actor={tripImportActor({ user: household.user })} />;
}
function Workspace(props: Props & { identity: string; actor: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState(() => initial(recovery.get(props.actor))), [busy, setBusy] = useState(false);
  const live = useRef(model), alive = useRef(false), active = useRef(false), focused = useRef(false), working = useRef(false), epoch = useRef(0), denied = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), hidden = useRef(false), windowFocused = useRef(true);
  const flight = useRef<AbortController | null>(null), reader = useRef<FileReader | null>(null), input = useRef<HTMLInputElement | null>(null), fence = useRef(new TripImportFence(props.identity));
  const same = () => latest.current.household.identityKey === props.identity;
  const current = (ticket = epoch.current) => alive.current && same() && active.current && focused.current && foreground.current && windowFocused.current && !hidden.current && !denied.current
    && epoch.current === ticket && latest.current.household.online && connected() && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || !!live.current.raw.trim() || !!live.current.preview || !!live.current.operation || !!live.current.receipt;
  function report() { if (alive.current && same()) latest.current.props.onPendingChange?.(pending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); report(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); report(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    const oldReader = reader.current; reader.current = null; oldReader?.abort(); if (input.current) input.current.value = '';
    working.current = false; setBusy(false);
    if (clear) live.current = initial(recovery.get(props.actor));
    install({ visible: false, error: '', message: '', list: null, proof: null, leave: false, ending: false });
  }
  function failed(error: unknown) {
    if (error instanceof TripImportDiscarded && error.message !== 'identity') return;
    if (error instanceof TripImportDiscarded || error instanceof TripImportError && [401, 403].includes(error.status)) {
      denied.current = true; conceal(true); install({ error: '登录身份已变化，导入内容已清除。请重新核对身份。' }); void latest.current.household.refresh(); return;
    }
    let message = error instanceof Error ? error.message : '暂时无法完成操作，请重试读取。';
    if (error instanceof TripImportError && error.body && typeof error.body === 'object') {
      const body = error.body as Record<string, unknown>;
      if (typeof body.field === 'string' && body.field.length < 200) message += `\n请修改 JSON 的 ${body.field}。`;
      if (Array.isArray(body.choices) && body.choices.length <= 2) for (const choice of body.choices) {
        if (choice && typeof choice === 'object' && Number.isInteger(choice.offsetMinutes) && typeof choice.instant === 'string' && choice.instant.length < 40)
          message += `\n可选偏移 ${choice.offsetMinutes} 分钟，对应 ${choice.instant}；请明确填写相应偏移后重新预览。`;
      }
    }
    install({ error: message });
  }
  const guard = <T,>(signal: AbortSignal, ticket: number, job: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await tripImportRequest('/me', signal) as TripImportSession, job, () => current(ticket));
  async function run(job: (signal: AbortSignal, ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const controller = new AbortController(), ticket = epoch.current; flight.current = controller; setWorking(true); install({ error: '', leave: false, ending: false });
    try { await job(controller.signal, ticket); } catch (error) { if (current(ticket)) failed(error); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  function enter() {
    if (active.current || denied.current || !alive.current || !focused.current || !foreground.current || !windowFocused.current || hidden.current || !same() || !connected()
      || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void run(async (signal, ticket) => {
      const versions = await guard(signal, ticket, async () => tripImportVersions(await tripImportRequest('/journeys/templates', signal)));
      if (current(ticket)) install({ versions, visible: true });
    });
  }
  useEffect(() => { alive.current = true; report(); return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); reader.current?.abort(); live.current = initial(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identity]));
  useEffect(() => {
    const visibility = () => document.hidden ? conceal() : enter(), offline = () => conceal(), online = () => enter();
    const blur = () => { windowFocused.current = false; conceal(); }, focus = () => { windowFocused.current = true; enter(); };
    const hide = () => { hidden.current = true; conceal(); }, show = () => { hidden.current = false; enter(); };
    const unload = (event: BeforeUnloadEvent) => { if (pending()) { event.preventDefault(); event.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('offline', offline); window.addEventListener('online', online);
      window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('offline', offline); window.removeEventListener('online', online);
        window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function refresh() { if (!working.current) { active.current = false; enter(); } }
  function edit(raw: string, filename = '') { if (current() && !working.current && !live.current.operation && !live.current.receipt) install({ raw, filename, preview: null, intent: null, error: '', message: '', proof: null }); }
  function choose(file?: File) {
    if (!file || !current() || working.current || live.current.operation || live.current.receipt) return;
    if (!/\.json$/i.test(file.name) || !file.size || file.size > MAX_TRIP_IMPORT_BYTES) { install({ error: '请选择非空且不超过 200,000 字节的 JSON 文件。' }); return; }
    const ticket = epoch.current, fileReader = new FileReader(); reader.current = fileReader; setWorking(true); install({ error: '', preview: null });
    fileReader.onload = () => {
      if (!current(ticket) || reader.current !== fileReader) return;
      try { if (!(fileReader.result instanceof ArrayBuffer)) throw new Error('无法读取此文件。'); const raw = decodeTripImportFile(fileReader.result); parseTripImport(raw); install({ raw, filename: file.name, intent: null }); }
      catch (error) { failed(error); }
      finally { if (reader.current === fileReader) { reader.current = null; setWorking(false); } }
    };
    fileReader.onerror = () => { if (current(ticket) && reader.current === fileReader) { reader.current = null; setWorking(false); failed(new Error('文件读取失败，请重新选择。')); } };
    fileReader.readAsArrayBuffer(file);
  }
  const preview = () => void run(async (signal, ticket) => {
    if (live.current.operation || live.current.receipt) return;
    const input = parseTripImport(live.current.raw); install({ preview: null });
    const result = await guard(signal, ticket, async csrf => {
      const versions = tripImportVersions(await tripImportRequest('/journeys/templates', signal));
      return readTripImportPreview(await tripImportRequest('/journeys/preview', signal, { method: 'POST', csrf, payload: tripImportPreviewBody(input, versions) }));
    });
    if (current(ticket)) install({ preview: result, intent: null });
  });
  async function finish(receipt: ImportReceipt, signal: AbortSignal, ticket: number) {
    const detail = await guard(signal, ticket, async () => readTripImportCurrent(await tripImportRequest('/journeys/' + receipt.id, signal), receipt));
    if (!current(ticket)) return;
    // Keep the known receipt until the parent has also completed its guarded read and transition.
    await latest.current.props.onSaved({ journeyId: detail.id, tripId: detail.tripId });
    if (current(ticket)) { install({ raw: '', preview: null, receipt: null }); report(); }
  }
  function accepted(receipt: ImportReceipt) {
    const key = live.current.operation; if (key) recovery.finish(props.actor, key);
    install({ receipt, operation: null, preview: null, intent: null, raw: '', filename: '', list: null, proof: null, message: '已查到保存回执，正在读取当前旅行。' });
  }
  const save = (retry = false) => void run(async (signal, ticket) => {
    const before = live.current;
    if (before.receipt || retry && (!before.intent || !before.operation || !before.checked) || !retry && (before.operation || !before.preview)) return;
    const intent = retry ? before.intent! : createTripImportIntent(before.preview!);
    let dispatched = false;
    try {
      const receipt = await checkedTripImportWrite(job => guard(signal, ticket, job), async csrf => {
        dispatched = true; recovery.set(props.actor, intent.body.idempotencyKey);
        install({ operation: intent.body.idempotencyKey, lastKey: intent.body.idempotencyKey, intent: { ...intent, uncertain: true }, proof: null, list: null, preview: null });
        return readTripImportReceipt(await tripImportRequest('/journeys/apply', signal, { method: 'POST', csrf, payload: intent.body }));
      });
      if (!current(ticket)) return; accepted(receipt); await finish(receipt, signal, ticket);
    } catch (error) {
      if (current(ticket) && dispatched && !live.current.receipt) {
        const retained = failedTripImportIntent(intent, error);
        if (retained) install({ intent: retained, message: '保存结果尚未确认，请先核对原操作。' });
        else { recovery.finish(props.actor, intent.body.idempotencyKey); install({ operation: null, intent: null, preview: null, checked: false, message: '本次请求被明确拒绝，输入已保留，请重新预览。' }); }
      }
      throw error;
    }
  });
  const inspect = () => void run(async (signal, ticket) => {
    const key = live.current.operation; if (!key) return; install({ proof: null, list: null, checked: true });
    const outcome = await guard(signal, ticket, async () => {
      const rows = readTripImportList(await tripImportRequest('/journeys', signal));
      try { return { rows, receipt: readTripImportOperation(await tripImportRequest('/journeys/operations/' + key, signal), key) }; }
      catch (error) { if (!missingTripImportReceipt(error)) throw error; return { rows, receipt: null }; }
    });
    if (!current(ticket) || live.current.operation !== key) return;
    if (outcome.receipt) { accepted(outcome.receipt); await finish(outcome.receipt, signal, ticket); }
    else install({ list: outcome.rows, proof: Object.freeze({ key, identity: props.identity, epoch: ticket }), message: '暂未查到结果，原请求仍可能完成。请先核对当前旅行列表；重新创建可能产生重复旅行。' });
  });
  const reread = () => void run(async (signal, ticket) => { if (live.current.receipt) await finish(live.current.receipt, signal, ticket); });
  function lookup() { if (!current() || working.current || live.current.raw.trim() || live.current.operation || live.current.receipt) return;
    try { const key = importOperationKey(live.current.lookup || live.current.lastKey); recovery.set(props.actor, key); install({ operation: key, lastKey: key, intent: null, checked: false, proof: null, error: '', message: '' }); }
    catch (error) { failed(error); }
  }
  function end() {
    if (!current() || working.current || !canEndTripImport(live.current.proof, live.current.operation, props.identity, epoch.current)) return;
    recovery.finish(props.actor, live.current.operation!); install({ raw: '', filename: '', preview: null, intent: null, operation: null, proof: null, list: null, checked: false, ending: false, message: '已结束本地核对，原编号仍可查询；没有再次创建旅行。' });
  }
  function exit() { if (working.current || live.current.operation) return; conceal(); live.current = initial(null); latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
  function back() { if (working.current) return; if (live.current.operation) install({ error: '请先核对保存结果，或在核对当前旅行后明确结束本次核对。' });
    else if (live.current.raw.trim() || live.current.preview) install({ leave: true }); else exit(); }
  const people = household.state?.people || [], owner = (value: string) => value === 'shared' ? '共同负责' : people.find(p => p.id === value)?.name || '未识别成员';
  const usable = model.visible && current(), locked = busy || !!model.operation || !!model.receipt;
  return <View testID="trip-import-panel" style={{ gap: density.sectionGap }}>
    <PageHeader title="导入旅行" description="读入一份计划，核对后创建新旅行。" action={<Button contentStyle={styles.touch} disabled={busy} onPress={back}>返回旅行计划</Button>} />
    {busy ? <ActivityIndicator accessibilityLabel="正在处理旅行导入" /> : null}
    {model.error ? <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{model.error}</Text> : null}
    {!usable ? <EmptyState title="旅行导入内容已隐藏" description="连接恢复并核对身份后继续。草稿仅保留在当前页面内存中。" action={<Button contentStyle={styles.touch} disabled={busy || !connected() || denied.current} onPress={refresh}>重新核对身份</Button>} /> : <>
      {model.message ? <Text accessibilityLiveRegion="polite">{model.message}</Text> : null}
      {model.receipt ? <SectionCard title="已查到保存回执"><View testID="trip-import-saved" style={styles.stack}><Text>还需读取当前旅行；读取失败不会再次创建。</Text>
        <Button mode="contained" contentStyle={styles.touch} disabled={busy} onPress={reread}>重新读取旅行</Button></View></SectionCard> : null}
      {model.operation ? <SectionCard title="核对保存结果"><View testID="trip-import-unknown" style={styles.stack}>
        <Text>先核对原操作。未查到回执不代表没有保存。</Text><Text selectable>操作编号：{model.operation}</Text>
        <View style={styles.actions}><Button mode="contained" contentStyle={styles.touch} disabled={busy} onPress={inspect}>核对保存结果</Button>
          {model.intent ? <Button contentStyle={styles.touch} disabled={busy || !model.checked} onPress={() => save(true)}>按原请求重试</Button> : null}</View>
        {model.list ? <RecordPages title="当前旅行" rows={model.list.map(r => ({ title: r.title, lines: [`${r.start} 至 ${r.end}`] }))} disabled={busy} /> : null}
        {canEndTripImport(model.proof, model.operation, props.identity, epoch.current) ? <Button contentStyle={styles.touch} disabled={busy} onPress={() => install({ ending: true })}>结束本次核对</Button> : null}
      </View></SectionCard> : null}
      {!model.operation && !model.receipt && !model.preview ? <SectionCard title="选择或粘贴计划"><View style={styles.stack}>
        <Text>支持第 1、2 版旅行 JSON，最多 200,000 字节。只创建新旅行；已有旅行请从详情编辑。</Text>
        {Platform.OS === 'web' ? <><View style={styles.actions}><Button contentStyle={styles.touch} mode="outlined" disabled={locked} onPress={() => input.current?.click()}>选择 JSON 文件</Button>
          <Text>{model.filename || '尚未选择文件，也可直接粘贴'}</Text></View>
          {React.createElement('input', { type: 'file', accept: '.json,application/json', 'aria-label': '旅行 JSON 文件', 'data-testid': 'trip-import-file', style: { display: 'none' },
            ref: (node: HTMLInputElement | null) => { input.current = node; }, onChange: (event: React.ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; event.target.value = ''; choose(file); } })}</> : <Text>可在浏览器选择文件，或在下方粘贴内容。</Text>}
        <Text>旅行 JSON</Text><TextInput testID="trip-import-input" accessibilityLabel="旅行 JSON" mode="outlined" multiline numberOfLines={8} maxLength={MAX_TRIP_IMPORT_BYTES} style={styles.input} value={model.raw} editable={!locked} onChangeText={value => edit(value)} />
        <View style={styles.actions}><Button mode="contained" contentStyle={styles.touch} disabled={locked || !model.raw.trim()} onPress={preview}>预览导入</Button>
          {Platform.OS === 'web' ? <>{React.createElement('a', { href: '/static/examples/journey-plan-v1.json', download: 'journey-plan-v1.json', style: { color: theme.colors.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' } }, '下载第 1 版示例')}
            {React.createElement('a', { href: '/static/examples/journey-plan-v2.json', download: 'journey-plan-v2.json', style: { color: theme.colors.primary, minHeight: 44, display: 'inline-flex', alignItems: 'center' } }, '下载第 2 版示例')}</> : null}</View>
      </View></SectionCard> : null}
      {model.preview && !model.operation && !model.receipt ? <View testID="trip-import-preview" style={{ gap: density.sectionGap }}>
        <SectionCard title="核对新旅行"><View style={styles.stack}><Text variant="titleLarge">{model.preview.plan.title}</Text><Text>{model.preview.plan.start} 至 {model.preview.plan.end} · {model.preview.plan.international ? '境外旅行' : '国内旅行'}</Text>
          <Text>同行成员：{model.preview.plan.memberIds.map(owner).join('、')}</Text><Text>预算 ¥{amountText(model.preview.plan.budget)} · 已预留 ¥{amountText(model.preview.plan.saved)} · 已支付 ¥{amountText(model.preview.plan.paid)}</Text>
          <Text>{model.preview.plan.note || '未填写旅行备注'}</Text><Text>将新增：{Object.entries(model.preview.create).map(([key, n]) => `${({ trips: '旅行', tasks: '准备事项', shopping: '采购', events: '日程' } as Record<string, string>)[key]} ${n}`).join('、')}</Text>
          <Text>未提供准备清单时使用服务端模板；未提供分段时按目的地生成。下方是实际采用的全部内容。</Text>
          <Text>{model.preview.calendar}</Text><Text>{model.preview.policyNotice}</Text>{model.preview.warnings.map((message, i) => <Text key={i} style={{ color: theme.colors.error }}>{message}</Text>)}
          {model.preview.plan.schemaVersion === 2 ? <Text>参考时区：{model.preview.plan.referenceTimezone}；预订状态均为人工标记。</Text> : null}
        </View></SectionCard>
        <PlanDetails plan={model.preview.plan} owner={owner} disabled={busy} />
        <View style={styles.actions}><Button contentStyle={styles.touch} disabled={busy} onPress={() => install({ preview: null })}>修改输入</Button>
          <Button mode="contained" contentStyle={styles.touch} disabled={busy} onPress={() => save()}>确认创建旅行</Button></View>
        <Text>仅保存站内旅行与事项，不预订、不自动记账或写入云日历。</Text>
      </View> : null}
      {!model.operation && !model.receipt && !model.preview && !model.raw.trim() ? <SectionCard title="查询之前的操作"><View style={styles.stack}>
        {model.lastKey ? <Text selectable>上次操作编号：{model.lastKey}</Text> : null}<TextInput mode="outlined" accessibilityLabel="原操作编号" placeholder="粘贴原操作编号" value={model.lookup} editable={!busy} onChangeText={lookup => install({ lookup })} />
        <Button contentStyle={styles.touch} disabled={busy || !model.lookup && !model.lastKey} onPress={lookup}>查询原操作</Button></View></SectionCard> : null}
    </>}
    <Portal><Dialog visible={usable && model.leave} onDismiss={() => install({ leave: false })}><Dialog.Title>放弃导入草稿？</Dialog.Title><Dialog.Content><Text>尚未发送保存请求的内容将从此页面清除。</Text></Dialog.Content>
      <Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ leave: false })}>继续编辑</Button><Button contentStyle={styles.touch} onPress={exit}>放弃草稿并返回</Button></Dialog.Actions></Dialog>
      <Dialog visible={usable && model.ending} onDismiss={() => install({ ending: false })}><Dialog.Title>结束本次核对？</Dialog.Title><Dialog.Content><Text>暂未查到结果，原请求仍可能完成。结束后保留操作编号；重新创建可能产生重复旅行。</Text></Dialog.Content>
        <Dialog.Actions style={styles.actions}><Button contentStyle={styles.touch} onPress={() => install({ ending: false })}>继续核对</Button><Button contentStyle={styles.touch} onPress={end}>结束核对并清空输入</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}

type DisplayRow = { title: string; lines: string[] };
function RecordPages({ title, rows, disabled }: { title: string; rows: DisplayRow[]; disabled: boolean }) {
  const [open, setOpen] = useState(false), [page, setPage] = useState(0), density = useDisplayDensity();
  return <SectionCard title={`${title} · ${rows.length} 项`}><View style={styles.stack}><Button contentStyle={styles.touch} disabled={disabled} accessibilityLabel={`${open ? '收起' : '展开'}${title}`} onPress={() => setOpen(!open)}>{open ? '收起' : '查看全部内容'}</Button>
    {open ? <>{!rows.length ? <Text>没有{title}</Text> : null}{rows.slice(page * 5, page * 5 + 5).map((r, i) => <View key={`${page}-${i}`} style={{ gap: 4, paddingVertical: density.sectionGap / 2 }}><Text variant="titleSmall">{r.title}</Text>{r.lines.map((line, n) => <Text key={n}>{line}</Text>)}</View>)}
      {rows.length > 5 ? <View style={styles.actions}><Button contentStyle={styles.touch} disabled={disabled || page === 0} accessibilityLabel={`${title}上一页`} onPress={() => setPage(page - 1)}>上一页</Button><Text>{page + 1} / {Math.ceil(rows.length / 5)}</Text><Button contentStyle={styles.touch} disabled={disabled || (page + 1) * 5 >= rows.length} accessibilityLabel={`${title}下一页`} onPress={() => setPage(page + 1)}>下一页</Button></View> : null}</> : null}
  </View></SectionCard>;
}
const when = (point: TimePoint) => `${point.local.replace('T', ' ')} · ${point.timeZone}${point.offsetMinutes === undefined ? '' : ` · UTC 偏移 ${point.offsetMinutes} 分钟`}`;
function segmentLines(s: Segment): string[] {
  const common = [`${({ idea: '计划中', booked: '人工标记已预订', cancelled: '人工标记已取消' })[s.bookingState]} · ${s.datePolicy === 'fixed' ? '日期固定' : '可随旅行调整'}`, s.location || '未填写地点', s.note || '未填写备注'];
  if (s.kind === 'flight') return [`航班：${s.flightNumber || '未填写航班号'}`, `出发：${s.departure.city} ${s.departure.airport} · ${when(s.departure)}`, `到达：${s.arrival.city} ${s.arrival.airport} · ${when(s.arrival)}`, ...common];
  if (s.kind === 'stay') return [`住宿：${s.propertyName || '未填写名称'} · ${s.address || '未填写地址'}`, `入住：${s.checkInDate} ${s.checkInTime || '时刻未知'}；退房：${s.checkOutDate} ${s.checkOutTime || '时刻未知'}`, `${s.timeZone} · ${s.nights} 晚（不含退房日）`, ...common];
  if (s.kind === 'legacy_day') return [`日期：${s.start} 至 ${s.end}（含结束日）`, ...common];
  return [s.dateRange ? `${s.dateRange.startDate} 至 ${s.dateRange.endDateExclusive}（不含结束日） · ${s.timeZone}` : `${when(s.start)} 至 ${when(s.end)}`, ...common];
}
function PlanDetails({ plan, owner, disabled }: { plan: JourneyPlan; owner: (id: string) => string; disabled: boolean }) {
  return <>
    <RecordPages title="目的地" disabled={disabled} rows={plan.destinations.map(d => ({ title: `${d.country} · ${d.city}`, lines: [`${d.arrival} 至 ${d.departure}`, ...('timeZone' in d ? [`时区：${d.timeZone}`] : [])] }))} />
    <RecordPages title="准备事项" disabled={disabled} rows={plan.checklist.map(t => ({ title: t.title, lines: [owner(t.owner), `截止：${t.due}（出发日期偏移 ${t.dueOffsetDays} 天）`, `分类：${t.category || '未分类'}`, t.note || '未填写备注'] }))} />
    <RecordPages title="采购" disabled={disabled} rows={plan.shopping.map(s => ({ title: s.title, lines: [owner(s.owner), `数量：${s.quantity || '未填写'}`, s.budget === null ? '预算未知' : `预算：¥${amountText(s.budget)}`, s.note || '未填写备注'] }))} />
    <RecordPages title="行程分段" disabled={disabled} rows={plan.schemaVersion === 2 ? plan.segments.map(s => ({ title: s.title, lines: segmentLines(s) })) : plan.segments.map(s => ({ title: s.title, lines: [`${s.start} 至 ${s.end}（含结束日）`, s.location || '未填写地点', s.note || '未填写备注'] }))} />
  </>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, stack: { gap: 12 }, input: { minHeight: 190, maxHeight: 320 } });
