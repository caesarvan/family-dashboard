import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Image, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Card, Dialog, Divider, List, Menu, Portal, ProgressBar, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { memberIdentity } from '../lib/sessionIdentity.ts';
import { openPhotosProvider } from '../lib/navigation';
import type { ScreenProps } from '../lib/types';
import { CONSENT, PhotoReadDiscarded, PhotoReadFence, confirmPhotos, countText, photoSignature, finishPhotoCreate, importLabels, isMediaId, newPhotoRequestId, photoError, previewPath, savedSummary, terminalImport, validateImport, validatePhoto, videoDescription, photoOriginalNotice, photoSourceLabel } from '../lib/photos';
import type { ImportDetail, Photo, PhotoAccount, PhotoDevice, PhotoImport, PhotoJourney, PhotoPage, PhotoSession } from '../lib/photos';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import PhotoConfirmedDate from '../components/PhotoConfirmedDate';
import { canConfirmPhotoDate, confirmedDateBody } from '../lib/photoConfirmedDate';
import PhotoJourneySuggestions from '../components/PhotoJourneySuggestions';
import PhotoDuplicateHints from '../components/PhotoDuplicateHints';
import { duplicatePhotoKey, fetchPhotoDuplicates, verifyDuplicatePhotos, withPhotoDuplicateRead, type PhotoDuplicateRead, type PhotoDuplicates } from '../lib/photoDuplicates';
import MemberVideoPlayer from '../components/MemberVideoPlayer';
import LocalPhotoImportPanel from '../components/LocalPhotoImportPanel';
import { LocalPhotoUpload } from '../lib/localPhotoUpload';
import { photoSuggestionBody, readPhotoJourneySuggestions, type PhotoJourneySuggestions as Suggestions } from '../lib/photoJourneySuggestions';
import { memoryDisplayDate, memoryDateLabel, unknownMemoryDates, memoryOffsetAfterDateChange, photoMemoriesQuery, readPhotoMemories, type PhotoMemories } from '../lib/photoMemories';

type Editor = { dateDraft: string; dateReview: boolean; dateMessage: string; item: Photo; caption: string; visibility: 'private' | 'shared'; journeyId: string; grants: string[]; savedGrants: string[]; tvConsent: boolean; blocked: boolean; suggestionReview: boolean; message: string };
type Receipt = { path: string; body: Record<string, unknown> };
const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
const imageUri = (item: Photo) => { const path = previewPath(item); return path ? (Platform.OS === 'web' ? path : origin + path) : ''; };
const dirty = (e: Editor) => e.caption !== e.item.caption || e.visibility !== e.item.visibility || e.journeyId !== (e.item.journey?.id || '');
const settingsDraft = (e: Editor) => dirty(e) || e.tvConsent || [...e.grants].sort().join(',') !== [...e.savedGrants].sort().join(',');
const dateDirty = (e: Editor) => e.dateDraft !== (e.item.userConfirmedDate ?? '');
const anyDraft = (e: Editor) => settingsDraft(e) || dateDirty(e);
const draftKey = (e: Editor) => JSON.stringify([e.item.id, e.item.revision, e.caption, e.visibility, e.journeyId, e.grants, e.tvConsent, e.dateDraft]);
const toggle = (ids: string[], id: string) => ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id];

type Props = ScreenProps & { initialPhotoId?: string; onBack?: () => void };
export default function PhotosScreen(props: Props) {
  const household = useHousehold();
  const identityKey = (household as typeof household & { identityKey?: string }).identityKey;
  const actor = identityKey || memberIdentity(props.user);
  // The key makes clearing private React state synchronous with identity changes.
  if (props.user.role !== 'member') return <EmptyState title="请用成员账户管理相册" description="电视仅能读取单独授予该设备的照片。" />;
  if (props.initialPhotoId !== undefined && !isMediaId(props.initialPhotoId)) return <EmptyState title="照片入口无法核对" action={props.onBack ? <Button onPress={props.onBack}>返回搜索</Button> : undefined} />;
  return <PhotoWorkspace key={actor + ':' + (props.initialPhotoId || '')} {...props} identityKey={identityKey} />;
}

