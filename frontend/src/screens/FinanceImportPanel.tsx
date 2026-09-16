import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Menu, Portal, SegmentedButtons, Text, TouchableRipple, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import { canConfirmImport, confirmImportPayload, importAmount, importPayload, importRejectionIsDefinite, importSourceLabel, newImportRequestId, readImportPreview, readImportReceipt,
  type FinanceImportReceipt, type ImportFile, type ImportKind, type ImportPayload, type ImportPreview, type ImportSource } from '../lib/financeImport';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Props = { onClose: () => void; onImported: (receipt: FinanceImportReceipt) => void };
type Pending = { requestId: string; payload: ReturnType<typeof confirmImportPayload>; uncertain: boolean };
const sources: Record<ImportSource, string> = { generic: '通用表格', alipay: '支付宝', wechat: '微信', taobao: '淘宝', pinduoduo: '拼多多' };
const flows: Record<string, string> = { expense: '支出', income: '收入', refund: '退款', transfer: '转账／还款', unknown: '待核对', excluded: '不计收支' };
const front = () => typeof document === 'undefined' || !document.hidden;
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法读取，请稍后重试。';

function browserFile(signal: AbortSignal): Promise<File | null> {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return Promise.reject(new Error('请在手机或电脑浏览器中导入文件。'));
  return new Promise((resolve, reject) => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.csv,.txt,.xlsx';
    input.setAttribute('aria-label', '账单文件'); input.style.display = 'none'; document.body.appendChild(input);
    const finish = (file: File | null) => { signal.removeEventListener('abort', abort); input.remove(); resolve(file); };
    const abort = () => finish(null);
    input.addEventListener('change', () => finish(input.files?.[0] || null), { once: true });
    input.addEventListener('cancel', () => finish(null), { once: true });
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) return finish(null);
    try { input.click(); } catch (error) { signal.removeEventListener('abort', abort); input.remove(); reject(error); }
  });
}
async function fileData(file: File): Promise<ImportFile> {
  if (!file.size || file.size > 2 * 1024 * 1024) throw new Error('请选择非空且不超过 2 MiB 的文件。');
  if (!/\.(csv|txt|xlsx)$/i.test(file.name)) throw new Error('请选择 CSV、TXT 或无宏 XLSX 文件。');
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.byteLength !== file.size) throw new Error('文件读取不完整，请重新选择。');
  let binary = '';
  for (let i = 0; i < bytes.length; i += 16384) binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return { name: file.name, contentBase64: btoa(binary), encoding: 'auto' };
}

