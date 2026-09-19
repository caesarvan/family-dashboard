import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text, TextInput, TouchableRipple, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { DocumentDiscarded, DocumentError, DocumentFence, DocumentRejected, checkedDocumentWrite, documentListPath,
  documentPath, documentRequest, downloadDocument, newDocumentRequestId, readDeleteResult, readDocumentFile,
  readDocumentList, readMutationResult, readPatchPayload, readUploadPayload, readUploadResult,
  type DocumentFile, type DocumentList, type DocumentPatchPayload, type DocumentUploadPayload, type JourneyDocument, type DocumentSession } from '../lib/journeyDocuments';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

type Props = { journeyId?: string; initialDocumentId?: string; onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Fields = { title: string; journeyId: string | null; segmentKey: string; visibility: 'private' | 'shared' };
type Editor = { kind: 'upload' | 'edit'; base: JourneyDocument | null; fields: Fields; file: DocumentFile | null; initialJourney: string | null };
type Intent = { kind: 'upload'; payload: DocumentUploadPayload } | { kind: 'edit'; id: string; payload: DocumentPatchPayload } | { kind: 'delete'; id: string; payload: { revision: number } };
type Model = { list: DocumentList | null; editor: Editor | null; focus: string | null; segments: DocumentList['segments']; unknown: Intent | null;
  review: { document: JourneyDocument | null } | null; blocked: boolean; checked: boolean };
type Choice = 'journey' | 'segment' | null;
const empty = (): Model => ({ list: null, editor: null, focus: null, segments: [], unknown: null, review: null, blocked: false, checked: false });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const fields = (value: JourneyDocument): Fields => ({ title: value.title, journeyId: value.journeyId, segmentKey: value.segmentKey, visibility: value.visibility });
const same = (a: Fields, b: Fields) => a.title === b.title && a.journeyId === b.journeyId && a.segmentKey === b.segmentKey && a.visibility === b.visibility;
const dirty = (model: Model) => !!model.editor && (model.editor.kind === 'upload'
  ? !!model.editor.file || !!model.editor.fields.title.trim() || !!model.editor.fields.segmentKey || model.editor.fields.visibility !== 'private' || model.editor.fields.journeyId !== model.editor.initialJourney
  : !!model.editor.base && !same(model.editor.fields, fields(model.editor.base)));
const PAGE_SIZE = 12;
const sizeLabel = (bytes: number) => bytes < 1000 ? `${bytes} B` : bytes < 1_000_000 ? `${Math.ceil(bytes / 1000)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;

function pickFile(signal: AbortSignal): Promise<File | null> {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return Promise.reject(new Error('请在手机或电脑浏览器中选择资料文件。'));
  return new Promise((resolve, reject) => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf,.jpg,.jpeg,.png,.webp';
    input.setAttribute('aria-label', '资料文件'); input.style.display = 'none'; document.body.appendChild(input);
    let finished = false;
    const finish = (file: File | null) => { if (finished) return; finished = true; signal.removeEventListener('abort', abort); input.remove(); resolve(file); };
    const abort = () => finish(null);
    input.addEventListener('change', () => finish(input.files?.[0] || null), { once: true });
    input.addEventListener('cancel', () => finish(null), { once: true });
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) return finish(null);
    try { input.click(); } catch (error) { input.remove(); signal.removeEventListener('abort', abort); reject(error); }
  });
}

export default function JourneyDocumentsPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看旅行资料" />;
  if (props.initialDocumentId !== undefined && !/^[a-f0-9]{32}$/.test(props.initialDocumentId)) return <EmptyState title="资料入口无法核对" action={<Button onPress={props.onBack}>返回搜索</Button>} />;
  return <Workspace key={`${household.identityKey}:${props.journeyId || 'library'}:${props.initialDocumentId || ''}`} {...props} identityKey={household.identityKey} owner={household.user.id} />;
}

function Workspace(props: Props & { identityKey: string; owner: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(() => ({ ...empty(), focus: props.initialDocumentId || null })), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const [search, setSearch] = useState(''), [page, setPage] = useState(0), [choice, setChoice] = useState<Choice>(null), [choiceSearch, setChoiceSearch] = useState(''), [choicePage, setChoicePage] = useState(0);
  const [leaving, setLeaving] = useState<'panel' | 'editor' | 'unknown' | null>(null), [deleting, setDeleting] = useState(false);
  const alive = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const flight = useRef<AbortController | null>(null), urls = useRef(new Set<string>()), fence = useRef(new DocumentFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && active.current && !denied.current && focused.current && foreground.current && ticket === epoch.current
    && latest.current.household.identityKey === props.identityKey && latest.current.household.online && online() && (typeof document === 'undefined' || !document.hidden);
  function notify() { latest.current.props.onPendingChange?.(working.current || dirty(live.current) || !!live.current.unknown); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function releaseUrls() { for (const url of urls.current) URL.revokeObjectURL(url); urls.current.clear(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); setChoice(null); setDeleting(false); setLeaving(null); setError(''); setMessage(''); releaseUrls();
    working.current = false; setBusy(false);
    if (clear) { live.current = empty(); setModel(live.current); setSearch(''); setPage(0); }
    notify();
  }
  function failed(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (caught instanceof DocumentDiscarded) {
      if (caught.message === 'identity') { denied.current = true; conceal(true); setError('身份已变化，请重新打开旅行资料。'); void latest.current.household.refresh(); }
      return;
    }
    if (caught instanceof DocumentError && [401, 403].includes(caught.status)) {
      conceal(); setError('当前身份或权限需要重新核对，资料已隐藏。'); void latest.current.household.refresh(); return;
    }
    setError(caught instanceof Error ? caught.message : '暂时无法读取旅行资料。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (caught) { failed(caught, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, operation: (csrf: string) => Promise<T>) => fence.current.run(
    () => documentRequest('/me', signal) as Promise<DocumentSession>,
    operation, () => current(ticket));
  async function readList(ticket: number, signal: AbortSignal, journeyId: string | null = props.journeyId || null) {
    return readDocumentList(await guard(ticket, signal, () => documentRequest(documentListPath(journeyId || undefined), signal)), journeyId || undefined, props.owner);
  }
  async function load(ticket: number, signal: AbortSignal) {
    let list: DocumentList;
    try { list = await readList(ticket, signal); }
    catch (caught) {
      if (!(caught instanceof DocumentError) || caught.status !== 404 || !props.journeyId || !current(ticket)) throw caught;
      if (props.initialDocumentId) throw new DocumentError('原旅行已不可用，这份资料已移出原搜索范围。请返回搜索重新查询。', 404);
      // This 404 already passed the original request's before/after identity fence.
      list = await readList(ticket, signal, null);
      if (current(ticket)) setMessage('原旅行当前不可用，已读取你的资料库。文件可在此重新关联。');
    }
    const before = live.current;
    let review: Model['review'] = null;
    if ((before.unknown && before.unknown.kind !== 'upload') || before.editor?.base || before.blocked && before.focus) {
      const own = props.journeyId && list.journey ? await readList(ticket, signal, null) : list;
      const id = (before.unknown?.kind !== 'upload' ? before.unknown?.id : null) || before.editor?.base?.id || before.focus;
      const record = own.documents.find(item => item.id === id) || null;
      if (before.unknown || before.blocked || before.editor?.base && (!record || record.revision !== before.editor.base.revision)) review = { document: record };
    }
    let segments = before.segments;
    if (before.editor?.fields.journeyId) {
      try {
        const related = before.editor.fields.journeyId === list.journey?.id ? list : await readList(ticket, signal, before.editor.fields.journeyId);
        segments = related.segments;
      } catch (caught) {
        if (!(caught instanceof DocumentError) || caught.status !== 404 || !current(ticket)) throw caught;
        segments = [];
        setMessage('草稿中关联的旅行已不可用。请选择现存旅行，或在编辑资料时解除关联。');
      }
    }
    if (!current(ticket)) return;
    install({ list, review, segments, blocked: !!review || before.blocked, checked: !!before.unknown });
    if (before.focus && !before.editor && !before.unknown && !list.documents.some(item => item.id === before.focus)) {
      install({ focus: null });
      if (before.focus === props.initialDocumentId) setError('这份资料已移除、移出当前范围，或不再对你可见。请返回搜索重新查询。');
      else setMessage('这份资料已不在当前列表，请查看最新资料库。');
    }
    setVisible(true);
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || !foreground.current || denied.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(load);
  }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); releaseUrls(); live.current = empty();
      if (latest.current.household.identityKey === props.identityKey) latest.current.props.onPendingChange?.(false); };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, disconnected = () => conceal(), connected = () => enter();
    const hide = () => conceal(), show = (event: PageTransitionEvent) => { if (event.persisted) { conceal(); enter(); } };
    const unload = (event: BeforeUnloadEvent) => { if (working.current || dirty(live.current) || live.current.unknown) { event.preventDefault(); event.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', disconnected); window.addEventListener('online', connected); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', disconnected); window.removeEventListener('online', connected); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function edit(patch: Partial<Fields>) {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.editor) return;
    install({ editor: { ...live.current.editor, fields: { ...live.current.editor.fields, ...patch } } }); setError(''); setMessage('');
  }
  function openUpload() {
    if (!current() || working.current || live.current.unknown) return;
    const journeyId = live.current.list?.journey?.id || null;
    install({ focus: null, editor: { kind: 'upload', base: null, file: null, initialJourney: journeyId, fields: { title: '', journeyId, segmentKey: '', visibility: 'private' } }, segments: live.current.list?.segments || [], review: null, blocked: false });
    setError(''); setMessage('');
  }
  async function openEdit(record: JourneyDocument) {
    if (!current() || working.current || !record.canManage || live.current.unknown) return;
    await job(async (ticket, signal) => {
      const related = record.journeyId ? await readList(ticket, signal, record.journeyId) : null;
      if (!current(ticket)) return;
      install({ editor: { kind: 'edit', base: record, file: null, initialJourney: record.journeyId, fields: fields(record) }, segments: related?.segments || [], review: null, blocked: false });
    });
  }
  async function chooseFile() {
    if (!current() || working.current || live.current.unknown || live.current.editor?.kind !== 'upload') return;
    await job(async (ticket, signal) => {
      const selected = await pickFile(signal); if (!selected || !current(ticket)) return;
      const value = await readDocumentFile(selected, signal, () => current(ticket));
      await guard(ticket, signal, async () => true);
      if (!current(ticket) || live.current.editor?.kind !== 'upload') return;
      install({ editor: { ...live.current.editor, file: value, fields: { ...live.current.editor.fields, title: live.current.editor.fields.title || selected.name.replace(/\.[^.]+$/, '') } } });
    });
  }
  async function selectJourney(id: string | null) {
    if (!current() || working.current || !live.current.editor || live.current.unknown || live.current.blocked) return;
    setChoice(null);
    await job(async (ticket, signal) => {
      const related = id ? await readList(ticket, signal, id) : null;
      if (!current(ticket) || !live.current.editor) return;
      install({ segments: related?.segments || [], editor: { ...live.current.editor, fields: { ...live.current.editor.fields, journeyId: id, segmentKey: '', ...(!id ? { visibility: 'private' as const } : {}) } } });
    });
  }
  async function send(intent: Intent, retry = false) {
    if (!current() || working.current || live.current.unknown && !retry) return;
    await job(async (ticket, signal) => {
      setMessage('');
      try {
        const result = await checkedDocumentWrite(perform => guard(ticket, signal, perform), async csrf => {
          install({ unknown: intent, review: null, checked: false });
          const path = intent.kind === 'upload' ? documentListPath() : documentPath(intent.id);
          const raw = await documentRequest(path, signal, { method: intent.kind === 'upload' ? 'POST' : intent.kind === 'edit' ? 'PATCH' : 'DELETE', payload: intent.payload, csrf });
          const saved = intent.kind === 'upload' ? readUploadResult(raw).document : intent.kind === 'edit' ? readMutationResult(raw, intent.id) : (readDeleteResult(raw, intent.id), null);
          if (saved && saved.owner !== props.owner) throw new DocumentError('保存返回的资料身份无法核对，请读取当前列表。');
          return saved;
        });
        if (!current(ticket)) return;
        install({ editor: null, focus: null, unknown: null, review: null, blocked: false, checked: false, segments: [] });
        setMessage(intent.kind === 'delete' ? '资料已删除。' : `${intent.kind === 'upload' ? retry ? '已核对上传结果' : '资料已上传' : '资料已更新'}：${result?.title || ''}${result?.unlinked ? '。当前未关联旅行，仅本人可见，可在我的旅行资料中查看。' : result && props.journeyId && result.journeyId !== props.journeyId ? '。当前关联在另一旅行，可在我的旅行资料中查看。' : ''}`); setPage(0);
        // Once the mutation has a valid response, a later read failure is not an unknown mutation.
        await load(ticket, signal);
      } catch (caught) {
        if (!current(ticket)) return;
        if (caught instanceof DocumentRejected && !retry) {
          install({ unknown: null, blocked: caught.status === 409 && intent.kind !== 'upload' });
          if (caught.status === 403) failed(caught, ticket); else setError(caught.message);
        }
        else { if (live.current.unknown) setMessage('操作结果尚未确定。请先核对；不会自动重复提交。'); throw caught; }
      }
    });
  }
  function save() {
    const editor = live.current.editor;
    if (!current() || working.current || !editor || live.current.unknown || live.current.blocked) return;
    try {
      if (!editor.fields.title.trim() || Array.from(editor.fields.title.trim()).length > 120) throw new Error('请填写 1–120 个字符的资料标题。');
      if (editor.kind === 'upload') {
        if (!editor.file || !editor.fields.journeyId) throw new Error('请选择资料文件和已保存的旅行。');
        void send({ kind: 'upload', payload: readUploadPayload({ ...editor.fields, file: editor.file, requestId: newDocumentRequestId() }) });
      } else if (editor.base) void send({ kind: 'edit', id: editor.base.id, payload: readPatchPayload({ ...editor.fields, revision: editor.base.revision }) });
    } catch (caught) { setError(caught instanceof Error ? caught.message : '请核对资料信息。'); }
  }
  function decide(keep: boolean) {
    if (!current() || working.current || !live.current.review) return;
    const record = live.current.review.document, editor = live.current.editor;
    if (keep && record && editor?.kind === 'edit') {
      const original = fields(editor.base!), retained = { ...fields(record) };
      for (const key of ['title', 'journeyId', 'segmentKey', 'visibility'] as const) {
        if (editor.fields[key] !== original[key]) Object.assign(retained, { [key]: editor.fields[key] });
      }
      if (!retained.journeyId) { retained.visibility = 'private'; retained.segmentKey = ''; }
      void job(async (ticket, signal) => {
        const related = retained.journeyId ? await readList(ticket, signal, retained.journeyId) : null;
        if (!current(ticket)) return;
        install({ editor: { ...editor, base: record, fields: retained }, segments: related?.segments || [], unknown: null, blocked: false, review: null, checked: false });
        setMessage('已保留修改。请核对关联与共享范围，再明确保存。');
      });
    } else {
      install({ editor: null, focus: record && live.current.list?.documents.some(item => item.id === record.id) ? record.id : null, unknown: null, blocked: false, review: null, checked: false });
      setMessage('已采用刚读取的当前状态，没有再次写入。');
    }
    setError('');
  }
  async function download(record: JourneyDocument) {
    await job(async (ticket, signal) => {
      const result = await downloadDocument(record, signal, perform => guard(ticket, signal, perform), () => current(ticket));
      if (!current(ticket)) return;
      if (Platform.OS !== 'web' || typeof document === 'undefined') throw new Error('请在浏览器中下载资料。');
      const url = URL.createObjectURL(result.blob); urls.current.add(url);
      try { const link = document.createElement('a'); link.href = url; link.download = result.filename; document.body.appendChild(link); link.click(); link.remove(); }
      finally { setTimeout(() => { URL.revokeObjectURL(url); urls.current.delete(url); }, 1000); }
      setMessage('已发起下载。请在浏览器下载列表核对文件；资料不会在页面内打开。');
    });
  }
  function back(to: 'panel' | 'editor') {
    if (working.current || live.current.unknown) return;
    if (dirty(live.current)) { setLeaving(to); return; }
    if (to === 'panel') { latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
    else { install({ editor: null, focus: null, blocked: false, review: null }); setMessage(''); setError(''); }
  }
  function discard() {
    if (!current() || working.current) return;
    const destination = leaving; setLeaving(null);
    if (live.current.unknown && destination !== 'unknown') return;
    install({ editor: null, focus: null, unknown: null, blocked: false, review: null, checked: false });
    setError(''); setMessage(destination === 'unknown' ? '已结束本次上传操作。此操作不撤销服务器可能已保存的文件，请核对列表。' : '未保存的修改已放弃。');
    if (destination === 'panel') latest.current.props.onBack();
  }
  const locked = busy || !visible || !!model.unknown || model.blocked;
  const rows = (model.list?.documents || []).filter(item => `${item.title} ${item.filename}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const maxPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1), shownPage = Math.min(page, maxPage), shown = rows.slice(shownPage * PAGE_SIZE, (shownPage + 1) * PAGE_SIZE);
  const focusedRecord = model.list?.documents.find(item => item.id === model.focus), editor = model.editor;
  const journeyTitle = (id: string | null) => !id ? '未关联旅行' : model.list?.journeys.find(item => item.id === id)?.title || '原旅行已不存在，请重新选择';
  const segmentTitle = editor?.fields.segmentKey ? model.segments.find(item => item.key === editor.fields.segmentKey)?.title || '原分段已移除（可保留原关联）' : '整次旅行';
  const options = (choice === 'journey' ? [...(editor?.kind === 'edit' ? [{ key: '', title: '解除关联（仅本人）' }] : []), ...(model.list?.journeys || []).map(item => ({ key: item.id, title: item.title }))]
    : [{ key: '', title: '整次旅行' }, ...model.segments.map(item => ({ key: item.key, title: item.title }))]).filter(item => item.title.toLocaleLowerCase().includes(choiceSearch.trim().toLocaleLowerCase()));
  const choiceMax = Math.max(0, Math.ceil(options.length / PAGE_SIZE) - 1), choiceCurrent = Math.min(choicePage, choiceMax);
  const actions = (children: React.ReactNode) => <View style={styles.actions}>{children}</View>;
  const metadata = (record: JourneyDocument, showTitle = true) => <View style={{ gap: density.tripGap }}>
    {showTitle && <Text variant="titleMedium" style={styles.wrap}>{record.title}</Text>}<Text style={styles.wrap}>{record.filename} · {sizeLabel(record.bytes)}</Text>
    <Text>{record.visibility === 'shared' ? '家庭共享' : '仅本人'} · {record.canManage ? '由你上传' : '伙伴共享，只可下载'}</Text>
    <Text style={styles.wrap}>{journeyTitle(record.journeyId)}{record.segmentKey ? ` · ${record.segmentMissing ? '原分段已移除' : record.segmentKey}` : ''}</Text>
    <Text variant="bodySmall">更新于 {record.updatedAt} · 版本 {record.revision}</Text>
  </View>;
  return <View testID="journey-documents-panel" style={{ gap: density.screenGap }}>
    <PageHeader title={props.journeyId ? '旅行资料' : '我的旅行资料'} description="预订凭证集中保存。默认仅本人，分享由你决定。"
      action={<Button contentStyle={styles.touch} accessibilityLabel={props.initialDocumentId ? '返回资料搜索' : '返回旅行资料入口'} disabled={busy || !!model.unknown} onPress={() => back('panel')}>{props.initialDocumentId ? '返回搜索' : '返回'}</Button>} />
    {!!message && <Text testID="journey-documents-message">{message}</Text>}{!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在处理旅行资料" />}
    {!visible ? <EmptyState title="旅行资料已隐藏" description="正在核对身份；离线和后台期间仅在内存保留你的草稿。"
      action={<Button contentStyle={styles.touch} disabled={busy || !online()} onPress={() => { if (active.current) void job(load); else enter(); }}>重新读取旅行资料</Button>} /> : <>
      {model.unknown && <SectionCard title="先核对操作结果"><View testID="journey-documents-unknown" style={{ gap: density.tripGap }}>
        <Text>请求可能已完成。列表只是当前状态，不是上次操作的回执；页面不会自动重发。</Text>
        <Button contentStyle={styles.touch} mode="outlined" disabled={busy} onPress={() => void job(load)}>核对资料当前状态</Button>
        {model.unknown.kind === 'upload' && <>
          <Text style={styles.wrap}>本次文件：{model.unknown.payload.file.name}</Text>
          <Button contentStyle={styles.touch} mode="contained" disabled={busy} onPress={() => { const intent = live.current.unknown; if (intent?.kind === 'upload') void send(intent, true); }}>按原请求重试上传</Button>
          {model.checked && <><Text>下方是刚读取的可见资料，请核对标题、文件名和共享范围。</Text>
            <Button contentStyle={styles.touch} disabled={busy} onPress={() => setLeaving('unknown')}>结束本次上传并返回列表</Button></>}
        </>}
      </View></SectionCard>}
      {model.blocked && !model.review && !model.unknown && <SectionCard title="资料已变化"><Text>保留了你的草稿，请先读取当前资料后核对。</Text><Button contentStyle={styles.touch} disabled={busy} onPress={() => void job(load)}>读取最新资料</Button></SectionCard>}
      {model.review && <SectionCard title="刚读取的当前资料"><View testID="journey-documents-review" style={{ gap: density.tripGap }}>
        {model.review.document ? metadata(model.review.document) : <Text>本人资料库当前没有这份文件。不能据此确定上次操作是否执行；不会自动重建或删除。</Text>}
        {actions(<><Button contentStyle={styles.touch} mode="outlined" disabled={busy} onPress={() => decide(false)}>采用当前资料状态</Button>
          {!!model.review.document && editor?.kind === 'edit' && <Button contentStyle={styles.touch} mode="contained" disabled={busy} onPress={() => decide(true)}>保留我的修改</Button>}</>)}
      </View></SectionCard>}
      {editor && !model.unknown ? <SectionCard title={editor.kind === 'upload' ? '上传资料' : '编辑资料'}><View testID="journey-document-editor" style={{ gap: density.sectionGap }}>
        {editor.kind === 'upload' && <><Button icon="file-upload-outline" accessibilityLabel="选择资料文件" contentStyle={styles.touch} mode="outlined" disabled={locked} onPress={() => void chooseFile()}>选择资料文件</Button>
          <Text style={styles.wrap}>{editor.file ? editor.file.name : 'PDF、JPG、PNG 或 WebP，每份最多 5 MB。图片会去除元数据并保存为 JPEG。'}</Text></>}
        <TextInput mode="outlined" label="资料标题" accessibilityLabel="资料标题" value={editor.fields.title} disabled={locked} onChangeText={title => edit({ title })} />
        <Text>关联旅行</Text><TouchableRipple style={[styles.selector, { borderColor: theme.colors.outline }]} accessibilityRole="button" accessibilityLabel="选择关联旅行" disabled={locked} onPress={() => { setChoice('journey'); setChoiceSearch(''); setChoicePage(0); }}><Text style={styles.wrap}>{journeyTitle(editor.fields.journeyId)}</Text></TouchableRipple>
        {editor.fields.journeyId && <><Text>关联分段</Text><TouchableRipple style={[styles.selector, { borderColor: theme.colors.outline }]} accessibilityRole="button" accessibilityLabel="选择关联分段" disabled={locked} onPress={() => { setChoice('segment'); setChoiceSearch(''); setChoicePage(0); }}><Text style={styles.wrap}>{segmentTitle}</Text></TouchableRipple></>}
        <View accessibilityRole="radiogroup" accessibilityLabel="资料共享范围">
          <SelectionRow kind="radio" label="仅本人可见" checked={editor.fields.visibility === 'private'} disabled={locked} onPress={() => edit({ visibility: 'private' })} />
          <SelectionRow kind="radio" label="与家庭共享" checked={editor.fields.visibility === 'shared'} disabled={locked || !editor.fields.journeyId} onPress={() => edit({ visibility: 'shared' })} />
        </View><Text variant="bodySmall">解除旅行关联后只对本人可见。文件内容不会发送到 AI、云日历或电视。</Text>
        {actions(<><Button contentStyle={styles.touch} mode="contained" disabled={locked || editor.kind === 'edit' && !dirty(model)} onPress={save}>{editor.kind === 'upload' ? '确认上传资料' : '保存资料修改'}</Button>
          <Button contentStyle={styles.touch} disabled={busy || !!model.unknown} onPress={() => back('editor')}>返回资料列表</Button></>)}
      </View></SectionCard> : focusedRecord && !model.unknown ? <SectionCard title="资料详情"><View testID="journey-document-detail" style={{ gap: density.sectionGap }}>
        {metadata(focusedRecord)}{actions(<><Button contentStyle={styles.touch} mode="contained" disabled={busy} onPress={() => void download(focusedRecord)}>下载资料</Button>
          {focusedRecord.canManage && <><Button contentStyle={styles.touch} mode="outlined" disabled={busy} onPress={() => void openEdit(focusedRecord)}>编辑资料</Button><Button contentStyle={styles.touch} textColor={theme.colors.error} disabled={busy} onPress={() => setDeleting(true)}>删除这份资料</Button></>}
          <Button contentStyle={styles.touch} disabled={busy} onPress={() => back('editor')}>返回资料列表</Button></>)}
      </View></SectionCard> : <View testID="journey-documents-list" style={{ gap: density.sectionGap }}>
        {actions(<><Button contentStyle={styles.touch} mode="contained" icon="plus" accessibilityLabel="上传资料" disabled={busy || !!model.unknown} onPress={openUpload}>上传资料</Button>
          <Button contentStyle={styles.touch} disabled={busy} onPress={() => void job(load)}>刷新资料列表</Button></>)}
        <TextInput mode="outlined" label="搜索资料" accessibilityLabel="搜索资料" value={search} onChangeText={text => { setSearch(text); setPage(0); }} />
        {!rows.length ? <EmptyState title={search ? '没有匹配的资料' : '还没有可见资料'} description={props.journeyId ? '可上传自己的凭证；伙伴明确共享的文件也会出现在这里。' : '这里保留你上传的资料，包括已删除旅行留下的文件。'} /> : shown.map(record =>
          <SectionCard key={record.id} title={record.title}><View testID={`journey-document-${record.id}`} style={{ gap: density.tripGap }}>{metadata(record, false)}
            <Button contentStyle={styles.touch} accessibilityLabel={`查看资料：${record.title}`} mode="outlined" disabled={busy || !!model.unknown} onPress={() => { install({ focus: record.id }); setMessage(''); setError(''); }}>查看资料</Button>
          </View></SectionCard>)}
        {rows.length > PAGE_SIZE && actions(<><Button contentStyle={styles.touch} disabled={shownPage === 0} onPress={() => setPage(shownPage - 1)}>上一页资料</Button><Text>第 {shownPage + 1} / {maxPage + 1} 页 · {rows.length} 份</Text><Button contentStyle={styles.touch} disabled={shownPage === maxPage} onPress={() => setPage(shownPage + 1)}>下一页资料</Button></>)}
      </View>}
    </>}
    <Portal>
      <Dialog visible={visible && !!choice && !locked} onDismiss={() => setChoice(null)} style={styles.dialog}><Dialog.Title>{choice === 'journey' ? '选择关联旅行' : '选择关联分段'}</Dialog.Title>
        <Dialog.Content><TextInput mode="outlined" accessibilityLabel="搜索关联选项" label="搜索" value={choiceSearch} onChangeText={text => { setChoiceSearch(text); setChoicePage(0); }} /></Dialog.Content>
        <Dialog.ScrollArea><ScrollView style={styles.choiceScroll}>{options.slice(choiceCurrent * PAGE_SIZE, (choiceCurrent + 1) * PAGE_SIZE).map(option => <TouchableRipple key={option.key} accessibilityRole="menuitem" accessibilityLabel={option.title}
          onPress={() => { if (!current() || working.current || live.current.unknown || live.current.blocked) return; if (choice === 'journey') void selectJourney(option.key || null); else { edit({ segmentKey: option.key }); setChoice(null); } }} style={styles.option}>
          <Text style={styles.wrap}>{option.title}</Text></TouchableRipple>)}{!options.length && <Text style={styles.option}>暂无匹配选项</Text>}</ScrollView></Dialog.ScrollArea>
        <Dialog.Actions style={styles.actions}><Button contentStyle={styles.touch} disabled={choiceCurrent === 0} onPress={() => setChoicePage(choiceCurrent - 1)}>上一页选项</Button><Button contentStyle={styles.touch} disabled={choiceCurrent === choiceMax} onPress={() => setChoicePage(choiceCurrent + 1)}>下一页选项</Button><Button contentStyle={styles.touch} onPress={() => setChoice(null)}>取消选择</Button></Dialog.Actions>
      </Dialog>
      <Dialog visible={visible && deleting && !busy && !model.unknown} onDismiss={() => setDeleting(false)}><Dialog.Title>删除这份资料？</Dialog.Title><Dialog.Content><Text>文件和共享入口将被移除，无法在这里撤销。不会更改旅行或外部预订。</Text></Dialog.Content><Dialog.Actions>
        <Button contentStyle={styles.touch} onPress={() => setDeleting(false)}>保留资料</Button><Button contentStyle={styles.touch} textColor={theme.colors.error} onPress={() => { const record = live.current.list?.documents.find(item => item.id === live.current.focus); setDeleting(false); if (record?.canManage && current() && !working.current) void send({ kind: 'delete', id: record.id, payload: { revision: record.revision } }); }}>确认删除资料</Button>
      </Dialog.Actions></Dialog>
      <Dialog visible={visible && !!leaving && !busy} onDismiss={() => setLeaving(null)}><Dialog.Title>{leaving === 'unknown' ? '结束本次上传核对？' : '放弃未保存的修改？'}</Dialog.Title><Dialog.Content><Text>{leaving === 'unknown' ? '这不会撤销服务器可能已保存的文件。结束后不再保留本次请求编号，请先核对当前列表。' : '只放弃内存中的修改，服务器资料保持不变。'}</Text></Dialog.Content><Dialog.Actions>
        <Button contentStyle={styles.touch} onPress={() => setLeaving(null)}>继续核对</Button><Button contentStyle={styles.touch} onPress={discard}>{leaving === 'unknown' ? '确认结束上传核对' : '确认放弃修改'}</Button>
      </Dialog.Actions></Dialog>
    </Portal>
  </View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 }, wrap: { flexShrink: 1 },
  dialog: { maxWidth: 640, width: '92%', alignSelf: 'center' }, choiceScroll: { maxHeight: 320 }, option: { padding: 16, minHeight: 48 }, selector: { borderWidth: 1, borderRadius: 8, padding: 14, minHeight: 48 } });
