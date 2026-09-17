# 家庭与成员：发布与验收记录

<a id="household-members-release"></a>
## 当前状态

北京时间 2026-09-18 05:49:18 已完成激活，05:49:55 post 正常 TLS 读回通过；05:55:19 独立 fresh 读回、05:55:37 独立审计通过。后续纯文档提交不改变安装包身份。

入口为「更多 → 家庭与成员」。现有两位成员初始化为共同管理员；管理员可以明确调整另一成员的家庭角色，或让对方当前浏览器全部退出。对方仍可重新登录；普通成员仍能使用原有业务，只是不能管理成员。会话数不等于物理设备数。本人登录设备继续使用既有入口。

结果不明时，只能明确读取当前成员状态再结束本地核对；当前列表不冒充本次操作回执，不自动重发。详情见[使用与恢复](EXPO-HOUSEHOLD-MEMBERS.md)、[API](HOUSEHOLD-MEMBERS.md)。

## 固定身份与本地证据

私有证据根为 `family-dashboard-access`（下称 access）；`T=access/household-members-tools-20260918-r1`。没有将凭据、数据库正文或个人资料写入本文。

| 对象 | 固定身份／SHA256 |
|---|---|
| 正式 main | `08c0260b24e7ae917d5698dcbebde4fda6ff428d` |
| formal／source | `6cbab928ac29ea39eb125a8b5987e5d2a135f202` |
| 同一文件树 | `64c02ab1996836a5e6cc783b17f279c9637499f5` |
| archive | `57cee29157d0ab96f500e760506139cef47d88fa90875409916cda4fab20e276` |
| manifest | `af59bbbe1fd637930ae8c7878392e4a688f651a83f4061f015ec26cbce7b3fad` |
| binding | `28e2949280ac71b3fa41adbd994fe62c76ba6a8b7d6738f301f6f6779c179d3f` |
| freeze | `743afd6a718c05f65cc9e6b4749c2e9df435080dd3e33248c0efa6c5d3703ae8` |
| 运行镜像 | `sha256:5fa4c5d0b89e2a5ebce3f72c1691b3f4238f665a01c7419aff19a7aae2df98cc` |
| 最终 build R2 | `dcff1b639f1ae3f9d9447258404025b9fb47938aaf0c37f43b347dd136b18b3f` |
| 浏览器受验 build R1 | `74b5a29e77cd088bd5a99a390330c3edd9a3c78d4c39ae9f5c2a9b69f19be0ee` |

包内 752 文件＝729 源文件＋23 导出；正式包不含私人输入、数据库或 test-results。浏览器受验应用为 `caf34d5a825716fe2ff0aaf363df0d4412c71e91`／tree `bfb9a1156931bd86225d5f220a6fed9c27a233ad`。之后仅加入已审发布器、专项测试与三份文档，R2 重建后 196 个完整构建输入和 23 个导出与实际受验 R1 逐项相同；没有把两个不同源码 HEAD 写成相同。

