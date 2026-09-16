# 验证记录

## Expo 财务发布：2026-09-17 04:26:46

本轮将共同资金、本人完整账本、账单／订单导入、来源追溯、付款／退款／重复核对和月预算迁入 `/app/finance`。主页面、导入、后端回执、迁移、浏览器和文档由独立分支／worktree 作者实现，经非作者审查、修订和组合验证后合入 main。本机打包／绑定助手与服务器操作脚本也经非作者审查。北京时间 04:26:46 实际激活，生产为 54 张户内表和两张平台注册表；04:41:46 正常 TLS 最终读回通过。发布后的本地文档不改变已安装源码、构建或 manifest。

### 冻结来源与构建

| 项目 | 实际身份 |
| --- | --- |
| main | `a2081051657647564345a54b61662682ff4dd663` |
| integration／最终受验应用 | `2d08258fc67388e4de237747eb35db3fe3b0d8cf` |
| 同一文件树 | `9508cddb1b4cdde1caf70c268673110a0bd50194` |
| 本机最终构建目录 | 私有 `family-dashboard-access/expo-finance-build-20260917-r3/` |
| build-evidence SHA256 | `ffa4afc01046ed577cc43204a09350497531e22a6ba5fbb61a49ff3052b76694` |
| Expo 入口 | `entry-08fd53f0b66e839ec2d8ea5fc7d55b6d.js`，共 23 个导出文件 |
| manifest SHA256 | `f5a49949e6d868533392f64fa46c4042a85df635b2f8123b3f05076a7d619976` |
| 源码包 SHA256 | `656b74fa4036113de41d7c800390835ba12062f52bbce2834f5545fae073966c` |
| app／sync／media 镜像 | `sha256:4433d1d5c97ec4ed4a1336c2402b0fae121a04e092050ff9eb2821ac61fa4798` |
| 固定父镜像 | `sha256:7f2b301ccf9577c1ec8c61fd52dd152484809cbf1e8e612d81dd5d39887e8dcf` |
| 原 manifest SHA256 | `11da3a4bd52d4233629b7df26884831ff19c314ea2a1f3f9c8da7310b967d718` |
| 发布目录 | `/opt/family-dashboard-releases/expo-finance-54-20260916T202549009688Z` |

完整 typecheck 通过。Node 两模块 `test_expo_finance.mjs`／`test_expo_finance_import.mjs` **19 项通过**，覆盖严格金额解析、八字段整数分与百分比契约、逐笔来源、导入预览及同请求恢复。Node、Windows、浏览器各自记录，不相加为一次全套。

### Windows 后端与迁移

Windows 16 个后端／迁移／运行模块 **418 passed，0 failed／error／skipped，86.11 秒**。实际执行来源 `9ed5d19e035ab40d9ba3a56b4913c73c6e1935c5`；到最终候选仅两份前端 TSX 和浏览器脚本改变，后端及这些受验模块字节保持。JUnit 原件在私有 `worktrees/integration/test-results/expo-finance-combined-r1.xml`，SHA256 `4053714ac748616d8420eda5002ffd6b9e172bc29d13ae531490853e8f76d3a1`。

53→54 迁移、文档完整恢复及历史迁移的独立组合 **45 项通过**；该 45 项也包含在上述 418 项中，不重复累计。JUnit 在私有 `worktrees/expo-finance-migration-test/test-results/finance-receipt-migration-r1.xml`，SHA256 `c2fda9190568380009129347f3c23c5365709a0dc3241d75eddc66d5e0cf48ab`。迁移只新增 `hub_import_receipts`，既有 `hub_imports` 七列不变，旧记录不回填来源；实际生产备份与迁移必须另按 [回执迁移和完整恢复](FINANCE-RECEIPTS-RELEASE.md) 执行。

### Linux 首轮拒绝与精确平台例外

第一轮同镜像实际执行 418 项：**417 passed、1 skipped、0 failure／error、0 deselected，130.16 秒**，JUnit 计时 130.125 秒。唯一跳过为 `tests.test_frontend_runtime.test_windows_junction_rejected`，原因精确为 `Windows junction semantics`。pytest exit0，但当时发布检查要求零跳过，因此 `allPassed=false`，在 validate 阶段拒绝，没有 stage、激活或生产数据／配置变更。加载的运行代码与测试支持文件前后核对通过，不能把测试 exit0 写成首轮发布检查成功。

首轮私有原件保留在 `expo-finance-linux-r1-proof/`：`validation.json` SHA256 `53850fb4b73b202d2891135237e8ba64d40db850d7d734f1a64e72da3bd696f0`，`results.xml` `b1c2ed47186dd963b1ed7518c7920687df7883b2eb7e6aa62944b1f16006432e`，`validation.log` `5cf5db14f880fe51b99f2cb4858c97f0662a96b3923ab46dcbcfb72d47abb9b7`，`runtime.json` `c873bc00a23ea8f103a30f30edc910b094e7d36be2011116ec097505dbda80d5`。原 `expo-finance-package-20260917/` 保留该未激活尝试，不覆盖失败记录。

修订在新的私有 `expo-finance-package-20260917-r2/` 与操作目录进行；应用源码、归档、manifest、Expo 构建和实际镜像保持同一身份。发布验证经非作者审查后只接受上述完整测试身份及精确原因的一项平台跳过，仍拒绝其他跳过、失败、错误、少跑或取消选择；不是忽略任意 skipped。重新完整执行后实际仍是 **417 passed、1 项精确平台 skipped、0 failure／error、0 deselected**，总计 418 项，JUnit 125.980 秒，`allPassed=true`。Windows 418 项全部通过仍独立记录，不能把 Linux 写成 418 passed，不能累计两轮或两平台数量。

r2 原件在私有 `expo-finance-package-20260917-r2/`：`validation.json` SHA256 `3e676a7035011cb946ff647d8db4634bb8bd03be7c7ccbfe33121e2c438f4a9f`；`validation/results.xml` `b8adef5afad6a0c825594520941e185381b05915fce6f7b3159b03a046c34e01`，`validation/validation.log` `3993f4c5966b817791efe7912b7a0e43878675a1f771b803288c7e996b019c38`，`validation/runtime.json` 与首轮运行来源报告相同。三份验证原件已下载并按报告逐 SHA 核对，实际 XML 的数量与唯一 skip 也已读取。

### 实际生产迁移与激活

北京时间 **2026-09-17 04:26:46.943695**，`activation.json` 报告 `completed=true`，SHA256 `04cc60cc4e91217696616f42dbfeb84d10dd12ec54665b7ea7d9c3bcc7a80221`。实际源码 486 文件、运行输入 112 文件、Expo 导出 23 文件，安装身份见上表。原源码、环境和固定镜像已保留；停止 web、备份定时器及全部数据卷写者后，对实际 **1 户、2 库**完成组备份，`backupCheck.groupVerified=true`。

迁移前核对原 53 表与平台注册库，迁移仅新增空 `hub_import_receipts`，全部既有行、schema、序列与平台注册库保持。安装新源码且原配置保持，新 app healthy 后完整 54 表组再次核对，`allExistingDataPreservedAtAppStartup=true`；`after-migration.json` 和 `after-app.json` SHA256 均为 `854f1a065d592c027a5516ca93c71b930fb1d95199cc19b433ffb2b55e15ebad`。随后才启动 worker、web 和备份定时器。数据相等限于这些核对时点，后台恢复后的正常更新不属于永久不变保证。

该激活确实执行了生产 DDL 迁移。报告继承的 `productionWrites:0` 是准备阶段字段，不能据此说激活没有生产写入。后续发布必须重新绑定实际 54 表基线，不能重放本次 53→54 或固定旧 manifest／镜像的操作；包含后续真实回执的完整恢复按 [恢复指导](FINANCE-RECEIPTS-RELEASE.md) 核对。

### 首次读回失败与最终独立 r3 读回

原 r2 `post_readback` 在入口资源、TLS 与匿名检查后，对 live `/data:ro` 作结构快照／核对时报 `unable to open database file`，未形成完整通过报告，该次备份 service 尚未运行。诊断为运行库采用 WAL、缺少侧车时只读挂载无法完成该打开方式；这是读回工具失败，不是已完成的业务迁移失败。原七份操作绑定、激活报告与失败现场保留，不覆盖或重放原激活。

独立 r3 工具位于私有 `expo-finance-post-r3-20260917/post_readback_r3.py`，SHA256 `09c32314b68f1a135bc9f613daa3a02bbc74b8cd4aa35486c5abbb8335383d35`，经非作者审查后执行。作者合成检查最终 27 项通过、exit0；首次测试驱动因连接未关闭导致临时目录清理失败，显式关闭后重跑通过，原失败不作为完整通过。既有真实备份清单格式另经只读核对。r3 使用同一源码、运行文件、归档与构建，不再部署或迁移，只执行原计划的新一次备份 service 并读取证据。

北京时间 **2026-09-17 04:41:46.934850** 正常 TLS 最终读回通过：486 源文件、112 运行文件、75 项 HTTPS 静态资源匹配；24 个内部生成路径及 1 个退役资源拒绝，19 个匿名 API 均 401，包含本人导入回执。四服务 running／restarts 0、app healthy，`envPreserved=true`；新版与经典入口均已核对。原件 `expo-finance-package-20260917-r2/post-readback-r3.json` SHA256 `02a9104725599554a103acce5ff653867212f763d5133b3905bae7c296339332`，本地已按 SHA 下载读回。

本次备份 service 新 InvocationID 为 `43b2057bf08547f5bd5736eaaafb810d`，结果 success、exit0，timer active。只核对该次产生的 `manifest-20260916T204143327693Z.json`，SHA256 `d3bbdb40cf48dce4ac591ff945066b0ccd05ad9bb78ff9fce989d40f7d100bdb`：完整 1 户、2 库，家庭 54 表、平台注册库两表，组映射、不可变备份文件散列及结构可读性通过。**每个数据库分别进行在线备份，不是跨库全局原子事务，也不是正在运行的多库全组快照**；报告明确 `liveGroupSnapshotRechecked=false`。启动时 54 表组保全与当前备份核验是两个不同证据，不把它们写成运行数据自激活以来始终未变。

集成人还用已安装源码的 `verify_addition` 对下载的迁移前快照与 after-app 原件独立复核，结果与原迁移报告一致；after-app／after-migration 相同，原件哈希与绑定匹配。私有同目录 `publication-index.json` 列出 22 份发布原件，SHA256 `cfbf26db8f29ff1ac0266869f21e6f72e86d1e4d31f3a93322e7f97be8392d60`。本人真实财务、真实云和实体电视验收仍为 false，不由服务器正常 TLS、匿名拒绝和备份通过替代。

### 最终真实本地浏览器

真实临时 Flask／SQLite／Edge **21 项全部通过，19 张截图**，包含 320／390／1040／1440 四宽。报告在私有 `worktrees/integration/test-results/expo-finance-20260916T195435212799Z/result.json`，SHA256 `4f6bc3364398e6bd13c57d1b22a9ca6e9fe21ac6a84b85f80e42e301ce01d56a`；实际执行 harness SHA256 `4bcb31d3a4acf329569f8db1f51ba4e898dd2031625c1badb30c4e718bd92e95`。应用来源为上表最终 integration，源码和构建前后保持；`pageErrors` 与 `externalRequests` 均为空。

实际覆盖：

- CSV 与 XLSX 选工作表、金额列，读取新文件时立即清除旧确认令牌，空文件替换，错误行整份拒绝，跨月入口，以及重复／冲突保留原值和首次来源。
- 导入服务重启、已提交和未提交响应丢失；GET 暂无回执后，真实预览过期重试仍保留原编号，迟到的原请求实际提交后再次 GET 恢复。不以模拟成功响应替代业务保存。
- 551 条完整账本的月份／搜索／分页及快照 409；真实订单／付款／退款／重复关系预览、确认、撤销，净支出 170→70→170；预算、八字段共同资金整数分与 409；撤销活动关系后删除当前详情，再刷新回到账本。
- 本人成员、另一成员、独立家庭与配对电视隔离；后台／离线隐藏、恢复重验，以及迟到私有响应不能跨身份显示。

财务文件、家庭和凭据均为虚构，业务操作落在独立临时数据库，未连接实际金融平台或写生产。四宽截图不是四台物理设备；浏览器隐藏事件与断网场景也不代表所有真实浏览器生命周期已穷尽。

### 保留的失败与修订

前期主页面 `f3a1498` 的非作者审查发现共同资金将分当元且漏八字段中的两项，以及当前详情已删除后 GET 404 无法恢复。`fb977c6` 修正完整整数分 DTO 与账本恢复，`792e396` 再补回 404 身份重验的原 epoch，避免迟到旧请求关闭新详情；修复后重新审查。真实共享资金验证确认 1,000,000 分显示为 10,000.00，输入 123.45 提交为 12,345 分，其余字段与比例保持。

以下三次未完成浏览器运行保留原件，不把其部分通过项重复加到最终 21 项中：

| 私有目录 | 结果与修订 |
| --- | --- |
| `worktrees/integration/test-results/expo-finance-20260916T194525271556Z/` | 第一轮应用 `9ed5d19`、无 r 后缀构建，共同资金通过；图标字符进入按钮 accessible name，随后导入定位失败。按钮补明确可访问标签后重新构建 r2，应用 `2a6206c` |
| `worktrees/integration/test-results/expo-finance-20260916T194851287829Z/` | r2 前 4 项通过；harness 使用文本 `.last` 误点同名支付类型段选，改为明确 `menuitem` 选择 |
| `worktrees/expo-finance-browser-fixes/test-results/expo-finance-20260916T195035371030Z/` | r2 修订 harness 前 4 项通过；Paper Menu 真实选项稳定前被卸载，工作表选择无法完成。未确定底层触发原因；改用标准 Paper Dialog／ScrollArea，保留身份与禁用检查，重新 typecheck、构建 r3 并跑完整最终浏览器 |

### 视觉与交付边界

本轮查看最终 19 张截图中的 15 张，集成人另查看手机导入确认和桌面账本。所见区域无阻断性水平裁切或不可读内容；手机导入记录、金额、原编号与确认按钮完整，四宽退款确认窗稳定不透明且关键操作可见。AppShell 的内部滚动使 `full_page` 截图未必覆盖整个内部页面；部分手机账本／预算下部没有被截图展示，不宣称全区域视觉验收。

资产、投资与来源报告仍有经典入口；当前支持工作表和金额列选择，任意日期／标题／币种字段映射尚未实现。本次没有验收真实平台账单、新的本人云操作或实体电视。新镜像 Linux 验收、生产 53→54 激活、正常 TLS 最终读回和逐库在线备份分别记录；本地通过、服务器检查与本人真实操作验收不互相替代。

## Expo 账户与同步发布：2026-09-17 03:01:51

