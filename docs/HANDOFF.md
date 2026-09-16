# 联合开发接手说明

> **线上版本：2026-09-16 18:57:14（北京时间），镜像 `sha256:43e8214c5241f0b94271d19503c3f4d26c398bb4a18596258bbf4f1e75db17bd`。** 相册逐项处理原因、历史未知提示和确切保存数已上线；344 源文件、70 Markdown、51 静态资源、130 个方法／路径模板、48 张户内表及 2 张平台表，无数据迁移。安装源码对应 main `d9c51b9`／integration `2aac0007` 同树；本次文档仅本地交接，不改已发布 manifest。本人已授权并完成一次十选三保存，其余七项原因未记录；新诊断的本人选片验证及实体电视仍待验收。

先读 [README](../README.md)，再按下方模块地图阅读接口和源码。本文帮助开发者确定从哪份代码开始、负责哪些文件、如何验证与交付。历次发布和失败修订集中在 [VALIDATION](VALIDATION.md)，不重放历史候选补丁。

## 当前接手基线：相册 48 表已上线

安装源码 main `d9c51b9847e8ea9e0640c1da6d2e9f1c49dd5819`／integration `2aac0007b689a40d45fd36ed40fb75a1a64f8a3c` 同树 `db0949c2d1b55bb53351d4c352740edc9ac34a7c`。发布目录 `/opt/family-dashboard-releases/photos-results-20260916T105630Z-20260916`，manifest `76b8bc77ba786be3069ca477facd7ecb7d9b6d2d61a10c8df0388994a886b45d`。本次是 48 表内诊断补丁，无 schema 迁移；实际 1 户两库完整备份，停写至新 app 启动前后全部 48 表与平台 2 表的行、schema、序列保持，原配置保持。

18:58:16 正常 TLS 读回确认全 344 源文件、84 运行文件和 51 静态文件匹配；四服务 running、重启计数 0，app healthy，六个匿名接口 401；发布后备份 service 成功、timer active。分段验证与原件见 [VALIDATION](VALIDATION.md)。不要在当前 48 表重放历史 43→43、43→44 或 44→48 迁移。

本人 Google Photos 已授权并完成选片；历史选择 10 张普通照片、保存 3 张，另外 7 项原因无法还原。新选择才会生成逐项诊断，旧回执显示已知保存数及其余未知；不扩展解码格式／限额，不自动重新下载。使用见 [媒体交付](MEDIA-DELIVERY.md)、[结果契约](MEDIA-IMPORT-RESULTS.md)。新诊断仍待下一次本人选片反馈，实体电视另验；库存仍是独立候选，不属于此生产镜像。后续按独立分支／worktree→非作者审查→integration→组合验证→main，生产另行验收。

<a id="当前接手基线地点-44-表已上线"></a>
## 历史接手基线：地点 44 表（16:33）

本节保留地点发布当时的状态，不能代替顶部媒体 48 表基线。

2026-09-16 16:33:32 发布 main `6f3d97855613e9b8ff78df5850652180e083ea76` 与 integration `cd857f525e5bf9127b1338e17a1a003e58f4916e` 的同树 `5581c3fb16852afaf0455bff991c8560dbcdbf19`。安装 manifest `1a5990e0b7e500ed44986b979e413a8ba26c92bd6cf4c7757be429bed17e51d8`，目录 `/opt/family-dashboard-releases/journey-places-20260916T083232752975Z`。精确 READY 经非作者核对后才执行，实际证据见 [VALIDATION](VALIDATION.md)。

原43表、schema、序号及配置在停写至HTTP核对窗口保持；新地点表为空。实际生产1户、两库完整备份；双户迁移与恢复使用另建虚构数据，不能混算。当前44户内表+2平台表、112路由；旧43→43 SOURCE和43→44地点迁移均不能用于下一次更新。

NVIDIA配置工具在独立分支通过审查，并经组合复审合入main `18f30dd`，只新增工具/测试/说明三文件，原295源文件与74运行文件不变。同日 16:58 已用审查后的工具只新增三项 AI 配置并以原镜像有序重建服务；旧 `.env` 原样 0600 备份、其他配置字节和数据卷保持。真实模型草稿 API 200、`mode=model`，只使用临时虚构家庭；未 apply。Google Photos OAuth/协议、图片净化/加密仍在独立已审候选；精选/逐台电视许可、库存和完整成员关系尚未接线。电视先按浏览器实现，型号稍后补充。

后续继续独立分支/worktree→非作者审查→integration组合验证与复审→main。下方历史段落描述当时状态，其base、表数和命令不能作为当前发布输入。

## 历史 13:24 发布与后续开发

### 本地地图基线：已合 main，尚未部署

当前地图基线 main `9559ca4ea0dfab064cb9c19897daeca86475876b` 与已审 integration `1ff3bd441350545370cb03306187bd776fda659b` 同树 `69a1afa4f8afec8e8ab9c34fc0fa157cb780bb91`，279 个跟踪文件。该基线包含先前 NVIDIA/编排、地图 API `05f885b`、底图 `0585547`、界面 `e6795f4`、应用接线 `f429569`，分别经非作者审查后按 Git 合入，再核对精确联合与实际测试证据。不要重新拷贝或重放这些分支。