- 客户端最终 R2：完整应用／测试 TypeScript 退出 0，13 项纯客户端检查通过。`access/household-members-client-check-20260918-r2/result.json` SHA `874251b42d663ece57570757713369bfb95edec1155ef31660086933d36f9e5f`。此前 Root R1 的运行器三个守卫路径拼错，Node 缺 `--experimental-transform-types` 导致模块加载失败、0 项通过；R2 修正运行参数，未改产品。旧结果保留，不与此前同一套 13 项累加。
- 浏览器 R1 单次实际 7／7，通过角色变更、两目标会话撤销、重新登录、双户／普通成员／TV 拒绝、真实已提交丢回复、409、保存后读回失败、身份迟到、后台／离线及导航保护。独立脚本 `5ffd087c4cd4f979369cce8e151280d58a2b18d9`；`worktrees/household-members-browser/test-results/expo-household-members-20260917T211621366932Z/result.json` SHA `2cae6c990087227f1ec9606ca0343ac5e1b4f542db6bd53fbc17ae75293657b5`。727 tracked／23 导出／4 实际夹具前后不变，7 个临时环境全清理，零外网／页面异常。
- Root 实际逐张看完 320／390／1280／1920 宽的浅色列表与深色紧凑确认框，共 8 图，结论 `PASS_VISIBLE_VIEWPORT`。`access/household-members-visual-review-20260918-r1.json` SHA `6bb48de14a52ba544879aebc6c9125aca043c63d433ebe714688cf30144b6ccf`。320 浅色列表下方说明在内部滚动区，未做完整滚动视觉覆盖；仅覆盖本轮新控件与键盘路径。
- API 专项分轮覆盖 48 个独立用例，会话／多户兼容分轮覆盖 70 个独立用例；不是一次 118 项全量通过。首轮失败及修正留在 API 作者工作树的 `test-results/household-members-delivery.json`，另见[成员 API](HOUSEHOLD-MEMBERS.md)。迁移最终独立专项 27／27，见[迁移记录](HOUSEHOLD-MEMBERS-MIGRATION.md)；发布适配器 9 个 pytest 和实际父工具 CLI 拒绝检查见[发布适配器](HOUSEHOLD-MEMBERS-RELEASE.md)，各套数字不累加。
- 最终 Linux 实际 8 模块、227 项＝226 通过＋唯一精确 `tests.test_frontend_runtime::test_windows_junction_rejected` 跳过（`Windows junction semantics`），0 失败／错误／删选，实际 277.084 秒；JUnit 唯一集合与 collect 完全相同。116 个运行文件和 39 个已加载模块前后保持。最终 collect-only 记录 `access/household-members-collection-20260918-r1/result.json` SHA `0b8f4030a462d21f5b8afe25cef2a41c47df41c806e7e47677c7e7d6546a48b9`；`T/validate-command.stdout` SHA `d3ed381267008de9d8edb151a6fca1cf8deb27b8d56d60d0de1975f5c65fd829`。JUnit SHA `e7234dba74a3c6eae0f82db0a648390311ec7dee538d65e70fc4d4bdf8021a7e`，runtime SHA `86fd3c748d90ec1f4260b21d383f9daaf9569294a5237861255c538405e8d4b0`，validation.log SHA `c662d75ea8412a40afbc7e836b66fafec237353823093344cd2a59787e64bce0`。

九份实际工具已独立审核；`T/operator-review-record.json` SHA `cb63b6c41529266fa6d5c614e79e0e12217b4d5fa5399956958de7975cfc93f3`，binder 使用仅七算子散列的 `T/operator-review.json` SHA `24f0c4cbad8e02a2e100ae5181663600f601ca51fb801d9b2861fce1c59d6289`。这项静态批准与后续服务器实际阶段分别记录。

## 58 → 58 的结构与保全范围

本次表数不变，但 `schemaChange=true`：仅新增 `users.household_role` 列，原两位成员初始化为管理员。家庭角色与认证 `member/tv` 分开；权限不会自动扩大到个人财务、云来源或电视许可。

实际激活目录 `/opt/family-dashboard-releases/household-members-58-20260917T214815962308Z`。所有数据卷写入者及备份计时器停写后，已验证并另存 1 户／2 库完整组备份，再由固定 helper 一次迁移。原 users 五列、其余 57 张表的行／schema／序列与注册库保持；`after-migration.json` 与 `after-app.json` 同 SHA `f55fa3a646b064163144f1332ca351f06a587728caa97843e96e77a3ac7d5fb6`，随后才启动 workers／web。激活时 752 包文件、116 运行文件核对，四服务 running／零重启，public HTTPS 200。不能声称 users 完整 schema 未变，也不能把表数相同当成无需迁移。

`T/activate-command.stdout` SHA `afbdfc6ce4469fa4e522edd29ae3b357498c9b7aba760dd28f632ace2d91b94f`；该值是命令 stdout 字节 SHA，不是远端 stored activation.json 的 SHA。`T/post_readback-command.stdout` SHA `c3d9f88645a76848153498335a53ac9dceea790a0d50f50b676459a8e4e94bd0`；同样是 stdout SHA，不能与下方 stored 报告原件 SHA 混用。

