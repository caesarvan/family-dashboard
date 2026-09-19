# Expo 旅行待办同步：浏览器验收

脚本为 `tests/browser_expo_journey_tasks_check.py`。本批只准备脚本并完成静态自检，**尚未执行浏览器验收，不能据此声称界面或云端联调通过**。实际运行须在非作者审查、产品变更整合及下一批独立 Expo 构建完成后进行。

本分支 `codex/expo-trip-task-publish-browser` 固定从产品候选 `5f2eef86580c76fa0df534323eec44dbfa5b89ee` 派生，准备时该候选尚在独立审查。本分支只增加此文档和验收脚本，不包含随后产品分支的文案修改；协调者应整合审查通过的产品版本后再构建。不要使用正在验收或发布的 trip-items 导出目录，也不要跨分支复制产品实现。

## 运行边界

- 真实：Edge 无头浏览器、已冻结的 Expo 导出、临时 HTTPS Flask 服务、独立临时 SQLite、成员登录和 CSRF、旅行创建、待办发布 state/preview/confirm/action 接口及实际同步队列 worker。
- 合成：两个成员、两家提供商的账户和旅行数据，以及现有 `test_task_publish.Remote` 的提供商 HTTP 传输。Microsoft/Google 适配器仍执行真实代码，不制造业务响应 DTO。
- 故障：仅拦截真实浏览器传输，区分“请求未发到服务端”和“已提交但返回丢失”；身份场景暂留真实预览回复，切换真实登录 Cookie 后才放行。未知确认与迟到身份场景将页面 10 秒轮询延长到一小时，避免轮询抢先消除待观察的故障；显式刷新仍走真实 HTTP。其他场景保留原轮询。
- 旅行、账户和清单选择在每个临时数据库内准备；重连用实际 `CloudAccounts.select_sources` 撤销并重新选择原来源，前端操作实际预览及确认。合成云端内容变化通过既有内存传输对象注入，随后由真实 worker 观察。
- 禁止：生产写入、真实云端/模型请求、真实授权、真实个人数据、实体电视验收。Python socket 仅允许回环地址，浏览器请求只允许当前临时 HTTPS origin；模型调用被明确拒绝并记为失败。

## 八个独立场景

每种提供商运行以下四个场景，共八个；每个场景有独立临时应用、数据库、浏览器上下文和证据目录。某个场景失败不会阻止其他场景收集证据。

| 场景 | 核验结果 |
| --- | --- |
| 原任务发布与完成回流 | 从原旅行选原任务，明确选清单，预览只读，确认才入队；worker 创建一个云端任务，云端完成写回同一本地任务。负责人、旅行关联、备注、截止日保持，旅行进度更新，没有额外本地任务。重建实际 Flask 应用和监听器后，同一 SQLite 数据保持；这不等同于独立操作系统进程重启。 |
| 未知确认与队列重试 | 服务端已提交而回复丢失时，只读取原绑定，不再确认。请求未发出时，核对后显式使用完全相同的预览凭证。提供商已创建而回执丢失时，显式重试仍查找原发布标记，不重复创建云端任务。 |
| 冲突与原目标重连 | 查看两边真实内容，分别明确采用云端内容或用本地更新云端；包含双方同时修改、暂停和恢复。撤销后恢复同一云账户/清单，重新预览，沿用原 publication 和远端任务，不复制本地任务。 |
| 身份切换与迟到预览 | 持有成员一的真实私有清单预览回复，实际登录成员二后才放行；旧账户名称和确认按钮不再显示，原任务/发布表不变，没有确认请求，私有预览没有写入浏览器持久存储或地址栏。 |

Microsoft 场景额外保存预览、云端确认后、冲突比较三个状态各 390/1280 宽截图，共六张。复用现有控件边界检查，并直接记录和断言 `document.body.scrollWidth`、`body.clientWidth`、根节点 `scrollWidth` 与实际视口，不能只用截图或内部容器宽度声称页面无水平溢出。截图不替代人工视觉审查，也不覆盖全部滚动位置或实体电视。

## 冻结构建与执行

准备好审查通过、干净的整合 worktree 和独立构建结果后，以仓库现有 Python 虚拟环境运行。以下变量必须替换为本批真实冻结值：

```powershell
$taskPython = 'C:\path\to\family-dashboard\.venv\Scripts\python.exe'
$taskSource = 'C:\path\to\reviewed-task-publish-worktree'
$taskHead = '<该 worktree 的完整 40 位提交>'
$taskBundle = 'C:\path\to\independent-build\experience'
$taskBuildEvidence = '<build-evidence.json 的完整 SHA256>'
& $taskPython -B -X utf8 "$taskSource\tests\browser_expo_journey_tasks_check.py" `
  --source-root $taskSource --expected-head $taskHead `
  --bundle $taskBundle --expected-build-evidence $taskBuildEvidence
```

`build-evidence.json` 必须位于导出目录的父目录。脚本校验其 SHA256、构建源 head/tree、输入文件哈希及完整导出清单。长 Windows 路径通过复用 `export_hashes` 的扩展路径枚举检查，不静默忽略超过 MAX_PATH 的文件。

若构建后只追加验收脚本/文档，可额外传 `--build-source-head <构建提交>`；脚本要求它是待验收 head 的祖先，而且两者**完整 frontend Git tree 一致**，所有绑定构建输入仍匹配。不得用此参数绕过产品代码差异。Python 必须启用 `-B` 且不能用 `-O`，避免生成未跟踪字节码或禁用断言。

## 证据和判定

输出到新建的 ignored `test-results/expo-journey-tasks-<UTC时间>/`，不会覆写旧报告。`result.json` 包含源/导出/实际导入 fixture 的前后哈希、八个场景状态、HTTP 收发证据、业务表快照、合成提供商调用、截图尺寸与哈希。每个故障场景保存独立失败文本，浏览器失败还尝试保存截图和可访问树。

全部八项通过、六张截图形成、没有浏览器异常/外部请求/意外模型调用、所有临时 fixture 及监听线程退出、源和导出冻结不变，才输出 `passed: true` 并退出 0。最终证据检查失败也会写失败报告。HTTP 原文及数据库快照仅含合成数据；不要把该脚本接到生产数据库或真实 OAuth 环境。

结果应分别报告：静态自检、实际浏览器结果、独立视觉审查、真实账户及实体设备尚未验证的范围。不要把重复运行或每个断言累加成新的验收场景。
