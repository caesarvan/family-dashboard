import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Image, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Card, Checkbox, Dialog, Divider, List, Menu, Portal, ProgressBar, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { openPhotosProvider } from '../lib/navigation';
import type { ScreenProps } from '../lib/types';
import { CONSENT, PhotoReadDiscarded, PhotoReadFence, confirmPhotos, countText, finishPhotoCreate, importLabels, isMediaId, newPhotoRequestId, photoError, previewPath, savedSummary, terminalImport, validateImport, validatePhoto } from '../lib/photos';
import type { ImportDetail, Photo, PhotoAccount, PhotoDevice, PhotoImport, PhotoJourney, PhotoPage, PhotoSession } from '../lib/photos';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Editor = { item: Photo; caption: string; visibility: 'private' | 'shared'; journeyId: string; grants: string[]; tvConsent: boolean; blocked: boolean; message: string };
type Receipt = { path: string; body: Record<string, unknown> };
const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
const imageUri = (item: Photo) => { const path = previewPath(item); return path ? (Platform.OS === 'web' ? path : origin + path) : ''; };
const dirty = (e: Editor) => e.caption !== e.item.caption || e.visibility !== e.item.visibility || e.journeyId !== (e.item.journey?.id || '');
const toggle = (ids: string[], id: string) => ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id];

export default function PhotosScreen(props: ScreenProps) {
  const household = useHousehold();
  const identityKey = (household as typeof household & { identityKey?: string }).identityKey;
  const actor = identityKey || JSON.stringify([props.user.role, props.user.householdId, props.user.id, props.user.auth_version]);
  // The key makes clearing private React state synchronous with identity changes.
  if (props.user.role !== 'member') return <EmptyState title="请用成员账户管理相册" description="电视仅能读取单独授予该设备的照片。" />;
  return <PhotoWorkspace key={actor} {...props} identityKey={identityKey} />;
}