地图模块入口为 `journey_places.py`、`static/journey-map.js/.css`，app 注册和主导航已接好；[API](JOURNEY-PLACES.md)、[UI](JOURNEY-MAP-UI.md)、[底图来源](MAP-BASEMAP.md)、[接线与导出](JOURNEY-MAP-INTEGRATION.md) 是对应契约。新增 `journey_places` 一表后本地为 44+2 表、112 路由。原 SOURCE 43→43 与历史 42→43 工具不能承担这次发布，地点迁移工具和双户恢复演练仍需独立审查、真实运行和发布证据。

真实浏览器 10 项通过；不同阶段的 API、界面及接线测试分开记录于 [VALIDATION](VALIDATION.md)。Google Photos 纯协议适配器 `44bf644` 已通过独立 129 项合成检查，但保留在独立分支：OAuth 接线、展示副本、相册和独立电视许可尚未完成；不能把它混进只允许新增地点模块的发布清单。

### 新一轮本地候选：NVIDIA 与并发编排

发布后文档、设计参考及扩展计划已通过独立审查后合入本地 main `e42c535`；这不改变上方服务器安装身份。其上 NVIDIA 产品适配 `52be16e803758797eabe545c0500094cd005ee09` 和开发编排 `96d8a82f64b6b9a05e5270953b2214935d55b41d` 分别经非作者审查，无冲突合入 integration `ff590965c8feb544930e12a0cd7a477ffd17b872`。本段文档在以该集成提交为明确依赖的 `codex/root-nvidia-handoff` 独立工作树编辑，再交非作者审查；不在 integration 直接编辑。

产品适配只修改既有 `home_assistant.py`、`app.py` 的 AI 配置读取、`household_spaces.py` 的子户配置白名单和一处前端服务名称告知，另加专用测试及 [说明](ASSISTANT-PROVIDER.md)。开发编排只增加 `tools/inference_orchestrator/` 四文件、合成测试及 [指导](INFERENCE-ORCHESTRATION.md)，不操作工作树、应用补丁或自行审查晋级。两个分支没有新应用路由、schema 或依赖；配置秘密仍只在服务端。

root 独立执行最终适配 168 项回归和真实服务的隔离应用 18 项检查；编排独立 27 项合成测试与 24 次真实需求请求分列，原件/限制见 [VALIDATION](VALIDATION.md)。这一历史 NVIDIA 组合后来已审合入 main `583f5c9`，再作为上方地图基线祖先；它本身没有地图 API/UI。源码合入不代表生产已配置 NVIDIA。旧 SOURCE 策略没有准许根 DESIGN.md 和开发工具路径变化；后续独立地点发布策略须针对实际环境配置、镜像与数据版本验收。

开发共同 base 为 `fa72df437af8e97315e04d019a2f110b6cf69938`。发布前服务器的 255 文件 BASE 逐字对应 `54c0854`；本次实际安装同树 integration `82f4401`／main `79faaf3` 的 258 文件，不能把开发基线当作服务器安装状态。

| 分支 | 独立 worktree | 允许范围 |
|---|---|---|
| `codex/finance-ledger-api` | finance-ledger-api | `finance_hub.py`、新分页／金额测试、FINANCE-API 与 FINANCE-IMPORT |
| `codex/product-ledger-navigation` | product-ledger-navigation | `static/finance-hub.js/.css`、财务 demo 的 product-shell 入口、新账本浏览器测试 |
| `codex/root-ledger-handoff` | root-ledger-handoff | README、HANDOFF、VALIDATION、路由索引两文件；SOURCE 精确路由文档路径策略、测试与指导 |

新增 `GET /api/finance-hub/transactions` 提供本人全月记录的有界分页与搜索；原 overview 仍保留最多 500 条兼容数据和完整月度汇总。前端分页不再依赖这 500 条。`snapshot` 只检测账本变化，不是可查询历史版本；翻页时遇到变更返回 409，刷新获取新结果。没有新表、迁移、运行依赖或环境变量。账单文件的金额歧义检查只作用于新导入，历史记录和手工金额接口保持。

作者分别提交固定 head，由非作者在独立 detached worktree 审查，root 合入 integration；组合验证与再次审查通过后合入 main。本次还单独完成新 Linux 镜像验证、真实双户 SOURCE 演练及生产准入，原件与本地结果分别记录在 [VALIDATION](VALIDATION.md)。

已审模块为后端 `1e83821`、界面 `85ce24d`、SOURCE 文档路径策略 `fd0a128`；无冲突合入固定运行组合 `98fb73904667a55e92c13db76d65b94aab158ed8`，树 `22e73f65f307570e05b638156a9c4bfe838f10e8`。非作者核对该树精确等于三份已审提交的文件并集。其上实际执行 Windows 后端 435 项、实际新 GET 浏览器 17 项、投资浏览器 15 项和五组既有财务浏览器 183 项，均通过。258 跟踪文件在各次验证前后保持；根文档与路由索引另经审查合入，不改变运行文件或重写这些原件。

已安装源码共 258 文件、43 Markdown、44 静态资源、107 方法／路径模板；每户 43 表、平台 2 表。manifest `7089ca8899929ec8eee8b705547943c697b21c684014855f92b7f5ca4fa8fb42`，镜像 `sha256:ea399441e6696bc29214842ab8c47e3db943714c1ae72a05ca1266bdc4a1b739`，实际发布目录 `/opt/family-dashboard-releases/source-20260916T052333559366Z`。Windows／Linux 各 435 后端、Linux 工具 275、分组浏览器 215、两户演练及实际单户／2 库备份均有独立证据。发布后文档在 `codex/root-ledger-publication-docs`／独立同名 worktree 修改七份文档及文档检查器，由非作者审查后另行合入；它不改变已安装源码身份。

