# Expo 任务依赖：组合浏览器验收工具

工具为 `scripts/check_expo_task_dependencies_browser.py`，复用已有真实 Flask / 临时 SQLite / HTTPS / Edge 基础 runner。此批先提交工具供独立审查；代码或小测试通过不等于三个浏览器场景已经通过，须等待集成人提供已审组合源码和新 Expo 导出后实际运行。

## 三个固定场景

| 场景 | 实际路径与核验 |
| --- | --- |
| `selection_completion` | 分别在 390 与 1280 宽度编辑原任务、选择前置、真实 PATCH。检查出站原 ID / revision、SQLite 后续投影与版本。Home 和 List 均阻塞后续完成；前置完成后，390 用 Home→List、1280 用 List→Home 完成整个流程。 |
| `invalid_conflict_clear` | 初始临时数据库放置明确标识的历史失效引用；UI 保留它、阻止直接保存，并由本人清空后真实 PATCH。循环候选和自身不得列入选项。第二个真实成员会话在浏览器已选候选后用 API 建立反向边，原保存真实返回 `task_dependency_cycle` 409；输入及选择保留，再明确清空保存。 |
| `committed_response_lost` | 390 的真实新增 POST 提交并返回 201 后丢弃响应；1280 先收到真实 201，再在传输层改为合成网关 503。两次均核对真实数据库只有一条原 ID / revision=1、一次 create 审计，编辑器保留并冻结。一次真实定时 GET 不能解锁或重发；明确关闭并重新读取，找到原记录，不再次新增。 |

核心 CRUD、完成、并发冲突、授权与数据库全部真实运行。仅历史失效引用属于初始 SQL 夹具，范围严格限制为新建临时数据库，不模拟正常删除 API 的行为。成功响应均来自真实服务器；注入的 503 只是响应丢失故障，证据同时保留实际 201 与交付故障类型，不把假响应算作真实后端失败。

默认预期三项完成记录、10 张截图：`selection_completion` 6 张，`invalid_conflict_clear` 2 张，`committed_response_lost` 2 张。自动检查当前视口横向溢出及错误提示完整文本边界；截图还需独立人工读取，不把数值布局检查当作视觉审查。

## 固定输入

必须用项目 Python 的 `-B -X utf8`，不可使用 `-O`；脚本检查禁止字节码和优化。当前源码须 clean，`--expected-head` 固定完整提交。`--bundle` 的相邻 `build-evidence.json` 必须与显式 SHA256 匹配，导出逐文件哈希和构建输入逐文件哈希都要相同。

默认构建来自同一提交。若构建先于工具合入，必须显式给 `--build-source-head`，且该提交必须是当前 HEAD 祖先，两者差异只允许本脚本、小测试和本页三条路径；业务源码、前端或借用的 runner 变化一律拒绝复用。集成/API/UI 已有变化时应构建新的组合导出，不能套用旧包。

```powershell
& '<项目 Python 绝对路径>' -B -X utf8 scripts/check_expo_task_dependencies_browser.py `
  --source-root '<已审组合 worktree>' `
  --expected-head '<组合完整 SHA>' `
  --build-source-head '<构建源码完整 SHA；与组合相同时可省略>' `
  --bundle '<冻结导出 web 目录>' `
  --expected-build-evidence '<build-evidence.json 的 SHA256>' `
  --temp-root 'C:/tmp'
```

可选 `--case committed_response_lost` 只执行第三条，预期 1 项完成记录、2 张截图；重复 `--case` 可选择多项，按给出顺序去重，仅接受三个固定名称且不可为空。不传则仍运行全部三条。报告明确 `requestedCases`、`requestedChecks`、`expectedScreenshots`；单项通过不代表未选择场景本次也通过。

`--temp-root` 必须是现有本地短目录；每个场景使用专属随机子目录，避免 Windows 长路径失败。Windows 导出读取使用扩展路径。三个夹具依次清理，Flask listener 和工作线程必须停止。工具仅监听 127.0.0.1，Python socket 与浏览器外部请求均拒绝；模型及云 provider 未连接。

## 证据与界限

每次新建 ignored `test-results/expo-task-dependencies-<UTC>/`，保存执行脚本副本、每条核心 HTTP 原始响应及摘要、合成数据库快照、截图、失败原件和 `result.json`。不覆盖或删除旧失败，不自动重跑失败场景。总结果只有在所选场景及各自预期截图数、原件/源码/构建/借用 runner 前后哈希不变、Git clean 和临时资源清理全部满足时才为通过；默认仍是三场景、10 图。

`tests/test_task_dependencies_browser.py` 只测试构建来源门禁、拒绝业务差异，以及提交响应丢失注入必须先有成功后端响应。它不验证产品 UI、真实云账户、Linux 发布、实体电视、通知提醒或生产。运行三个浏览器场景和独立审查仍是后续步骤。

冻结文字输入使用浏览器不可编辑语义（只读或禁用）；勾选和保存按钮仍要求禁用。工具小测试包含真实 Playwright 静态 HTML 定位及只读/禁用/正常输入验证，不加载应用、不请求网络，不替代三条产品流程。
