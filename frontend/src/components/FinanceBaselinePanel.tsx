import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Divider, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { BaselineDiscarded, BaselineError, BaselineFence, baselinePage, baselineRequest, formatBaselineMoney, formatBaselineTime, readFinanceBaseline,
  type BaselineQuality, type BaselineRow, type BaselineSession, type FinanceBaseline } from '../lib/financeBaseline';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';

type Props = { onBack: () => void };
type Tab = 'overview' | 'assets' | 'liabilities' | 'income' | 'spending' | 'source';
const tabs: [Tab, string][] = [['overview', '概览'], ['assets', '资产'], ['liabilities', '负债'], ['income', '收入'], ['spending', '消费观察'], ['source', '来源说明']];
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const dayText = (value: string | null) => value || '日期待核对';
const labels: Record<string, string> = { dated_record: '有日期的记录', confirmed: '已确认', unknown: '待核对', cash: '现金与存款', liability: '负债', historical_income: '历史收入',
  historical_income_not_asset: '历史收入，不计入资产', synthetic_record_date: '来源记录日期' };
const describe = (value: string) => labels[value] || value;

export default function FinanceBaselinePanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看本人来源报告" action={<Button contentStyle={styles.touch} onPress={props.onBack}>返回财务</Button>} />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} owner={household.user.id} />;
}
function Workspace(props: Props & { identityKey: string; owner: string }) {
  const household = useHousehold(), density = useDisplayDensity(), theme = useTheme();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [data, setData] = useState<FinanceBaseline | null>(null), [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('overview'), [query, setQuery] = useState(''), [page, setPage] = useState(0);
  const alive = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false), epoch = useRef(0), working = useRef(false), flight = useRef<AbortController | null>(null);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), pageHidden = useRef(false), fence = useRef(new BaselineFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && !pageHidden.current && foreground.current && epoch.current === ticket
    && connected() && latest.current.household.online && latest.current.household.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  function conceal() {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null; working.current = false;
    setBusy(false); setVisible(false); setData(null); setQuery(''); setPage(0); setError('');
  }
  async function load() {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; working.current = true;
    setBusy(true); setVisible(false); setData(null); setQuery(''); setPage(0); setError('');
    try {
      const result = await fence.current.run(async () => await baselineRequest('/me', controller.signal) as BaselineSession,
        async () => readFinanceBaseline(await baselineRequest('/finance-baseline/private', controller.signal), props.owner), () => current(ticket));
      if (current(ticket)) { setData(result); setVisible(true); }
    } catch (caught) {
      if (!current(ticket)) return;
      if (caught instanceof BaselineDiscarded) {
        if (caught.message === 'identity') { denied.current = true; conceal(); setError('身份已变化，来源报告已清除。请重新进入。'); void latest.current.household.refresh(); }
      } else if (caught instanceof BaselineError && [401, 403].includes(caught.status)) {
        conceal(); setError('身份或权限暂时无法核对，来源报告已清除。'); void latest.current.household.refresh();
      } else setError(caught instanceof BaselineError ? caught.message : '暂时无法读取来源报告，请重试。');
    } finally { if (flight.current === controller) flight.current = null; if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function enter() {
    if (active.current || denied.current || !alive.current || !focused.current || !foreground.current || pageHidden.current || !connected() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void load();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); };
    const offline = () => conceal(), online = () => enter(), hide = () => { pageHidden.current = true; conceal(); };
    const show = (event: PageTransitionEvent) => { if (event.persisted || pageHidden.current) { pageHidden.current = false; conceal(); enter(); } };
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  const back = () => { conceal(); latest.current.props.onBack(); };
  const refresh = () => { if (active.current) void load(); else enter(); };
  const showData = visible && current();
  const rows = data && (tab === 'assets' || tab === 'liabilities' || tab === 'income') ? baselinePage(data[tab], query, page, item => [item.label, item.category, item.source, item.currency, item.asOf].join(' ')) : null;
  const months = tab === 'spending' && data?.spending ? baselinePage(data.spending.monthly, query, page, item => item.period + ' ' + (item.currency || '')) : null;
  const files = tab === 'source' && data?.sourceBridge ? baselinePage(data.sourceBridge.files, query, page, item => item.path) : null;
  return <View testID="finance-baseline-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="我的资产与来源报告" description="查看已经录入的本人资料、日期和覆盖范围。这里的金额不代表实时余额。"
      action={<Button contentStyle={styles.touch} accessibilityLabel="返回财务" onPress={back}>返回财务</Button>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对本人来源报告" />}
    {!showData ? <EmptyState title={connected() && household.online ? '正在核对本人资料' : '离线时隐藏私密资料'} description="每次返回前台都会重新核对身份和当前记录，不保留离线副本。"
      action={<Button contentStyle={styles.touch} disabled={busy || !connected() || !household.online || denied.current} onPress={refresh}>重新读取来源报告</Button>} />
      : data === null ? <EmptyState title="还没有本人资产来源记录" description="当前账户尚未录入来源报告。此页只读，不会自动访问邮箱或金融机构。"
        action={<Button contentStyle={styles.touch} onPress={refresh}>重新读取来源报告</Button>} />
      : <View testID="finance-baseline-content" style={{ gap: density.screenGap }}>
        <View style={styles.actions}>{tabs.map(([id, title]) => <Button key={id} contentStyle={styles.touch} mode={tab === id ? 'contained' : 'outlined'} accessibilityLabel={title + '分类'} accessibilityState={{ selected: tab === id }}
          onPress={() => { setTab(id); setQuery(''); setPage(0); }}>{title}</Button>)}</View>
        <Text>资产资料截至 {data.asOf} · 余额记录日期 {data.balanceAsOfStart} 至 {data.balanceAsOfEnd}</Text>
        {tab === 'overview' && <>
          <SectionCard title="已录入的人民币记录"><View style={{ gap: density.sectionGap }}>
            <Metric label="已记录资产小计" value={formatBaselineMoney(data.totals.recordedAssetCents, 'CNY')} />
            <Metric label="已记录负债小计" value={formatBaselineMoney(data.totals.recordedLiabilityCents, 'CNY')} />
            <Divider />
            {data.totals.complete ? <><Metric label="来源标记的完整资产" value={formatBaselineMoney(data.totals.assetCents, 'CNY')} /><Metric label="来源标记的完整负债" value={formatBaselineMoney(data.totals.liabilityCents, 'CNY')} /><Metric label="来源标记的净资产" value={formatBaselineMoney(data.totals.netCents, 'CNY')} /></>
              : <Text>整体资产、负债和净资产仍待核对。以上小计只包含明确计入的人民币记录，不能当作全部资产。</Text>}
          </View></SectionCard>
          <SectionCard title="先看日期，再看金额"><View style={{ gap: density.sectionGap }}>
            <Text>录入时间：{formatBaselineTime(data.importedAt)}</Text><Text>外币和未核对金额分别保留；不换算汇率，不与持仓、交易账本或家庭荷包重复相加。</Text>
            <Text>收入页是来源中的历史记录，不自动推断当前工资。消费观察有独立的报告日期和覆盖窗口。</Text>
          </View></SectionCard>
        </>}
        {tab !== 'overview' && <TextInput mode="outlined" label={tab === 'source' ? '搜索来源文件' : tab === 'spending' ? '搜索月份或币种' : '搜索本分类记录'} testID="baseline-search" value={query} maxLength={200}
          onChangeText={value => { setQuery(value); setPage(0); }} style={{ backgroundColor: theme.colors.surface }} />}
        {rows && <>
          {tab === 'income' && <Text>这些是来源里的收入记录，不计入资产小计，也不推断为当前月收入。</Text>}
          {rows.rows.map((item, index) => <RecordCard key={rows.page + ':' + index} row={item} income={tab === 'income'} />)}
          <Pages value={rows} onPage={setPage} empty="没有匹配的记录" />
        </>}
        {tab === 'spending' && <>
          {!data.spending ? <EmptyState title="没有结构化消费观察" description="未提供的消费金额和覆盖范围保持未知，不填成零。" /> : <>
            <SectionCard title="消费报告覆盖"><View style={{ gap: density.sectionGap }}>
              <Text>报告生成：{formatBaselineTime(data.spending.generatedAt)}</Text><Text>请求窗口：{dayText(data.spending.requestedStart)} 至 {dayText(data.spending.requestedEnd)}</Text>
              <Text>月份只表示报告中存在的观察。窗口首尾可能不足整月；没有出现的月份不等于没有消费。</Text>
              <Quality value={data.spending.quality} />{!!data.spending.note && <Text>{data.spending.note}</Text>}
            </View></SectionCard>
            {data.spendingObservation && <SectionCard title="当前采用的消费观察"><View style={{ gap: density.sectionGap }}>
              <Text>{data.spendingObservation.origin === 'spending_observation' ? '使用后来录入的独立消费报告。' : '使用资产来源记录中的消费报告。'}</Text>
              <Text>独立观察录入时间：{formatBaselineTime(data.spendingObservation.acceptedAt)}</Text><Text>消费报告更新没有改写资产记录。</Text>
              {data.spendingObservation.warnings.map((warning, index) => <Text key={index}>{warning}</Text>)}
            </View></SectionCard>}
            {months?.rows.map((month, index) => <SectionCard key={months.page + ':' + index} title={month.period + ' · ' + (month.currency || '币种待核对')}><View style={{ gap: density.sectionGap }}>
              <Metric label="支出" value={formatBaselineMoney(month.grossSpendCents, month.currency)} /><Metric label="退款" value={formatBaselineMoney(month.refundCents, month.currency)} />
              <Metric label="净支出" value={formatBaselineMoney(month.netSpendCents, month.currency)} /><Text>记录笔数：{month.transactionCount === null ? '待核对' : month.transactionCount}</Text>
            </View></SectionCard>)}
            {months && <Pages value={months} onPage={setPage} empty="没有匹配的消费月份" />}
          </>}
        </>}
        {tab === 'source' && <>
          {!data.sourceBridge ? <EmptyState title="旧记录未提供结构化来源清单" description="各条记录的来源文字仍可在资产、负债和收入分类中查看。" /> : <>
            <SectionCard title="资产来源报告"><View style={{ gap: density.sectionGap }}>
              <Text>生成时间：{formatBaselineTime(data.sourceBridge.generatedAt)}</Text><Text>来源请求窗口：{dayText(data.sourceBridge.requestedStart)} 至 {dayText(data.sourceBridge.requestedEnd)}</Text>
              <Quality value={data.sourceBridge.quality} /><Text>下列路径仅是来源说明；页面不会打开或执行这些文件。</Text>
            </View></SectionCard>
            {files?.rows.map((file, index) => <SectionCard key={files.page + ':' + index} title="来源文件"><View style={{ gap: density.sectionGap }}>
              <Text selectable style={styles.wrap}>{file.path}</Text><Text>{file.bytes === null ? '文件大小待核对' : `${file.bytes.toLocaleString('zh-CN')} 字节`}</Text>
            </View></SectionCard>)}
            {files && <Pages value={files} onPage={setPage} empty="没有匹配的来源文件" />}
          </>}
        </>}
        <Button contentStyle={styles.touch} mode="outlined" disabled={busy} onPress={refresh}>重新读取来源报告</Button>
      </View>}
  </View>;
}
function Metric({ label, value }: { label: string; value: string }) { return <View style={styles.metric}><Text>{label}</Text><Text variant="titleLarge" style={styles.wrap}>{value}</Text></View>; }
function RecordCard({ row, income }: { row: BaselineRow; income: boolean }) {
  const density = useDisplayDensity();
  return <SectionCard title={row.label}><View style={{ gap: density.sectionGap }}>
    <Metric label={describe(row.category)} value={formatBaselineMoney(row.amountCents, row.currency)} />
    <Text>记录日期：{row.asOf} · 状态：{describe(row.status)}</Text>
    {!income && <Text>{row.includedInRecordedSubtotal ? '已计入人民币小计' : '未计入人民币小计'}</Text>}
    {!row.includedInRecordedSubtotal && <Text>排除依据：{row.exclusionReason ? describe(row.exclusionReason) : income ? '收入单列，不作为资产小计' : '来源未提供，需核对'}</Text>}
    {!!row.dateBasis && <Text>日期依据：{describe(row.dateBasis)}</Text>}{!!row.period && <Text>记录期间：{row.period}</Text>}
    <Text selectable style={styles.wrap}>来源：{row.source}</Text>{!!row.note && <Text>{row.note}</Text>}
  </View></SectionCard>;
}
function Quality({ value }: { value: BaselineQuality | null }) {
  if (!value) return <Text>来源没有提供覆盖质量说明。</Text>;
  return <View style={styles.metric}><Text>已知覆盖缺口：{value.knownGapsCount === null ? '待核对' : value.knownGapsCount} · 无法读取的账单：{value.unreadableStatementsCount === null ? '待核对' : value.unreadableStatementsCount}</Text>
    <Text>渠道记录：{value.channelOnlyAdded === null ? '是否补充待核对' : value.channelOnlyAdded ? '已补充' : '未补充'} · 订单记录：{value.orderOnlyAdded === null ? '是否补充待核对' : value.orderOnlyAdded ? '已补充' : '未补充'}</Text>
    <Text>这些是来源报告的覆盖说明，零个已知缺口不代表资料一定完整。</Text></View>;
}
function Pages({ value, onPage, empty }: { value: { page: number; pages: number; count: number }; onPage: (page: number) => void; empty: string }) {
  if (!value.count) return <EmptyState title={empty} />;
  return <View style={styles.actions}><Button contentStyle={styles.touch} disabled={value.page === 0} accessibilityLabel="上一页记录" onPress={() => onPage(value.page - 1)}>上一页</Button>
    <Text style={styles.page}>第 {value.page + 1} / {value.pages} 页 · 共 {value.count} 条</Text>
    <Button contentStyle={styles.touch} disabled={value.page + 1 >= value.pages} accessibilityLabel="下一页记录" onPress={() => onPage(value.page + 1)}>下一页</Button></View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }, metric: { gap: 6 }, wrap: { flexShrink: 1, minWidth: 0 }, page: { paddingVertical: 10 } });