post 实际核对 752 包文件（729 源＋23 导出）、116 运行文件、75 HTTPS 静态资源；24 个生成目录路径和 1 个退休资源拒绝，38 个唯一匿名接口全部 401（算子保留父版重复路径，共 39 次请求）。四服务运行、零重启；仅 app 的 health 为 healthy，其余未配置 health。环境保持。新逐库在线备份已成功校验 1 户／2 库、每户 58 表，timer active，`liveGroupSnapshotRechecked=false`；新备份 manifest SHA `73f14a2052e616724cf3b7452a42f59087f168469c29b847c52925d2359b9fde`。

post 新逐库在线备份只对已关闭备份文件使用 immutable 读取；补齐 users 投影，接受之后合法的普通成员角色，不重新设为管理员。它不是全局原子快照或 live 全组再次快照。新结构恢复须使用[角色迁移检查器](HOUSEHOLD-MEMBERS-MIGRATION.md)的 `snapshot-current/check-restored`；旧结构完整组回退使用 `check-rollback`。固定迁移及历史发布工具不可重放，不自动恢复。

## 独立审计

`D=access/household-members-published-audit-20260918-r1`。已实读 `D/audit.json`，SHA `3ccd0d1da8f5b7aed48d36be896c0321fed0283a2275c254d185c90b4be0a84d`，结论 PASS；32 份本地原件固定，8 份下载报告的远端前后与本地 SHA 一致，各阶段 JSON 与原 stdout 内容一致。原件位于 `D/remote-evidence`：`activation.json` SHA `975ead7b6828b8b787f249424f9e090344c65be02728f70fc436895c29b57c6e`；`post-readback.json` SHA `19f8490e79225a3d185eb180ca914d2d8404ed7c5e97e2118608bf14d5fc39dd`。

`D/fresh-readback.stdout` SHA `7f421f8f65a5a4d2cb48f6cdabd262bb93fb5798bd12a4ae07fb3f9bd1b29ced`；05:55:19 再次核对 752 包文件散列、38 个唯一匿名接口全部 401、四服务运行／零重启、app healthy、配置原散列及 0600、备份计时器 active。迁移独立比较七份远端 proof JSON 的既有指纹，确认仅角色列变化、初始两位 admin、旧五列／57 表／注册库保全及 after-app 等于 after-migration。未下载 proof 正文、数据库或环境正文，也未执行算子、发起备份或新增 live 数据库快照。

## 尚未覆盖

本轮只实现每户现有两位成员的基础角色和会话管理。另一个独立本地 D 连续验收已实际通过 6／6：两家庭同 ID 的私有账户、照片、地点与 PDF 隔离，显式共享，撤销另一成员两会话，旧 cookie 的 18 次读与 2 次写均 401、迟到 JPEG 不回显，重新登录后本人数据保留。其报告 `worktrees/household-isolation-chain/test-results/household-isolation-chain-20260917T213414781654Z/result.json` SHA `17c96dad0dd17d9f398c0dd899f67f483e0092af757b3bd22982a6deea2ecfbf`；Root 实际看完 3 图，视觉记录 SHA `728d2d5fefc4b5ffb869b88ed4ef3b4c6213508971e6e55c424e572c96d4211c`。730 源文件／23 导出／9 夹具前后相同，临时环境清理、零页面异常／外网。该独立脚本及其说明不在当前 752 文件发布包内，不计入本轮 7 组或 Linux 数量；该说明随独立文档合入，见[家庭隔离连续链](HOUSEHOLD-ISOLATION-CHAIN.md)。

通用注册、加入／退出已有家庭、同一用户多家庭关系与切换仍未实现；这条合成数据链不代表完整目标 D 或真实外部环境已验收。

真实本人公网新流程、真实云写入、手机原生设备及实体电视未验收；普通业务在途请求按各模块事务边界处理，不承诺撤销能取消全部已在途操作。旅行本地连续子链的分轮记录见[旅行链](EXPO-TRAVEL-CHAIN.md)，日历仅预览、不含真实云或在线 AI；它不是本轮新增通过数。
