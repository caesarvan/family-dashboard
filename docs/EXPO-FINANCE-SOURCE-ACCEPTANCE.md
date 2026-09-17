# Expo 来源导入界面：组合验收

<a id="expo-finance-source-candidate"></a>
## 本地阶段与边界

来源导入 UI 已在后续 R2 发布，见[正式发布](#expo-source-release)。下述为此前 R1 本地组合记录。固定组合 `c148699601d6234e5acc6f6e4f970b24700ccd1d`、tree `4f6a3451056ed8d2e64f3b178fa1d2aa10f83233` 已完成 Node、全量类型、构建与 R1 浏览器功能检查；12 张原始截图已由 UI 审查者逐张核 hash 并查看，`PASS_VISIBLE_VIEWPORT`，当前可见区域无阻断。本批不改后端、金额算法、依赖、表或共享规则，从财务页「更新资产来源」使用已发布的 preview／confirm／status 协议。

已由非作者审查并合入的四部分：UI／model `efdaeb0d3b623e503ebca122f7edf9e699153a32`，入口与导航 `39397e97b1a06b14c4cc8443e2bf618104dadcc4`，浏览器 `bf0cbc1c1a6172918fd056fa7659243546436895`，发布适配器 `d29f15e42e6c2f9bdae75fbd7899f34903c5faed`。这四项审查不代替最终组合或生产验收。

本地私有路径以下以 `A=family-dashboard-access`、`W=A/worktrees` 简写；原件不提交 Git。

| 实证 | 实际结果与固定原件 |
| --- | --- |
| Node 模型 | 固定真实 API `05ee6568` 的临时 Flask／SQLite 合成来源，15 passed／0 failed。`W/expo-finance-source-ui/test-results/source-import-node-final.tap` SHA `bd59a03f0fff6a3fbde9b9f7df14bc32cc1384fb7eef01db72adb97e07e2e3f1`；原作者调试 r1–r5 日志保留，不合计。 |
| TypeScript | 严格 model／Panel 定向 0 诊断；组合 `4b6d6c5aeba98386e0aafe712313a3fce2524359` 直接执行 `node frontend/typecheck.mjs` exit 0（主配置＋测试配置），其前端字节与 `c1486996` 相同。`A/expo-finance-source-typecheck-r1.log` SHA `e06b5185cf9fa8d032487267733caf2325010e36aa77dbb49fbb7d34726c23fc`。 |
| Expo 构建 | `A/expo-finance-source-build-20260917-r1/build-evidence.json` SHA `c73d2bb7d578f040472a0583a07307a6c54d4907fdb6d39f2b25fe72da0020e9`；来源为上述 head／tree，184 个构建输入、23 个导出。 |
| 浏览器功能 R1 | 一次真实运行 12／12、12 PNG。`W/expo-finance-source-browser/test-results/expo-finance-source-20260917T140931825859Z/result.json` SHA `ba01e02acccecdd6ed7643c7bdc2902356a131bdff0d1ee8e890e13a0e90fd03`。源码／导出前后 649／23 相同、clean、12 案例清理完成；0 页面错误／外部请求／生产写入。 |
| 视觉 | 同一浏览器目录的 `visual-review.json` SHA `40d6fd64e8236d8574ffed4f454d1f7954a203ead258991e0abd3d3d18cf85c3`；审查者 `/root/expo_finance_ui` 实际查看全部 12 PNG，没有重跑浏览器。 |
| 发布适配器 | 20 passed；XML SHA `04650ea3708ee861655114e2cf754375feb3cdc00b3b5f1c083facb58d6d7030`。真实父九工具 CLI 7 个未绑定拒绝、33 个坏 freeze、37 个后端字节变更拒绝通过；完整范围见 [发布说明](EXPO-FINANCE-SOURCE-RELEASE.md)。 |
| Python collection | `A/expo-finance-source-validation-20260917-r1/collection.json` SHA `cbe997970fdbd3e592cc7ddc973e16bcd7b4aee6d22c43be04cba507a777ce45`；同一冻结 head 实际 8 模块／184 唯一 nodeId，`collectedOnly=true`、`executed=false`，不是 184 passed。 |

浏览器 invocation 原件为 `W/expo-finance-source-browser/test-results/source-r1-invocation-20260917T1409303354110Z/`，stdout SHA `4f4c76f43a5390f778333a9f2b7b06f18b19d9a0ec18b2c1c0a339cb74e537bf`，stderr 空。R1 无失败案例；未重新运行浏览器或修改成功响应来取得通过。Node、适配器、浏览器和 collection 彼此不累加为总通过数；构建输入 184 与收集测试 184 不是同一集合。

## 本轮实际覆盖

真实临时 Flask／SQLite／HTTPS loopback／Edge 覆盖两条来源流程、预览零业务写、明确确认与后端重启、消费观察不改资产／账本／持仓、格式／体积／金额拒绝、真实并发冲突、提交后丢响应的精确 GET 与原请求重试、未送达时 found=false 仍未知及明确结束核对、过期与新会话历史回执、两成员／跨户／匿名／配对 TV、迟到身份、隐藏／断网和导航返回。成功业务 DTO 均来自实际 API；来源 JSON 全为合成，故障只丢弃或延迟真实请求／响应。

12 PNG 包含 320／390／1280／1920 四宽的浅色完整来源、深色紧凑消费预览及成功回执；自动检查横向溢出、长文本和两个主按钮的 44px 尺寸。独立逐图视查确认长标题／路径／操作编号换行，未知金额、零、负净额及历史回执区别可读。浅色图只覆盖列表中段，窄屏消费图不包含底部确认区，回执下方输入也未完整覆盖；不能扩称整个内层滚动页面或真实手机验收。

后台使用可见性事件模拟，断网使用浏览器 offline；到期由真实 signer 时间夹具推进，未等待真实 20 分钟。本人真实财务文件、银行／邮箱访问、新云操作、实体电视和原生设备均未验收。完整使用与恢复语义见 [操作说明](EXPO-FINANCE-SOURCE-IMPORT.md)、[入口接线](EXPO-FINANCE-SOURCE-INTEGRATION.md) 和 [浏览器范围](EXPO-FINANCE-SOURCE-BROWSER.md)。

## 当前线上父版本

父 baseline 已于 2026-09-17 21:58:49 激活、21:59:22 TLS 读回、22:01:55 独立只读核验通过（北京时间）。实际 main `0bd330a6`／source `f0317fb6`／tree `f9f14984`，镜像、archive 和 manifest 见 [发布适配器](EXPO-FINANCE-SOURCE-RELEASE.md)。独立审计 `A/expo-baseline-published-audit-20260917T135020363048Z/audit.json` SHA `86358d4a77f074f9ff581c0efdab7e3c5ef2aed4d096494658a245f7afb8ac87` 已核。

父版本实际 Linux 347 passed＋1 精确 Windows junction skip、55 张户内表及注册库保持、1 户两库备份，四服务运行／零重启，仅 app 配置 healthcheck 且 healthy；发布后逐库在线备份不等于全局事务或重新核对 live 全组快照。这些是父发布事实，不是本批来源 UI 的生产验证。新组合正式合入、freeze、九工具独立审查、Linux 和发布仍待完成。


## R1 服务器验证失败：测试提交竞态

在上述本地候选记录之后，R1 已完成正式合入、打包与绑定，但 Linux 验证实际为 **182 passed、1 failed、1 精确 Windows junction skip（184 项）**，0 errors；未进入 stage 或 activate，当时线上仍是 baseline 父版本。不能将本地浏览器 12／12 或 184 项 collection 当作本轮发布通过。

失败用例为 `test_confirm_checks_actual_session_after_guard_and_waited_lock[False-expired-spending_observation]`：非等待锁分支在工作线程提交前设置事件，主线程收到事件后又对同一个 SQLite writer 无条件提交，两个线程可能并发 commit，导致工作线程抛出 `cannot commit - no transaction is active`。这是夹具同步问题，尚未到该用例的 HTTP 拒绝与数据不变断言。修订仅让非等待分支提交完再通知，主线程仅在等待锁分支提交释放真实写锁，并断言事件后的事务状态符合分支；保留 401、真实等待和全部业务行快照不变检查，不改产品。

原件保留在 `A/expo-finance-source-tools-20260917-r1/failed-validation-originals/`：JUnit `validation-results.xml` SHA `a2570af81039a1408d809cdc90c0e55ee1a8dc3cdb6b73b3a97e87511c20d411`，日志 `validation-validation.log` SHA `1dbd2ad97a34c7efc6a0f136c4b12d44b3132e61bf150482c50f4b661644a2c8`，runtime SHA `aa0dea8507a85a21316be3ebfda08d8658d646575d3138d579b13eb2e0bfbd1f`；runtime 前后检查均 true。R1 原件和未完成的发布审计准备保留；修订后的本地定向结果与后续新 R2 Linux／发布结果分别记录，不重放 R1 算子。

修订后仅对上述用例的 12 个参数组合执行一次真实本地 Flask／SQLite 专项：**12 passed、0 failed／error／skip，9.37秒**；基线 `944a712d69375c209ec7a63fe28b3a2287df8beb` 的工作树修订字节运行前后全部 650 个 tracked 文件 SHA 相同。原件 `W/finance-import-test-race/test-results/finance-import-test-race-20260917T144005086631Z/`：`results.xml` SHA `983f287140f248025093b86595908f2482857ec0c6e0849ea9109ff25974e784`，`evidence.json` SHA `bffc1676b83530efc80b7399bf012b4b4107ad4dba685441a4e6f243c7cbdcec`，stdout SHA `2940df64882be1a99a555bfbd51ce62fdf4de81ea28fa6d72886af7bd46aba7f`，stderr 空。随后仅补本文结果说明；未重跑其他用例、浏览器或远端算子，不能由这 12 项推断 R2 的 Linux 全套或发布通过。


## R2 本地组合：修复测试竞态后重新冻结

R2 固定 source `43bddc4cdd4531bcd9ad66b5bcd2cbd4b0cbc0be`、tree `81769033c0832a4c1f2858d84c8d4beaa96c59ce` 包含已独立审查的测试同步修复 `78c34574aa02b445ad5126d1725a7a6218e50c76`。实际重新构建 `A/expo-finance-source-build-20260917-r2/build-evidence.json` SHA `e16e89bfbc3d17aef686f3f685f0f9b0f76ca950758ba7c7b0387d9e9c73ec55`，184 构建输入／23 导出；入口字节与 R1 相同，但保留新的 source／build 身份，不重绑 R1 报告。

同一未修改的 `bf0cbc1` harness 单次真实运行 **12／12 通过、12 PNG**。原件 `W/expo-finance-source-browser/test-results/expo-finance-source-20260917T144433030097Z/result.json` SHA `a11dc86cd3041e088b558050dbc8d6ce4e4e85782e5ad60ec739f230fcfc391c`；650 tracked 源码／23 导出前后相同，0 页面错误／外部请求／生产写入，12 个临时目录均已清理。调用原件 `test-results/source-r2-invocation-20260917T1444320861411Z/` 的 stdout SHA `055c7ebeef66ec207cb26a5f9207cf7adfac87e23ddede3f36b7759d7eeecf42`，stderr 空。

R2 同源 collection 原件 `A/expo-finance-source-validation-20260917-r2/collection.json` SHA `30a497bcf05a33805656c627502660035d3e72d6d5e6770f9887cd393377465b`：8 模块／184 唯一 nodeId，仅收集，未执行 Linux 验证。R1 的服务器失败、定向 12 参数结果与 R2 浏览器结果分别保留、不累加；该本地阶段尚未发布；之后完成的独立服务器验证与发布记录见下节。

R2 的 12 PNG 由 `/root/expo_finance_ui` 实际逐张查看并核散列，同目录 `visual-review.json` SHA `64574ecbee18ef68d48455eb8adad73cd8c6b6368c526f99a88c90dbf41dc205`；可见 viewport 无阻断。四宽长标题／编号换行、零／未知／退款负额可读；手机内层滚动的确认区等未全部覆盖，不外推本人真实财务、云或设备验收。

<a id="expo-source-release"></a>
## R2 正式发布与独立读回

北京时间 **2026-09-17 23:11:09 激活、23:11:48 正常 TLS 读回、23:15:17 独立只读复核通过**。
财务页「更新资产来源」已实际上线；后端、依赖、55 表结构和既有分享范围保持。
R1 测试竞态失败未发布，其原件保留；R2 使用全新工具目录，不重放 R1。

| 身份 | 实际固定值 |
|---|---|
| main | `e0e3beb33b1b419dd68583e89d03df8cd97ed25a` |
| integration / source | `3c113a9fab65910fd0a938e0105e142a058ce2e8` |
| tree | `4ea5a46328f16af86d814d009ac561fa2eadafed` |
| image | `sha256:6b886eb5123916673d8c9ac38810390cb7ec6b46db5941c651602835769cab68` |
| archive | `93426c1c8feac4c8f8c8f2626c74637ed9d1ba6fb884da276cbab49393fce5f5` |
| manifest | `f11d9d58971fa9bcf91ac2a53f19ad23c426fbd833f9f6b1a575c0dfb4e1f7c0` |
| freeze | `57d5eade107e0d867d5486fdf67712d1e66962e9505b39b00b84c67b2cf0709f` |
| operator review | `14fbcf1c3305dc0f9cc0bfa8228778233687bdbc2dd5aa0df3b61ee0e05512cc` |
| bindings | `6a0831c8055172b1c13d390c9ba88380b29de75a8be6cb19c3ddeb814e14fe7b` |
| release | `/opt/family-dashboard-releases/expo-finance-source-55-20260917T151009177797Z` |

实际 `T2=A/expo-finance-source-tools-20260917-r2/` 完成 build、validate、stage、activate、post_readback 各一次。
Linux **184 项：183 passed、0 failed/error/deselected，1 项精确 Windows junction 跳过**；
八模块 nodeId 集与 R2 collection 一致。37 个已加载模块／114 运行文件前后匹配固定镜像。
JUnit 原件 SHA `275e90b3f38d54fbcdb54365df266b274d33d9600699fadab468ebfeaf506459`，
runtime SHA `37d860dae34fdb72605636c5a75756974e1107fa34132b9166d67ede6cdc2144`，
validation.log SHA `40e9acc6d51bbb2011a62f78c4814523142281c8c7c4f7c4df6ff467dea98450`。
R2 构建／浏览器到最终 tree 只有本文的已审 Markdown 增量，所有可执行源码一致。

包内 672 文件＝649 源文件＋23 Expo 导出；184 个构建输入逐项绑定。
正常 TLS 核对 75 项静态资源、24 项生成私有资源拒绝、1 项退役脚本拒绝，34 个唯一匿名 API 均返回 401。
`/app`、`/app/finance`、`/app/tv` 与 `/classic` 入口正常，电视转向及经典回退保持。

激活停止所有写入者，完成 **1 家庭／2 数据库**的完整停写备份。
原 55 张业务表、`sqlite_sequence`、注册库两表的行及 schema 在新 app 启动核对时保持。
`before.json` 与 `after-app.json` 原件 SHA 均为
`19caa52de52566e6b1d1c5f382396ad5c08923339f2dc4efb3a0f3a568b5c69c`；
preservation SHA `9b8c0b9b4a06a13554fe04eaea9580ea0fa0fec6585e922f9a4ba1e09c407bfc`。
环境散列和 0600 权限保持；四服务运行、零重启，app 健康，其余服务没有配置 healthcheck。
发布后新一次逐库在线备份 `manifest-20260917T151144242832Z.json` 成功，SHA
`a4d7e5d0a806cbcea6cf66d7206457b7dc475518d04bec50e5c96ae70f43b78d`；
它不是跨库全局原子快照，也不代表再次核验运行中的整组数据库。

独立审计目录 `A/expo-finance-source-r2-published-audit-20260917T150126310069Z/`：
13 份允许原件经两次远端散列与本地散列比对，完整来源／阶段／保全链通过；
仅只读采集，不下载数据库或环境内容，不执行发布或备份算子。
`audit.json` SHA `81df023e4d0d31b70aaa64304d8e77df8686b4b66b67436bd30f2c0b27120390`，
`readback.json` SHA `f334b1c6792e23a8e0af30271f2b941ffdee59d2d53c206d647978d4f8496411`，
fresh 原件 SHA `2527555204004f7a52207248e2d2a76f6b8ab8fa8b532ca6602981109d597856`。
服务器原始 `activation.json` SHA `e42e3c00523d126d84e596ce16676c7eb805cb66d0e838e384c948ab16d79cff`，
`post-readback.json` SHA `5a98f925673683cee9058e0c3a07ef78f1aa175f68f3b060fe0d2e69d4ddbcbe`；
这些是实际远端文件散列，不能与命令 stdout 的 JSON 文本散列混称。

后续纯文档提交不改变安装包身份。本人真实财务输入、真实云操作和实体电视仍未验收；
可见区域截图与临时数据库流程不能代替这些验收。资产账户及历史估值在独立候选继续开发。