## 历史：11:39 SOURCE 发布与接手基线

发布源码为已审 integration `ecc3edce9f714edbd830fcde796e2bb903878b06` 合入的 main `54c08547e965ba9dd2bea1c8e8e8f34c1b0dabbe`，同树 `08c13778d26ab8cb7a68bcbb9f22ed72f9434ec3`。业务与源码发布工具均经独立审查，工具固定提交为 `4c05e5019aeb182f5ae23d183ec525dffc72ac60`。每个任务仍使用自己的分支与 worktree，已结束的业务分支保留为历史，不重放补丁。

发布镜像 `f82bc0fc…` 已完成父层加一层、完整配置保持与父／子运行字节核验。Windows 受影响后端 406 项、新镜像 Linux 后端 406 项与工具 269 项分别通过；首次 Linux 因测试挂载含宿主缓存而在执行用例前被拒绝，原失败保留，按 manifest 复制 185 项测试支持文件后重试通过。真实双户 SOURCE 演练保持每户 43 表、平台 2 表、8 份资料与 3 库备份，未恢复数据库、未操作生产。浏览器 187 项补测功能与适用历史 65 项分列，59 项路由单列。入口与要求见 [SOURCE-RELEASE](SOURCE-RELEASE.md)，精确范围与原件索引见 [VALIDATION](VALIDATION.md)。

本次更新前 BASE 为 22:32 运行版本加其后已发布的八份纯文档，共 248 文件，逐文件与 Git `daf5ab4e7adbddb994ca5c1fd745180d5d912c63` 相同；BASE manifest `3db7f24e…` 原样保留。实际 SOURCE 发布已安装两项 Python 与五项静态差异及完整 255 文件清单，当前 manifest 为 `169c9621…`。服务器原件证明实际单户／2 库备份和三阶段完整数据保持；随后另只读核对全部源码、配置、镜像及服务。下一次发布重新冻结真实现状，不使用旧 BASE 或历史包冒充当前安装。

本次发布后文档在 `codex/docs-source-publication`／独立同名 worktree、base `54c0854` 上整理，只允许 README、HANDOFF、VALIDATION、SOURCE-RELEASE、DEPLOYMENT 五文件。非作者审查后由集成人合入 integration／main；这次文档提交不更新服务器，不改写已发布 manifest 或原运行证据。

## 前阶段：淘宝订单分组与商品明细开发

本轮共同 base 为 `923975454564e6914b638e90c1602d603e342430`。该提交已接收上一轮待办起步与 XLSX 声明兼容的审查结果；它与已审 integration `02597e5` 的文件树一致，不能把下方保留的历史分支再应用一遍。

| 分支 | 独占 worktree | 允许范围 |
|---|---|---|
| `codex/finance-taobao-order-groups` | finance-taobao-order-groups | `financial_files.py`、`finance_hub.py`、新订单测试和三份财务／数据契约 |
| `codex/product-order-items` | product-order-items | `static/finance-hub.js/.css`、新明细浏览器测试和用户指导 |
| `codex/journey-source-release` | journey-source-release | 无 schema 变化的更新工具、工具专项及发布指导；独立审查，不与业务代码共用工作区 |
| `codex/root-order-group-handoff` | root-order-group-handoff | README、HANDOFF、VALIDATION、DEVELOPMENT；无运行文件编辑 |

后端与界面先约定 `orderItems`／`orderGroup` 及 `conflictCount`／`row.conflict` 契约，再分别实现。界面分支可以用服务器侧的合成契约测试，但必须标明未执行新解析器；非作者审查后才由集成人 Git 合并，并在组合版本实际执行 XLSX → 预览 → 确认 → 账本流程。禁止复制另一位作者尚未审查的文件。

每个作者交付固定 base/head；审查者在 detached worktree 只读检查，有问题交原作者修订。只有集成人操作 integration 和 main，组合测试与再次审查通过后才合入 main。当前没有 remote 或托管平台强制保护，协作协议见 [GIT-WORKFLOW](GIT-WORKFLOW.md)。

本轮没有新 API、表、依赖或环境变量。所有商品明细留在本人的交易 JSON；共同财务只返回已允许的汇总，电视不能读取私人明细。JSON 副本保留明细，CSV 仍是一单一行；订单不自动成为付款或退款。

后端 `df9ef6b`、界面 `4186bbe` 通过 root 非作者审查后合入 `b0acd800`；旧金额断言修订 `275c5a5` 另经审查合入 `481c907`。当时候选为 251 源文件、42 Markdown、44 静态资源，406 后端与 65 浏览器的分段验证及原失败见 [VALIDATION](VALIDATION.md)。后续源码工具、最终合并与本次实际发布见上文；本表只保留开发责任和历史依赖。

## 历史：11:39 发布与源码状态

本次于 **2026-09-16 11:39:20（北京时间）** 发布 `f82bc0fc…`，发布目录为 `/opt/family-dashboard-releases/source-20260916T033817065173Z`。实际 1 户的 43 表与 2 张平台表在停写至 HTTP 核对窗口保持，2 库完整组备份核验通过；原 `.env` 与完整解析配置保持，没有 schema 初始化或数据库恢复。开放 sync/web 后允许正常业务写入，不据此持续宣称数据库静止不变。