export default function FinanceImportPanel(props: Props) {
  const household = useHousehold();
  if (!household.user || household.user.role !== 'member') return <EmptyState title="请使用成员账户导入" description="账单与订单仅本人可见。" />;
  return <ImportWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} user={household.user} />;
}
function ImportWorkspace({ onClose, onImported, identityKey, user }: Props & { identityKey: string; user: NonNullable<PhotoSession['user']> }) {
  const household = useHousehold(), latest = useRef(household), theme = useTheme(), { height } = useWindowDimensions(); latest.current = household;
  const mounted = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), user, identityKey));
  const generation = useRef(0), draftEpoch = useRef(0), writing = useRef(false), reading = useRef(false);
  const picker = useRef<AbortController | null>(null), pendingRef = useRef<Pending | null>(null);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [source, setSource] = useState<ImportSource>('generic'), [kind, setKind] = useState<ImportKind>('payments');
  const [file, setFile] = useState<ImportFile | null>(null), [sheets, setSheets] = useState<string[]>([]), [sheet, setSheet] = useState('');
  const [column, setColumn] = useState<number | undefined>(), [preview, setPreview] = useState<ImportPreview | null>(null);
  const previewRef = useRef<{ value: ImportPreview; payload: ImportPayload } | null>(null);
  const [pending, setPendingState] = useState<Pending | null>(null), [receipt, setReceipt] = useState<FinanceImportReceipt | null>(null);
  const [notFound, setNotFound] = useState(false), [menu, setMenu] = useState(''), [page, setPage] = useState(0), [errorPage, setErrorPage] = useState(0), [leaving, setLeaving] = useState(false);
  const current = () => mounted.current && focused.current && active.current && !denied.current && appActive.current
    && latest.current.identityKey === identityKey && latest.current.online && front() && connected();
  const setPending = (value: Pending | null) => { pendingRef.current = value; setPendingState(value); };
  function invalidatePreview() { ++draftEpoch.current; previewRef.current = null; setPreview(null); setPage(0); setErrorPage(0); setError(''); }
  function resetAll() { invalidatePreview(); setFile(null); setSheets([]); setSheet(''); setColumn(undefined); setPending(null); setReceipt(null); setNotFound(false); }
  function conceal(clear = false) {
    active.current = false; ++generation.current; fence.current.invalidate(); setVisible(false); setBusy(false); setMenu(''); setLeaving(false);
    if (clear) { resetAll(); picker.current?.abort(); }
  }
  function failed(error: unknown) {
    if (!mounted.current || latest.current.identityKey !== identityKey) return;
    if (error instanceof PhotoReadDiscarded && error.message !== 'identity') return;
    if (error instanceof PhotoReadDiscarded || error instanceof ApiError && [401, 403].includes(error.status)) {
      conceal(true); denied.current = true; setError('登录身份已变化，请重新打开导入。'); void latest.current.refresh(); return;
    }
    if (current()) setError(message(error));
  }
  async function guarded<T>(load: () => Promise<T>, ticket = generation.current) {
    return fence.current.read(load, () => current() && ticket === generation.current);
  }
  async function resume() {
    if (!mounted.current || !focused.current || !appActive.current || denied.current || !front() || !connected() || !latest.current.online) return;
    const ticket = ++generation.current; active.current = true;
    try { await guarded(async () => true, ticket); if (current() && ticket === generation.current) { setBusy(reading.current || writing.current); setVisible(true); } }
    catch (error) { failed(error); }
  }
  useEffect(() => {
    mounted.current = true;
    const change = () => { if (!front() || !connected()) conceal(); else void resume(); };
    const sub = AppState.addEventListener('change', value => { appActive.current = value === 'active'; if (appActive.current) void resume(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', change);
    if (typeof window !== 'undefined') { window.addEventListener('offline', change); window.addEventListener('online', change); }
    return () => { mounted.current = false; focused.current = false; active.current = false; ++generation.current; ++draftEpoch.current; fence.current.invalidate(); picker.current?.abort(); sub.remove();
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', change);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', change); window.removeEventListener('online', change); } };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; void resume(); return () => { focused.current = false; conceal(); }; }, [identityKey]));
  useEffect(() => { if (!household.online) conceal(); else if (focused.current) void resume(); }, [household.online]);

  async function choose() {
    if (!current() || writing.current || reading.current || pendingRef.current) return;
    picker.current?.abort(); picker.current = new AbortController();
    let epoch = ++draftEpoch.current, startedReading = false;
    try {
      const selected = await browserFile(picker.current.signal); if (!selected || !mounted.current || epoch !== draftEpoch.current) return;
      if (writing.current || reading.current || pendingRef.current) return;
      invalidatePreview(); epoch = draftEpoch.current;
      setFile(null); setSheets([]); setSheet(''); setColumn(undefined); setReceipt(null); setNotFound(false);
      reading.current = true; startedReading = true; setBusy(true);
      const next = await fileData(selected); if (!current() || epoch !== draftEpoch.current) return;
      await guarded(async () => true); if (!current() || epoch !== draftEpoch.current) return;
      setFile(next);
    } catch (error) { if (epoch === draftEpoch.current) failed(error); }
    finally { if (startedReading) { reading.current = false; if (current()) setBusy(writing.current); } }
  }
  async function inspect() {
    if (!file || !current() || reading.current || writing.current || pendingRef.current) return;
    const payload = importPayload(source, kind, { ...file, ...(sheet ? { sheet } : {}) }, column, /\.xlsx$/i.test(file.name) && !sheet);
    invalidatePreview(); const epoch = draftEpoch.current; const ticket = generation.current;
    reading.current = true; setBusy(true);
    try {
      const result = readImportPreview(await guarded(() => latest.current.mutate<unknown>('/finance-hub/imports/preview', 'POST', payload), ticket));
      if (!current() || epoch !== draftEpoch.current) return;
      previewRef.current = { value: result, payload }; setPreview(result);
      if (result.requiresSheetSelection) setSheets(result.fileInfo?.sheets || []);
      if (result.amountSelection?.selectedIndex !== null && result.amountSelection?.selectedIndex !== undefined) setColumn(result.amountSelection.selectedIndex);
    } catch (error) { if (epoch === draftEpoch.current) failed(error); }
    finally { reading.current = false; if (current()) setBusy(writing.current); }
  }
  async function send(intent: Pending) {
    if (!current() || writing.current || reading.current) return;
    const ticket = generation.current; writing.current = true; setBusy(true); setError(''); setNotFound(false);
    try {
      const result = readImportReceipt(await guarded(() => latest.current.mutate<unknown>('/finance-hub/imports/confirm', 'POST', intent.payload), ticket), intent.requestId);
      if (!current()) return;
      setReceipt(result); setPending(null); previewRef.current = null; setPreview(null); setFile(null); setSheets([]); setSheet(''); setColumn(undefined);
    } catch (error) {
      if (importRejectionIsDefinite(error instanceof ApiError ? error.status : undefined, intent.uncertain) && current()) { setPending(null); invalidatePreview(); failed(error); }
      else { intent.uncertain = true; failed(error); if (current() && !(error instanceof PhotoReadDiscarded)) setError('保存结果尚未确认，请先核对保存结果。'); }
    } finally { writing.current = false; if (current()) setBusy(reading.current); }
  }
  function confirm() {
    if (!current() || pendingRef.current || writing.current || reading.current || !previewRef.current) return;
    try {
      const { value, payload } = previewRef.current, requestId = newImportRequestId();
      const intent = { requestId, payload: confirmImportPayload(payload, value, requestId), uncertain: false };
      setPending(intent); void send(intent);
    } catch (error) { failed(error); }
  }
  async function lookup() {
    const intent = pendingRef.current;
    if (!intent || !current() || reading.current || writing.current) return;
    const ticket = generation.current; reading.current = true; setBusy(true); setError(''); setNotFound(false);
    try {
      const result = readImportReceipt(await guarded(() => request<unknown>('/finance-hub/imports/results/' + intent.requestId), ticket), intent.requestId);
      if (!current() || pendingRef.current !== intent) return;
      setReceipt(result); setPending(null); previewRef.current = null; setPreview(null); setFile(null); setSheets([]); setSheet(''); setColumn(undefined);
    } catch (error) {
      if (current() && error instanceof ApiError && error.status === 404 && error.code === 'import_result_not_found') { setNotFound(true); setError('暂未找到本次保存回执，原请求也可能仍在处理。可以继续核对，或使用同一请求重试。'); }
      else failed(error);
    } finally { reading.current = false; if (current()) setBusy(writing.current); }
  }
  async function showResults() {
    if (!receipt || !current() || writing.current || reading.current) return;
    try { await guarded(async () => true); if (current()) onImported(receipt); } catch (error) { failed(error); }
  }
  async function template() {
    if (!current() || writing.current || reading.current) return;
    try {
      const value = await guarded(() => request<{ filename: string; csv: string }>('/finance-hub/template?kind=' + kind));
      if (!current()) return;
      if (Platform.OS !== 'web' || typeof document === 'undefined') throw new Error('请在浏览器中下载通用模板。');
      if (value.filename !== `household-${kind}-template.csv` || typeof value.csv !== 'string' || value.csv.length > 10000) throw new Error('模板无法核对，请稍后重试。');
      const url = URL.createObjectURL(new Blob(['\ufeff', value.csv], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a'); link.href = url; link.download = value.filename; document.body.appendChild(link);
      try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (error) { failed(error); }
  }
  const disabled = busy || !!pending || !!receipt;
  const dropdown = (id: string, label: string, items: { key: string; title: string }[], change: (value: string) => void) =>
    <Menu visible={menu === id} onDismiss={() => setMenu('')} anchor={<Button mode="outlined" disabled={disabled} onPress={() => setMenu(id)} contentStyle={styles.buttonContent}>{label}</Button>}>
      <ScrollView style={{ maxHeight: Math.min(340, height * .5), maxWidth: 280 }}>{items.map(item => <TouchableRipple key={item.key} accessibilityRole="menuitem" accessibilityLabel={item.title} onPress={() => { setMenu(''); change(item.key); }} style={{ paddingHorizontal: 16, paddingVertical: 12, minHeight: 44 }}><Text>{item.title}</Text></TouchableRipple>)}</ScrollView>
    </Menu>;
  const back = () => { if (file || pendingRef.current) setLeaving(true); else onClose(); };
  if (!visible) return <SectionCard title="导入账单"><Text>{error || (!connected() || !household.online ? '连接恢复后会重新核对身份，文件内容暂不显示。' : '正在核对登录状态…')}</Text>
    <Button onPress={() => void resume()}>重新核对身份</Button><Button onPress={onClose}>返回账本</Button></SectionCard>;
  return <View style={styles.page} testID="finance-import-panel">
    <PageHeader title="导入账单" description="先核对，再保存。文件仅导入到本人的账本。" action={<Button onPress={back} disabled={busy}>返回账本</Button>} />
    {!!error && <SectionCard title="需要核对"><Text accessibilityLiveRegion="polite">{error}</Text></SectionCard>}
    {receipt ? <SectionCard title="导入结果"><View testID="finance-import-receipt" style={styles.page}>
      <Text variant="headlineSmall">{receipt.imported ? `新增 ${receipt.imported} 条` : '已核对，未新增记录'}</Text><Text>重复 {receipt.duplicates} 条 · 冲突 {receipt.conflicts} 条（保留原记录）</Text>
      <Text>已保存到本人账本，公共余额未改变。</Text><Text>原请求的保存结果已经确认；后来修改或删除的记录不会因核对回执而恢复。</Text>
      <Text variant="bodySmall">保存时间：{receipt.confirmedAt}</Text>
      {receipt.resultMonths.map(row => <Text key={row.month}>{row.month} · {row.recordCount} 条确认时保留的记录</Text>)}
      <Button mode="contained" onPress={() => void showResults()}>查看已导入账本</Button>
    </View></SectionCard> : pending ? <SectionCard title="核对本次保存"><Text>请先查看持久化回执。重复核对只读取结果，不会再次入账。</Text>
      <Button mode="contained" loading={busy} disabled={busy} onPress={() => void lookup()}>核对保存结果</Button>
      {notFound && <Button mode="outlined" disabled={busy} onPress={() => void send(pending)}>使用原请求重试</Button>}
    </SectionCard> : <>
      <SectionCard title="选择文件"><View style={styles.page}>
        <View style={styles.controls}>{dropdown('source', '文件来源：' + sources[source], Object.entries(sources).map(([key, title]) => ({ key, title })), value => { invalidatePreview(); setSource(value as ImportSource); setSheets([]); setSheet(''); setColumn(undefined); })}</View>
        <SegmentedButtons value={kind} onValueChange={value => { invalidatePreview(); setKind(value as ImportKind); setSheets([]); setSheet(''); setColumn(undefined); }} buttons={[{ value: 'payments', label: '支付账单', disabled }, { value: 'orders', label: '订单记录', disabled }]} />
        <Button mode="outlined" icon="file-upload-outline" accessibilityLabel="选择账单文件" disabled={disabled} onPress={() => void choose()}>选择账单文件</Button>
        <Text>{file?.name || '支持 CSV、TXT、无宏 XLSX，最大 2 MiB。'}</Text>
        <Button disabled={disabled} onPress={() => void template()}>下载通用模板</Button>
        {file && !/\.xlsx$/i.test(file.name) && dropdown('encoding', '编码：' + ({ auto: '自动识别', 'utf-8': 'UTF-8', gb18030: 'GB18030' })[file.encoding], [{ key: 'auto', title: '自动识别' }, { key: 'utf-8', title: 'UTF-8' }, { key: 'gb18030', title: 'GB18030' }], value => { invalidatePreview(); setFile({ ...file, encoding: value as ImportFile['encoding'] }); setColumn(undefined); })}
        {sheets.length > 0 && <>{dropdown('sheet', sheet || '选择账单工作表', sheets.map(name => ({ key: name, title: name })), value => { invalidatePreview(); setSheet(value); setColumn(undefined); })}<Text variant="bodySmall">工作表名称不代表内容已校验；选择后读取账单。</Text></>}
        {preview?.amountSelection && preview.amountSelection.columns.length > 1 && dropdown('amount', column === undefined ? '选择入账金额列' : (() => { const c = preview.amountSelection!.columns.find(c => c.index === column); return c ? c.columnLabel + ' 列 · ' + c.label : '选择入账金额列'; })(), preview.amountSelection.columns.map(c => ({ key: String(c.index), title: c.columnLabel + ' 列 · ' + c.label })), value => { ++draftEpoch.current; previewRef.current = null; setColumn(Number(value)); setPreview(old => old ? { ...old, previewToken: null, rows: [], newCount: 0, duplicateCount: 0, conflictCount: 0, requiresAmountSelection: true } : null); setError(''); setPage(0); })}
        <Button mode="contained" disabled={!file || disabled || sheets.length > 0 && !sheet || !!preview?.requiresAmountSelection && column === undefined} loading={busy} onPress={() => void inspect()}>{sheets.length > 0 && !preview?.amountSelection ? '读取所选工作表' : preview?.requiresAmountSelection ? '按所选金额预览' : '预览文件'}</Button>
      </View></SectionCard>
      {preview && !preview.requiresSheetSelection && !preview.requiresAmountSelection && <SectionCard title="核对预览"><View style={styles.page}>
        <Text>新增 {preview.newCount} 条 · 重复 {preview.duplicateCount} 条 · 冲突 {preview.conflictCount} 条 · 错误 {preview.errorCount} 条</Text>
        <Text variant="bodySmall">重复项不再次入账，冲突项保留原值；订单与付款分别核对。</Text>
        {!!preview.fileInfo && <Text variant="bodySmall">{[preview.fileInfo.format, preview.fileInfo.encoding, preview.fileInfo.sheet].filter(Boolean).join(' · ')}</Text>}
        {preview.warnings.map((warning, index) => <Text key={index} style={{ color: theme.colors.onSurfaceVariant }}>{warning}</Text>)}
        {preview.errors.slice(errorPage * 24, errorPage * 24 + 24).map((row, index) => <Text key={index}>第 {row.line} 行：{row.message}</Text>)}
        {preview.errors.length > 24 && <View style={styles.controls}><Button disabled={errorPage === 0} onPress={() => setErrorPage(p => p - 1)}>上一页错误</Button><Text>错误 {errorPage + 1} / {Math.ceil(preview.errors.length / 24)} 页</Text><Button disabled={(errorPage + 1) * 24 >= preview.errors.length} onPress={() => setErrorPage(p => p + 1)}>下一页错误</Button></View>}
        {preview.errorCount > 0 && <Text>请修正文件后重新选择并预览，本次不会部分入账。</Text>}
        {preview.rows.slice(page * 24, page * 24 + 24).map((row, index) => <View key={page * 24 + index} testID={'finance-import-row-' + row.line} style={styles.row}>
          <Text variant="titleMedium">{row.title}</Text><Text>{row.date} · {flows[row.flow] || '待核对'} · {importSourceLabel(row.sourceLocation)}</Text>
          <Text>{importAmount(row.amountCents, row.currency)}{row.conflict ? ' · 冲突，保留原值' : row.duplicate ? ' · 已有记录' : ''}</Text>
          {!!row.externalId && <Text variant="bodySmall">原编号：{row.externalId}</Text>}
          {row.orderItems?.map((item, key) => <Text key={key} variant="bodySmall">{[item.title, item.variant, item.quantityText && '数量：' + item.quantityText, item.listedAmountText && '原标价：' + item.listedAmountText].filter(Boolean).join(' · ')}</Text>)}<Divider />
        </View>)}
        {preview.rows.length > 24 && <View style={styles.controls}><Button disabled={page === 0} onPress={() => setPage(p => p - 1)}>上一页</Button><Text>{page + 1} / {Math.ceil(preview.rows.length / 24)}</Text><Button disabled={(page + 1) * 24 >= preview.rows.length} onPress={() => setPage(p => p + 1)}>下一页</Button></View>}
        {!preview.rows.length && !preview.errorCount && <Text>这份文件没有可导入记录，请核对文件和工作表。</Text>}
        <Button mode="contained" disabled={!canConfirmImport(preview) || disabled} onPress={confirm}>确认导入 · 仅本人</Button>
      </View></SectionCard>}
    </>}
    {busy && <ActivityIndicator accessibilityLabel="正在处理文件" />}
    <Portal><Dialog visible={leaving} onDismiss={() => setLeaving(false)} style={{ maxWidth: 560, width: '92%', alignSelf: 'center', borderRadius: 24, backgroundColor: theme.colors.surface }}>
      <Dialog.Title>返回账本？</Dialog.Title><Dialog.Content><Text>{pending ? '保存可能已经完成。离开不会撤销服务器上的保存；回到账本后请核对记录。本页文件和未确认结果会清除。' : '尚未确认的文件不会入账，返回后需要重新选择文件。'}</Text></Dialog.Content>
      <Dialog.Actions><Button onPress={() => setLeaving(false)}>继续核对</Button><Button onPress={() => { resetAll(); onClose(); }}>返回账本</Button></Dialog.Actions>
    </Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 18 }, controls: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10 }, row: { gap: 6, minWidth: 0 }, buttonContent: { minHeight: 44 } });
