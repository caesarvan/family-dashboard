import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { ApiError } from '../lib/api';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';
import { RoutineDiscarded, RoutineError, RoutineRejected, RoutineFence, checkedRoutineWrite, draftRoutinePayload,
  readRoutineConfirmed, readRoutineContext, readRoutinePreview, readRoutineReceipt, rebaseRoutineDraft, routineAmount, routineContextPath,
  routineDraft, routineOperationPath, routineRequest, type RoutineContext, type RoutineDraft, type RoutineKind, type RoutineOperation,
  type RoutinePayload, type RoutinePending, type RoutinePlan, type RoutinePreview, type RoutineReceipt, type RoutineSchedule, type RoutineSession } from '../lib/routines';

type Props = { kind?: RoutineKind; onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Model = { context: RoutineContext | null; page: number; archived: boolean; selected: string; base: RoutinePlan | null; draft: RoutineDraft | null;
  preview: RoutinePreview | null; unknown: RoutinePending | null; receipt: RoutineReceipt | null; blocked: boolean; reviewed: boolean;
  completion: { planId: string; entityId: string } | null };
const empty = (): Model => ({ context: null, page: 0, archived: false, selected: '', base: null, draft: null, preview: null, unknown: null, receipt: null, blocked: false, reviewed: false, completion: null });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const pending = (m: Model) => !!(m.draft || m.preview || m.unknown || m.completion);
const labels: Record<RoutineOperation, string> = { create: '新建计划', update: '修改规则', pause: '暂停计划', resume: '恢复计划', skip: '跳过本期', archive: '归档计划' };
const statuses: Record<string, string> = { active: '运行中', pending: '等待完成', completed: '本期已完成', missing: '当前事项已删除', paused: '已暂停', archived: '已归档', capacity_blocked: '事项数量已满，等待整理', exhausted: '后续日期已用尽', skipped: '已跳过' };
const frequencyLabels = { daily: '天', weekly: '周', monthly: '个月' };
const scheduleText = (s: RoutineSchedule) => `每 ${s.interval} ${frequencyLabels[s.frequency]} · 从 ${s.anchor} 起`;
const momentText = (v: string) => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(v));

