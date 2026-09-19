# 本人站内提醒的浏览器演练

工具为 `scripts/check_expo_task_reminders_browser.py`，使用真实临时 Flask、SQLite、HTTPS 和本机 Edge，覆盖[提醒 API](TASK-REMINDERS.md)与已审前端的组合行为。当前提交只是演练工具候选；helper 检查和静态定位器检查不代表下列业务流程已经通过，也不表示生产发布。

## 三条可独立执行的流程

| `--case` | 实际操作和核对 | 预期截图 |
| --- | --- | --- |
| `read_snooze_edit` | 创建 41 条本地到期待办及一个合成共享云镜像；390px 核对超过 100 字且包含 emoji 的完整云标题，云事项打开只提示原应用。切换全部／第 2 页，在提醒投影后真实修改原任务备注，再从提醒打开原编辑器；保存必须使用最新原 ID、revision，保留备注与筛选页。真实已读后暂缓一小时，提醒版本变化且任务仍未完成、任务记录未被提醒操作修改。 | 长云标题 390、编辑返回与暂缓 1280，共 2 张 |
| `committed_response_lost` | 分别在 390／1280 将真实已提交的暂缓 POST 200 响应改为 abort／503。保存浏览器原最小 intent，真实 reload 页面；重新进入提醒只查询原 requestId 回执。核对同一回执、一次 POST、一条操作记录、暂缓不延长、任务未改变。 | 两种故障各恢复前后，共 4 张 |
| `committed_identity_read_failed` | 分别在 390／1280，真实已读 POST 返回 200 后，将后续真实 `/me` 200 改为 429／404。原 intent 必须保留，不当成明确拒绝。故障期间刷新不得写业务；解除故障后只查原回执，等待同一页面的真实列表和后置身份检查完成、刷新及返回恢复可用，再截取最终空状态；持久化记录及 POST 均不重复。 | 两种故障各恢复前后，共 4 张 |

每条 case 有独立临时家庭数据库、HTTPS listener 和浏览器会话。提醒时钟冻结为 2027-10-10 上海 09:00；云镜像仅在该临时库初始化，并通过真实 provider 纯解析函数规范化，不使用 OAuth 或调用提供方。事项编辑、提醒 POST、身份检查、回执 GET 和数据库结果均来自实际应用。故障只替换真实成功回复，不伪造成功 DTO；`/me` 原文和 CSRF 不写入证据。

## 固定输入与调用

先由集成人审查工具和真实构建，再在固定提交、干净的独立 checkout 中执行。以下为参数示例，必须替换为实际冻结身份，不能沿用旧包：

```powershell
& $python -B -X utf8 scripts/check_expo_task_reminders_browser.py `
  --source-root $checkout --expected-head $fixedHead `
  --build-source-head $buildHead --bundle $freshExport `
  --expected-build-evidence $buildEvidenceSha256 --temp-root C:/tmp
```

默认执行三条。需要补验时可重复 `--case committed_response_lost --case committed_identity_read_failed`，只执行指定流程并去重；结果记录实际 case 和对应截图数，不能把部分通过称为全部通过。保留失败目录，不自动重试。

构建来源必须是当前提交的祖先，完整 `frontend` Git tree 和构建 `inputFiles` 每个字节都必须相同。工具允许后端、测试、文档等已审非前端增量，但会列出完整构建来源差异；实际服务使用当前 checkout 的后端，核对真实 import 路径，并记录全部受跟踪源码前后 hash。此复用规则只证明导出和前端相同，不替代后端差异审查。导出文件集合及 hash 必须与原 `build-evidence.json` 完全一致；Windows 复制使用扩展路径，临时根需采用存在的短目录。

## 原件和边界

新的 ignored `test-results/expo-task-reminders-<UTC>/` 保存执行脚本、真实 HTTP 请求／成功响应原件及 SHA、SQLite 表快照、逐图尺寸指标、失败截图／ARIA 和最终 `result.json`。`sessionStorage` 仅记录合成任务的原 requestId、occurrence、revision、动作、绝对暂缓时间、筛选／页码及会话身份 SHA256，不含标题、令牌或明文身份。真实 `/me` 失败注入只记录状态、合成成员／家庭 ID 和回复 SHA。

成功要求所有指定 case 完成、截图数匹配、无外部网络或提供方尝试、无浏览器异常、源码／导出／fixture 前后不变，且 listener、线程和临时库都已清理。这是临时合成数据下的实际 UI／HTTP／SQLite 演练；不验证真实 Microsoft／Google 账号、手机通知、实体电视、生产迁移或本人完整验收。

`tests/test_task_reminders_browser.py` 只验证导出复用边界、case 选择、故障注入前提、证据脱敏及真实 Edge 静态 HTML 定位器。运行此模块不会启动产品演练、模型、正式构建或生产操作。
