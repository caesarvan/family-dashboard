import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { canEndMemberReview, checkedMemberWrite, intentStillAllowed, memberIntent, MembersDiscarded, MembersError, MembersFence,
  MembersRejected, membersRequest, readMemberResult, readMembers, type HouseholdRole, type MemberIntent, type MemberReview,
  type MembersSession, type MembersSnapshot } from '../lib/householdMembers';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';
import PersonalAccountPanel, { MembershipButton } from './PersonalAccountPanel';
import MembershipInvitationsPanel from './MembershipInvitationsPanel';
import MembershipManagementPanel from './MembershipManagementPanel';

type Props = { onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Model = { snapshot: MembersSnapshot | null; confirmation: MemberIntent | null; unknown: MemberIntent | null; review: MemberReview | null };
const empty = (): Model => ({ snapshot: null, confirmation: null, unknown: null, review: null });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const roleName = (role: HouseholdRole) => role === 'admin' ? '管理员' : '普通成员';

export default function HouseholdMembersPanel(props: Props) {
  const household = useHousehold();
  const [page, setPage] = useState<'members' | 'account' | 'invitations' | 'relationships'>('members');
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const changed = (value: boolean) => { pendingRef.current = value; setPending(value); props.onPendingChange?.(value); };
  const back = () => { if (!pendingRef.current) setPage('members'); };
  // Each child owns fresh identity checks. Provider refresh only updates shared navigation.
  const refresh = () => household.refresh();
  if (page === 'account') return <PersonalAccountPanel onBack={back} onPendingChange={changed} onIdentityChanged={refresh} />;
  if (page === 'invitations') return <MembershipInvitationsPanel onBack={back} onPendingChange={changed} onJoined={refresh} />;
  if (page === 'relationships') return <MembershipManagementPanel onBack={back} onPendingChange={changed} onLeft={refresh} />;
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看家庭成员" />;
  return <View style={{ gap: 16 }}>
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      <MembershipButton label="我的家庭账户" disabled={pending} onPress={() => setPage('account')} />
      <MembershipButton label="邀请与加入家庭" disabled={pending} onPress={() => setPage('invitations')} />
      <MembershipButton label="管理成员关系" disabled={pending} onPress={() => setPage('relationships')} />
    </View>
    <Workspace key={household.identityKey} {...props} onPendingChange={changed} identityKey={household.identityKey} />
  </View>;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const alive = useRef(false), focused = useRef(false), active = useRef(false), windowFocused = useRef(typeof document === 'undefined' || document.hasFocus()), epoch = useRef(0), working = useRef(false);
  const flight = useRef<AbortController | null>(null), fence = useRef(new MembersFence(props.identityKey));
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && windowFocused.current && foreground.current
    && ticket === epoch.current && online() && latest.current.household.online && latest.current.household.identityKey === props.identityKey
    && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || !!live.current.confirmation || !!live.current.unknown;
  function notify() { latest.current.props.onPendingChange?.(pending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); working.current = false; setBusy(false);
    // Same-session confirmation/unknown intent stays in memory, never rendered
    // until fresh identity verification. A prior readback cannot authorize ending it.
    install(clear ? empty() : { snapshot: null, review: null }); setMessage(''); setError('');
  }
  function failed(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof MembersDiscarded) {
      if (e.message === 'identity') { conceal(true); void latest.current.household.refresh(); }
      return;
    }
    if (e instanceof MembersError && [401, 403].includes(e.status)) {
      conceal(); setError('登录身份或权限暂时无法核对，成员信息已隐藏。'); void latest.current.household.refresh(); return;
    }
    setError(e instanceof Error ? e.message : '暂时无法核对成员状态。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (e) { failed(e, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, action: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await membersRequest('/me', signal) as MembersSession, action, () => current(ticket));
  async function load(ticket: number, signal: AbortSignal, explicitReview = false) {
    const unknown = live.current.unknown;
    install({ snapshot: null, review: null });
    const snapshot = readMembers(await guard(ticket, signal, () => membersRequest('/members', signal)),
      latest.current.household.user!.id, Number(latest.current.household.user!.auth_version));
    if (!current(ticket)) return;
    const confirmation = live.current.confirmation;
    const stale = confirmation && !intentStillAllowed(confirmation, snapshot);
    install({ snapshot, ...(stale ? { confirmation: null } : {}), review: explicitReview && unknown === live.current.unknown && unknown
      ? { intent: unknown, identity: props.identityKey, epoch: ticket } : null });
    if (stale) setMessage('成员状态已变化，请按当前状态重新选择。');
    if (unknown) setMessage('已读取当前状态；这不能确认刚才那次操作是否完成。');
    setVisible(true);
  }
  async function resume(ticket: number, signal: AbortSignal) {
    if (live.current.unknown) { await guard(ticket, signal, async () => undefined); if (current(ticket)) setVisible(true); }
    else await load(ticket, signal);
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || !windowFocused.current || !foreground.current || !online()
      || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(resume);
  }
  function retry() { if (!latest.current.household.online) void latest.current.household.refresh(); else if (active.current) void job(resume); else enter(); }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); live.current = empty(); latest.current.props.onPendingChange?.(false); };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); };
    const offline = () => conceal(), connected = () => { if (!latest.current.household.online) void latest.current.household.refresh(); else enter(); };
    const blur = () => { windowFocused.current = false; conceal(); }, focus = () => { windowFocused.current = true; enter(); };
    const beforeUnload = (e: BeforeUnloadEvent) => { if (pending()) { e.preventDefault(); e.returnValue = ''; } };
    const app = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('offline', offline);
      window.addEventListener('online', connected); window.addEventListener('pagehide', offline); window.addEventListener('pageshow', connected); window.addEventListener('beforeunload', beforeUnload); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('offline', offline);
        window.removeEventListener('online', connected); window.removeEventListener('pagehide', offline); window.removeEventListener('pageshow', connected); window.removeEventListener('beforeunload', beforeUnload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function choose(targetId: string, kind: 'role' | 'revoke') {
    if (!current() || pending() || !live.current.snapshot) return;
    const target = live.current.snapshot.members.find(m => m.id === targetId);
    if (!target) return;
    try { install({ confirmation: memberIntent(live.current.snapshot, targetId, kind, kind === 'role' ? target.householdRole === 'admin' ? 'member' : 'admin' : undefined) }); setError(''); setMessage(''); }
    catch (e) { failed(e, epoch.current); }
  }
  function cancel() { if (!alive.current || latest.current.household.identityKey !== props.identityKey || working.current || live.current.unknown) return; install({ confirmation: null }); }
  async function confirm() {
    const intent = live.current.confirmation;
    if (!current() || working.current || live.current.unknown || !intent || !live.current.snapshot || !intentStillAllowed(intent, live.current.snapshot)) return;
    await job(async (ticket, signal) => {
      try {
        await checkedMemberWrite(action => guard(ticket, signal, action), async csrf => {
          install({ unknown: intent, confirmation: null, snapshot: null, review: null }); setMessage('');
          return readMemberResult(await membersRequest('/members/' + intent.targetId + (intent.kind === 'role' ? '/role' : '/revoke-sessions'), signal,
            { method: intent.kind === 'role' ? 'PATCH' : 'POST', payload: intent.body, csrf }), intent);
        });
        if (!current(ticket)) return;
        install({ unknown: null, snapshot: null, review: null });
        setMessage(intent.kind === 'role' ? '角色已调整，对方需要重新登录。正在读取当前状态。' : '退出请求已处理，对方仍可重新登录。正在读取当前状态。');
      } catch (e) {
        if (!current(ticket)) return;
        if (e instanceof MembersRejected) { install({ unknown: null, snapshot: null, confirmation: null, review: null }); setMessage('请重新读取成员列表，再核对要执行的操作。'); }
        else if (live.current.unknown) setMessage('请求可能已执行。请先读取当前成员状态，不会自动重复提交。');
        throw e;
      }
      // The write is known successful. A failing GET must not restore stale actions
      // or turn the accepted write into an uncertain request eligible for resending.
      await load(ticket, signal);
      if (current(ticket)) setMessage(intent.kind === 'role' ? '角色已调整；以下为刚读取的当前状态。' : '退出请求已处理；以下为刚读取的当前状态。');
    });
  }
  function finishReview() {
    if (!current() || working.current || !canEndMemberReview(live.current.review, live.current.unknown, props.identityKey, epoch.current)) return;
    install({ unknown: null, review: null }); setError(''); setMessage('已结束本地核对。后续操作请按当前状态重新选择并确认。');
  }
  function back() { if (!alive.current || latest.current.household.identityKey !== props.identityKey || pending()) return; latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
  const button = (label: string, action: () => void, disabled = false, mode: 'text' | 'outlined' | 'contained' = 'outlined') =>
    <Button accessibilityLabel={label} contentStyle={styles.touch} labelStyle={styles.buttonLabel} mode={mode} disabled={disabled} onPress={action}>{label.split('：')[0]}</Button>;
  const confirmation = visible ? model.confirmation : null, stack = { gap: density.sectionGap };
  return <View testID="household-members-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="家庭与成员" description="一起管理这个家，个人数据仍各自保管。" action={button('返回更多', back, busy || !!model.unknown || !!model.confirmation)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {visible && !!message && <Text testID="members-message" style={styles.wrap}>{message}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对家庭成员" />}
    {!visible ? <><EmptyState title="成员信息已隐藏" description="联网并回到前台后，重新核对身份与当前成员。" action={button('重新读取成员列表', retry, busy || !online())} />
      {model.confirmation && !model.unknown && button('取消待确认操作', cancel, busy)}</> : <>
      {model.unknown && <SectionCard title="先核对当前状态"><View testID="members-unknown" style={stack}>
        <Text style={styles.wrap}>刚才为「{model.unknown.targetName}」{model.unknown.kind === 'role' ? '调整角色' : '退出浏览器'}的结果尚未确认。读取列表只显示现在的状态，不是本次操作回执。</Text>
        {button('读取当前成员状态', () => void job((ticket, signal) => load(ticket, signal, true)), busy, 'contained')}
        {canEndMemberReview(model.review, model.unknown, props.identityKey, epoch.current) && <>
          <Text>核对下方当前状态后，可结束本次核对。不会再次发送刚才的请求。</Text>
          {button('结束本次核对', finishReview, busy)}
        </>}
      </View></SectionCard>}
      {model.snapshot ? <View testID="members-current" style={stack}>
        {model.snapshot.members.map(member => <SectionCard title={member.name} key={member.id}><View testID={'household-member-' + member.id} style={stack}>
          <Text>{roleName(member.householdRole)}{member.id === model.snapshot!.currentMemberId ? ' · 本人' : ''}</Text>
          {member.activeSessionCount !== null && <Text>{member.activeSessionCount} 个有效浏览器会话</Text>}
          {!model.unknown && <View style={styles.actions}>
            {member.capabilities.changeRole && button('调整角色：' + member.name, () => choose(member.id, 'role'), busy || !!model.confirmation)}
            {member.capabilities.revokeSessions && button('退出所有浏览器：' + member.name, () => choose(member.id, 'revoke'), busy || !!model.confirmation)}
          </View>}
        </View></SectionCard>)}
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>管理员可以调整角色、退出另一成员的浏览器；个人财务、照片和云账户的可见范围保持。浏览器会话数不代表物理设备数或在线人数。</Text>
      </View> : !model.unknown && <EmptyState title="需要重新读取当前成员" description="读取完成后才会恢复操作。" action={button('重新读取成员列表', () => void job(load), busy)} />}
      {model.snapshot && !model.unknown && button('刷新成员列表', () => void job(load), busy || !!model.confirmation)}
    </>}
    <Portal><Dialog visible={!!confirmation} onDismiss={cancel} style={styles.dialog}>
      <Dialog.Title>{confirmation?.kind === 'role' ? '调整成员角色？' : '退出所有浏览器？'}</Dialog.Title>
      <Dialog.ScrollArea><ScrollView contentContainerStyle={styles.dialogContent}>
        {confirmation && <>
          <Text style={styles.wrap}>成员：{confirmation.targetName}</Text>
          {confirmation.kind === 'role' && <Text>{roleName(confirmation.previousRole)} → {roleName(confirmation.body.householdRole!)}</Text>}
          <Text>{confirmation.kind === 'role' ? '角色修改后，对方当前浏览器都需要重新登录。' : '对方当前浏览器都需要重新登录，之后仍可用自己的凭据登录。'}</Text>
          <Text>不会删除成员、个人数据、云账户绑定或电视连接。</Text>
        </>}
      </ScrollView></Dialog.ScrollArea>
      <Dialog.Actions style={styles.actions}>{button('取消', cancel, busy)}{button(confirmation?.kind === 'role' ? '确认调整角色' : '确认退出所有浏览器', () => void confirm(), busy, 'contained')}</Dialog.Actions>
    </Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, buttonLabel: { flexShrink: 1 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  wrap: { flexShrink: 1, ...(Platform.OS === 'web' ? { overflowWrap: 'anywhere' as const } : {}) },
  dialog: { maxWidth: 520, width: '92%', alignSelf: 'center' }, dialogContent: { gap: 14, paddingVertical: 16 } });