export default function RoutinesPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看例行计划" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  const [query, setQuery] = useState(''), [category, setCategory] = useState<RoutineKind | 'all'>(props.kind ?? 'all'), [discard, setDiscard] = useState<'back' | 'list' | null>(null);
  const alive = useRef(false), active = useRef(false), focused = useRef(false), denied = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), flight = useRef<AbortController | null>(null), fence = useRef(new RoutineFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && !denied.current && ticket === epoch.current
    && latest.current.household.identityKey === props.identityKey && latest.current.household.online && online() && (typeof document === 'undefined' || !document.hidden);
  function notify() { latest.current.props.onPendingChange?.(working.current || pending(live.current)); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); setError(''); setMessage(''); setDiscard(null); working.current = false; setBusy(false);
    if (clear) { live.current = empty(); setModel(live.current); setQuery(''); }
    else { live.current = { ...live.current, preview: null }; setModel(live.current); }
    notify();
  }
  function failed(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof RoutineDiscarded) {
      if (e.message === 'identity') { denied.current = true; conceal(true); setError('身份已变化，请重新打开例行计划。'); void latest.current.household.refresh(); } return;
    }
    if ((e instanceof RoutineError || e instanceof ApiError) && [401, 403].includes(e.status)) {
      conceal(); setError('身份或权限需要重新核对，内容已隐藏。'); void latest.current.household.refresh(); return;
    }
    setError(e instanceof Error ? e.message : '暂时无法读取例行计划。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (e) { failed(e, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, operation: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await routineRequest('/me', signal) as RoutineSession, operation, () => current(ticket));
  async function load(ticket: number, signal: AbortSignal, selection = live.current.selected) {
    const { page, archived } = live.current; let context: RoutineContext, missing = false;
    try { context = readRoutineContext(await guard(ticket, signal, () => routineRequest(routineContextPath(page, archived, selection || undefined), signal)), page, selection || undefined); }
    catch (e) {
      if (!(e instanceof RoutineError) || e.status !== 404 || !selection || !current(ticket)) throw e;
      context = readRoutineContext(await guard(ticket, signal, () => routineRequest(routineContextPath(page, archived), signal)), page); missing = true;
    }
    if (!current(ticket)) return;
    const old = live.current, record = context.plans.find(p => p.id === selection), conflict = !!old.draft && !!old.base && (!record || record.revision !== old.base.revision);
    install({ context, selected: selection, blocked: old.blocked || conflict, reviewed: old.blocked || conflict || !!old.completion });
    setVisible(true); if (missing) setMessage('这项计划当前不存在。旧回执仅用于核对历史，不会重新创建计划。');
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || !foreground.current || denied.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(load);
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; flight.current?.abort(); fence.current.invalidate(); live.current = empty(); latest.current.props.onPendingChange?.(false); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, offline = () => conceal(), connected = () => enter(), hide = () => conceal();
    const show = (event: PageTransitionEvent) => { if (event.persisted) { conceal(); enter(); } };
    const beforeUnload = (event: BeforeUnloadEvent) => { if (working.current || pending(live.current)) { event.preventDefault(); event.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', beforeUnload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', beforeUnload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function change(patch: Partial<RoutineDraft>) {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.draft) return;
    install({ draft: { ...live.current.draft, ...patch }, preview: null, receipt: null }); setError(''); setMessage('');
  }
  function start(plan?: RoutinePlan) {
    if (!current() || working.current || pending(live.current) || plan?.state === 'archived' || !live.current.context) return;
    install({ selected: plan?.id ?? '', base: plan ?? null, draft: routineDraft(plan, live.current.context.today, props.kind ?? (category === 'all' ? 'tasks' : category)), preview: null, receipt: null, blocked: false, reviewed: false }); setError(''); setMessage('');
  }
  async function preview(op?: Exclude<RoutineOperation, 'create' | 'update'>) {
    if (!current() || working.current || live.current.unknown || live.current.completion || live.current.blocked) return;
    let payload: RoutinePayload;
    try {
      const selected = live.current.context?.plans.find(p => p.id === live.current.selected);
      if (op) { if (!selected || selected.state === 'archived') return; payload = { operation: op, planId: selected.id, revision: selected.revision }; }
      else { if (!live.current.draft) return; payload = draftRoutinePayload(live.current.draft, latest.current.household.state?.people ?? [], live.current.base ?? undefined); }
    } catch (e) { setError(e instanceof Error ? e.message : '请核对输入。'); return; }
    await job(async (ticket, signal) => {
      install({ preview: null, receipt: null });
      try { const result = await guard(ticket, signal, async csrf => readRoutinePreview(await routineRequest('/routines/preview', signal, { payload, csrf }), payload));
        if (current(ticket)) install({ preview: result }); }
      catch (e) { if (current(ticket) && e instanceof RoutineError && e.status === 409) install({ blocked: true, reviewed: false }); throw e; }
    });
  }
  async function accepted(receipt: RoutineReceipt, ticket: number, signal: AbortSignal) {
    if (!current(ticket)) return;
    install({ unknown: null, preview: null, draft: null, base: null, blocked: false, reviewed: false, receipt, selected: receipt.planId });
    setMessage('操作已确认。下面的回执是历史结果，当前计划另行读取。');
    await load(ticket, signal, receipt.planId); if (current(ticket)) void latest.current.household.refresh();
  }
  async function confirm(retry = false) {
    if (!current() || working.current || live.current.completion) return;
    const p = live.current.preview;
    const intent: RoutinePending | null = retry ? live.current.unknown : p ? Object.freeze({ previewToken: p.previewToken, operationKey: p.operationKey, operation: p.operation, ...(p.before ? { planId: p.before.id } : {}) }) : null;
    if (!intent || !retry && live.current.unknown) return;
    await job(async (ticket, signal) => {
      try {
        const receipt = await checkedRoutineWrite(operation => guard(ticket, signal, operation), async csrf => {
          install({ unknown: intent });
          return readRoutineConfirmed(await routineRequest('/routines/confirm', signal, { payload: { previewToken: intent.previewToken }, csrf }), intent);
        });
        await accepted(receipt, ticket, signal);
      } catch (e) {
        if (!current(ticket)) return;
        if (e instanceof RoutineRejected && (!retry || e.status === 410 && e.code === 'preview_expired_unapplied')) {
          install({ unknown: null, preview: null, blocked: true, reviewed: false });
          setMessage(e.status === 410 ? '服务器已确认这份过期预览未执行。草稿仍保留，请读最新计划并重新预览。' : '本次确认未执行。请核对最新计划后重新预览。');
        } else if (live.current.unknown) setMessage('确认结果暂不确定。请核对操作记录，或明确重试原请求；不会自动生成新预览。');
        throw e;
      }
    });
  }
  async function recover() {
    const intent = live.current.unknown; if (!intent) return;
    await job(async (ticket, signal) => {
      try { const receipt = await guard(ticket, signal, async () => readRoutineReceipt(await routineRequest(routineOperationPath(intent.operationKey), signal), intent)); await accepted(receipt, ticket, signal); }
      catch (e) { if (current(ticket) && e instanceof RoutineError && e.status === 404 && e.code === 'routine_receipt_not_found') { setMessage('当前尚未查到这次操作记录，不能据此判断未执行。原请求仍保留，可稍后核对或明确重试。'); return; } throw e; }
    });
  }
  function resolve(keep: boolean) {
    if (!current() || working.current || !live.current.reviewed || live.current.unknown) return;
    const record = live.current.context?.plans.find(p => p.id === live.current.selected), old = live.current;
    if (keep && old.base && (!record || record.state === 'archived')) return;
    install({ draft: keep && old.draft ? old.base && record ? rebaseRoutineDraft(old.base, old.draft, record) : old.draft : null,
      base: keep ? record ?? null : null, preview: null, blocked: false, reviewed: false, completion: null });
    setMessage(keep ? '已保留你的修改。请重新预览，再明确确认。' : '已采用刚读取的当前计划。'); setError('');
  }
  async function complete() {
    const plan = live.current.context?.plans.find(p => p.id === live.current.selected), item = plan?.current?.entity;
    if (!current() || working.current || pending(live.current) || !plan || !item || item.done) return;
    await job(async (ticket, signal) => {
      const result = await guard(ticket, signal, async () => {
        // Provider has its own preflight. A failure cannot prove its PATCH was unsent,
        // so recovery reads current state and never repeats this completion blindly.
        install({ completion: { planId: plan.id, entityId: item.id }, reviewed: false });
        return latest.current.household.mutate<{ ok: boolean }>('/items/' + plan.kind + '/' + item.id, 'PATCH', { done: true, revision: item.revision });
      });
      if (!current(ticket)) return;
      if (result?.ok !== true) throw new RoutineError('完成状态的返回无法核对，请读取当前计划。');
      install({ completion: null }); setMessage('当前事项已完成。后继由后台调度生成，请按下方真实状态核对。');
      await load(ticket, signal); if (current(ticket)) void latest.current.household.refresh();
    });
  }
  function leave(where: 'back' | 'list') {
    if (working.current || live.current.unknown || live.current.completion) return;
    if (pending(live.current)) { setDiscard(where); return; } finishLeave(where);
  }
  function finishLeave(where: 'back' | 'list') {
    if (working.current || live.current.unknown || live.current.completion) return;
    install({ draft: null, base: null, preview: null, receipt: null, selected: '', blocked: false, reviewed: false }); setDiscard(null); setMessage(''); setError('');
    if (where === 'back') { latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
  }
  function listPage(page: number, archived = live.current.archived) {
    if (!current() || working.current || pending(live.current)) return;
    install({ page, archived, selected: '', receipt: null }); void job(load);
  }
  const locked = busy || !visible || !!model.unknown || !!model.completion || model.blocked;
  const selected = model.context?.plans.find(p => p.id === model.selected), people = household.state?.people ?? [];
  const owner = (id: string) => id === 'shared' ? '共同负责' : people.find(p => p.id === id)?.name ?? '家庭成员';
  const stack = { gap: density.sectionGap }, small = { gap: density.tripGap };
  const button = (title: string, action: () => void, disabled = locked, primary = false) => <Button accessibilityLabel={title} contentStyle={styles.touch} mode={primary ? 'contained' : 'outlined'} disabled={disabled} onPress={action}>{title}</Button>;
  const field = (name: string, value: string, patch: (value: string) => Partial<RoutineDraft>, multiline = false) => <TextInput label={name} accessibilityLabel={name} mode="outlined" value={value} disabled={locked}
    multiline={multiline} onChangeText={value => change(patch(value))} outlineStyle={{ borderRadius: 8 }} style={{ backgroundColor: theme.colors.surface }} />;
  const rule = (value: Pick<RoutinePlan, 'kind' | 'template' | 'schedule' | 'state'>) => <View style={small}>
    <Text variant="titleSmall">{value.template.title}</Text><Text>{value.kind === 'tasks' ? '待办' : '采购'} · {owner(value.template.owner)} · {statuses[value.state]}</Text>
    <Text>{scheduleText(value.schedule)}</Text>{!!value.template.note && <Text>{value.template.note}</Text>}
    {value.kind === 'shopping' && <Text>每期数量：{value.template.quantity} · 预算：{value.template.budget == null ? '待核对' : '¥ ' + routineAmount(value.template.budget)}</Text>}
  </View>;
  return <View testID="routines-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="家庭例行计划" description="为重复的家务和采购定好节奏。全家共享，确认后才生成事项。"
      action={button('返回例行计划入口', () => leave('back'), busy || !!model.unknown || !!model.completion)} />
    {!!message && visible && <Text testID="routines-message">{message}</Text>}{!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对例行计划" />}
    {!visible ? <EmptyState title="例行计划已隐藏" description="核对当前身份后再显示；离线或后台期间草稿只保留在内存。"
      action={button('重新读取例行计划', () => { if (active.current) void job(load); else enter(); }, busy || !online())} /> : <>
      {model.unknown && <SectionCard title="先核对操作结果"><View testID="routines-unknown" style={stack}>
        <Text>这次{labels[model.unknown.operation]}可能已经完成。原预览和操作编号仍保留，当前未查到记录也不代表未执行。</Text>
        {button('核对例行操作结果', () => void recover(), busy, true)}{button('按原请求重试', () => void confirm(true), busy)}
      </View></SectionCard>}
      {model.completion && <SectionCard title="核对当前事项"><View style={stack}>
        <Text>完成状态可能已经保存。只读取当前计划，不会自动重复勾选或假定下一期已经生成。</Text>
        {button('核对当前事项状态', () => void job(load), busy)}
        {model.reviewed && button('已核对当前事项', () => resolve(false), busy)}
      </View></SectionCard>}
      {model.receipt && <SectionCard title="操作已确认"><View testID="routines-receipt" style={small}>
        <Text>{labels[model.receipt.operation]} · {momentText(model.receipt.createdAt)}</Text>
        <Text>{model.receipt.generated ? `当时生成了一项${model.receipt.generated.kind === 'tasks' ? '待办' : '采购'}，期次日期 ${model.receipt.generated.scheduledOn}。` : '这次操作没有生成新事项。'}</Text>
        <Text>这是历史回执。下方重新读取的计划才表示当前状态，不会恢复后来删除或修改的内容。</Text>
        {button('读取当前计划', () => void job(load), busy)}
      </View></SectionCard>}
      {model.blocked && !model.unknown && <SectionCard title="计划已变化，请重新核对"><View testID="routines-conflict" style={stack}>
        <Text>草稿仍保留。先读取当前规则，再决定保留修改还是采用当前内容。</Text>
        {button('读取最新计划', () => void job(load), busy)}
        {model.reviewed && <>{selected ? rule(selected) : <Text>当前计划不存在，或新建计划需要重新核对容量。</Text>}
          {button('采用当前计划', () => resolve(false), busy)}
          {!!model.draft && button('保留草稿重新核对', () => resolve(true), busy || !!model.base && (!selected || selected.state === 'archived'))}</>}
      </View></SectionCard>}
      {model.draft && !model.unknown && <SectionCard title={model.base ? '编辑例行计划' : '新建例行计划'}><View testID="routine-editor" style={stack}>
        {!model.base && <View accessibilityRole="radiogroup" accessibilityLabel="计划类型">{(['tasks', 'shopping'] as const).map(k => <SelectionRow key={k} kind="radio" label={k === 'tasks' ? '待办计划' : '采购计划'} checked={model.draft!.kind === k} disabled={locked} onPress={() => change({ kind: k })} />)}</View>}
        {field('例行计划名称', model.draft.title, title => ({ title }))}
        <Text variant="titleSmall">负责人</Text><View accessibilityRole="radiogroup" accessibilityLabel="例行计划负责人">
          {[{ id: 'shared', name: '共同负责' }, ...people].map(p => <SelectionRow key={p.id} kind="radio" label={p.name} accessibilityLabel={'例行负责人：' + p.name} checked={model.draft!.owner === p.id} disabled={locked} onPress={() => change({ owner: p.id })} />)}
        </View>
        <Text variant="titleSmall">重复节奏</Text><View accessibilityRole="radiogroup" accessibilityLabel="重复周期">
          {(['daily', 'weekly', 'monthly'] as const).map(f => <SelectionRow key={f} kind="radio" label={{ daily: '按天', weekly: '按周', monthly: '按月' }[f]} checked={model.draft!.frequency === f} disabled={locked} onPress={() => change({ frequency: f })} />)}
        </View><View style={styles.columns}><View style={styles.column}>{field('每隔多少期', model.draft.interval, interval => ({ interval }))}</View><View style={styles.column}>{field('起始日期', model.draft.anchor, anchor => ({ anchor }))}</View></View>
        <Text>日期格式 YYYY-MM-DD，按上海日期计算。过去的日期不会补建历史事项。{model.draft.frequency === 'monthly' ? '短月取月底，下一期仍按原起始日计算。' : ''}</Text>
        {model.draft.kind === 'shopping' && <>{field('采购数量', model.draft.quantity, quantity => ({ quantity }))}{field('每期预算（元）', model.draft.budget, budget => ({ budget }))}<Text>预算未知请留空；0 元表示已明确为零。预算不代表付款。</Text></>}
        {field('例行计划备注', model.draft.note, note => ({ note }), true)}
        {button('预览例行计划', () => void preview(), locked, true)}
      </View></SectionCard>}
      {model.preview && !model.unknown && <SectionCard title="确认前，请核对变化"><View testID="routine-preview" style={stack}>
        <Text variant="titleSmall">{labels[model.preview.operation]}</Text>
        {model.preview.before && <><Text variant="titleSmall">原规则</Text>{rule(model.preview.before)}<Text>原后续日期：{model.preview.before.nextDates.join('、') || '无'}</Text></>}
        <Text variant="titleSmall">确认后的规则</Text>{rule(model.preview.after)}
        <Text variant="titleSmall">接下来三期</Text><Text>{model.preview.nextDates.length ? model.preview.nextDates.join('、') : '没有可用的后续日期'}</Text>
        <Text>{model.preview.willGenerate ? `确认后生成一项${model.preview.willGenerate.kind === 'tasks' ? '待办' : '采购'}，期次日期 ${model.preview.willGenerate.scheduledOn}。` : '这次操作不生成新事项。'}</Text>
        {model.preview.warnings.map((w, i) => <Text key={i}>{w}</Text>)}
        {button('确认例行计划操作', () => void confirm(), locked, true)}{button('返回修改', () => install({ preview: null }))}
      </View></SectionCard>}
      {!model.draft && !model.preview && selected && <SectionCard title={selected.template.title}><View testID="routine-detail" style={stack}>
        {rule(selected)}<Text>当前状态：{statuses[selected.status]}</Text>
        <Text variant="titleSmall">当前事项</Text>{selected.current ? <View style={small}>
          <Text>期次日期：{selected.current.scheduledOn} · {statuses[selected.current.state]}</Text>
          {selected.current.entity ? <><Text>{selected.current.entity.title}</Text><Text>{owner(selected.current.entity.owner)}{selected.current.entity.due ? ' · 截止 ' + selected.current.entity.due : ''}</Text>
            {!!selected.current.entity.note && <Text>{selected.current.entity.note}</Text>}
            {!selected.current.entity.done && button(selected.kind === 'tasks' ? '完成当前待办' : '标记当前采购已买到', () => void complete())}</> : <Text>当前事项已删除，不会自动复活。</Text>}
        </View> : <Text>尚无当前事项。</Text>}
        <Text>后续理论日期：{selected.nextDates.join('、') || '无'}。暂停或归档时不会自动生成。</Text>
        {selected.state !== 'archived' && <View style={styles.row}>{button('编辑例行计划', () => start(selected))}
          {button(selected.state === 'active' ? '暂停计划' : '恢复计划', () => void preview(selected.state === 'active' ? 'pause' : 'resume'))}
          {selected.state === 'active' && button('跳过本期并保留事项', () => void preview('skip'))}{button('归档计划', () => void preview('archive'))}</View>}
        <Text variant="titleSmall">最近十期</Text>{selected.history.map(h => <View key={h.index} style={small}><Text>{h.scheduledOn} · {statuses[h.state]} · {h.entity?.title ?? '事项已删除'}</Text></View>)}
        {button('刷新当前计划', () => void job(load), busy)}
      </View></SectionCard>}
      {(model.selected || model.draft || model.preview || model.receipt) && button('返回例行计划列表', () => leave('list'), busy || !!model.unknown || !!model.completion)}
      {!model.selected && !model.draft && !model.preview && !model.unknown && <View testID="routines-list" style={stack}>
        <View style={styles.row}>{button('新建例行计划', () => start(), locked, true)}{button('刷新例行计划', () => void job(load), busy)}</View>
        <View accessibilityRole="radiogroup" accessibilityLabel="筛选计划类型">{(['all', 'tasks', 'shopping'] as const).map(k => <SelectionRow key={k} kind="radio" label={{ all: '全部计划', tasks: '只看待办', shopping: '只看采购' }[k]} checked={category === k} disabled={busy} onPress={() => setCategory(k)} />)}</View>
        <SelectionRow label="包括已归档计划" checked={model.archived} disabled={busy} onPress={() => listPage(0, !model.archived)} />
        <TextInput mode="outlined" label="搜索当前页计划" accessibilityLabel="搜索当前页计划" value={query} onChangeText={setQuery} disabled={busy} style={{ backgroundColor: theme.colors.surface }} />
        {model.context?.plans.filter(p => (category === 'all' || p.kind === category) && p.template.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(p => <SectionCard key={p.id} title={p.template.title}><View testID={'routine-' + p.id} style={small}>
          <Text>{p.kind === 'tasks' ? '待办' : '采购'} · {owner(p.template.owner)} · {statuses[p.status]}</Text><Text>{scheduleText(p.schedule)}</Text>
          {p.current && <Text>当前期：{p.current.scheduledOn}</Text>}
          <Button accessibilityLabel={'查看计划：' + p.template.title} contentStyle={styles.touch} mode="outlined" disabled={busy}
            onPress={() => { install({ selected: p.id, receipt: null }); void job(load); }}>查看计划</Button>
        </View></SectionCard>)}
        {!model.context?.plans.some(p => (category === 'all' || p.kind === category) && p.template.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && <EmptyState title="当前页没有符合条件的计划" description="可以调整筛选、查看下一页，或新建一项例行计划。" />}
        <View style={styles.row}>{button('上一页计划', () => listPage(model.page - 1), busy || model.page === 0)}<Text>第 {model.page + 1} 页 · 每页最多 40 项</Text>{button('下一页计划', () => listPage(model.page + 1), busy || !model.context?.pageInfo.more)}</View>
      </View>}
    </>}
    <Portal><Dialog visible={visible && !!discard && !busy && !model.unknown && !model.completion} onDismiss={() => setDiscard(null)}><Dialog.Title>放弃未保存的修改？</Dialog.Title>
      <Dialog.Content><Text>只放弃本页草稿和未确认的预览，服务器计划保持原样。</Text></Dialog.Content><Dialog.Actions>
        {button('继续编辑', () => setDiscard(null), false)}{button('确认放弃例行修改', () => { if (discard) finishLeave(discard); }, false)}
      </Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 }, columns: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 }, column: { flexGrow: 1, flexBasis: 220, minWidth: 0 } });
