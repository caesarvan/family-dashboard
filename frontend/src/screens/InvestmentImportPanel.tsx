import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Text, TextInput, TouchableRipple, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import type { Member } from '../lib/types';
import { canConfirmHoldingImport, holdingCheckedRead, holdingImportAttempt, holdingImportPayload, holdingMoney, holdingReceiptPath, holdingRecoveryChoices,
  holdingSourceName, readHoldingImportPreview, readHoldingSources, readHoldingTemplate, readInvestmentImportReceipt, HOLDING_FILE_LIMIT,
  type HoldingFile, type HoldingImportAttempt, type HoldingImportPayload, type HoldingImportPreview, type HoldingSource,
  type ImportHolding, type InvestmentImportReceipt, HOLDING_PREVIEW_MS } from '../lib/investmentImport';

export type InvestmentImportPanelProps = { user: Member; identityKey: string; initialSourceName?: string; onDismiss: () => void; onImported: (receipt: InvestmentImportReceipt) => void };
const front = () => typeof document === 'undefined' || !document.hidden;
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '暂时无法读取，请稍后重试。';
const actions = { create: '新增', update: '更新', unchanged: '不变' };
const PAGE_SIZE = 12;

function browserFile(signal: AbortSignal): Promise<File | null> {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return Promise.reject(new Error('请在手机或电脑浏览器中选择文件。'));
  return new Promise((resolve, reject) => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.csv,.txt,.xlsx';
    input.setAttribute('aria-label', '持仓整理表文件'); input.style.display = 'none'; document.body.appendChild(input);
    let finished = false;
    const finish = (file: File | null) => { if (finished) return; finished = true; signal.removeEventListener('abort', abort); input.remove(); resolve(file); };
    const abort = () => finish(null);
    input.addEventListener('change', () => finish(input.files?.[0] || null), { once: true });
    input.addEventListener('cancel', () => finish(null), { once: true }); signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) return finish(null);
    try { input.click(); } catch (error) { signal.removeEventListener('abort', abort); input.remove(); finished = true; reject(error); }
  });
}
async function fileData(file: File): Promise<HoldingFile> {
  if (!file.size || file.size > HOLDING_FILE_LIMIT) throw new Error('请选择非空且不超过 2 MiB 的整理表。');
  if (!/\.(csv|txt|xlsx)$/i.test(file.name)) throw new Error('支持 CSV、TXT 和无宏 XLSX。');
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.byteLength !== file.size) throw new Error('文件读取不完整，请重新选择。');
  let binary = '';
  for (let i = 0; i < bytes.length; i += 16384) binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return { name: file.name, contentBase64: btoa(binary), encoding: 'auto' };
}
function HoldingValues({ title, value }: { title: string; value: ImportHolding | null }) {
  return <View style={styles.values}><Text variant="labelLarge">{title}</Text>{value ? <>
    <Text>{value.name}</Text><Text variant="bodySmall">{value.institution} · {value.assetType} · {value.currency}</Text>
    <Text>总成本 {holdingMoney(value.costCents, value.currency)}</Text><Text>总估值 {holdingMoney(value.valueCents, value.currency)}</Text>
    <Text variant="bodySmall">数量 {value.quantity ?? '未填写'} · 核对日期 {value.asOf}</Text>
    {!!value.note && <Text variant="bodySmall">备注：{value.note}</Text>}
    {!!value.id && <Text variant="bodySmall">记录 {value.id} · 版本 {value.revision}</Text>}
  </> : <Text>尚无关联持仓</Text>}</View>;
}

