import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PlaceDiscarded, PlaceFence, type PlaceSession } from '../lib/places';
import { newKey } from '../lib/trips';
import { checkedRescheduleWrite, clockText, failedRescheduleIntent, impactLabels, impactReason, initialRescheduleDraft, offsetText, pageItems, readRescheduleOperation, readReschedulePreview, readRescheduleReceipt, readRescheduleSnapshot, rebaseRescheduleDraft, reschedulePayload, RescheduleRejected, RescheduleUnverified, snapshotVersion, spanText, type Clocks, type ImpactKind, type Intent, type Issue, type RescheduleDraft, type ReschedulePreview, type RescheduleReceipt, type Snapshot } from '../lib/journeyReschedule';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { journeyId: string; onBack: () => void; onSaved: (result: { journeyId: string; revision: number }) => void };
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const description = (failure: unknown) => failure instanceof Error ? failure.message : '暂时无法核对改期。';
const groups: ImpactKind[] = ['overview', 'destination', 'segment', 'task', 'place', 'shopping'];
export default function JourneyReschedulePanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户调整旅行日期" />;
  if (!/^[a-f0-9]{24}$/.test(props.journeyId)) return <EmptyState title="旅行编号无法核对" action={<Button onPress={props.onBack}>返回旅行</Button>} />;
  return <Workspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef(household); latest.current = household;
  const alive = useRef(false), focus = useRef(false), active = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey));
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [source, setSource] = useState<Snapshot | null>(null), [draft, setDraft] = useState<RescheduleDraft | null>(null), [review, setReview] = useState<Snapshot | null>(null);
  const [preview, setPreview] = useState<ReschedulePreview | null>(null), [pending, setPending] = useState<Intent | null>(null), [receipt, setReceipt] = useState<RescheduleReceipt | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [warningPage, setWarningPage] = useState(0), [issuePage, setIssuePage] = useState(0);
  const [conflict, setConflict] = useState(false), [terminal, setTerminal] = useState(false), [leaving, setLeaving] = useState(false), [pages, setPages] = useState<Partial<Record<ImpactKind, number>>>({});
  const live = useRef({ source, draft, review, preview, pending, receipt }); live.current = { source, draft, review, preview, pending, receipt };
  const setIntent = (intent: Intent | null) => { live.current.pending = intent; setPending(intent); };
  const current = (ticket = epoch.current) => alive.current && focus.current && active.current && foreground.current && connected() && latest.current.online
    && ticket === epoch.current && latest.current.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  const locked = busy || !!pending || !!review || !!receipt || conflict || terminal || !household.online;
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); working.current = false; setBusy(false); setVisible(false); setLeaving(false);
    if (clear) { setSource(null); setDraft(null); setReview(null); setPreview(null); setIssues([]); setIntent(null); setReceipt(null); setNotice(''); }
  }
  function failed(failure: unknown, ticket: number) {
    if (!current(ticket)) return;
    const original = failure instanceof RescheduleUnverified ? failure.reason : failure;
    if (original instanceof PlaceDiscarded && original.message !== 'identity') return;
    if (original instanceof PlaceDiscarded) { conceal(true); setError('登录身份已变化，请重新打开旅行。'); void latest.current.refresh(); return; }
    if (failure instanceof RescheduleUnverified || original instanceof ApiError && [401, 403].includes(original.status)) {
      conceal(); setError('身份或权限暂时无法核对，旅行内容已隐藏。原草稿与操作编号仍留在本次页面。'); void latest.current.refresh(); return;
    }
    if (original instanceof ApiError && [404, 410].includes(original.status) && !live.current.pending) {
      setSource(null); setReview(null); setPreview(null); setTerminal(true); setError('旅行已不可读取。已保存的历史回执不会恢复或重建它。'); return;
    }
    if (original instanceof ApiError && original.status === 409) { setConflict(true); setPreview(null); }
    setError(description(original));
  }
  function guarded<T>(action: (csrf: string) => Promise<T>, ticket: number) { return fence.current.run(action, () => current(ticket)); }
  // Wrapping the action outcome distinguishes an endpoint error from a failed
  // final /me request. Both successful and failed reads remain identity fenced.
  function read<T>(action: () => Promise<T>, ticket: number) { return checkedRescheduleWrite(job => guarded(job, ticket), action, () => undefined); }
  async function fresh(ticket: number) {
    return readRescheduleSnapshot(await read(() => request<unknown>('/journeys/' + props.journeyId + '/reschedule'), ticket), props.journeyId);
  }
  async function reload(ticket: number, forceReview = false) {
    const value = await fresh(ticket); if (!current(ticket)) return;
    if (live.current.receipt) { setSource(value); setTerminal(false); return; }
    if (live.current.source && live.current.draft && (forceReview || snapshotVersion(live.current.source) !== snapshotVersion(value))) {
      setReview(value); setConflict(true); setPreview(null);
    } else { setSource(value); if (!live.current.draft) setDraft(initialRescheduleDraft(value)); }
    setTerminal(false);
  }
  async function job(action: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current; working.current = true; setBusy(true); setError('');
    try { await action(ticket); } catch (failure) { failed(failure, ticket); }
    finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function enter() {
    if (!alive.current || active.current || !focus.current || !foreground.current || !connected() || !latest.current.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; const ticket = epoch.current; working.current = true; setBusy(true);
    void (async () => {
      try { if (live.current.pending) await read(async () => true, ticket); else await reload(ticket); if (current(ticket)) setVisible(true); }
      catch (failure) { failed(failure, ticket); if (current(ticket)) conceal(); }
      finally { if (current(ticket)) { working.current = false; setBusy(false); } }
    })();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focus.current = true; enter(); return () => { focus.current = false; conceal(); }; }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, offline = () => conceal(), online = () => enter();
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function change(patch: Partial<RescheduleDraft>, keepIssues = false) {
    if (!current() || locked || !draft) return;
    setDraft({ ...draft, ...patch }); setPreview(null); if (!keepIssues) setIssues([]); setError(''); setNotice('');
  }
  function select(key: string) {
    if (!draft) return;
    const selectedKeys = draft.selectedKeys.includes(key) ? draft.selectedKeys.filter(item => item !== key) : [...draft.selectedKeys, key];
    change({ selectedKeys, timeOverrides: Object.fromEntries(Object.entries(draft.timeOverrides).filter(([item]) => selectedKeys.includes(item))) });
  }
  function correction(issue: Issue, local: string, offsetMinutes?: number) {
    if (!draft || !issue.key || !issue.field || !draft.selectedKeys.includes(issue.key)) return;
    change({ timeOverrides: { ...draft.timeOverrides, [issue.key]: { ...draft.timeOverrides[issue.key], [issue.field]: { local, ...(offsetMinutes === undefined ? {} : { offsetMinutes }) } } } }, true);
  }
  async function makePreview() {
    if (locked || !source || !draft) return;
    let body; try { body = reschedulePayload(source, draft); } catch (failure) { setError(description(failure)); return; }
    void job(async ticket => {
      const result = readReschedulePreview(await checkedRescheduleWrite(action => guarded(action, ticket), csrf => request<unknown>('/journeys/' + props.journeyId + '/reschedule-preview', { method: 'POST', body: JSON.stringify(body) }, csrf), () => undefined), source, draft);
      if (current(ticket)) { setPreview(result); setIssues(result.blockingIssues); setPages({}); setWarningPage(0); setIssuePage(0); setNotice(result.canApply ? '这里只是预览。确认后才保存改期。' : '请处理下方时间问题，再重新预览。'); }
    });
  }
  async function completed(value: RescheduleReceipt, ticket: number) {
    if (!current(ticket)) return;
    setIntent(null); live.current.receipt = value; setReceipt(value); setPreview(null); setReview(null); setConflict(false);
    setNotice(value.replayed ? '已核对原改期，没有再次平移日期。' : '改期已保存。日历云端结果请在旅行详情继续核对。');
    try { await reload(ticket); } catch (failure) { failed(failure, ticket); }
  }
  async function send(intent: Intent) {
    if (!current() || working.current) return;
    const ticket = epoch.current; working.current = true; setBusy(true); setError(''); setIntent({ ...intent, uncertain: true });
    try {
      const raw = await checkedRescheduleWrite(action => guarded(action, ticket), csrf => request<unknown>('/journeys/apply', { method: 'POST', body: JSON.stringify(intent.body) }, csrf), failure => failure instanceof ApiError ? { status: failure.status, code: failure.code } : undefined);
      const result = readRescheduleReceipt(raw, props.journeyId, intent); await completed(result, ticket);
    } catch (failure) {
      if (!current(ticket)) return;
      const next = failedRescheduleIntent(intent, failure); setIntent(next);
      if (failure instanceof RescheduleUnverified || failure instanceof PlaceDiscarded || failure instanceof ApiError && [401, 403].includes(failure.status)) { failed(failure, ticket); return; }
      if (failure instanceof RescheduleRejected && failure.status === 403) { failed(new ApiError('旅行权限暂时无法核对。', 403), ticket); return; }
      if (next) { setError('保存结果尚未核实，请核对原操作；不会生成新的操作编号。'); }
      else { setPreview(null); setConflict(true); setError('此次请求未保存。原日期与选择仍保留，请读取最新内容并重新核对。'); }
    } finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function confirm() {
    if (locked || !preview?.canApply || !preview.previewToken) return;
    try { void send({ body: Object.freeze({ previewToken: preview.previewToken, idempotencyKey: newKey() }), start: preview.start, end: preview.end, uncertain: false }); }
    catch (failure) { setError(description(failure)); }
  }
  function recover() {
    if (!pending || busy) return;
    const intent = pending;
    void job(async ticket => {
      try { const raw = await read(() => request<unknown>('/journeys/operations/' + intent.body.idempotencyKey), ticket); await completed(readRescheduleOperation(raw, props.journeyId, intent), ticket); }
      catch (failure) {
        if (current(ticket) && failure instanceof ApiError && failure.status === 404 && failure.code === 'operation_not_found') { setError('暂未查到原操作回执。这不能证明尚未保存；可稍后再次核对，或按原操作重试。'); return; }
        throw failure;
      }
    });
  }
  function acceptLatest() {
    if (!current() || busy || !review || !draft || pending) return;
    const next = rebaseRescheduleDraft(draft, review); setSource(review); setDraft(next.draft); setReview(null); setConflict(false); setPreview(null); setError(''); setPages({});
    setIssues([]); setNotice(next.removed.length ? `已保留你的日期输入；${next.removed.length} 项已不可调整，改为保持。请重新预览。` : '已核对当前版本，原输入保留。请重新预览。');
  }
  function exit() { if (busy) return; if (receipt && current()) { conceal(true); props.onSaved({ journeyId: props.journeyId, revision: receipt.revision }); } else { conceal(true); props.onBack(); } }
  function back() { if (busy) return; if (receipt) { exit(); return; } if (pending || draft && source && JSON.stringify(draft) !== JSON.stringify(initialRescheduleDraft(source))) setLeaving(true); else exit(); }
  const pagination = (kind: ImpactKind, page: number, count: number) => count > 1 && <View style={styles.actions}><Button disabled={busy || page === 0} accessibilityLabel={`${impactLabels[kind]}上一页`} onPress={() => setPages(value => ({ ...value, [kind]: page - 1 }))}>上一页</Button><Text>{page + 1} / {count}</Text><Button disabled={busy || page + 1 === count} accessibilityLabel={`${impactLabels[kind]}下一页`} onPress={() => setPages(value => ({ ...value, [kind]: page + 1 }))}>下一页</Button></View>;
  const currentWarnings = preview?.warnings || review?.warnings || source?.warnings || [];
  const warningRows = pageItems(currentWarnings, warningPage), issueRows = pageItems(issues, issuePage, 4);
  const leavingDialog = <Portal><Dialog visible={leaving} dismissable={!busy} onDismiss={() => setLeaving(false)}><Dialog.Title>离开改期页面？</Dialog.Title><Dialog.Content><Text>{pending ? '本次保存结果仍未知。离开不会取消服务器已经收到的请求，请回旅行详情核对，不要直接再提交相同改期。' : '未保存的日期和选择会关闭。'}</Text></Dialog.Content><Dialog.Actions style={styles.actions}><Button onPress={() => setLeaving(false)}>继续核对</Button><Button onPress={exit}>离开并返回旅行</Button></Dialog.Actions></Dialog></Portal>;
  if (!visible) return <View style={styles.page}><ActivityIndicator animating={busy} /><Text>{error || '正在核对旅行与登录身份…'}</Text><Button disabled={busy} onPress={back}>返回旅行</Button><Button disabled={busy || !household.online} onPress={enter}>重新核对改期身份</Button>{leavingDialog}</View>;
  return <View style={styles.page} testID="journey-reschedule-panel">
    <PageHeader title="调整旅行日期" description={source?.items.find(item => item.key === 'trip')?.title} />
    <Button accessibilityLabel="返回旅行" disabled={busy} onPress={back}>返回旅行</Button>
    {!!error && <Text accessibilityRole="alert">{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}{busy && <ActivityIndicator accessibilityLabel="正在核对改期" />}
    {pending && <View testID="journey-reschedule-unknown"><SectionCard title="先核对这次改期"><Text>原内容和操作编号仍保留。查询无回执不代表保存失败；同一操作重试不会重复平移日期。</Text><View style={styles.actions}><Button mode="contained" disabled={busy} onPress={recover}>核对保存结果</Button><Button mode="outlined" disabled={busy} onPress={() => void send(pending)}>按原操作重试</Button></View></SectionCard></View>}
    {receipt && <SectionCard title="改期已保存"><Text>本次已确认：{receipt.reschedule.start} — {receipt.reschedule.end}</Text><Text>变更 {receipt.reschedule.changedKeys.length} 项。回执只证明这次历史操作，不覆盖随后发生的修改。</Text>{source && <Text>当前旅行日期：{source.start} — {source.end} · 版本 {source.revision}</Text>}<Text>云端日历可能仍在排队或需要核对，不代表已同步成功。</Text><Button mode="contained" disabled={busy} accessibilityLabel="返回旅行详情" onPress={exit}>返回旅行详情</Button></SectionCard>}
    {conflict && !pending && !receipt && <SectionCard title="内容已变化，输入仍保留"><Text>重新读取不会直接覆盖你的日期与选择。</Text><Button disabled={busy} onPress={() => void job(ticket => reload(ticket, true))}>读取最新并重新核对</Button></SectionCard>}
    {review && draft && <SectionCard title="核对最新内容"><Text>当前保存：{review.start} — {review.end} · 版本 {review.revision}</Text><Text>你的输入：{draft.start} — {draft.end}</Text><Text>下方清单展示刚读取的内容，日期输入保留。最新版本有 {review.items.filter(row => row.eligible).length} 项可调整；你的 {rebaseRescheduleDraft(draft, review).removed.length} 项旧选择已不可调整。确认后这些项目将保持，其他选择与输入保留。</Text><Button disabled={busy} onPress={acceptLatest}>已核对最新内容</Button></SectionCard>}
    {source && draft && !receipt && <>
      <SectionCard title="新的旅行日期"><Text>原日期：{source.start} — {source.end}</Text><View style={styles.fields}>
        <TextInput mode="outlined" label="新的出发日期" accessibilityLabel="新的出发日期" placeholder="YYYY-MM-DD" value={draft.start} disabled={locked} onChangeText={start => change({ start, timeOverrides: {} })} style={styles.field} />
        <TextInput mode="outlined" label="新的返程日期" accessibilityLabel="新的返程日期" placeholder="YYYY-MM-DD" value={draft.end} disabled={locked} onChangeText={end => change({ end, timeOverrides: {} })} style={styles.field} />
      </View><Text>默认保持关联项目原日期。只调整你明确选择的可用项目，已完成、到访与已预订记录保留。</Text></SectionCard>
      {!preview && <View style={styles.actions}><Button disabled={locked} onPress={() => change({ selectedKeys: source.items.filter(row => row.eligible).map(row => row.key) })}>联动所有可调整项</Button><Button disabled={locked} onPress={() => change({ selectedKeys: [], timeOverrides: {} })}>全部保持原日期</Button></View>}
      <View testID={preview ? 'journey-reschedule-preview' : 'journey-reschedule-selection'} style={styles.page}>
        {groups.map(kind => {
          const rows = (preview?.items || review?.items || source.items).filter(row => row.kind === kind); if (!rows.length) return null;
          const paged = pageItems(rows, pages[kind] || 0);
          return <SectionCard key={kind} title={`${impactLabels[kind]} · ${rows.length} 项`}>
            {paged.items.map((row, index) => <View key={row.key} testID={`reschedule-item-${kind}-${paged.page * 12 + index}`} style={styles.item}>
              {row.eligible && !preview ? <SelectionRow label={row.title} accessibilityLabel={`联动改期：${row.title}`} checked={draft.selectedKeys.includes(row.key)} disabled={locked} onPress={() => select(row.key)} /> : <Text variant="titleSmall">{row.title}</Text>}
              <Text>{spanText(row.before)}{'after' in row ? ' → ' + spanText(row.after as { start: string | null; end: string | null }) : ''}</Text>
              {row.timeBefore && (['start', 'end'] as const).filter(endpoint => row.timeBefore?.[endpoint] || 'timeAfter' in row && (row.timeAfter as Clocks | undefined)?.[endpoint]).map(endpoint => <View key={endpoint} style={styles.item}><Text variant="bodySmall">{endpoint === 'start' ? '开始时刻' : '结束时刻'}</Text><Text>{clockText(row.timeBefore?.[endpoint])}</Text>{'timeAfter' in row && <Text>→ {clockText((row.timeAfter as Clocks | undefined)?.[endpoint])}</Text>}</View>)}
              <Text variant="bodySmall">{row.endExclusive ? '结束日不包含在停留中 · ' : ''}{'selected' in row ? row.selected || kind === 'overview' ? '本次联动' : '保持原日期' : impactReason(row)}</Text><Divider />
            </View>)}{pagination(kind, paged.page, paged.pages)}
          </SectionCard>;
        })}
      </View>
      {!!warningRows.items.length && <SectionCard title={`需要留意 · ${currentWarnings.length} 项`}>{warningRows.items.map((warning, index) => <Text key={index}>{warning.message}</Text>)}{warningRows.pages > 1 && <View style={styles.actions}><Button accessibilityLabel="提示上一页" disabled={busy || warningRows.page === 0} onPress={() => setWarningPage(warningRows.page - 1)}>上一页</Button><Text>{warningRows.page + 1} / {warningRows.pages}</Text><Button accessibilityLabel="提示下一页" disabled={busy || warningRows.page + 1 === warningRows.pages} onPress={() => setWarningPage(warningRows.page + 1)}>下一页</Button></View>}</SectionCard>}
      {issueRows.items.map((issue, index) => <SectionCard key={`${issue.key}:${issue.field}:${index}`} title="这项时间需要核对"><Text accessibilityRole="alert">{issue.message}</Text>{issue.timeZone && <Text>时区：{issue.timeZone}</Text>}
        {issue.key?.startsWith('segment:') && issue.field && draft.selectedKeys.includes(issue.key) && <>
          <TextInput mode="outlined" label={`纠正当地${issue.field === 'start' ? '开始' : '结束'}时间`} accessibilityLabel={`纠正当地${issue.field === 'start' ? '开始' : '结束'}时间：${issue.key}`} value={draft.timeOverrides[issue.key]?.[issue.field]?.local ?? issue.local ?? ''} disabled={locked} onChangeText={local => correction(issue, local)} placeholder="YYYY-MM-DDTHH:mm" />
          {issue.choices && <View accessibilityRole="radiogroup" accessibilityLabel={`选择时区偏移：${issue.key}:${issue.field}`}>{issue.choices.map(choice => <SelectionRow key={choice.offsetMinutes} kind="radio" label={`${offsetText(choice.offsetMinutes)} · ${choice.instant}`} checked={draft.timeOverrides[issue.key!]?.[issue.field!]?.offsetMinutes === choice.offsetMinutes} disabled={locked} onPress={() => correction(issue, draft.timeOverrides[issue.key!]?.[issue.field!]?.local ?? issue.local ?? '', choice.offsetMinutes)} />)}</View>}
        </>}
      </SectionCard>)}
      {issueRows.pages > 1 && <View style={styles.actions}><Button accessibilityLabel="时间问题上一页" disabled={busy || issueRows.page === 0} onPress={() => setIssuePage(issueRows.page - 1)}>上一页</Button><Text>时间问题 {issueRows.page + 1} / {issueRows.pages}</Text><Button accessibilityLabel="时间问题下一页" disabled={busy || issueRows.page + 1 === issueRows.pages} onPress={() => setIssuePage(issueRows.page + 1)}>下一页</Button></View>}
      <View style={styles.actions}>{preview?.canApply ? <Button mode="contained" disabled={locked} onPress={confirm}>确认改期</Button> : <Button mode="contained" disabled={locked} onPress={makePreview}>预览改期</Button>}{preview && <Button disabled={locked} onPress={() => setPreview(null)}>继续修改</Button>}</View>
      <Text variant="bodySmall">采购没有截止日期；本次不修改采购、金额、负责人、共享权限或到访状态。</Text>
    </>}
    {leavingDialog}
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, fields: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, field: { flex: 1, flexBasis: 220, minWidth: 0 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, item: { gap: 8, paddingVertical: 10 } });