function PhotoWorkspace(props: Props & { identityKey?: string }) {
  const household = useHousehold(); const latest = useRef(household); latest.current = household;
  const theme = useTheme(); const { width, height } = useWindowDimensions();
  const alive = useRef(false); const active = useRef(false); const locked = useRef(false);
  const routeActive = useRef(false), epoch = useRef(0), deniedRef = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const windowFocused = useRef(typeof document === 'undefined' || document.hasFocus()), pageHidden = useRef(false), requests = useRef(new Set<AbortController>());
  const freshSession = useRef<PhotoSession | null>(null);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  const suggestionFence = useRef(new PhotoReadFence(async () => {
    const session = await suggestionRequest<PhotoSession>('/me'); freshSession.current = session; return session;
  }, props.user, props.identityKey));
  const serial = useRef({ gallery: 0, detail: 0, imports: 0 });
  const initialPhoto = useRef(props.initialPhotoId || '');
  const [denied, setDenied] = useState(false); const [focused, setFocused] = useState(false);
  const [writeBusy, setBusy] = useState(false); const [localBusy, setLocalBusy] = useState(false);
  const busy = writeBusy || localBusy; const [loading, setLoading] = useState(true);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [scope, setScope] = useState('mine'); const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PhotoPage>({ items: [], total: 0, hasMore: false });
  const [memories, setMemories] = useState<PhotoMemories | null>(null);
  const memoryDate = useRef<string | null>(null);
  const [accounts, setAccounts] = useState<PhotoAccount[]>([]); const [accountId, setAccountId] = useState('');
  const [devices, setDevices] = useState<PhotoDevice[]>([]); const [journeys, setJourneys] = useState<PhotoJourney[]>([]);
  const [imports, setImports] = useState<PhotoImport[]>([]); const [importDetail, setImportDetail] = useState<ImportDetail | null>(null);
  const importRef = useRef(importDetail); importRef.current = importDetail;
  const importReadAt = useRef(0);
  const [selected, setSelected] = useState<string[]>([]); const [temporary, setTemporary] = useState(false); const [persist, setPersist] = useState(false);
  const [importSource, setImportSource] = useState('google');
  const localUpload = useRef<LocalPhotoUpload | null>(null);
  const [importOpen, setImportOpen] = useState(false); const [accountMenu, setAccountMenu] = useState(false);
  const [createReceipt, setCreateReceipt] = useState<Receipt | null>(null); const [confirmReceipt, setConfirmReceipt] = useState<Receipt | null>(null);
  const [confirmReview, setConfirmReview] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null); const editorRef = useRef(editor); editorRef.current = editor;
  const [suggestionVersion, setSuggestionVersion] = useState(0);
  const duplicateSerial = useRef(0);
  const duplicateIdentity = useRef(props.identityKey);
  const [duplicates, setDuplicates] = useState<{ target: Photo; page: PhotoDuplicates } | null>(null);
  const duplicatesRef = useRef(duplicates); duplicatesRef.current = duplicates;
  const [duplicateReturn, setDuplicateReturn] = useState<{ id: string; offset: number } | null>(null);
  const duplicateReturnRef = useRef(duplicateReturn); duplicateReturnRef.current = duplicateReturn;
  function clearDuplicates() { ++duplicateSerial.current; duplicatesRef.current = null; setDuplicates(null); }
  function resetDuplicateReturn() { duplicateReturnRef.current = null; setDuplicateReturn(null); }
  const [journeyMenu, setJourneyMenu] = useState(false);
  const [decision, setDecision] = useState<'discard' | 'delete' | 'cancel' | null>(null);
  const [clock, setClock] = useState(Date.now());
  const available = () => foreground.current && windowFocused.current && !pageHidden.current
    && (typeof document === 'undefined' || !document.hidden) && (typeof navigator === 'undefined' || navigator.onLine !== false) && latest.current.online;
  const current = () => alive.current && active.current && routeActive.current && !deniedRef.current && available()
    && (!props.identityKey || latest.current.identityKey === props.identityKey);

  if (!localUpload.current) localUpload.current = new LocalPhotoUpload({ user: props.user, identityKey: props.identityKey,
    current: () => current() && !locked.current, denied: () => clearIdentity(),
    review: async id => { await readImport(id, true); await support(); },
  });
  useEffect(() => localUpload.current!.subscribe(() => setLocalBusy(localUpload.current!.view.busy)), []);

  // This local transport covers identity, source and photo suggestion reads. The URL
  // is fixed to this origin, and both JSON consumption and lifetime are bounded.
  async function suggestionRequest<T>(path: string, body?: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
    if (!(path === '/me' || path === '/accounts' || /^\/media\/items\/[a-f0-9]{24}(?:\/journey-suggestions\?dateMode=confirmed-or-source|\/tv-grants|\/duplicates\?limit=20&offset=\d{1,4})?$/.test(path))
      || body && !/^\/media\/items\/[a-f0-9]{24}$/.test(path)) throw new Error('照片请求无法核对。');
    const controller = new AbortController(); requests.current.add(controller);
    const timeout = setTimeout(() => controller.abort(), 20000);
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true }); if (signal?.aborted) abort();
    try {
      const response = await fetch('/api' + path, { method: body ? 'PATCH' : 'GET', mode: 'same-origin', credentials: 'same-origin',
        cache: 'no-store', redirect: 'error', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(body ? { 'X-CSRF-Token': freshSession.current?.csrf || '' } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}) });
      if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json') || !response.body) throw new ApiError('照片响应无法核对。', response.ok ? 0 : response.status);
      const reader = response.body.getReader(), decoder = new TextDecoder(); let text = '', bytes = 0;
      try {
        for (;;) { const chunk = await reader.read(); if (chunk.done) break; bytes += chunk.value.byteLength;
          if (bytes > 1000000) { await reader.cancel(); throw new ApiError('照片响应过大，请重新读取。'); }
          text += decoder.decode(chunk.value, { stream: true }); }
      } finally { reader.releaseLock(); }
      let value: any; try { value = JSON.parse(text + decoder.decode()); } catch { throw new ApiError('照片响应无法核对。', response.ok ? 0 : response.status); }
      if (!response.ok) throw new ApiError(response.status === 409 ? '照片或旅行已变化，请重新核对。' : '暂时无法读取或保存照片。', response.status, typeof value?.code === 'string' ? value.code : '');
      return value as T;
    } catch (caught) { if (caught instanceof ApiError) throw caught; throw new ApiError('连接中断或超时，请重新核对。'); }
    finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort); requests.current.delete(controller); }
  }

  const clearIdentity = () => {
    clearDuplicates(); resetDuplicateReturn();
    deniedRef.current = true; localUpload.current?.dispose(); fence.current.invalidate(); suggestionFence.current.invalidate(); requests.current.forEach(value => value.abort()); setDenied(true); setPage({ items: [], total: 0, hasMore: false });
    memoryDate.current = null; setMemories(null); setEditor(null); editorRef.current = null; setImportDetail(null); importRef.current = null;
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
    const ticket = epoch.current;
    const live = () => current() && ticket === epoch.current && valid();
    try { return await fence.current.read(load, live); }
    catch (caught) { if (!live()) throw new PhotoReadDiscarded(); throw caught; }
  }
  async function gallery(nextScope = scope, nextOffset = offset) {
    const ticket = ++serial.current.gallery;
    const data = await checked(async () => {
      if (nextScope === 'memories') {
        const memories = readPhotoMemories(await request(photoMemoriesQuery(nextOffset)), nextOffset);
        if (memories.version !== 2) throw new Error('回看日期格式无法核对，请重新读取。');
        return { items: memories.items.map(row => row.item), total: memories.total, hasMore: memories.hasMore, memories };
      }
      const result = await request<PhotoPage>(`/media/items?scope=${nextScope}&limit=24&offset=${nextOffset}`);
      if (!Array.isArray(result.items) || result.items.length > 24) throw new Error('图库数据无法核对。');
      result.items.forEach(validatePhoto); return { ...result, memories: null };
    }, () => ticket === serial.current.gallery);
    if (data.memories) {
      const next = memoryOffsetAfterDateChange(memoryDate.current, data.memories);
      memoryDate.current = data.memories.referenceDate;
      if (next !== nextOffset) {
        setPage({ items: [], total: 0, hasMore: false }); setMemories(null); setLoading(true);
        // The existing focus lifecycle reads offset 0 with a fresh identity
        // fence. Never briefly install the new day's second page as its start.
        setOffset(next); return;
      }
    }
    setPage({ items: data.items, total: data.total, hasMore: data.hasMore }); setMemories(data.memories); setLoading(false);
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
    const result = await checked(async () => validateImport(await request<ImportDetail>(`/media/imports/${id}`)), () => ticket === serial.current.imports);
    const ended = terminalImport(result.import.state);
    const data = ended ? { ...result, items: [] } : result;
    const changed = importRef.current?.import.id !== id;
    localUpload.current?.observe(data);
    if (changed || reset) setImportSource(data.import.source === 'local-upload' ? 'device' : 'google');
    importRef.current = data; importReadAt.current = Date.now(); setImportDetail(data);
    if (changed || reset) { setSelected(data.items.map(item => item.id)); setPersist(false);
      if (!ended || data.import.state === 'confirmed') { setConfirmReceipt(null); setConfirmReview(false); } }
    else setSelected(previous => previous.filter(id => data.items.some(item => item.id === id)));
    if (ended) { setSelected([]); setPersist(false);
      if (data.import.state === 'confirmed') { setConfirmReceipt(null); setConfirmReview(false); } }
  }
  async function duplicateRead<T>(action: (read: PhotoDuplicateRead) => Promise<T>, valid: () => boolean): Promise<T> {
    const controller = new AbortController(); requests.current.add(controller);
    try {
      return await withPhotoDuplicateRead((path, signal) => suggestionRequest(path, undefined, signal), valid, async read => {
        let lastSession: PhotoSession | null = null;
        const guard = new PhotoReadFence(async () => { lastSession = await read<PhotoSession>('/me'); return lastSession; }, props.user, duplicateIdentity.current);
        const value = await guard.read(() => action(read), valid);
        if (lastSession && !duplicateIdentity.current) duplicateIdentity.current = photoSignature(lastSession);
        return value;
      }, { signal: controller.signal });
    } finally { requests.current.delete(controller); }
  }
  async function editorData(id: string, read: PhotoDuplicateRead = request) {
    const { item } = await read<{ item: Photo }>(`/media/items/${id}`); validatePhoto(item);
    if (item.id !== id) throw new Error('照片读取结果与所选内容不一致，请返回后重新查询。');
    const grants = item.canManage ? await read<{ revision: number; deviceIds: string[] }>(`/media/items/${id}/tv-grants`) : { revision: item.revision, deviceIds: [] };
    if (grants.revision !== item.revision) throw new Error('照片正在更新，请重新打开核对。');
    return { item, grants: grants.deviceIds };
  }
  async function readEditor(id: string, keepDraft = false, resuming = false) {
    const ticket = ++serial.current.detail;
    clearDuplicates(); setSuggestionVersion(value => value + 1);
    const data = await checked(() => editorData(id), () => ticket === serial.current.detail);
    installEditor(data, id, keepDraft, resuming);
  }
  function installEditor(data: { item: Photo; grants: string[] }, id: string, keepDraft = false, resuming = false) {
    const previous = editorRef.current?.item.id === id ? editorRef.current : null;
    const retained = keepDraft && previous;
    const blocked = !!(resuming && previous && (previous.blocked || previous.item.revision !== data.item.revision));
    const next: Editor = { dateDraft: retained ? retained.dateDraft : data.item.userConfirmedDate || '',
      dateReview: !!(retained && retained.dateReview), dateMessage: retained ? retained.dateMessage : '', item: data.item, caption: retained ? retained.caption : data.item.caption,
      visibility: retained ? retained.visibility : data.item.visibility,
      journeyId: retained ? retained.journeyId : data.item.journey?.id || '',
      grants: retained ? retained.grants : data.grants, savedGrants: data.grants,
      tvConsent: retained ? retained.tvConsent : false, blocked: blocked || !!(retained && retained.dateReview),
      suggestionReview: !!(resuming && previous?.suggestionReview),
      message: resuming ? blocked ? previous?.suggestionReview ? '旅行关联需要核对，页面不会自动重发。' : '照片已更新。你的草稿仍保留，请读取当前版本后核对。' : previous?.message || ''
        : retained ? '已读取当前版本，保留你的未保存修改；请比较后再保存。' : '' };
    editorRef.current = next; setEditor(next);
  }
  async function readAction(action: () => Promise<void>) {
    setError(''); try { await action(); } catch (caught) { failure(caught); }
    finally { if (current()) setLoading(false); }
  }
  async function write(path: string, method: string, body: Record<string, unknown>, done: (data: any) => Promise<void>, category: 'create' | 'confirm' | 'editor' | 'other' = 'other') {
    if (locked.current || localUpload.current?.view.busy || !current()) return;
    clearDuplicates();
    locked.current = true; setBusy(true); setError(''); setNotice('');
    const ticket = epoch.current; let writeReturned = false;
    try {
      const result = await latest.current.mutate(path, method, body);
      writeReturned = true;
      if (!current() || ticket !== epoch.current) return;
      await checked(async () => result);
      await done(result);
      void latest.current.refresh();
    } catch (caught) {
      if (!current() || ticket !== epoch.current) return;
      if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) { failure(caught); return; }
      const unknown = writeReturned || !(caught instanceof ApiError) || caught.status === 0 || caught.status >= 500;
      if (category === 'editor') setEditor(value => value ? { ...value, blocked: true, message: unknown ? '提交结果尚不明确。草稿仍保留，请读取最新版本核对，不会自动重发。' : '修改未保存。草稿仍保留，请读取最新版本核对。' } : null);
      if (category === 'confirm' && !unknown) { setConfirmReview(true); }
      if (category === 'create' && !unknown) setCreateReceipt(null);
      setError(unknown ? '结果尚未确认。请核对当前状态；页面不会自动重发写入。' : caught instanceof Error ? caught.message : '操作未完成。');
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }

  function conceal() {
    clearDuplicates();
    active.current = false; localUpload.current?.suspend(); ++epoch.current; fence.current.invalidate(); suggestionFence.current.invalidate(); requests.current.forEach(value => value.abort());
    setFocused(false); setPage({ items: [], total: 0, hasMore: false }); setMemories(null); setJourneyMenu(false); setAccountMenu(false); setDecision(null);
  }
  async function resume() {
    if (!alive.current || !routeActive.current || !available() || deniedRef.current || active.current) return;
    active.current = true; const ticket = ++epoch.current; setLoading(true); setError('');
    try {
      await Promise.all([gallery(), support()]);
      const importId = importRef.current?.import.id;
      if (importId) {
        try { await readImport(importId); }
        catch (caught) {
          if (!current() || ticket !== epoch.current) return;
          if (!(caught instanceof ApiError) || ![404, 410].includes(caught.status)) throw caught;
          if (importRef.current?.import.id === importId) {
            ++serial.current.imports; importRef.current = null; importReadAt.current = 0; setImportDetail(null);
            setSelected([]); setPersist(false); setConfirmReview(true);
            // Keep uncertain creation/confirmation IDs without guessing a receipt.
            setError('本次选片记录已移除或不再可见。');
          }
        }
      }
      const detailId = editorRef.current?.item.id || initialPhoto.current;
      if (detailId) {
        try {
          await readEditor(detailId, true, !!editorRef.current);
          if (current() && ticket === epoch.current) initialPhoto.current = '';
        }
        catch (caught) {
          if (!current() || ticket !== epoch.current) return;
          if (!(caught instanceof ApiError) || ![404, 410].includes(caught.status)) throw caught;
          initialPhoto.current = '';
          editorRef.current = null; setEditor(null); setError('照片已移除或不再可见。');
        }
      }
      if (current() && ticket === epoch.current) { setFocused(true); void localUpload.current?.resumeSelection(); }
    } catch (caught) {
      if (ticket !== epoch.current || !current()) return;
      failure(caught); active.current = false;
    } finally { if (ticket === epoch.current && alive.current) setLoading(false); }
  }
  const lifecycle = useRef({ conceal, resume }); lifecycle.current = { conceal, resume };
  useEffect(() => { alive.current = true; return () => {
    alive.current = false; localUpload.current?.dispose(); active.current = false; localUpload.current?.suspend(); ++epoch.current; fence.current.invalidate(); suggestionFence.current.invalidate(); requests.current.forEach(value => value.abort());
  }; }, []);
  useFocusEffect(useCallback(() => {
    routeActive.current = true; void lifecycle.current.resume();
    return () => { routeActive.current = false; lifecycle.current.conceal(); };
  }, [scope, offset]));
  useEffect(() => {
    const sync = () => { if (available()) void lifecycle.current.resume(); else lifecycle.current.conceal(); };
    const app = AppState.addEventListener('change', value => { foreground.current = value === 'active'; sync(); });
    const blur = () => { windowFocused.current = false; lifecycle.current.conceal(); };
    const focus = () => { windowFocused.current = true; sync(); };
    const hide = () => { pageHidden.current = true; lifecycle.current.conceal(); };
    const show = (event: PageTransitionEvent) => { if (event.persisted || pageHidden.current) { pageHidden.current = false; sync(); } };
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus);
      window.addEventListener('offline', sync); window.addEventListener('online', sync); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', sync);
    return () => { app.remove(); if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus);
      window.removeEventListener('offline', sync); window.removeEventListener('online', sync); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); }
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', sync); };
  }, []);
  useEffect(() => { if (household.online) void lifecycle.current.resume(); else lifecycle.current.conceal(); }, [household.online]);
  useEffect(() => {
    if (!focused || denied) return;
    let running = false;
    const timer = setInterval(() => {
      setClock(Date.now());
      if (running || locked.current || localUpload.current?.view.busy || typeof document !== 'undefined' && document.hidden) return;
      running = true;
      void (async () => {
        try {
          // Metadata/source checks invalidate visible hints, without another scan.
          const hints = duplicatesRef.current;
          if (hints) {
            try {
              await duplicateRead(read => verifyDuplicatePhotos([hints.target, ...hints.page.items], read),
                () => current() && duplicatesRef.current === hints && !locked.current);
            } catch (caught) {
              if (duplicatesRef.current === hints) clearDuplicates();
              throw caught;
            }
          }
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
          if (!current()) return;
          if (caught instanceof ApiError && [404, 410].includes(caught.status)) { editorRef.current = null; setEditor(null); setImportDetail(null); setError('记录已移除或不再可见。'); }
          else failure(caught);
        } finally { running = false; }
      })();
    }, 5000);
    return () => clearInterval(timer);
  }, [focused, scope, offset, denied]);

  const update = (patch: Partial<Editor>) => { clearDuplicates(); const value = editorRef.current; if (value) { editorRef.current = { ...value, ...patch }; setEditor(editorRef.current); } };
  function suggestionFailure(caught: unknown, id: string) {
    if (!current()) return;
    if (caught instanceof ApiError && [404, 410].includes(caught.status)) {
      if (editorRef.current?.item.id === id) { ++serial.current.detail; editorRef.current = null; setEditor(null); }
      setError('照片已移除或不再可见。'); return;
    }
    failure(caught);
  }
  // A scan is explicit. Background checks only discard stale displayed rows.
  async function loadDuplicates(nextOffset = 0) {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial?.item.canManage || initial.item.mediaType === 'video' || initial.blocked || anyDraft(initial)) return;
    clearDuplicates(); const ticket = duplicateSerial.current, key = draftKey(initial), generation = epoch.current;
    const valid = () => current() && epoch.current === generation && ticket === duplicateSerial.current
      && !!editorRef.current && draftKey(editorRef.current) === key && !editorRef.current.blocked && !anyDraft(editorRef.current);
    locked.current = true; setBusy(true); setError('');
    try {
      const page = await duplicateRead(read => fetchPhotoDuplicates(initial.item, nextOffset, read), valid);
      if (valid()) { const value = { target: initial.item, page }; duplicatesRef.current = value; setDuplicates(value); }
    } catch (caught) { if (valid()) suggestionFailure(caught, initial.item.id); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function openDuplicate(item: Photo) {
    const initial = editorRef.current, hints = duplicatesRef.current;
    if (locked.current || !current() || !initial || initial.blocked || anyDraft(initial) || !hints
      || !hints.page.items.some(row => row.id === item.id && duplicatePhotoKey(row) === duplicatePhotoKey(item))) return;
    const generation = epoch.current, key = draftKey(initial);
    const valid = () => current() && epoch.current === generation
      && !!editorRef.current && draftKey(editorRef.current) === key && !editorRef.current.blocked && !anyDraft(editorRef.current);
    locked.current = true; setBusy(true); setError('');
    try {
      clearDuplicates();
      const ticket = ++serial.current.detail;
      const data = await duplicateRead(async read => {
        await verifyDuplicatePhotos([hints.target, item], read);
        const value = await editorData(item.id, read);
        if (duplicatePhotoKey(value.item) !== duplicatePhotoKey(item)) throw new ApiError('照片已变化，请重新查找。', 409);
        await verifyDuplicatePhotos([value.item], read); return value;
      }, () => valid() && ticket === serial.current.detail);
      if (!valid() || ticket !== serial.current.detail) return;
      setSuggestionVersion(value => value + 1); installEditor(data, item.id);
      if (current() && epoch.current === generation && editorRef.current?.item.id === item.id) {
        const anchor = { id: hints.target.id, offset: hints.page.offset };
        duplicateReturnRef.current = anchor; setDuplicateReturn(anchor);
      }
    } catch (caught) {
      if (current() && epoch.current === generation) { clearDuplicates(); suggestionFailure(caught, initial.item.id); }
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function returnToDuplicates(discard = false) {
    const anchor = duplicateReturnRef.current, initial = editorRef.current;
    if (!anchor || locked.current || !current()) return;
    if (!discard && initial && (anyDraft(initial) || initial.blocked)) { setDecision('discard'); return; }
    const generation = epoch.current;
    locked.current = true; setBusy(true); setError('');
    try {
      // Original ID only; the detail and returned page share one deadline.
      clearDuplicates(); const ticket = ++serial.current.detail;
      const valid = () => current() && epoch.current === generation && ticket === serial.current.detail;
      const value = await duplicateRead(async read => {
        const data = await editorData(anchor.id, read);
        const page = await fetchPhotoDuplicates(data.item, anchor.offset, read); return { data, page };
      }, valid);
      if (valid()) {
        setSuggestionVersion(value => value + 1); installEditor(value.data, anchor.id); resetDuplicateReturn();
        const hints = { target: value.data.item, page: value.page }; duplicatesRef.current = hints; setDuplicates(hints);
      }
    } catch (caught) { if (current() && epoch.current === generation) {
      if (caught instanceof ApiError && [404, 410].includes(caught.status)) resetDuplicateReturn();
      suggestionFailure(caught, anchor.id);
    } }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  function invalidateDateViews() {
    clearDuplicates(); setSuggestionVersion(value => value + 1); ++serial.current.gallery; setMemories(null);
    if (scope === 'memories') setPage({ items: [], total: 0, hasMore: false });
  }
  async function saveDate(value: string | null) {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial || initial.blocked || settingsDraft(initial) || !canConfirmPhotoDate(initial.item)) return;
    const ticket = epoch.current, key = draftKey(initial);
    const valid = () => current() && epoch.current === ticket && !!editorRef.current && draftKey(editorRef.current) === key;
    locked.current = true; setBusy(true); setError(''); let attempted = false;
    try {
      const body = confirmedDateBody(initial.item, value);
      const outcome = await suggestionFence.current.read(async () => {
        if (!freshSession.current?.csrf) throw new PhotoReadDiscarded('identity');
        attempted = true; invalidateDateViews();
        update({ blocked: true, dateReview: true, dateMessage: '结果待核对，不会自动重发。' });
        try { return { result: await suggestionRequest<{ item: Photo }>(`/media/items/${initial.item.id}`, body) }; }
        catch (error) { return { error }; }
      }, valid);
      if ('error' in outcome) throw outcome.error;
      const saved = validatePhoto(outcome.result.item);
      if (saved.id !== initial.item.id || !canConfirmPhotoDate(saved) || saved.revision !== initial.item.revision + 1
        || saved.userConfirmedDate !== value) throw new Error('照片日期响应无法核对。');
      // A bounded, identity-checked successful response is sufficient to install
      // this revision. Refreshing the gallery is GET-only and cannot resend it.
      update({ item: saved, dateDraft: value || '', dateReview: false, blocked: false, dateMessage: '照片日期已更新。' });
    } catch (caught) {
      if (!current() || ticket !== epoch.current) return;
      if (attempted && editorRef.current?.item.id === initial.item.id) update({ blocked: true, dateReview: true,
        dateMessage: caught instanceof ApiError && caught.status === 409 ? '照片已变化，请核对当前照片日期。输入仍保留，不会自动重发。' : '结果待核对，不会自动重发。' });
      suggestionFailure(caught, initial.item.id); return;
    } finally { locked.current = false; if (alive.current) setBusy(false); }
    try { await gallery(); } catch (caught) { if (current() && ticket === epoch.current) {
      if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) failure(caught);
      else update({ dateMessage: '照片日期已更新，列表暂未刷新。请刷新列表。' });
    } }
  }
  async function reviewDate() {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial?.dateReview) return;
    locked.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try {
      await readEditor(initial.item.id, true);
      if (current() && ticket === epoch.current) {
        update({ dateReview: false, blocked: false, dateMessage: '已读取当前照片日期；这不是上一请求的执行回执。' });
        await gallery();
      }
    } catch (caught) { if (current() && ticket === epoch.current) suggestionFailure(caught, initial.item.id); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function loadSuggestions(): Promise<Suggestions | null> {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial?.item.canManage || initial.blocked || anyDraft(initial)) return null;
    const key = draftKey(initial), ticket = epoch.current;
    const valid = () => epoch.current === ticket && !!editorRef.current && draftKey(editorRef.current) === key;
    locked.current = true; setBusy(true); setError('');
    try {
      return await suggestionFence.current.read(async () => {
        const { item } = await suggestionRequest<{ item: Photo }>(`/media/items/${initial.item.id}`); validatePhoto(item);
        if (!item.canManage || item.id !== initial.item.id || item.revision !== initial.item.revision || item.journey?.id !== initial.item.journey?.id) throw new ApiError('照片已变化，请重新核对。', 409);
        const suggestions = readPhotoJourneySuggestions(await suggestionRequest(`/media/items/${item.id}/journey-suggestions?dateMode=confirmed-or-source`), item);
        if (suggestions.version !== 2) throw new Error('建议日期格式无法核对，请重新读取。');
        return suggestions;
      }, () => current() && valid());
    } catch (caught) {
      if (current() && valid()) {
        if (caught instanceof ApiError && caught.status === 409) update({ blocked: true, suggestionReview: true, message: '照片已变化，请核对当前旅行关联后重新查看建议。' });
        suggestionFailure(caught, initial.item.id);
      }
      return null;
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function confirmSuggestion(suggestions: Suggestions, journeyId: string) {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial?.item.canManage || initial.blocked || anyDraft(initial)) return;
    const key = draftKey(initial), ticket = epoch.current;
    const valid = () => epoch.current === ticket && !!editorRef.current && draftKey(editorRef.current) === key;
    locked.current = true; setBusy(true); setError(''); setNotice(''); let attempted = false;
    try {
      const body = photoSuggestionBody(initial.item, suggestions, journeyId);
      // Capture errors inside the fence so a rejected PATCH also receives a
      // fresh post-request identity check before the UI handles its status.
      const outcome = await suggestionFence.current.read(async () => {
        if (!freshSession.current?.csrf) throw new PhotoReadDiscarded('identity');
        attempted = true; update({ blocked: true, suggestionReview: true, message: '旅行关联尚待核对，页面不会自动重发。' });
        try { return { result: await suggestionRequest<{ item: Photo }>(`/media/items/${initial.item.id}`, body) }; }
        catch (error) { return { error }; }
      }, () => current() && valid());
      if ('error' in outcome) throw outcome.error;
      const saved = validatePhoto(outcome.result.item);
      if (saved.id !== initial.item.id || !saved.canManage || saved.journey?.id !== journeyId || saved.revision <= initial.item.revision) throw new Error('保存响应无法核对。');
      await readEditor(initial.item.id); await gallery();
      if (!current() || ticket !== epoch.current) return;
      update({ message: '已收到关联保存确认，并重新读取当前照片。' }); setNotice('旅行关联已更新。');
    } catch (caught) {
      if (!current() || ticket !== epoch.current) return;
      if (attempted && editorRef.current?.item.id === initial.item.id) update({ blocked: true, suggestionReview: true,
        message: caught instanceof ApiError && caught.status === 409 ? '照片或旅行已变化。请核对当前关联，再重新选择建议。'
          : '关联结果尚未核对。请读取当前关联；当前状态不能证明上一请求是否成功，页面不会自动重发。' });
      suggestionFailure(caught, initial.item.id);
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function reviewSuggestion() {
    const initial = editorRef.current;
    if (locked.current || !current() || !initial?.suggestionReview) return;
    locked.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try {
      await readEditor(initial.item.id); await gallery();
      if (current() && ticket === epoch.current) update({ message: '已读取当前旅行关联；这不是上一请求的执行回执。需要更改时，请重新查看建议并明确确认。' });
    } catch (caught) {
      if (current() && ticket === epoch.current) {
        if (editorRef.current?.item.id === initial.item.id) update({ blocked: true, suggestionReview: true, message: '尚未完成核对，请重试读取当前旅行关联。' });
        suggestionFailure(caught, initial.item.id);
      }
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  const connect = () => void write('/accounts/google-photos/bind', 'POST', accountId ? { accountId } : {}, async data => {
    if (!openPhotosProvider(data.url, 'authorize')) throw new Error('授权链接无法安全打开，请刷新核对。');
  });
  function create() {
    if (confirmReceipt) { setError('请先核对原选片保存请求，再开始新的选择。'); return; }
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
    if (confirmReceipt && confirmReceipt.path !== `/media/imports/${importDetail.import.id}/confirm`) { setError('请先核对原选片保存请求。'); return; }
    const receipt = confirmReceipt || { path: `/media/imports/${importDetail.import.id}/confirm`, body: confirmPhotos(importDetail.import, selected, newPhotoRequestId()) };
    setConfirmReceipt(receipt);
    void write(receipt.path, 'POST', receipt.body, async () => { await readImport(importDetail.import.id); await gallery(); await support(); setNotice('保存结果已更新，仅留下本次明确勾选的照片或视频。'); }, 'confirm');
  }
  function saveEditor() {
    if (!editor || editor.blocked || dateDirty(editor)) return;
    const item = editor.item;
    void write(`/media/items/${item.id}`, 'PATCH', { revision: item.revision, caption: editor.caption, visibility: editor.visibility, journeyId: editor.journeyId || null }, async () => {
      await readEditor(item.id); await gallery(); setNotice('照片设置已保存。');
    }, 'editor');
  }
  function saveGrants(revoke = false) {
    if (!editor || editor.blocked || dirty(editor) || dateDirty(editor)) return;
    const ids = revoke ? [] : editor.grants;
    if (ids.length && !editor.tvConsent) { setError('请确认允许选中的电视展示此照片或视频。'); return; }
    void write(`/media/items/${editor.item.id}/tv-grants`, 'PUT', { revision: editor.item.revision, deviceIds: ids, consentVersion: CONSENT, allowTvDisplay: !!ids.length }, async () => {
      await readEditor(editor.item.id); setNotice(ids.length ? '已保存电视展示范围。' : '已收回全部电视展示。');
    }, 'editor');
  }
  function decide() {
    const action = decision; setDecision(null);
    if (action === 'discard') { if (duplicateReturnRef.current) void returnToDuplicates(true); else { clearDuplicates(); serial.current.detail++; editorRef.current = null; setEditor(null); props.onBack?.(); } }
    if (action === 'delete' && editor) void write(`/media/items/${editor.item.id}`, 'DELETE', { revision: editor.item.revision }, async () => { resetDuplicateReturn(); setEditor(null); editorRef.current = null; await gallery(); setNotice('已移除看板副本。' + photoOriginalNotice(editor.item.source)); }, 'editor');
    if (action === 'cancel' && importDetail) void write(`/media/imports/${importDetail.import.id}`, 'DELETE', { revision: importDetail.import.revision }, async () => {
      setConfirmReceipt(null); setConfirmReview(false); setPersist(false); await readImport(importDetail.import.id); await support();
    });
  }
  const account = accounts.find(value => value.id === accountId);
  const row = importDetail?.import;
  const expired = !!row && Date.parse(row.expiresAt) <= clock && !terminalImport(row.state);
  const canSelect = !!row?.canConfirm && !expired && row.state === 'awaiting_confirmation';
  const localPending = localUpload.current!.view.needsCheck || !!localUpload.current!.view.detail && !terminalImport(localUpload.current!.view.detail!.import.state);
  const activeImport = localPending || imports.some(item => !terminalImport(item.state)) || !!row && !terminalImport(row.state);
  const columns = width < 540 ? 2 : width < 960 ? 3 : 4;
  const cardWidth = `${100 / columns - 1.7}%` as `${number}%`;
  const closeEditor = () => { if (busy) return; if (duplicateReturnRef.current) { void returnToDuplicates(); return; } clearDuplicates(); if (editor && (anyDraft(editor) || editor.blocked)) setDecision('discard'); else { serial.current.detail++; editorRef.current = null; setEditor(null); props.onBack?.(); } };
  const renderPhoto = (item: Photo, label: string, large = false) => <Image accessibilityLabel={label} source={{ uri: imageUri(item) }} style={large ? styles.detailImage : styles.thumbnail} resizeMode={large ? 'contain' : 'cover'} />;
  const checkbox = (label: string, checked: boolean, change: () => void, disabled = false) => <SelectionRow label={label} checked={checked} onPress={change} disabled={disabled} />;
  const backToSearch = props.onBack ? <Button contentStyle={{ minHeight: 44 }} disabled={busy || !!editor || !!createReceipt || !!confirmReceipt || !available()} onPress={props.onBack}>返回搜索</Button> : undefined;
  if (denied) return <EmptyState title="正在核对登录身份" description="原账户的照片和编辑内容已清空。" action={backToSearch} />;
  if (!focused || !available()) return <EmptyState title={loading && available() ? '正在核对照片权限' : '照片内容已隐藏'} description={error || '联网并回到页面后，将重新核对当前身份；未保存的修改仍保留在此页面内。'}
    action={<View style={styles.actions}><Button contentStyle={{ minHeight: 44 }} disabled={!available() || loading} onPress={() => void lifecycle.current.resume()}>重新读取相册</Button>{backToSearch}</View>} />;
  return <View style={styles.page}>
    <PageHeader title="相册" description="自己留下，按你的选择分享。" action={<View style={styles.actions}>{backToSearch}<Button accessibilityLabel="电视与播放" mode="outlined" icon="television" disabled={busy || !!editor || importOpen || !!createReceipt || !!confirmReceipt} onPress={() => props.onNavigate('devices')}>电视与播放</Button><Button accessibilityLabel="选择照片" mode="contained" icon="plus" disabled={busy} onPress={() => setImportOpen(value => !value)}>选择照片</Button></View>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {importOpen && <SectionCard title="添加照片" action={<Button disabled={busy} onPress={() => setImportOpen(false)}>收起</Button>}>
      <View style={styles.stack}>
        <View style={styles.actions}><Button mode={importSource === 'device' ? 'contained' : 'outlined'} disabled={busy || !!createReceipt || !!confirmReceipt} onPress={() => setImportSource('device')}>设备照片</Button><Button mode={importSource === 'google' ? 'contained' : 'outlined'} disabled={busy} onPress={() => setImportSource('google')}>Google Photos</Button></View>
        {importSource === 'device' && <LocalPhotoImportPanel controller={localUpload.current!} disabled={writeBusy || !!createReceipt || !!confirmReceipt || activeImport && !localPending && !localUpload.current?.view.detail} />}
        {importSource === 'google' && <>
        <Text variant="bodyMedium">最多 20 项，仅处理本次选择的照片和视频，不扫描整个图库。视频最长 10 分钟、源文件最大 100 MiB；超限会说明原因，不截断保存。</Text>
        <Menu theme={{ animation: { scale: 0 } }} visible={accountMenu} onDismiss={() => setAccountMenu(false)} anchor={<Button mode="outlined" disabled={busy || !!createReceipt} onPress={() => setAccountMenu(true)}>{account ? account.name || account.email || 'Google 账户' : '选择照片来源'}</Button>}>
          {accounts.map(value => <Menu.Item key={value.id} title={value.name || value.email || 'Google 账户'} onPress={() => { setAccountId(value.id); setAccountMenu(false); }} />)}
          {!accounts.length && <Menu.Item title="尚未连接 Google Photos" disabled />}
        </Menu>
        <View style={styles.actions}><Text>{account?.capabilities?.photos && !account.needsReauth ? '照片来源已连接' : '需要连接或更新照片授权'}</Text><Button disabled={busy || !!createReceipt} onPress={connect}>{account?.capabilities?.photos && !account.needsReauth ? '更新授权' : '连接 Google Photos'}</Button></View>
        <Text variant="bodySmall">Google 保留原始照片和视频；在账户设置中解绑照片来源会删除这里对应的展示副本。</Text>
        {checkbox('允许临时处理本次选择，供我预览确认；未保存的内容最迟 24 小时后清理。', temporary, () => setTemporary(v => !v), busy || !!createReceipt)}
        <Button mode="contained" disabled={busy || (!createReceipt && (!temporary || activeImport || !account?.capabilities?.photos || account.needsReauth)) || !!confirmReceipt} onPress={() => { try { create(); } catch (caught) { failure(caught); } }}>{createReceipt ? '核对 / 重试原选择请求' : '开始选择照片'}</Button>
        {!!createReceipt && <Text>上一请求结果未确认；此按钮沿用原请求标识，不会自动重复创建。</Text>}
        </>}
        {!!confirmReceipt && (!row || terminalImport(row.state)) && <View style={styles.stack}>
          <Text>原保存结果仍待核对。结束核对只清除此页的等待记录，不代表原请求成功或失败。</Text>
          <Button contentStyle={{ minHeight: 44 }} disabled={busy} onPress={() => { if (!locked.current && current()) { setConfirmReceipt(null); setConfirmReview(false); setSelected([]); setPersist(false); } }}>结束本次核对</Button>
        </View>}
        {activeImport && !row && <Text>已有进行中的选择，请从下方继续。</Text>}
        {imports.length > 0 && <List.Accordion title="最近的选择" description="继续选片或查看保存结果">
          {imports.map(item => <List.Item key={item.id} title={photoSourceLabel(item.source) + ' · ' + (importLabels[item.state] || '选择记录')} description={item.state === 'confirmed' ? savedSummary(item, '项') : new Date(item.createdAt).toLocaleString('zh-CN')} onPress={() => { if (!busy && !confirmReceipt) void readAction(async () => {
            if (item.source === 'local-upload') { setImportSource('device'); await localUpload.current?.check(item.id); }
            await readImport(item.id);
          }); }} />)}
        </List.Accordion>}
        {!!row && <View style={styles.stack}>
          {row.source === 'local-upload' && row.state === 'staging' && <Button disabled={busy} onPress={() => { setImportSource('device'); void localUpload.current?.check(row.id); }}>继续本批设备上传</Button>}
          <Divider /><Text variant="titleMedium" accessibilityRole="header">{importLabels[row.state]}</Text>
          {row.resultsState === 'unknown' ? <Text>{row.state === 'confirmed' ? savedSummary(row, '项') : terminalImport(row.state) ? '本次其他处理结果未记录。' : '正在等待本次选择的处理结果。'}</Text> : <>
            <Text accessibilityLiveRegion="polite">本次选择 {countText(row.counts.selected, '项')} · 成功 {countText(row.counts.ready, '项')} · 失败 {countText(row.counts.failed, '项')} · 跳过 {countText(row.counts.skipped, '项')} · 处理中 {countText(row.counts.pending, '项')}</Text>
            {row.state === 'confirmed' && <Text>{savedSummary(row, '项')} · 成功但未勾选 {countText(row.counts.unselected, '项')}</Text>}
            {!!row.counts.selected && row.counts.pending !== null && <ProgressBar progress={(row.counts.selected - row.counts.pending) / row.counts.selected} />}
            {row.results.filter(result => ['failed', 'skipped'].includes(result.status)).map(result => <Text key={result.position}>第 {result.position} 项：{photoError(result.error?.code)}</Text>)}
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
              {renderPhoto(candidate.item, candidate.item.mediaType === 'video' ? '待保存视频封面' : '本次选择的照片')}
              {candidate.item.mediaType === 'video' && <Text style={styles.photoCopy}>{videoDescription(candidate.item)}</Text>}
              {checkbox(candidate.status === 'duplicate' ? '已有，可复用' : candidate.item.mediaType === 'video' ? '保留此视频' : '保留这张', selected.includes(candidate.id), () => setSelected(ids => toggle(ids, candidate.id)), busy || !!confirmReceipt)}
            </Card>)}</View>
            <Text variant="titleSmall">仅将当前勾选的 {confirmReceipt ? (confirmReceipt.body.itemIds as string[]).length : selected.length} 项保存到私密相册。</Text>
            <Text variant="bodySmall">未勾选的预览不会新增保存；已存在的照片不会因此删除。</Text>
            {checkbox('同意将勾选照片或视频的展示副本持久保存在私密相册中。之后另行设置家庭共享和电视展示。', persist, () => setPersist(v => !v), busy || !!confirmReceipt)}
            {confirmReview ? <Button disabled={busy} onPress={() => void readAction(() => readImport(row.id, true))}>读取最新选择，重新核对</Button> : <Button mode="contained" disabled={busy || !persist || !selected.length} onPress={() => { try { saveSelection(); } catch (caught) { failure(caught); } }}>{confirmReceipt ? '核对 / 重试原保存请求' : `保存选中的 ${selected.length} 项`}</Button>}
          </>}
          <View style={styles.actions}><Button disabled={busy} onPress={() => void readAction(() => readImport(row.id))}>刷新状态</Button>{row.state !== 'confirmed' && row.state !== 'cancelled' && <Button disabled={busy || !!confirmReceipt} onPress={() => setDecision('cancel')}>取消本次选择</Button>}</View>
        </View>}
      </View>
    </SectionCard>}
    <View style={styles.actions}><SegmentedButtons style={styles.scope} value={scope} onValueChange={value => { if (!busy) { setScope(value); setOffset(0); setLoading(true); } }} buttons={[{ value: 'mine', label: '我的照片', disabled: busy }, { value: 'shared', label: '家人共享', disabled: busy }, { value: 'memories', label: '那年今日', disabled: busy }]} /><Button icon="refresh" disabled={busy} onPress={() => void readAction(async () => { await Promise.all([gallery(), support()]); })}>刷新</Button></View>
    {scope === 'memories' && !loading && memories && <View style={{ gap: 6 }} testID="photo-memories-summary">
      <Text variant="titleLarge" accessibilityRole="header">{Number(memories.referenceDate.slice(5, 7))} 月 {Number(memories.referenceDate.slice(8))} 日，那些年的今天</Text>
      <Text variant="bodyMedium">按本人确认日期或来源日期回看；来源时刻按北京时间取日期。</Text>
      {!!unknownMemoryDates(memories) && <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{unknownMemoryDates(memories)} 张照片没有可核对的日期，暂未纳入回看。</Text>}
    </View>}
    {loading ? <ActivityIndicator accessibilityLabel="正在读取相册" /> : !page.items.length ? <EmptyState
      title={scope === 'memories' ? offset ? '这一页暂时没有照片' : '还没有往年同日的照片' : scope === 'mine' ? '把想回看的照片留下' : '还没有家人共享的照片'}
      description={scope === 'memories' ? offset ? '照片可能已变化，回到第一页查看最新内容。' : '回看使用本人确认日期或已记录的来源日期，不会用导入日期补齐。' : scope === 'mine' ? '先选择照片，预览后再确认保存。默认只有你能看见。' : '家人明确共享后，照片才会出现在这里。'}
      action={scope === 'memories' && offset ? <Button onPress={() => setOffset(0)}>返回第一页</Button> : scope === 'mine' ? <Button onPress={() => { setImportSource('device'); setImportOpen(true); }}>从设备选择照片</Button> : undefined} />
      : <View style={styles.grid}>{page.items.map((item, index) => {
        const memory = scope === 'memories' ? memories?.items[index] : undefined;
        const year = memory ? memoryDisplayDate(memory).slice(0, 4) : undefined;
        return <React.Fragment key={item.id}>
          {memory && (!index || memoryDisplayDate(memories!.items[index - 1]).slice(0, 4) !== year) && <Text variant="titleMedium" accessibilityRole="header" style={{ width: '100%' }}>{year} 年 · {memory.yearsAgo} 年前</Text>}
          <Card mode="outlined" accessibilityLabel={(item.mediaType === 'video' ? '查看视频：' : '查看照片：') + (item.caption || '未添加说明')} onPress={() => { if (!busy) void readAction(() => readEditor(item.id)); }} style={[styles.photoCard, { width: cardWidth }]}>
            {renderPhoto(item, item.caption || (item.mediaType === 'video' ? '视频封面' : '已保存的照片'))}<Card.Content style={styles.photoCopy}>
              {item.mediaType === 'video' && <Text variant="bodySmall">{videoDescription(item)}</Text>}
              {memory && <Text variant="bodySmall">{memoryDateLabel(memory)}：{memoryDisplayDate(memory)}</Text>}
              <Text variant="bodyMedium">{item.caption || '未添加说明'}</Text><Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{item.visibility === 'private' ? '仅我自己' : '家庭共享'}{item.journey ? ' · ' + item.journey.title : ''}</Text>
            </Card.Content>
          </Card>
        </React.Fragment>;
      })}</View>}
    <View style={styles.actions}><Text variant="bodySmall">共 {page.total} 项 · 第 {Math.floor(offset / 24) + 1} 页</Text><Button disabled={!offset || busy || loading} onPress={() => setOffset(v => Math.max(0, v - 24))}>上一页</Button><Button disabled={!page.hasMore || busy || loading || scope === 'memories' && offset + 24 > 4000} onPress={() => setOffset(v => v + 24)}>下一页</Button></View>
    {scope === 'memories' && page.hasMore && offset + 24 > 4000 && <Text variant="bodySmall">已到达当前可浏览范围，可返回第一页查看。</Text>}
    <Portal><Dialog testID="photo-editor" visible={!!editor} onDismiss={closeEditor} dismissable={!busy} style={[styles.dialog, { maxHeight: height - 40 }]}>
      <Dialog.Title>{editor?.item.mediaType === 'video' ? '视频详情' : '照片详情'}</Dialog.Title>
      <Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent} keyboardShouldPersistTaps="handled">
        {editor && <>
          {renderPhoto(editor.item, editor.item.caption || (editor.item.mediaType === 'video' ? '视频封面' : '照片详情预览'), true)}
          {editor.item.mediaType === 'video' && <MemberVideoPlayer key={[props.identityKey, editor.item.id, editor.item.revision].join(':')} item={editor.item} user={props.user} identityKey={props.identityKey} enabled={!busy && !editor.blocked && focused && current()} />}
          {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
          {!!editor.message && <Text accessibilityLiveRegion="polite">{editor.message}</Text>}
          {editor.item.canManage ? <>
            {canConfirmPhotoDate(editor.item) && <PhotoConfirmedDate value={editor.dateDraft} saved={editor.item.userConfirmedDate ?? null}
              busy={busy} blocked={editor.blocked} otherDraft={settingsDraft(editor)} needsCheck={editor.dateReview} message={editor.dateMessage}
              change={dateDraft => update({ dateDraft, dateMessage: '' })} save={value => void saveDate(value)} recheck={() => void reviewDate()}
              cancel={() => update({ dateDraft: editor.item.userConfirmedDate || '', dateMessage: '' })}
              discardOther={() => { if (!locked.current && current() && !editor.blocked) update({ caption: editor.item.caption, visibility: editor.item.visibility,
                journeyId: editor.item.journey?.id || '', grants: [...editor.savedGrants], tvConsent: false }); }} />}

            <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} label="照片说明" accessibilityLabel="照片说明" multiline maxLength={500} value={editor.caption} disabled={busy || editor.suggestionReview || editor.dateReview} onChangeText={caption => update({ caption })} />
            <Text variant="titleSmall">谁能查看</Text><SegmentedButtons value={editor.visibility} onValueChange={visibility => update({ visibility: visibility as 'private' | 'shared', tvConsent: false })} buttons={[{ value: 'private', label: '仅我自己', disabled: busy || editor.suggestionReview || editor.dateReview }, { value: 'shared', label: '家庭成员', disabled: busy || editor.suggestionReview || editor.dateReview }]} />
            <Text variant="bodySmall">家庭共享包括所选照片或视频及说明。改回私密会同时收回全部电视展示。</Text>
            <Menu theme={{ animation: { scale: 0 } }} visible={journeyMenu} onDismiss={() => setJourneyMenu(false)} anchor={<Button mode="outlined" disabled={busy || editor.suggestionReview || editor.dateReview} onPress={() => setJourneyMenu(true)}>{editor.journeyId ? journeys.find(j => j.id === editor.journeyId)?.trip?.title || journeys.find(j => j.id === editor.journeyId)?.plan?.title || editor.item.journey?.title || '已关联旅行' : '关联旅行（可选）'}</Button>}>
              <Menu.Item title="不关联旅行" onPress={() => { update({ journeyId: '' }); setJourneyMenu(false); }} />
              {journeys.map(journey => <Menu.Item key={journey.id} title={journey.trip?.title || journey.plan?.title || '旅行'} onPress={() => { update({ journeyId: journey.id }); setJourneyMenu(false); }} />)}
            </Menu>
            <Text variant="bodySmall">解除已有旅行关联会自动转为私密并收回电视许可；关联照片不会标记地点到访。</Text>
            {editor.dateReview ? null : editor.suggestionReview ? <Button contentStyle={{ minHeight: 44 }} disabled={busy} onPress={() => void reviewSuggestion()}>核对当前旅行关联</Button>
              : editor.blocked ? <Button disabled={busy} onPress={() => void readAction(() => readEditor(editor.item.id, true))}>读取当前版本，保留我的修改</Button> : <Button mode="contained" disabled={busy || !dirty(editor) || dateDirty(editor)} onPress={saveEditor}>保存照片设置</Button>}
            {editor.item.mediaType !== 'video' && !duplicateReturn && <PhotoDuplicateHints
              data={duplicates?.page || null} busy={busy} dirty={anyDraft(editor)} blocked={editor.blocked}
              load={nextOffset => void loadDuplicates(nextOffset)} open={item => void openDuplicate(item)} thumbnail={renderPhoto} />}
            <PhotoJourneySuggestions key={JSON.stringify([scope, offset, suggestionVersion, draftKey(editor)])} busy={busy} dirty={anyDraft(editor)} blocked={editor.blocked}
              load={loadSuggestions} confirm={confirmSuggestion} cancelDraft={() => {
                if (locked.current || !current()) return;
                const value = editorRef.current; if (value) update({ caption: value.item.caption, visibility: value.item.visibility, dateDraft: value.item.userConfirmedDate || '', dateMessage: '', journeyId: value.item.journey?.id || '', grants: [...value.savedGrants], tvConsent: false });
              }} />
            <Divider /><List.Accordion title="电视展示" description="家庭共享后，再选择具体电视">
              <Text variant="bodySmall">先保存上方设置。只有勾选并确认的电视可以展示此照片或视频；电视配对不等于获得全部相册。</Text>
              {devices.length ? devices.map(device => <React.Fragment key={device.id}>{checkbox(device.name || '家庭电视', editor.grants.includes(device.id), () => update({ grants: toggle(editor.grants, device.id), tvConsent: false }), busy || editor.blocked || dirty(editor) || dateDirty(editor) || editor.item.visibility !== 'shared')}</React.Fragment>) : <Text>尚未配对电视，可在设备设置中添加。</Text>}
              {checkbox('允许选中的电视展示此照片或视频。', editor.tvConsent, () => update({ tvConsent: !editor.tvConsent }), busy || editor.blocked || dirty(editor) || dateDirty(editor) || editor.item.visibility !== 'shared')}
              <Button mode="outlined" disabled={busy || editor.blocked || dirty(editor) || dateDirty(editor) || editor.item.visibility !== 'shared' || !!editor.grants.length && !editor.tvConsent} onPress={() => saveGrants()}>保存电视范围</Button>
              <Button disabled={busy || editor.blocked || dirty(editor) || dateDirty(editor)} onPress={() => saveGrants(true)}>收回全部电视展示</Button>
            </List.Accordion>
            <Button textColor={theme.colors.error} disabled={busy || editor.blocked} onPress={() => setDecision('delete')}>移除看板副本</Button><Text variant="bodySmall">{photoSourceLabel(editor.item.source)} · {photoOriginalNotice(editor.item.source)}</Text>
          </> : <><Text variant="titleMedium">{editor.item.caption || '家庭共享照片'}</Text><Text>由上传者管理，你可以查看当前共享的照片。</Text>{!!editor.item.journey && <Text>关联旅行：{editor.item.journey.title}</Text>}</>}
        </>}
      </ScrollView></Dialog.ScrollArea><Dialog.Actions><Button disabled={busy} onPress={closeEditor}>{duplicateReturn ? '返回重复提示' : props.onBack ? '返回搜索' : '关闭'}</Button></Dialog.Actions>
    </Dialog>
    <Dialog visible={!!decision} onDismiss={() => setDecision(null)} style={styles.dialog}><Dialog.Title>{decision === 'discard' ? '离开照片详情？' : decision === 'delete' ? '移除这张照片？' : '取消本次选择？'}</Dialog.Title><Dialog.Content><Text>{decision === 'discard' ? '未保存的输入将丢弃。关闭页面不会撤销已经提交的操作。' : decision === 'delete' ? '将删除看板副本，并收回家庭共享及电视展示。' + photoOriginalNotice(editor?.item.source) : '清理未确认的临时预览。' + photoOriginalNotice(row?.source) + '已经发出的请求仍会由服务器处理。'}</Text></Dialog.Content><Dialog.Actions><Button onPress={() => setDecision(null)}>返回</Button><Button onPress={decide}>确认</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16 }, stack: { gap: 14 }, actions: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10 },
  scope: { flexGrow: 1, minWidth: 240 }, grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 16 },
  photoCard: { borderRadius: 12, overflow: 'hidden' }, thumbnail: { width: '100%', aspectRatio: 1, backgroundColor: '#f0f0f3' },
  photoCopy: { paddingHorizontal: 12, paddingVertical: 12, gap: 6 },
  dialog: { width: '92%', maxWidth: 620, alignSelf: 'center', borderRadius: 12 }, dialogScroll: { paddingHorizontal: 0, flexShrink: 1 },
  dialogContent: { padding: 20, gap: 16 }, detailImage: { width: '100%', height: 250, borderRadius: 8, backgroundColor: '#f0f0f3' },
});
