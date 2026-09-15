# 验证记录

> **当前版本：2026-09-15 22:32:04（北京时间），镜像 `sha256:14c7db7ba55cb4bbbed919b0b14d4bb1b1670eeb07d9a6f90e05799220590dfb`。** 新建旅行入口与原预览／确认向导统一，静态更新已发布；248 源文件、42 份 Markdown、44 静态资源，106 个方法／路径模板、43 张户内表及 2 张平台表。原后端与依赖保持，本轮证据与历史批次分别记录如下。

## 源码发布工具与组合验证（尚未部署）

工具作者固定提交 `4c05e5019aeb182f5ae23d183ec525dffc72ac60`，base 为 `9239754`；10 个授权文件、253 源文件。作者 Windows 269 项通过，包括保留的 187 项静态工具与 82 项新增源码模式用例。finance_hub 核对原 JUnit／日志／源码散列、原测试函数与断言 AST，并独立运行新增 82 项和真实临时 SQLite 24 项，共 106 passed。两组计数有重叠，不相加。

非作者同时验证真实 248 文件发布 TAR／BASE 清单，将已审业务 251 文件与工具差异组合成 255 文件映射，源码策略和依赖绑定通过；这是本地字段与字节预检，没有执行真实镜像或读写生产库。旧静态入口权限、共同锁、停止写者／全组备份／43+2 完整比较／HTTP 读回后再开放同步的顺序保持。

root 通过 Git 合入 integration `e0769e3cb9d341c73e5b21c1043eb943ddbf0be3`，再次执行五个工具模块，**269 passed，0 failed / error / skipped**。255 个源文件前后散列相同，原始报告为 `source-tools-combination-20260915T164219409390Z/verification.json`（SHA `d67c9fe7e1d3f7bae6492e2783cf9e2d4fc1096f4cc6acf5705d4e6322d93c6a`）。这次使用命令替身与临时 SQLite，不代表真实 Docker 演练。

下方已审业务 406 后端／65 浏览器按运行依赖分别保留；文件读取、投资、核对、待办起步和共享页面的最终浏览器组合需要补齐。新不可变镜像 Linux 测试、双户 43→43 源码升级演练及生产准入尚未完成。工具审查通过不是部署批准，流程见 [SOURCE-RELEASE](SOURCE-RELEASE.md)。

## 淘宝订单分组与商品明细候选（尚未部署）

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

当前生产仍以 22:32 的发布记录为准。本轮没有确认真实订单、执行新镜像、云写、生产更新或恢复；静态发布工具不能承接这两个 Python 后端变化。无 schema 变化的通用更新工具在独立分支开发，单独审查与演练。

## 前阶段：待办起步与 XLSX 声明兼容（尚未部署）

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
