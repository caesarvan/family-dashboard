# 本人站内提醒：使用与集中验收

<a id="task-reminders-release"></a>
## 当前状态

**2026-09-20 07:52:22（北京时间）激活，07:56:49 独立生产只读审计通过。** Git 合入、实际发布和独立审计分别有原件；本次计划已经消费，不得重放。

源码已由 [PR #13](https://github.com/caesarvan/family-dashboard/pull/13) 合入 main `0e35f3d9ad83cc8506257a5ff06a350c8484534a`，与下方实际安装 source 同树；后续纯文档提交不改变运行包身份。

本批增加本人站内提醒及个人导出、两表迁移和恢复配套。只在看板内显示，不含系统推送、短信或自动云写入；不自动完成待办或解除前置关系，电视不读取个人提醒。日程重叠是下一独立功能，未包含在本包。

## 怎样使用

1. 在本地待办填写截止日，并分配给本人或选择共同处理。到期日北京时间 09:00 起，未完成事项出现在「首页 → 我的提醒」；没有截止日期的任务不会提醒。
2. 默认查看「未读」，可切换「全部」，每页 40 项。共同任务的已读与暂缓各成员独立；不会替伴侣处理提醒。前置未完成仍显示原因，提醒不绕过任务完成门禁。
3. 选择「标为已读」「1 小时后提醒」或「明天 09:00 提醒」。后两项保存明确的绝对时刻，暂缓到期重新显示未读；核对或重复原操作不会延后时间。
4. 选择「打开待办」时重新读取原事项，再用原 ID 和版本编辑。返回原筛选与页码；完成、删除、改负责人或改截止日后刷新，列表依最新任务状态变化。同步清单的事项须在原应用修改。
5. 有需要时从现有个人数据导出入口下载本人提醒历史。导出不会加入伴侣的已读习惯，也不会执行历史操作或恢复数据库。

同一截止日重新打开任务会保留原已读／暂缓状态；更换截止日形成另一条日期记录，改回原日期恢复原历史。提醒接收人规则不把家庭共享待办变成私人任务。共享云清单只有在真实来源关系仍获授权时才参与提醒；本批测试使用合成来源，没有对真实云账户写入。

## 断线或结果不明时

先点「核对操作结果」。找不到回执也不会自动再次保存，只有明确选择「重试原操作」才重发同一请求和同一绝对暂缓时间。回执已确认但列表读取失败时，只刷新读取，不重复写入。

浏览器同一标签页刷新后可恢复原操作；身份未核对完成时不展示旧记录，切换成员或退出后清除旧范围。恢复记录不含标题、备注或凭证。该能力依赖当前网站的 sessionStorage，不承诺跨设备、关闭标签页后或原生 App 重启恢复；存储不可用时不会开始写入。服务端状态与回执保存在 SQLite，后台重启后仍可核对。

只有实际保存请求收到明确拒绝且身份核验成功，才显示未保存。保存后身份读取发生 404／429 等错误仍属于结果待核对；不能丢弃原操作并假报失败。明确版本冲突时先读取最新状态再决定下一次操作。历史容量满时说明限制，不静默删除未核回执；普通退出登录不删除服务端历史，移除成员会同事务清理其提醒记录。

## 已完成的分段验证

下表各阶段有重叠，不相加为一次全量检查，也不代表本人完整验收。

| 阶段 | 实际结果 | 范围与限制 |
| --- | --- | --- |
| Windows 组合后端 | 82/82，0 失败／错误／跳过 | 提醒、个人导出、任务依赖、成员撤权和 worker；真实临时 Flask／SQLite，合成身份和任务 |
| 正式 Expo | fresh npm、两组 TypeScript、31 Node、23 导出 | 21 提醒＋10 任务依赖；前端及补充输入前后绑定，组件宿主与传输使用合成数据 |
| 浏览器 R1 | 全部 3/3，10 图 | 读／暂缓与原任务编辑返回、POST 已提交后响应丢失／503、提交后身份 GET 429／404；真实本地 HTTPS／Flask／SQLite／Edge |
| 浏览器 R2 | 仅第三项补验，中途失败，2 图 | 加强身份失败故障时序后的首次执行；故障命中断言失败原件保留，不能记为通过 |
| 浏览器 R3 | 仅第三项 1/1，4 图 | 稳定故障命中、原回执恢复、无重复 POST／状态写入；不写成 R3 全三流程 |
| Windows 迁移工具 | 33 个唯一用例，分 32+1 通过 | 首轮一项测试注入路径失败，修正该测试后单项通过；依赖历史 Git 的 Windows fixture，未混入 Linux 82 |
| 发布适配工具 | 45 项与帮助文案增量 3 项分别通过 | 临时文件／包与记录式服务调用，不当作真实生产迁移 |
| 演练工具 | 首轮 31 项、修正后 4 项通过，其中 1 项重复 | 原 settings 校验误将两次真实建任务的 meta +2 判为漂移；窄修后用真实 Flask 闭合程序验证 +2、其余 settings 不变、漂移拒绝。不是 35 个唯一用例 |
| 实际隔离 Linux | 82/82，0 失败／错误／跳过 | 固定精确节点、无网络、只读根、UID 10001、仅临时数据，不挂生产 |
| 实际 Linux 迁移与恢复 | 独立程序通过 | 父镜像生成两户三库 69/9；69→71、仅 app 启动严格保全；真实 read／snooze、回执与重放，71 表重启，旧 69 与非空 71 完整库组恢复 |

浏览器原件包括真实请求、状态／回执数据库核对、390／1280 截图和实际 body 横向溢出检查。R1 与 R3 使用同一正式前端导出；R2／R3 是工具时序补验，未改变产品保存语义。所有失败原件保留；不使用模拟成功响应替代核心业务请求。

迁移首次只创建两张精确匹配的空表，不回填任务。app-only 阶段原 69 表、平台 9 表及全部 settings 必须不变；worker 恢复运行后新增提醒与检查 heartbeat 属于正常活动，不能据此放宽停写证明。非空演练两次真实任务创建允许且验证 settings.meta 恰好 +2，提醒读／暂缓本身不改 settings，其余旧表哨兵保持。两种恢复都使用完整注册库及所有家庭库；未执行生产覆盖恢复。

## 固定交付身份

| 项目 | SHA256／固定值 |
| --- | --- |
| Source / tree | `77150610f4fa2eae1edaaadb94198e9f3093f3c5` / `fa940fcb63d8ca6fe470e674539fd74492cae602` |
| Expo build source | `a382c9b1a8c4c92a93d9872b27a4ee3da0c916d4`，前端与最终包逐字节一致 |
| Expo build evidence | `6f75ea34e049bae1130d7c9bb06f4e0bc61b14583e843a204bd417964841a736` |
| Package | `67720847156174e624e8a5d648f83126e3f7db23fa5dc5839a04225359ab0590` |
| Manifest | `0690076adebf7e8c2204ecde005444ee1aa3489eb888fd08c9fd9053e7e3c727` |
| Archive | `6e00c09b984116d406e267f630bbb61ba01fa621e6d55980b33b56111587f9a6` |
| Image | `sha256:a99d11dec43be931f36496368e0565f9dfc87492fcd391dfbff92d2a61470f0e` |
| Linux build | `ad0cd2aaed02e86588b8701382e18d5a043fc160db18ddb2f031a74e8fb775d2` |
| Linux 82 节点验证 | `41a7622fb2257acf9877083c20dd8e57859790fd3dd2976861b5f306933fec98` |
| Linux 迁移与恢复结果 | `88a139001601a54871da1cfb1bcb6fc3589161638c1fea64de9d145ccc2aba3f` |
| 已消费计划 | `53d47e9e95307a6169b13d7a8ab67098b107e6cf4e2e56845dd4338b8417b009` |
| Stage / activation | `470eab690144f813ab4d99ae5848c53c6c35ca3c9caec87276c214f7ccdfa274` / `40be8e20a84b990a8045bea57b192395a74bf0a510e84bbfb395316e989647b3` |
| Release directory | /opt/family-dashboard-releases/task-reminders-71-20260919T235036202570Z |

106 个非 Expo 运行文件中，只新增 task_reminders.py、修改 app.py／sync_worker.py／household_memberships.py／data_portability.py，其余 101 项保持父版；Docker COPY 增加新模块，依赖锁、Compose 和环境合同保持。生产实际由家庭 69 表迁至 71 表，平台 9 表保持。纯文档提交不改变正式包身份。

## 实际发布与独立审计

激活于 UTC 2026-09-19T23:52:22.889230 完成，stage 与 activate 均 exit 0；独立审计于 UTC 23:56:49.726935 观测，执行 exit 0、stderr 为空。核对 1030 个安装文件、app／sync／media 各 129 个运行文件，106 个非 Expo 文件及 101 个父版保留项均匹配；四服务 running、零重启，app healthy。75 个正常 TLS 资源与三个入口均 200，metadata 入口 404；env 文件、实际环境键值映射、成员 marker、web 镜像保持，备份 timer active。环境变量排列顺序有变化，未声称排列字节相同。

生产是 **一户两库**，与隔离演练的两户三库分开。迁移只新增两张提醒空表，原 69 表的 schema／行／列／序列、平台 9 表和全部 settings 保全；迁移后与 app-only 干净停机后的完整逻辑摘要相同：`bd50951d5cff6466ce1d295522f21423613b435b34f04e2b219b2ed54a42440c`。两新表在该窗口为空，之后 worker 正常写入状态和 heartbeat 不属于此停机证明。审计不读取活跃数据库，也不宣称活库永久不变。

两份停机备份仅核验保留文件字节，没有生产覆盖恢复或在审计阶段新建备份。32 项匿名 GET 均 401，只证明匿名读取被拒绝，不证明 POST 身份验证、本人操作或真实模型／云端请求；审计没有服务变更、业务写入、app／SQLite 导入或活库查询。

## 原件定位

以下相对路径位于维护者受限的 family-dashboard-access 下；完整数据库、回执与截图不提交 Git。

| 原件 | 相对路径／摘要 |
| --- | --- |
| 正式包及 Expo 证据 | task-reminders-release-20260920-r1/package/ 中 package.json、release-manifest.json、build-evidence.json；摘要见上表 |
| 实际 Linux 传输终态 | 同批 linux-inputs-r1/transport/ 中 build、validate、rehearsal 的 json／stdout／stderr；均 exit 0，stdout 绑定上表远端结果摘要 |
| Windows 组合后端 | worktrees/task-reminders-combination/test-results/task-reminders-combination-r1/ 的 execution.json、junit.xml、stdout／stderr |
| 构建独立证据审查 | worktrees/task-reminders-migration/test-results/reminders-build-independent-r1/review.json，`0999e14db09b8584ef65548696b8c6625028d7e04536ad6107761aec9ec4d40a` |
| R1 三流程浏览器 | worktrees/task-reminders-browser-r1/test-results/expo-task-reminders-20260919T224134810051Z/result.json，`d56a0024265d49bc399170a1a88724c2e5738f3c47e69f15a68aa8693a5f0c1c` |
| R2 失败保留 | worktrees/task-reminders-browser-settle/test-results/expo-task-reminders-20260919T225243486201Z/result.json，`1b23370aaea1445f579374962439d14100f93e5a530cbe7be5cd951dd2bdb7e1` |
| R3 第三流程补验 | 同 worktree 的 test-results/expo-task-reminders-20260919T225726940866Z/result.json，`3bf6dc1bb158f01e21665b731ebf168ca374e4c85ec9e0a80b32c4e4226dabb0` |
| 实际激活调用 | task-reminders-release-20260920-r1/execution/activate.result.json 与 stdout；终态绑定上表 activation 回执 |
| 独立生产审计 | worktrees/task-dependencies-browser-r4/test-results/task-reminders-production-audit-r1/task-reminders-production-readonly-r1.result.json，`313e15072070f499f286c817d20227378309ec1a6129feb8e985d597f88e30f8` |
| 独立审计执行终态 | 同目录 task-reminders-production-readonly-r1.execution.json，`e44322a8e0ff0143bd72642ddc37a3e39ad81a17e8211fd4ec2c3c5999e6acce` |

实际 Linux 独立审查见同批 reviews/actual-linux-review.json，`2809ba36dbcd44719895a15d8ba3f8f46167289beede06e585f36fc24c4e0338`；该审查绑定上表真实演练结果，与本次生产审计分开。

## 后续协作与验收边界

本人完整 A–D 验收仍为 **0/4**；真实云写入待明确目的地，实体电视暂无法验证，真实家庭长期使用和生产恢复仍需单列验收。新增工具与分模块测试不能替代本人操作。

接口、界面和导出模块文档保留各自作者阶段的历史测试范围，当前交付状态统一以本页为准。下一轮从已审主线新建独立分支／worktree，不重放已消费计划或覆盖冻结目录。[提醒 API](TASK-REMINDERS.md) · [Expo 交互](EXPO-TASK-REMINDERS.md) · [个人导出](TASK-REMINDERS-PORTABILITY.md) · [迁移](TASK-REMINDERS-MIGRATION.md) · [Linux 演练](TASK-REMINDERS-LINUX-REHEARSAL.md) · [发布合同](TASK-REMINDERS-RELEASE.md) · [Git 协作](GIT-WORKFLOW.md)。
