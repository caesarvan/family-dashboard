# D：家庭隔离与协作连续验收

脚本：`tests/browser_household_isolation_chain_check.py`。作者基线 `caf34d5a825716fe2ff0aaf363df0d4412c71e91`。这是下一批验收候选，仅做静态检查，尚未运行浏览器；不影响当前家庭成员发布。

## 六个连续检查点

只启动一套临时 Flask、HTTPS、SQLite 和 Edge；同一 A/B 两户与合成记录贯穿全部步骤，不在步骤间清空财务数据。

| 检查点 | 实际操作与主要断言 |
| --- | --- |
| identities | 实际邀请创建 B 户，两户均有 member1/member2；A1 将 A2 设为普通成员，A2 登录两个浏览器。普通成员管理返回 403；A cookie 与 B 家庭入口混用返回 401；B 户角色／会话不变。 |
| private_records | A2 创建资产、两张照片、两个地点和两个 PDF；B2 用同一 requestId 创建另一账户。按 ID、列表、文件和后台 import 结果检查隔离，A1 管理员也无 A2 私有读取权限。账户回执按户／本人隔离，金额及文件真实持久化。 |
| explicit_sharing | A2 仅共享一张照片、一个地点、一个 PDF；A1 实际打开地图、读取粗略坐标及 JPEG/PDF。其余对象和资产仍私人；共享 PDF 不赋予管理权限；另一户与合成 TV 不获得额外权限。 |
| revoke_two_sessions | A2 真实 JPEG 响应暂扣后隐藏页面；A1 经成员界面实际撤销两个会话，提交成功后丢响应。未知状态不自动 GET／重发；明确读取和结束核对后显示当前状态。目标版本、两会话、浏览器代次及一条审计变化，业务与 B 户保持。 |
| old_sessions_and_late_bytes | 两个旧 cookie 的财务、照片、地点、PDF、后台结果新请求均 401，旧 cookie 写入也拒绝。释放旧 JPEG 不恢复隐藏内容；旧 blob 失效，前台读取发现当前用户为空并卸载旧回顾。 |
| fresh_login | A2 以新会话登录后恢复本人资产、原回执、照片、地点、PDF 和原后台处理结果，普通成员身份保持；没有重放确认或创建新业务记录。A1 私有权限不扩大，B 户保持。 |

每步记 `passed/failed/not_run`。首个失败保留异常堆栈、可取得的截图与可访问树，下游依赖步骤保持 `not_run`；不把未执行记成失败，不从多轮拼接通过数。清理失败或源码变化都会使整轮失败。

## 复用与证据

复用 `browser_expo_finance_check.Run` 的临时应用／浏览器框架，经 `browser_expo_trip_recap_check.Run` 复用真实旅程、地点、媒体入库和图片生命周期方法；仅复用 `browser_expo_household_members_check.Run` 的局部成员交互，不执行这两份脚本的原场景。实际依赖还包括 `test_household_media`、`test_journey_documents`、`test_financial_files`、`test_app` 和 `media_images`，合计八个复用文件与本脚本九个 SHA 绑定。

所有用户侧成功响应来自真实应用；故障仅丢弃已提交的真实响应或暂扣真实 JPEG。唯一提供方替代是合成媒体账户／选片／下载任务结果，实际引擎仍持久化媒体、确认记录并返回清洗后的 JPEG；不连接真实云、不运行真实定时调度。SQLite 只读证据连接使用 `closing`，资源按浏览器 context、服务器、临时目录的顺序释放。

输出独占 `test-results/household-isolation-chain-<UTC>/`，包含执行脚本、完整结果与三张有限可见视口截图：共享地图、管理员未知状态、新登录的本人账户。截图不自动视为人工视觉通过，也不扩展为全站尺寸／主题矩阵。

脚本必须单独传作者 `--expected-harness-head` 与 `--expected-harness-sha256`；受验应用另传 `--source-root`、`--expected-head`、`--bundle`、`--expected-build-evidence`。执行前后核对双方 Git HEAD、tree、clean、作者两文件、全部受验 tracked 源码、构建输入、导出文件及实际复用 fixture 字节。受验应用可以不包含本次新脚本，不把作者 HEAD 当成应用 HEAD。只能在非作者审查后按协调者给定的最终应用与构建身份运行。

## 解释边界

这份验收补充 [D 场景](ACCEPTANCE-SCENARIOS.md#d多用户隔离与协作) 的集中本地链，不替代加入／退出家庭、任意成员数量、通用用户成员关系或同一人多家庭切换。创建 B 户仍是“邀请创建新家庭”，不是加入 A 户。

管理员撤会话不是删除成员、封禁新登录、删除云账户或取消所有后台任务。只核本链明确发出的后续服务端请求和页面迟到响应；已经交付给客户端的字节不能撤回，不推断所有在途请求均被取消。`found:false` 仅表示该本人／家庭查询未找到原回执，不作为某次写入从未在途或可自动重写的证明。真实个人数据、真实云、实体电视均未覆盖。
