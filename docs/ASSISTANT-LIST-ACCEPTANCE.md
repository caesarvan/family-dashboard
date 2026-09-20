# 助理清单调整与恢复：使用和验收

<a id="assistant-list-release"></a>

**已发布。** 2026-09-21 05:41:15（北京时间）激活，05:41:40只读回读通过。接口见[清单契约](ASSISTANT-LIST-EDITING.md)，发布方式见[固定适配](ASSISTANT-LIST-RELEASE.md)。

## 最短使用路径

家庭助理 → 输入待办或采购需求 → 整理并预览 → 逐项调整 → 勾选并确认保存 → 查看待办／采购或首页。

可调整标题、分工、截止日和备注；采购另有数量、预算与优先级。预算以元输入，空值与零分别保留；服务端使用整数分。调整期间不创建事项，最后确认才保存到家庭共享清单。负责人只表示分工，保存不会下单、扣款、扣库存或自动写入云端。

保存响应丢失时，先按原计划核对回执；刷新后也能恢复原计划编号，再按实际状态继续。未确认的字段修改不写浏览器存储，刷新后需重新核对。过期或无法读取时先查看已有清单，再明确结束原计划核对；无法读取不等于之前没有保存。账号变化、离线或后台会隐藏本页内容。

## 固定运行身份

| 项目 | 固定值 |
|---|---|
| source / build source | `e8f0427b35157074d179bc4de86a7c5c4db0a755` |
| tree | `20943ac7e9e791e6d6dfa8c4ec5e0c0e3df8470e` |
| package | `e73244becca1664973d4ee0e2f4d670c8cc79148ed9c3000d1501edb77eca0df` |
| manifest | `670859d5c9e9124f50381f410ac3cb231055ed05a8572af7e347be3daec4ec63` |
| app image | `sha256:e5195f8db0df97860ccec7ffd6955156240f4b9920406b40d8aad104f7392bf1` |
| Expo build evidence | `1a30780e92e7ca85caa068bbcb85508f7bbc690392806d1f977bad077c027177` |
| activation plan | `89c99949c18204fef03de42b3c1c0fc718cadad9a3404e9900d3c123d89ff0e8` |
| operator | `ecf5b38bcca7ae1f1110dbc588a1975e4dc59d4a491fd9e9b51c07dd2062834c` |

Git [PR #60](https://github.com/caesarvan/family-dashboard/pull/60) 已合入 integration `cfc21a3`。运行包固定在 e8；后续 `0266a5c`、`9395df8` 两次修正只涉及浏览器工具与说明，验证执行提交为 `6e271d6`。它们没有改变业务模块、前端构建或运行包，不以新的 Git 提交冒充重新部署。

## 实际验证范围

| 验证 | 结果与范围 |
|---|---|
| 后端作者检查 | 55 个唯一用例分轮通过，56 次实际执行；第二轮仅针对严格任务日期类型修正。非作者审查通过。 |
| 前端作者检查 | 20 个新增＋14 个相邻唯一场景分轮通过；37 次场景执行及一次测试文件语法装载失败保留。两组类型检查，末尾小改动另有定向验证。 |
| 正式前端构建 | 独占工作树 fresh npm ci、两组 tsc、Expo export 全部退出0；166前端＋9补充输入，23导出固定。 |
| 真实前后端交互 | 1 个 pytest 包装中实际12条 Flask/Node场景通过，包括丢响应、原确认重试、切换账号、退出、迟到响应及分页搜索。 |
| 真实 Edge 浏览器 | R1 手机390px编辑／保存／刷新／首页通过；R3 桌面1280px原回执恢复、离线隐藏、切成员与撤权通过。六张有效截图无横向溢出。 |
| Linux实际镜像 | 精确55/55、0失败／0跳过；59个业务模块来自 `/app`，136运行文件和1249安装来源／导出文件前后保持。隔离验证1024MiB，运行前后父服务保持。 |
| 发布适配 | 7个记录式服务流程用例通过；75→75，无迁移；完整组备份、失败停止及计划不可重放。不是生产恢复演练。 |

浏览器 R1、R2 的整轮失败仍保留：首次工具在真实响应丢弃完成前过早检查；第二次工具错误等待账户菜单自动切换。修正分别等待真实 abort，以及先核对旧内容清除再按页面提示显式刷新。最终仅补桌面，不重跑已通过手机；不能将分轮结果改写成首次整轮通过。

112个非Expo运行文件与父版保持，仅 `home_assistant.py` 变化；媒体资源证据只沿用未变的媒体路径，不代表新增助理负载、任意并发或生产恢复验证。本人完整A–D验收仍0/4，真实云写入、手机选择器和实体电视另验。

## 实际生产更新

生产一户两库完成完整组备份，75张家庭表和9张平台表没有迁移；app单独启动后再次停止，核对全部表、数据、settings和序列一致。1249个安装文件、三个应用服务各136个运行文件及decoder原4文件逐项核对；五服务运行，app/decoder健康，无OOM或重启，HTTPS正常校验证书，备份timer active。本次未执行生产恢复；只读回查不重新读取活库业务内容或重验备份SQLite字节。本人完整A–D验收仍0/4，实体电视待验。

- release目录：`/opt/family-dashboard-releases/assistant-list-75-20260920T213925112208Z`。
- stage：`5ad7c88faf9dd17ae2c18502525a4c12630e023b8103620d71669df1c7b2624d`。
- activation：`3e60ab9d6980fe0bbc7747820afaed220ce437624706ab1373550f4bda6f90a8`。
- 正常TLS只读回查：`7e85d630658491965651cff457e6c31e28ff02a48b3a7ae7fd2852ab0f80d8e0`。
- 25份stage、activation、phase及保全回执已下载并逐项复算散列；下载原件：`059c9c316e9e783bc39164383ae11a6eb3fb5adb1158a36703f90f6076979b58`。

## 原件索引

原件放在版本库外的 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`，不提交截图、临时数据库或测试输出：

- `assistant-list-release-candidate-r1/`：固定包、选择、Linux镜像构建／验证原件、五角色审查、实际计划。
- `worktrees/assistant-list-combination/test-results/`：正式Expo构建、真实Flask/Node、浏览器R1/R2/R3及有效截图。
- `worktrees/assistant-list-api/test-results/`：作者后端用例、契约／发布／资源独审。
- `worktrees/assistant-list-ui/test-results/`：作者前端检查与Linux独审。
- `worktrees/assistant-list-browser/test-results/`：API/UI及固定包业务source独审。
- `assistant-list-production-r1/`：本批实际部署、只读回查、25份回执及准入原件。

后续发布须按届时的实际安装身份重新准备；禁止重放历史已消费计划。下一步产品工作见[产品计划](PRODUCT-PLAN.md)。
