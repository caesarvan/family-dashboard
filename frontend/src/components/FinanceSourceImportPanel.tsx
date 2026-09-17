import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { baselinePage, formatBaselineMoney, formatBaselineTime } from '../lib/financeBaseline';
import { canEndSourceReview, checkedSourceConfirm, MAX_SOURCE_BYTES, parseSourceJSON, permitsSourceRepreview, readSourceOperation, readSourcePreview, readSourceReceipt, readSourceStatus,
  SourceDiscarded, SourceError, SourceFence, SourceRecoveryMemory, SourceRejected, sourceActor, sourceEndReview, sourceIntent, sourcePreviewBody, sourceRequest, sourceStatusPath,
  type SourceEndReview, type SourceIntent, type SourceMode, type SourceOperation, type SourcePreview, type SourceReceipt, type SourceSession, type SourceStatus } from '../lib/financeSourceImport';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

type Props = { onBack: () => void; onPendingChange?: (pending: boolean) => void };
// Opaque recovery handles only. Never persist candidate, token, receipt or financial DTO.
// A new authenticated session for the same household/member may read its own receipt.
const recovery = new SourceRecoveryMemory();
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const modes: [SourceMode, string][] = [['baseline', '完整资产来源'], ['spending_observation', '仅更新消费观察']];
type Model = { mode: SourceMode; raw: string; filename: string; candidate: Readonly<Record<string, unknown>> | null; status: SourceStatus | null; preview: SourcePreview | null;
  intent: SourceIntent | null; operation: SourceOperation | null; receipt: SourceReceipt | null; visible: boolean; acknowledged: boolean; confirmed: boolean; query: string; page: number;
  error: string; message: string; operationInput: string; leave: boolean; endReview: SourceEndReview | null; ending: boolean };
const initial = (operation: SourceOperation | null): Model => ({ mode: operation?.mode || 'baseline', raw: '', filename: '', candidate: null, status: null, preview: null, intent: null,
  operation, receipt: null, visible: false, acknowledged: false, confirmed: false, query: '', page: 0, error: '', message: '', operationInput: '', leave: false, endReview: null, ending: false });