本轮按用户再次指定的当前 [Expo 官网](https://expo.dev/) 风格，将账户主入口迁入 `/app/connections`，包括两家授权、来源搜索／分页、共享范围预览、主清单、逐来源状态、失效同步单独停止及断开确认。前端、后端、浏览器和接线分别使用独立分支，由非作者审查后组合；发布工具放在独立私有目录，并经非作者审查。

实际安装 main `a6099c9c2e7d8e8c64aa7a8f911b00107945a6ab`／integration `549e23d842fab92569394cc2ba55efac219bf79f` 同树 `87f47c3414f7b663f64bdf3613d2e636d055edd9`。实际最终浏览器执行的是 r2 应用来源 `0965b6b0488952cf43e8332005c5f1f1bf92d537`／tree `c732048758827225a6f0846bb2ed46ac4c962c97`、构建证据 `dc21fc7842b07649801e0c1441bd00cee911c37e96e3a1e9ce4543df4a828bc7`。随后只有 harness 修订进入源码；实际重新构建 r3，证据 SHA256 `e7d76d4fc0ebb8571a5dce1ab0a88483f548d0d71a2f5165f6ea670fac69879f`。独立检查 r3 的全部 **136 个输入与 23 个导出文件**均与 r2 相同，因此沿用该实际浏览器验证，不宣称 r3 又执行了浏览器。

真实临时 Flask／SQLite／Edge **18 项检查通过，已包括 320／390／1040／1440 四宽**：安全回调消费、配置与连接真实分层、本人账号列表、两家绑定按钮、键盘与明确共享选择、只读任务拒绝、主清单、真实 worker 成功／失败／恢复、15秒轮询保留输入、真实409核对、来源取消及丢提交响应只读确认、后台／离线隐藏、失效账户不发现云来源即可停止同步、未发现旧来源保留、重新授权提示、断开丢响应恢复、成员切换与同成员ID跨户迟到响应、第二家庭及配对电视拒绝。

最终原件在私有 `expo-account-browser/test-results/expo-accounts-20260916T183546659269Z/`：`result.json` SHA256 `3c174d1de32787db6e072dbf93cac7faef3f52389e133c75300f56ec2912d2b3`，执行 harness SHA256 `647c1fc36db4a69c5138833d774679f4c217e46722fa4604cb519f6c339275dd`；没有 failure 键，0 pageErrors／externalRequests，源码与 bundle 前后保持。记录18张截图，作者查看全部；8个保存／断开对话框在动画完成后 opacity 为1、浅灰背景 `rgb(248,248,250)`、圆角24px。另有首页390／1440截图，root核对首页手机与桌面及账户示例。`acceptance-review.json` SHA256 `d4c80e11e1143b45e2f49dbdccba9d0c8e0e4e9c9392dd180ff58327f4d52797`。最终 harness 之后另有一行异常路径 `passed=False` 报告守护修订，未再重跑业务；最终有效原件本身不存在异常键，不受此报告守护影响。

两家授权按钮确实通过应用生成 PKCE 授权地址，但供应商文档导航在浏览器被明确拦截为 HTTP204，未连接真实云、未完成本人授权。其余业务响应来自实际临时 API，丢响应场景先获取真实已提交响应再丢弃；后台场景注入 document.hidden／visibilitychange。虚构账户、临时回环HTTPS证书、SQLite和会话校验不是本人公网浏览器、真实云授权／长期同步、原生安装包或实体电视验收。

Windows 在 integration `0bb7af6` 对七个模块执行 **242 passed／0 failure／error／skip，152.44s**：`test_account_source_version.py`、`test_cloud_accounts.py`、`test_cloud_review.py`、`test_google_photos_oauth.py`、`test_sync_health.py`、`test_member_sessions.py`、`test_expo_account_navigation.py`。原件 `integration/test-results/expo-accounts-combined.xml` SHA256 `687dc4959c43f06eabb80df46bcf5f9d692e96ef6027d9e7163c9f951947fe25`；从该来源到最终 integration 的相关 Python 与这七份测试字节相同。Node 与最终镜像 Linux 的结果分别记录，不相加为一次全套。

Node 在来源 `50d110b05a79777cc01bb2d92b61e838d41e0225` 执行 `node --test tests/test_expo_accounts.mjs tests/test_expo_photos.mjs tests/test_expo_auth_navigation.mjs`，终端实际报告 **28 passed／0 skipped**，没有另外保存 TAP 原件；三份测试与相关 helper 到最终来源无变化。`npm run typecheck` 在独立 builder 来源 `50d110b` 与导航修复后 `0965b6b0488952cf43e8332005c5f1f1bf92d537` 均通过。r3 实际重新构建且逐文件与 r2 相同，但没有声称 r3 又单独执行 typecheck。

### 本轮失败与修订原件

下列目录均在私有 `expo-account-browser/test-results/`，各自保留原 `result.json`；部分检查不计入最终18项，也不合并成额外通过数量。

| 目录 | 原件 SHA256 | 结果与修订 |
| --- | --- | --- |
| `expo-accounts-20260916T182143166048Z` | `912354d17ba93748fa506bef92f17aaece6a48bb74dacdda1a563699a8fe63c5` | 产品失败，0项；r1 `50d110b` 在导航根挂载前尝试消费授权回调，出现白屏和 Router 错误。等待根就绪订阅的实际修复后，重新构建 r2 |
| `expo-accounts-20260916T182531060320Z` | `6ba8feeb47e0bd2f96ac561863615eb1eb4a3eb75491128761ecf61b183dbe99` | harness生命周期失败，2项；unroute与尚在处理的供应商文档abort竞争 |
| `expo-accounts-20260916T182746833492Z` | `773494b5c524ffab053feef2a183987668e1bf0dafbd9156663f561d0a0a6d87` | harness生命周期失败，2项；Chromium被中止文档的错误导航与返回竞争，改为仅供应商文档HTTP204阻止外网访问 |
| `expo-accounts-20260916T183008941257Z` | `86fe1d8e78a24454cb81cde3e64007d500ee441da835731aafddf2756e3106de` | harness等待定位失败，8项；通用页脚先于重新授权状态出现，改为等待准确状态和可用恢复动作 |
| `expo-accounts-20260916T183155170060Z` | `7eabf89e585bcbb1111933e54a4cf72963cd86b913bb2ee67f1a8b22b28aad22` | 18项交互通过，但确认窗截图拍在入场动画中，不作为最终视觉验收；显式等待不透明对话框后完整复跑 |

### 第一次 Linux 镜像验收未通过

私有 `expo-accounts-package-20260917/` 保留第一次真实容器验证：242 项中 **169 passed、73 setup errors、0 assertion failures／skip／deselect**，199.19s。检查原 XML，错误由54个 SQLite `database or disk is full` 和19个 `No space left on device` 构成；隔离测试的128MiB `/tmp` 耗尽，宿主仍有可用空间。加载来源与运行文件哈希在测试前后均一致。runner 在 validate 阶段停止，没有 stage、激活或生产数据／配置变更；这些部分通过项不作为完整通过。

失败报告 `validation.json` SHA256 `27fe3101126407d402b602ede2ed056d50c2442ea7a358d722d4e18942473f4a`；原日志 `validation-failed-original.log` SHA256 `b106e4f0b50572f9dab4dc90904d06e10152d0e36ab5bdeb7af4e0a76f257bff`；XML `validation-failed-results.xml` SHA256 `f54f2c67429d05bf62b68ae0c6e59cb523d495cc8eeeae679b158ea14339543e`；运行来源原件 `validation-failed-runtime.json` SHA256 `53303ab67efc357f694af492c352657a85aea6f18834dd4181e38a149db4078c`。后续另建 `expo-accounts-package-20260917-r2/` 与对应私有操作目录，保留相同源码包、manifest 与构建证据，只将隔离验证 `/tmp` 上限改为256MiB、内存上限改为512MiB，经非作者审查后完整重跑，不修改应用、数据或测试选择。

### 最终 Linux 验收与生产发布

`expo-accounts-package-20260917-r2/` 在同一实际镜像完整执行上述七模块，**242 passed／0 failure／error／skip／deselect，269.12s**；原日志与XML均已读回，XML计时269.089s。容器使用 `--network none`，没有生产数据卷，运行代码和测试支持文件在执行前后逐SHA保持；测试代码从独立只读支持目录加载，业务导入仍来自受验 `/app`。这是第二次完整执行的结果，不与第一次169项或Windows结果相加。原件 `validation/validation.log` SHA256 `97d3e0255c4593ac5e53a27c3db13a896c5684cafbae1bdea04b6449742a1988`，`validation/results.xml` SHA256 `8d8e76d765708e9bab8658c611e87368d475b89a6b81392aa38579d78e8bd9ee`，`validation/runtime.json` SHA256 `b8c6d1bac6f808b174eb1e71433cb5df5f0baee90e10d462e79189e7838a6218`。

北京时间 **2026-09-17 03:01:51** 激活、**03:02:05** 正常TLS读回通过，runner exit0。固定实际版本如下；这些发布后文档没有重写已安装manifest或构建证据。

| 项目 | 固定身份 |
| --- | --- |
| main／integration | `a6099c9c2e7d8e8c64aa7a8f911b00107945a6ab`／`549e23d842fab92569394cc2ba55efac219bf79f` |
| 共同 tree | `87f47c3414f7b663f64bdf3613d2e636d055edd9` |
| manifest SHA256 | `11da3a4bd52d4233629b7df26884831ff19c314ea2a1f3f9c8da7310b967d718` |
| 源码包 SHA256 | `e0b3490e2662f5259c84331ab1c7e88e2df81d27ad644ee3abdffc6229a18c59` |
| 实际 app／sync／media 镜像 | `sha256:7f2b301ccf9577c1ec8c61fd52dd152484809cbf1e8e612d81dd5d39887e8dcf` |
| 继承的固定父镜像 | `sha256:87c442df6f8a03a6ee74846338621dba849ac09f2907506d182a53aea0b3abc4` |
| 旧 manifest SHA256 | `d21b3840cb284b2ea680018d4895fa3767a079008e0fdca8035e4965e7bfead8` |
| 生产发布目录 | `/opt/family-dashboard-releases/expo-accounts-53-20260916T190101969525Z` |

实际1户、2个数据库完整备份，53张户内表及平台注册库的行／schema／序列在新app启动时与停写快照相同：`before.json` 与 `after-app.json` 均为 `5994e24c6a0ff2d00188479142f4e2aacfb7126179c6a949136bd37336520ce9`。原配置、依赖、Dockerfile、Compose和Nginx保持，无迁移；旧源码、环境、镜像和完整备份组另行保留。数据相等仅说明启动核对时点，不把后续worker正常更新当作数据不变。

正常TLS核对 **474源／112运行／75公开静态文件**；`/app/connections` 等Expo入口与经典入口通过，24个内部生成文件及1个退役JS拒绝，包含 `/api/accounts` 的 **13个匿名API均401**。app／sync／media／web均running、restart0，app healthy；备份service success、timer active。公网认证账户交互、本人真实云与实体电视仍未在本轮验收，原生安装包没有交付。

五份报告及完整发布索引位于私有 `expo-accounts-package-20260917-r2/`，索引 `publication-index.json` SHA256 `910243343fc3d4b5be8ec67fb074fb5011147ef369dd10fa37fb2bce2466e99c`：

| 报告 | SHA256 |
| --- | --- |
| `build.json` | `de3c92454bdea30aeaaa39bd9ccd87cef06fcb8e09ffa6abf57f2692398408bd` |
| `validation.json` | `634d18187dab86179dbc66ffb846ed0caa553bda98fe839ec3d935578fcc41e2` |
| `ready.json` | `033f9ebd8eff56c3ff22d5f11e4acd54c267c9ebb592565f8bed6a33287229b5` |
| `activation.json` | `9c242cc1ac4dd714e3b361521dd2a2f81cf9f7feefad6d8f9bea346fbd6a53ea` |
| `post-readback.json` | `d148b0abdc95dc3478909ef6054678b5cd40bf5f3508037428128ad4a0033826` |

操作绑定当时旧manifest与镜像，成功后不可重放；下一次部署应重新核对当前53表基线。

## Expo 足迹地图与旅行相册发布：2026-09-17 01:47:27

实际安装 main `7ec8c305bbf0ab0e85aaf62d70e7c571881a964f`／integration `9c63f9da262d8c690a3554931f78c3b6824d971e` 同树 `adf7dfa10bbac51ceff95edbfbf9aff3adc3a032`，01:47:27 激活、01:47:42 正常 TLS 读回通过。实际浏览器使用 r3 导出：来源 `0c533e789eb3d2b74704a9e155bcabb02f4a3e63`，tree `836e801c36d04ed742d71a47af094f8c807508da`，构建证据 SHA256 `c3b7d7e3d02dee9671ab068c9268cd649bbd6b9043f3d4b16d2bc09588e4b7c8`。

后续测试入口维护提交 `a053865` 合入 integration `9c63f9da262d8c690a3554931f78c3b6824d971e`／tree `adf7dfa10bbac51ceff95edbfbf9aff3adc3a032`，并实际重新构建 r4，证据 SHA256 `1315e96ea0355f3a892ee3d375bef341d1993379ea7110534bdfa332d87d8794`。r4 的全部 133 个构建输入和 23 个导出文件 SHA 与 r3 完全相同，因此继承下方浏览器证据；没有声称浏览器对 r4 再次执行。应用代码未因测试入口维护而改变。

真实临时 Flask／SQLite／Edge **16 项检查通过，已包含 320／390／1040／1440 四宽**：私有地点保存、键盘明确到访、后台慢请求时保留输入、真实 409 重核、创建提交后丢响应用原 requestId 恢复、删除墓碑及应用重启、共享隐藏／粗化投影、离线隐藏、全部筛选与第二页往返、只读相册 24+2 分页与详情、旅行读取中返回及过期响应丢弃、照片与地点分别撤权、双家庭隔离、切成员清理及电视拒绝。源码与 bundle 前后保持，没有页面异常或外站请求。

最终原件 `expo-map-browser/test-results/expo-map-20260916T171820315770Z/result.json` SHA256 `07a883e8a1bdb639745c013077ea0b248028e34b06bf4fcb589e7487df902ce3`；执行 harness SHA256 `ddf6653a970cefc72f20d5f428debc4af1f6a0e3752c1dc3b4b786e97d9ed4ce`，保存 16 张截图。使用合成地点／照片，真实 Cookie、CSRF、SQLite、净化加密和媒体接口；后台采用页面可见性事件注入，网络场景延迟或丢弃真实业务响应，不替换业务 API。0 次生产写入，没有真实 Google 或实体电视验收。

非作者实际查看全部 16 张最终截图，确认窄屏卡片可操作、桌面列表／详情并排、单行名称输入高度正常及四宽无横向裁切；同目录 `acceptance-review.json` SHA256 `0b2f560830cbf2cef683959a157fa78240a27fb64691696e52f020489f39fb2b`。最后一次 r3 重跑覆盖字段高度修订，前一 r2 通过记录不与最终 16 项相加。合成缩略图为单色夹具，本地回环 HTTPS 接受临时测试证书；不等同于生产域名、真实照片或完整应用验收。

root 另执行 `node --test tests/test_expo_trip_photos.mjs tests/test_expo_photos.mjs`，记录 **18 passed**；对应辅助模块到最终来源保持。审查记录 `expo-map-reviews-20260917/root-helper-gallery-review.json` SHA256 `3aef96952698330d7c7ee9b49859f1e52a917e1bd689c960640b54ea60565817`，未另保存原始 TAP 日志。此项、实际浏览器与后续镜像 Linux 分开记录，不相加为一次全套。

第二轮实际新镜像 `sha256:87c442df6f8a03a6ee74846338621dba849ac09f2907506d182a53aea0b3abc4` 内 `test_journey_places.py`、`test_journey_map_integration.py`、`test_household_media.py` 三模块 **142 passed，0 failure／error／skip／deselected**，运行文件前后核验通过。原件 `expo-map-package-20260917-r2/validation.json` SHA256 `8c38cfc1433f3d7bea657a086cbe35c00fe06a6f4de13cdba0cdbaca0db73d38` 绑定实际日志、JUnit 和运行文件证据；此执行不操作生产数据。

首轮真实浏览器仅完成 1 项检查后失败：390px 下地图后的地点列表／详情卡片因纵向布局使用 `flexBasis: 0` 而塌陷，按钮虽在可访问树中但不能正常点击。原件 `expo-map-browser/test-results/expo-map-20260916T170638632218Z/result.json` SHA256 `4f38c3399da3c98e6a50c452e8ff93c25badb60968380d23679304a19fc73741` 保留。修订恢复窄屏自然高度，并改善世界轮廓对比度、立即离线隐藏和旅行读取期间的返回操作；重新构建后的结果另行记录，不把初轮诊断计作验收通过。

两次中间执行各完成 8 项后因 harness 的重复标题定位及重复处理已完成路由失败。原件 `expo-map-20260916T171053890972Z/result.json`（`4702581756fb2f55bf06e96e6bee3ec7533bca90d62f25d8e8d3972251ce54d4`）与 `expo-map-20260916T171213524544Z/result.json`（`1a724309622e010d78af5480e40520545dda482c6ad5233ac785d409a53c3c05`）同在上述 test-results 下保留；只修测试定位／响应释放方式后完整重跑，没有放宽业务断言，也不将部分结果与最终 16 项相加。

第一次新镜像 Linux 执行 **141 passed／1 failed，169.57s**，发布停在 stage／activate 之前。`test_journey_map_integration.py` 的经典页脚本检查仍请求根路径 `/`，而当前根路径按 Expo 契约重定向 `/app`，因此旧测试未读取到经典页。修订仅把该测试入口明确为 `/classic`，没有据此修改应用跳转行为；独立审查后另建 r2 候选完整重跑，不把第一次 141 项部分通过与第二次通过相加。失败原件 `expo-map-package-20260917/validation.json` SHA256 `01158d9315cc7856da71ccab79b8a52164732842960452debe740b6936498e78` 保留。

实际 1 户两库完整备份，53 张户内表的行／schema／序列及平台注册库在新 app 启动时保持，原 `.env` 保全。发布后核对 464 源／112 运行／75 HTTPS 静态文件，24 个内部生成路径及 1 个退役资源拒绝，12 个匿名接口均 401；四服务 running／restart 0、app healthy，备份 service success／timer active。数据相等限于启动核对时点，恢复服务后允许正常业务变化；没有数据库迁移。

最终私有原件 `expo-map-package-20260917-r2/`：

| 原件 | SHA256 |
|---|---|
| `build.json` | `ae1021a4618707fd65105fbd42d1ff8adefd3d6ff39ffd6f269c95f89b223976` |
| `validation.json` | `8c38cfc1433f3d7bea657a086cbe35c00fe06a6f4de13cdba0cdbaca0db73d38` |
| `ready.json` | `69a5f8b9b526a1f31ed7762e01125c663b47a577a529e4083516f2476ec88660` |
| `activation.json` | `8eccdddb4ff6e5117b94935eb0f64906237b0adc2bb000fbfa5a407dbba081ab` |
| `post-readback.json` | `5192c7d5a3b845d9507cc83c0f5d3c9c70679ccdc6ed43c9fddfece92edbbcd9` |

两库备份 manifest SHA256 `362a4d491027843b1cc184f6202c52d0248b5de5e62bd7608432c030fc4e7d50`。统一索引 `expo-map-reviews-20260917/published-proof-index.json` SHA256 `ce22ab5300943b1fb53669c6b8b40802faac7a699d45d892ded4b6875ec3b713`；独立五报告审查 SHA256 `66e6f6e121a8add0af39c716012561bb585303fa9d488510195a64040d668e09`。镜像、manifest 与发布目录见 [Expo 地图](EXPO-MAP.md)。本人已登录的生产地图操作、真实云操作、原生安装包与实体电视均未在本轮验收；Windows 公共域名此前的过滤限制不由服务器 TLS 读回解除。后续发布须重新绑定当前基线，不能重放这次操作。

## Expo 家庭物品与库存搜索发布：2026-09-17 00:40:16

安装 main `2925be09d09a4b6e1eab2d6633c1cf5bdebfc8ad`／integration `c1ca0e14acc44d61afe08641fd237e19705dd750` 同树 `3d28f16a7036f84bc2bfbe326a5eb0e34eee3c43`。r2 构建证据 SHA256 `a53d6e55125e095c5f29e5e020e315c88037abfa99b727daf863dc5e1d2ef178`，23 个导出文件；实际 00:40:16 激活、00:40:31 正常 TLS 读回通过。

真实临时 Flask／SQLite／Edge 使用精确 r2 bundle，**14 项检查通过**：私有物品与成员权限、批次不提前计库存、分批收货、共享成员允许的操作、使用／退回／历史撤销、已提交丢响应后原回执恢复、后台草稿保留、真实 409 重核、助理搜索跳转重新读取数量、刷新及应用重启保持、撤共享和真实邀请创建的第二家庭隔离，以及 320／390／1040／1440 四宽布局与原生入口。14 项已包含四宽检查，不再相加；没有页面异常或外站请求，源码与 bundle 前后保持。

原件 `inventory-native-browser/test-results/expo-inventory-20260916T162359438974Z/result.json` SHA256 `3fb0baecd6443c5e7ad31978d59e357e662337189b82cb0f1ad78c7f137bcb3d`，`passed`、`businessChecksPassed`、`accessibilityPassed` 均为 true。保存 16 张截图，作者查看全部，root 另看四张。r1 的业务／布局检查虽通过，但选中语义缺失导致整体失败；修复 Paper 选择控件语义与键盘操作、隐藏 Banner 残留 alert 和手机数量排版后，重新构建完成 r2，不将 r1 diagnostic 计作验收通过。

本轮使用合成数据、真实 Cookie／CSRF／SQLite；后台场景注入页面可见性事件，丢响应场景丢弃一次真实已提交的响应，不替换业务接口。未写生产家庭数据，没有真实商家、云模型或本人库存操作验收，也不证明所有设备的系统后台行为。

实际新镜像内 `test_home_assistant.py`、`test_assistant_inventory_search.py`、`test_inventory_api.py` 三模块 **86 passed、0 failed／error／skipped**；明确 deselect 一项需要 Windows Edge 的浏览器节点，运行文件前后 SHA 保持。此前作者 Windows 同组三模块 86 项与经典页 Edge 七项流程分别验证，照片／地点搜索另 29 项，不能与 Linux 或 Expo 14 项合算成单轮全套。

第一次 Linux 执行是 **84 passed／2 failed**，旧 `expo-inventory-package-20260917/failed-validation.json` SHA256 `2a48bcef4fded6239df784985c924f29c3768db340635dffddc1e337ef9dc138` 保留。当时隔离验证环境设 `ASSISTANT_PROVIDER=local`，两个模型 mock 测试在进入 mock 前因无效 provider 返回 503。新操作候选仅把隔离测试 provider 改为匹配 mock 的 `openai`，真实密钥为空且容器无网络；没有放宽断言、修改业务源码或生产配置，完整 86 项重新执行通过。第一次失败候选没有 stage 或 activate。

生产实际 1 户两库完整备份，无 schema 迁移；全部 53 张户内表的行／schema／序列和平台注册库在新 app 启动时保持，原配置保全。发布后核对 453 源／112 运行／75 HTTPS 资源，24 个内部路径和 1 个退役资源 404，十个匿名接口 401；四服务 running／restart 0、app healthy，备份 service success／timer active。数据相等限于启动核对时点，恢复服务后允许正常业务变化。

最终私有原件均在 `expo-inventory-package-20260917-r2/`：

| 原件 | SHA256 |
|---|---|
| `build.json` | `b1561c744c427e4c4fef50b1fd8b9219971a64a054051c70c4c3cd1b5e25e354` |
| `validation.json` | `ff88615ec4eff7908e0ec6fd843a7bd2a2e1c54bc0987a14787a885cfa8ee0bb` |
| `ready.json` | `b5228b51d35d50d91c58f66874de01830cc2f50d693d5a1fb0a812ddf8a1f6fc` |
| `activation.json` | `3e370a28efa29574d84afb207c6482cb50adcb1b6e126b3a4978d15963a5ec9a` |
| `post-readback.json` | `2712a26909e3efaa4cbbcf4ce3c0bd7f6078a7da50012cd3e778bf67afd790d1` |

两库备份 manifest SHA256 `3965ccb867d163b3bb8468f087bc183b615ae141faa39a167185766d5f6f9731`；源码、镜像、manifest 和发布目录见 [家庭物品交付](INVENTORY-DELIVERY.md)。当前 Windows 公共域名仍受 `Website Filtered` 限制；本地真实浏览器与服务器 TLS 读回不代替本人线上库存、真实云、原生安装包或实体电视验收。

## Expo 官网风格发布：2026-09-16 23:48:34

安装 integration `5ebfd2d6db408128f8137de288f300900794b1bb`，同树 main `d94f7ce746bfbc45de328c516ac9c24d640f2d40`，tree `f57a232684180d72a0254d04bdbf3f1d15ae6f89`。本轮按当前 expo.dev 重做共享风格、导航、首页和登录布局，并修复 Paper Menu 初次隐藏动画竞态；各菜单局部关闭动画，不改变原业务请求和授权逻辑。构建原件 SHA256 `039ab1ebb33bdab720b3308e1f97431669db1686a659d6d7fe5f20e60e3b25a1`。

真实临时 Flask／SQLite／Edge 在 **320／390／1040／1440** 四种宽度通过登录、首页、导航、新建与账户菜单、待办表单打开／取消及退出检查；记录 154 次成功 API 响应和 42 项布局测量，无页面异常、请求失败、外站请求或页面横向溢出。源码与 bundle 前后 SHA 保持。独立审查实际查看最终 19 张截图，核对黑色胶囊、浅灰大圆角、横向导航和长金额完整显示；23 个导出文件另行匹配。

浏览器原件 `expo-review-20260916T154102434460Z/result.json` SHA256 `95cf81ac3449cd59f201815ea1ae9846deaecf3a72b15920f83208e875cc9af4`；组合审核 `expo-site-visual-review-20260916/final-combination-review-r3.json` SHA256 `a08032db55544cee293fc7b16c28fdc4f38c6a5b55345de3d2f0e2adbb8e22df`。初次 Menu 动画失败原件保留，修复后重新构建和完成上述四宽终检。此轮使用合成家庭数据，不把视觉及导航验收等同于重跑上一轮全部云端和复杂业务矩阵；原生安装包、本人真实云操作和实体电视未另验。

本次固定镜像 `sha256:befe93434119bf8bb5a58423895174ed7093b9a1b8ae8f1e41be06f2ab87c0bc` 内 dashboard layout／display preferences／household spaces／frontend runtime 四模块 **63 passed、0 failed／error／skipped**；明确 deselect 一项 Windows junction 检查，运行文件前后 SHA 保持。此项与四宽浏览器分开计数。

**23:48:34 激活，23:48:49 正常 TLS 读回通过。** 实际 1 户两库完整备份，无 schema 迁移；全部 53 表行／schema／序列及平台注册库在新 app 启动时保持，原环境配置保全。447 源／112 运行／75 HTTPS 静态文件匹配，24 个内部生成路径与 1 个退役资源 404，十个匿名接口 401；四服务 running／restart 0、app healthy，发布后备份 service success／timer active。数据相等限于启动核对时点，开放服务后允许正常业务变化。

私有原件 `expo-site-package-20260916/activation.json` SHA256 `961d601a2721eea111b569a0ab2aa78e1ff60e974f26c65e47a2199066e77a2c`、`post-readback.json` SHA256 `9fbe4200423897db85bc3baaf6b090569e66fa43ab3983391b6d68a0af068166`、`validation.json` SHA256 `99ece4d8854daa61ed48fed6b4eee78634942ba59f9e900fb5bc3692943a79c2`。两库备份 manifest SHA256 `34ec0a2878cfa71b1b624b89d7a5db8fddd6ebdcc876deefc689ae9e58381c4f`。固定包身份见 [官网风格交付](EXPO-SITE-STYLE.md)。Windows 公共域名 `Website Filtered` 限制仍保留，未据本地浏览器或服务器 TLS 读回声称该网络下本人登录验收通过。

## Expo 统一设计与三模块发布：2026-09-16 23:02:11

本轮旅行、助理、相册接入真实原有 API，不改变 53+2 表。main `5c59ffb7`／integration `95c73ed` 同树 `a405fd56`，23:02:11 激活、23:02:30 正常 TLS 读回通过；完整源码／镜像／包身份见 [本轮交付](EXPO-NEXT-RELEASE.md)。

| 范围 | 已取得证据 |
|---|---|
| r2 真实组合浏览器 | `4cb69ac` 实际导出，临时 Flask／SQLite／Edge **14 组通过**；保留原日常操作，新增旅行预览／确认、助理选项与原计划回执、照片共享／逐台 TV／撤回、创建 202 后丢 GET 保留原标识与同步打开 Picker；零页面错误／外站请求 |
| 视觉 | r2 实际查看 390／1440 的 16 张图，另独立真实 320 视口补充 8 张，合计查看 24 张；白底黑 CTA、细边框、无旧主题菜单，中文长标题／地点换行。320 八张页面宽度均为 320，无横向溢出；不是重复 14 组业务回归 |
| r3 定向增量 | `95c73ed` 新导出 **6 组通过**：390／1440 首页查看旅行进入详情、明确编辑后的放弃草稿对话框居中限宽，以及新版登录／相册／助理烟测。其余 r2 结果按未改变输入继承，不写成单轮 20 组 |
| 实际 Linux | 本次固定镜像 `c9229460` 内 dashboard layout／display preferences／household spaces／frontend runtime 四模块 **63 passed，0 failed／error／skipped**；明确 deselect 一项 Windows junction 检查，运行文件前后 SHA 验证通过 |
| 生产与读回 | 1 户两库完整备份，53 表行／schema／序列及平台注册库在新 app 启动时相同，配置保全。444 源／112 运行／75 项正常 TLS 静态文件匹配，24 个内部生成路径和 20 个退役资源 404，十个匿名接口 401；四服务 running／restart 0、app healthy，发布后备份 service success／timer active |

r2 功能原件 `expo-review-20260916T144652655491Z/result.json` SHA256 `2a8cb39d29897bcda6e97124fe7ec43dd66a794c8eb50c95e4ca8eb8826e00e8`；独立视觉报告 `review-4cb69ac-r2.json` SHA256 `daae0e66ef2bb508a8751fd8a402cd65fe067676f28aca0c8c658114198beeec`。r3 原件 `expo-review-20260916T145311737431Z/result.json` SHA256 `2918ca802d8bc4aa374ab45f1ac1a523c0a7b29851b3ffd4eb3f76a4157eb89c`。r3 两张放弃编辑对话框也已实际查看，390／1440 分别约 359／520px 宽，居中且文字可读。

生产原件为私有 `expo-next-package-20260916/{activation,post-readback,validation}.json`，SHA 见 [本轮交付](EXPO-NEXT-RELEASE.md)。完整备份 manifest SHA256 `6387bb68f4688a57440bca620d3c55f71884866c9e261b1a3f1e27dd67f81b54`；启动前后快照 SHA 均为 `9580832d983279797015d093c10385765527d9919b0457ed4414eeb4e75c3e76`。数据相等限于新 app 启动核对时点，开放服务后允许正常业务变化。

早期 Metro 沿 node_modules junction 解析到旧树，旧导出已拦下；改为独立 `npm ci` 后重新构建 r2／r3，未发布无效产物。浏览器初轮照片 readback 等待过早及 320 脚本标题／带图标按钮选择器失败均保留原件，修测试等待或定位后通过，没有据此放宽业务断言。Google 输入和像素均为合成，真实 Flask 身份、CSRF、SQLite、净化加密和保存接口参与执行；没有新增本人真实 Google、原生安装包或实体电视验收。此前本人 Photos 5／5 保存成功事实保留，Windows 公共域名 DNSFilter 限制仍未改变。

## Expo 前端发布：2026-09-16 21:59:19

main `c74e72c79daa64a9fb9b575db496375b5803b91d`／integration `e00e5c25e0c64f0981913780ffb2024e77a384a7` 同树 `967ba95a0438bea7c405e1590adaa82af22d141e`。实际 Metro 导出使用 React Native Web／Paper；发布包 427 源、112 运行、23 导出文件，75 项公开静态资源。21:59:19 激活、21:59:51 正常 TLS 读回通过，完整身份见 [Expo 交付](EXPO-RELEASE.md)。

| 范围 | 已取得证据 |
|---|---|
| Windows 分段 | 既有受影响组合 60 项通过；runtime 后续单独 37 项通过，含新增 4 项 OAuth 状态返回 classic 的检查。两轮范围重叠，不相加为 97 项 |
| 实际导出浏览器 | 精确导出候选 `4265faa`，真实临时 Flask／SQLite／Edge 八组通过：登录、范围持久化、本地待办、采购金额与图片、409 保草稿、已提交丢响应不重发、换成员清草稿、手机路由刷新；零页面错误／外站请求 |
| 视觉 | 同候选 390／1440 两组、30 张原始截图，实际查看 13 张代表图；覆盖今日／周、日程、待办、采购、登录、导航、新建菜单及森林／晨光主题。长标题和地点换行，零页面横向溢出；组件作者视觉核验与非作者八组功能验收分别记录 |
| 构建 | `npm run build:web` 实际执行；固定锁文件、输入与 23 输出字节绑定 `build-evidence.json`，SHA256 `4ed5633ec1c6bd6e553af7b0c30a3e6f15763d95fedd82ef5ba6bb2517652c23` |
| 实际 Linux | 固定新镜像内四模块一轮 63 passed、0 failed／error／skipped；明确 deselect 一项 Windows junction 测试。全部运行文件前后核验通过，未使用生产数据 |
| 生产与读回 | 实际 1 户两库完整备份，无迁移；53 表行／schema／序列及平台注册库在新 app 启动时保持，配置保全。全部 427 源／112 运行／75 HTTPS 资源匹配，24 个受限生成路径 404；深链、classic／tv／demo 入口通过，十个匿名 API 401，四服务 running／restart 0、app healthy，备份 service success／timer active |

八组浏览器原件 `expo-review-20260916T134447004754Z/result.json` SHA256 `c20136df78116a50c3fb3ca60685145b33e12060a518b2459c69c51209888cdf`；视觉报告 `visual-review-4265faa.json` SHA256 `23f42ba39201b5b21d4eccdd0b53eccd945a7b1de8585a66a4d3de0047f81310`。旧登录 label、保留字路由 `/app/undefined`、手机 tab 名称及重复描边已修；初始失败和后续测试定位修订保留原件。最终源码新增的回调衔接另由 runtime 专项验证，不把早期浏览器执行写成针对后续 Python 改动的全量重跑。

生产原始 JSON 位于私有 `expo-package-20260916/server-evidence/`：`activation.json` SHA256 `02dd3c2792ee9788324d6ba005cbef6d360bf29b4a0b1f514ecb26ece9f3e1db`，`post-readback.json` SHA256 `6b5fcc2c9abcd09671d26c87e7bf485f47505fbe9839e26519ef157537deec7f`。`validation.json` SHA256 `dd93b913fffca41118173a5b716fbfd61d66d9addbd2d0b04c52850f234f001f`，绑定同镜像和实际日志／JUnit／运行证明；完整两库备份 manifest SHA256 `a339e66bf11d24785c227b9cedc45a96b59b9b1d4b31b775202fb0807050d03e`。数据相等结论覆盖新 app 启动核对时点，开放 worker／web 后允许正常业务变化。

**线上浏览器检查未通过：** 当前 Windows 网络把根路径与 `/app` 返回为 `Website Filtered` 页面，包含 `blocked.dnsfilter.com/index.js`，响应不是应用 CSP；同页 SHA256 `66d9a8da0b6e608c0bc4e8c6ad73baeef7a118d983d27699396d837dc9667f4a`。独立浏览器未进入应用，0 组完成；报告 `expo-public-20260916T140013842499Z/review.json` SHA256 `25eeab2409cbb952993cf6298dbeb3969c0d84ce380f5818efa452fb69c60156`。未修改 DNS、代理或安全设置。此限制与服务器正常 TLS 的入口／75 资源读回分开记录，不把本地八组浏览器结果写成线上浏览器通过。

未制作／验证原生 APK 或 iOS 安装包，没有新增真实云写入、本人登录操作或实体 TV 验收。此前本人 Photos 五选五保存成功事实保留。本节为发布后交接，不改变已安装 manifest。

以下保留此前发布的独立身份和验证原件，不作为 Expo 当前安装身份。

## 地图相册与照片时间建议发布：2026-09-16 20:38:46

安装 main `e20c269`／integration `c716e4d` 同树 `4127507e571656db19cd268804020874be0eca02`，manifest `945f0b70e1b07b2eac21485483e24a49855a0de0a57c207a02327d804fa342a9`；373 源／88 运行／53 静态文件，83 份 Markdown、145 路由、53+2 表。此轮只更新源码，无迁移。用户入口与错误处理见 [媒体交付](MEDIA-DELIVERY.md)。

Windows 作者后端五模块 **144 passed／83.30s**，根代理独立建议专项另 **34 passed／23.83s**；新 UI 合成 10 组与旧相册 15 组分开执行。非作者真实临时 Flask／SQLite／Edge 地图桥接 **13 组**、建议 **6 组**分别通过，覆盖明确关联、地图读回、旧 unknown 手动关联、真实 409、已提交丢响应后只读回及共享撤回。最终镜像 Linux 五模块单轮 **144 passed／150.48s**，0 failure／error／skip，运行文件前后核验通过；不把这些执行相加为一次全套。

实际 1 户两库完整组备份后更新，全部 53 张户内表和平台库在新 app 启动时的行／schema／序列与原值一致，配置保持，随后才开放 worker／web。20:39:27 正常 TLS 读回核对 373 源／88 运行／53 静态 SHA，十个匿名接口 401；四服务 running／restart 0、app healthy，完整备份 service success／timer active。

实际原件在私有 `media-journey-package-20260916/`：`activation.json` SHA256 `87660ae1f736f743d6d526497df8f1570fb97446bdcad9e05e0efdc4d29bbc95`、`post-readback.json` SHA256 `0e988e1b52dbb33788d2f1d21a8e86d6faadc107d88b629917e4a982c43e591e`、`validation.json` SHA256 `03bdf20d89625f5a25372043e0ea5213cb40beb9a0e513c3e9fb5bb9a92fe1cf`。Linux 日志／JUnit／运行证明在同目录 `validation/`，均与报告绑定。发布目录 `/opt/family-dashboard-releases/media-journey-53-20260916T123758365084Z`；两库备份 manifest SHA256 `e978f53dfb2da37451a8d1d98b681c24735ac59ef5951fd3771c5fb33afbac1a`。

非作者组合报告 SHA256 `79872ec25ae15517f1927a1b5faed4ef0d18af79ccf70cdca8a359e2275950cf` 绑定精确联合与 373 文件哈希。地图 13 组执行于 `b2be531`，到 `c716e4d` 只恢复相册 JS 原 LF 换行；建议 6 组直接执行于 `c716e4d`。测试工具首轮未等页面加载的失败原件保留，补等待后 6 组通过，未修改产品源码。

此次私有操作脚本在 `media-journey-release-20260916/`，与上述包和证据目录分开；它们绑定发布前的旧 manifest／镜像，发布成功后不可直接重放。仓库 43→43 SOURCE 历史入口不适用于当前 53 表。本轮 Google 输入为合成，未重做本人真实云或实体 TV 验收。此前本人 Photos 5／5 保存仍成立；旧照片 unknown 不回填，日期建议不证明 GPS 或到访。本人新入口／旅行关联及库存 AI 搜索另候选仍分别待验／待发布。本文是发布后本地交接，不改写已安装 manifest 或原始报告。

## 库存与本地搜索发布：2026-09-16 19:48:57

最终 main `cf0369084fb34ca24aa31777779d29e8487206fd`／integration `0c7c783985ef78e8391e874e0b00dbf38f536520` 同树 `8e8fb21c6a357340fd31bf2f98450e3c1e8464c9`。安装包 367 源文件、80 份 README/docs Markdown、53 静态资源；源码实际索引 144 方法／路径模板、53 户内表及 2 平台表。已完成生产 48→53 激活和 19:49:16 发布后读回；这不代表本人实际库存或新增搜索体验验收完成。

| 范围 | 实际结果与边界 |
|---|---|
| Windows 最终组合 | 助理搜索 30 项、库存严格工厂／原 HTML 浏览器 8 组、53 表恢复 1 项分别通过；真实临时 Flask／SQLite／Edge与虚构输入，不是本人真实库存或实体 TV |
| 实际 Linux domain | **177 passed／135.14s**；库存核心、HTTP、运行接线、个人导出，在固定不可变镜像内使用合成数据 |
| 实际 Linux recovery | **42 passed／95.01s**；库存迁移／完整恢复和媒体运行／恢复／迁移，另一次独立容器执行 |
| 包与来源 | 367 源文件、88 运行文件核验；最终树相对 build source `9f5f5db` 只改变 README、HANDOFF、MEDIA-DELIVERY、VALIDATION 四份文档；两个 Linux 报告各自 allPassed、JUnit、日志及实际 `/app` 模块路径均绑定原镜像 |
| 生产迁移 | 实际 1 户两库完整组备份；旧 48 表全部行、schema、序列及平台目录保持，新增五表在新 app 启动后仍为空；随后启动 worker／web，原环境配置与密钥保持 |
| 19:49:16 读回 | 全 367 源／88 运行／53 HTTPS 静态文件 SHA 匹配，九个匿名接口 401；四服务 running、重启计数 0、app healthy；发布后完整备份 service success、timer active |

两组 Linux 测试分别执行，结果按各自原件记录。构建镜像为 `sha256:b82d0cdc1a594be661beed949fc317ddd7adaf2d2c53981f6403f667d31d0426`，build manifest `2b946250361e44f0f9624757ec125ed939ed824bfbd7ce1f4f9b0ad93ed7c1b1`；最终包 manifest `c3c718d35ba43fd4b67505a6116264b709a90a7a9dd3d524e74f8e7a091a815c`。最终发布文档不改变实际镜像运行文件。部署后本轮交接文档也只在本地更新，不改写原发布 manifest 或验证原件。

Linux 原件分别在私有候选 `inventory-release-9f5f5db/validation-domain-20260916T113033068044Z-bb6c1ced/` 与 `validation-recovery-20260916T113033094742Z-c8d9fd28/`，各含 report.json、results.xml、validation.log、runtime.json。最终包非作者核对报告 SHA256 `49ce43f389fd49bc577f1e3ab3ca1abc12b4acf2db0e679e94fcca9cd401cd3e`。阶段性作者测试、原失败和修订按对应 [库存浏览器](INVENTORY-INTEGRATION.md)、[迁移](INVENTORY-MIGRATION.md) 与 [恢复](INVENTORY-RECOVERY.md) 保留，不重写为一次全部通过。

生产原件在私有候选 `inventory-package-final-20260916/activation.json` 与 `post-readback.json`，SHA256 分别为 `f60da08b1de36c2ab20b651afe665f884048c7c7d51cf71684d3e19a553710e2`、`3a7f57aeb66554675644776cd88c111c601b9c53d28b706e4791c5e6cf7ae378`。发布目录 `/opt/family-dashboard-releases/inventory-53-20260916T114808119918Z`；完整两库备份 manifest SHA256 `a3799fed9c6780a2f24034004056960da0bae8488a4f5c47cd116a3666eaea47`，另保留原源码、配置、镜像和独立备份组副本。数据保持结论截至仅启动 app 后的检查；开放 worker／web 后允许正常业务变化。控制器由 root 审查并在 stage 实际通过后执行，另一次非作者静态／语法审查报告 SHA256 `44f3c9210b406547719faf403e7354616dff3333edae0429c99ecf2924e98a15`，该次审查仅覆盖静态代码与语法。

此前本人 Google Photos 真实 5／5 预览与明确保存通过的证据仍成立，见下一节。库存分段验证不重新执行真实云操作；本人真实库存数据录入、新增搜索体验、实体电视、长期 Google 配额／网络和生产覆盖恢复仍未验收。

## JPEG 主图兼容发布：2026-09-16 19:16:22

main `f603151`／integration `e2087e0` 同树 `dc8e805e22914b701c2e2e0b6d888bd047d66f36`，manifest `a48831b101ab78f5b4cc61ea29e8b1cb5204af70a13885886fcda47cd36635eb`。补丁只净化完整首张 JPEG 及其方向／色彩标志，不放宽体积、像素、完整解码或 PNG／WebP 动图限制；详见 [兼容说明](MEDIA-JPEG-COMPAT.md)。各次验证分列，不相加为一次全套。

| 范围 | 实际结果与边界 |
|---|---|
| Windows 作者 | 图片 139 passed，另 worker／结果 60 passed |
| 非作者独立 | 图片 186 passed（包含 47 项独立反例），另 worker／结果 60 passed；真实 worker／SQLite／成员确认桥接另 1 passed。所有图片与 Google 传输均为合成 |
| 实际 Linux | 新不可变镜像四模块一轮 **199 passed / 36.50s** |
| 生产与读回 | 实际 1 户两库完整备份，无迁移；原 48+2 表全部行、schema、序列及配置保持。19:17:28 全 346 源／84 运行／51 HTTPS 静态文件匹配，71 Markdown；四服务重启计数 0、app healthy、六个匿名接口 401、备份 service 成功且 timer active |

私有原件在 `photos-jpeg-20260916/` 的 `build.json`、`validation.json`、`activation.json`、`post-readback.json`；目录 `/opt/family-dashboard-releases/photos-jpeg-20260916T111536Z-20260916`。完整备份 manifest SHA256 `58a97281b62a4af864149803a9190183c3fb83a020109430ba95385f5647ce0b`。Linux 计数来自实际执行日志，`validation.json` 只绑定退出状态与镜像／运行字节，不从该 JSON 补造用例数。

18:57 诊断补丁后的本人重试确实得到十选五和五项 `invalid_image`（见下一节），但没有原图级根因证明。发布后本人重试明确反馈“出现预览，并成功保存”；服务器只读确认最新记录为 confirmed／resultsState=known，selected=5、ready=5、failed=0、skipped=0、pending=0、saved=5、unselected=0，五项均 successful。本批真实 Google 授权选片→处理→明确保存已 5／5 成功，补丁对这次重试有效；不以此推定原失败的逐项 MPO／尾部／EXIF 原因，也不扩展到实体电视或长期配额验收。该反馈晚于 19:17 读回，原 `post-readback.json` 中当时的未验收标识原样保留，不反写原件。 后续独立原件 `photos-jpeg-20260916/real-import-acceptance.json`（SHA256 `c8c7548e3be056e63768e85472822a8f6ffd21c83a5f7343ddf77e02cf39ff0f`）记录本批成功，不断言它与此前每个 source ID 的逐项映射。

## 相册结果诊断发布：2026-09-16 18:57:14

main `d9c51b9`／integration `2aac0007` 同树 `db0949c2d1b55bb53351d4c352740edc9ac34a7c`，安装 manifest `76b8bc77ba786be3069ca477facd7ecb7d9b6d2d61a10c8df0388994a886b45d`。补丁保留逐项白名单原因、确认后的统计和准确勾选保存数，旧记录明确未知；不修改解码器、配额、依赖或 schema。以下各轮分别记录，不相加为一次全套测试。

| 范围 | 实际结果与边界 |
|---|---|
| Windows 后端 | 三个受影响模块 105 passed；非作者另有 4 项真实 SQLite／worker 合成边界检查通过 |
| 界面 | 非作者 Edge 新结果 10 组、既有相册 15 组分别通过；明确合成 HTTP DTO，非真实 Google |
| 最终组合 | Edge 10 组及真实后端→UI 桥接 1 pytest／4 组通过；含十选三可用、仅勾两张保存、一个未勾选和旧回执未知；Google 输入为合成 |
| 实际 Linux | 新不可变镜像三个受影响模块 **105 passed / 93.97s**，不与 Windows 或浏览器计数混合 |
| 生产与读回 | 实际 1 户两库完整备份，无迁移；原 48+2 表全部行、schema、序列及配置保持。18:58:16 全 344 源／84 运行／51 HTTPS 静态文件匹配，70 Markdown；四服务重启计数 0、app healthy、六个匿名接口 401、备份 service 成功且 timer active |

私有原件为 `photos-results-20260916/` 下的 `build.json`、`validation.json`、`activation.json`、`post-readback.json`；发布目录 `/opt/family-dashboard-releases/photos-results-20260916T105630Z-20260916`。完整备份 manifest SHA256 `caa4bded81a99574df0750fca1fdf9801808f13bd6187e5103a4adddf602c0a0`。

本人已完成 Google 授权与真实选片：历史 10 张普通照片只保存 3 张，其余 7 项原因没有保留，不能以合成格式调查替代真实原因。补丁不补写历史。后续本人重试的真实记录为 selected=10、ready=5、failed=5、skipped=0、pending=0、saved=5、unselected=0；第 1／7／8／9／10 项固定错误均为 `invalid_image`，已确认保存。诊断展示与保存数已验证，但具体解码原因仍未知，不能据此宣称完整兼容、长期配额／网络行为和实体电视验收完成。

## 实际媒体发布：2026-09-16 18:05:30

安装源码 main `2c2332d8820e7a7f43d8c2e9fb63a885c03293ef`／integration `8607b14500b21158f74e6c0876b6778ced34169e`／候选 `36bd770ecb014fde32004747cb95fdd2d4c06ab0` 同树 `421ed257d55ca6a83659de0465b9094cc3e8103e`；340 源文件、130 方法／路径模板、48 户内表 + 2 平台表。发布目录 `/opt/family-dashboard-releases/media-20260916T100305Z-36bd770`，manifest `7b9c7dcb4f734a619b6acef1f92c83cb57f1cd522fc6f54ca1b773bb605d0b32`。本次仅发布媒体，不包含库存五表或库存运行接线。

| 范围 | 实际结果与边界 |
|---|---|
| 候选 Linux | 实际新镜像、无生产库、网络 none、只读运行；七模块原轮为 **182 passed / 1 failed**，失败为旧测试仍断言三张媒体表。保留 exit 1 原件；修正为实际四表后，同镜像另跑该单项 **1 passed / 1.48s**，不是一轮 183 全过 |
| 隔离恢复 | 实际候选 Docker 中两户、三库严格恢复 **1 passed / 9.52s**；同一镜像、合成数据，不执行生产覆盖恢复 |
| 真实本地浏览器 | 相册真实 Flask／SQLite／Edge、工厂注册与子户／重启 10 组通过；Google 外网 transport 为合成。电视实际 HTML／工厂另验证播放控制、断网清图和期限，不代替实体电视 |
| 生产迁移 | 实际 1 户 44→48、2 库完整备份；独立迁移后检查及 app 启动后旧数据核对，旧 44 表的全部行、schema、序列保持，新增四表为空 |
| 服务与健康 | app／sync／media 同新镜像；web 保持原镜像。四服务 running、重启计数 0，公开 HTTPS `/healthz` 200；原配置和密钥保持 |
| 18:07:30 发布后读回 | 全 340 源文件、84 运行文件及正常 TLS 下 51 静态文件 SHA 匹配；68 Markdown；六个匿名媒体／导出接口均 401；app healthy、四服务重启计数 0；发布后备份 service success、timer active |

私有原件分别位于 `media-release-25c9f20/linux-tests-retry2.json`（exit 1 原轮）、`media-release-f9f7301/recovery.json`（exit 0 恢复）与 `media-release-36bd770/` 下的 `validation.json`、`activation.json`、`post-readback.json`。后面三份 SHA256 依次为 `c54602f0fe54d95237452ee0fab83bfce764085e894b575e6ac69d9e2af1dd84`、`518c8b7d1c44579c116c6e5d194d426971d93f5570aa8879bf193b592dcb4051`、`256f68ec4937c777a87cc18ee78ffcbbfb0202acc948ed7a735b67eb9f03f4b9`。`validation.json` 记录 exit 0 与运行字节保持，不含逐项计数；单项 1 passed／1.48s 来自实际 Linux 日志。测试阶段 Git HEAD 与最终安装身份分别保留；恢复阶段只新增测试和说明，原 338 文件字节保持、运行镜像不变。不得改写失败原件或把多轮结果拼成一次全套。

该 18:05 发布时本人 Google Photos 授权、照片导入和实体电视尚待反馈；后续真实授权与十选三情况见顶部，不据此认定真实 Google 配额／网络行为已完整验证。视频、iCloud／NAS、自动旅行关联和回忆精选尚未实现。库存的独立候选测试也不计入本次媒体发布。

## 实际地点发布：2026-09-16 16:33:32

main `6f3d978` 与 integration `cd857f5` 同树，295文件。精确READY SHA `15fa1dbaaa1df1e0161510a2ba1bca642f4318a5be4a7a373a9ecdf939a6e5e0`，非作者准入报告SHA `d44cb4a33216a296e0f08ceffacc9110f88010eabab92945871d8054c4845b34`。七类证据、43原件及新鲜基线核验通过后才部署。

| 范围 | 实际结果与边界 |
|---|---|
| Windows | 899 passed：467后端+432工具。保留各次执行/JUnit与依赖适用性，非同一head单次全套；41 subtests单列 |
| 新镜像Linux | 同29脚本899 passed，0 failed/error/skipped；41 subtests单列；74 runtime、221 fixture、958测试依赖不变，同Python3.12 ABI，4容器清理 |
| 浏览器 | 地图真实应用10、成员会话33、导出权限59；运行文件和脚本逐字适用、各组0外站请求。另59布局的外站请求未测，不能填零 |
| 双户Docker迁移 | 47 runner检查，seed15/HTTP100单列；旧43表保持、新增空地点表；17容器+2新卷清理；未调用生产controller |
| 双户Docker恢复 | 65 runner、23 seed、232 verify分列；24地点含4删除标记、8资料、8采购图片；旧会话/OAuth各拒绝4；22容器+6卷清理 |
| 实际生产 | 1户43→44、平台2表保持、两库组备份；安装前/启动后/HTTP后三次数据核对；47静态、10匿名权限GET；原配置保持、三服务运行且app健康 |
| 独立读回 | 全295 source、manifest、镜像及原配置相符；正常TLS五项HTTPS：health200、地点匿名401、三地图资源200且SHA一致；不是手机或实体电视验收 |

Linux `result.json` SHA `2659407b2fb40409355e4d06a13b6aae34878358e0199b312f8b6c8e3723ad2a`；Windows来源汇总SHA `3d23c4b8d10b6dfece0d67fa7498b584330ea1a798a3e66b951b3dc62a6f8e38`。迁移原件SHA `a9a0b4ceb401ecc6708892f9b84b4b7a7ca7ccd9aaaf11b2025ae3956e2b560f`；恢复原件SHA `63753f35cf4d6336508eeddf9fd8e53bcb0424a7928ad5b6d03beb8073ae6bbc`，其中79源码依赖是完整295 manifest的精确子集，另用实际调用和镜像绑定。计数不相加冒充独立功能数。

实际 `deployment.json` SHA `e96105192351de23135e8b5df6b4fb61eb861f3f68b6d726e9ceb16309de77e3`；目录 `/opt/family-dashboard-releases/journey-places-20260916T083232752975Z`；manifest `1a5990e0b7e500ed44986b979e413a8ba26c92bd6cf4c7757be429bed17e51d8`。

首次生产preflight因候选目录root 0700导致非root校验容器不可读，在停服前退出（interrupted=false、stops=[]）。仅修候选根及manifest权限，保留READY/evidence私有与所有字节，UID10001全源码读取和原verify-image通过，再按同一READY发布成功。原失败目录 `journey-places-20260916T082932814752Z` 保留。r2 Linux原有29失败来自测试环境遮蔽合成NVIDIA配置，修订测试进程环境后r3全部通过；旧失败不改写。迁移输入、子进程测试依赖路径与文档占位符修订也各经审查。

NVIDIA配置工具组合 `14dc2b1` 仅增加3文件，其非作者报告SHA `2eed45a25c87d226091c141fcf8f9dbc1d70fe80264873807e2b2d6940557e3f`；组合Windows102 passed/7 POSIX跳过，独立WSL114通过。main `18f30dd` 接收同树组合；同日 16:58 完成配置启用及原镜像服务重建：三键、0600 原样备份、其他配置原字节、Compose 和数据卷保持均核验。公开正常 TLS `/healthz` 200，三服务运行、app healthy，重启计数均 0。新 app 容器使用实际 NVIDIA 配置调用 `us/azure/openai/gpt-4o-mini` 一次（2.193 秒），在独立 `/tmp` 虚构家庭经 `/api/assistant/plan` 返回 200、`mode=model` 和一条预期待办草稿；0 业务实体，未 apply，未读取真实家庭数据。证据汇总 `nvidia-production-activation/activation-summary.json` SHA256 `7d6d860cad12a493c54d68f67befa6b94382500164c2f06f800631cb408083f0`；不等于本人在线 UI 或真实旅行全流程验收。真实新云写、Google Photos、实体电视及生产覆盖恢复仍未验收。

下方为历史分段开发记录，“尚未部署”仅描述当时阶段。

## 历史分段开发：账本与地图

### 后续本地地图增量（尚未部署）

main `9559ca4` 与已审 integration `1ff3bd4` 同树。非作者组合报告 `map-final-combination-review-1ff3bd4.json` SHA `ce95f9ba4f04200c651221e3bc7f3b7c092b2624c6453929f33f73c8f351ee78` 核对 279 文件、相对 main `583f5c9` 的 20 路径精确联合、四个已审 head 的祖先关系和原始证据；它只准本地合并，不是生产发布批准。

实际组合浏览器报告 `journey-map-real-20260916T064356439073Z.json` SHA `a8228eca17fbda089665eada9f912352d3162e0dcf9fccf338684a4920de2f9b`：**10 项通过**，真实 Flask/SQLite/Edge，0 页面错误、外站及提供方请求。覆盖本地底图、保存/刷新/应用重启、关联旅行、页面刷新保留同一草稿与焦点、成员切换清理、共享投影与撤回、390px 布局及实际 revision 冲突处理。原执行 head `aae0ee10` 与最终候选运行代码一致；最后只补接入文档，非作者逐项核对散列适用性。

分段验证不相加冒充一次全套测试：API 作者 95 项含 4 项既有用例，root 独立 91 项；UI 最终独立 20 项合成后端浏览器；接线非作者 7 项后端。接线原组合 104 项为 100 passed / 4 failed，四项原因是新测试对全局 Cache-Control 的期望不符，修正后 6 项接入专项通过。UI 首版有“离开已到访状态仍提交隐藏确认”的 P2，修复后新 head `e6795f4` 审查通过。

首次真实浏览器报告虽然执行了 10 项流程，但临时 SQLite 未关闭导致 Windows 清理失败，且当时失败标志错误地仍为 true；**该报告不计通过**。修正资源关闭顺序与失败标志后，上述独立报告才成为有效证据。48 份文档、917 链接、64 锚点检查通过；其中 7 个临时文档恢复用例不是 44 表 Docker 恢复演练。实际生产升级、Google Photos 账号和实体电视均未据此验收。

### 历史本地 NVIDIA 增量（现已按顶部记录启用）

产品提供方适配固定 head `52be16e803758797eabe545c0500094cd005ee09`、base `79faaf3`，由 root 非作者审查：最终 Windows 四模块实际 **168 passed**，0 failed/error/skipped；260 跟踪文件前后相同，前端 JS 语法通过。作者先前 163 项组合、其后 108 项专项和首次环境/测试名失败分别保留，不累加到 168。新模块不改变原权限、旅行事实核对或预览确认规则。

root 随后在该固定 head 的临时家庭中使用指定真实模型 `us/azure/openai/gpt-4o-mini`，实际两次模型请求分别经过任务草案与旅行简报接口，完成 **18 项检查**：草案不执行、其他成员不能应用、本人确认保存、相同确认不重复、原 SQLite 在新应用实例中读回，以及明确日期/预算/目的地核对。报告 `nvidia-product-live-20260916.json` SHA `dd9ccf3044ffc98e4f241d8efc59c02dfedb1b5dd41aa69a5417dd8b1c29476f`；实际执行 exit 0。仅发送虚构需求，没有生产库、真实财务、云日历/清单写入或实体设备操作。生产服务器只做过不带密钥的目录连通检查并得到 HTTP 401；这不证明该服务器上的授权调用已成功。

开发编排固定 head `96d8a82f64b6b9a05e5270953b2214935d55b41d`，非作者独立 **27 passed**。实际目录返回 170 个模型 ID，选定同一模型通过基本 chat/completions JSON 探针。24 份脱敏需求任务各一次成功，实测最高同时在途调用 **14**（配置 24 worker、每秒 3 次）；服务返回用量合计 **5879 输入 + 4399 输出 = 10278 tokens**，延迟最小 2766、中位 3768.5、最大 7536 ms。幂等重跑新增生成请求 **0**，仅重新请求目录一次。这不是 24 个工具执行代理或已开发功能；真实 429/超时故障未出现，故障处理只有合成验证。

编排首轮原摘要保留峰值 14，重跑报告保留峰值 0；原 SQLite 的任务摘要 http_status 为空，但请求 attempts 与各 observation 中实际为 200。首轮摘要缺少后来新增的 run_id/started_at 字段，不能回填或声称最终代码重新执行了 24 次。45 份原件引用与全部建议 SHA 由非作者核对，建议仍标记 `untrusted_unreviewed_proposal`。索引见 [编排指导](INFERENCE-ORCHESTRATION.md)；原始私有 test-results 不进入分发源码。

产品适配审查报告 SHA `315ac6b7e774193969d11ae60b3571fba0bd5e17b622148045eb417a82c65fe1`；编排审查报告 SHA `ff8efbadbec6226ee09a62657ceb8bce4aeda79a69f070d525aa53bb778e2cde`。两个已审候选以精确文件并集合入 `ff590965c8feb544930e12a0cd7a477ffd17b872`，后续组合验证另记，不改写原固定 head 记录。Linux/生产配置/完整 A–D 场景/实体设备仍未验收；不能把此前账本的 Linux/生产结果套用于本次 AI 改动。

开发基线为 `fa72df4`。只读审计以合成 Flask／SQLite 复现两处缺口：同月 501 条收入全部保存，但 overview 只返回 500 条且没有通用分页入口；文件金额 `1,23` 被无错误解析为 123.00，可确认并进入预算。没有据此断言真实平台文件已经受影响。

后端、前端和本节文档在三个独立任务分支开发。后端 `047fa53` 首次审查发现人民币前缀后空格被误拒；`1e83821` 仅恢复边界空白兼容并补充三个文件通道的正负例，独立复审通过。界面 `0ca4d4c` 审查发现挂起读取期间切换标签再返回会停在加载中；合成浏览器真实复现后，`85ce24d` 修复请求取消与重新读取，补第 17 项场景，同时让源码变化导致测试失败。原拒绝报告与失败浏览器报告保留，不改成通过状态。

已审后端、界面与 SOURCE 精确路由文档路径策略合入 `98fb73904667a55e92c13db76d65b94aab158ed8`，树 `22e73f65f307570e05b638156a9c4bfe838f10e8`。非作者逐文件核对该组合是三份已审提交的精确并集，没有额外运行修改。固定组合的实际本地验证如下：

| 范围 | 本轮结果与证据边界 |
|---|---|
| Windows 受影响后端 | 10 模块 **435 passed**，0 failed / error / skipped；覆盖文件解析、金额列、淘宝分组、对账、导入导航、投资导入、新分页和金额专项 |
| 新账本实际 API 浏览器 | **17 项通过**；551 条实际合成导入，使用真实新 GET，覆盖后续页核对／删除、采购往返、快照冲突、异步身份与标签返回、手机与纯本地 demo；没有注入分页路由 |
| 投资导入浏览器 | **15 项通过**，验证共用编辑身份边界后的原流程 |
| 既有财务浏览器 | 对账身份 57、月份导航 35、采购关联 61、淘宝 adapter 17、金额列 13，共 **183 项通过** |
| 路由与存储盘点 | 临时新数据库生成 **107 方法／路径模板、43 户内表和 2 平台表**；生成文档另存后加入文档分支，没有改动验证中的源码 |
| SOURCE 工具 | 独立 reviewer 在 `fd0a128` 全文件 **88 passed**；该工具、fixture 和受依赖配置的 29 文件在组合中逐字保持，因此按适用性单列；没有计入 435 或浏览器计数 |

浏览器合计 **215 项**来自 7 组分别执行的用例，不是一次全套测试；各组 258 个跟踪文件前后散列保持，页面错误、外部请求、真实财务输入与生产写入均为 0。金额列、对账身份和投资组未单独计数服务商调用，不将未统计值写成 0。请求观察中的方法／路径数量不作为专门路由覆盖。历史发布的 406 项后端与 252 项浏览器不作为本轮新行为的通过证据。

本机忽略的 `test-results/` 原件索引（均保留原文件，分发源码不包含这些私有报告）：

- 后端／投资 `backend-combination-20260916T043139918717Z/combination-final.json`，SHA `17e68c679c6aadf099f42f146b4d3faa1fa13c1495b060211e17796da843761c`。
- 新账本 `finance-ledger-api-20260916T043010264039Z.json`，SHA `ad09bf427aa68f7c255cea3a972da6089879b58467cb7f0a16eee2b518bb565b`。
- 五组旧浏览器 `combo-browser-98fb739-index.json`，SHA `a2435957566310976eaa1236e571aaf0e22c2af485f910e6a879b3f1e5d49306`。
- 组合接缝预审 `combination-seam-review-98fb739.json`，SHA `97b587cc60afa68eb84472c2fd5833c6e8cbbe94d75035de96b641c1a5b95034`，不代替最终主分支准入审查。

本轮没有新依赖、配置或数据结构。上述原件保留测试时 `98fb739` 的源码身份；最终发布源码只增加四份 Markdown 和路由索引 JSON 的已审变化，253 个其他文件逐字相同。新账本报告未记录原始退出码；root 对执行会话 20063 的 exit 0 观察作为后补说明保留，不回填原 JSON。后续镜像与实际发布见下一节。

## 2026-09-16 13:24:33（北京时间）完整账本 SOURCE 发布

最终 integration `82f4401ddbaa364674cec4df9f246879dbfba36d` 经非作者审查后合入 main `79faaf3940d7826243c95884b37ee9917eb3b4d0`，同树 `e627bb843bcf84024b097eaa5e486d98d437c17f`。实际安装 258 源文件／43 Markdown／44 static，107 方法／路径模板，43 户内表 + 2 平台表；manifest `7089ca8899929ec8eee8b705547943c697b21c684014855f92b7f5ca4fa8fb42`。发布目录 `/opt/family-dashboard-releases/source-20260916T052333559366Z`，`publishedAt=2026-09-16T05:24:33.636839+00:00`。

| 证据 | 本次实际范围 |
|---|---|
| BASE／镜像 | 发布前 255 文件逐字对应 Git `54c0854`，manifest `169c9621…`。固定父 `f82bc0fc…` 的 19 层上追加一层得到 `sha256:ea399441e6696bc29214842ab8c47e3db943714c1ae72a05ca1266bdc4a1b739`；完整配置摘要保持，父／子 70 运行文件分别核验，排除字节码，不运行 pip |
| 运行差异 | 仅 `finance_hub.py`、`static/finance-hub.js`、`static/finance-hub.css`、`static/product-shell.js`；SOURCE 精确允许路由索引 JSON 的配套工具变化已独立审查 |
| Linux | 新镜像实际执行与 Windows 相同的 10 模块 435 项后端，另执行 5 模块 275 项发布工具，各 0 failed / error / skipped；188 项只读测试支持文件与 958 项冻结测试依赖分别核对，不挂生产库、网络 none，容器清理通过 |
| 浏览器与适用性 | 七组 215 项来自上节固定运行组合；54 个必要原件引用及实际源码范围保留。253 文件保持，五份文档差异独立审查；原报告不改为新执行时间／Git 或补齐缺失的 provider 计数 |
| 实际 Docker 演练 | 两户、43+2 表、8 份资料和 3 库备份保持；真实控制器三阶段比较、44 static SHA、8 匿名权限 GET、旧登录和文件下载通过。13 项受管资源清理完成，为保护调用者镜像保留一个标签；没有恢复或生产写入 |
| 实际生产 | 单户／2 库完整备份核验；安装前、app 启动后、HTTP 后三次完整比较保持 schema、行、索引／触发器、序号和认证；配置保持，app 健康后才开放 sync/web，没有自动恢复 |
| 发布后读回 | 独立逐字核对 258 源文件、manifest、原环境摘要与三服务镜像／状态；服务器 TLS 验证下 healthz 200、新账本匿名 API 401、三项更新静态资源 200 且 SHA 匹配 |

本机私有证据目录 `source-ledger-20260916T044922913886Z-e60be56e` 保留原件，不包含在通用源码包：

- `build.json` SHA `e24bcc0506d63d80b069ee3010d0ed848991acbe8e703b945aaa5d64dcf6f4f0`。
- `linux-source-receipt.json` SHA `88d28b303f05f1462269e4e46b9f29db7341490711b7179bcef2b8444124dba4`，其新镜像结果及两组 JUnit／日志／镜像字节原件独立保存。
- `rehearsal-receipt.json` SHA `32d13cb766f15e1cef484c53fb3b8c49d80ca85e9b35fbbf530e441a6920278c`，绑定本轮实际控制器、seed、资料核验及清理报告。
- `production-deployment.json` SHA `7c2ad6def937cacc39ba33d6c8a214f66a13d7a0850e4baf305ca8495319e1de`；root 独立核验 SHA `80f84c638d9f64025d2fd8d455d212095ef2f0ad919098271ed9bc45045afd7b`；匿名 HTTPS 读回 SHA `4346efd8fe8d7bc15208eefbb893112a5977f51f529048c270f66cab54a364ad`。

READY 草稿保持 false，完整独立审查绑定草稿、升级后 READY 摘要与一次性 publisher 后才执行。证据目录包含 99 个去重原件与 5 类 envelope；103 个来源路径的原始字节不改写。数据相等只覆盖停写至 HTTP 核对窗口，正常同步重新开放后允许业务变化。真实新增云写、实体设备、可选模型、真实财务映射与生产恢复仍未因此完成验收。发布后的七份文档及文档检查器修订仅在本地交接，不改写服务器 manifest。

发布后的首个本地核验脚本错误地直接比较两种报告的 service 对象：控制器另含 `exitCode:0`，只读报告仅有 id、image、running、health、oom。原失败及诊断保存在 `post-verification-first-attempt.json`；修订后要求五字段逐一相同且控制器退出码为 0，再完成上述核验与 HTTPS 读回。没有重试发布、改写原报告或再次停止线上服务。

## 2026-09-16 11:39:20（北京时间）SOURCE 43→43 发布

已审 integration `ecc3edce9f714edbd830fcde796e2bb903878b06` 合入 main `54c08547e965ba9dd2bea1c8e8e8f34c1b0dabbe`，同树 `08c13778d26ab8cb7a68bcbb9f22ed72f9434ec3`。本次实际安装 **255 源文件、43 Markdown、44 静态资源、106 方法／路径模板、43 张户内表及 2 张平台表**；发布 manifest SHA `169c962136464f1ba8cbd134665e80e820a21664a0b812b1bf3628ddcba98b5d`。控制器以 `source-update` 完成发布，`publishedAt=2026-09-16T03:39:20.854732+00:00`，目录 `/opt/family-dashboard-releases/source-20260916T033817065173Z`。

| 证据 | 实际范围 |
|---|---|
| BASE 与构建 | 248 文件 BASE 逐字绑定 `daf5ab4`，manifest SHA `3db7f24ee5566b1535abbfaacad0daae0d07fcacee6eafe060edda073b4179ae`。从不可变父镜像 `14c7db7b…` 构建子镜像 `sha256:f82bc0fc147038ca3cdba546756192259a6f28c68c21621f75494ab9dc262ee6`，11:00:39（北京时间）完成；父层加一层，完整镜像配置、requirements 保持，无 pip，无生产操作 |
| 运行差异 | 仅两项既有根 Python 与五项静态文件；父／子各 70 项运行文件核验，子镜像 26 项 Python／requirements 与 44 项 static 匹配候选，字节码检查通过。没有 schema、数据迁移、依赖或配置变化 |
| Windows 受影响后端 | 13 个模块 406 passed，0 skipped / failed / error；保留原 JUnit、日志、前后依赖和原整段报告状态，与历史作者测试不重复相加 |
| 新镜像 Linux | 13 个受影响后端模块 406 passed，五个工具模块 269 passed，各 0 skipped / failed / error；分别保留 JUnit、日志、镜像运行字节证明，执行前后依赖相同。测试网络为 none、未挂生产数据，清理通过 |
| 浏览器 | `e0769e3` 时实际补测 187 项功能；历史 17+35+13=65 项在应用、实际脚本与辅助依赖相同后复用，共 252 项功能，工作台 59 项路由另列。89 份原始引用保留，0 页面错误／外站／服务商请求；不是当前候选上的一次全套重跑 |
| 真实 SOURCE Docker 演练 | 11:10:25（北京时间）完成；两户、每户 43 表、平台 2 表、8 份资料、3 库完整备份。实际控制器完成 43→43 升级，安装前／启动后／HTTP 后原行、schema、序号和认证保持，44 静态 SHA 与 8 匿名 401 通过；无恢复、无生产写入。13 项受管资源清理通过，保护调用者镜像而明确保留一个标签 |
| 实际生产 | 1 户及平台注册库，2 库完整组备份 `groupVerified=true`；安装前／启动后／HTTP 后三次核对全部 43 表的行、schema、索引／trigger、序号及平台注册数据保持。原 `.env` 和完整解析配置保持，`bytecodeExcluded=true`，未执行恢复 |
| 发布后读回 | 44 静态资源 200 且 SHA 匹配、8 匿名接口 401；app/sync/web 新容器均运行，app 健康。随后独立只读核对全部 255 源文件、manifest `169c9621…`、原环境 SHA `0c92e0ae…` 及 app/sync 镜像 `f82bc0fc…`，无覆盖配置或宿主 Compose 变量 |

首次 Linux 尝试在 11:03:22（北京时间）因测试支持目录挂载带入三份宿主 `deploy/__pycache__` 文件，被严格字节码门禁拒绝，**0 项用例执行，原报告保持失败**；源码散列未变。随后只在测试支持副本中按 manifest 精确复制 185 项文件，不挂载或改写镜像运行 Python/static，不放宽门禁；新输出 `linux-source-fixture-retry1` 于 11:19:02 完成上述 406／269 项。旧 1495 项后端和历史静态工具 187 项不充作新镜像受影响范围。

本机私有证据目录 `source-order-group-20260916T025846126274Z-0fe612be` 保留 `source.json`、`main-merge.json`、实际 `build.json`（SHA `336f39037522e8eeb99732320d95ba5907516c95ec6b8ff4dfa7d7a2d1270847`）、`root-build-verification.json`、`linux-source-fixture-retry1-receipt.json`、原失败与诊断、`root-source-rehearsal-verification.json` 及其控制器／seed／数据核验原件。浏览器原报告 `source-release-browser-verification-e0769e3.json` SHA 为 `2c27bd9944b83fb6d4fd061e424f1edeee5e97e1a72670e551fb68d25aedd966`。这些原件不改写为新的执行时间、源码或结果，也不随通用源码包分发。

实际生产原件 `production-deployment.json` SHA `0b2c92c96affb470f508801255a573dae7eaf51545a0772b27ef2a22e86994dd`；发布后只读原件 `static-production-base-20260916T033958860318Z.json` SHA `c83ce86730488437930ea0731e66ba7d4b615d64604c5465482450d3e1967c20`。数据相等结论覆盖停写至 HTTP 核对窗口，开放 sync/web 后允许正常业务变化；未用旧库覆盖新写入。本次文档变更只在独立本地分支交接，不能据此改变服务器精确源码身份。

root 独立核验原件 `root-production-verification.json` SHA `33155938c17f340ce8c1c111fa22815b31a9d5aff6343651fc5557a2f9e12484`；服务器发起并正常验证 TLS 的 `production-https-readback.json`（SHA `5f32a5a1a198633bb4f5e65401572d17b6f0b9cc8b7eda60f29050d18438c953`）确认域名 healthz 200、匿名 `/api/state` 401、`task-publish.js` 200 且候选 SHA 匹配，未登录或调用提供者；不代表用户手机浏览器或实体电视验收。

真实新增云写、银行／电商连接、私人真实账单确认、用户端公网浏览器、实体设备、可选模型和生产覆盖恢复仍未由此次发布完成验收。

## 前阶段：源码发布工具与组合验证

以下保留工具合入时的本地审查范围；后续新镜像与真实演练结果见上节。

工具作者固定提交 `4c05e5019aeb182f5ae23d183ec525dffc72ac60`，base 为 `9239754`；10 个授权文件、253 源文件。作者 Windows 269 项通过，包括保留的 187 项静态工具与 82 项新增源码模式用例。finance_hub 核对原 JUnit／日志／源码散列、原测试函数与断言 AST，并独立运行新增 82 项和真实临时 SQLite 24 项，共 106 passed。两组计数有重叠，不相加。

非作者同时验证真实 248 文件发布 TAR／BASE 清单，将已审业务 251 文件与工具差异组合成 255 文件映射，源码策略和依赖绑定通过；这是本地字段与字节预检，没有执行真实镜像或读写生产库。旧静态入口权限、共同锁、停止写者／全组备份／43+2 完整比较／HTTP 读回后再开放同步的顺序保持。

root 通过 Git 合入 integration `e0769e3cb9d341c73e5b21c1043eb943ddbf0be3`，再次执行五个工具模块，**269 passed，0 failed / error / skipped**。255 个源文件前后散列相同，原始报告为 `source-tools-combination-20260915T164219409390Z/verification.json`（SHA `d67c9fe7e1d3f7bae6492e2783cf9e2d4fc1096f4cc6acf5705d4e6322d93c6a`）。这次使用命令替身与临时 SQLite，不代表真实 Docker 演练。

在冻结的 `e0769e3` detached worktree 已实际补跑八组浏览器：文件 5、选表 11、投资 15、对账 6、异步保护 57、待办起步 32、采购核对 61，共 **187 项功能**；另有 **59 项工作台路由**。每组 255 源文件前后相同，0 页面错误、外网或服务商请求。新报告 SHA `2c27bd9944b83fb6d4fd061e424f1edeee5e97e1a72670e551fb68d25aedd966` 绑定 89 个原始引用；旧 65 项按相同运行依赖单独复用，总计 252 功能与 59 路由，仍是分段证据。下方 406 后端也保留其原固定运行范围。当时新不可变镜像 Linux 测试、双户 43→43 源码升级演练及生产准入尚未完成；后续结果见本文本次 SOURCE 发布记录。工具审查通过不是部署批准，流程见 [SOURCE-RELEASE](SOURCE-RELEASE.md)。

发布前只读核对发现：线上 `RELEASE-MANIFEST.json` SHA 为 `3db7f24ee5566b1535abbfaacad0daae0d07fcacee6eafe060edda073b4179ae`，248 源文件逐字等于已审 Git `daf5ab4e7adbddb994ca5c1fd745180d5d912c63`。与原运行发布 TAR 的 `7150c5c9…` manifest 相比仅八份后来已发布文档不同，Python/static/配置保持。后续构建／演练必须冻结当前 BASE，而不能重用早期 TAR 当作完整现状；此次核对无生产写入。

## 前阶段：淘宝订单分组与商品明细候选

共同 base 为 `9239754`；后端 `df9ef6b` 与界面 `4186bbe` 分别在独立分支／worktree 提交。root 在两个固定提交的 detached worktree 完成非作者审查，再合入 integration `b0acd800`。没有新 API、表、依赖或配置变化；43 张户内表和 2 张平台表的结构保持。

| 证据 | 实际范围 |
|---|---|
| 后端作者 | 6 个模块 221 passed，0 failed / error / skipped，34.94 秒；其中新增淘宝分组 48 项。覆盖几何拒错、原文保留、重传、状态变化、历史歧义、本人导出、电视限制及采购实付计额 |
| 界面作者 | 新契约浏览器 17 项，旧月份 35、对账 6、保护 57 项；四组 exit 0。新组使用明确标注的服务器侧合成明细契约，不算新 XLSX 解析器已经运行 |
| 非作者审查 | root 读完两个分支全部差异和测试，核验后端 20 份／界面 23 份原始证据引用及各 250 源文件散列；查看 360 像素手机截图；批准集成，不批准部署 |
| 真实输入只读预览 | 淘宝 299 单／394 条商品明细／0 错误；拼多多 910 行／0 错误。原文件 SHA 保持，0 真实确认、入账、外站或生产操作。默认 CNY、未知方向及退款状态仍未独立核实 |

原始失败保留：同一淘宝订单由成功变成关闭时，旧 flow 指纹会新增第二单，合成红测真实失败后才采用仅分组订单的稳定编号查找；新输入遇到旧状态或明细变化时标冲突，原记录保持。界面第一版在对账无候选时没有显示主记录明细，修订共用渲染函数后完成新组。中间版本及清晰度调整前的截图／报告不冒充最终版本。

集成 `b0acd800` 实际重跑 13 个受影响后端模块，406 passed、0 failed / error / skipped；新明细浏览器以 `--mode adapter` 执行真实合成 XLSX 解析流程，17 项通过，月份导航另 35 项通过。原金额浏览器在第 4 项期待旧“重复”文字而失败，实际显示的是金额冲突保留提示；这一轮整体 exit 1，原报告保持失败状态。

修订在另一个独立分支、以 `b0acd800` 为 base 完成。测试提交 `275c5a5` 仅将旧文案断言改为明确冲突提示，保留记录数量／8000 分断言并增加按原 ID 比较完整记录；应用与其余源文件逐字相同。该金额组 13 项完整重跑通过后，由 root 非作者审查并合入 integration `481c907`。未重复运行已经通过且依赖保持的 406／17／35 范围。

最终有效范围为 **406 项后端、65 项浏览器（17 + 35 + 13）**，属于保留原失败并精确重跑后的分段证据，**不是一次全量绿测**。源码共 251 文件、42 份 Markdown、44 静态资源；与首轮组合相比只改变一份测试。根文档随后独立提交审查，运行字节保持；main 合入仍须最终组合非作者审查。作者 221／115 项、上阶段 399／32 项不重复相加。

这一开发阶段的生产仍为 22:32 版本，当时没有确认真实订单、执行新镜像、云写、生产更新或恢复；静态发布工具不能承接这两个 Python 后端变化。后续 SOURCE 工具审查、镜像验证与实际发布见本文最上方记录。

## 前阶段：待办起步与 XLSX 声明兼容

共同 base 为 `daf5ab4`。以下本地验证与前次线上发布分别记录；历史 1495 项后端或 187 项静态工具结果不能直接作为已改变 reader 的本轮通过证明。

- 待办初版 `a3183ed` 作者完成 28 项起步、32 项连接返回、32 项待办发布检查，另有 59 条工作台页面记录。非作者随后通过实际临时 Flask/SQLite/Edge 复现两个起步动作同时在途时旧编辑器抢先打开的问题，初版未获合入批准；复现尾部临时库清理异常也保留原记录，不宣称整段清理通过。
- reader 合成测试先复现未使用 `Default Extension="bin"` 声明导致拒绝，再验证精确豁免及实际宏、二进制部件、非标准声明、外链、公式等拒错；只处理格式误判，不补填订单字段或猜测付款。
- 两份本地真实输入仅进入临时预览，未确认、未入正式财务库、未联网，原文件散列保持。淘宝工作表已可发现，但缺日期行导致整个预览没有确认令牌；拼多多可生成预览，缺币种时默认 CNY 仍须本人核对。样本与日志不进入 Git、通用源码包或服务器。

待办修订 `05d388d` 将两个起步动作同时锁定，失败时仅在原页面恢复按钮；作者重新完成 32 项起步（新增两种点击顺序及各自失败恢复）、32 项连接返回、32 项待办发布和 59 条页面记录。先前因测试登录数超过 16 个而使旧管理会话失效的测试准备错误已保留，重新登录虚构账号后完成最后的电视场景，不修改应用会话规则。

reader 分支 `fe2d043` 已由 root 独立审查：完整三文件差异、11 份原件散列、合成 JUnit 105 项、其余 247 源文件适用性均核对；批准合入 integration `f78c8ca`，未批准部署。

后续只读结构检查确认淘宝 95 条报错行全部是多商品订单续行：订单号、日期、状态、店铺、实付及运费六列具有一致的明确纵向合并区间，起始行完整，没有孤立缺日期行。394 商品行对应 299 个订单；当前 reader 尚未按订单组处理，不能逐商品复制订单实付，否则会重复计额。此检查没有改源码、原表或数据库，也没有补填字段。下一步应保留商品明细并按订单取一次实付，币种与退款仍不得推断。

集成版本 `83a1a71` 已实际重跑 12 个受影响后端测试模块：文件读取／选表、金额列、电商表头、账本、对账、导入月份、持仓及其副本、待办／日历发布与账户连接，共 399 项通过，0 失败、0 错误、0 跳过。使用临时合成数据；此范围不等于重跑完整后端套件，也不证明线上第三方账户成功。

同一集成版本另实际重跑起步浏览器 32 项，0 页面错误与外站请求，最终 249 个源文件前后散列保持。399 项后端与 32 项浏览器均 exit 0；原作者的 96 项与 59 条页面记录属于各自模块的已绑定证据，不重复相加。组合报告及 JUnit、浏览器原件保留在本机 test-results，未随源码分发。

原误判报告、修复后预览、合成红／绿测试与非作者问题记录分别保留。所有通过项仅说明各自固定源码范围；真实 OAuth、真实云写、完整淘宝导入、生产镜像和实体设备验收仍未完成。

## 2026-09-15 22:32:04（北京时间） 旅行入口与静态 43→43 发布

真实发布时间 `2026-09-15T14:32:04.509817+00:00`；镜像 `sha256:14c7db7ba55cb4bbbed919b0b14d4bb1b1670eeb07d9a6f90e05799220590dfb`，固定父镜像为下节历史资料版的 `651ecfd6…`。已审 integration `fec0e55` 合入同树 main `cd75b0b`。248 源文件、42 Markdown、44 静态资源、106 方法／路径模板、43 户内表 + 2 平台表；发布清单 SHA `7150c5c9f72f97e8892d9f7893432e3a43b7e162209031680d453e2b1666affb`。

| 证据 | 本轮范围 |
|---|---|
| 构建 | 固定父镜像只 COPY 完整 static；父层加恰好一层，完整镜像配置和非静态运行字节不变，无 pip、无数据卷 |
| 继承后端 | Windows 1495 = 1477 passed / 18 skipped，Linux 1495 = 1494 passed / 1 skipped；原始 XML、精准重试、去重集合和未变依赖逐项绑定。本轮未在新镜像重跑 1495 全套 |
| 新工具 Linux | 最终镜像 187 passed：构建 23、控制器与 SQLite 112、演练安全 52；无网络测试容器，源码与依赖不变，独立于旧后端结果 |
| 受影响 Edge | 旅行入口 27、草稿保护 32、确认保护 5，共 64；另有原旅行核心流程记录。临时 Flask/SQLite/真实 Edge、合成输入、零外站。此前资料版 129 项不相加、不作为变化 JS 的本轮验收 |
| 实际 Docker 静态演练 | 两户 43 表和平台 2 表，旧登录会话、8 份资料下载、3 库完整备份组保持；实际调用控制器，未执行恢复；13 个隔离资源清理通过 |
| 生产发布 | 实际 1 户及平台注册库，2 库完整组备份。安装前、启动后、HTTP 后三次 schema／行／BLOB／序号比较通过；无 warm、新表或预启动 worker |
| 内部读回 | 44 静态资源 SHA、8 匿名接口 401、三服务运行且 app 健康；22:32:15 追加核对全部 248 源文件、原配置和服务 |

失败记录分别保留：①首轮合成 Docker 演练在 HTTP 读回时发现剥掉 `static/` 导致 43 文件 404，其他健康与匿名检查通过；修正真实 Flask URL、补完整路由正／负对照、独立审查后重新构建与实跑通过。②生产首次在源码预检发现两份早期 Nginx 配置备份未列清单，正常拒绝；未创建发布目录、未停服、未操作数据库。核实未挂载后将旧备份保留归档，源码／配置／服务不变，再受控重试完成发布。两类失败不改写为成功，也不合并其检查数量。

原始证据包保留 `production-deployment.json`（SHA `38e39ec54d8e28e8f7ae19832857352c7f3045dbaedf374c1e2aa72989afe4ff`）、`root-production-verification.json`、`production-preflight-diagnosis.json`、`production-backup-archive.json`、Linux JUnit、浏览器原件与真实演练记录；私有路径和配置不随通用源码包交付。后续纯文档检查只证明文档与示例，不改写这些运行证据。

数据相等仅覆盖停写至 HTTP 核对窗口，开放 sync/web 后允许正常业务变化；未恢复旧库覆盖新写。此次没有真实新增云发布、私人财务候选接受或生产恢复，容器 loopback 读回不代表公网／实体设备验收。下面各节保持原历史范围与字节。

## 2026-09-15 20:23:00（北京时间）旅行资料与 42→43 发布

真实发布时间 `2026-09-15T12:23:00.979502+00:00`；镜像 `sha256:651ecfd6bdb65cf04bb8778c8657a8ec0f27a123940683a44a8b9931a5f22352`。当前 237 源文件、40 Markdown（含 README 与 AGENTS）、44 静态资源、106 方法／路径模板，43 户内表（41 业务 + 2 认证）及 2 平台表。已审 integration `b1981a4f579d4893d0694993e2c03434bcb45553` 经 Git 合入 main `670f34ff44757791f7263c5ee229ffde775838ce`。源码部署清单 SHA：`716223fddce4f2d8e8feee7d66c8651702d75d594ac07c6162baf898ecb2a017`；本次纯文档交接在此后单独审查，不能改写原运行证据。

| 证据 | 实际范围 |
|---|---|
| Windows | 最终去重 1495 项：1477 passed / 18 skipped。保留最初 full exit 1 与 3 项失败用例的精准重试，并结合环境控制器修订专项；不是一次全绿 full run |
| Linux | 最终去重 1495 项：1494 passed / 1 skipped。原完整同镜像 1461 项中旧控制器 66 项移出，以当前 100 项实际镜像定向测试替换；全 collect 校准最终集合 |
| 浏览器 | 资料 43、原细项 10、旅行执行 53、返回 23，共 129。临时 Flask/SQLite 与真实 Edge、虚构文件，零外站请求；原记录的实际依赖与最终源逐字一致后复用 |
| 两户 43 表 Docker 恢复 | 控制器 65、seed 15、verify 216 分别通过；2 户 + 注册库、8 份资料，22 容器／6 卷清理。恢复所需源码依赖保持原字节，复用同镜像原记录，不冒充再次重跑 |
| 单户 42→43 Docker 配置迁移 | 独立单户 + 注册库（2 DB），6 个 helper、9 个资源；旧令牌解密、美元符号／引号／换行配置保真、精确新表和原数据保持通过。不与上一行恢复统计相加 |
| 生产迁移 | 发布目录 `/opt/family-dashboard-releases/journey-documents-20260915T122200692493Z`。停 web，再停 sync/app、全组备份核验、snapshot→validate-backup→warm→check；只新增精确空表，原 42 表所有行／schema／序号保持；app 健康及再核对后启动 sync/web；原 .env 字节保持 |
| 内部读回 | `2026-09-15T12:23:44.550689+00:00`：237 源文件与 44 静态 SHA 匹配，8 匿名 GET 均 401；实际 1 户 43 表、平台 2 表，quick_check 正常，三服务运行、app 健康 |
| 既有来源 | 6 来源有成功、0 错误；最早 `12:23:01 UTC`、最新 `12:23:35 UTC`，均晚于发布。只是既有自然读取，不代表新的授权／云写／内容完整性 |

首次生产尝试在约 **11:30 UTC** 的 warm 阶段失败：Docker 原始 `--env-file` 与 Compose 的引号处理不同。完整备份已核验，只读比较确认数据库仍为旧 42 表、行／schema／序号／registry 不变，旧 222 源树和 218 文件 manifest 未安装替换；**11:35 UTC 恢复原服务，没有执行数据库 restore**。失败记录保留，不计入成功。

之后约 **12:00 UTC** 的合成配置 fixture 在创建任何资源前发现 Compose v2.40.3 将输出 `$` 再渲染为 `$$`，该次 0 资源、0 生产操作。两次修订 `684da03` → `2c9be6c` 均由非作者审查；最终经单次反解后与运行 app 环境逐项比较，用 UID 10001 的 0400 私有 JSON 注入，原 .env 不修改。历史 66／83 与当前 100 项控制流分别记录，fake runner 不当作真实 Docker 证明。

实际安全汇总 `journey-documents-env-v2-activation.json` SHA：`19171087f461b1e8823bbcf8a7952195671a42cbe11cb8fc855083d4ad0aaf47`；只读结果 `journey-documents-published-readback.json` SHA：`31b15e7d92e54c3894a0d0ee26ad392da02d937aa53768be8a39b27e165282c6`。原始 `journey-documents-env-v2-original-deployment.json` SHA：`e7ecbd309295062de3a57177b2b029722fcf25ffdbe65b20c17739a80056c5c6`，解析结果与安全汇总相等。私有证据不进入通用源码包。后续完整文档包、源码读回和备份记录由集成人另行完成；这里不预填其结果。

读回只经 SSH 到 app 容器 loopback GET 与 SQLite `mode=ro`／`query_only`，拒绝代理与重定向；未执行登录、OAuth、设备配对或提供者写入。公网浏览器的 SmartScreen 阻断未绕过；实体电视、真实银行／电商、新云发布、可选模型、真实凭证上传和生产覆盖恢复仍未因本次验收完成。恢复 Python 与成员失效 SQL 保持既有原字节，后续 43→43 零结构更新算法尚未实现验证，旧 42→42 示例不可用于当前库。

## 2026-09-15 16:54（北京时间） 独立 Docker 恢复演练

应用仍为 16:25 的 `f1e4cc…` 镜像；本次只增加运维工具、测试和文档，交接包为 222 文件／36 Markdown。无应用接口或 schema 变化。运行 ID：`efec152089624913aa858d85830e1ead`，UTC 08:53:01 开始、08:54:00 完成，实际进程 exit 0。

| 证据 | 已执行范围 |
|---|---|
| Windows 安全专项 | 13 passed；不调用 Docker，覆盖镜像输入、资源归属、旧证据目录及创建超时后的精确清理 |
| 实际 Docker | 65 项控制器检查、9 项 seed 检查、202 项 verify 检查均通过；分别记录，不相加为完整后端测试 |
| 合成数据与 HTTP | 两户、四成员、每户 42 表、平台 2 表、8 张照片、两台 TV；seed 80 次、verify 94 次实际回环请求 |
| 完整组恢复 | 原 backup.py 生成三库 manifest；原文档 Python 恢复到全新空卷，再逐户原样执行文档成员失效 SQL |
| 拒错 | 错误 SHA、缺失子户快照、注册目录与快照集合不一致均失败且未创建目标库 |
| 数据与权限 | schema、列、行、索引、外键及序号保留；只允许四类认证失效变化；4 旧 Cookie 和 4 旧 OAuth 状态被拒；新登录、跨户隔离、私有财务、已引用/未引用照片、原 TV 只读和虚构令牌解密通过 |
| 隔离与清理 | 22 个容器全部 network none、无发布端口、根只读；6 个新卷。28 项资源清理并读回，无遗留 |
| 来源绑定 | 72 个输入文件前后散列一致；镜像业务 Python、静态资源和 requirements 与候选逐字相同 |
| 线上服务 | 演练前后 app/sync/web 的容器 ID、镜像、运行及健康状态保持；不挂载生产卷，不读取生产 .env，不启动同步 worker |

恢复 Python SHA-256：`49897642eb676af7e897ff7fff6a2d8fa53a0d83ede2b28c92b703aeca9fffd8`；成员失效 SQL：`ca6512176839bc4acec35f59dbd6c85328e107a073378dd0d1b831326521fc23`。控制器：`477cc8417c6a2d99ac8514f4dbddfa9b6d0dea6f56d40dd4faf103302f4f040a`；fixture：`205b727f9c0e946ffced12c716b536f329379b1e71b651e33b11c75aceaac4cb`。

维护封装脚本首次在只读 Docker 状态格式化时退出，未开始演练；修正格式化后才完成上述运行，失败不计入通过。fixture 先完成临时真实 Flask 自检，不能把该自检等同 Docker 恢复；上表来自后续真实容器。虚构账号和 OAuth 状态使用明确的数据库 fixture，不代表真实授权成功；普通实体、财务、照片、TV 使用实际 API。运行报告不随通用源码包分发。

当前镜像的完整后端 1286 项沿用下方 16:25 记录；本次新增 13 项安全测试独立执行，没有声称重新跑完整后端或 UI。实际生产覆盖恢复、异地恢复、物理磁盘损坏、真实令牌与外部队列核对仍未完成。复跑入口见 [RECOVERY-REHEARSAL](RECOVERY-REHEARSAL.md)。

## 2026-09-15 16:25:03（北京时间） 旅行执行与订单兼容发布

镜像 `sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d`；218 源文件、35 Markdown、101 路由、42 张户内表及平台 2 表。本次从 15:10:00 版本执行 42→42 无结构更新；下面历史记录的测试和迁移不计入本轮。

| 证据 | 本次实际范围 |
|---|---|
| Windows 完整后端 | 1268 passed / 18 skipped，共 1286 项 |
| Linux 最终镜像 | 1285 passed / 1 skipped，共 1286 项；测试容器无外网、无生产配置或数据卷 |
| 新旅行执行浏览器 | 53 项通过，真实临时 Flask/SQLite/Edge，88 项依赖散列前后一致，11 张合成数据截图 |
| 原旅行与发布浏览器 | 8 组最终源码回归通过：旅行、细项、返回预算、导入、草稿、确认、待办发布、日历发布；逐组日志与网络记录绑定 |
| 发布与数据 | 停止入口和旧写进程，验证全家庭备份；逐表 schema、列、行及内部序号保持；启动核对后恢复 sync/web |
| 内部读回 | 42 静态资源匹配、18 个匿名受保护 GET 返回 401；三服务运行且 app 健康，配置不变 |

新增 `localChangesPending` 的 44 项后端专项与订单表头 24 项已计入完整后端，不另相加。此前 361 项关联后端只是中途专项，不替代上表完整执行。浏览器首轮发现返回提示被刷新清除，后又发现被负责人筛选隐藏的事项误提示已删除，均修复后按最终源码重跑；测试等待条件修正的历史失败也保留，不计为通过。

所有浏览器外站请求、意外服务商请求和真实云写均为零。真实新增云发布、财务来源完整覆盖、模型、公网浏览器、实体电视及生产恢复演练仍未验收。数据相等仅指停写到启动核对窗口，恢复正常同步后业务可以变化；未用旧快照覆盖发布后的正常数据。


## 2026-09-15 15:10:00（北京时间） 财务月份、独立消费观察与导出保护发布

镜像 `sha256:65a71881894ed85ff7d88b818372962a42eaf1ead4610338de3318f0decc6c3c`；214 源文件、34 Markdown、101 路由、42 张户内表及平台 2 表。下方 13:43:04／`5e338ef…` 为历史例行版本，测试与迁移数量不跨版本相加。

| 证据 | 本次实际范围 |
|---|---|
| Windows | 1200 passed / 18 skipped，完整 1218 项 |
| Linux 最终镜像 | 1217 passed / 1 skipped，完整 1218 项；挂载冻结测试／部署配置，不挂生产配置或卷 |
| 财务组合浏览器 | 10 组 222 项；真实临时 Flask/SQLite/Edge、虚构输入、零外站请求和页面错误；已发送请求与 GET-only 读回分别验证 |
| 迁移保留 | 先停 web 再停 sync/app，整组备份校验后逐户串行初始化；仅新增 finance_spending_observations、finance_spending_receipts 两空表及约定索引，旧 40 表／平台注册表／SQLite 内部序号保持 |
| 启动与内部检查 | app 健康并读回后开放 sync/web；42 静态资源匹配，18 个匿名受保护 GET 返回 401；配置及前后完整备份组核验通过 |
| 离线恢复与部署文档 | 激活 165、控制器 119、42→42 零结构文档 79 项；临时 SQLite／文件和命令替身，不是 Docker 或生产恢复实测 |

| 实际脚本 | 功能检查 | 本次组合证据 |
|---|---:|---|
| `tests/browser_finance_import_navigation_check.py` | 35 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_finance_amount_columns_check.py` | 13 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_financial_files_check.py` | 5 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_financial_sheet_discovery_check.py` | 11 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_finance_reconciliation_check.py` | 6 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_finance_reconciliation_guard_check.py` | 57 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_finance_source_check.py` | 5 | 测试观察修正后复跑 |
| `tests/browser_spending_observations_check.py` | 27 | 测试观察修正后复跑 |
| `tests/browser_data_portability_check.py` | 4 | 首轮通过，完整依赖相同后保留 |
| `tests/browser_data_portability_guard_check.py` | 59 | 首轮通过，完整依赖相同后保留 |

首轮来源桥因旧断言仍要求展示原始 503 文本而未完成；改为当前固定安全提示，保留原草稿／重试断言后 5 项通过。消费观察首轮在 21 项后因固定毫秒等待尚未捕获预览请求而失败；改为有界条件等待并保留 traceback 后 27 项通过。没有为此改运行代码。两组失败报告／日志按原字节保留；其他八组 190 项的全部 runtime/config/deploy/static 与各自测试依赖均与最终清单相同，原报告、日志、网络记录继续绑定。不能把首轮部分成功当完整通过。

**另有 1 项观察限制，不计入 222 项保护通过。** 导出最终 /me 已在服务端读取成员 A 后，另一标签页仅将 Cookie 切到 B，原页尚未收到身份事件，仍可能触发 A 的副本下载。详情见 [PORTABILITY](PORTABILITY.md)。有限次身份 GET 不与下载原子化，不能声称所有跨标签切换都已被阻断。

六个既有日历／清单来源在发布后自然同步成功，只证明这些读取。本机已用现有报告准备源码外消费观察候选，尚未上传或确认导入，也未启用自动刷新。资产来源完整映射、贷款余额日期、真实新云写、银行／券商、模型、公网浏览器和实体电视仍未验收；未增加邮箱任务、后台自动确认或无人值守上传。消费观察不改原资产基线与共享小计，不写实际支付账本。

数据库保留比较限定停写初始化与启动读回窗口，服务开放后正常业务可以变化；提交后不盲目用旧快照覆盖。发布后文档保留 BASE/RESULT，通用包不含 test-results、密钥、数据库或真实私人来源。历史 37→40 迁移及其测试见下节。

## 2026-09-15 13:43:04（北京时间） 家庭例行计划发布

镜像 `sha256:5e338ef586fbc0e7b2f2efb842b08b464e33f1b3a4d8be9eb1996100fb371f6e` 新增家庭共享例行计划，保留采购核对、同步状态与此前全部模块。12:11:36 / `1167dffd…` 采购版和更早各节仍为历史记录；各次测试、迁移和浏览器范围不相加。

| 证据 | 本轮范围 |
|---|---|
| 源码与接口 | 207 源文件、33 份 Markdown、101 个 Flask 方法/路径模板、40 张户内表 + 平台 2 表、42 静态。最终归档、接口实例化及容器读回分别绑定实际证据 |
| Windows | 1136 passed / 18 skipped，完整 1154 项 |
| Linux 最终镜像 | 1153 passed / 1 skipped，完整 1154 项；绑定不可变镜像、源码及挂载测试清单，不含生产卷／配置 |
| 本轮浏览器 | 三组：98 项功能检查，另 59 条工作台页面／视口记录，见下表 |
| 停写迁移 | 停止 web，再停止旧 sync/app。验证注册目录和完整家庭备份组后串行初始化；原 37 表及 SQLite 内部序号不变，只新增 household_routines、routine_occurrences、routine_receipts 三空表与冻结索引 |
| 启动读回 | 三表无预置业务，用户未创建计划前不生成事项；app 健康且完整读回匹配后才开放 sync/web。环境、旧源码／镜像及前后备份依实际证据核对 |
| 内部访问 | 42 静态资源按镜像/回环 HTTP 字节核对，17 个匿名受保护 GET 拒绝访问；这些检查不登录或写真实业务 |
| 失败恢复 | 激活／成组恢复 151 项，控制器 119 项；仅离线临时 SQLite/文件和命令替身，没有真实 Docker 回滚或生产恢复 |

Linux 首轮完整执行得到 1136 passed / 1 skipped / 17 errors；17 项均为测试夹具初始化时读取 `/app/pytest.ini` 的 `FileNotFoundError`。原镜像与业务源码未改，私有测试 runner 已补齐该配置的只读挂载并开始完整重跑。首轮不是全套通过；上表最终 Linux 统计须以完整重跑的终态证据填入，不用首轮的部分成功替代。

| 实际执行脚本 | 功能检查 | 页面／视口记录 |
|---|---:|---:|
| `tests/browser_household_routines_check.py` | 77 | 0 |
| `tests/browser_assistant_actions_check.py` | 21 | 0 |
| `tests/browser_product_shell_check.py` | 0 | 59 |

例行后端专项 81 项（38.31 秒）及独立跨模块 17 项（14.00 秒）是模块阶段的实际记录，不额外累加到最终完整后端数量。对应依赖散列与最终组合的关系由终态报告核对。专项覆盖月末／闰年／2100、每日每周间隔、原节奏、当前事项独立修改、删除后 missing、跳过保留原项及固定历史、暂停／恢复／归档、容量、日期和版本 CAS、原回执重放、已撤销会话、线程并发、空闲不取写锁、助理只读及共享导出。跨模块使用 fake Microsoft／Google 完成回流、真实临时采购核对与旅行迁期，不是真实云写。

创建／更新等操作先预览明确确认，GET 和助理 brief 不推进、不写业务数据；新事项直接写本户 entities，不调用默认云主清单写入器。下一期采购重置实际金额／照片／完成状态，不复制旅行、付款或来源标识。每期任务若需发布到云，仍单独授权、预览、确认。

发布后既有六来源自然同步成功仅证明这六个已选来源的读取；真实新增云写、私人财务完整映射、银行／券商、模型、公网浏览器和实体设备仍单独待验收。保留既往组织安全策略阻断，不绕过或用容器内部检查替代公网。数据保留比较限定在停写初始化及 app 启动读回窗口；服务恢复后正常成员／同步可以写新数据，失败时不可盲目用旧库覆盖。恢复须使用相配源码／镜像／密钥及整组库，目标家庭旧成员会话先失效，核对后才重启 sync。

维护者完整证据按本轮 ready、release-verification、冻结 manifest 与原报告保存；通用源码包只含源码、测试和脱敏文档，不含 test-results、真实配置或数据库。发布后文档刷新另有 BASE/RESULT，不把刷新后整包字节等同测试归档。

## 2026-09-15 12:11:36 采购实付核对发布

2026-09-15 12:11:36（北京时间）已发布本人付款到共享采购的实付核对，镜像 `sha256:1167dffd3b7e234d43460442acfe0d30959370c90c7e8147a1b30baa0e2380b5`。保留同步状态、电视显示、投资、成员会话及所有既有模块。下方 10:43:53 / `6882d2a…` 及更早各节是独立历史记录，不将不同版本的测试和迁移结果合并。

| 证据 | 本轮精确范围 |
|---|---|
| 源码与接口 | 200 个源码文件、32 份 Markdown；98 个 Flask 方法/路径模板，另有 WSGI 家庭入口；37 张户内表（35 业务 + 2 认证）与 2 张平台表 |
| Windows 后端 | 1035 passed / 12 skipped，完整收集 1047 项；跳过不是通过，不与 Linux 相加为独立测试 |
| Linux 最终镜像 | 1046 passed / 1 skipped，完整收集 1047 项；测试和实际发布镜像、归档与清单绑定，隔离测试不挂载生产配置或数据卷 |
| 本轮浏览器 | 3 组：118 项功能检查，另有 59 条页面／视口记录，具体脚本见下表 |
| 停写初始化 | 先停止 web，再停止旧 sync/app；核对全部已登记家庭与两张平台注册表。各户原 35 张表的 schema、旧列、行与 SQLite 序号保留，只允许新增 `hub_shopping_settlements`、`hub_shopping_settlement_receipts` 两张空表及约定索引 |
| 启动与数据保留 | 完整备份组的清单、文件字节／哈希和 SQLite 摘要核验后串行初始化，候选 app 启动后再次读回，符合允许变化才开放 sync/web。环境和全部原有数据保留；37 表不是上一版的“全库零 schema 变化” |
| 发布后内部核对 | app 健康、sync/web 运行，发布前后备份组已验证；镜像内及 app 容器回环 HTTP 的 40 个静态资源匹配清单；16 个匿名受保护 GET 返回 401。没有通过本次检查登录或操作真实业务 |
| 离线失败恢复 | 激活／成组恢复 138 项；发布控制器 119 项。只使用临时合成文件/SQLite 和命令替身，不代表真实 Docker 回滚或生产恢复 |

| 实际执行脚本 | 功能检查 | 页面／视口记录 |
|---|---:|---:|
| `tests/browser_shopping_settlement_check.py` | 61 | 0 |
| `tests/browser_finance_reconciliation_guard_check.py` | 57 | 0 |
| `tests/browser_product_shell_check.py` | 0 | 59 |

采购专项使用真实临时 Flask/SQLite/Edge 与虚构家庭，覆盖采购和账本两入口、订单进入原对账再返回、搜索分页与聚焦记录、零金额、独立已买到、预览不写、确认后原采购读回、重复确认、更新及两种解除、退款和缺源提示、409/503 草稿、迟到响应和成员／家庭／TV／演示隔离。三主题在 360／768／1440 像素截图检查，没有将账单标题、来源或回执投影到共享采购。

专项首轮到 59 项后因测试夹具旧登录导致电视配对断言失败，修正合成登录及补充分页场景后完整重跑 61 项通过；旧记录保留，不将其中 59 项再加到最终 61 项。后端局部 44 项与跨模块 10 项属于完整套件的范围，不重复累加到 1047 项；测试依赖与最终源码的对应关系由本轮聚合证据记录。

所有浏览器范围限定于回环地址、临时数据库与虚构数据；外部请求、真实云写和生产业务写入均不在该验收范围。程序只把本人确认的 `actual/done` 更新到共享采购，原账本、预算、公共余额、旅行 `paid`、原实体 ID 与照片应保留。来源后来变化仅提示重新核对，不自动共享退款或改变“已买到”。个人 ZIP 包含本人的关联和业务回执白名单，排除伴侣私密、凭据和预览签名。

本轮数据保留结论限定在入口与写进程停止后到 app 启动读回的受控窗口；正常运行后成员与同步可继续产生变化。开放服务后的失败不能盲目恢复旧库。恢复旧备份仍需在重新开放前使目标家庭旧成员会话失效。备份是同服务器副本，没有据本轮执行生产恢复或证明异地容灾。

依据维护者 `shopping-settlement-ready.json`、`shopping-settlement-release-verification.json`、冻结源码清单及对应原始报告。发布时间、镜像、Linux 终态和数据保留声明只来自最终发布证据；源码包包含可复跑测试与脱敏文档，不包含私人运行证据、凭据或数据库。发布后文档刷新另留 BASE/RESULT，不声称更新后的文档字节与测试归档相同。

公网浏览器历史组织 SmartScreen 阻断仍保留；本轮没有绕过策略或将容器内部检查冒充公网通过。既有 Microsoft／Google 读取的历史成功不证明新增云日历／待办写流程已真实验收；银行、小荷包、券商实时连接、真实私人来源映射、可选模型、实体电视和长期跨设备使用仍需各自授权与验收。采购核对也不代表执行实际付款、转账或自动抓取银行账单。

## 2026-09-15 10:43:53 同步新鲜度与问题中心发布

2026-09-15 10:43:53（北京时间）已发布同步新鲜度与问题中心，保留电视、投资、会话及此前全部模块；镜像 `sha256:6882d2a2009ce4ef378cc2448026f5a7edc4b63fd14e440bc104fcdd6d7e159c`。Windows **981 passed / 12 skipped**，Linux **992 passed / 1 skipped**；两端完整收集 993 项；本轮 3 组浏览器记录：131 项功能检查，另有 59 条页面／视口记录；两类不混算。停止入口和旧写进程后核对 35 张户内表与 2 张平台表，表、列、schema 对象、行及 SQLite 内部序号完全保留；初始化未增加表或列。发布前后完整备份、环境保留、三服务运行与 app 健康已核对；6 个既有来源有发布后成功记录，38 个静态资源匹配，15 个匿名受保护 API 返回 401。公网浏览器、两台实体电视、真实新增云写、私人来源映射和可选模型调用仍单独待验收；没有执行生产恢复或宣称商业化就绪。

| 证据 | 精确范围 |
|---|---|
| 源码与接口 | 193 文件、31 份 Markdown、95 个 Flask 方法/路径模板；35 张户内表与 2 张平台表，无新增表或列 |
| 后端 | Windows **981 passed / 12 skipped**，Linux **992 passed / 1 skipped**；两端完整收集 993 项 |
| 停写后保留 | 全家庭集合与注册表不变；所有旧表、列、schema 对象、行和 SQLite 内部序号比较一致。候选 app 启动读回通过后才开放 sync/web |
| 发布后核对 | 停止入口和旧写进程后核对 35 张户内表与 2 张平台表，表、列、schema 对象、行及 SQLite 内部序号完全保留；初始化未增加表或列。发布前后完整备份、环境保留、三服务运行与 app 健康已核对；6 个既有来源有发布后成功记录，38 个静态资源匹配，15 个匿名受保护 API 返回 401 |
| 失败恢复 | 激活／成组恢复 114 项，控制器标签保护 119 项；均为临时 SQLite 或 AST/命令替身的离线模拟，没有真实 Docker 回滚或生产恢复 |

本轮浏览器逐组列出，历史数量不相加：

| 实际执行脚本 | 功能检查 | 页面／视口记录 |
|---|---:|---:|
| `tests/browser_sync_health_check.py` | 63 | 0 |
| `tests/browser_product_shell_check.py` | 0 | 59 |
| `tests/browser_tv_display_check.py` | 68 | 0 |

所有浏览器只在回环地址使用虚构家庭和临时数据库；真实服务商写入、真实财务、实体电视及公网浏览器不在范围内。新问题中心只读已有成功和错误记录，页面正常不能证明云内容完整；它不会自动重试、刷新令牌或写入第三方平台。

“数据完全保留”限定于入口和写进程停止后的初始化、启动读回比较；恢复正常运行后真实成员或同步可以继续写入，不把两个运行中快照声称为永久相等。2026-09-15 09:47:39 电视新增列的证据保留在下方历史章节；本次不再次迁移该列。

## 2026-09-15 09:47:39 电视显示设置发布

2026-09-15 09:47:39（北京时间）已发布每台电视的卡片排序／显隐、主题、密度与手机预览，保留此前全部模块；镜像 `sha256:3998d415c39493d86a3ccfadc5ab1a722267f12a84bcda74eb5eaf452cc8da3a`。Windows **948 passed / 12 skipped**，Linux **959 passed / 1 skipped**；两套完整收集 960 项。四组受影响浏览器记录分为 **114 项功能检查**与 **59 条页面/视口记录**，不混算为相同场景。停止入口及旧写进程后核对全部既有表、设备旧列和平台注册数据保留，仅增加 devices.display_layout；发布前后完整备份核对通过，环境配置保留、三服务运行且 app 健康。6 个既有来源有发布后成功记录，36 个静态资源匹配，14 个匿名受保护 API 返回 401。公网浏览器、两台实体电视、真实新增云写、私人来源与模型接入仍分别待验收；本轮未执行生产恢复。

| 证据 | 精确范围 |
|---|---|
| 冻结源码 | 187 文件、30 份 Markdown；94 个 Flask 路由模板、35 张户内表 + 2 张平台表；新列为 devices.display_layout |
| 后端 | Windows 948 passed / 12 skipped；Linux 最终镜像 959 passed / 1 skipped，两端完整收集 960 项 |
| 新电视浏览器 | 68 项，含两块设备独立、1—5 张卡片、手机/720p/1080p/4K、并发保存、迟到响应、身份及隐私；9 张截图 |
| 受影响旧浏览器 | 配对 35 项、首页布局 11 项；工作台另有 59 条页面/视口记录及其业务断言。各组绑定实际执行脚本及未变的运行依赖 |
| 初始化保留 | 停入口和旧写进程后的真实完整快照比较：平台注册表、35 张表的所有旧行及设备旧列保留；仅增加默认为空 JSON 的布局列 |
| 备份与运行 | 发布前后完整备份按散列和 SQLite 完整性核对；app 健康、sync/web 运行，环境未变，既有 6 来源有发布后成功记录 |
| 内部访问 | 36 个静态资源的镜像/HTTP 字节匹配；14 个匿名受保护 API 拒绝；检查未访问公网或真实业务写接口 |
| 失败恢复 | 53 项离线激活/成组恢复模拟；另有 71 项发布控制器标签保护模拟。没有执行真实 Docker 回滚或生产数据库恢复 |

新浏览器首轮因隐藏元素定位失败，修正测试定位后完整重跑；既有配对测试原先期待保存后关闭弹窗，已按新编辑器保留并读回的契约更新后完整重跑。旧失败保留，不与最终通过数量相加。后端早期错误测试路径已纠正，最终套件无失败。

发布后正常用户和同步写入可以改变实时摘要，不能把前后两次运行快照描述为始终完全相同；数据保留证明来自停止写进程后的逐表、逐旧列比较。隐藏卡片只是显示偏好，私有账户/消费/投资权限仍由后端约束。实体电视、公网浏览器、真实新增云写、私人来源映射及模型调用保留未验收状态。

## 2026-09-15 08:56:01 投资持仓与首次电视配对发布

2026-09-15 08:56:01（北京时间）已发布投资持仓文件导入、本人导出扩展及首次电视配对入口，保留成员会话与历史功能，镜像 `sha256:f3c695c24cf95385be26142332cef4c7a13ce5043232073121b71a1eced170ae`。Windows **904 passed / 12 skipped**，Linux **915 passed / 1 skipped**；两套完整收集 916 项，本轮重跑 8 组临时浏览器共 **175** 场景通过。受保护数据、全部既有表内容与环境配置保留，服务健康；发布前后完整备份已核对；6 个既有来源有发布后成功记录，内部 34 个静态资源匹配、13 个匿名受保护 API 拒绝访问。这些结果不替代真实银行／券商格式、生产持仓导入、新增云写、真实模型、OAuth 公网回跳及两台实体电视验收。公网浏览器的组织策略阻断保留其历史范围，不称本轮公网 UI 通过；没有执行生产恢复。

本次测试及部署绑定同一最终镜像。冻结源码 181 文件、29 份 Markdown，94 个 Flask 方法/路径模板、35 张户内表（33 业务 + 2 认证）与 2 张平台表。下列 8 组都是本次组合源码的实际运行；07:58 的 14 组 280 和更早候选专项保留其历史范围，不与本轮相加。发布后仅文档刷新另留 BASE/RESULT 哈希，不能声称刷新后的整包与测试归档哈希完全相同。

| 浏览器脚本 | 本轮范围 | 实际通过场景 |
|---|---|---|
| `tests/browser_investment_import_check.py` | 持仓文件预览、确认与回读 | 15 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 |
| `tests/browser_finance_reconciliation_check.py` | 财务关联与对账 | 6 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账与身份迟到响应保护 | 57 |
| `tests/browser_financial_files_check.py` | 既有文件导入 | 5 |
| `tests/browser_financial_sheet_discovery_check.py` | XLSX 工作表发现与选择 | 11 |
| `tests/browser_member_sessions_check.py` | 成员登录设备与撤销 | 33 |
| `tests/browser_tv_onboarding_check.py` | 首次电视配对入口与返回 | 35 |

前一正式镜像为 `sha256:6251c9bfe9eab14c70da7ef4d07836e08ff5195c9a60f73983ac6438572bf639`。维护者实际发布证据为 `investment-import-release-verification.json`，其中的部署时间、镜像、保留与健康检查绑定本次记录；私有运行证据和原始金融输入不随通用源码分发。完整备份／恢复指导仍需配合已发布的成员会话失效步骤；本轮没有实际生产恢复。

## 投资与电视首次配对候选验收

以下为投资候选阶段记录，当时尚未部署；现已完成上方 2026-09-15 08:56:01 的正式发布与完整验收。开发阶段新增 3 路由、4 户内表，未增加第三方依赖；作者投资后端／既有 finance_hub／本人导出 130 项及最终金额／坏表头独立复核 12 项通过。投资交互 15 场景使用临时 Flask/SQLite/Edge 和虚构 CSV/XLSX，手机与桌面截图人工检查。上述局部结果不与本次 916 项和 8 组 175 相加；当时仍在运行的 Windows／Linux／组合浏览器最终结果见上方发布节。

首轮界面发现按钮高度被既有主题覆盖、步骤切换保留旧滚动位置，已修复并重跑；一次开发期间源码变更的运行不计为最终通过。旧浏览器数量和旧镜像只是历史证据。当时的发布门槛为完整套件、同源镜像、文档、备份、权限及发布后读回；本次最终结果见上方发布节。

## 2026-09-15 07:58:24 成员登录设备与会话撤销发布

2026-09-15 07:58:24（北京时间）已发布成员登录设备、服务端会话撤销、认证代次与缺库恢复保护，镜像 `sha256:6251c9bfe9eab14c70da7ef4d07836e08ff5195c9a60f73983ac6438572bf639`。Windows **809 passed / 12 skipped**，Linux **820 passed / 1 skipped**；两套完整收集 821 项，14 组临时浏览器共 **280** 场景通过。受保护数据与环境配置保留，发布前后完整备份已核对；6 个既有来源有发布后成功记录，内部 32 个静态资源匹配、12 个匿名受保护 API 拒绝访问。真实新增云写、OAuth 公网回跳、实体设备与真实模型仍须单独验收；未导入新的私人财务来源、未执行生产恢复。

本次最终存储修订完整 Windows/Linux 均收集 821 项；测试与发布使用同一最终源码/镜像。源码归档 173 文件、28 份 Markdown，91 个 Flask 方法/路径模板、31 张户内表（29 业务+2 认证）及 2 张平台表。发布状态的后续文档刷新另留 BASE/RESULT 清单，不声称测试归档与刷新后整包哈希相同。

- 初次 Windows：首次 Windows 完整收集 815 项：802 通过、12 跳过、1 失败；无 Cookie 且原家庭缺库时恢复入口返回 503，预期 303。保留失败记录，未作为最终验收。
- 初次 Linux：旧 6d430 镜像因上述已确认缺陷被主动中断，测试容器退出码 137，Linux 全套未完成；这是独立测试中止，不是通过或生产容器失败。
- 未发布的中间候选：pre-storage 候选的 Windows 816 项为 804 通过、12 跳过，280 个浏览器场景通过；随后独立审查发现缓存家庭缺库会创建零字节数据库，故未发布。最终 storage 候选重新完成 Windows、Linux 和 280 浏览器验证。

上述失败、中断和被拒候选保留原结论，不计为最终通过，不与最终统计相加。

| 浏览器专项 | 范围 | 本轮通过场景 |
|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行文件导入保护 | 31 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 |
| `tests/browser_journey_details_check.py` | 旅行 v2 时间细项 | 10 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 |
| `tests/browser_financial_sheet_discovery_check.py` | XLSX 名称发现与选表 | 11 |
| `tests/browser_assistant_journey_brief_check.py` | 助理简报到旅行向导 | 25 |
| `tests/browser_assistant_actions_check.py` | 助理原事项处理与返回 | 21 |
| `tests/browser_member_sessions_check.py` | 登录设备与会话撤销 | 33 |

以上 14 组共 280 场景属于最终组合源码；独立审查和此前候选通过数不重复加入。会话验证包括复制 Cookie 撤销、固定期限、legacy 撤销记录保留、浏览器认证代次、OAuth 网络前后检查、改密与绑定保留、成员/家庭/TV 隔离、私有导出排除认证数据、界面迟到响应。存储验证包含 cached/uncached 与 Cookie 有无、连接前移除数据库、首次根/子户初始化顺序。`mode=rw` 仅用于成员会话连接，不宣称全站任意文件删除竞态均已加固。

受保护数据与环境配置保留，发布前后完整备份均已核对；6 个既有云来源有发布后成功记录，内部 32 静态资源及 12 个匿名受保护接口通过读回。没有新增私人来源导入、真实云写或生产恢复；真实模型、OAuth 公网回跳、实体设备与长期使用仍分别待验收。恢复旧备份需先使恢复家庭旧会话失效，不能把备份保存的旧状态视为最新撤销状态。

依据维护者 `test-results/member-sessions-release-verification.json`；原失败、中断、最终测试、备份及发布证据留在私人运行目录，不随通用源码分发。以下 7b 及更早章节保留各自历史范围。

## 2026-09-15 06:50:21 工作表选择与旅行简报组合发布

2026-09-15 06:50:21（北京时间）已发布 XLSX 工作表选择与助理旅行简报，镜像 `sha256:7b775a7a9aa106c83600d8e0bfba22f79f39a71f54f70e85b2d5d638e63796f7`。Windows **742 passed / 12 skipped**，Linux **753 passed / 1 skipped**，两套均完整运行测试集，各收集 754 项；13 组临时浏览器全部重跑、共 **247** 场景通过。app 健康、sync/web 运行，6 个既有来源有发布后成功记录；容器内部 30 个静态资源匹配、11 个匿名受保护 API 返回 401。真实模型调用、新增云写、OAuth 回跳、私人财务完整覆盖、公网浏览器及实体设备仍分别待验收；未导入新的真实私人来源或执行生产恢复。

- 本轮完整 Windows：742 passed / 12 skipped，301.724 秒；完整 Linux：753 passed / 1 skipped，618.77 秒。实际收集均 754，不是沿用 05:47 的 706 镜像后端例外；Windows POSIX 跳过在 Linux 执行，Linux 缺 Docker CLI 的检查在 Windows 执行。
- 首次 Linux 尝试退出码 1：733 passed、18 failed、1 skipped、2 errors。首次隔离测试的 192 MiB `/tmp` 临时盘耗尽，日志报告 database or disk is full；维护者保留失败记录，改用独立磁盘临时目录挂载 `/tmp` 后，仍以相同 immutable 镜像、相同源码及 384 MiB 内存上限完整重跑，未挂生产环境或数据卷。这是测试资源修正，首次失败不改记为通过，两次计数不相加；上行只计最终完整重跑。
- 测试与发布镜像相同；165 文件归档、运行／测试／部署散列和 Linux 挂载内容关联。27 份 Markdown 中的发布状态后续仅文档更新，归档 manifest 与最终文档 manifest 分别保留，不声称两份完整包哈希一致。88 个 Flask 路由模板、额外 WSGI 家庭入口、29+2 张表；无新依赖。
- 工作表发现验证说明页／空表／公式表恢复、选表清金额与旧令牌、发现模式拒绝确认、全部 XML 与外链边界、成员／家庭与迟到响应保护。名单不是金融单元格校验证明。旅行简报验证明确字段、保守人民币总额、外币／人均／约数留空、模型白名单、三步补齐、重新整理／继续与原向导最终确认；不执行真实模型或云写。

| 浏览器专项 | 范围 | 本轮通过场景 |
|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行文件导入保护 | 31 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 |
| `tests/browser_journey_details_check.py` | 旅行 v2 时间细项 | 10 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 |
| `tests/browser_financial_sheet_discovery_check.py` | XLSX 名称发现与选表 | 11 |
| `tests/browser_assistant_journey_brief_check.py` | 助理简报到旅行向导 | 25 |
| `tests/browser_assistant_actions_check.py` | 助理原事项处理与返回 | 21 |

上述 13 组、247 场景全部在本轮组合源码重新运行。使用临时 Flask/SQLite/Edge 和假模型；每组额外在 loopback 网络守卫下执行，守卫报告与原专项报告分别记录并核对散列，外站请求、真实云写、生产写和页面错误均为零。合入前独立 51 API、25/21/5 浏览器及独立审查不重复加入总数，也不把本机结果推广到真实模型质量或全部账单变体。

- 旧 app/sync 停止记录：sync exit=0、OOM=False；app exit=0、OOM=False，耗时 1.99 秒；按实测退出码记账，不把超时或 137 解释为平稳停止。
- 停写后备份 `manifest-20260914T224942213586Z.json`；发布后备份 `manifest-20260914T225056304986Z.json`。每组 2 库，对应 1 户及平台目录，散列／完整性／注册映射通过；未执行生产恢复。串行初始化 cloudTicks=0，配置和受保护数据保持。
- app 健康、sync/web 运行；6 个既有云来源有晚于发布时间的成功同步。容器内部 30 个静态资源与 11 个受保护匿名 API 已核对；没有访问或绕过组织 SmartScreen 阻断。未新增私人财务导入；真实来源映射／日期、模型、OAuth 回跳、新增日历／待办写入及实体设备覆盖仍分别待验收。

证据：`test-results/workflow-guidance-release-verification.json`、`workflow-guidance-pytest-verification.json`、`workflow-guidance-suite.xml`、`workflow-guidance-linux-tests.json`、`workflow-guidance-browser-verification.json`、`workflow-guidance-source.json`、`workflow-guidance-deployment.json`、`workflow-guidance-linux-tests-initial-tempfs.json`、`workflow-guidance-backup-before.json`、`workflow-guidance-backup-after.json`。证据和私人运行目录不随通用源码包分发。以下历史标题与原批次测试范围保留。

## 2026-09-15 05:47:43 旅行示例、金额选择与对账保护发布

2026-09-15 05:47:43（北京时间）已发布旅行示例下载、账单金额列选择与对账迟到响应保护，镜像 `sha256:2bae500814cdad8cc467de8811c33ac1534f6399aabb56e0ca65ce26bd4f8265`。后端证据复用已测试镜像 `sha256:706124251cac52fad2c56f017dacb8084c712818da1ccca3083849474eeac8b8`：Windows 666 passed / 12 skipped，Linux 677 passed / 1 skipped。最终镜像已核对全部既有后端、配置、pytest、部署源码与已安装依赖相同；本轮没有在最终镜像重跑后端全套。临时浏览器共 10 组、190 场景：本轮重跑 4 组 81 场景，另 6 组旅行专项沿用同源码 109 场景证据。30 个静态资源、11 个匿名 API 拒绝及6 个既有来源发布后的成功同步经服务器内部核对。真实新增云写、OAuth 回跳、私人财务完整覆盖、可选模型调用与公网浏览器仍各自待验收；本轮没有导入新的真实私人财务来源，也没有进行生产恢复。XLSX 工作表发现与助理旅行简报仍为下一版独立候选，未合入本次源码或镜像。

- 源码 160 文件；相对 04:58 的 153 文件新增两份静态 JSON 和五份专项测试（含对账请求保护浏览器专项）。存储保持 29 张户内表、2 张平台注册表及 87 个 Flask 路由模板；没有新依赖或迁移。
- 后端证据复用已测试镜像 `sha256:706124251cac52fad2c56f017dacb8084c712818da1ccca3083849474eeac8b8`：Windows 666 passed / 12 skipped，Linux 677 passed / 1 skipped。最终镜像已核对全部既有后端、配置、pytest、部署源码与已安装依赖相同；本轮没有在最终镜像重跑后端全套。既有两套后端测试总数均为 678。Windows 的 POSIX 跳过在 Linux 执行；Linux 唯一跳过是容器缺 Docker CLI。
- 旅行模板为虚构多国家／城市输入，覆盖日期级与航班／住宿／活动时区细项。下载保留草稿，预览不写，只有明确确认才创建本地关联实体；原请求守卫与幂等保持。
- 金额列以物理索引区分同名列，选择进入签名，未选多金额列不能确认；相同文件同一行重选保持旧值并返回冲突。保留历史无编号文件的身份规则、本人／家庭隔离及 TV 禁止导入；列名不是实际付款的独立证据。

| 浏览器专项 | 范围 | 通过场景 | 证据批次 |
|---|---|---|---|
| `tests/browser_journey_import_guard_check.py` | 旅行导入保护 | 31 | 沿用同源码证据 |
| `tests/browser_journey_draft_guard_check.py` | 相邻草稿与提交返回 | 32 | 沿用同源码证据 |
| `tests/browser_journey_confirm_guard_check.py` | 重新预览确认 | 5 | 沿用同源码证据 |
| `tests/browser_journey_details_check.py` | 旅行时间细项 | 10 | 沿用同源码证据 |
| `tests/browser_journey_return_budget_check.py` | 旅行返回与预算 | 23 | 沿用同源码证据 |
| `tests/browser_journey_examples_check.py` | 旅行示例下载 | 8 | 沿用同源码证据 |
| `tests/browser_finance_amount_columns_check.py` | 账单金额列选择 | 13 | 本轮重跑 |
| `tests/browser_financial_files_check.py` | 现有文件导入 | 5 | 本轮重跑 |
| `tests/browser_finance_reconciliation_check.py` | 现有关联与对账 | 6 | 本轮重跑 |
| `tests/browser_finance_reconciliation_guard_check.py` | 对账迟到响应与身份保护 | 57 | 本轮重跑 |

临时浏览器共 10 组、190 场景：本轮重跑 4 组 81 场景，另 6 组旅行专项沿用同源码 109 场景证据。各组使用临时 Flask/SQLite/Edge 与合成输入；独立审查不重复加入总数。八组有独立浏览器外部请求记录且均为空（其中六组为沿用的旅行证据）；传统文件导入与对账专项使用本地合成数据，但未单独记录浏览器网络请求，不能据此扩大网络验收范围。实际第三方账号、真实订单变体和公网浏览器不由这些检查替代。在该 05:47 历史批次当时，XLSX 说明页发现仍为独立候选；现已在上方最新组合批次合入并发布。

- 停旧写入：sync exit=0，OOM=False；app exit=0，OOM=False，耗时 1.91 秒；这是实际记录，不承诺所有在途请求在 45 秒内结束。
- 停写后完整备份 `manifest-20260914T214703721086Z.json`；发布后完整备份 `manifest-20260914T214812596032Z.json`，每组 2 个数据库，对应 1 户及平台注册目录；哈希与完整性通过，未执行生产恢复。
- 配置与受保护业务摘要保持，app 健康、sync/web 运行，6 个既有来源有发布后的成功记录；30 个静态资源（含两份 JSON）和 11 个匿名受保护 API 仅经服务器内部核对。没有访问或绕过组织 SmartScreen 阻断。

证据：`test-results/import-reconciliation-release-verification.json`、`import-reconciliation-deployment.json`、`import-reconciliation-backup-after.json`。发布汇总关联已测试 706 镜像的后端／Linux、最终镜像同源核对、本轮重跑与沿用的浏览器及源码散列证据；私人输入和维护者运行目录不随通用源码包分发。04:58 及以下各节保留其历史范围，不拼接成此次新验收。

## 2026-09-15 04:58:08 旅行草稿与会话保护发布

2026-09-15 04:58:08（北京时间）已发布，镜像 `sha256:a5c2d414d4a282c6ce10d51212f16d85f85e4742eaabc179b5970eace7333675`。Windows 630 项通过、12 个 POSIX 场景跳过；Linux 641 项通过、1 项因容器无 Docker CLI 跳过。整合源码的临时浏览器 154 场景通过；28 个静态资源、11 个匿名 API 拒绝及六个所选云来源成功同步经服务器内部核对。真实新增云写、OAuth 回跳、私人财务完整覆盖与公网浏览器仍各自待验收。

- 153 文件源码，运行模块只改 `app.py` 和 `static/journey-ui.js`；增加四份专项测试，包括独立 `tests/browser_journey_confirm_guard_check.py`，未替换原 32 项草稿专项。接口与存储保持 87 个 Flask 路由模板、29 张户内表与 2 张平台表。
- 主目录完整 Python 测试 630 passed / 12 skipped（共 642）；Linux 同一候选 641 passed / 1 skipped。Windows 12 项 POSIX 跳过在 Linux 执行；Linux 唯一跳过为 Docker CLI。
- 旅行导入 31、相邻预览／保存 32、重新预览确认 5、旅行细项 10、旅行返回 23、助理 21、双平台连接 32，7 组共 154 项真实临时 Flask/SQLite/Edge 场景。测试使用实际后端默认值，无会话配置覆盖；云平台为模拟，外部请求与真实云写为零。
- 重新确认专项分别延迟真实身份核对与预览响应：新建重新预览和 409 后重新预览期间，确认按钮立即禁用，点击与 Enter 不发旧凭证；503 后保持禁用，重试成功仅提交新凭证、写入一条操作，更新保留实体 ID。已发送的写请求仍依靠服务端版本和幂等校验，不由按钮禁用撤销；该 5 项是临时环境验证，不代表真实云写或生产身份切换验收。
- 后端 23 项会话专项已包含在全量中；真实延迟 HTTP/CookieJar 的旧配置负对照会恢复原成员，修复默认值保留新成员或退出状态。普通读取不续期，最后一次真实 session 签发后 30 天；会话变更响应乱序和旧 Cookie 主动重放仍在范围外。
- Linux 记录镜像、源码 manifest 散列、运行镜像内容及 tests/deploy 挂载前后散列；发布前再次核对同一 manifest，避免将不同源码的测试拼接。
- 停止 03:58 已有信号处理的 worker 与 app：sync exit=0，OOM=False；app exit=0，OOM=False，耗时 1.1 秒。这是此次实际停止记录，不能承诺所有在途请求均在 45 秒内完成。
- 停写后立即备份 `manifest-20260914T205731300227Z.json`，发布后备份 `manifest-20260914T205844093671Z.json`；两组注册目录与全部家庭库均校验通过。源码／配置回退点见 `draft-session-host-preparation.json`；未执行生产恢复。
- 配置及受保护业务摘要前后相同，app 健康、sync/web 运行；六个既有来源有发布时间之后的成功记录，28 个静态资源与 11 个匿名受保护 API 经容器内部核对。未访问受组织策略阻断的公网浏览器。

证据：`test-results/draft-session-release-verification.json`、`draft-session-pytest-verification.json`、`draft-session-suite.xml`、`draft-session-browser-verification.json`、`draft-session-linux-tests.json`、`draft-session-deployment.json`、`draft-session-after-release.json`、`draft-session-backup-before.json`、`draft-session-backup-after.json`。浏览器逐份报告位于该轮固定源码演练副本，路径和散列保存在汇总证据中；它们不随通用源码包分发。

## 2026-09-15 04:08 README 与当前交接状态核对

本次整理软件方案、接口导航、部署运维与多 agent 接手入口；未合入独立业务候选或更新运行镜像。

- 通过既有 SSH 只读确认正式镜像仍为下节 03:58 的 `sha256:f6774e9f5bf668f42eb45b98b7cbc64f0df6303b3780161db1887c9c0d9b99dd`，app 健康、sync/web 运行。户内数据库检查通过、外键错误为零，平台注册仍为 1 户。
- Microsoft / Google 共六个所选来源均有 04:07 至 04:08 的成功记录，无错误或重新授权标记。配置和受保护数据的摘要与上一轮发布保持一致；没有输出账户及消费明细。
- 修正开发文档中 `AccountsReturn` 的模块依赖说明，将 03:40 历史补丁改为明确的历史时态；登记尚未合入的旅行导入和会话 Cookie 竞态，候选不能计为已发布功能。
- 代码与依赖本次未变，沿用下节对应源码的运行测试结果，不重复计数或称为本次重跑；文档链接、示例语法、临时恢复演练及交接包散列另行核对。

服务器只读证据为维护者本地 `test-results/readme-handoff-current-snapshot.json`。文档与交接校验使用 `documentation-validation.json`、`published-handoff-verification.json`、`published-handoff-audit.json` 和 `published-handoff-server-sync.json`；这些运行记录不随通用源码包分发。

## 2026-09-15 03:58 流程衔接、来源适配与 worker 发布

2026-09-15 03:58:15（北京时间）已发布，镜像 `sha256:f6774e9f5bf668f42eb45b98b7cbc64f0df6303b3780161db1887c9c0d9b99dd`。Windows 607 项通过、12 个 POSIX 场景跳过；Linux 618 项通过、1 项因容器无 Docker CLI 跳过。合并后的临时浏览器 76 场景通过；28 个静态资源、11 个匿名 API 拒绝及六个所选云来源成功同步经服务器内部核对。真实新增云写、OAuth 回跳、私人财务完整覆盖与公网浏览器仍各自待验收。

- 149 文件候选归档完成校验，正式 app/sync 均使用同一镜像；来源 CLI 随部署源码交付。接口仍为 87 个模板、29 张户内表及 2 张平台表。
- Windows 全量 `flow-completion-suite.xml` 为 607 passed / 12 skipped；Linux 镜像为 618 passed / 1 skipped。Windows 跳过 POSIX 信号场景；Linux 唯一跳过为 Docker CLI 不存在。各平台只按实际执行计数。
- 主目录旅行返回 23、助理 21、Microsoft/Google 连接各 16 项通过；源码散列与报告一致，零外网请求及真实云写。真实 OAuth 仅保留待验收边界，合成回跳不是本人授权证明。
- worker 独立 Linux 18 项及真实 PID 1 容器验证早先通过：空闲约 0.27 秒、在途 SQLite 提交后约 1.52 秒退出；使用临时库和合成阶段。此次停止的是旧 03:11 进程，耗时 46.49 秒，记录为 sync exit=137 OOM=False, app exit=0 OOM=False。该记录不证明新 worker 已在生产长请求下平稳停止，137 不记为平稳退出。
- 停止旧写入后生成完整即时备份，立即持久保存备份回执，再串行初始化全部家庭且不运行云 tick，依次启动 app/web/sync。保护业务及配置摘要保持一致；所有既有来源发布后均有新成功时间。
- 发布前备份 `manifest-20260914T195738058246Z.json`、发布后 `manifest-20260914T195857188338Z.json` 各 2 库，大小、SHA-256、数据库与平台注册映射检查通过。保留旧源码／配置 `/opt/family-dashboard-before-flow-completion-20260914T192450Z` 及镜像标签 `family-dashboard-app:before-flow-completion-20260914T192450Z`，未执行生产恢复。
- 容器内部 28 个静态资源对应 manifest、11 个受保护 GET 匿名返回 401。没有重复访问或绕过被组织策略阻断的公网浏览器，没有提交真实私人财务候选或进行真实新增云发布。

证据：`test-results/flow-completion-release-verification.json`、`flow-completion-suite.xml`、`flow-completion-linux-tests.json`、`flow-completion-product-browser-verification.json`、`connection-return-integrated-verification.json`、`flow-completion-deployment.json`、`flow-completion-after-release.json`、`flow-completion-backup-before.json`、`flow-completion-backup-after.json`。03:40 交接包仍是当时不可变快照；新版交接包交付已整合源码，不再次附待应用补丁。

## 2026-09-15 03:31 README 与联合开发快照

本轮交付以文档、源码和待集成补丁为范围，没有更新正式镜像或修改生产业务数据。

- 通过既有 SSH 只读核对：正式镜像仍为 `sha256:2aff068d58560acd4099954fc034f3aeedc55bff1a0971ceb27d5ff33e0c4b5d`，app 健康，sync/web 运行；每户 29 张表、平台注册 1 户，数据库检查通过。六个所选云来源持续成功同步、无重新授权标记，受保护数据及配置摘要与 03:11 发布记录相符。没有重新请求被组织策略阻断的公网浏览器。
- 在临时数据库重新生成结构索引：87 个 Flask 方法/路径模板、额外 WSGI 家庭入口、29 张户内表和 2 张平台表。补齐基础 API 的旅行 v2 时间字段守卫、日程备注上限和删除旅行的解绑规则；修正部署/运维中旧的待部署描述。
- 主目录已有银行来源分类与尾备注 CLI 增量，但未部署；来源、基线及数据副本的独立候选测试 130 项通过，代码哈希与合入结果一致。原发布版全量仍以此前 Windows 551、Linux 550 通过/1 跳过为准，不能用不同测试集的数量相加。
- 三份独立候选在联合开发包的 `pending-changes/` 中交付，未应用到主目录：worker 的 Linux 专项 18 通过及真实 PID 1 停止验证；旅行返回 23 项浏览器及原助理/旅行回归通过；连接返回双平台各 16 项及原发布回归通过。各自使用合成输入，未与主目录增量一起完成全量或新镜像验收；详细范围见 [交接说明](HANDOFF.md)。
- 交接包保留源码、测试、部署脚本、README 与配套文档，候选只附集成补丁、基础/结果哈希和说明。环境配置、数据库、原始财务文件及运行证据目录不随包分发。文档检查只校验链接、示例语法和临时恢复场景，不执行正式部署命令。

本地证据为 `test-results/readme-current-snapshot.json`、`finance-adapter-integration.json`、`documentation-validation.json`；最终交接包校验记录为 `developer-handoff-verification.json`。正式运行验收仍以下方 03:11 发布记录为准。

## 2026-09-15 03:11 助理处理入口与并发初始化发布

北京时间 **03:11:08** 已更新 app/sync/web，镜像 `sha256:2aff068d58560acd4099954fc034f3aeedc55bff1a0971ceb27d5ff33e0c4b5d`；源码归档 145 个文件。

- Windows **551 passed，230.87 秒**；Linux **550 passed、1 skipped**，唯一跳过因隔离容器没有 Docker CLI。测试容器没有挂载生产环境配置或数据卷。
- 合并后的临时 Flask/SQLite/Edge 浏览器 **21 场景通过**：五类原事项入口、完成/预算/图片保存及原 ID 读回、409/503、重复提交、旧请求晚到、返回前身份核验、两成员/两家庭/TV/演示边界。无外站、私人财务接口请求或页面错误；JS 语法检查通过。
- 日历发布表检查/补列与命名空间写入现用 BEGIN IMMEDIATE 保护，异常回滚；真实双进程旧库竞争、既有复核标志/待写数据保留及失败重试通过。不增加接口或表，仍为 87 个 Flask 方法/路径模板、29 张户内表与 2 张平台表。
- 发布前停止旧 sync/app，完整组备份后串行预热，再分步启动。预热没有云 tick，发布队列仍为空；配置及账号、实体、资金、基线、电视等保护数据的前后摘要一致。
- app 健康、sync/web 运行；六个既有云来源均有晚于发布时间的成功同步。容器内部 28 个静态资源匹配源码散列，11 个受保护 GET 匿名返回 401。公网浏览器仍受组织 SmartScreen 策略阻断，未重复访问或绕过。
- 即时发布前备份 `manifest-20260914T191030120415Z.json`、发布后 `manifest-20260914T191136466023Z.json` 各 2 库，大小/散列/quick_check/外键/注册映射核对通过。保留旧源码与配置 `/opt/family-dashboard-before-actions-schema-20260914T185626Z`，旧镜像标签 `family-dashboard-app:before-actions-schema-20260914T185626Z`；未执行生产覆盖恢复。

本次没有提交新的私人财务候选，没有执行真实新增日历/待办云写或可选模型调用。财务来源适配与 worker 平稳停止仍在独立候选，不在本次发布中。

证据：`test-results/actions-schema-release-verification.json`、`actions-schema-suite.xml`、`actions-schema-linux-tests.json`、`assistant-actions-verification.json`、`actions-schema-deployment.json`、`actions-schema-after-release.json`、`actions-schema-internal-verification.json`、`actions-schema-backup-before.json`、`actions-schema-backup-after.json`。

## 2026-09-15 02:33 旅行与来源更新发布

北京时间 **02:33:28** 已更新 app/sync/web。运行镜像为 `sha256:07666ba7e4473c5feb967cf0bcf2616244d0e510b18191c35cdf724ae1cbb139`，包含旅行 v2、本人财务来源更新、日历时间复核及同目标重连恢复。

- 冻结的 143 个源码文件经归档与逐文件哈希核对后构建。Linux 隔离镜像 **546 passed、1 skipped，415.25 秒**；唯一跳过因容器没有 Docker CLI，相应平台检查已包含于 Windows **547 passed**。测试容器未挂生产配置或数据卷。
- 停止旧 sync 和 app 并确认进程停止后，使用候选执行即时完整组备份，再串行初始化所有已注册家庭，最后分步启动 app、web、sync。初始化没有调用云同步 tick；原家庭两类发布队列均为空，来源回执表为空。
- 每户从 28 张业务表增至 **29 张**，另有 **2 张**平台注册表，当前注册 1 户。新增 `finance_source_receipts` 和 `calendar_publications.review_required`。初始化前后以及发布后 users、entities、private_finance、devices、photos、finance_baselines、公共资金和云绑定身份的数量与 SHA-256 逐项一致；`.env` 字节不变。
- **02:34** app 健康、sync/web 运行；原有六个 Microsoft/Google 来源均有晚于发布完成时间的成功同步，无错误或重新授权标记。没有执行真实云日历/待办新增发布，也没有提交新的私人财务候选。
- 容器文件与内部 HTTP 的 **28 个静态资源**逐项匹配源码 manifest；**11 个**受保护 GET 接口匿名均返回 401，包含新增来源状态接口。仅访问容器 `127.0.0.1:8000`，没有重新尝试被组织策略阻断的公网浏览器。
- 发布前即时备份 `manifest-20260914T183250105031Z.json`、发布后备份 `manifest-20260914T183438487326Z.json` 各含 2 个数据库；大小、哈希、quick_check、外键和平台注册映射核验通过。回退源码/配置目录为 `/opt/family-dashboard-before-sources-travel-20260914T175808Z/`，对应旧镜像标签 `family-dashboard-app:before-sources-travel-20260914T175808Z`。没有执行生产覆盖恢复。
- 部署文档已明确旧进程停写与全户串行初始化；保存 v2 数据或复核状态后，不能只回退不理解新语义的旧镜像并直接启动旧 worker。后续并发补列加固和助理行动台在独立副本，未包括在本次运行镜像。

本地证据：`test-results/sources-travel-build.json`、`sources-travel-linux-tests.json`、`sources-travel-deployment.json`、`sources-travel-before-activation.json`、`sources-travel-after-release.json`、`sources-travel-internal-verification.json`、`sources-travel-backup-before.json`、`sources-travel-backup-after.json`。本次 Windows、浏览器与文档交接的详细场景保留在下方先前的本地验收记录中；不得将不同阶段的测试数重复相加。真实云写、金融格式覆盖、模型、实体设备与异地恢复仍未由本次部署完成验收。

## 2026-09-15 旅行细项、来源更新与联合开发交接（本地候选）

本节保留 **02:13 交接时**的本地候选状态；后续 02:33 发布见上节。当时 **02:06** 通过既有 SSH 只读核实服务器仍运行 `sha256:2cdb7a8df93574f3399d80ee7d1d1a6ff3bd915ae8e566b16f1f2a83e4268f08`，app 健康，sync/web 运行；28 张户内表，数据库检查通过，六个所选云来源无同步错误。那次文档交付未替换运行镜像或写入真实云日历。

- Windows 全量 `.\.venv\Scripts\python.exe -m pytest -q --junitxml=test-results/sources-travel-suite.xml`：**547 passed，230.14 秒**，环境为 Python 3.14.7、pytest 9.1.1、tzdata 2026.4。`pytest.ini` 将默认收集限制在 `tests/`，排除运行证据、旧部署助手与虚拟环境；这些测试使用临时数据，不自动运行浏览器脚本。
- Node 日程纯函数 **10 项通过**；`static/` 下 **14 份 JavaScript** 语法检查通过。
- 实际临时 Flask 应用重新生成接口和字段索引：**87 个 Flask 方法/路径模板、29 张户内表、2 张平台注册表**。比线上增加 3 个财务来源接口、2 个日历复核接口、财务来源回执表，以及日历发布表的 `review_required` 字段。
- 旅行 v2 浏览器 **10 项闭环通过**：跨日期变更线航班、住宿晚数、活动与旧版日期段、取消状态、固定/可移动事项迁期、独立字段保留、显式冲突选择、夏令时不存在/重复时刻、503 草稿保留、409 重新预览、旧版升级及演示零写。390/1440px 页面无横向溢出；截图已经人工检查。
- 财务来源浏览器验证文件选择—本人预览—勾选确认—状态读回，并覆盖实际另一设备抢先保存后的 CAS 冲突、重新预览、503 重试、相同输入不增加版本、伴侣/TV/演示隔离。使用合成候选，360/390/1440px 布局通过。
- 日历时间语义复核浏览器在 Microsoft/Google 两种模拟服务商下通过：只读预览、暂停不能绕过复核、确认后排队及更新原远端 ID。日历重连与旧账号锁另经独立只读审查及 **62 项**针对回归通过，已包括在上述全量测试中，不重复相加。
- 三份新增浏览器报告均无页面异常、外站请求或生产写入。模拟服务商结果不证明真实账号已经具备写权限。
- README 与 24 份配套 Markdown 汇总产品范围、架构、接口、数据、使用、部署、恢复、协作与验收。源码包带逐文件 SHA-256；运行证据目录、环境配置、数据库和私人财务输入不随包分发。文档部署命令只作语法核验，不由文档检查执行。

真实来源曾仅做只读结构核对；缺少稳定字段映射和部分贷款余额日期，**未生成或导入新的私人候选，未启用持续刷新**。本轮也未构建或运行 Linux 候选镜像，未更换线上版本；真实新增云写、真实金融样本完整覆盖、可选模型、实体设备与公网浏览器仍按既有边界分别验收。

本地证据：`test-results/sources-travel-suite.xml`、`journey-details-browser-verification.json`、`finance-source-browser-verification.json`、`journey-timing-review-browser-verification.json`、`candidate-handoff-live-snapshot.json`、`documentation-validation.json` 和 `candidate-handoff-verification.json`。文档与打包检查结果只对记录的文件散列有效；后续修改应重新检查与打包。

## 2026-09-15 01:10 工作流增量发布

首页布局、财务对账、本地待办持续发布及个人数据副本已在北京时间 **01:10:44** 发布。运行镜像为 `sha256:2cdb7a8df93574f3399d80ee7d1d1a6ff3bd915ae8e566b16f1f2a83e4268f08`。

- 最终 Linux 候选镜像：**380 passed、1 skipped，289.83 秒**；跳过仅因容器内没有 Docker CLI。本地相应平台检查已通过。候选容器没有挂载生产环境变量或数据卷。
- app 健康，sync/web 运行；每户数据库从 25 张业务表升级到 28 张，平台注册目录仍为 2 张表，当前只有原家庭。数据库 quick_check 与外键检查通过。
- 切换前后 users、entities、private_finance、devices、photos、finance_baselines、公共资金与云身份摘要逐项一致；`.env` 字节保持一致。六个已选 Microsoft/Google 来源均在发布后重新同步成功，没有错误或重新授权标记。
- 发布前完整组 `manifest-20260914T170237405701Z.json`、切换前即时组 `manifest-20260914T170956931857Z.json`；发布后组 `manifest-20260914T171128879109Z.json`。前后两组各 2 库的文件大小、SHA-256、quick_check 与注册映射核验通过。没有执行生产覆盖恢复。
- 回退材料：`/opt/family-dashboard-before-workflows-20260914T170213Z/`，其中源码归档与原配置单独保管；旧镜像标签 `family-dashboard-app:before-workflows-20260914T170213Z`。
- 服务器容器内直接通过 `127.0.0.1:8000` 检查：全部 **27 个静态文件**的 HTTP 输出、容器文件与源码 manifest 哈希一致；**10 个受保护 GET API** 匿名均返回 401。只输出状态与摘要，无登录、生产写入或外部请求。这是内部服务验证，不证明公网页面渲染。
- **公网浏览器未通过环境门槛**：Microsoft Defender SmartScreen 显示组织不允许访问该域名，状态为 `browser_environment_blocked`。页面未加载，因此 23 个页面引用资源、10 个接口及桌面/手机/电视的浏览器检查均未执行。未关闭策略、切换路线或重复尝试绕过；组织拦截页错误不归因于家庭应用。

临时 Flask/Edge 的布局、对账、数据副本与双平台待办流程结果沿用下节记录；不能据此把本次公网浏览器标成通过。真实云端新增发布写入、真实金融格式完整覆盖、可选模型调用、两台实体电视与异地恢复仍未验收。在本节 01:10 发布时，[财务来源桥接](FINANCE-SOURCE-BRIDGE.md) 和 [旅行细项与时区](TRAVEL-DETAILS-PLAN.md) 尚为下一轮设计；后续本地实现见本文最上方候选记录。

证据：汇总 `test-results/workflows-release-verification.json`；原记录包括 `workflows-linux-tests.json`、`workflows-deployment.json`、`workflows-before-activation.json`、`workflows-after-release.json`、`workflows-backup-before.json`、`workflows-backup-after.json`、`workflows-internal-verification.json`、`workflows-live-browser-verification.json` 及 `workflows-live-organization-block.png`。这些运行证据不随通用源码包分发。

发布后的交接文档已统一为本节版本：README 加 24 份配套 Markdown，共 25 份。相对链接、51 个 JSON 示例、12 个 PowerShell 代码块、19 个 Shell 代码块及其中 2 段 Python 检查通过；7 个临时数据库恢复场景通过。部署命令只作语法检查，不自动执行。通用交接包包含源码、测试、文档和逐文件散列清单，测试报告另保存在本地 `test-results/`；两篇后续设计没有计为已开发功能。

## 2026-09-15 README、完整文档与本地增量交接

本节记录截至 **00:59** 的本地交接状态，当时新增布局、对账、待办发布、个人数据副本尚未部署；后续已于上节时间发布。当时线上仍为 00:17 镜像，00:39 再次只读核实 app 健康、sync/web 运行、两平台六个所选来源均有新成功时间且无错误/重新授权标记。数据库检查通过，当次文档工作没有重启服务或写入真实云端。

- README 作为统一入口，补齐设计风格、软件架构、接口族、代码地图、已开发/未部署/未验收边界、开发环境、部署指导和多 agent 分工；另提供家庭成员使用手册与可直接复制的 agent 接手模板。
- Windows 整体回归 **379 项通过，148.21 秒**，JUnit 保存为 `test-results/readme-suite.xml`。该轮收集后，待办模块补上账号重绑时旧锁快照保护及两个测试；最后版本单独 **61 项通过，35.63 秒**，另经独立复核，不能把两轮测试数量直接相加。Node 的 10 项日程纯函数测试及 13 份业务脚本语法检查通过。
- `tests/inspect_contract.py` 在临时数据库核对实际路由及字段结构：本地 82 个 Flask 方法/路径模板，另有一个 WSGI 家庭入口；每户 28 张业务表，平台注册目录 2 张表。动态 `<action>` 是一个路由模板，具体允许动作由模块契约列出。
- 文档检查工具 `tests/check_documentation.py` 随源码交付：README 加 22 份配套 Markdown，共 23 份；49 个 JSON 示例、12 个 PowerShell 代码块、19 个 Shell 代码块及其中 2 段 Python、全部相对链接通过。文档中的部署命令只解析，不执行。恢复示例在临时数据库的 7 个有效/失败场景通过。
- 独立检查修复恢复步骤：正常状态先在线备份；服务不可用或缺库时可从既有完整组进入离线恢复。两条路径都先停止写入、保全残存整卷与配置；恢复后先启动 app/web，核对历史待写队列后再启动 sync。没有执行生产覆盖恢复；物理损坏目标的自动修复不在已验证范围内。
- 首页布局 17 项针对性测试通过；真实临时 Flask + Edge 验证排序、键盘操作、隐藏、恢复默认、跨设备/成员隔离、503 草稿保留、409 冲突选择与 TV 零布局接口访问。
- 财务与文件 86 项针对性测试通过，其中 21 项覆盖新增对账。真实本地浏览器通过订单 100 元、付款 100 元、重复付款 100 元、退款 30 元的确认闭环：净支出 70 元，撤销重复关系后为 170 元，四条原始记录均保留；另一成员不可见。
- 数据副本 5 项针对性测试通过；真实本地浏览器下载两份 ZIP，逐项验证 5 个文件、4 条 manifest 散列及字节数、原币/整数分和 null 值、伴侣私密与凭证排除；503 时保留选择且不生成下载，TV/演示没有导出入口或请求。
- 待办发布使用两个真实 provider adapter 配合模拟 HTTP 与临时 Edge，验证发布、完成回流、冲突处理、重试和原清单重连。独立审查发现的并发标题覆盖和同清单重连失效已修复；最终 10 项针对回归与另外 14 个临时边界场景通过，覆盖成员撤回授权、不同云身份拒绝和旧账号锁不能影响新绑定。真实账号写入仍未验收，最终边界见 [待办发布契约](TASK-PUBLISH.md)。

源码交接包携带 README、配套文档、测试代码及逐文件 SHA-256 清单。生产 `.env`、数据库、财务原始文件和 `test-results/` 不打包；测试记录中的合成数据结果不等于用户实际平台数据覆盖。截至本节 00:59 的新增代码尚未完成 Linux 候选与上线核对，后续结果见最上方 01:10 发布记录。

本地证据：`test-results/readme-live-snapshot.json`、`documentation-validation.json`、`dashboard-layout-verification.json`、`finance-reconciliation-browser-verification.json`、`data-portability-browser-verification.json`、`task-publish-browser-verification.json`、`recovery-documentation-syntax.json`。更早的全量和正式版本结果保留在下方，不能混合不同日期的测试数量。

## 2026-09-15 00:17 平台发布与联合开发交接

时间为北京时间。现代工作台、多家庭空间、旅行联动、私有账本和投资、助理、云日历发布队列已部署。实际外部账号写入仍按下方边界判断。

- Windows 完整后端测试 277 项通过；Linux 候选镜像 276 项通过、1 项需要 Docker CLI 的检查跳过，耗时 182.54 秒。该平台检查已在 Windows 验证。测试容器没有生产环境变量或数据卷。
- 运行镜像 `sha256:5da77023e4535481e0d9eaca6eb7cdfedf6991fb37a936eb42952d6001db203d`；00:17:44 完成 app/sync 更新及 Nginx 重建，随后确认 app 健康，三个服务运行。
- 发布前后 users、entities、private_finance、devices、photos、finance_baselines、共同资金记录、云绑定身份逐项数量与 SHA-256 一致；生产 `.env` 字节保持一致。
- 主户数据库从 15 张表扩展到 25 张表；新增平台注册目录目前只登记原家庭，没有创建虚构生产家庭。主库与注册目录 quick_check 通过，主库 foreign_key_check 无错误。
- 原家庭 Google 与 Microsoft 绑定均不需要重新授权；发布后的所选 6 个日历/任务来源都有新的成功同步时间，错误计数为 0。此结果证明既有读同步继续运行，不等于新增云日历写权限已经授权。
- 正式域名浏览器 00:18 完成严格 TLS 验证，使用显式 DNS 映射；6 个受保护 API 匿名访问均为 401，21 个静态资源 SHA-256 与本地一致。10 个演示页面覆盖电脑与 390px 手机的 20 组布局，另有 1080p 电视布局，均无溢出或 JavaScript 异常。脚本未读取凭据，写请求、外站请求、真实配对和 OAuth 操作均为 0。
- 发布前完整组备份 `manifest-20260914T161656798906Z.json` 含原家庭 1 库；扩展初始化后的 `manifest-20260914T161846933272Z.json` 含原家庭与注册目录 2 库，逐文件大小、SHA-256 和 quick_check 验证通过。没有覆盖恢复生产数据库。
- README 与配套文档共 19 份 Markdown。独立验证链接、JSON 示例、PowerShell/Shell 语法和内嵌 Python；部署命令仅解析，不通过文档检查自动执行。
- 多家庭恢复示例原样提取到临时目录验证 7 种情况：完整两户及注册目录恢复、单主户、单子户，以及坏哈希、注册映射不匹配、成员缺失、当前注册目录缺户。后四种均拒绝且目标摘要不变，单户恢复不改另一户。
- 平台 API 文档的 8 个 JSON 示例可解析；旅行预览/应用、助理草案/确认、邀请兑换和偏好保存均在临时 Flask 数据库实际执行通过。

备份为同服务器副本，未完成异地灾难恢复。新增日历写入、真实平台导出格式、真实模型调用和实体电视观看仍未借本次发布宣称验收。完整产品目标与剩余工作见 [产品目标](PRODUCT-PLAN.md)。

本地证据：`test-results/platform-before-release.json`、`platform-after-release.json`、`platform-release-verification.json` 中的 `liveBrowser`（另保存为 `platform-live-browser-verification-20260915T0018.json`）、当时的文档检查及 `platform-api-examples-verification.json`。未带日期的浏览器报告现已记录 01:10 版本的组织策略阻断，不作为本节成功证据。证据文件不随通用源码包分发；源码包携带 README、配套文档、测试代码和逐文件散列清单。

## 2026-09-14 家庭中枢平台扩展：本地集成验收

以下扩展已完成本地集成；生产发布结果另行记录，不能由本节推断已经接通真实第三方写入。

- Windows 全量 pytest：277 项通过（97.42 秒）；覆盖多家庭身份隔离、财务私有数据、旅行事务与版本冲突、模型动作白名单、导入资源限制、发布队列及备份。
- Node：10 项日程逻辑测试通过；11 份业务 JavaScript 语法检查通过。
- 实际 Flask 路由和 SQLite schema 核对：70 个 HTTP 方法与路径组合，另有 WSGI 的家庭入口跳转；25 张户内业务表、2 张平台注册表。
- 17 份 Markdown、27 个 JSON 示例及本地相对链接检查通过；后续文档修订需重新核对链接。
- 临时数据库 + Edge：10 个工作台页面覆盖 5 种视口，另有 9 组电视视图；主题、密度、跨设备偏好、搜索、导航、失败保留草稿通过，无页面异常和横向溢出。
- 助理草案验证预览不写入、勾选后只创建所选动作、重复提交不重复创建；未配置真实模型密钥，不把本地模式验收当作模型已接通。
- 旅行验证多城市计划、负责人、准备与采购预算、预览确认、两次迁期仍保留完成状态和关联实体编号。
- 财务验证 UTF-8/GB18030 CSV、受限 XLSX 的工作表选择、预览确认、重复导入、币种与退款口径及双方私有数据隔离。使用合成样本，真实平台导出格式仍需逐一验收。
- 云日历浏览器通过实际 Flask 与两个服务商 adapter 下的模拟 HTTP：权限、仅本人来源、预览、排队、轮询、暂停恢复、远端变化冲突核对和失败重试。外部请求及真实日历写入均为 0。
- 创建独立家庭后的成员、电视、照片、财务与云连接隔离审查通过；这不是商业级负载或渗透测试。

本地证据位于 `test-results/`：`platform-docs-js-verification.json`、`platform-contract-inventory.json`、`product-shell-verification.json`、`product-workflows-verification.json`、`journey-browser-verification.json`、`financial-files-browser-verification.json`、`household-privacy-audit.json`、`calendar-publish-browser-verification.json`。该目录不随源码发布。

## 2026-09-14 文档与联合开发交接核对

本次只整理 README 与配套文档，没有修改业务代码或重新发布运行镜像。

- 11 份 Markdown 的相对文件链接与代码围栏检查通过；19 个 JSON 示例可解析。
- 从当前 Flask 应用的路由表比对接口文档：33 个显式路由注册、35 个 HTTP 方法与路径组合，覆盖一致。
- 对照建表代码核对数据模型文档：15 张业务表均已覆盖。
- 8 个 PowerShell 代码块通过语法解析，19 个 shell 代码块通过 `sh -n`；这些检查没有执行文档中的部署或恢复命令。
- 部署文档的数据库恢复逻辑在临时库上验证了缺失、零字节、错误结构、缺少成员和有效备份五种情况；无效输入未修改目标库。没有覆盖生产数据库。
- 本次未重跑业务测试。下节是上一轮功能发布的实际验收记录，应按各自日期和验证范围理解。

文档结构检查证据保存在本地 `test-results/documentation-verification.json`，不随交接包分发。

## 2026-09-14 日程、采购、财务基线发布验收

本节是基础功能版本的发布记录；平台扩展另见上方记录。下方继续保留更早阶段的验证与当时限制。

- Windows：138 项 pytest 通过；Node 10 项日程逻辑测试通过。
- Linux 发布镜像：137 项 pytest 通过，1 项仅适用 Windows 的检查跳过；测试容器未挂载生产数据库或环境变量。
- 临时 Flask 数据库 + Edge 实测图片压缩、真实上传保存、预算、本人/伴侣/电视权限；三种日程视图各覆盖 720p、1080p、4K，无卡片裁切或页面错误，手机页面无横向溢出。
- 另验证 15 组常规日程布局、9 组每日至少 10 项长标题的 TV 自动播放；采购 20 秒翻页及上传失败保留草稿通过。
- 图片解码限制为 400 万像素、单并发；四路并发 probe 返回 1 次 201、3 次 429，进程峰值约 120.5 MB。
- 发布前在线备份 household-20260914T142146Z.sqlite3；导入后再备份 household-20260914T142654Z.sqlite3。SQLite quick_check 与 foreign_key_check 通过。
- 真实财务基线通过 SSH 标准输入导入，不进入发布包：15 条资产记录、14 条负债记录、17 条收入记录。共享汇总仅返回批准字段；本人明细读取与伴侣隔离读回通过，重复导入不更新版本。
- 导入前后公共财务、个人月度收支、采购、旅行和家庭账号内容摘要一致。资产/负债尚不完整，净资产为空，不把旧日期小计冒充实时全量资产。
- 已运行镜像：sha256:2a2fe3b19696f4598ddf505d45cb3602505a4089c124b96273818eeb38b66684。app 健康，sync/web 正常；正式 HTTPS healthz 200。
- 正式域名浏览器使用 DNS 显式映射及严格 TLS，登录页、演示三视图、受保护 API 的 401 与发布资源内容匹配均通过，零 JS 错误；此项不代表本机默认 DNS 缓存已刷新。
- 发布后微软/Google 各 1 个绑定账户无需重新授权；当前所选日历与清单最近一轮同步均成功，无来源错误。金融账户自动刷新未接入，导入仍为固定版本。
- 浏览器排版验证不能代替两块实体电视的观看距离与具体浏览器验收。备份仍为同服务器副本，未执行生产覆盖恢复演练。

证据：test-results/live-feature-verification.json、features-tv-week.png、features-phone.png；私有导入回读结果在家庭看板私有访问目录 finance-import/import-verification.json。


验证日期：2026-09-14，北京时间。

## Microsoft 绑定失败修复（2026-09-14 21:47 起）

- 用户实测绑定失败。安全诊断定位到 scope_validation：只缺少 Calendars.Read.Shared；令牌兑换和 UserInfo 身份读取已成功，基本个人日历与任务权限已通过。
- 将额外共享日历权限与基本绑定分开：基本要求为 User.Read、Calendars.Read、Tasks.ReadWrite 和离线刷新令牌。共享日历是否可读取仍由微软 API 实际权限决定。
- 同时修复微软返回 URL 编码 Graph scope 时误判缺权限，以及共享日历读取权限覆盖个人日历读取的兼容性问题。
- 新增阶段化安全诊断：只记录阶段、固定错误类别、HTTP 状态和数值 AADSTS 编号，不记录 code、state、token、secret、邮箱或服务商错误全文。页面分别提示令牌、身份、权限和离线授权问题。
- 第一批修复全量本地 91 项通过，Linux 镜像 90 项通过 / 1 项跳过；针对实际缺少 Shared 的最终修正及诊断回归 29 项通过。
- 21:52 服务器确认实际 Microsoft 账号已绑定，并选中三份任务清单；三份清单均已有成功同步时间且无错误。用户本人完成授权，未使用模拟账号或代替用户同意。此时未选中 Microsoft 日历，不能据此宣称已验证微软共享日历读取。
- 发布前在线备份 household-20260914T134548Z.sqlite3；账号和个人财务逐表比对保留，Google 已有两个日历与一份任务清单继续同步，未改动生产 .env。
- 发布检查发现 Windows 打包未保留 shell 脚本可执行位，已恢复服务器三个部署脚本的 0755，并修正打包规则；备份实际执行成功。

## 账号与自动同步版本（2026-09-14 20:13 起）

- 已部署 Microsoft / Google 网页登录、成员绑定、来源选择、后台自动检查、日历只读同步与任务新建 / 完成 / 恢复回写。当前两家 client ID / secret 均未配置，账号与来源数量为 0，登录页明确显示等待配置。
- Windows Python 3.14：63 项测试通过。生产镜像 Python 3.12.14：62 项通过、1 项跳过；仅跳过容器内无 Docker CLI 的 Compose 转义检查，该项已在 Windows 实际 Compose CLI 上通过。
- 测试覆盖一次性 state、浏览器与成员会话绑定、PKCE、稳定 subject 身份匹配、禁止邮箱自动关联、双成员权限、电视只读、加密与刷新令牌、进程锁、分页失败不发布、云端删除、冲突回写和保留已确认写入。
- 隔离数据库上的实际 Flask + Edge：密码登录、未配置平台提示、账号设置、本地任务创建与完成、旅行任务、720p / 1080p / 4K 电视布局通过，零 JavaScript 页面错误。
- 公网域名严格 TLS 校验通过；登录页、手机布局、账号指南、电视演示、匿名数据拦截、伪造回调拒绝通过。浏览器仍显式映射 DNS，不把该结果作为本机默认 DNS 缓存已更新的证据。
- 生产 app / sync / web 三个容器运行，app 健康。SQLite integrity_check 为 ok；发布前后 users、entities、private_finance、settings 逐表比较一致，生产 .env 字节未变。
- 发布前数据库备份：household-20260914T121152Z.sqlite3；旧源代码、私密环境备份和旧镜像保存在服务器供回退。未更改已有密码，也没有尝试已过期的本地初始密码。
- 发现 Nginx 同时继承默认 combined 日志的问题，已在四个 server 块明确覆盖日志格式并重建 web。使用无敏感数据的回调标记检查，app / web 日志均记录路径且不含查询参数。
- 证据：test-results/account-ui-integrated.json、accounts-live-check.json 及对应截图。

验证边界：真实 Microsoft / Google 授权、远端账号内容、长期刷新、平台配额及撤销授权，必须在管理员注册应用并由成员本人同意后验收。当前自动同步为任务约 30 秒、日历约 60 秒轮询，尚未实现第三方变更推送。原有财务同步仍未连接。

## 域名上线验证（2026-09-14 19:46 起）

- Name.com 权威 DNS 与 .world 父区委派已确认；Google 8.8.8.8、Cloudflare 1.1.1.1 返回 `home.caesarcharles.world → 96.44.160.28`。
- Let's Encrypt 域名证书签发成功，SAN 为 home.caesarcharles.world，首张到期日 2026-12-13。
- 新域名 HTTPS healthz 返回 ok，HTTP 返回 301 跳转；旧 IP HTTPS healthz 仍返回 ok。未关闭 TLS 证书校验。
- 修复单文件 bind mount 指向旧配置 inode 的问题，重建 Nginx 容器后新域名证书正确生效。应用容器和数据库未重建。
- 浏览器使用显式 DNS 映射验证域名证书、登录页、未登录 API 拒绝访问、电视配对页与演示页；没有 JavaScript 页面异常。由于本机上游 DNS 仍缓存 NXDOMAIN，这次浏览器测试不算本机默认 DNS 路径已通过。
- 本地保存的 member1 初始密码在新域名登录返回 401；可能已被用户修改。本次未重置或更改任何账号密码，不宣称完成了已有账号登录验证。
- `certbot renew --cert-name family-dashboard-domain --dry-run --no-random-sleep-on-renew` 成功；现有六小时续期任务覆盖域名与 IP 证书。
- 原始证据：本地 test-results/domain-check.json、domain-demo.png。新域名需要用户重新登录，电视重新配对。
- 此阶段仅部署 Nginx 域名入口；后续账号同步版本见上方记录。

## 已通过

- 后端 pytest：8 项通过。覆盖登录 / CSRF / 跨源拦截、共享任务与过期版本冲突、个人财务隔离、电视配对只读与撤销、金额类型与财务冲突、ICS 重复日程与去重、旅行任务关联、全天日程跨日边界。
- 本地 Edge 无头浏览器：720p / 1080p / 4K 电视、390×844 手机、1440×1000 电脑；电视整屏无滚动、手机无横向溢出，截图逐项检查。日程完整标题与地点允许换行。
- 浏览器登录与新建任务通过，未捕获 JavaScript 页面异常。
- 正式服务器公网 HTTPS：本机 curl 和 Edge 均验证通过，未关闭证书校验；HTTP 自动转到 HTTPS。
- 正式服务双成员操作：成员一创建临时任务，成员二修改，应用容器重启后状态仍保存；临时任务已删除。
- 正式服务电视流程：电视页产生配对码，成员授权后显示；禁止读取个人财务与写共享任务；撤销后返回未授权。临时电视已删除。
- Certbot 使用 staging 执行 `renew --dry-run`，模拟续期成功。
- Docker 服务开机启用，应用 / 代理 restart 策略为 unless-stopped；续期与备份 systemd timer 已启用。
- 首次备份生成，SQLite `PRAGMA integrity_check` 返回 ok。

浏览器截图及结构化公网验收结果在本地 test-results/，该目录不进入生产镜像。正式数据不含演示金额或行程。

## 验证边界

- 没有重启整台 racknerd；验证了应用容器重启与持久化，并检查开机启动配置。
- 没有在两台实体电视 / iPhone / OnePlus 上操作；当前验收为浏览器与视口测试，实机全屏与系统缩放仍需用户首次使用时确认。
- 公网直连可用；本机默认代理路径曾超时，绕过代理后 HTTPS 正常。若用户浏览器走代理，需要保证代理可访问服务器，或对该 IP 使用直连。
- 尚未验证真实个人日历的 OAuth / 订阅同步，也未连接金融账户。ICS 使用生成的测试日历验证，不代表自动同步已经完成。
- 备份为同服务器副本，尚未执行生产账本覆盖恢复或灾难恢复演练。

本次对账界面增量绑定原页面和原成员／家庭／CSRF，读取、候选、预览、确认及撤销的迟到结果不接管后来页面；已发送写入不能由关页取消。独立专项为 `tests/browser_finance_reconciliation_guard_check.py`。本修复不声称覆盖全部财务缓存生命周期。

XLSX 工作表发现与助理旅行简报已于 2026-09-15 06:50:21 合入并发布，详情见 [验收记录](VALIDATION.md)。


## 发布后文档检查器修订

首次文档校验实际返回失败：五处链接指向已存在的 HTML `id`，旧检查器只识别 Markdown 标题，未识别显式锚点；随后向 cp1252 终端输出中文报告又触发 UnicodeEncodeError。原始 JSON 保留为 `documentation-validation-first-attempt.json`。本地检查器改用标准库 HTMLParser 收集代码块外的显式 `id`／`a name`，保留原有标题去重规则；后续运行使用 Python `-X utf8`，不改写首次失败。此次工具及七份文档修订不改变应用运行代码，也不表示服务器重新发布。