| 交接项 | 当前范围 |
|---|---|
| 源码／Git | 已发布 255 文件、43 Markdown；integration `ecc3edc` → main `54c0854`，同树 `08c1377…`；后续纯文档独立交接，尚未同步服务器 |
| 接口与存储 | 106 方法／路径模板，另有 WSGI 家庭入口；43 户内表 + 2 平台表 |
| 受影响后端 | Windows 406 passed、新镜像 Linux 406 passed；均无 skipped / failed / error，旧 1495 项保留为历史 |
| 新工具 | 新镜像 Linux 269 passed；原失败与测试支持副本修订后的成功分开，不与历史静态工具 187 项混算 |
| 受影响浏览器 | 187 补测 + 65 适用历史 = 252 功能，59 路由单列；0 页面错误与外站，非一次全套运行 |
| 实际 Docker SOURCE 演练 | 两户每户 43 表、平台 2 表、旧认证、8 份资料与 3 库组备份保持；没有恢复操作，受管资源清理通过并保留保护镜像标签 |
| 生产读回 | 44 静态 200/SHA、8 匿名 401；三服务新容器运行、app 健康、字节码排除检查通过；发布后全部 255 源文件、manifest、原 `.env` 和镜像再次核对 |
| 分发及未验收 | 不含私有配置、数据库／财务输入或 test-results；真实新增云写、公网、实体设备、模型与生产覆盖恢复仍单列 |

## 此前旅行入口与静态发布

以下分支以 `65362fc` 为共同开发基线，已由非作者审查并逐层合入 `fec0e55`，最终 main 为 `cd75b0b`。它们保留作者历史，不代表永久文件占用或待重放补丁。

| 分支 | 作者／独立 worktree | 已审交付 |
|---|---|---|
| `codex/product-travel-entry` | product_interface / product-travel-entry | `724e091`：三个前端接缝、入口专项和两项旧脚本准备步骤 |
| `codex/root-static-build` | root / root-static-build | `cbb2609` 与文案修订 `225d84b`：固定父镜像、完整 static 单层构建 |
| `codex/finance-static-release` | finance_hub / finance-static-release | 最终 `bed2229`：严格配置、43 表保持与真实 Flask 静态读回；Compose 和 URL 修订均重新审查 |
| `codex/journey-static-rehearsal` | journey_workflows / journey-static-rehearsal | `2241ea1`：调用真实控制器的独立两户 Docker 演练及资源边界 |
| `codex/root-travel-entry-docs` | root / root-travel-entry-docs | `5a30f18`：总览、模块和发布导航 |

本轮发布后的 README/docs 在 `codex/finance-static-published-docs` 独立 worktree 整理，base 为 `cd75b0b`；仍按非作者审查 → integration → main 交接，不能跨目录编辑或把文档提交当作再次发布。下一轮重新登记 base、允许路径、依赖与验证范围。

新入口不增加后端 API、表或自动云写入。接口见 [TRAVEL-ENTRY](TRAVEL-ENTRY.md)，部署见 [STATIC-RELEASE](STATIC-RELEASE.md)，两次不同阶段的失败和实际重试见 [VALIDATION](VALIDATION.md)。

<a id="当前候选与文件占用"></a>

## 历史旅行资料与分支记录

旅行资料 API、导出、UI、接入、迁移与发布工具已经分模块审查，完成组合验收并于 20:23:00 发布。以下分支保留作者与审查历史，不代表还有待重放的补丁或永久文件占用；新的任务需重新登记独立分支、base 与允许路径。

