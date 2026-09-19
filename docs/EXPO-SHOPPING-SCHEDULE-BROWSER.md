# 采购日期与优先级：本地浏览器验收

`tests/browser_expo_shopping_schedule_check.py` 是下一批采购功能的独立验收脚本。目前仅准备脚本与静态检查，没有运行浏览器，也没有接入当前 task-publish 发布构建。作者基线是已审 UI `bc4c292a91c59a42329a6d967ce19beb88334b33`；运行前需要审查通过的采购 API、UI、AI 组合提交和对应的新 Expo export。准备脚本时核对的 API 合同为 `7fca1ff886e385d3d6e3a07ed9e786b41b52a3a8`，AI 候选为 `8b12dac9370cbe86464f8c27955c6d4aa3b76834`（实际 AI head 以整合人提供的冻结组合为准）。

## 四条流程

1. **普通采购创建、编辑、清空。** 在真实采购弹窗填写截止日、高优先级和预算；保存、刷新、改为另一天与低优先级，再显式清空日期、选择普通。读取原实体和 SQLite，重启临时应用后核对同一采购、空日期、普通优先级与金额、图片引用等原字段保持。
2. **本地助理草案到采购。** 输入明确旅行字段及 `采购：转换插头 | 负责人：我 | 数量：2件 | 预算：100元 | 截止：出发前3天 | 优先级：高`。调用真实 local brief，核对来源、负责人、相对日期、优先级，并确认尚未写入。用户在草案改变相对天数与优先级，交接旅行编辑后再次编辑绝对日期，再实际预览、明确确认。采购实体必须保持同一 workflowKey、负责人、金额和最终日期/优先级，且出现在采购清单。没有替换模型或业务响应，也不创建云同步队列。
3. **明确选择采购改期。** 通过真实 API 准备有日期未完成、已完成、无日期和保留原日期四项采购；进入旅行「调整日期」。默认未选，已完成和无日期不可选；只选一项。核对预览仅移动该项，确认后原实体及优先级、金额、图片引用等保持，其他采购完全不变。重启临时应用后再次读取。
4. **真实离线保留草稿。** 编辑采购后让 Edge context 进入离线，点击保存。核对失败提示、日期/低优先级仍在、保存被锁定、没有成功提示，数据库保持原样。恢复网络不自动重发；先核对实际清单为空，再由用户明确关闭、重新填写及保存，只产生一次采购。

每条流程使用自己的临时 Flask、SQLite、HTTPS 服务与 Edge context。复用现有 finance/brief/trip-items harness 的本地基础设施、导航及证据工具，但不调用会替换模型输出的作者构造器。服务器模型函数被设为失败哨兵，`ASSISTANT_PROVIDER=local`；Python socket 仅允许 loopback，浏览器仅允许当前临时 origin。未使用真实账号、真实云、模型服务、生产数据库或实体电视。

## 冻结运行

以下只是一条命令模板，须由整合人提供真实路径和 SHA 后执行。不要指向作者 worktree、旧 export 或生产目录。

```powershell
& $python -B -X utf8 "$combined/tests/browser_expo_shopping_schedule_check.py" `
  --source-root $combined `
  --expected-head $combinedHead `
  --bundle $newExport `
  --expected-build-evidence $buildEvidenceSha256
```

脚本要求干净且精确匹配的源 head/tree，验证完整已跟踪源码、实际导入模块路径及哈希、构建输入哈希和整个 export 哈希。可选 `--build-source-head` 仅允许其为当前源的祖先且完整 frontend tree 相同；该选项适用于纯验收脚本/文档随后合入，不允许跳过构建输入比对。运行结束再次核对所有源码、导入文件和 export 未变化。

## 证据与判定

结果写入组合 worktree 的忽略目录 `test-results/expo-shopping-schedule-<UTC>/result.json`。四个流程分别保存真实 HTTP 请求体、响应原始字节及哈希、数据库前后快照。每条流程保留 390/1280 宽截图，共八张；实际测量 `document.body.scrollWidth`、body clientWidth、documentElement scrollWidth、视口以及可见交互控件横向边界。截图和指标不代替人工视觉审查或屏幕阅读器验证。

每条流程异常独立记录并继续其他流程；保存失败截图、ARIA 快照和 traceback，不将超时或跳过称为通过。临时请求线程需关闭、服务需停止、临时数据库需清理；这些条件、四条全部通过、无页面脚本错误、无外连/模型尝试及源码/构建冻结复核共同决定总结果。

这四条是采购增量的本地端到端验证，不重复整个日程、权限、库存结算或云同步套件。local 模式验收不证明真实模型质量；未覆盖真实支付、下单、配送、外部账号、所有滚动位置、电视或所有辅助技术。