export default function FinanceSourceImportPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户更新本人资产来源" action={<Button contentStyle={styles.touch} onPress={props.onBack}>返回财务</Button>} />;
  return <Workspace key={household.identityKey} {...props} identity={household.identityKey} actor={sourceActor({ user: household.user })} owner={household.user.id} />;
}
function Workspace(props: Props & { identity: string; actor: string; owner: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState(() => initial(recovery.get(props.actor) || null)), [busy, setBusy] = useState(false);
  const live = useRef(model), alive = useRef(false), active = useRef(false), focused = useRef(false), working = useRef(false), epoch = useRef(0), denied = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), pageHidden = useRef(false);
  const flight = useRef<AbortController | null>(null), reader = useRef<FileReader | null>(null), input = useRef<HTMLInputElement | null>(null), fence = useRef(new SourceFence(props.identity));
  const sameActor = () => latest.current.household.identityKey === props.identity;
  const current = (ticket = epoch.current) => alive.current && sameActor() && active.current && focused.current && foreground.current && !pageHidden.current && !denied.current
    && epoch.current === ticket && latest.current.household.online && connected() && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || !!live.current.operation || !!live.current.raw.trim() || !!live.current.preview;
  function report() { if (alive.current && sameActor()) latest.current.props.onPendingChange?.(pending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); report(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); report(); }
  function remember(operation: SourceOperation | null) { if (operation) recovery.set(props.actor, operation); else if (live.current.operation) recovery.clear(props.actor, live.current.operation); }
  function conceal() {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null; reader.current?.abort(); reader.current = null;
    if (input.current) input.current.value = '';
    working.current = false; setBusy(false);
    live.current = initial(live.current.operation); setModel(live.current); report();
  }
  function failed(error: unknown) {
    if (error instanceof SourceDiscarded && error.message !== 'identity') return;
    if (error instanceof SourceDiscarded || error instanceof SourceError && [401, 403].includes(error.status)) {
      denied.current = error instanceof SourceDiscarded; conceal(); install({ error: '身份或权限已变化，私密内容已清除。请重新核对身份。' }); void latest.current.household.refresh(); return;
    }
    install({ error: error instanceof SourceError ? error.message : '暂时无法完成操作，请重试读取。' });
  }
  const guard = <T,>(controller: AbortController, ticket: number, job: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await sourceRequest('/me', controller.signal) as SourceSession, job, () => current(ticket));
  async function readStatus(controller: AbortController, ticket: number, mode = live.current.mode) {
    const status = await guard(controller, ticket, async () => readSourceStatus(await sourceRequest(sourceStatusPath(mode), controller.signal), mode));
    if (current(ticket)) install({ status, visible: true }); return status;
  }
  async function run(job: (controller: AbortController, ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const controller = new AbortController(), ticket = epoch.current; flight.current = controller; setWorking(true); install({ error: '', leave: false });
    try { await job(controller, ticket); } catch (error) { if (current(ticket)) failed(error); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const refresh = () => { if (!active.current) enter(); else void run(async (controller, ticket) => { install({ status: null }); await readStatus(controller, ticket); }); };
  function enter() {
    if (active.current || denied.current || !alive.current || !focused.current || !foreground.current || pageHidden.current || !sameActor() || !connected() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void run(async (controller, ticket) => { await readStatus(controller, ticket); });
  }
  useEffect(() => { alive.current = true; report(); return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); reader.current?.abort(); live.current = initial(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identity]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, offline = () => conceal(), online = () => enter();
    const hide = () => { pageHidden.current = true; conceal(); }, show = (event: PageTransitionEvent) => { if (event.persisted || pageHidden.current) { pageHidden.current = false; conceal(); enter(); } };
    const unload = (event: BeforeUnloadEvent) => { if (pending()) { event.preventDefault(); event.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function back() {
    if (working.current) return;
    if (pending()) install({ leave: true }); else exit();
  }
  function exit() {
    if (working.current) return;
    conceal(); latest.current.props.onPendingChange?.(false); latest.current.props.onBack();
  }
  function edit(raw: string, filename = '') { if (!current() || working.current || live.current.operation) return; install({ raw, filename, preview: null, candidate: null, intent: null, receipt: null, confirmed: false, error: '', message: '', query: '', page: 0 }); }
  function chooseFile(file?: File) {
    if (!file || !current() || working.current || live.current.operation) return;
    if (!/\.json$/i.test(file.name) || file.size <= 0 || file.size >= MAX_SOURCE_BYTES) { install({ error: '请选择非空且小于 1.95 MB 的 JSON 文件。' }); return; }
    const ticket = epoch.current, job = new FileReader(); reader.current = job; setWorking(true); install({ error: '' });
    job.onload = () => { if (!current(ticket) || reader.current !== job) return;
      try { const raw = new TextDecoder('utf-8', { fatal: true }).decode(job.result as ArrayBuffer); parseSourceJSON(raw, live.current.mode); setWorking(false); edit(raw, file.name); }
      catch (error) { setWorking(false); failed(error); } finally { if (reader.current === job) reader.current = null; }
    };
    job.onerror = () => { if (current(ticket) && reader.current === job) { reader.current = null; setWorking(false); install({ error: '文件读取失败，请重新选择。' }); } };
    job.readAsArrayBuffer(file);
  }
  function preview() {
    if (live.current.operation) return;
    void run(async (controller, ticket) => {
      const candidate = parseSourceJSON(live.current.raw, live.current.mode), mode = live.current.mode, ack = live.current.acknowledged;
      install({ preview: null, candidate: null, intent: null, confirmed: false, receipt: null, message: '', page: 0, query: '' });
      const status = await readStatus(controller, ticket, mode);
      const result = await guard(controller, ticket, async csrf => readSourcePreview(await sourceRequest('/finance-baseline/imports/preview', controller.signal, sourcePreviewBody(status, candidate, ack), csrf), mode, props.owner));
      if (current(ticket)) install({ preview: result, candidate, message: '预览没有保存任何资产或消费记录。请核对后再确认。' });
    });
  }
  async function accepted(receipt: SourceReceipt, controller: AbortController, ticket: number) {
    if (!current(ticket)) throw new SourceDiscarded();
    remember(null); if (input.current) input.current.value = '';
    install({ raw: '', filename: '', candidate: null, preview: null, intent: null, operation: null, receipt, status: null, confirmed: false, operationInput: '', query: '', page: 0, endReview: null, ending: false,
      message: '已取得这次操作的历史回执。正在重新读取当前来源状态。' });
    await readStatus(controller, ticket);
    if (current(ticket)) install({ message: '已读取当前来源状态。下方回执只说明对应操作已保存，不代表当前最新版本。' });
  }
  function confirm(retry = false) {
    if (!current() || working.current) return;
    const priorUnknown = !!live.current.operation;
    let intent = live.current.intent;
    if (!retry) {
      if (priorUnknown || !live.current.confirmed || !live.current.preview || !live.current.candidate) return;
      intent = sourceIntent(live.current.preview, live.current.candidate, props.identity);
    }
    if (!intent || intent.identity !== props.identity) return;
    const original = intent;
    void run(async (controller, ticket) => {
      let receipt: SourceReceipt;
      try {
        receipt = await checkedSourceConfirm(job => guard(controller, ticket, job), async csrf => {
          // This is the first point where a write may have reached the server.
          remember(original); install({ intent: original, operation: { mode: original.mode, operationId: original.operationId }, message: '', confirmed: false, endReview: null, ending: false });
          return readSourceReceipt(await sourceRequest('/finance-baseline/imports/confirm', controller.signal, original.body, csrf), original, original.candidateDigest);
        });
      } catch (error) {
        if (!current(ticket)) throw error;
        if (permitsSourceRepreview(error) || !priorUnknown && error instanceof SourceRejected) {
          remember(null); install({ operation: null, intent: null, preview: null, candidate: null, confirmed: false, status: null, endReview: null, ending: false, message: '这次提交未被接受。请重新读取当前状态，再明确预览。' });
        } else if (live.current.operation) install({ message: '保存结果尚不确定。保留原操作编号；请核对回执，或明确重试同一请求。' });
        throw error;
      }
      // A successful commit is not made uncertain by a subsequent failed read.
      await accepted(receipt, controller, ticket);
    });
  }
  function recover() {
    const operation = live.current.operation; if (!operation) return;
    void run(async (controller, ticket) => {
      install({ endReview: null, ending: false });
      const result = await guard(controller, ticket, async () => {
        const status = readSourceStatus(await sourceRequest(sourceStatusPath(operation.mode), controller.signal), operation.mode);
        const receipt = readSourceOperation(await sourceRequest(sourceStatusPath(operation.mode, operation.operationId), controller.signal), operation);
        return { status, receipt };
      });
      if (!result.receipt) { install({ status: result.status, endReview: sourceEndReview(operation, result.status, result.receipt, props.identity), message: '目前未找到这次操作的回执。这不能证明没有保存，也不会自动再次提交。' }); return; }
      await accepted(result.receipt, controller, ticket);
    });
  }
  function endRecovery() {
    if (!current() || working.current || !canEndSourceReview(live.current.endReview, live.current.operation, props.identity, live.current.ending)) return;
    const operation = live.current.operation!, status = live.current.endReview!.status;
    remember(null); if (input.current) input.current.value = '';
    install({ ...initial(null), mode: operation.mode, visible: true, status, operationInput: operation.operationId,
      message: '你已结束本次核对，未断言原操作是否提交。原编号保留在下方可再次查询；请选择来源文件并重新核对最新版本后预览。' });
  }
  function useOperation() {
    if (!current() || pending()) return;
    try { const operation = { mode: live.current.mode, operationId: live.current.operationInput.trim() }; sourceStatusPath(operation.mode, operation.operationId); remember(operation); install({ operation, error: '', message: '已保留操作编号。请核对该操作的本人历史回执。' }); }
    catch { install({ error: '操作编号应为 64 位小写十六进制字符。' }); }
  }
  const show = model.visible && current(), disabled = busy || !show, rows = baselinePage(model.preview?.rows || [], model.query, model.page, row => [row.title, row.kind, row.currency, row.date].join(' '));
  const stack = { gap: density.sectionGap }, locked = disabled || !!model.operation;
  return <View testID="finance-source-import-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="更新资产来源" description="仅使用你选择的来源 JSON。先核对差异和日期，再明确保存；页面不会访问邮箱或金融机构。"
      action={<Button contentStyle={styles.touch} accessibilityLabel="返回财务" disabled={busy} onPress={back}>返回财务</Button>} />
    {!!model.error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{model.error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对资产来源" />}
    {!show ? <EmptyState title={connected() && household.online ? '正在核对本人身份和来源状态' : '离线时隐藏私密来源'} description="离开或进入后台后，来源 JSON 和预览会清除；已尝试保存的操作编号只在当前应用内存中保留。"
      action={<Button contentStyle={styles.touch} disabled={busy || !connected() || !household.online || denied.current} onPress={refresh}>重新读取来源状态</Button>} /> : <>
      {!!model.message && <Text accessibilityLiveRegion="polite">{model.message}</Text>}
      {model.operation ? <SectionCard title="核对上次操作"><View testID="source-import-unknown" style={stack}>
        <Text>更新范围：{modes.find(([mode]) => mode === model.operation!.mode)?.[1]}</Text>
        <Text selectable style={styles.wrap}>操作编号：{model.operation.operationId}</Text>
        <Text>未找到回执不代表操作未执行。清除页面数据或重新登录后，也可以使用此编号读取本人的历史回执。</Text>
        <Button mode="contained" contentStyle={styles.touch} disabled={disabled} onPress={recover}>核对操作结果</Button>
        {model.intent && <Button mode="outlined" contentStyle={styles.touch} disabled={disabled} onPress={() => confirm(true)}>按原请求重试</Button>}
        {model.endReview && <Button contentStyle={styles.touch} disabled={disabled} onPress={() => install({ ending: true })}>结束本次核对</Button>}
        <Button contentStyle={styles.touch} disabled={disabled} onPress={back}>保留操作编号并返回</Button>
      </View></SectionCard> : null}
      {model.receipt && <SectionCard title="操作回执"><View testID="source-import-receipt" style={stack}>
        <Text>{model.receipt.status === 'unchanged' ? '来源内容一致，未重复更新。' : '对应来源操作已保存。'}{model.receipt.replayed ? '这是历史操作的回执。' : ''}</Text>
        <Text>{formatBaselineTime(model.receipt.acceptedAt)}</Text><Text selectable style={styles.wrap}>操作编号：{model.receipt.receiptId}</Text>
        <Text>回执不是当前余额或最新报告；以重新读取的来源状态为准。</Text>
      </View></SectionCard>}
      <SectionCard title="选择更新范围"><View style={stack}>
        <View accessibilityRole="radiogroup">{modes.map(([mode, label]) => <SelectionRow key={mode} kind="radio" label={label} checked={model.mode === mode} disabled={locked || !!model.raw.trim() || !!model.preview}
          onPress={() => { if (locked || live.current.raw.trim() || live.current.preview) return; install({ ...initial(null), mode, visible: true }); void run(async (controller, ticket) => { await readStatus(controller, ticket, mode); }); }} />)}</View>
        <Text>{model.mode === 'baseline' ? '更新本人资产、负债、历史收入及来源消费观察；只共享已批准的人民币资产和负债小计。' : '只更新消费观察，不改变资产基线、家庭共享金额、持仓或交易账本。'}</Text>
        {model.status ? <><Text>资产资料截至：{model.status.dates.asOf || '尚未录入'}</Text><Text>余额记录日期：{model.status.dates.balanceAsOfStart || '待核对'} 至 {model.status.dates.balanceAsOfEnd || '待核对'}</Text>
          <Messages values={model.status.warnings} /></> : <Text>当前状态尚未重新读取，不能把历史回执当成当前记录。</Text>}
        <Button contentStyle={styles.touch} disabled={disabled} onPress={refresh}>重新读取来源状态</Button>
      </View></SectionCard>
      {!model.operation && <SectionCard title="选择或粘贴来源 JSON"><View style={stack}>
        <Text>使用已有转换工具生成的来源包，小于 1.95 MB。金额、错误记录和覆盖范围由服务器核对，页面不自动修补。</Text>
        {Platform.OS === 'web' && React.createElement('input', { ref: input, type: 'file', accept: '.json,application/json', style: { display: 'none' }, tabIndex: -1, 'aria-hidden': true,
          onChange: (event: React.ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; event.target.value = ''; chooseFile(file); } })}
        {Platform.OS === 'web' && <Button mode="outlined" contentStyle={styles.touch} disabled={locked} onPress={() => input.current?.click()}>选择来源 JSON 文件</Button>}
        {!!model.filename && <Text>已选择：{model.filename}</Text>}
        <TextInput mode="outlined" label="来源 JSON" accessibilityLabel="来源 JSON" multiline numberOfLines={6} maxLength={MAX_SOURCE_BYTES} value={model.raw} disabled={locked}
          style={{ minHeight: 150 }} onChangeText={raw => edit(raw)} />
        {model.status?.unknownCoverage && <SelectionRow label="我已了解旧消费覆盖未知，原快照仍会保留" checked={model.acknowledged} disabled={locked} onPress={() => install({ acknowledged: !live.current.acknowledged, preview: null, candidate: null, confirmed: false })} />}
        {model.mode === 'spending_observation' && model.status && !model.status.baselineExists && <Text>请先建立本人资产基线，再更新消费观察。</Text>}
        <View style={styles.actions}><Button mode="contained" contentStyle={styles.touch} disabled={locked || !model.raw.trim() || model.mode === 'spending_observation' && (!model.status?.baselineExists || model.status.unknownCoverage && !model.acknowledged)} onPress={preview}>预览来源变化</Button>
          <Button contentStyle={styles.touch} disabled={locked || !model.raw.trim()} onPress={() => edit('')}>清除来源草稿</Button></View>
      </View></SectionCard>}
      {model.preview && !model.operation && <SectionCard title="确认前核对"><View testID="source-import-preview" style={stack}>
        <Text>新增 {model.preview.changes.added} · 更新 {model.preview.changes.updated} · 保留 {model.preview.changes.preserved}</Text>
        <Text>资产资料截至 {model.preview.dates.asOf || '待核对'}；余额日期 {model.preview.dates.balanceAsOfStart || '待核对'} 至 {model.preview.dates.balanceAsOfEnd || '待核对'}</Text>
        <Text>消费覆盖 {model.preview.coverage.start} 至 {model.preview.coverage.end}</Text><Text>报告生成：{formatBaselineTime(model.preview.coverage.generatedAt)}</Text>
        <Text>已知缺口 {model.preview.coverage.quality.knownGapsCount}；不可读账单 {model.preview.coverage.quality.unreadableStatementsCount}。零个已知缺口不代表资料完整。</Text>
        <Text>渠道补充：{model.preview.coverage.quality.channelOnlyAdded ? '已补充' : '未补充'}；订单补充：{model.preview.coverage.quality.orderOnlyAdded ? '已补充' : '未补充'}</Text>
        {model.preview.shared ? <><Text>家庭可见的已记录资产小计：{formatBaselineMoney(model.preview.shared.assets, 'CNY')}</Text><Text>家庭可见的已记录负债小计：{formatBaselineMoney(model.preview.shared.liabilities, 'CNY')}</Text><Text>明细与历史收入仅本人可见。小计不代表全部资产，不与持仓、账本或荷包相加。</Text></> : <Text>资产基线保持不变。不同币种逐项展示，不换汇、不跨币种汇总。</Text>}
        <Messages values={model.preview.warnings} />
        {!!model.preview.removedMonths.length && <Messages title="本次滚出覆盖窗口的月份" values={model.preview.removedMonths} />}
        {!!model.preview.files.length && <Messages title="来源文件" values={model.preview.files} />}
        <Divider /><TextInput mode="outlined" label="搜索预览记录" value={model.query} disabled={disabled} onChangeText={query => install({ query, page: 0 })} />
        {rows.rows.map((row, index) => <View key={index} style={[stack, { paddingVertical: density.rowPadding }]}><Text variant="titleSmall">{row.title}</Text><Text>{row.kind} · {row.date}</Text>
          <Text>{formatBaselineMoney(row.amountCents, row.currency)}</Text>{row.gross !== undefined && <Text>支出 {formatBaselineMoney(row.gross, row.currency)} · 退款 {formatBaselineMoney(row.refund ?? null, row.currency)}</Text>}<Text>{row.note}</Text><Divider /></View>)}
        <Pager page={rows.page} pages={rows.pages} count={rows.count} disabled={disabled} onPage={page => install({ page })} />
        <SelectionRow label="我已核对来源日期、变化和共享范围" checked={model.confirmed} disabled={disabled} onPress={() => install({ confirmed: !live.current.confirmed })} />
        <Button mode="contained" contentStyle={styles.touch} disabled={disabled || !model.confirmed} onPress={() => confirm()}>确认保存来源</Button>
      </View></SectionCard>}
      {!model.operation && !model.raw && !model.preview && <SectionCard title="已有操作编号"><View style={stack}><Text>重新登录后可核对同一家庭中本人的历史操作。请选择原更新范围，再输入保存的编号。</Text>
        <TextInput mode="outlined" label="操作编号" accessibilityLabel="操作编号" maxLength={64} autoCapitalize="none" value={model.operationInput} disabled={disabled} onChangeText={operationInput => install({ operationInput })} />
        <Button contentStyle={styles.touch} disabled={disabled || !model.operationInput.trim()} onPress={useOperation}>使用操作编号核对</Button></View></SectionCard>}
    </>}
    <Portal><Dialog visible={show && model.ending && !busy} onDismiss={() => install({ ending: false })}><Dialog.Title>结束本次核对？</Dialog.Title>
      <Dialog.Content><Text>暂未查到历史结果，不能证明未提交；结束后可重新选择文件，核对最新版本再预览。页面不会自动再次提交。</Text><Text selectable style={styles.wrap}>原操作编号：{model.operation?.operationId}</Text></Dialog.Content>
      <Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ ending: false })}>继续核对</Button><Button contentStyle={styles.touch} onPress={endRecovery}>确认结束本次核对</Button></Dialog.Actions>
    </Dialog><Dialog visible={model.leave && !busy} onDismiss={() => install({ leave: false })}><Dialog.Title>{model.operation ? '保留核对编号后返回？' : '放弃未保存的来源？'}</Dialog.Title>
      <Dialog.Content><Text>{model.operation ? '来源内容和预览会清除，原操作编号仍在当前应用内存中。再次进入后只能核对原操作；关闭或刷新应用前，请自行保留编号。' : '当前来源 JSON 和预览只在此页面内存中，返回后需要重新选择或粘贴。'}</Text></Dialog.Content>
      <Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ leave: false })}>继续核对</Button><Button contentStyle={styles.touch} onPress={exit}>{model.operation ? '保留编号并返回' : '放弃并返回'}</Button></Dialog.Actions>
    </Dialog></Portal>
  </View>;
}
function Pager({ page, pages, count, disabled = false, onPage }: { page: number; pages: number; count: number; disabled?: boolean; onPage: (page: number) => void }) {
  return <View style={styles.actions}><Text>{count ? `第 ${page + 1} / ${pages} 页，共 ${count} 项` : '没有匹配的记录'}</Text>
    <Button contentStyle={styles.touch} disabled={disabled || page <= 0} onPress={() => onPage(page - 1)}>上一页</Button><Button contentStyle={styles.touch} disabled={disabled || page + 1 >= pages} onPress={() => onPage(page + 1)}>下一页</Button></View>;
}
function Messages({ values, title }: { values: string[]; title?: string }) {
  const [page, setPage] = useState(0), items = baselinePage(values, '', page, String, 5);
  return values.length ? <View style={{ gap: 8 }}>{title && <Text variant="titleSmall">{title}</Text>}{items.rows.map((value, i) => <Text key={i} style={styles.wrap}>{value}</Text>)}
    {items.pages > 1 && <Pager {...items} onPage={setPage} />}</View> : null;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }, wrap: { flexShrink: 1, ...(Platform.OS === 'web' ? { overflowWrap: 'anywhere' as const } : {}) } });