最初 Git 基线为 `ad667bf2b744d707db080964c662249c7cd8b056`，标签 `baseline/2026-09-15-handoff`。当前主仓为项目根目录，各工作树位于维护者本机 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/` 下；换机器后按 [Git 指导](GIT-WORKFLOW.md) 从 bundle 创建自己的工作树，不复用这些机器绝对路径。

| 分支 | 本轮负责人 / worktree 目录名 | 已保存范围与状态 |
|---|---|---|
| `main` | 集成人 / 项目根目录 | 2026-09-15 22:32 历史发布基线 `cd75b0b`，248 文件、106 路由、43 户内表；当前 SOURCE 发布基线见本页顶部，后续纯文档提交另记 |
| `codex/integration` | 集成人专用 | 仅合并审查通过的提交，不供模块 agent 直接开发 |
| `codex/journey-documents-api` | journey_workflows / journey-documents-api | `90292c7`；product_interface 独立审查功能，root 复核末尾空行修正，已合入 integration |
| `codex/journey-documents-ui` | product_interface / journey-documents-ui | `a9dd519`；journey_workflows 审查提出三项修复，作者修复后由 root 复核，已合入 integration |
| `codex/journey-documents-portability` | finance_hub / journey-documents-portability | `8eb120e`；本人导出和恢复夹具，由 root 独立审查后合入 integration |
| `codex/journey-documents-wiring` | 集成人 / journey-documents-wiring | `2774e75`；app、加载、Docker 与发布白名单，由 finance_hub 独立审查后合入 integration |
| `codex/finance-journey-migration` | finance_hub / finance-journey-migration | `ec0ec4c`；可移植 42→43 检查器、16 项测试及契约，由 root 独立审查后合入 integration |
| `codex/journey-documents-release` | journey_workflows / journey-documents-release | `aecfd6c`；专用发布控制器、66 项命令替身检查，由 root 独立审查后合入 integration；此旧 66 项记录仅覆盖初版，后续环境修订与真实发布见下文 |
| `codex/journey-release-guide` | journey_workflows / journey-release-guide | `af81669`；发布输入、原始证据和失败处理指导，由 root 独立审查并复核文案修正后合入 integration |
| `codex/journey-release-env-fix` | journey_workflows / journey-release-env-fix | `684da03` → `2c9be6c`，配置解析与美元输出反解；finance_hub 独立审查，100 项控制流通过，经 integration `b1981a4` 合入 main `670f34f` |
| `codex/journey-published-docs` | journey_workflows / journey-published-docs | 20:23 发布后的纯文档 `c952a09`，经 integration `0f7693b` 合入 main `65362fc`，已结束 |
| `codex/root-journey-docs` | root / root-journey-docs | 旅行资料集成阶段的 README、接口索引、数据与部署文档；已独立审查并合入 |
| `codex/docs-git-handoff`、`codex/git-workflow-guide` | 文档集成人与文档 agent，各自独立目录 | 此前 README、Git 规则与指导；已通过独立审查逐层合入 main，保留历史分支 |

已发布资料默认本人私有、明确共享后伙伴只读，TV 不可读；PDF 仅下载、图片净化，删除旅行保留上传者资料。当前 **106 路由、43 户内表及 2 平台表**，完整契约见 [旅行资料](JOURNEY-DOCUMENTS.md)。

各模块分支保留独立职责，**单独分支不一定能启动完整新功能**。UI、导出和接线依赖新后端；完整测试在审查后的集成提交上执行，不通过复制其他工作树文件拼装。浏览器验证使用固定提交的 detached worktree，作者仍只在自己的功能分支修复；修复再次审查和 Git 合并后才验证新提交。

20:23 资料版历史组合证据（不计入本轮变化 JS 的浏览器验收）：`edc4ad9` 上资料 API／导出组合 **85 passed**（68 + 12 + 原导出 5），后续仅 API 末尾空行整理不改变 AST；`c91c6fe` 上完整资料浏览器 **43/43**、原详情 **10/10**、执行流程 **53/53**、返回流程 **23/23** 通过，共 129 项，232 个受控源文件前后相同且无页面错误或外站请求。43 项包含刷新后的准确分段焦点、四种空闲身份切换清屏，以及成功响应丢失后原旅行删除／重新关联的幂等重试。迁移工具在无 Git 的独立 TAR 解压目录中 **16 passed**，不依赖开发者路径。

原本机 seed 15 / verify 216 仅为夹具验证；后续同镜像两户真实 Docker 恢复已完成 65 / 15 / 216，恢复的资料为 8 份；恢复所需源码依赖保持原字节，复用同镜像原记录。另有单户 42→43 真 Docker 配置迁移演练，不能混算成恢复检查。Windows、Linux 的最终去重范围及生产迁移均已按最终源码记录，旧失败不隐去。

旅行执行跨模块接缝：`static/journey-ui.js/.css` 管详情刷新、负责人筛选和原流程返回；`task_publish.py`、`calendar_publish.py` 管 `localChangesPending` 的只读比较；`finance_hub.py` 管来源限定的订单表头兼容。验收入口为 `tests/browser_journey_execution_check.py`、`tests/test_publication_local_changes.py` 和 `tests/test_order_source_headers.py`。这些文件及接口变更由集成人协调，不能由旅行与云同步 agent 同时修改同一文件。见 [旅行执行契约](JOURNEY-EXECUTION.md)。

本页不登记已结束任务的永久占用者。家庭例行计划、采购实付、同步问题中心、电视布局、投资导入、成员会话、旅行简报及更早的 worker／旅行返回／连接返回均已在当前版本内；旧候选只供追溯，不是待应用操作。**不要重复 apply 历史补丁，也不要用旧候选整目录覆盖当前源码。**

下一轮开始前，由集成人登记目标、独立分支/worktree、base commit、允许路径、依赖与冻结状态。只在自己的工作树提交；结束交付 head commit 与 diff，散列补充文件证据。其他 agent 未收到审查通过的提交时，不假定依赖已经合入。

### 本次财务增量的交接边界

消费观察、历史月份导航和导出保护已结束独立候选阶段，并已包含在当前清单。旧 export-guard-candidate 目录只供追溯，没有待应用补丁或仍在占用的永久负责人。后续修改先向集成人登记唯一编辑者。

消费观察由 spending_observations.py 管规范化、覆盖、双版本 CAS 和事务，finance_source_bridge.py 分派显式 mode；finance_baseline.py 只在本人响应选择观察，不更新旧资产基线或共享小计。账单导航由 finance_hub.py 返回实际 resultMonths／availableMonths，finance-hub.js 保留成功回执并只重试读取。data_portability.py／data-portability.js 负责本人白名单副本和异步身份保护；最终身份读取后的 Cookie-only 切换仍有已观察的非原子限制。

这三条流程与来源、导出及既有财务模块共用文件，下一轮不得按旧任务分工同时写 finance-hub.js、finance-source-ui.js 或 data-portability.js。只提交允许路径的 BASE/RESULT 和精确 diff；完整源码、测试及接口应来自同一当前清单。

采购实付跨模块接缝为：`shopping_settlement.py` 负责私有来源、预览确认及回执；`static/shopping-settlement.js/.css` 负责新流程；`shopping-ui.js` 提供已保存采购入口；`finance-hub.js` 经原模型身份守卫提供账本入口、原订单对账及精确返回；`app.py`、`index.html`、Docker／发布白名单与 `data_portability.py` 由集成人统筹。整项 CNY 实付与 done 只投影到原共享采购，原交易、来源及关系不公开，旅行 paid 和账本不自动改变。

维护者的 `test-results/`、私人配置、运行数据库、真实财务输入和运行截图不进入通用源码包。包内保留可复跑测试与脱敏说明；单独查看原证据须明确范围，开发不要求生产凭据。

## 模块地图与接口入口

| 负责功能 | 核心文件 | 先读的契约与关键边界 |
|---|---|---|
| 家庭例行计划 | `household_routines.py`、`static/household-routines.js/.css` | [例行计划契约](ROUTINES.md)；固定起始日、单个自动当前项、十分钟签名预览、原子回执、缺失与容量提示、只读助理及共享导出 |
| 基础应用与共享数据 | `app.py`、`static/app.js` | [基础 API](API.md)；身份、CSRF/同源、共享实体 revision、模块注册和通用弹窗。原生 JS，无前端构建服务 |
| 家庭隔离与登录会话 | `household_spaces.py`、`member_sessions.py`、对应 UI | [平台架构](PLATFORM.md)、[成员会话](MEMBER-SESSIONS.md)；每户独立 DB/密钥、两成员、邀请、撤销和认证代次。缺库不得初始化空身份 |
| 成员工作台 | `static/product-shell.js/.css`、`dashboard_preferences.py` | [工作台界面](WORKSPACE-UI.md)；导航、搜索、主题/密度、卡片顺序/隐藏。成员偏好与电视布局分别保存 |
| 电视配对与显示 | `tv_display.py`、`static/tv-display.js/.css`；`app.py` 设备接口 | [电视显示设置](TV-DISPLAY.md)；整设备 revision，`layout` 四字段整体替换，隐藏只影响显示。`deviceForm()` 转入 `TVDisplay.openDevice(id)`，TV 重绘后调用 `applyBoard()` |
| 日程、采购与图片 | `static/calendar-ui.js`、`static/shopping-ui.js`、`shopping_media.py` | [基础 API](API.md)、[使用手册](USER-GUIDE.md)；时区/日界、共享权限、图片引用及草稿，TV 保留分页与长内容滚动 |
| 采购实付核对 | `shopping_settlement.py`、`static/shopping-settlement.js/.css` | [采购核对契约](SHOPPING-SETTLEMENT.md)；整项 CNY 替换、done 独立、私有 link／receipt、版本与重放、两种撤销、本人导出；不改账本／trip.paid |
| 同步状态与问题中心 | `sync_health.py`、`static/sync-health.js/.css` | [同步状态契约](SYNC-HEALTH.md)；本人详情和共享聚合分离，不触发云写；app/cloud_accounts/外壳加载接缝交集成人 |
| 云账户与同步 | `cloud_accounts.py`、`cloud_providers.py`、`sync_worker.py`、`static/accounts-ui.js` | [账号接入](ACCOUNT-SYNC.md)、[连接返回](CONNECTION-RETURN.md)；成员授权、选源、账号锁、分页后替换与失败保旧。停止信号不保证在途请求立即结束 |
| 云日历与本地待办发布 | `calendar_publish.py`、`task_publish.py`、对应 UI | [日历发布](CALENDAR-PUBLISH.md)、[待办发布](TASK-PUBLISH.md)；明确预览确认、原幂等标识、ETag/冲突、目标重连与本地实体 ID。不确定创建不得盲目重发 POST |
| 旅行与跨模块联动 | `journey_workflows.py`、`journey_time.py`、`static/journey-ui.js/.css`、旅行示例 JSON | [平台 API](PLATFORM-API.md)、[旅行时间](TRAVEL-DETAILS-PLAN.md)；v1/v2、各地时间/IANA、排他日期、稳定 key、三方比较、待办/采购/日程联动和返回原计划 |
| 旅行资料 | `journey_documents.py`、`static/journey-documents.js/.css` | [资料契约](JOURNEY-DOCUMENTS.md)；上传者权限、文件净化／下载、稳定分段、幂等 tombstone、孤立资料、元数据导出及备份 |
| 私有账本与投资 | `finance_hub.py`、`financial_files.py`、`investment_import.py`、对应 UI | [财务 API](FINANCE-API.md)、[账单导入](FINANCE-IMPORT.md)、[持仓导入](INVESTMENT-IMPORT.md)；整数分、分币种、未知值、工作表/金额选择、对账及原始来源标识。预览与确认分开 |
| 独立消费观察 | `spending_observations.py`、`finance_source_bridge.py`、`finance_baseline.py`、来源准备器和 UI | [消费观察](SPENDING-OBSERVATIONS.md)；需要已有本人基线，滚动覆盖、原基线不变、独立回执；不代表核对实付或自动银行接入 |
| 个人财务基线来源 | `finance_baseline.py`、`finance_source_bridge.py`、`deploy/prepare-finance-source.py`、对应 UI | [来源桥](FINANCE-SOURCE-BRIDGE.md)；私人映射、日期/覆盖范围、版本 CAS、缺源保旧。不能将个人银行余额当公共荷包，真实映射仍需核对 |
| 家庭助理 | `home_assistant.py`、`static/home-assistant.js/.css` | [平台 API](PLATFORM-API.md)、[旅行简报](ASSISTANT-JOURNEY-BRIEF.md)；本周待处理、原事项编辑返回、三步简报到向导。与旅行负责人共享 `journey-ui.js` 接缝，不能自动云发布 |
| 本人数据副本 | `data_portability.py`、`static/data-portability.js` | [导出契约](PORTABILITY.md)；仅本人私密与显式勾选的共同记录。排除令牌、会话/设备认证表和暂存预览；不是数据库恢复包 |
| 部署与备份 | `Dockerfile`、`compose.yaml`、`deploy/` | [部署指导](DEPLOYMENT.md)、[运维说明](OPERATIONS.md)；源码白名单、现有配置、全部家庭、停止写入、成组备份及相配恢复 |

当前路由定位入口是 [PLATFORM-ROUTES](PLATFORM-ROUTES.md) 和 [contract-inventory.json](contract-inventory.json)，结构为 130 个方法/路径模板、48 张户内表与 2 张平台表，须与最终源码实例化一致。例行管理的字段、鉴权和签名见 [ROUTINES](ROUTINES.md)，采购接口继续按 [采购核对契约](SHOPPING-SETTLEMENT.md#5-接口与数据模型)；不能仅按 UI 文案猜测 API。

## 例行计划公共接缝

`app.py` 在助理前注册 `household_routines`。`sync_worker.py` 每户顺序执行待办发布、日历发布、云读取、例行推进，各阶段开始前检查停止标记。推进只在观察到当前事项完成时创建下一期；不调用云账户默认写入器，不继承上一期云写授权。

`data_portability.py` 只在 `includeShared=true` 时加入 `shared.routines`。`home_assistant.py` 调用只读 `brief(con)`；`static/home-assistant.js` 按存在的数据显示例行计划待处理组。`static/product-shell.js` 提供三个入口并在共享状态刷新时通知例行模块；通知不发送请求、不重置草稿。新模块在 `product-shell.js` 之前加载。公开接口为 `HouseholdRoutines.open({planId?})`、`refresh()` 和 `notifyStateChanged()`。返回桥支持原待办／采购编辑器与 TaskPublish 初始选择页；保留未保存字段、图片和写中保护，显式返回重新核对原计划，不接管助理外层的关闭返回处理。Docker COPY 和 `deploy/prepare_release.py` 白名单都包含新后端。

当前完整结构为 130 路由／48 户内表／2 平台表；资料版 106／43、例行版 101／40 和采购版 98／37 是历史范围。最终结果见 [VALIDATION](VALIDATION.md)，不沿用历史通过数。

## 已开发与待真实验证

目前可用的流程还包括旅行／分段资料夹、本人资料库、明确共享和逐份文件下载；现有本地完整流程包括：家庭进入/邀请与会话管理；日程和主清单连接；多城市旅行经表单预览确认联动准备、采购和日程；助理处理原事项或整理旅行简报；私人账单/持仓文件预览确认与本人导出；本人付款经预览确认核对原共享采购、订单对账后返回、来源变化复核与明确解除；两台电视分别配对并保存显示设置；按来源检查同步新鲜度并打开本人原问题。云写入始终由独立授权和明确确认驱动。

| 尚需实际验收或实现 | 必须保留的界限 |
|---|---|
| 公网与实体设备 | 组织 SmartScreen 曾阻断公网浏览器，未绕过；容器内部和临时浏览器不等于公网、遥控器、电视休眠唤醒或长期常亮通过 |
| Microsoft / Google 新写流程 | 既有来源读取与同步有历史实测；新的云日历/待办发布、真实 OAuth 回跳、冲突/重连和刷新令牌闭环须本人授权验收 |
| 真实私人财务 | 稳定来源映射、贷款余额日期、真实脱敏账单与持仓格式逐一核对；未连接个人银行/券商、实时行情或小荷包自动 API，未建立无人值守财务刷新 |
| 模型能力 | 本地规则与操作流程可运行；可选模型需服务器配置及本人明确选择，真实调用和抽取质量单独验收，不能称本地规则为模型回答 |
| 运维与商业化 | 同机备份不是异地容灾；生产覆盖恢复、跨机恢复、公开注册/更多角色、计费与运营制度未完成 |

共同资金与经批准的资产/负债汇总可以共享；个人账户、消费、投资与来源明细只属于本人。电视侧重某成员或隐藏财务卡片都不改变服务器权限。所有新模块须保留这些数据边界。

## 文件所有权与协作协议

1. **每个任务独立分支和 worktree。** 禁止多人编辑同一工作目录，即使计划修改不同文件也须隔离。集成人维护 main/integration，模块 agent 只维护分配的 codex 功能分支。共用文件变更先约定契约和顺序。
2. **跨模块接缝先约定。** 助理与旅行共用 `journey-ui.js`；账单、投资、对账与采购入口共用 `finance-hub.js`，采购入口还涉及 `shopping-ui.js`；成员与电视入口共用 `product-shell.js`；会话、OAuth 和家庭路由跨后端。模块负责人提供精确输入/输出、权限与插入点，不直接覆盖另一人的文件。
3. **用提交审查和合并。** 交付 base/head commit、允许路径、diff、测试与未验证项；另一位 agent 审查固定提交。通过后集成人按依赖合入 integration，组合验证与再次审查后合入 main。Git 合并冲突逐项处理，禁止整目录覆盖或以旧 SHA 补丁绕过提交审查，详见 [Git 流程](GIT-WORKFLOW.md)。
4. **按真实依赖记录验证。** 记录执行脚本、源码散列、临时配置、退出码、通过/跳过、截图及未覆盖范围。独立候选通过不自动代表组合版本通过；不要把多平台测试数相加当独立场景。
5. **冻结后不再改源。** 新问题先通知集成人，再决定解除哪个文件的冻结。新增 Python 文件要检查 Docker COPY/发布白名单；新增静态模块要检查 `defer` 和 CSS 顺序。公共入口与最后发布由集成人处理。

保存失败保留草稿；异步请求绑定原节点、请求代次、原成员/家庭/CSRF，并按流程重新核验身份。已经发送的写请求不会因关闭弹窗而取消；重试保留原幂等标识，不自动重发。鉴权由后端执行，前端隐藏按钮不能替代权限。

## 可复制的 agent 任务模板

```text
项目：family-dashboard。先读 README、docs/HANDOFF.md、docs/DEVELOPMENT.md
及负责模块的 API 契约。核对当前源码与线上版本，不重放历史补丁。