export default function InvestmentImportPanel(props: InvestmentImportPanelProps) {
  return props.user.role === 'member' ? <ImportWorkspace key={props.identityKey} {...props} /> : null;
}
function ImportWorkspace({ user, identityKey, initialSourceName, onDismiss, onImported }: InvestmentImportPanelProps) {
  const household = useHousehold(), latest = useRef(household), theme = useTheme(), { height } = useWindowDimensions(); latest.current = household;
  const mounted = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), user, identityKey));
  const generation = useRef(0), draftEpoch = useRef(0), reading = useRef(false), writing = useRef(false);
  const picker = useRef<AbortController | null>(null), pendingRef = useRef<HoldingImportAttempt | null>(null);
  const previewRef = useRef<{ value: HoldingImportPreview; payload: HoldingImportPayload; receivedAt: number } | null>(null);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [sources, setSources] = useState<HoldingSource[]>([]), [source, setSource] = useState(initialSourceName || ''), [newSource, setNewSource] = useState(false);
  const [file, setFile] = useState<HoldingFile | null>(null), [sheets, setSheets] = useState<string[]>([]), [sheet, setSheet] = useState('');
  const [preview, setPreview] = useState<HoldingImportPreview | null>(null), [pending, setPendingState] = useState<HoldingImportAttempt | null>(null);
  const [receipt, setReceipt] = useState<InvestmentImportReceipt | null>(null), [notice, setNotice] = useState(''), [downloadNotes, setDownloadNotes] = useState<string[]>([]);
  const [menu, setMenu] = useState<'source' | 'sheet' | 'encoding' | ''>(''), [page, setPage] = useState(0), [errorPage, setErrorPage] = useState(0), [leaving, setLeaving] = useState(false);
  const current = () => mounted.current && focused.current && active.current && !denied.current && appActive.current
    && latest.current.identityKey === identityKey && latest.current.user?.role === 'member' && latest.current.online && front() && connected();
  const setPending = (value: HoldingImportAttempt | null) => { pendingRef.current = value; setPendingState(value ? { ...value } : null); };
  function invalidatePreview() { ++draftEpoch.current; previewRef.current = null; setPreview(null); setPage(0); setErrorPage(0); setError(''); setNotice(''); }
  function reset() { invalidatePreview(); setFile(null); setSheet(''); setSheets([]); setPending(null); setReceipt(null); setSources([]); setSource(''); setDownloadNotes([]); }
  function conceal(clear = false) {
    active.current = false; ++generation.current; fence.current.invalidate(); setVisible(false); setBusy(false); setMenu(''); setLeaving(false);
    if (clear) { reset(); picker.current?.abort(); }
  }
  function failed(error: unknown) {
    if (!mounted.current || latest.current.identityKey !== identityKey) return;
    if (error instanceof PhotoReadDiscarded && error.message !== 'identity') return;
    if (error instanceof PhotoReadDiscarded || error instanceof ApiError && [401, 403].includes(error.status)) {
      conceal(true); denied.current = true; setError('登录身份已变化，请关闭后重新进入。'); void latest.current.refresh(); return;
    }
    if (current()) setError(errorMessage(error));
  }
  async function guarded<T>(load: () => Promise<T>, ticket = generation.current) { return holdingCheckedRead(fence.current, load, () => current() && generation.current === ticket); }
  async function resume() {
    if (!mounted.current || !focused.current || !appActive.current || denied.current || !front() || !connected() || !latest.current.online) return;
    const ticket = ++generation.current; active.current = true;
    try {
      const result = readHoldingSources(await guarded(() => request<unknown>('/finance-hub/investments'), ticket));
      if (!current() || ticket !== generation.current) return;
      setSources(result); if (!result.length) setNewSource(true); setVisible(true); setBusy(reading.current || writing.current);
    } catch (error) { failed(error); }
  }
  useEffect(() => {
    mounted.current = true;
    const change = () => { if (!front() || !connected()) conceal(); else void resume(); };
    const subscription = AppState.addEventListener('change', value => { appActive.current = value === 'active'; if (appActive.current) void resume(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', change);
    if (typeof window !== 'undefined') { window.addEventListener('offline', change); window.addEventListener('online', change); }
    return () => { mounted.current = false; focused.current = false; active.current = false; ++generation.current; ++draftEpoch.current;
      fence.current.invalidate(); picker.current?.abort(); subscription.remove();
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', change);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', change); window.removeEventListener('online', change); } };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; void resume(); return () => { focused.current = false; conceal(); }; }, [identityKey]));
  useEffect(() => { if (!household.online) conceal(); else if (focused.current) void resume(); }, [household.online]);

  async function choose() {
    if (!current() || reading.current || writing.current || pendingRef.current) return;
    picker.current?.abort(); picker.current = new AbortController(); let epoch = ++draftEpoch.current, started = false;
    try {
      const selected = await browserFile(picker.current.signal);
      if (!selected || !current() || epoch !== draftEpoch.current || reading.current || writing.current || pendingRef.current) return;
      invalidatePreview(); epoch = draftEpoch.current; setFile(null); setSheet(''); setSheets([]); setReceipt(null);
      reading.current = true; started = true; setBusy(true);
      const next = await fileData(selected);
      if (!current() || epoch !== draftEpoch.current) return;
      await guarded(async () => true); if (current() && epoch === draftEpoch.current) setFile(next);
    } catch (error) { if (epoch === draftEpoch.current) failed(error); }
    finally { if (started) { reading.current = false; if (current()) setBusy(writing.current); } }
  }
  async function previewFile(payload: HoldingImportPayload, previous?: HoldingImportAttempt) {
    if (!current() || reading.current || writing.current || pendingRef.current && pendingRef.current !== previous) return;
    invalidatePreview(); const epoch = draftEpoch.current, ticket = generation.current, startedAt = Date.now(); reading.current = true; setBusy(true);
    try {
      const result = readHoldingImportPreview(await guarded(() => latest.current.mutate<unknown>('/finance-hub/investments/imports/preview', 'POST', payload), ticket), payload.sourceName);
      if (!current() || epoch !== draftEpoch.current || previous && pendingRef.current !== previous) return;
      if (previous && result.sourceDigest !== previous.sourceDigest) throw new Error('原文件的保存标识已变化，请先返回持仓核对。');
      previewRef.current = { value: result, payload, receivedAt: startedAt }; setPreview(result);
      if (result.requiresSheetSelection) setSheets(result.fileInfo.sheets);
      if (previous) { setPending(null); setNotice('原请求暂未查到回执。新的预览不代表原保存失败；再次确认仍会按同一来源文件核对已有回执。'); }
    } catch (error) { if (epoch === draftEpoch.current) failed(error); }
    finally { reading.current = false; if (current()) setBusy(writing.current); }
  }
  function inspect() {
    if (!file || !current() || pendingRef.current) return;
    try { void previewFile(holdingImportPayload(source, { ...file, ...(sheet ? { sheet } : {}) })); } catch (error) { failed(error); }
  }
  function received(result: InvestmentImportReceipt, intent: HoldingImportAttempt) {
    if (!current() || pendingRef.current !== intent) return;
    setReceipt(result); setPending(null); previewRef.current = null; setPreview(null); setFile(null); setSheets([]); setSheet(''); setNotice(''); setError('');
  }
  async function send(intent: HoldingImportAttempt) {
    if (!current() || reading.current || writing.current || pendingRef.current !== intent) return;
    const ticket = generation.current; writing.current = true; setBusy(true); setError(''); intent.notFound = false; setPending(intent);
    try {
      const result = readInvestmentImportReceipt(await guarded(() => latest.current.mutate<unknown>('/finance-hub/investments/imports/confirm', 'POST', { previewToken: intent.previewToken }), ticket), intent);
      received(result, intent);
    } catch (error) {
      if (pendingRef.current === intent) {
        intent.uncertain = true;
        if (current() && generation.current === ticket && !(error instanceof PhotoReadDiscarded)) {
          if (error instanceof ApiError && [400, 409].includes(error.status)) intent.previewRejected = true;
          setPending(intent); setError('保存结果需要核对。请先读取本次回执；预览失效时也不要直接重复导入。');
        }
      }
      failed(error);
    } finally { writing.current = false; if (current()) setBusy(reading.current); }
  }
  function confirm() {
    if (!current() || reading.current || writing.current || pendingRef.current || !previewRef.current) return;
    try {
      const p = previewRef.current, intent = holdingImportAttempt(p.payload, p.value, p.receivedAt);
      if (Date.now() - p.receivedAt >= HOLDING_PREVIEW_MS || Date.now() < p.receivedAt) {
        intent.previewRejected = true; intent.uncertain = true; setPending(intent); void lookup(intent);
      } else { setPending(intent); void send(intent); }
    } catch (error) { failed(error); }
  }
  async function lookup(intent = pendingRef.current): Promise<'found' | 'not_found' | 'failed'> {
    if (!intent || !current() || reading.current || writing.current || pendingRef.current !== intent) return 'failed';
    const ticket = generation.current; reading.current = true; setBusy(true); setError(''); intent.notFound = false; setPending(intent);
    try {
      const result = readInvestmentImportReceipt(await guarded(() => request<unknown>(holdingReceiptPath(intent.sourceName, intent.sourceDigest)), ticket), intent, true);
      received(result, intent); return current() ? 'found' : 'failed';
    } catch (error) {
      if (current() && pendingRef.current === intent && error instanceof ApiError && error.status === 404 && error.code === 'investment_import_receipt_not_found') {
        try { await guarded(async () => true, ticket); } catch (identityError) { failed(identityError); return 'failed'; }
        if (!current() || generation.current !== ticket || pendingRef.current !== intent) return 'failed';
        intent.notFound = true; setPending(intent); setError('暂未读到本次回执，原请求也可能仍在处理。可继续核对；重新预览后仍需你明确确认。'); return 'not_found';
      }
      failed(error); return 'failed';
    } finally { reading.current = false; if (current()) setBusy(writing.current); }
  }
  async function repreview() {
    const intent = pendingRef.current;
    if (!intent || !holdingRecoveryChoices(intent).repreviewOriginal) return;
    if (await lookup(intent) === 'not_found' && current() && pendingRef.current === intent) await previewFile(intent.original, intent);
  }
  async function template(mode: 'sample' | 'current') {
    if (!current() || reading.current || writing.current || pendingRef.current) return;
    reading.current = true; setBusy(true); setError('');
    try {
      const named = mode === 'current' ? holdingSourceName(source) : undefined;
      const value = readHoldingTemplate(await guarded(() => request<unknown>('/finance-hub/investments/imports/template?mode=' + mode + (named ? '&sourceName=' + encodeURIComponent(named) : ''))), mode, named);
      if (!current()) return;
      if (Platform.OS !== 'web' || typeof document === 'undefined') throw new Error('请在浏览器中下载整理表。');
      const url = URL.createObjectURL(new Blob(['\ufeff', value.csv], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a'); link.href = url; link.download = value.filename; document.body.appendChild(link);
      try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
      setDownloadNotes([`已下载 ${value.rowCount} 行${mode === 'sample' ? '虚构示例，请替换为自己的持仓' : '当前整理表，请保留 recordId 和文本保护列'}。`, ...value.warnings]);
    } catch (error) { failed(error); } finally { reading.current = false; if (current()) setBusy(writing.current); }
  }
  async function showResults() {
    if (!receipt || !current() || reading.current || writing.current) return;
    try { await guarded(async () => true); if (current()) onImported(receipt); } catch (error) { failed(error); }
  }
  const disabled = busy || !!pending || !!receipt;
  const dismiss = () => { if (file || pendingRef.current) setLeaving(true); else onDismiss(); };
  const dialogStyle = { maxWidth: 940, width: '94%' as const, marginHorizontal: 0, marginVertical: 20, maxHeight: Math.max(240, height - 40), alignSelf: 'center' as const, borderRadius: 24, backgroundColor: theme.colors.surface };
  const choices: { key: string; label: string; sourceName?: string; create?: boolean }[] = menu === 'source' ? [...sources.map(s => ({ key: 'source:' + s.sourceName, label: s.sourceName, sourceName: s.sourceName })), { key: 'create-source', label: '新增来源名称', create: true }]
    : menu === 'sheet' ? sheets.map(s => ({ key: s, label: s })) : [{ key: 'auto', label: '自动识别' }, { key: 'utf-8', label: 'UTF-8' }, { key: 'gb18030', label: 'GB18030' }];
  if (!visible) return <Dialog visible style={dialogStyle} dismissable={false}><Dialog.Title>导入持仓整理表</Dialog.Title><Dialog.Content>
    <Text>{error || '正在核对身份，文件内容暂不显示。'}</Text>{!connected() || !household.online ? <Text>恢复连接后可继续核对。</Text> : <Button onPress={() => void resume()}>重新核对身份</Button>}
  </Dialog.Content><Dialog.Actions><Button onPress={onDismiss}>返回持仓</Button></Dialog.Actions></Dialog>;
  return <>
    <Dialog visible dismissable={!busy} onDismiss={dismiss} style={dialogStyle} testID="investment-import-panel">
      <Dialog.Title>导入持仓整理表</Dialog.Title>
      <Dialog.ScrollArea style={{ paddingHorizontal: 0, flexShrink: 1 }}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.body}>
        {!!error && <View style={styles.block}><Text accessibilityLiveRegion="polite">{error}</Text></View>}
        {receipt ? <View testID="investment-import-receipt" style={styles.stack}>
          <Text variant="headlineSmall">已确认这份文件的保存结果</Text><Text>{receipt.sourceName}</Text>
          <Text>新增 {receipt.created} 项 · 更新 {receipt.updated} 项 · 不变 {receipt.unchanged} 项</Text>
          <Text>{receipt.replayed ? '这是此前的保存回执。' : '本次保存已确认。'}后来修改或删除的持仓不会因查看回执恢复；当前值请返回持仓读取。</Text>
          <Text variant="bodySmall">确认时间：{receipt.confirmedAt}</Text><Text variant="bodySmall">回执：{receipt.receiptId}</Text>
          <Button mode="contained" onPress={() => void showResults()}>查看持仓</Button>
        </View> : pending ? <View style={styles.stack}>
          <Text variant="titleLarge">核对本次保存</Text><Text>来源：{pending.sourceName}。原文件与预览仅保留在本页内存；先读取回执，不会再次写入。</Text>
          <Button mode="contained" loading={busy} disabled={busy} onPress={() => void lookup()}>核对持仓保存结果</Button>
          {holdingRecoveryChoices(pending).retryOriginal && <Button mode="outlined" disabled={busy} onPress={() => { const intent = pendingRef.current; if (intent && holdingRecoveryChoices(intent).retryOriginal) void send(intent); }}>使用原预览重试</Button>}
          {holdingRecoveryChoices(pending).repreviewOriginal && <Button mode="outlined" disabled={busy} onPress={() => void repreview()}>使用原文件重新预览</Button>}
          <Text variant="bodySmall">预览有效期 15 分钟。重新预览会先再查一次回执，新的预览也必须明确确认。</Text>
        </View> : <>
          <Text>先把本人核对的持仓整理为标准模板，再预览并整批保存。各币种单独记录，空估值保留“未知”。</Text>
          <View style={styles.stack}><Text variant="titleMedium">1 · 选择账户来源</Text>
            <Button mode="outlined" accessibilityLabel="选择持仓来源" disabled={disabled} onPress={() => setMenu('source')}>{source || '选择或新增来源'}</Button>
            {newSource && <TextInput mode="outlined" label="持仓来源名称" accessibilityLabel="持仓来源名称" value={source} disabled={disabled} maxLength={160} onChangeText={value => { invalidatePreview(); setSource(value); setDownloadNotes([]); }} />}
            <Text variant="bodySmall">使用稳定的自定义名称，例如“我的券商账户”。同一账户请保持来源名称和 holdingKey 不变；确认导入后才建立新来源。</Text>
            <View style={styles.controls}><Button disabled={disabled} onPress={() => void template('sample')}>下载示例整理表</Button><Button disabled={disabled || !source.trim()} onPress={() => void template('current')}>下载当前整理表</Button></View>
            {downloadNotes.map((note, i) => <Text key={i} variant="bodySmall">{note}</Text>)}
          </View><Divider />
          <View style={styles.stack}><Text variant="titleMedium">2 · 读取整理表</Text>
            <Button mode="outlined" icon="file-upload-outline" accessibilityLabel="选择持仓文件" disabled={disabled} onPress={() => void choose()}>选择持仓文件</Button>
            <Text>{file?.name || '支持 CSV、TXT、无宏 XLSX，最大 2 MiB、最多 300 项持仓。'}</Text>
            {file && !/\.xlsx$/i.test(file.name) && <Button disabled={disabled} onPress={() => setMenu('encoding')}>文件编码：{file.encoding === 'auto' ? '自动识别' : file.encoding.toUpperCase()}</Button>}
            {!!sheets.length && <><Button mode="outlined" accessibilityLabel="选择持仓工作表" disabled={disabled} onPress={() => setMenu('sheet')}>{sheet || '选择持仓工作表'}</Button><Text variant="bodySmall">这里只列出工作表名称，选表后才校验记录。</Text></>}
            <Button mode="contained" disabled={disabled || !source.trim() || !file || !!sheets.length && !sheet} loading={busy} onPress={inspect}>{sheets.length ? '读取所选工作表' : '预览持仓文件'}</Button>
          </View>
          {preview && !preview.requiresSheetSelection && <View testID="investment-import-preview" style={styles.stack}><Divider /><Text variant="titleMedium">3 · 核对本次变化</Text>
            {!!notice && <Text>{notice}</Text>}
            <Text>新增 {preview.counts.create} 项 · 更新 {preview.counts.update} 项 · 不变 {preview.counts.unchanged} 项 · 错误 {preview.errorCount} 项</Text>
            <Text>本次文件缺少的 {preview.preservedCount} 项原持仓将保留；缺行不代表清仓，已删除记录不会自动恢复。</Text>
            <Text variant="bodySmall">{preview.fileInfo.name} · {preview.fileInfo.encoding}{preview.fileInfo.sheet ? ' · ' + preview.fileInfo.sheet : ''}</Text>
            {preview.warnings.map((warning, i) => <Text key={i}>{warning}</Text>)}
            {preview.replayed && <Text>这份原文件此前已确认。下方不展示历史文件作为当前值；确认只会返回历史回执。</Text>}
            {!!preview.errors.length && <View testID="investment-import-errors" style={styles.stack}>{preview.errors.slice(errorPage * PAGE_SIZE, (errorPage + 1) * PAGE_SIZE).map((r, i) => <Text key={i}>{r.line === 0 ? '整批' : `第 ${r.line} 行`}：{r.message}</Text>)}
              <Text>请修正文件再重新选择，存在错误时不会部分保存。</Text>
              {preview.errors.length > PAGE_SIZE && <View style={styles.controls}><Button disabled={!errorPage} onPress={() => setErrorPage(p => p - 1)}>上一页错误</Button><Text>{errorPage + 1} / {Math.ceil(preview.errors.length / PAGE_SIZE)}</Text><Button disabled={(errorPage + 1) * PAGE_SIZE >= preview.errors.length} onPress={() => setErrorPage(p => p + 1)}>下一页错误</Button></View>}
            </View>}
            {preview.rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(row => <View key={row.holdingKey} testID={'investment-import-row-' + row.line} style={[styles.block, { backgroundColor: theme.colors.surfaceVariant }]}>
              <Text variant="titleMedium">{actions[row.action]} · {row.after.name}</Text><Text variant="bodySmall">第 {row.line} 行 · 持仓编号 {row.holdingKey}</Text>
              <View style={styles.columns}><HoldingValues title="之前" value={row.before} /><HoldingValues title="之后" value={row.after} /></View>
              {row.warnings.map((warning, i) => <Text key={i} variant="bodySmall">{warning}</Text>)}
            </View>)}
            {preview.rows.length > PAGE_SIZE && <View style={styles.controls}><Button disabled={!page} onPress={() => setPage(p => p - 1)}>上一页持仓</Button><Text>{page + 1} / {Math.ceil(preview.rows.length / PAGE_SIZE)}</Text><Button disabled={(page + 1) * PAGE_SIZE >= preview.rows.length} onPress={() => setPage(p => p + 1)}>下一页持仓</Button></View>}
            <Button mode="contained" disabled={disabled || !canConfirmHoldingImport(preview)} onPress={confirm}>确认导入持仓 · 仅本人</Button>
          </View>}
        </>}
        {busy && <ActivityIndicator accessibilityLabel="正在处理持仓整理表" />}
      </ScrollView></Dialog.ScrollArea>
      <Dialog.Actions><Button disabled={busy} onPress={dismiss}>返回持仓</Button></Dialog.Actions>
    </Dialog>
    <Dialog visible={!!menu} onDismiss={() => setMenu('')} style={dialogStyle}><Dialog.Title>{menu === 'source' ? '选择持仓来源' : menu === 'sheet' ? '选择持仓工作表' : '选择文件编码'}</Dialog.Title>
      <Dialog.ScrollArea style={{ paddingHorizontal: 0, flexShrink: 1 }}><ScrollView>{choices.map(item => <TouchableRipple key={item.key} accessibilityRole="menuitem" accessibilityLabel={item.label} disabled={disabled}
        onPress={() => { if (!current() || disabled) return; invalidatePreview(); setMenu('');
          if (menu === 'source') { setNewSource(item.create === true); setSource(item.create ? '' : item.sourceName || ''); setDownloadNotes([]); }
          else if (menu === 'sheet') setSheet(item.key); else if (file) setFile({ ...file, encoding: item.key as HoldingFile['encoding'] }); }} style={styles.option}><Text>{item.label}</Text></TouchableRipple>)}</ScrollView></Dialog.ScrollArea>
      <Dialog.Actions><Button onPress={() => setMenu('')}>取消</Button></Dialog.Actions>
    </Dialog>
    <Dialog visible={leaving} onDismiss={() => setLeaving(false)} style={dialogStyle}><Dialog.Title>离开持仓导入？</Dialog.Title><Dialog.Content><Text>{pending ? '保存可能已经完成，离开不会撤销。返回后请重新读取持仓；本页原文件与预览会清除。' : '尚未确认的整理表不会保存。离开后需要重新选择文件。'}</Text></Dialog.Content>
      <Dialog.Actions><Button onPress={() => setLeaving(false)}>继续核对</Button><Button onPress={() => { reset(); onDismiss(); }}>返回持仓</Button></Dialog.Actions>
    </Dialog>
  </>;
}
const styles = StyleSheet.create({ body: { padding: 24, gap: 20 }, stack: { gap: 12 }, controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  block: { padding: 18, borderRadius: 18, gap: 10, minWidth: 0 }, columns: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 }, values: { flex: 1, minWidth: 200, gap: 6 }, option: { padding: 18, minHeight: 48 } });
