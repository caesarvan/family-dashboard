import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Icon, Portal, Text, TextInput, TouchableRipple, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { openSyncProvider } from '../lib/navigation';
import { syncAuthMessage } from '../lib/authNavigation';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import { accountTime, providerName, readAccounts, readDiscovery, reviewSelection, sameSelection, selectionChanges, selectionDraft, sourceKey, sourcePayload,
  type AccountList, type CloudAccount, type DraftSource, type ProviderId, type SelectionDraft, type SourceChoice, type SourceOwner } from '../lib/accounts';
import type { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Props = ScreenProps & { authResult?: { status: 'connected' | 'error'; reason?: string } };
type Pending = { accountId: string; kind: 'save'; sources: SourceChoice[]; version: string } | { accountId: string; kind: 'disconnect' | 'sync' };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const inForeground = () => typeof document === 'undefined' || !document.hidden;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '暂时无法完成操作，请稍后再试。';
const consentLabel = '我确认共享所选的完整日程标题、地点和任务';

function Check({ label, checked, disabled = false, onPress }: { label: string; checked: boolean; disabled?: boolean; onPress: () => void }) {
  const theme = useTheme();
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === ' ' || event.key === 'Spacebar') { event.preventDefault(); event.stopPropagation(); if (!disabled && !event.repeat) onPress(); }
  } } : {};
  return <TouchableRipple {...keyboard} accessible accessibilityRole="checkbox" accessibilityLabel={label}
    accessibilityState={{ checked, disabled }} aria-checked={checked} aria-disabled={disabled} disabled={disabled} onPress={onPress}
    style={state => [styles.check, { borderColor: state.focused ? theme.colors.primary : 'transparent' }]}>
    <View style={styles.checkContent} pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Icon source={checked ? 'checkbox-marked' : 'checkbox-blank-outline'} size={24} color={disabled ? theme.colors.onSurfaceDisabled : theme.colors.primary} />
      <Text style={styles.grow}>{label}</Text>
    </View>
  </TouchableRipple>;
}

export default function AccountsScreen(props: Props) {
  const household = useHousehold();
  if (props.user.role !== 'member') return <EmptyState title="账户连接仅本人管理" description="请使用成员账户登录。电视不能读取账户详情。" />;
  return <AccountsWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}

function AccountsWorkspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), { width, height } = useWindowDimensions();
  const latest = useRef(household); latest.current = household;
  const alive = useRef(false), active = useRef(false), focused = useRef(false), denied = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const generation = useRef(0), reading = useRef(false), writing = useRef(false);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [notice, setNotice] = useState(() => props.authResult ? syncAuthMessage(props.authResult) : '');
  const [list, setList] = useState<AccountList | null>(null);
  const [draft, setDraftState] = useState<SelectionDraft | null>(null), draftRef = useRef<SelectionDraft | null>(null);
  const [conflict, setConflictState] = useState<CloudAccount | null>(null), conflictRef = useRef<CloudAccount | null>(null);
  const [pending, setPendingState] = useState<Pending | null>(null), pendingRef = useRef<Pending | null>(null);
  const [query, setQuery] = useState(''), [offset, setOffset] = useState(0), [consent, setConsent] = useState(false);
  const [reviewing, setReviewing] = useState(false), [disconnect, setDisconnect] = useState<CloudAccount | null>(null), [discard, setDiscard] = useState(false);
  const current = () => alive.current && active.current && focused.current && appActive.current && !denied.current
    && latest.current.identityKey === props.identityKey && latest.current.online && online() && inForeground();
  const setDraft = (next: SelectionDraft | null) => { draftRef.current = next; setDraftState(next); };
  const setConflict = (next: CloudAccount | null) => { conflictRef.current = next; setConflictState(next); };
  const setPending = (next: Pending | null) => { pendingRef.current = next; setPendingState(next); };
  function clearEditor() { setDraft(null); setConflict(null); setQuery(''); setOffset(0); setConsent(false); setReviewing(false); setDiscard(false); }
  function conceal(clear = false) {
    active.current = false; ++generation.current; fence.current.invalidate(); setVisible(false); setBusy(false);
    reading.current = false; writing.current = false; setList(null); setReviewing(false); setDisconnect(null); setDiscard(false);
    if (clear) { clearEditor(); setPending(null); setNotice(''); setError(''); }
  }
  function failed(caught: unknown) {
    if (!current()) return;
    if (caught instanceof PhotoReadDiscarded && caught.message !== 'identity') return;
    if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) {
      conceal(true); denied.current = true; setError('登录身份已变化，请重新打开账户连接。'); void latest.current.refresh(); return;
    }
    setError(errorMessage(caught));
  }
  async function guarded<T>(load: () => Promise<T>, ticket = generation.current) {
    return fence.current.read(load, () => current() && ticket === generation.current);
  }
  async function accountSnapshot() { return readAccounts(await guarded(() => request<unknown>('/accounts'))); }
  function installSnapshot(snapshot: AccountList) {
    if (!current()) return;
    setList(snapshot);
    const intent = pendingRef.current, old = draftRef.current;
    if (intent) {
      const fresh = snapshot.accounts.find(a => a.id === intent.accountId);
      if (intent.kind === 'save') {
        if (fresh && sameSelection(intent.sources, fresh.sources)) {
          clearEditor(); setNotice('已核对：当前保存的共享范围与本次选择一致。同步结果请查看各来源的成功时间。');
        } else if (fresh && old) {
          setConflict(fresh); setConsent(false); setNotice('保存结果尚未确认，已读取最新选择。请核对后再决定是否保存。');
        } else { clearEditor(); setError('此账户已断开，旧选择已清空。'); }
      } else if (intent.kind === 'disconnect') {
        if (!fresh) { clearEditor(); setNotice('已核对：账户绑定已断开。原应用中的记录仍保留。'); }
        else { setDisconnect(fresh); setNotice('断开结果尚未确认，账户仍在列表中。如需断开，请再次明确确认。'); }
      } else setNotice('检查请求结果尚未确认。请以各来源的最近成功时间为准；不会自动重复提交。');
      setPending(null);
    } else if (old) {
      const fresh = snapshot.accounts.find(a => a.id === old.accountId);
      if (!fresh) { clearEditor(); setError('此账户已断开，旧选择已清空。'); }
      else if (fresh.selectionVersion !== old.version) { setConflict(fresh); setConsent(false); setReviewing(false); }
      else if (conflictRef.current) setConflict(fresh);
    }
  }
  async function reload(background = false) {
    if (!current() || writing.current || reading.current) return;
    const ticket = generation.current; reading.current = true; if (!background) setBusy(true);
    try { const result = await accountSnapshot(); if (current() && ticket === generation.current) { installSnapshot(result); setVisible(true); } }
    catch (caught) { if (ticket === generation.current) { failed(caught); if (current()) { setVisible(false); setList(null); } } }
    finally { if (ticket === generation.current) { reading.current = false; if (alive.current) setBusy(false); } }
  }
  function enter() {
    if (!alive.current || active.current || !focused.current || denied.current || !appActive.current || !online() || !inForeground() || !latest.current.online) return;
    active.current = true; setError(''); void reload();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++generation.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(true); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (inForeground()) enter(); else conceal(); };
    const offline = () => { conceal(); setError('网络已断开，账户内容已隐藏。恢复连接后会重新核对，原输入暂时保留。'); };
    const connected = () => enter();
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    const subscription = AppState.addEventListener('change', value => { appActive.current = value === 'active'; if (appActive.current) enter(); else conceal(); });
    const timer = setInterval(() => { if (current()) void reload(true); }, 15000);
    return () => {
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); }
      subscription.remove(); clearInterval(timer);
    };
  }, [props.identityKey]);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);

  async function operation(job: () => Promise<void>) {
    if (!current() || writing.current || pendingRef.current || reading.current && busy) return;
    // A background status check never consumes a user's click. Discard its
    // eventual UI response before starting the explicitly requested operation.
    if (reading.current) { ++generation.current; fence.current.invalidate(); reading.current = false; }
    writing.current = true; setBusy(true); setError(''); const ticket = generation.current;
    try { await job(); }
    catch (caught) {
      if (ticket !== generation.current || !current()) return;
      if (caught instanceof ApiError && caught.status > 0 && caught.status < 500) setPending(null);
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) {
        // A provider can reject an expired cloud grant while the household
        // session is still valid. Check the complete identity before deciding.
        try { installSnapshot(await accountSnapshot()); if (current()) setError(errorMessage(caught)); }
        catch (verification) { failed(verification); if (current()) { setVisible(false); setList(null); } }
        return;
      }
      failed(caught);
      if (current() && pendingRef.current) {
        try { installSnapshot(await accountSnapshot()); }
        catch (followup) { failed(followup); if (current()) setNotice('操作结果尚未确认。请刷新核对；系统不会自动重复提交。'); }
      }
    } finally { if (ticket === generation.current) { writing.current = false; if (alive.current) setBusy(false); } }
  }
  async function bind(provider: ProviderId) {
    await operation(async () => {
      const result = await guarded(() => latest.current.mutate<{ url: string }>('/accounts/bind', 'POST', { provider }));
      if (!current()) return;
      if (typeof result?.url !== 'string' || !openSyncProvider(result.url, provider)) throw new Error('授权地址无法核对，请刷新后重新连接。');
    });
  }
  async function discover(account: CloudAccount, preserve = false) {
    await operation(async () => {
      const result = readDiscovery(await guarded(() => request<unknown>(`/accounts/${account.id}/sources`)));
      if (!current()) return;
      const next = selectionDraft(account.id, result, props.user.id), old = draftRef.current;
      if (preserve && old?.accountId === account.id) {
        const prior = new Map(old.rows.map(r => [sourceKey(r), r]));
        const rows = next.rows.map(r => { const before = prior.get(sourceKey(r)); return before ? { ...r, selected: before.selected, owner: before.owner, primary: before.primary } : { ...r, selected: false, primary: false }; });
        const present = new Set(rows.map(sourceKey));
        for (const r of old.rows) if (!present.has(sourceKey(r)) && r.selected) rows.push({ ...r, available: false, writable: false });
        setDraft({ ...old, rows });
        if (old.version !== result.selectionVersion) setConflict({ ...account, sources: result.selected, selectionVersion: result.selectionVersion });
      } else { setDraft(next); setConflict(null); setQuery(''); setOffset(0); }
      setConsent(false); setReviewing(false); setNotice('请选择准备与家人共享的内容。未选择的日历和清单不会同步。');
    });
  }
  function changeRow(row: DraftSource, patch: Partial<DraftSource>) {
    if (busy || pending || !current() || conflictRef.current) return;
    const old = draftRef.current; if (!old) return;
    const rows = old.rows.map(r => sourceKey(r) === sourceKey(row) ? { ...r, ...patch } : patch.primary === true ? { ...r, primary: false } : r);
    setDraft({ ...old, rows }); setConsent(false); setReviewing(false); setError('');
  }
  function startReview() {
    if (!draftRef.current || !current() || pending || conflict || busy) return;
    try { sourcePayload(draftRef.current); if (!consent) throw new Error('请先确认共享范围。'); setReviewing(true); setError(''); }
    catch (caught) { setError(errorMessage(caught)); }
  }
  async function save() {
    const selected = draftRef.current; if (!selected || !consent || conflictRef.current || !reviewing) return;
    await operation(async () => {
      const payload = sourcePayload(selected);
      setPending({ accountId: selected.accountId, kind: 'save', sources: payload.sources, version: payload.selectionVersion });
      setReviewing(false);
      try {
        await guarded(() => latest.current.mutate(`/accounts/${selected.accountId}/sources`, 'POST', payload));
      } catch (caught) {
        if (current() && caught instanceof ApiError && caught.status === 409) {
          setPending(null); const snapshot = await accountSnapshot(); installSnapshot(snapshot);
          const fresh = snapshot.accounts.find(a => a.id === selected.accountId);
          if (fresh && draftRef.current) setConflict(fresh);
          setConsent(false); setError(caught.message); return;
        }
        throw caught;
      }
      installSnapshot(await accountSnapshot());
      if (current()) void latest.current.refresh();
    });
  }
  async function sync(account: CloudAccount) {
    await operation(async () => {
      setPending({ accountId: account.id, kind: 'sync' });
      const result = await guarded(() => latest.current.mutate<{ queued: boolean }>(`/accounts/${account.id}/sync`, 'POST'));
      if (!current()) return;
      if (typeof result?.queued !== 'boolean') throw new Error('检查请求的结果无法核对，请刷新状态。');
      setPending(null); setNotice(result.queued ? '已安排后台检查。请查看各来源的最近成功时间，排队不代表同步完成。' : '当前没有选中的来源，无需检查。');
      installSnapshot(await accountSnapshot());
    });
  }
  async function removeAccount() {
    if (!disconnect) return; const account = disconnect;
    await operation(async () => {
      setPending({ accountId: account.id, kind: 'disconnect' }); setDisconnect(null);
      await guarded(() => latest.current.mutate(`/accounts/${account.id}`, 'DELETE'));
      installSnapshot(await accountSnapshot()); if (current()) void latest.current.refresh();
    });
  }

  const locked = busy || !!pending || !current();
  const editingAccount = list?.accounts.find(a => a.id === draft?.accountId);
  const filtered = draft?.rows.filter(r => r.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) || [];
  const pageRows = filtered.slice(offset, offset + 24);
  const chosenCount = draft?.rows.filter(row => row.selected).length || 0;
  const ownerName = (id: string) => id === 'shared' ? '共同' : props.state.people.find(person => person.id === id)?.name || (id === 'member1' ? '成员一' : '成员二');
  const summary = (row: { name: string; kind: string; owner: string; primary: boolean }) => row.name + ' · ' + (row.kind === 'calendar' ? ownerName(row.owner) : row.primary ? '家庭主清单' : '共同清单');
  const privateVisible = visible && current();
  const dialogStyle = [styles.dialog, { maxHeight: height - 40 }];
  return <View style={styles.page}>
    <PageHeader title="账户与同步" description="连接自己的日历与清单，选择与家人共享的内容。"
      action={<Button mode="outlined" icon="refresh" disabled={busy || !online() || denied.current} onPress={() => { setError(''); if (!active.current) enter(); else void reload(); }}>刷新状态</Button>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && privateVisible && <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对账户" />}
    {!privateVisible && !busy && <EmptyState title="账户内容暂时隐藏" description="重新连接并核对当前身份后，会恢复可以管理的账户。" />}
    {privateVisible && list && <>
      {!draft && <>
        <View style={styles.providers}>{list.providers.map(provider => <SectionCard key={provider.id} title={provider.name}
          style={[styles.provider, width >= 740 && styles.providerWide]}>
          <Text style={styles.muted}>{provider.id === 'microsoft' ? 'Outlook 日历 · Microsoft To Do' : 'Google 日历 · Google Tasks'}</Text>
          <Text variant="bodySmall" style={styles.space}>{provider.configured ? '应用已配置，需由你授权账户' : '等待应用维护者配置'}</Text>
          <Button mode="contained" disabled={!provider.configured || locked} onPress={() => void bind(provider.id)}>连接 {provider.name}</Button>
        </SectionCard>)}</View>
        <Text variant="bodySmall" style={styles.muted}>绑定信息仅本人可见。连接成功后，仍需选择要共享的来源。每位成员最多连接 4 个账户。</Text>
        {list.accounts.length === 0 && <EmptyState title="还没有连接账户" description="选择上方平台开始授权，之后选择具体日历和清单。" />}
        {list.accounts.map(account => <SectionCard key={account.id} title={account.name || providerName(account.provider)}>
          <View style={styles.stack}>
            <Text style={styles.muted}>{providerName(account.provider)}{account.email ? ' · ' + account.email : ''}</Text>
            <Text style={{ color: account.needsReauth ? theme.colors.error : theme.colors.onSurface }}>{account.needsReauth ? '需要重新授权' : account.capabilities.sync ? '账户已连接' : '仅授权相册，日历与清单尚未授权'}</Text>
            {account.sources.length ? account.sources.map(source => <View key={source.id} style={styles.sourceStatus}>
              <Text variant="titleSmall">{summary(source)}</Text>
              <Text variant="bodySmall" style={styles.muted}>最近成功：{accountTime(source.lastSuccess)}</Text>
              {!!source.error && <Text style={{ color: theme.colors.error }}>{source.error}</Text>}
            </View>) : <Text style={styles.muted}>尚未选择来源，没有日历或清单向家庭共享。</Text>}
            <View style={styles.buttons}>
              <Button mode="outlined" accessibilityLabel={'选择日历与清单：' + (account.name || account.email)} disabled={locked || account.needsReauth || !account.capabilities.sync} onPress={() => void discover(account)}>选择日历与清单</Button>
              {(account.needsReauth || !account.capabilities.sync) && <Button mode="contained" disabled={locked || !list.providers.find(p => p.id === account.provider)?.configured} onPress={() => void bind(account.provider)}>重新授权 {providerName(account.provider)}</Button>}
              <Button accessibilityLabel={'检查更新：' + (account.name || account.email)} disabled={locked || account.needsReauth || !account.sources.length} onPress={() => void sync(account)}>检查更新</Button>
              {account.capabilities.photos && <Button disabled={locked} onPress={() => props.onNavigate('photos')}>管理相册</Button>}
              <Button accessibilityLabel={'断开绑定：' + (account.name || account.email)} textColor={theme.colors.error} disabled={locked} onPress={() => { setDisconnect(account); setError(''); }}>断开绑定</Button>
            </View>
          </View>
        </SectionCard>)}
        <Text variant="bodySmall" style={styles.muted}>任务约每 30 秒、日历约每 60 秒由后台检查；此页每 15 秒读取最新状态。网络、限流或重新授权可能延长等待。日历在原应用编辑；共同清单支持完成状态回写。</Text>
      </>}
      {!!draft && !!editingAccount && <SectionCard title="选择共享内容">
        <View style={styles.stack}>
          <Text>{editingAccount.name || editingAccount.email} · {providerName(editingAccount.provider)}</Text>
          <Text variant="bodySmall" style={styles.muted}>所选日历的完整标题、地点与任务将展示给双方及已配对电视。日历归属仅用于区分安排，不改变共享范围。</Text>
          {(editingAccount.needsReauth || !editingAccount.capabilities.sync) && <View style={styles.warning}>
            <Text>此账户需要重新授权日历与清单。原输入仍保留；前往服务商授权会离开此页面。</Text>
            <Button mode="contained" disabled={locked || !list.providers.find(p => p.id === editingAccount.provider)?.configured} onPress={() => void bind(editingAccount.provider)}>重新授权 {providerName(editingAccount.provider)}</Button>
          </View>}
          {!!pending && <Text accessibilityRole="alert">保存结果尚未确认。请刷新核对，暂时不能再次提交。</Text>}
          {!!conflict && <View style={styles.warning}>
            <Text accessibilityRole="header" variant="titleSmall">共享范围已变化，请核对最新选择</Text>
            <Text variant="bodySmall">你的输入已保留。服务器当前保存的是：</Text>
            {conflict.sources.length ? conflict.sources.map(row => <Text key={row.id}>{summary(row)}</Text>) : <Text>未选择任何来源</Text>}
            <Button mode="outlined" disabled={locked} onPress={() => { const currentDraft = draftRef.current, fresh = conflictRef.current; if (!currentDraft || !fresh) return; setDraft(reviewSelection(currentDraft, fresh)); setConflict(null); setConsent(false); setError(''); setReviewing(false); }}>已核对最新选择，继续编辑</Button>
          </View>}
          <View style={styles.buttons}><Button icon="arrow-left" disabled={locked} onPress={() => setDiscard(true)}>返回账户</Button>
            <Button icon="refresh" disabled={locked} onPress={() => void discover(editingAccount, true)}>重新读取来源</Button></View>
          <TextInput mode="outlined" label="搜索日历或清单" accessibilityLabel="搜索日历或清单" value={query} maxLength={200} disabled={!!pending || !current()} onChangeText={text => { setQuery(text); setOffset(0); }} outlineStyle={styles.inputOutline} style={styles.input} />
          <Text variant="bodySmall">已选择 {chosenCount} / 12 个来源 · 搜索结果 {filtered.length} 个</Text>
          {pageRows.map(row => <View key={sourceKey(row)} style={styles.sourceOption}>
            <Check label={(row.kind === 'calendar' ? '选择日历：' : '选择清单：') + row.name} checked={row.selected}
              disabled={locked || !!conflict || (!row.selected && (!row.available || row.kind === 'tasks' && !row.writable || chosenCount >= 12))}
              onPress={() => changeRow(row, { selected: !row.selected, primary: row.selected ? false : row.primary })} />
            {!row.available && <Text variant="bodySmall" style={styles.muted}>本次未发现，已保留；请重新读取，或明确取消。</Text>}
            {row.kind === 'tasks' && row.available && !row.writable && <Text variant="bodySmall" style={styles.muted}>此清单没有写入权限，暂时不能选择。</Text>}
            {row.selected && row.kind === 'calendar' && <View style={styles.buttons}>{(['member1', 'member2', 'shared'] as SourceOwner[]).map(id => <Button key={id} compact mode={row.owner === id ? 'contained' : 'outlined'}
              accessibilityLabel={'日历 ' + row.name + ' 归属：' + ownerName(id)} disabled={locked || !!conflict} onPress={() => changeRow(row, { owner: id })}>{ownerName(id)}</Button>)}</View>}
            {row.selected && row.kind === 'tasks' && <Button mode={row.primary ? 'contained' : 'outlined'} disabled={locked || !!conflict || !row.available || !row.writable}
              accessibilityLabel={(row.primary ? '取消主清单：' : '设为主清单：') + row.name} onPress={() => changeRow(row, { primary: !row.primary })}>{row.primary ? '家庭主清单 · 点击取消' : '设为家庭主清单'}</Button>}
          </View>)}
          {!pageRows.length && <Text style={styles.muted}>没有匹配的日历或清单。可以换个关键词或重新读取来源。</Text>}
          {filtered.length > 24 && <View style={styles.pagination}><Text variant="bodySmall">第 {Math.floor(offset / 24) + 1} / {Math.max(1, Math.ceil(filtered.length / 24))} 页</Text>
            <View style={styles.buttons}><Button disabled={offset === 0 || locked} onPress={() => setOffset(Math.max(0, offset - 24))}>上一页</Button><Button disabled={offset + 24 >= filtered.length || locked} onPress={() => setOffset(offset + 24)}>下一页</Button></View></View>}
          <Divider />
          <Text variant="bodySmall" style={styles.muted}>家庭最多设置一份主清单，也可以暂不设置。设为主清单，表示允许家人将明确确认的本地待办发布到此清单；不会自动迁移已有待办。</Text>
          <Check label={consentLabel} checked={consent} disabled={locked || !!conflict} onPress={() => setConsent(!consent)} />
          <Text variant="bodySmall" style={styles.muted}>保存会替换此账户的全部共享范围。取消选择会移除看板中的同步内容，原应用记录保留。</Text>
          <Button mode="contained" disabled={locked || !!conflict || !consent} onPress={startReview}>查看变更</Button>
        </View>
      </SectionCard>}
    </>}
    <Portal>{privateVisible && <>
      <Dialog visible={privateVisible && reviewing && !!draft} onDismiss={() => !busy && setReviewing(false)} style={dialogStyle}>
        <Dialog.Title>确认共享范围</Dialog.Title>
        <Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent}>
          <Text>将保存以下完整选择，并向双方及已配对电视共享：</Text>
          {draft && (selectionChanges(draft).selected.length ? selectionChanges(draft).selected.map(row => <Text key={sourceKey(row)}>{summary(row)}</Text>) : <Text>不共享任何日历或清单</Text>)}
          {draft && selectionChanges(draft).removed.length > 0 && <><Text variant="titleSmall">将取消以下来源</Text>
            {selectionChanges(draft).removed.map(row => <Text key={row.id}>{row.name}</Text>)}<Text>这些来源在看板中的同步内容会移除，原应用中的记录不会删除。</Text></>}
          {draft?.rows.some(row => row.selected && row.primary) && <Text>家庭主清单允许家人将逐项确认的本地待办发布到该账户。</Text>}
        </ScrollView></Dialog.ScrollArea>
        <Dialog.Actions style={styles.buttons}><Button disabled={busy} onPress={() => setReviewing(false)}>继续编辑</Button><Button mode="contained" disabled={locked || !!conflict} onPress={() => void save()}>确认保存</Button></Dialog.Actions>
      </Dialog>
      <Dialog visible={privateVisible && !!disconnect} onDismiss={() => !busy && setDisconnect(null)} style={dialogStyle}>
        <Dialog.Title>断开账户绑定</Dialog.Title>
        <Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent}>
          <Text>{disconnect?.name || disconnect?.email}</Text>
          <Text>断开后，这个账户的同步来源和本地云端镜像会移除，原应用中的日历、任务和照片仍保留。已发布的本地待办会保留，但停止云端同步。相册来源的后续导入也将停止。</Text>
          <Text>该账户将无法再用于登录此家庭，家庭密码登录仍可使用。</Text>
        </ScrollView></Dialog.ScrollArea>
        <Dialog.Actions style={styles.buttons}><Button disabled={busy} onPress={() => setDisconnect(null)}>保留绑定</Button><Button mode="contained" buttonColor={theme.colors.error} disabled={locked} onPress={() => void removeAccount()}>确认断开</Button></Dialog.Actions>
      </Dialog>
      <Dialog visible={privateVisible && discard} onDismiss={() => setDiscard(false)} style={dialogStyle}>
        <Dialog.Title>离开来源选择？</Dialog.Title><Dialog.Content><Text>尚未保存的选择会清空，已保存的共享范围保持不变。</Text></Dialog.Content>
        <Dialog.Actions style={styles.buttons}><Button onPress={() => setDiscard(false)}>继续选择</Button><Button onPress={clearEditor}>放弃输入并返回</Button></Dialog.Actions>
      </Dialog>
    </>}</Portal>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 18 }, stack: { gap: 14 }, muted: { color: '#60646c', flexShrink: 1 }, grow: { flex: 1, minWidth: 0 },
  providers: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 }, provider: { width: '100%' }, providerWide: { flex: 1, minWidth: 0, width: 'auto' },
  space: { marginTop: 12, marginBottom: 16 }, buttons: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  sourceStatus: { backgroundColor: 'white', padding: 16, borderRadius: 16, gap: 6 },
  sourceOption: { backgroundColor: 'white', padding: 12, borderRadius: 16, gap: 10 },
  check: { borderWidth: 2, borderRadius: 10, paddingVertical: 8, paddingHorizontal: 4 }, checkContent: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  input: { minWidth: 0, backgroundColor: 'white' }, inputOutline: { borderRadius: 8 }, notice: { backgroundColor: '#f0f0f3', padding: 16, borderRadius: 16 },
  warning: { backgroundColor: '#fff5df', padding: 16, borderRadius: 16, gap: 12 },
  pagination: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  dialog: { width: '92%', maxWidth: 640, alignSelf: 'center', borderRadius: 24 }, dialogScroll: { paddingHorizontal: 0, flexShrink: 1 },
  dialogContent: { padding: 20, gap: 14 },
});
