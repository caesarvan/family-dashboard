import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { readMembers } from '../lib/householdMembers';
import { identitySignature, MembershipDiscarded, MembershipError, MembershipFence,
  membershipRequest, newMembershipRequestId, readAccount, readMembershipIdentity, readOperation, record, boundedText, hexId,
  type MembershipIdentity, type MembershipRequest } from '../lib/personalAccounts';
import { canStartNewMembershipOperation } from '../lib/personalAccounts';
import { acceptedMembershipTransition, operationBelongsTo, readCurrentHousehold, readHouseholds, readMembershipResult, readMembershipWriteReply, validateResultTarget, roleLabel,
  type Households, type MembershipAction, type MembershipHandle, type MembershipResult } from '../lib/memberships';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';

export type MembershipPanelProps = { onBack: () => void; onPendingChange?: (pending: boolean) => void };
export type PersonalAccountPanelProps = MembershipPanelProps & { onIdentityChanged?: () => void | Promise<void> };
export type MembershipJob = { identity: MembershipIdentity; signal: AbortSignal; current: () => boolean };
type Job = MembershipJob;
export type MembershipCommand = { action: MembershipAction; scope: 'account' | 'member'; path: string;
  body: Record<string, unknown>; targetId?: string; login?: string };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
export const membershipStyles = StyleSheet.create({ stack: { gap: 14 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  touch: { minHeight: 44 }, wrap: { flexShrink: 1, ...(Platform.OS === 'web' ? { overflowWrap: 'anywhere' as const } : {}) } });
export function MembershipButton({ label, onPress, disabled = false, primary = false }: { label: string; onPress: () => void; disabled?: boolean; primary?: boolean }) {
  return <Button accessibilityLabel={label} mode={primary ? 'contained' : 'outlined'} contentStyle={membershipStyles.touch}
    labelStyle={{ flexShrink: 1 }} disabled={disabled} onPress={onPress}>{label}</Button>;
}

/** One controller is shared by the three panels; only opaque operation handles survive hiding. */
export function useMembershipPanel(props: MembershipPanelProps, dirty: boolean, clear: () => void,
  load: (job: Job) => Promise<() => void>) {
  const household = useHousehold();
  const latest = useRef({ props, dirty, clear, load, household }); latest.current = { props, dirty, clear, load, household };
  const [identity, setIdentity] = useState<MembershipIdentity | null>(null), identityRef = useRef<MembershipIdentity | null>(null);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  const [handle, setHandle] = useState<MembershipHandle | null>(null), handleRef = useRef<MembershipHandle | null>(null);
  const alive = useRef(false), active = useRef(false), focus = useRef(false), epoch = useRef(0), working = useRef(false), flight = useRef<AbortController | null>(null);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const windowFocus = useRef(typeof document === 'undefined' || document.hasFocus());
  const current = (e = epoch.current) => alive.current && active.current && focus.current && foreground.current && windowFocus.current
    && e === epoch.current && online() && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || latest.current.dirty || !!handleRef.current;
  const notify = () => latest.current.props.onPendingChange?.(pending());
  function saveHandle(h: MembershipHandle | null) { handleRef.current = h; setHandle(h); notify(); }
  function conceal(identityChanged = false) {
    active.current = false; ++epoch.current; flight.current?.abort(); flight.current = null; working.current = false;
    setBusy(false); setVisible(false); setIdentity(null); latest.current.clear(); setMessage(''); setError('');
    if (identityChanged) { identityRef.current = null; saveHandle(null); }
    else if (handleRef.current?.operation?.result && 'invitation' in handleRef.current.operation.result) {
      const h = handleRef.current; saveHandle({ ...h, operation: { ...h.operation!, result: { ...h.operation!.result as { invitation: import('../lib/memberships').Invitation }, token: null } } });
    }
    notify();
  }
  function installIdentity(value: MembershipIdentity) { identityRef.current = value; setIdentity(value); }
  async function run(action: (job: Job) => Promise<void>, bootstrap = false) {
    if (!current() || working.current) return;
    const e = epoch.current, controller = new AbortController(); flight.current = controller; working.current = true; setBusy(true); setError(''); notify();
    const valid = () => current(e);
    try {
      const before = await readMembershipIdentity(controller.signal); if (!valid()) return;
      if (!bootstrap && identityRef.current && identitySignature(before) !== identitySignature(identityRef.current)) throw new MembershipDiscarded('identity');
      if (bootstrap && identityRef.current && identitySignature(before) !== identitySignature(identityRef.current)) {
        latest.current.clear(); if (handleRef.current && !operationBelongsTo(handleRef.current, before)) saveHandle(null);
      }
      installIdentity(before); await action({ identity: before, signal: controller.signal, current: valid });
    } catch (e) {
      if (!valid()) return;
      if (e instanceof MembershipDiscarded) { if (e.message === 'identity') { conceal(true); void latest.current.household.refresh(); } }
      else { setError(e instanceof Error ? e.message : '暂时无法完成核对。');
        if (e instanceof MembershipError && [401, 403].includes(e.status)) { latest.current.clear(); setVisible(false); } }
    } finally { if (flight.current === controller) flight.current = null; if (valid()) { working.current = false; setBusy(false); notify(); } }
  }
  async function checked<T>(job: Job, action: () => Promise<T>) {
    return new MembershipFence(identitySignature(job.identity)).run(() => readMembershipIdentity(job.signal), action, job.current);
  }
  async function refreshJob(job: Job) {
    if (handleRef.current && !operationBelongsTo(handleRef.current, job.identity)) {
      // Anonymous registration keeps the original handle in this mounted browser until explicit login.
      if (!(handleRef.current.action === 'register' && !job.identity.account.account)) saveHandle(null);
    }
    const install = await checked(job, async () => !handleRef.current ? latest.current.load(job) : () => {});
    if (job.current()) { install(); setVisible(true); }
  }
  function refresh() { if (active.current) void run(refreshJob, true); else enter(); }
  function enter() { if (active.current || !alive.current || !focus.current || !foreground.current || !windowFocus.current || !online()
    || typeof document !== 'undefined' && document.hidden) return; active.current = true; void run(refreshJob, true); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; ++epoch.current; flight.current?.abort(); handleRef.current = null; latest.current.props.onPendingChange?.(false); }; }, []);
  useFocusEffect(useCallback(() => { focus.current = true; enter(); return () => { focus.current = false; conceal(); }; }, []));
  useEffect(() => { notify(); }, [dirty]);
  const priorProvider = useRef(household.identityKey);
  useEffect(() => { if (priorProvider.current !== household.identityKey) { priorProvider.current = household.identityKey; conceal(); enter(); } }, [household.identityKey]);
  useEffect(() => {
    const visibility = () => document.hidden ? conceal() : enter(), blur = () => { windowFocus.current = false; conceal(); }, refocus = () => { windowFocus.current = true; enter(); };
    const hide = () => conceal(), show = () => enter(), unload = (e: BeforeUnloadEvent) => { if (pending()) { e.preventDefault(); e.returnValue = ''; } };
    const app = AppState.addEventListener('change', state => { foreground.current = state === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', refocus); window.addEventListener('offline', hide);
      window.addEventListener('online', show); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', refocus); window.removeEventListener('offline', hide);
        window.removeEventListener('online', show); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  async function write(command: MembershipCommand, onComplete?: (result: MembershipResult) => void | Promise<void>) {
    if (handleRef.current || !visible) return;
    await run(async job => {
      const user = job.identity.member.user;
      if (command.scope === 'member' && (user?.role !== 'member' || !job.identity.member.csrf)) throw new MembershipError('请先登录这个家庭。');
      const requestId = newMembershipRequestId(), h: MembershipHandle = { requestId, action: command.action, scope: ['link', 'leave'].includes(command.action) ? 'account' : command.scope,
        accountId: job.identity.account.account?.id || null, login: command.login || job.identity.account.account?.login || null,
        householdId: user?.householdId || null, memberId: user?.id || null, targetId: command.targetId, operation: null,
        ...(['invite', 'revoke', 'remove'].includes(command.action) ? { retry: { path: command.path, body: { ...command.body, requestId } } } : {}) };
      // Store the handle before sending. Passwords and invitation tickets never enter it.
      saveHandle(h); setMessage('正在提交，请稍候。');
      const options: MembershipRequest = { method: 'POST', payload: { ...command.body, requestId },
        csrf: command.scope === 'account' ? job.identity.account.csrf : job.identity.member.csrf!,
        ...(['link', 'leave'].includes(command.action) ? { accountCsrf: job.identity.account.csrf } : {}) };
      let raw: unknown;
      try { raw = await membershipRequest(command.path, job.signal, options); }
      catch (e) {
        const after = await readMembershipIdentity(job.signal);
        if (!job.current() || handleRef.current !== h) return;
        if (identitySignature(after) !== identitySignature(job.identity)) { conceal(); return; }
        if (e instanceof MembershipError && [400, 403, 404, 409, 415, 422, 429].includes(e.status)) {
          if (e.status === 409) { const install = await checked(job, () => latest.current.load(job)); if (!job.current() || handleRef.current !== h) return; install(); }
          saveHandle(null); setMessage('请求已被拒绝。请核对当前状态，再确认操作。');
        }
        throw e;
      }
      const operation = readMembershipWriteReply(h, raw), result = operation.result;
      const after = await readMembershipIdentity(job.signal); if (!job.current() || handleRef.current !== h) return;
      if (operation.state !== 'completed' || !result) {
        if (identitySignature(job.identity) !== identitySignature(after)) throw new MembershipDiscarded('identity');
        saveHandle({ ...h, operation }); latest.current.clear(); setVisible(true);
        setMessage(operation.state === 'not_committed' ? '已确认原操作未提交，可以结束核对后重新选择。' : '原操作仍待核对，不会重复提交。'); return;
      }
      if (!acceptedMembershipTransition(job.identity, after, command.action, result)) throw new MembershipDiscarded('identity');
      installIdentity(after); latest.current.clear();
      const completed = { ...h, operation }; saveHandle(completed);
      setVisible(true); setMessage('操作已完成。请读取当前状态后继续。');
      if (onComplete) await onComplete(result);
    });
  }
  async function review(resume = false) {
    const h = handleRef.current; if (!h) return;
    await run(async job => {
      if (!operationBelongsTo(h, job.identity) && !(h.action === 'register' && !job.identity.account.account)) throw new MembershipDiscarded('identity');
      if (resume && (!job.identity.account.account || h.scope !== 'account')) return;
      const base = h.scope === 'account' ? '/account/operations/' : '/membership-operations/';
      const op = await checked(job, async () => readOperation(await membershipRequest(base + h.requestId + (resume ? '/resume' : ''), job.signal,
        resume ? { method: 'POST', csrf: job.identity.account.csrf, payload: {} } : {}), h.requestId,
        value => validateResultTarget(h, readMembershipResult(h.action, value, true))));
      if (!job.current() || handleRef.current !== h) return; saveHandle({ ...h, operation: op }); setVisible(true);
      setMessage(op.state === 'completed' ? '已查到原操作回执。请读取当前状态。' : op.state === 'not_committed' ? '已确认原操作未提交，可以结束核对后重新选择。'
        : op.state === 'pending' ? '操作仍待核对，可明确继续核对。' : '暂未查到回执，不能据此确认未提交。');
    });
  }
  async function finish(onComplete?: (result: MembershipResult) => void | Promise<void>) {
    const h = handleRef.current; if (!h?.operation || !['completed', 'not_committed'].includes(h.operation.state || '')) return;
    await run(async job => {
      if (!operationBelongsTo(h, job.identity) && !(['logout', 'register'].includes(h.action) && !job.identity.account.account
        && (h.action === 'logout' || h.operation?.state === 'not_committed'))) throw new MembershipDiscarded('identity');
      const install = await checked(job, () => latest.current.load(job)); if (!job.current() || handleRef.current !== h) return; install();
      if (h.operation?.state === 'completed' && h.operation.result && onComplete) await onComplete(h.operation.result);
      if (!job.current() || handleRef.current !== h) return; saveHandle(null); setVisible(true);
      setMessage(h.action === 'invite' && h.operation?.result && 'invitation' in h.operation.result && !h.operation.result.token
        ? '已读取当前状态。原邀请码不能再次显示，需要新邀请码时请先撤销旧邀请。' : '已读取当前状态。');
    });
  }
  async function retryOriginal() {
    const h = handleRef.current; if (!h?.retry || h.operation?.state === 'completed') return;
    await run(async job => {
      if (!operationBelongsTo(h, job.identity)) throw new MembershipDiscarded('identity');
      const result = await checked(job, async () => validateResultTarget(h, readMembershipResult(h.action,
        await membershipRequest(h.retry!.path, job.signal, { method: 'POST', csrf: job.identity.member.csrf!, payload: h.retry!.body }))));
      if (!job.current() || handleRef.current !== h) return;
      latest.current.clear(); saveHandle({ ...h, operation: { requestId: h.requestId, found: true, state: 'completed', result } });
      setMessage('已取得原操作结果，请读取当前状态。');
    });
  }
  async function authenticate(login: string, password: string, afterLogin?: () => void | Promise<void>) {
    await run(async job => {
      const account = readAccount(record(await membershipRequest('/account/login', job.signal, { method: 'POST', csrf: job.identity.account.csrf, payload: { login, password } })).account);
      const after = await readMembershipIdentity(job.signal); if (!job.current()) return;
      if (account.login !== login || !acceptedMembershipTransition(job.identity, after, 'login', { account })) throw new MembershipDiscarded('identity');
      latest.current.clear(); installIdentity(after);
      const install = await checked({ ...job, identity: after }, () => latest.current.load({ ...job, identity: after }));
      if (!job.current()) return; install(); setVisible(true); setMessage('已登录个人账户。请重新核对邀请或原操作。'); await afterLogin?.();
    });
  }
  function later() {
    if (!current() || working.current || !handleRef.current) return;
    latest.current.clear(); saveHandle(null); latest.current.props.onPendingChange?.(false); latest.current.props.onBack();
  }
  async function history(requestId: string, action: MembershipAction, scope: 'member' | 'account') {
    if (handleRef.current) return;
    await run(async job => {
      hexId(requestId);
      const op = await checked(job, async () => readOperation(await membershipRequest((scope === 'account' ? '/account/operations/' : '/membership-operations/') + requestId, job.signal), requestId,
        result => readMembershipResult(action, result, true)));
      if (!job.current()) return;
      const user = job.identity.member.user, result = op.result;
      const targetId = result && 'invitation' in result ? result.invitation.id : result && 'memberId' in result
        ? action === 'switch' || action === 'accept' ? result.householdId : result.memberId : undefined;
      latest.current.clear(); saveHandle({ requestId, action, scope, historical: true, accountId: result && 'account' in result ? result.account.id : job.identity.account.account?.id || null,
        login: result && 'account' in result ? result.account.login : job.identity.account.account?.login || null, householdId: user?.householdId || null, memberId: user?.id || null, targetId, operation: op });
      setVisible(true); setMessage(op.state === 'completed' ? '已查到原回执，请读取当前状态。' : '原操作尚未确认，不会自动重新提交。');
    });
  }
  return { identity, visible, busy, error, message, handle, locked: busy || !!handle, run, checked, write, review, retryOriginal, finish, refresh, authenticate,
    history, later, setMessage, setError, installIdentity, current, back: () => { if (!pending()) latest.current.props.onBack(); } };
}

export type MembershipController = ReturnType<typeof useMembershipPanel>;
export function MembershipFrame({ title, testID, panel, children, onCompleted, recovery }: { title: string; testID: string; panel: MembershipController;
  children: React.ReactNode; recovery?: React.ReactNode; onCompleted?: (result: MembershipResult) => void | Promise<void> }) {
  const theme = useTheme(), density = useDisplayDensity(), op = panel.handle?.operation;
  const [historyId, setHistoryId] = useState(''), [historyAction, setHistoryAction] = useState<MembershipAction>('accept');
  const [showHistory, setShowHistory] = useState(false);
  useEffect(() => { if (!panel.visible) setHistoryId(''); }, [panel.visible]);
  return <View testID={testID} style={{ gap: density.screenGap }}>
    <PageHeader title={title} action={<MembershipButton label="返回" onPress={panel.back} disabled={panel.locked} />} />
    {panel.busy && <ActivityIndicator accessibilityLabel="正在核对账户与家庭" />}
    {!!panel.error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{panel.error}</Text>}
    {!panel.visible ? <><EmptyState title="信息已隐藏" description="回到前台并联网后，重新核对身份。"
      action={<MembershipButton label="重新读取" onPress={panel.refresh} disabled={panel.busy || !online()} />} />
      {panel.handle && <MembershipButton label="稍后核对" onPress={panel.later} disabled={panel.busy} />}</> : <>
      {!!panel.message && <Text>{panel.message}</Text>}
      {panel.handle && <SectionCard title="核对原操作"><View testID="membership-operation" style={membershipStyles.stack}>
        <Text>原操作编号</Text><Text selectable style={membershipStyles.wrap}>{panel.handle.requestId}</Text>
        <Text>请求不会自动重复发送。回执只说明原操作结果，当前家庭状态需要重新读取。</Text>
        <MembershipButton label="查询原操作" onPress={() => void panel.review()} disabled={panel.busy} />
        {panel.handle.retry && op?.state !== 'completed' && <MembershipButton label="用原操作重试" onPress={() => void panel.retryOriginal()} disabled={panel.busy} />}
        {panel.handle.scope === 'account' && op?.state === 'pending' && <MembershipButton label="继续核对原操作" onPress={() => void panel.review(true)} disabled={panel.busy} />}
        {(op?.state === 'completed' || canStartNewMembershipOperation(op || null)) && <MembershipButton label={op?.state === 'completed' ? '读取当前状态' : '结束核对，重新选择'} onPress={() => void panel.finish(onCompleted)} disabled={panel.busy} />}
        {recovery}
        <Text>请先保存上方编号。稍后核对只离开本页，不表示操作被取消；之后可按原编号查询。</Text>
        <MembershipButton label="稍后核对" disabled={panel.busy} onPress={panel.later} />
      </View></SectionCard>}
      {!panel.handle && <>{children}<MembershipButton label="按编号查询原操作" disabled={panel.busy} onPress={() => setShowHistory(!showHistory)} />
        {showHistory && <SectionCard title="按编号查询原操作"><View style={membershipStyles.stack}>
        <TextInput mode="outlined" label="原操作编号" accessibilityLabel="原操作编号" value={historyId} onChangeText={setHistoryId} disabled={panel.busy} maxLength={32} autoCapitalize="none" />
        <View style={membershipStyles.actions}>{([['register', '创建账户'], ['logout', '退出账户'], ['link', '绑定身份'], ['switch', '切换家庭'], ['accept', '加入家庭'], ['leave', '退出家庭'], ['invite', '创建邀请'], ['revoke', '撤销邀请'], ['remove', '移除成员']] as const).map(([action, label]) =>
          <MembershipButton key={action} label={label} primary={historyAction === action} disabled={panel.busy} onPress={() => setHistoryAction(action)} />)}</View>
        <MembershipButton label="查询原操作编号" disabled={panel.busy || !/^[a-f0-9]{32}$/.test(historyId)} onPress={() => void panel.history(historyId, historyAction, ['invite', 'revoke', 'remove'].includes(historyAction) ? 'member' : 'account')} />
      </View></SectionCard>}</>}
    </>}
  </View>;
}

export default function PersonalAccountPanel(props: PersonalAccountPanelProps) {
  const [login, setLogin] = useState(''), [password, setPassword] = useState(''), [memberPassword, setMemberPassword] = useState('');
  const [eligibility, setEligibility] = useState(''), [households, setHouseholds] = useState<Households | null>(null);
  const [bindingLabel, setBindingLabel] = useState('');
  const [choice, setChoice] = useState<MembershipCommand | null>(null);
  const clear = () => { setLogin(''); setPassword(''); setMemberPassword(''); setEligibility(''); setHouseholds(null); setChoice(null); setBindingLabel(''); };
  const load = async (job: Job) => {
    let label = ''; const user = job.identity.member.user;
    if (user?.role === 'member') {
      const home = readCurrentHousehold(await membershipRequest('/spaces/current', job.signal), user.householdId);
      const members = readMembers(await membershipRequest('/members', job.signal), user.id, user.auth_version);
      label = home.name + ' · ' + members.members.find(m => m.id === user.id)!.name;
    }
    const data = job.identity.account.account ? readHouseholds(await membershipRequest('/account/households', job.signal)) : null;
    return () => { setHouseholds(data); setBindingLabel(label); };
  };
  const panel = useMembershipPanel(props, !!(login || password || memberPassword || eligibility || choice), clear, load), identity = panel.identity;
  async function prove() { await panel.run(async job => { const r = record(await panel.checked(job, () => membershipRequest('/account/eligibility', job.signal,
    { method: 'POST', csrf: job.identity.account.csrf, memberCsrf: job.identity.member.csrf || '', payload: { memberPassword } })));
    if (job.current()) { setEligibility(boundedText(r.eligibilityToken, 2048)); setMemberPassword(''); panel.setMessage('身份已核对，可创建个人账户。'); } }); }
  const signIn = () => panel.authenticate(login, password, props.onIdentityChanged);
  const confirmed = () => { if (!choice || panel.locked) return; const command = choice; setChoice(null); void panel.write(command); };
  return <MembershipFrame title="我的家庭账户" testID="personal-account-panel" panel={panel} onCompleted={() => props.onIdentityChanged?.()}
    recovery={panel.handle?.scope === 'account' && !identity?.account.account ? <View style={membershipStyles.stack}>
      <Text>若原登录已失效，请明确登录刚才的个人账号，再查询原操作。</Text>
      <TextInput mode="outlined" label="个人账号" accessibilityLabel="个人账号" value={login} onChangeText={setLogin} autoCapitalize="none" disabled={panel.busy} />
      <TextInput mode="outlined" label="个人密码" accessibilityLabel="个人密码" value={password} onChangeText={setPassword} secureTextEntry disabled={panel.busy} />
      <MembershipButton label="登录后核对" onPress={() => void signIn()} disabled={panel.busy || !login || !password} />
    </View> : null}>
    {!identity?.account.account ? <SectionCard title="登录或创建个人账户"><View style={membershipStyles.stack}>
      <Text>个人账户用于加入和切换家庭；原家庭身份需要另行确认绑定。</Text>
      <TextInput mode="outlined" label="个人账号" accessibilityLabel="个人账号" autoCapitalize="none" autoCorrect={false} value={login} onChangeText={v => { setLogin(v); setChoice(null); }} disabled={panel.locked} maxLength={64} />
      <TextInput mode="outlined" label="个人密码" accessibilityLabel="个人密码" secureTextEntry value={password} onChangeText={v => { setPassword(v); setChoice(null); }} disabled={panel.locked} maxLength={128} />
      <Text variant="bodySmall">账号为 3–64 位小写字母、数字或 . _ -；密码至少 12 个字符。</Text>
      <MembershipButton label="登录个人账户" onPress={() => void signIn()} disabled={panel.locked || !login || !password} primary />
      {identity?.member.user?.role === 'member' && <>
        <Text>{bindingLabel}</Text>
        <TextInput mode="outlined" label="当前家庭密码" accessibilityLabel="当前家庭密码" secureTextEntry value={memberPassword} onChangeText={v => { setMemberPassword(v); setChoice(null); setEligibility(''); }} disabled={panel.locked} maxLength={512} />
        <MembershipButton label="验证当前家庭身份" onPress={() => void prove()} disabled={panel.locked || !memberPassword} />
        <MembershipButton label="创建个人账户" onPress={() => setChoice({ action: 'register', scope: 'account', path: '/account/register', login, body: { login, password, eligibilityToken: eligibility } })}
          disabled={panel.locked || !eligibility || !login || !password} />
      </>}
    </View></SectionCard> : <>
      <SectionCard title={identity.account.account.login}><View style={membershipStyles.stack}>
        {identity.member.user?.role === 'member' && <>
          <Text>{bindingLabel}</Text>
          <Text>绑定当前家庭的本人身份，保留原来的私人资料。</Text>
          <TextInput mode="outlined" label="当前家庭密码" accessibilityLabel="当前家庭密码" secureTextEntry value={memberPassword} onChangeText={v => { setMemberPassword(v); setChoice(null); }} disabled={panel.locked} maxLength={512} />
          <MembershipButton label="绑定这个身份" disabled={panel.locked || !memberPassword} onPress={() => setChoice({ action: 'link', scope: 'member', path: '/membership-links',
            body: { memberPassword, expectedAuthVersion: identity.member.user!.auth_version, expectedRevision: identity.member.user!.membershipRevision } })} />
        </>}
        <MembershipButton label="退出个人账户" onPress={() => setChoice({ action: 'logout', scope: 'account', path: '/account/logout', body: {} })} disabled={panel.locked} />
      </View></SectionCard>
      {households && <SectionCard title="我的家庭"><View style={membershipStyles.stack}>
        {households.memberships.map(h => <View key={h.id} style={membershipStyles.stack}>
          <Text>{h.name} · {h.memberName} · {roleLabel(h.householdRole)}</Text>
          <MembershipButton label={'进入家庭：' + h.name} disabled={panel.locked || !!choice || !!memberPassword} onPress={() => setChoice({ action: 'switch', scope: 'account', path: '/account/switch-household', targetId: h.householdId,
            body: { membershipId: h.id, expectedRevision: h.revision } })} />
        </View>)}
        {!households.memberships.length && <Text>尚未绑定或加入家庭。</Text>}
        {!!households.unavailable.length && <Text>部分家庭暂时无法读取，请稍后重新读取。</Text>}
        <MembershipButton label="刷新我的家庭" onPress={panel.refresh} disabled={panel.locked || !!memberPassword || !!choice} />
      </View></SectionCard>}
    </>}
    {choice && <SectionCard title="确认操作"><View style={membershipStyles.stack}>
      {choice.action === 'link' && <Text>{identity?.account.account?.login} · {bindingLabel}</Text>}
      <Text>{choice.action === 'switch' ? '进入所选家庭，其他家庭的私人资料不会带入。' : choice.action === 'link' ? '将当前家庭的本人身份绑定到上方个人账户。' : choice.action === 'logout' ? '退出本浏览器的个人账户及其家庭登录。' : '创建个人账户，之后仍需明确绑定或加入家庭。'}</Text>
      <MembershipButton label="确认继续" onPress={confirmed} disabled={panel.locked} primary />
      <MembershipButton label="取消" onPress={() => setChoice(null)} disabled={panel.locked} />
    </View></SectionCard>}
    <MembershipButton label="清空未提交内容" onPress={() => { clear(); panel.refresh(); }} disabled={panel.locked} />
  </MembershipFrame>;
}