function PhotoWorkspace(props: ScreenProps & { identityKey?: string }) {
  const household = useHousehold(); const latest = useRef(household); latest.current = household;
  const theme = useTheme(); const { width, height } = useWindowDimensions();
  const alive = useRef(false); const active = useRef(false); const locked = useRef(false);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  const serial = useRef({ gallery: 0, detail: 0, imports: 0 });
  const [denied, setDenied] = useState(false); const [focused, setFocused] = useState(false);
  const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [scope, setScope] = useState('mine'); const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PhotoPage>({ items: [], total: 0, hasMore: false });
  const [accounts, setAccounts] = useState<PhotoAccount[]>([]); const [accountId, setAccountId] = useState('');
  const [devices, setDevices] = useState<PhotoDevice[]>([]); const [journeys, setJourneys] = useState<PhotoJourney[]>([]);
  const [imports, setImports] = useState<PhotoImport[]>([]); const [importDetail, setImportDetail] = useState<ImportDetail | null>(null);
  const importRef = useRef(importDetail); importRef.current = importDetail;
  const importReadAt = useRef(0);
  const [selected, setSelected] = useState<string[]>([]); const [temporary, setTemporary] = useState(false); const [persist, setPersist] = useState(false);
  const [importOpen, setImportOpen] = useState(false); const [accountMenu, setAccountMenu] = useState(false);
  const [createReceipt, setCreateReceipt] = useState<Receipt | null>(null); const [confirmReceipt, setConfirmReceipt] = useState<Receipt | null>(null);
  const [confirmReview, setConfirmReview] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null); const editorRef = useRef(editor); editorRef.current = editor;
  const [journeyMenu, setJourneyMenu] = useState(false);
  const [decision, setDecision] = useState<'discard' | 'delete' | 'cancel' | null>(null);
  const [clock, setClock] = useState(Date.now());
  const current = () => alive.current && active.current;

  const clearIdentity = () => {
    fence.current.invalidate(); setDenied(true); setPage({ items: [], total: 0, hasMore: false });
    setEditor(null); editorRef.current = null; setImportDetail(null); importRef.current = null;
    setAccounts([]); setDevices([]); setJourneys([]); setImports([]); setSelected([]);
    setCreateReceipt(null); setConfirmReceipt(null); setDecision(null); setError('登录身份已变化，正在重新读取。');
    void latest.current.refresh();
  };
  const failure = (caught: unknown) => {
    if (!current()) return;
    if (caught instanceof PhotoReadDiscarded) { if (caught.message === 'identity') clearIdentity(); return; }
    if (caught instanceof ApiError && [401, 403].includes(caught.status)) { clearIdentity(); return; }
    setError(caught instanceof Error ? caught.message : '暂时无法读取照片，请稍后重试。');
  };
  async function checked<T>(load: () => Promise<T>, valid = () => true) {
    return fence.current.read(load, () => current() && valid());
  }
  async function gallery(nextScope = scope, nextOffset = offset) {
    const ticket = ++serial.current.gallery;
    const data = await checked(async () => {
      const result = await request<PhotoPage>(`/media/items?scope=${nextScope}&limit=24&offset=${nextOffset}`);
      if (!Array.isArray(result.items) || result.items.length > 24) throw new Error('图库数据无法核对。');
      result.items.forEach(validatePhoto); return result;
    }, () => ticket === serial.current.gallery);
    setPage(data); setLoading(false);
  }
  async function support() {
    const [accountData, deviceData, journeyData, importData] = await checked(() => Promise.all([
      request<{ accounts: PhotoAccount[] }>('/accounts'), request<PhotoDevice[]>('/devices'),
      request<{ journeys: PhotoJourney[] }>('/journeys'), request<{ items: PhotoImport[] }>('/media/imports?limit=10&offset=0'),
    ]));
    const google = accountData.accounts.filter(a => a.provider === 'google');
    setAccounts(google); setAccountId(previous => google.some(a => a.id === previous) ? previous : google.find(a => a.capabilities?.photos && !a.needsReauth)?.id || google[0]?.id || '');
    setDevices(deviceData.filter(d => isMediaId(d.id))); setJourneys(journeyData.journeys.filter(j => isMediaId(j.id))); setImports(importData.items);
  }
  async function readImport(id: string, reset = false) {
    if (!isMediaId(id)) return;
    const ticket = ++serial.current.imports;
    const data = await checked(async () => validateImport(await request<ImportDetail>(`/media/imports/${id}`)), () => ticket === serial.current.imports);
    const changed = importRef.current?.import.id !== id;
    importRef.current = data; importReadAt.current = Date.now(); setImportDetail(data);
    if (changed || reset) { setSelected(data.items.map(item => item.id)); setPersist(false); setConfirmReceipt(null); setConfirmReview(false); }
    else setSelected(previous => previous.filter(id => data.items.some(item => item.id === id)));
    if (data.import.state === 'confirmed') { setConfirmReceipt(null); setConfirmReview(false); setPersist(false); }
  }
  async function readEditor(id: string, keepDraft = false) {
    const ticket = ++serial.current.detail;
    const data = await checked(async () => {
      const { item } = await request<{ item: Photo }>(`/media/items/${id}`); validatePhoto(item);
      const grants = item.canManage ? await request<{ revision: number; deviceIds: string[] }>(`/media/items/${id}/tv-grants`) : { revision: item.revision, deviceIds: [] };
      if (grants.revision !== item.revision) throw new Error('照片正在更新，请重新打开核对。');
      return { item, grants: grants.deviceIds };
    }, () => ticket === serial.current.detail);
    setEditor(previous => ({ item: data.item, caption: keepDraft && previous ? previous.caption : data.item.caption,
      visibility: keepDraft && previous ? previous.visibility : data.item.visibility,
      journeyId: keepDraft && previous ? previous.journeyId : data.item.journey?.id || '',
      grants: data.grants, tvConsent: false, blocked: false,
      message: keepDraft ? '已读取当前版本，保留你的文字、旅行和共享选择；请比较后再保存。电视勾选已按当前权限重新读取。' : '' }));
  }
  async function readAction(action: () => Promise<void>) {
    setError(''); try { await action(); } catch (caught) { failure(caught); }
    finally { if (current()) setLoading(false); }
  }
  async function write(path: string, method: string, body: Record<string, unknown>, done: (data: any) => Promise<void>, category: 'create' | 'confirm' | 'editor' | 'other' = 'other') {
    if (locked.current || !current()) return;
    locked.current = true; setBusy(true); setError(''); setNotice('');
    let writeReturned = false;
    try {
      const result = await latest.current.mutate(path, method, body);
      writeReturned = true;
      await checked(async () => result);
      await done(result);
      void latest.current.refresh();
    } catch (caught) {
      if (!current()) return;
      if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) { failure(caught); return; }
      const unknown = writeReturned || !(caught instanceof ApiError) || caught.status === 0 || caught.status >= 500;
      if (category === 'editor') setEditor(value => value ? { ...value, blocked: true, message: unknown ? '提交结果尚不明确。草稿仍保留，请读取最新版本核对，不会自动重发。' : '修改未保存。草稿仍保留，请读取最新版本核对。' } : null);
      if (category === 'confirm' && !unknown) { setConfirmReview(true); }
      if (category === 'create' && !unknown) setCreateReceipt(null);
      setError(unknown ? '结果尚未确认。请核对当前状态；页面不会自动重发写入。' : caught instanceof Error ? caught.message : '操作未完成。');
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }

  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => {
    active.current = true; setFocused(true); setLoading(true);
    void readAction(async () => { await Promise.all([gallery(), support()]); });
    return () => { active.current = false; setFocused(false); fence.current.invalidate(); };
  }, [scope, offset]));
  useEffect(() => {
    if (!focused || denied) return;
    let running = false;
    const timer = setInterval(() => {
      setClock(Date.now());
      if (running || locked.current || typeof document !== 'undefined' && document.hidden) return;
      running = true;
      void (async () => {
        try {
          // Recheck permissions while the page is visible. Never replace a draft.
          await gallery();
          const row = importRef.current?.import;
          if (row && !terminalImport(row.state)) await readImport(row.id);
          const detail = editorRef.current;
          if (detail) {
            const fresh = await checked(() => request<{ item: Photo }>(`/media/items/${detail.item.id}`), () => editorRef.current?.item.id === detail.item.id);
            validatePhoto(fresh.item);
            if (fresh.item.revision !== detail.item.revision) setEditor(e => e?.item.id === detail.item.id ? { ...e, blocked: true, message: '照片已更新。你的草稿仍保留，请读取当前版本后核对。' } : e);
          }
        } catch (caught) {
          if (caught instanceof ApiError && [404, 410].includes(caught.status)) { setEditor(null); setImportDetail(null); setError('记录已移除或不再可见。'); }
          else failure(caught);
        } finally { running = false; }
      })();
    }, 5000);
    return () => clearInterval(timer);
  }, [focused, scope, offset, denied]);

  const update = (patch: Partial<Editor>) => setEditor(value => value ? { ...value, ...patch } : null);
  const connect = () => void write('/accounts/google-photos/bind', 'POST', accountId ? { accountId } : {}, async data => {
    if (!openPhotosProvider(data.url, 'authorize')) throw new Error('授权链接无法安全打开，请刷新核对。');
  });
  function create() {
    let receipt = createReceipt;
    if (!receipt) {
      const account = accounts.find(a => a.id === accountId);
      if (!temporary || !account?.capabilities?.photos || account.needsReauth) { setError('请先连接照片来源，并同意临时处理本次选择。'); return; }
      receipt = { path: '/media/imports', body: { requestId: newPhotoRequestId(), accountId, consentVersion: CONSENT, allowTemporaryProcessing: true } };
      setCreateReceipt(receipt);
    }
    void write(receipt.path, 'POST', receipt.body, async data => {
      await finishPhotoCreate(data.import.id, id => readImport(id, true), support, () => { setCreateReceipt(null); setTemporary(false); });
    }, 'create');
  }
  function saveSelection() {
    if (!importDetail || confirmReview || !persist) return;
    const receipt = confirmReceipt || { path: `/media/imports/${importDetail.import.id}/confirm`, body: confirmPhotos(importDetail.import, selected, newPhotoRequestId()) };
    setConfirmReceipt(receipt);
    void write(receipt.path, 'POST', receipt.body, async () => { await readImport(importDetail.import.id); await gallery(); await support(); setNotice('保存结果已更新，仅留下本次明确勾选的照片。'); }, 'confirm');
  }
  function saveEditor() {
    if (!editor || editor.blocked) return;
    const item = editor.item;
    void write(`/media/items/${item.id}`, 'PATCH', { revision: item.revision, caption: editor.caption, visibility: editor.visibility, journeyId: editor.journeyId || null }, async () => {
      await readEditor(item.id); await gallery(); setNotice('照片设置已保存。');
    }, 'editor');
  }
  function saveGrants(revoke = false) {
    if (!editor || editor.blocked || dirty(editor)) return;
    const ids = revoke ? [] : editor.grants;
    if (ids.length && !editor.tvConsent) { setError('请确认允许选中的电视展示这张照片。'); return; }
    void write(`/media/items/${editor.item.id}/tv-grants`, 'PUT', { revision: editor.item.revision, deviceIds: ids, consentVersion: CONSENT, allowTvDisplay: !!ids.length }, async () => {
      await readEditor(editor.item.id); setNotice(ids.length ? '已保存电视展示范围。' : '已收回全部电视展示。');
    }, 'editor');
  }
  function decide() {
    const action = decision; setDecision(null);
    if (action === 'discard') { serial.current.detail++; setEditor(null); }
    if (action === 'delete' && editor) void write(`/media/items/${editor.item.id}`, 'DELETE', { revision: editor.item.revision }, async () => { setEditor(null); await gallery(); setNotice('已移除看板副本，Google Photos 原图保留。'); }, 'editor');
    if (action === 'cancel' && importDetail) void write(`/media/imports/${importDetail.import.id}`, 'DELETE', { revision: importDetail.import.revision }, async () => {
      setConfirmReceipt(null); setConfirmReview(false); setPersist(false); await readImport(importDetail.import.id); await support();
    });
  }
  const account = accounts.find(value => value.id === accountId);
  const row = importDetail?.import;
  const expired = !!row && Date.parse(row.expiresAt) <= clock && !terminalImport(row.state);
  const canSelect = !!row?.canConfirm && !expired && row.state === 'awaiting_confirmation';
  const activeImport = imports.some(item => !terminalImport(item.state)) || !!row && !terminalImport(row.state);
  const columns = width < 540 ? 2 : width < 960 ? 3 : 4;
  const cardWidth = `${100 / columns - 1.7}%` as `${number}%`;
  const closeEditor = () => { if (busy) return; if (editor && (dirty(editor) || editor.blocked)) setDecision('discard'); else { serial.current.detail++; setEditor(null); } };
  const renderPhoto = (item: Photo, label: string, large = false) => <Image accessibilityLabel={label} source={{ uri: imageUri(item) }} style={large ? styles.detailImage : styles.thumbnail} resizeMode={large ? 'contain' : 'cover'} />;
  const checkbox = (label: string, checked: boolean, change: () => void, disabled = false) => <Checkbox.Item label={label} status={checked ? 'checked' : 'unchecked'} onPress={change} disabled={disabled} position="leading" labelStyle={styles.checkLabel} style={styles.checkRow} />;
  if (denied) return <EmptyState title="正在核对登录身份" description="原账户的照片和编辑内容已清空。" />;
  if (!focused) return null;
  return <View style={styles.page}>
    <PageHeader title="相册" description="自己留下，按你的选择分享。" action={<View style={styles.actions}><Button accessibilityLabel="电视与播放" mode="outlined" icon="television" disabled={busy || !!editor || importOpen || !!createReceipt || !!confirmReceipt} onPress={() => props.onNavigate('devices')}>电视与播放</Button><Button accessibilityLabel="选择照片" mode="contained" icon="plus" disabled={busy} onPress={() => setImportOpen(value => !value)}>选择照片</Button></View>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {importOpen && <SectionCard title="从 Google Photos 选择" action={<Button disabled={busy} onPress={() => setImportOpen(false)}>收起</Button>}>
      <View style={styles.stack}>
        <Text variant="bodyMedium">最多 20 张，仅处理你本次选择的照片，不扫描整个图库。视频暂不支持播放。</Text>
        <Menu visible={accountMenu} onDismiss={() => setAccountMenu(false)} anchor={<Button mode="outlined" disabled={busy || !!createReceipt} onPress={() => setAccountMenu(true)}>{account ? account.name || account.email || 'Google 账户' : '选择照片来源'}</Button>}>
          {accounts.map(value => <Menu.Item key={value.id} title={value.name || value.email || 'Google 账户'} onPress={() => { setAccountId(value.id); setAccountMenu(false); }} />)}
          {!accounts.length && <Menu.Item title="尚未连接 Google Photos" disabled />}
        </Menu>
        <View style={styles.actions}><Text>{account?.capabilities?.photos && !account.needsReauth ? '照片来源已连接' : '需要连接或更新照片授权'}</Text><Button disabled={busy || !!createReceipt} onPress={connect}>{account?.capabilities?.photos && !account.needsReauth ? '更新授权' : '连接 Google Photos'}</Button></View>
        <Text variant="bodySmall">Google 保留原图；在账户设置中解绑照片来源会删除这里对应的展示副本。</Text>
        {checkbox('允许临时处理本次选择，供我预览确认；未保存的内容最迟 24 小时后清理。', temporary, () => setTemporary(v => !v), busy || !!createReceipt)}
        <Button mode="contained" disabled={busy || (!createReceipt && (!temporary || activeImport || !account?.capabilities?.photos || account.needsReauth))} onPress={() => { try { create(); } catch (caught) { failure(caught); } }}>{createReceipt ? '核对 / 重试原选择请求' : '开始选择照片'}</Button>
        {!!createReceipt && <Text>上一请求结果未确认；此按钮沿用原请求标识，不会自动重复创建。</Text>}
        {activeImport && !row && <Text>已有进行中的选择，请从下方继续。</Text>}
        {imports.length > 0 && <List.Accordion title="最近的选择" description="继续选片或查看保存结果">
          {imports.map(item => <List.Item key={item.id} title={importLabels[item.state] || '选择记录'} description={item.state === 'confirmed' ? savedSummary(item) : new Date(item.createdAt).toLocaleString('zh-CN')} onPress={() => { if (!busy && !confirmReceipt) void readAction(() => readImport(item.id)); }} />)}
        </List.Accordion>}
        {!!row && <View style={styles.stack}>
          <Divider /><Text variant="titleMedium" accessibilityRole="header">{importLabels[row.state]}</Text>
          {row.resultsState === 'unknown' ? <Text>{row.state === 'confirmed' ? savedSummary(row) : terminalImport(row.state) ? '本次其他处理结果未记录。' : '正在等待本次选择的处理结果。'}</Text> : <>
            <Text accessibilityLiveRegion="polite">本次选择 {countText(row.counts.selected)} · 成功 {countText(row.counts.ready)} · 失败 {countText(row.counts.failed)} · 跳过 {countText(row.counts.skipped)} · 处理中 {countText(row.counts.pending)}</Text>
            {row.state === 'confirmed' && <Text>{savedSummary(row)} · 成功但未勾选 {countText(row.counts.unselected)}</Text>}
            {!!row.counts.selected && row.counts.pending !== null && <ProgressBar progress={(row.counts.selected - row.counts.pending) / row.counts.selected} />}
            {row.results.filter(result => ['failed', 'skipped'].includes(result.status)).map(result => <Text key={result.position}>第 {result.position} 张：{photoError(result.error?.code)}</Text>)}
          </>}
          {!!row.error && <Text style={{ color: theme.colors.error }}>{photoError(row.error.code)}</Text>}
          {row.state === 'waiting_selection' && !expired && <><Button mode="contained" icon="open-in-new" disabled={busy || clock - importReadAt.current > 15000} onPress={() => {
            if (!current() || importRef.current?.import.id !== row.id || importRef.current.import.state !== 'waiting_selection' || Date.parse(row.expiresAt) <= Date.now() || Date.now() - importReadAt.current > 15000) { setError('请先刷新本次选择的状态，再打开选片页。'); return; }
            // Keep window.open in the user gesture; refresh after opening this
            // already identity-checked, short-lived session (no new POST).
            if (!openPhotosProvider(row.pickerUri || '', 'picker')) setError('选片链接无法安全打开，请刷新状态。');
            else void readAction(() => readImport(row.id));
          }}>打开 Google Photos 选片页</Button><Text variant="bodySmall">选完后回到这里。未打开新页面时，可再次点击同一个按钮；不会创建新的选片会话。</Text></>}
          {row.state === 'create_unknown' && <Text>Google 可能已创建选片页，但未取得结果。不会自动新建；请取消本记录，再明确开始一次选择。</Text>}
          {expired && <Text>临时预览已过期，请刷新后重新选择。</Text>}
          {canSelect && <>
            <View style={styles.grid}>{importDetail.items.map(candidate => <Card key={candidate.id} mode="outlined" style={[styles.photoCard, { width: cardWidth }]}>
              {renderPhoto(candidate.item, '本次选择的照片')}
              {checkbox(candidate.status === 'duplicate' ? '已有，可复用' : '保留这张', selected.includes(candidate.id), () => setSelected(ids => toggle(ids, candidate.id)), busy || !!confirmReceipt)}
            </Card>)}</View>
            <Text variant="titleSmall">仅将当前勾选的 {confirmReceipt ? (confirmReceipt.body.itemIds as string[]).length : selected.length} 张保存到私密相册。</Text>
            <Text variant="bodySmall">未勾选的预览不会新增保存；已存在的照片不会因此删除。</Text>
            {checkbox('同意将勾选照片的展示副本持久保存在相册中。之后另行设置家庭共享和电视展示。', persist, () => setPersist(v => !v), busy || !!confirmReceipt)}
            {confirmReview ? <Button disabled={busy} onPress={() => void readAction(() => readImport(row.id, true))}>读取最新选择，重新核对</Button> : <Button mode="contained" disabled={busy || !persist || !selected.length} onPress={() => { try { saveSelection(); } catch (caught) { failure(caught); } }}>{confirmReceipt ? '核对 / 重试原保存请求' : `保存选中的 ${selected.length} 张`}</Button>}
          </>}
          <View style={styles.actions}><Button disabled={busy} onPress={() => void readAction(() => readImport(row.id))}>刷新状态</Button>{row.state !== 'confirmed' && row.state !== 'cancelled' && <Button disabled={busy || !!confirmReceipt} onPress={() => setDecision('cancel')}>取消本次选择</Button>}</View>
        </View>}
      </View>
    </SectionCard>}
    <View style={styles.actions}><SegmentedButtons style={styles.scope} value={scope} onValueChange={value => { if (!busy) { setScope(value); setOffset(0); setLoading(true); } }} buttons={[{ value: 'mine', label: '我的照片', disabled: busy }, { value: 'shared', label: '家人共享', disabled: busy }]} /><Button icon="refresh" disabled={busy} onPress={() => void readAction(async () => { await Promise.all([gallery(), support()]); })}>刷新</Button></View>
    {loading ? <ActivityIndicator accessibilityLabel="正在读取相册" /> : !page.items.length ? <EmptyState title={scope === 'mine' ? '把想回看的照片留下' : '还没有家人共享的照片'} description={scope === 'mine' ? '先选择照片，预览后再确认保存。默认只有你能看见。' : '家人明确共享后，照片才会出现在这里。'} action={scope === 'mine' ? <Button onPress={() => setImportOpen(true)}>从 Google Photos 选择</Button> : undefined} /> : <View style={styles.grid}>{page.items.map(item => <Card key={item.id} mode="outlined" accessibilityLabel={'查看照片：' + (item.caption || '未添加说明')} onPress={() => { if (!busy) void readAction(() => readEditor(item.id)); }} style={[styles.photoCard, { width: cardWidth }]}>
      {renderPhoto(item, item.caption || '已保存的照片')}<Card.Content style={styles.photoCopy}><Text variant="bodyMedium">{item.caption || '未添加说明'}</Text><Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{item.visibility === 'private' ? '仅我自己' : '家庭共享'}{item.journey ? ' · ' + item.journey.title : ''}</Text></Card.Content>
    </Card>)}</View>}
    <View style={styles.actions}><Text variant="bodySmall">共 {page.total} 张 · 第 {Math.floor(offset / 24) + 1} 页</Text><Button disabled={!offset || busy} onPress={() => setOffset(v => Math.max(0, v - 24))}>上一页</Button><Button disabled={!page.hasMore || busy} onPress={() => setOffset(v => v + 24)}>下一页</Button></View>
    <Portal><Dialog visible={!!editor} onDismiss={closeEditor} dismissable={!busy} style={[styles.dialog, { maxHeight: height - 40 }]}>
      <Dialog.Title>照片详情</Dialog.Title>
      <Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent} keyboardShouldPersistTaps="handled">
        {editor && <>
          {renderPhoto(editor.item, editor.item.caption || '照片详情预览', true)}
          {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
          {!!editor.message && <Text accessibilityLiveRegion="polite">{editor.message}</Text>}
          {editor.item.canManage ? <>
            <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} label="照片说明" accessibilityLabel="照片说明" multiline maxLength={500} value={editor.caption} disabled={busy} onChangeText={caption => update({ caption })} />
            <Text variant="titleSmall">谁能查看</Text><SegmentedButtons value={editor.visibility} onValueChange={visibility => update({ visibility: visibility as 'private' | 'shared', tvConsent: false })} buttons={[{ value: 'private', label: '仅我自己', disabled: busy }, { value: 'shared', label: '家庭成员', disabled: busy }]} />
            <Text variant="bodySmall">家庭共享包括照片和说明。改回私密会同时收回全部电视展示。</Text>
            <Menu visible={journeyMenu} onDismiss={() => setJourneyMenu(false)} anchor={<Button mode="outlined" disabled={busy} onPress={() => setJourneyMenu(true)}>{editor.journeyId ? journeys.find(j => j.id === editor.journeyId)?.trip?.title || journeys.find(j => j.id === editor.journeyId)?.plan?.title || editor.item.journey?.title || '已关联旅行' : '关联旅行（可选）'}</Button>}>
              <Menu.Item title="不关联旅行" onPress={() => { update({ journeyId: '' }); setJourneyMenu(false); }} />
              {journeys.map(journey => <Menu.Item key={journey.id} title={journey.trip?.title || journey.plan?.title || '旅行'} onPress={() => { update({ journeyId: journey.id }); setJourneyMenu(false); }} />)}
            </Menu>
            <Text variant="bodySmall">解除已有旅行关联会自动转为私密并收回电视许可；关联照片不会标记地点到访。</Text>
            {editor.blocked ? <Button disabled={busy} onPress={() => void readAction(() => readEditor(editor.item.id, true))}>读取当前版本，保留我的修改</Button> : <Button mode="contained" disabled={busy || !dirty(editor)} onPress={saveEditor}>保存照片设置</Button>}
            <Divider /><List.Accordion title="电视展示" description="家庭共享后，再选择具体电视">
              <Text variant="bodySmall">先保存上方设置。只有勾选并确认的电视可以展示这张照片；电视配对不等于获得全部相册。</Text>
              {devices.length ? devices.map(device => <React.Fragment key={device.id}>{checkbox(device.name || '家庭电视', editor.grants.includes(device.id), () => update({ grants: toggle(editor.grants, device.id), tvConsent: false }), busy || editor.blocked || dirty(editor) || editor.item.visibility !== 'shared')}</React.Fragment>) : <Text>尚未配对电视，可在设备设置中添加。</Text>}
              {checkbox('允许选中的电视展示这张照片。', editor.tvConsent, () => update({ tvConsent: !editor.tvConsent }), busy || editor.blocked || dirty(editor) || editor.item.visibility !== 'shared')}
              <Button mode="outlined" disabled={busy || editor.blocked || dirty(editor) || editor.item.visibility !== 'shared' || !!editor.grants.length && !editor.tvConsent} onPress={() => saveGrants()}>保存电视范围</Button>
              <Button disabled={busy || editor.blocked || dirty(editor)} onPress={() => saveGrants(true)}>收回全部电视展示</Button>
            </List.Accordion>
            <Button textColor={theme.colors.error} disabled={busy || editor.blocked} onPress={() => setDecision('delete')}>移除看板副本</Button><Text variant="bodySmall">Google Photos 原图保留。</Text>
          </> : <><Text variant="titleMedium">{editor.item.caption || '家庭共享照片'}</Text><Text>由上传者管理，你可以查看当前共享的照片。</Text>{!!editor.item.journey && <Text>关联旅行：{editor.item.journey.title}</Text>}</>}
        </>}
      </ScrollView></Dialog.ScrollArea><Dialog.Actions><Button disabled={busy} onPress={closeEditor}>关闭</Button></Dialog.Actions>
    </Dialog>
    <Dialog visible={!!decision} onDismiss={() => setDecision(null)} style={styles.dialog}><Dialog.Title>{decision === 'discard' ? '离开照片详情？' : decision === 'delete' ? '移除这张照片？' : '取消本次选择？'}</Dialog.Title><Dialog.Content><Text>{decision === 'discard' ? '未保存的输入将丢弃。关闭页面不会撤销已经提交的操作。' : decision === 'delete' ? '将删除看板副本，并收回家庭共享及电视展示。Google Photos 原图保留。' : '清理未确认的临时预览，Google Photos 原图保留。已经发出的请求仍会由服务器处理。'}</Text></Dialog.Content><Dialog.Actions><Button onPress={() => setDecision(null)}>返回</Button><Button onPress={decide}>确认</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16 }, stack: { gap: 14 }, actions: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10 },
  scope: { flexGrow: 1, minWidth: 240 }, grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 16 },
  photoCard: { borderRadius: 12, overflow: 'hidden' }, thumbnail: { width: '100%', aspectRatio: 1, backgroundColor: '#f0f0f3' },
  photoCopy: { paddingHorizontal: 12, paddingVertical: 12, gap: 6 }, checkLabel: { fontSize: 14, lineHeight: 21, textAlign: 'left' }, checkRow: { paddingHorizontal: 0 },
  dialog: { width: '92%', maxWidth: 620, alignSelf: 'center', borderRadius: 12 }, dialogScroll: { paddingHorizontal: 0, flexShrink: 1 },
  dialogContent: { padding: 20, gap: 16 }, detailImage: { width: '100%', height: 250, borderRadius: 8, backgroundColor: '#f0f0f3' },
});