目标：[用户能完成的具体操作及结果]
基线：[base commit、codex/<agent>-<task> 分支、独立 worktree 绝对路径]
依赖：[需要的其他分支及审查通过的 commit；无则写无]
允许编辑：[唯一文件清单；共用文件需精确到授权范围]
接口：[方法、路径、输入/输出、身份/家庭边界、版本和错误语义]
集成人接缝：[模块注册、脚本/CSS顺序、数据迁移、公共文件]
验收：[正常闭环、失败草稿、并发/迟到响应、跨成员/家庭/TV、视口]
交付：[head commit、base...head diff、真实命令/结果、截图、未验收范围]
审查：[另一位 agent 对固定 base/head 的结论；由集成人合并]

使用临时数据库和虚构数据，不读取或上传生产凭据、真实账单或原始数据库。
不改生产、不部署；测试通过不等于真实云账户/实体设备已验收。
不编辑其他 worktree，不自行合入 integration/main。冻结后修复须新提交并重新审查。
```

## 接手后的首轮检查

1. 核对 Git 根目录、分支、HEAD、工作区状态和分配的 worktree；按 [Git 流程](GIT-WORKFLOW.md) 建立独立任务分支。使用源码归档时先核对清单，正式联合开发使用 bundle 恢复提交历史，不用旧候选整目录覆盖。
2. 按 [DEVELOPMENT](DEVELOPMENT.md) 创建项目虚拟环境、安装 `requirements.txt` 和测试工具。生产是 Python 3.12，Windows 已使用 Python 3.14；前端无需 npm 构建。
3. 按 [DEPLOYMENT 第 2 节](DEPLOYMENT.md#2-配置密钥与数据文件) 配置独立开发密钥、测试密码与临时 `DATA_DIR`，只绑定回环地址。Python 不自动读取 `.env`，不要复制生产配置。浏览器测试按各脚本使用自己的临时夹具。
4. 先运行负责模块的已有测试，确认本机 Edge/Playwright 路径，再跑适用的真实临时浏览器。`pytest` 不自动运行 `*_check.py`；不要把旧生产 `live_check.py` 当默认回归。具体命令见 [开发与验收](DEVELOPMENT.md)。
5. 明确接口/迁移/隐私变化后再编码。公共 API、数据模型、用户步骤、错误行为和相应测试一起交付；金额是整数分、不同币种分别计算，日期语义按旅行契约。
6. 由集成人检查合并结果，完成对应组合测试、冻结、打包及发布。源码打包只收白名单，不生成凭据，也不是内容脱敏器；不能把私人文件临时放到 `docs/tests/static/deploy`。

部署人员分清 [空服务器安装](DEPLOYMENT.md#3-空服务器首次安装) 与已有数据更新。当前已是媒体 48 表，历史 42→43、43→43、43→44 以及本轮一次性 44→48 工具均不能重放；不能只改表数或照搬 DEPLOYMENT 的历史算法。下一次更新须绑定实际 48 表基线，恢复边界见 [媒体交付](MEDIA-DELIVERY.md)。

更新保留 `.env` 和主密钥，先关闭 web，再停止 sync/app，核对注册目录、全部家庭与完整备份组后串行初始化。app 启动读回通过才开放 sync/web；本次控制器任何失败均停止并保全现场，不自动恢复数据库。需要恢复时另行确定相配源码、密钥、注册目录与家庭映射，不能让旧镜像盲接未知库；已有业务写入时不能用旧快照覆盖。**恢复后先使目标家庭旧成员登录失效，再启动 app/web 核对，最后才恢复 sync**。具体步骤见 [部署与恢复](DEPLOYMENT.md#6-备份恢复与回滚)、[运维](OPERATIONS.md) 和 [会话恢复要求](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)。上一财务版本的 165／119 项离线激活／控制器恢复、79 项文档零结构检查均不是生产恢复演练。

## 后续工作

优先完成已实现能力的真实端到端验收：允许环境中的公网访问和 OAuth、两台电视长期展示、云任务/日历读回与冲突，以及真实脱敏账单/持仓和个人来源映射。每次选一个可观察闭环，保留现有数据与授权边界。

两户虚构数据的实际 Docker 恢复已完成；之后推进异地加密备份、生产覆盖恢复及跨机恢复、同步错误趋势、队列容量、备份年龄与磁盘可观测性（当前来源状态页已实现）、更丰富成员角色、Apple 提醒事项桥接、离线能力和商业化条件。详细优先级见 [PRODUCT-PLAN](PRODUCT-PLAN.md)，各历史发布、失败修订和未验证记录见 [VALIDATION](VALIDATION.md)。
