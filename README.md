# 家庭中枢 · Family Dashboard

**最新上线：旅行资料与日程／清单优化，2026-09-17 18:13:25（北京时间）激活，18:13:50 正常 TLS 读回通过。** 从旅行详情打开「旅行资料」，或到「更多 → 我的旅行资料」管理凭证；默认仅本人可见，支持明确共享、下载和重新关联。日程及清单支持标准／紧凑间距，按钮与键盘操作已实际检查。本地资料 9 条流程／12 图和日程 5 条流程／18 图分别通过；服务器 235 项通过、1 项精确 Windows 跳过，55→55 原数据保持。使用见 [旅行资料](docs/EXPO-JOURNEY-DOCUMENTS.md)、[日程与清单](docs/EXPO-CALENDAR-DENSITY.md)，完整身份、失败修正与未验边界见 [发布验收](docs/EXPO-JOURNEY-DOCUMENTS-ACCEPTANCE.md#expo-documents-release)。实体电视仍待验收。

**此前版本：成员外观于 2026-09-17 16:17:28（北京时间）激活，16:17:57 正常 TLS 读回通过。** 从「更多 → 外观设置」选择本人浅色／深色、标准／紧凑密度，明确保存后应用；伴侣与每台电视设置独立。R1 本地浏览器 11 条流程／17 图及 Linux 226 项通过、1 项精确 Windows 跳过分别核验；595 包文件／114 运行文件／75 HTTPS 静态资源读回通过，55→55 数据与配置保持。操作见 [成员外观](docs/EXPO-APPEARANCE.md)，完整运行身份、证据与未验边界见 [本轮验收](docs/EXPO-APPEARANCE-ACCEPTANCE.md#expo-appearance-release)。

**此前版本：Expo 首页布局于 2026-09-17 14:56:51（北京时间）激活，14:57:27 正常 TLS 读回通过。** 从「首页 → 安排首页」调整本人卡片顺序、显示或恢复默认，明确保存后供本人手机与电脑使用；伴侣、电视设置与数据权限保持。R2 本地 9 条浏览器流程／9 图、Linux 188 通过及唯一精确 Windows 跳过分别核验。操作见 [首页布局](docs/EXPO-HOME-LAYOUT.md)，完整运行身份、55→55 保全与验证边界集中在 [本轮验收](docs/EXPO-HOME-LAYOUT-ACCEPTANCE.md#expo-home-layout-release)。

**此前版本：Expo 电视展示于 2026-09-17 14:19:19（北京时间）激活，14:19:53 正常 TLS 读回通过。** 电视打开 `/tv` 进入独立 `/app/tv`，手机仍从「更多 → 电视与播放」配对与控制；两台屏幕保留各自主题、布局、日程范围和照片许可。安装 main `2e314bf71491b96eade39e8d13525861ace4663a`／source `54cef032658ed9ddbddf0767336edf699906d5bb`，同树 `595baf255c57ad3c217afce0c0968861570754ed`。本地 R2 浏览器 13 项／9 图独立视觉审查通过；服务器 Linux 实际 321 通过、唯一精确 Windows 跳过，55→55 原数据保持。571 个包文件／114 个运行文件／75 项 HTTPS 静态资源及新逐库备份核验通过，四服务运行、零重启。经典电视入口保留 `/tv?classic=1`；实体电视与真实云播放未验收。使用见 [Expo 电视展示](docs/EXPO-TV.md)，完整身份与边界见 [本轮验收](docs/EXPO-TV-ACCEPTANCE.md#expo-tv-release)；后续文档提交不改变运行包。

**此前版本：Expo「电视与播放」于 2026-09-17 13:00:01（北京时间）激活，13:00:47 正常 TLS 读回通过。** 手机可在新版配对两块屏幕、分别设置布局、控制已授权照片并撤销连接。安装 main `5f41b61980481aba7d88e58b21b0806e59891fe2`／source `d0f660a8ead9f39126a35157f170e7fb6a1ad8b4`，同树 `a1b3bd81d492f235b0ca0d63ea60e2557aba06df`。第二轮真实临时浏览器 16 项检查／14 图通过；Linux R2 实际 758 项通过、唯一精确 Windows 跳过，首轮视觉问题和空间不足失败原件保留。55→55 数据与环境保持，四服务运行、零重启；555 源／114 运行／75 HTTPS 资源及 25 个匿名 API 拒绝通过，发布后逐库在线备份成功。该 13:00 版本的电视 `/tv` 当时仍沿用经典渲染器，实体电视未验收。使用见 [电视与播放](docs/EXPO-DEVICES.md)，完整身份与边界见 [本轮发布验收](docs/EXPO-DEVICES-ACCEPTANCE.md#expo-devices-release)。后续文档提交不改变本次运行包。

**此前版本：2026-09-17 11:09:53（北京时间）激活，11:10:38 正常 TLS 读回通过。** 新版旅行详情增加「调整日期」，明确选择联动事项、预览前后日期与当地时刻后保存；未知结果沿原操作核对与重试。main `2092cc43c4660df905755475706a88dfd62e7203`／source `0059cd9da2db43e1ad4f4cc95edc15b9bb3804a7`，同树 `07540964da68469d3861436afa04bb5dd8b36415`。使用见 [旅行改期](docs/JOURNEY-RESCHEDULE.md)，完整运行身份与证据见 [改期发布验收](docs/JOURNEY-RESCHEDULE-ACCEPTANCE.md#journey-reschedule-release)。

此前 11:09 发布为 55→55 无迁移，实际 1 户两库停写备份、原行／schema／序列在新 app 启动核对时保持。Linux 603 项通过、唯一精确 Windows 跳过；真实临时浏览器 16 项通过并产出 18 张截图，前两轮失败与修正保留。读回核对 545 源／114 运行文件与 75 项 HTTPS 资源，24 个匿名 API 均 401；四服务运行、零重启，app 健康。发布后新一次逐库在线备份成功，不是跨库全局原子快照。155 个方法／路由模板、户内 55 表与平台 2 表；本人真实云改期、实体电视和完整场景 A 仍另验。发布后文档不改变实际运行包。

> **此前发布：2026-09-17 09:25:21（北京时间），09:25:52 正常 TLS 读回通过。** 保存旅行后，从详情进入「旅行地点」，核对目的地后保存为私人计划地点，再到地图查看并返回；从「同步到日历」选择本人日历、预览并明确确认，查看队列与云端状态。界面沿用 [Expo 官网](https://expo.dev/) 的白底、黑色胶囊按钮和浅灰圆角卡片。使用见 [旅行地点与日历](docs/EXPO-TRIP-COORDINATION.md)，完整运行身份与证据见 [本轮发布验收](docs/EXPO-TRIP-COORDINATION-ACCEPTANCE.md#expo-trip-coordination-release)。

此前 09:25 发布为 55→55，无迁移；实际 1 户两库停写完整备份，原 55 表及注册库的行、schema、序列在新 app 启动后保持。第二轮 Linux 544 项通过、1 个精确 Windows junction 跳过，零失败／错误；第一轮 tmpfs 不足失败原件保留。当次本地真实临时浏览器 20 组和四宽 12 张截图另行记录，320 宽过渡帧已补稳定状态核对。读回核对 534 源／113 运行文件与 75 项 HTTPS 静态资源，四服务运行、app 健康；新一次逐库在线备份成功，不代表跨库全局原子快照。本人真实云写权限／改期、模型和实体设备仍待验收；此前 Photos 5／5 成功事实保留。发布后的文档不改变实际运行包。

此前本机 Windows 网络访问线上站点显示 `Website Filtered`，本轮未重新验证该网络下的线上登录；服务器正常 TLS 读回与本地真实浏览器验证分别通过，详见 [验证边界](docs/VALIDATION.md)。

**旅行地点默认仅本人可见、已计划、隐藏共享坐标。** 经纬度可以留空，不推测位置或到访。日历预览不写入云端，明确确认后才加入持续同步队列；队列受理与云端已确认分别显示。普通编辑总日期不会自动移动关联日期；需要联动时从详情进入「调整日期」，逐项选择并预览确认。复杂分段仍保留经典入口；旅行资料已支持新版管理。

**财务使用从核对开始。** 导入账单后先看新增、重复、冲突和错误，再明确保存到本人账本；导入不会自动修改公共荷包余额。搜索或翻页打开交易详情，可查看首次来源、选择关联候选、预览金额后确认，关系可明确撤销。共同资金和个人消费分开，个人账户与消费明细仅本人可见。实际操作步骤见 [Expo 财务](docs/EXPO-FINANCE.md)。

**持仓与公共资金分开管理。** 本人完整持仓支持手工增改删、CSV／TXT／XLSX 整理表预览确认、稳定来源关联、版本冲突核对及保存结果读回。估值未知与零分开，历史回执不会恢复已删除记录。使用与开发入口见 [Expo 持仓](docs/EXPO-INVESTMENTS.md)、[持仓 API](docs/INVESTMENTS-API.md)；早期 753c 候选 424 项记录仍保留于 [候选验收](docs/VALIDATION.md#expo-holdings-candidate)。完整资产账户、负债管理、估值历史和汇率功能仍待实现。

面向两位家庭成员的日程、待办、采购、旅行、财务与助理工作台。手机和电脑负责维护，50／75 英寸电视负责常亮展示；两个住处的屏幕可各自设置侧重、布局和主题。目前支持邀请建立独立家庭，每户两位成员。

**旅行从一次输入开始。** 助理将本次文字带入单页简报，可选 AI 需明确勾选；未知预算不当作零，准备与采购仍由成员核对后保存。响应丢失时沿用原预览和操作标识安全重试，不直接重新创建。此前 07:38 简报发布证据保留于 [旅行协作验收](docs/EXPO-TRAVEL-ACCEPTANCE.md)；新增地图与日历本地链路见 [本轮验收](docs/EXPO-TRIP-COORDINATION-ACCEPTANCE.md)，本人真实外部流程仍单独验收。

本 README 汇总**软件方案、已开发功能、代码地图、接口入口、开发环境、部署指导与联合开发方式**。字段级接口、完整安装命令、用户操作和验收记录分别放在 `docs/`，通过下方导航进入。

账户管理已发布新版 `/app/connections`：从「更多 → 账户与自动同步」或顶部「连接与账户」进入，连接 Microsoft／Google、搜索选择日历和清单、核对完整共享范围、查看各来源成功时间与错误。失效时可单独停止日历／清单同步并保留照片；断开账户则会移除该来源已导入的照片副本，确认前会说明。使用见 [Expo 账户与同步](docs/EXPO-ACCOUNTS.md)，实际发布身份以顶部与验收记录为准。

新版把地图、关联旅行和只读旅行相册放在 `/app/map` 内切换：查看照片后，可返回原筛选、页码和选中地点，并重新读取当前权限；整页刷新回到地图。每页 24 个地点，地图只显示当前页可见坐标，列表保留没有坐标的地点。普通 `/app/photos` 仍可选片和管理。使用见 [Expo 地图](docs/EXPO-MAP.md)，数据契约沿用 [地图相册联动](docs/MAP-TRAVEL-PHOTOS.md)。

资产基线和来源报告等高级财务、家庭／成员、照片旅行推荐及复杂旅行分段继续保留经典入口；旅行资料已迁入 Expo；设备、布局管理与电视展示页均已迁入 Expo，经典电视渲染器保留为明确回退入口。财务账本、本人持仓、地图、家庭物品及旅行日历同步主流程已迁入 Expo；电视继续独立只读 `/tv`。路线、精选回顾、视频、iCloud／NAS、通用成员角色和完整跨模块场景仍在 [产品计划](docs/PRODUCT-PLAN.md) 中逐项跟踪。

**此前媒体功能：地图 → 旅行相册 → 返回；本人照片 → 查看推荐 → 明确关联旅行。** 先核对照片时间对应的旅行日期和时区，再确认关联；旧照片来源时间未知时手动关联。版本冲突须重新读取并再次确认，网络结果不明先读回，不自动重写。关联不会自动共享、许可电视或标记到访。该轮 20:39:27 读回和全部历史证据保留于 [验证记录](docs/VALIDATION.md)。

家庭物品支持手工登记下单、分批收货、使用／报损／退回、纠正原流水、私有或明确共享及本人导出。这些主流程现已迁入 `/app/inventory`，并接入采购查库存和助理本地库存搜索；“更多 → 家庭物品”直接进入新版。不自动向商家下单、收货、补货、记财务账或写云端。使用见 [家庭物品交付](docs/INVENTORY-DELIVERY.md)、[Expo 家庭物品](docs/EXPO-INVENTORY.md) 与 [库存搜索](docs/ASSISTANT-INVENTORY-SEARCH.md)。

JPEG 补丁后本人已实际选择 5 张、全部出现预览并明确保存，服务器读回为 5 成功、0 失败。本轮未重新执行真实 Google 或实体电视验收；库存本地搜索已发布，真实用户库存体验仍待验收。旧十选三其余七项未知、十选五的五项 `invalid_image` 与原失败根因未确定继续保留，见 [媒体交付](docs/MEDIA-DELIVERY.md)。实体电视和长期云行为仍另验。

| 你要做什么 | 从这里开始 |
|---|---|
| 了解产品及全部已开发部分 | 本文「已开发范围与边界」「软件架构」「代码地图」 |
| 开发一个模块 | [项目规则](AGENTS.md) → [交接与候选状态](docs/HANDOFF.md) → [Git 分支协作](docs/GIT-WORKFLOW.md) → 对应接口文档 |
| 对接或修改 API | [基础 API](docs/API.md)、[平台 API](docs/PLATFORM-API.md)、[财务 API](docs/FINANCE-API.md)、[完整路由索引](docs/PLATFORM-ROUTES.md) |
| 使用或继续开发旅行简报 | [操作与组件](docs/EXPO-JOURNEY-BRIEF.md)、[组合验收及边界](docs/EXPO-TRAVEL-ACCEPTANCE.md)、[开发交接](docs/HANDOFF.md#expo-travel-release) |
| 接手旅行地点与日历同步增量 | [使用与接线](docs/EXPO-TRIP-COORDINATION.md)、[实际验证与发布阶段](docs/EXPO-TRIP-COORDINATION-ACCEPTANCE.md)、[发布工具](docs/TRIP-COORDINATION-RELEASE.md) |
| 使用或继续开发本人持仓 | [使用与组件说明](docs/EXPO-INVESTMENTS.md)、[持仓及操作回执 API](docs/INVESTMENTS-API.md)、[整理表契约](docs/INVESTMENT-IMPORT.md)、[开发交接](docs/HANDOFF.md#expo-holdings-candidate) |
| 安装、更新、备份或排障 | [部署指导](docs/DEPLOYMENT.md)、[运维手册](docs/OPERATIONS.md)、[恢复演练](docs/RECOVERY-REHEARSAL.md) |
| 开发新版 React Native 界面 | [前端开发与构建](frontend/README.md)、[同源托管与安全边界](docs/EXPO-WEB.md)、[官网风格](docs/EXPO-SITE-STYLE.md)、[财务](docs/EXPO-FINANCE.md)、[账户与同步](docs/EXPO-ACCOUNTS.md)、[地图与旅行相册](docs/EXPO-MAP.md)、[三模块发布记录](docs/EXPO-NEXT-RELEASE.md) |
| 把项目交给其他 agent | 源码 ZIP 供阅读；Git bundle 保留 main、候选分支和完整提交历史。恢复命令见 [Git 指导](docs/GIT-WORKFLOW.md) |

<a id="最新发布旅行地图"></a>
## 此前发布：旅行地图（16:33）

进入「旅行 → 地图」，可以保存心愿、已计划和本人确认已到访的地点，按年份、成员及旅行筛选，并打开关联旅行。地点默认仅本人可见；明确共享时可隐藏或粗化坐标。世界概览底图与应用同源，无需外部地图账号。电视不显示地点详情；当时的相册候选现已按顶部记录发布，自动回顾仍未实现。使用见 [地图界面](docs/JOURNEY-MAP-UI.md)、[地点接口](docs/JOURNEY-PLACES.md)。

本次保留全部旧 43 表和账户配置，只新增地点表。Windows 和实际 Linux 各 899 项受影响测试通过（467 后端、432 工具；Windows 为已核对来源的多次执行），另有真实双户迁移、44 表恢复、浏览器和生产读回；范围与失败修订见 [验收记录](docs/VALIDATION.md)。实际 1 户的两库组备份通过，服务健康，47 项静态资源和 10 项匿名权限检查通过；随后全 295 源文件及五项正常 TLS HTTPS 读回通过。

当时部署使用 [地点迁移流程](docs/JOURNEY-PLACES-RELEASE.md)，恢复演练显式选择 `journey_places44`。当前已是包含持仓操作回执的 55 表，不能重放历史迁移或本次已完成的 54→55；后续发布须绑定实际 55 表基线，完整恢复及发布边界见 [持仓发布](docs/HOLDINGS-RELEASE.md)。

NVIDIA 已于 16:58 通过独立配置步骤启用，模型为 `us/azure/openai/gpt-4o-mini`。服务器使用真实运行配置完成一次虚构家庭的模型待办草稿请求，未执行草稿或读取真实家庭事项；本次媒体发布保留这些配置。本人相册已授权，历史十选三、后续十选五及 JPEG 补丁后五选五成功的验收边界见顶部；真实新云写入和实体设备仍单独验收。

下面历次开发/发布段落保留其当时状态，当前安装身份以上述记录为准。

## 历史 13:24 更新：完整账本与金额校验

**历史开发阶段：地图当时已合 main `9559ca4`，尚未部署；现在已按顶部记录发布。** 可记录心愿、已计划及明确确认的已到访地点，按年份、成员和旅行筛选，打开关联旅行继续编辑；默认私密，可单独共享并隐藏、粗化或公开坐标。使用同源世界概览底图，支持无坐标记录；不提供街道导航或自动定位。地点数据进入有权限投影的个人 ZIP 导出，电视不能读取。使用与接口见 [地图界面](docs/JOURNEY-MAP-UI.md)、[地点接口](docs/JOURNEY-PLACES.md)、[应用接入](docs/JOURNEY-MAP-INTEGRATION.md)。

地图组合经过真实临时 Flask/SQLite/Edge 的 10 项流程检查，包括保存后重启读回、刷新保留草稿、旅行关联、成员切换清理、共享撤回和并发修改恢复。当前本地地图基线为 112 个方法／路径模板、44 张户内表及 2 张平台表；服务器仍是上方 43 表版本。上线必须走独立的 43→44 迁移和恢复验证。Google Photos 已选为首个影像来源，采用本人选择授权；相册授权界面、索引与电视播放仍在开发。

该开发阶段另有**本地已实现、当时尚未部署**的 NVIDIA 助理与开发编排，见 [模型配置及失败处理](docs/ASSISTANT-PROVIDER.md)、[并发编排使用说明](docs/INFERENCE-ORCHESTRATION.md)。产品适配经 168 项隔离回归，并通过真实模型生成草案→本人确认→幂等保存→重启读回及旅行简报的 18 项检查；使用虚构家庭数据，未连接生产账户或写云日历。开发编排的 24 个需求任务全部返回，配置 24 worker、实测峰值 14，用量 10,278 tokens；它们是未审查建议，不是 24 个功能交付。

扩展阶段、四个最终验收场景与地图后续关联/影像/库存/成员关系缺口见 [产品计划](docs/PRODUCT-PLAN.md)。根 [DESIGN.md](DESIGN.md) 是取得并审查的视觉参考；地图迁移与部署独立推进，不用当前本地代码或模型调用成功代替线上验收。

进入「财务 → 账单与订单」，选择月份后可搜索标题、交易编号和商品明细、翻页查看全部本人记录。同月超过 500 条的记录也能继续核对；修改、删除或采购核对后保留查询和合理页码。月度预算和汇总始终使用完整账本；翻页期间发生变化时提示刷新，避免混用不同结果。

文件导入接受完整的 `1,234.56`、`¥ 1,234.56`，拒绝 `1,23` 等有歧义的金额格式并标出行错误；不会猜测或修订历史记录，手工金额接口保持原约定。接口见 [财务 API](docs/FINANCE-API.md)，格式见 [导入契约](docs/FINANCE-IMPORT.md)。

后端、界面、工具策略与文档各自在独立分支／worktree 提交，由非作者审查后合入 integration；组合验证和再次审查后合入 main，再独立完成镜像、双户演练及生产发布。Windows／Linux 各 435 项受影响后端、新镜像 275 项发布工具、7 组 215 项浏览器分别记录，不能相加为一次全套测试。数据结构、依赖和账户配置保持。

## 历史发布：11:39 的订单与待办增量

已审 integration `ecc3edc` 合入 main `54c0854` 后，以同一文件树完成构建、隔离验证及实际发布。此次更新包括以下功能；开发、审查、合并和上线分别记录在 [HANDOFF](docs/HANDOFF.md) 和 [VALIDATION](docs/VALIDATION.md)。

- **待办起步：** 从空清单添加首项本地待办，或设置常用清单后返回；云端发布仍需选择、预览和确认。
- **淘宝订单：** 已验证的 XLSX 格式按明确合并范围识别订单，保留各项商品名称、规格、数量、标价和地址原文；订单实付只计算一次。缺失或冲突的结构仍拒绝，不补猜日期、金额、币种或退款。
- **重复导入：** 订单状态或内容变化会提示冲突并保留原记录；不会静默覆盖以前的核对结果。
- **商品明细界面：** 在预览、本人账本与核对页展开查看；数量和标价不参与额外合计，商品地址仅作为文本。接口见 [财务 API](docs/FINANCE-API.md)，支持范围见 [导入契约](docs/FINANCE-IMPORT.md)。

真实原文件仅完成本地临时预览，没有确认写入私人账本。本次按 [43→43 源码发布流程](docs/SOURCE-RELEASE.md) 更新两项既有 Python 与五项静态文件，没有 schema、依赖或配置变化。Windows 受影响后端 406 项、新镜像 Linux 后端 406 项与工具 269 项分别通过；浏览器 187 项补测功能与 65 项适用历史结果分列，共 252 项，另有 59 项路由，不是一次全套重跑。双户隔离演练与实际单户生产的备份、数据保持和读回分别记录。不能用 static-only 入口承接 Python 修改，也不能重放旧的 42→43 迁移。

## 历史 13:24 版本与交接状态

该历史版本于 **2026-09-16 13:24:33（北京时间）** 发布，镜像 `sha256:ea399441e6696bc29214842ab8c47e3db943714c1ae72a05ca1266bdc4a1b739`，固定继承 `f82bc0fc…` 父镜像并追加一层完整 Python/static。requirements、Dockerfile、Compose、Nginx、原 `.env` 与完整解析配置保持，没有 schema 初始化或数据库恢复。

| 项目 | 已核验结果 |
|---|---|
| 技术栈 | Flask／原生 JavaScript／SQLite；Docker Compose 运行 app、sync、web |
| 发布源码 | 258 文件、43 Markdown，manifest `7089ca8899929ec8eee8b705547943c697b21c684014855f92b7f5ca4fa8fb42`；发布后七份文档及文档检查器修订仅在本地 |
| Git 基线 | 已安装 integration `82f4401` → main `79faaf3`，同树 `e627bb8…`；各任务独立分支/worktree，无托管平台强制保护 |
| 接口与存储 | 107 个 Flask 方法／路径模板，另有 WSGI 家庭入口；43 户内表（41 业务 + 2 认证）、平台 2 表 |
| 受影响后端 | Windows 435 passed；新镜像 Linux 同一组 435 passed；各 0 skipped / failed / error |
| 新部署工具 | 新镜像 Linux 275 passed；先前专项 88 项按依赖适用性另列，不重复计数 |
| 受影响浏览器 | 7 组 215 项；真实临时 Flask/SQLite/Edge、虚构输入、0 页面错误与外站请求，非一次全套测试 |
| 实际 SOURCE 演练 | 两户合成 Docker：每户 43 表、平台 2 表、旧认证、8 份资料和 3 库备份保持；不执行恢复，受管资源清理通过，保护镜像而保留一个标签 |
| 生产数据与配置 | 实际 1 户 43 表 + 2 平台表、2 库完整组备份；安装前、启动后和 HTTP 后三次完整比较通过，原 `.env` 与完整解析配置保持 |
| 内部读回 | 44 静态 SHA 和 8 匿名权限 GET 通过；app/sync/web 正常且 app 健康；发布后独立核对全部 258 源文件、manifest、原配置和镜像 |
| 仍待真实验收 | 新云日历／待办写入、银行或电商自动连接、可选模型、用户端公网浏览器与实体设备、生产覆盖恢复和商业化运营 |

服务器另经正常 TLS 验证完成五个匿名 HTTPS 读回：healthz 200、新账本 API 401，以及三项更新的静态资源 200 且 SHA 匹配。这仅是服务器 HTTPS 客户端验证，不代表手机或实体电视验收。数据相等结论覆盖停写至 HTTP 核对窗口，恢复 sync/web 后允许正常业务变化。

### 旅行资料

从旅行或具体航班、住宿、活动进入资料夹，上传 PDF/JPG/PNG/WebP。默认仅上传者可见，明确共享后本户另一成员可读；电视不能读取。上传者可改标题、关联旅行或分段、逐份下载和删除。删除旅行后资料保留在“我的旅行资料”，可重新关联；文件不进入云日历、待办或助理。五个接口、大小限制、幂等及恢复边界见 [资料契约](docs/JOURNEY-DOCUMENTS.md)。

旅行详情展示已保存的航班号、起降、住宿地址、活动地点与备注，可复制并从日程定位原分段。已保存文件不代表预订平台或文件安全扫描验收。个人数据 ZIP 只含允许的资料元数据，批量文件迁移仍未实现；单份文件在资料夹明确下载。

| 入口 | 地址或文档 |
|---|---|
| 日常管理 | [家庭中枢](https://home.caesarcharles.world/) |
| 电视展示 | [电视配对与只读看板](https://home.caesarcharles.world/tv) |
| 虚构数据演示 | [普通演示](https://home.caesarcharles.world/demo)／[电视演示](https://home.caesarcharles.world/demo?tv=1) |
| 账号接入 | [Microsoft／Google 配置指导](docs/ACCOUNT-SYNC.md) |
| 新 agent 阅读顺序 | 本 README → [HANDOFF](docs/HANDOFF.md) → 所负责模块契约 → [DEVELOPMENT](docs/DEVELOPMENT.md) |
| 部署人员阅读顺序 | [DEPLOYMENT](docs/DEPLOYMENT.md) → [OPERATIONS](docs/OPERATIONS.md) → [VALIDATION](docs/VALIDATION.md) |

交接历史：16:25 为 218 文件／35 文档，20:23 旅行资料为 237／40，22:32 静态发布为 248／42，11:39 SOURCE 发布为 255／43，本次为 258／43。各次原件和迁移边界分别保留。

## 此前旅行与资料能力

此前已发布的首页快速记录、旅行卡和旅行页新建入口继续统一进入“填写 → 预览准备／采购／日程 → 确认”的旅行向导；已有草稿保留，旧旅行仍能编辑。确认前不保存，也不自动订票、付款或写入云端。使用与公共接口见 [新建旅行入口](docs/TRAVEL-ENTRY.md)。

该历史静态发布只改变三个前端文件，原演练失败、生产预检拒绝与受控重试继续保留在 [验收记录](docs/VALIDATION.md)；不与本次 SOURCE 验证混算。

旅行资料、完整细项、旅行执行、订单兼容、消费观察及其他模块继续保留。真实消费观察文件仍未自动上传或确认，见 [消费观察契约](docs/SPENDING-OBSERVATIONS.md)。

## 已开发范围与边界

下表描述当前已发布实现；真实账号、数据覆盖和实体设备的未验收范围单独列出。

| 模块 | 已实现 | 当前边界 |
|---|---|---|
| 工作台 | Expo 桌面横向顶部导航、窄屏五项底导航；日常主流程在新版操作，高级模块由更多／账户菜单进入 classic | 经典页保留侧栏与页面搜索；搜索不包含私有财务，电视保持独立布局 |
| 主题与偏好 | Expo 成员浅色／深色、标准／紧凑密度及本人首页排序／隐藏已发布；classic 与电视保持独立配色，默认日程范围采用 CAS 保存 | 密度覆盖导航、页头、共享卡片与首页；日程／清单内部密度及范围按钮已优化并实测，完整可访问性审计仍待完成；拖动与自定义背景未实现，隐藏不改变 API 可见范围 |
| 家庭与身份 | 邀请创建独立家庭、成员密码登录、资料维护、Microsoft / Google 绑定身份登录、显式切换家庭 | 默认最多 30 户、每户两人；无公开匿名注册、收费或更多成员角色 |
| 登录设备 | 查看本人有效浏览器登录；确认退出指定或其他全部会话；当前浏览器可从设置退出 | 最近使用约每 5 分钟更新；名称仅概括浏览器和系统，不证明物理设备或实时在线；云账号绑定与 TV 配对保持 |
| 日程 | 今日、本周、前后 3 天、翻页、完整标题/地点、每日数量与时段并集；本地安排及两个云平台读取 | 自动轮询；仅统计选择的来源；纯 iCloud 实时连接未完成 |
| 家庭例行计划 | 每日／每周／每月共享模板、三期预览、完成推进、暂停／恢复／跳过／归档、历史和助理入口 | 上海日期、固定月末 clamp；当前事项独立；新期不复制采购实付／照片／旅行或云来源，不自动发布到云 |
| 待办 | 本地任务与云清单新建/完成回写；旅行/助理/已有任务可确认发布到 Microsoft To Do 或 Google Tasks 主清单，保留原 ID/负责人并回流完成状态 | 新发布队列尚未完成真实云写验收；轮询同步；不确定创建结果需查远端，不盲目重建 |
| 采购与图片 | 数量、负责人、备注、预计总价、实付、勾选、最多 3 张参考图片；压缩与认证读取 | 未知金额与零区分；HEIC 需转换；不自动扣减公共资金 |
| 采购实付核对 | 本人账单或已核对订单选择有效 CNY 付款；搜索分页、整项实付和独立完成状态、预览确认、读回、更新、来源变化提示与两种解除；精确进入原对账后可返回 | 私有来源不公开，只共享 actual/done；不修改账本、预算、公共余额或旅行 paid，不自动响应退款，不执行付款或转账 |
| 旅行联动 | Expo 将自然语言简报在单页补齐后带入可编辑计划；经典入口保留原向导；v1/v2 虚构 JSON 模板下载、格式说明、文件/粘贴导入后审阅确认；多国家/城市、航班起降当地时间、住宿入住/退房、活动、预订状态；预览后生成准备任务、采购和日程；详情自动刷新进度、按负责人筛选并处理原发布；迁期保留固定事项、三方比较保护独立编辑 | 预订状态由用户标记，未连接航司/酒店订单；日期/时区语义变更须再次核对云发布；旧日期级计划兼容 |
| 旅行地图 | 已发布 Expo 地点管理、确认到访、坐标与共享精度、年份／成员／旅行筛选、分页，以及关联旅行／只读相册往返 | 世界概览只显示当前页授权坐标；无街道导航／外部地理编码，TV 不读；真实新入口、自动照片关联与路线回顾另验或待实现 |
| 家庭物品 | 手工物品、采购批次、分批到货、消耗／报损／退回与反转原流水；默认私有、明确共享、分页和个人 ZIP | 已上线；本人真实使用反馈待补；不自动商家下单、收货、补货或金融入账；TV 不读取；助理库存搜索只读本地授权范围，不调用模型 |
| 家庭相册 | Google Photos 本人选片、后台净化加密、明确保存为私密副本、旅行关联、家庭共享、逐台电视许可及照片元数据导出 | 已发布；JPEG 补丁后本人实际选片、预览、保存 5／5 成功；原失败根因未确定，实体电视与长期行为另验；仅照片，不支持视频、iCloud／NAS或自动回忆精选 |
| 旅行资料 | 本人资料库、旅行／分段关联、私有或明确共享、上传重放、修改、逐份下载和删除 | 文件只由用户上传；PDF 不内嵌、不抓 URL；不声称病毒扫描或预订核验；TV 不可读 |
| 云日历发布 | 独立写权限升级、目标日历选择、确认入队、创建/更新读回、迁期、重试、暂停、远端修改冲突核对；时间语义复核与同目标重连恢复 | 新写流程仅完成本地模拟服务商验收；需本人真实授权验证；不自动邀请与会者或删除远端事件 |
| 公共财务 | 荷包余额、日常预算、旅行准备金、储蓄、出资比例、核对日期；经批准的资产/负债汇总 | 手动快照；支付宝小荷包与银行没有自动连接；不执行转账或理财交易 |
| 私有财务 | 完整本人账本分页和标题／编号／商品搜索；CSV/XLSX 工作表与金额列选择；账单/订单预览、确认与对账；确认后定位实际月份，成功后读回失败只重试 GET；完整来源基线和独立消费观察分别预览确认，原资产/负债小计保持批准的共享范围 | 真实文件变体和私人来源映射未全部验证；观察报告不是已核对实付，不与账本相加；未启用无人值守刷新或银行连接 |
| 投资 | Expo 本人完整持仓与筛选、分币种精确汇总、手工增改删、CSV/TXT/XLSX 整理表预览、稳定来源关联、版本保护、导出及持久回执恢复 | 没有完整资产账户、负债编辑、估值历史、券商连接、实时行情或自动汇率；缺估值不按零处理，股息费用不含在当前盈亏中 |
| 助理 | 旅行文字简报、可选 AI 与手工补齐、明确重新整理和旅行预览确认；本地近期概览、搜索、待办/采购草案与逐项确认；已发布“本周待处理”，从待办、冲突日程、采购金额、旅行准备和公共资金打开原记录；存在到期或异常例行计划时显示第六组，处理后回读 | 行动台范围为今天至七天后并含逾期待办，不是完整自然周；默认本地规则，可选模型调用另行验收 |
| 电视与手机 | 配对、撤销、独立侧重成员／日程范围／卡片／主题／密度；手机管理逐屏照片许可及开始／暂停／继续／翻页／间隔，电视只读轮播获准照片 | 不返回私有财务；家庭共享不自动授权电视；实体 50／75 英寸电视、离线编辑及各系统安装体验待验收 |
| 同步问题中心 | 共享来源状态、本人账户／来源和可管理发布项；超过 5 分钟、等待、失败、授权与未知状态分开；相同业务 revision 也局部刷新摘要 | 仅读数据库记录，不探测服务商、不自动重试或写云端；不能证明外部内容完整、进程实时健康或金融来源已同步 |
| 运维与同步 | 加密令牌、分页后发布、失败保留旧数据、退避、账号锁；多家庭调度；全家庭在线备份与归档校验 | 单服务器；两户虚构数据已通过实际 Docker 恢复；无第三方 webhook、异地备份或真实生产恢复演练 |
| 个人数据副本 | 设置页导出本人资料/财务/投资/布局；可选附带家庭共享记录；ZIP 带 JSON/CSV 与散列清单 | 照片和旅行资料仅元数据，不含文件 BLOB、令牌或伴侣私密；无一键重新导入 |

### 财务与隐私规则

个人消费走个人账户，共同消费走公共资金。税后到账收入出资比例默认 50%，荷包周转目标默认 ¥10,000；日常 ¥6,200/月、旅行 ¥104,000/年是**可修改的规划参考**，不是已发生消费或已核对余额。

| 数据 | 本人 | 伴侣与本户电视 |
|---|---|---|
| 明确共享的日程、任务、采购、旅行、公共资金 | 可见；成员可编辑 | 可见；电视只读 |
| 经批准的资产、负债汇总及其覆盖说明 | 可见 | 可见 |
| 个人账户、消费明细、私有导入账本、投资明细与收入基础 | 可见 | 不可见 |
| 导入后明确确认共享的汇总 | 可见 | 仅可见授权汇总，不附带明细 |
| 其他家庭的数据与第三方令牌 | 不可见 | 不可见 |

来自个人财务仓库的现有基线仍是固定版本、部分覆盖的快照。新增来源工具可准备并预览候选；当前真实来源尚未完成稳定映射和缺失日期核对，没有启动持续刷新。缺失资产、负债或估值时不能据此宣称完整净资产；基线与后续投资记录也不直接相加。真实账单、数据库、账户名与密钥不放入源码、测试夹具或公开文档。

## 软件架构

Expo 按用户最新要求参考 [expo.dev](https://expo.dev/) 当前界面：白底、近黑文字、黑色胶囊按钮和浅灰大圆角区块，登录页去除天空渐变；中文使用系统字体回退。实页依据与尺寸见 [官网风格](docs/EXPO-SITE-STYLE.md)，优先于较早生成的 `expo/DESIGN.md` 描述。宽度达到 1040px 时采用顶部横向导航，窄屏保留五项底导航；经典页保留 [原电视设计](docs/approved-tv-prototype.png)；Expo 电视展示保留各自主题与布局偏好，仍独立只读。入口契约见 [Expo 接缝](docs/EXPO-NAVIGATION.md) 与 [经典工作台](docs/WORKSPACE-UI.md)。

```mermaid
flowchart LR
    Client[手机 / 电脑 / 只读电视] --> Web[Nginx HTTPS]
    Web --> App[Gunicorn + Flask\n家庭路由与成员授权]
    App --> Registry[(平台注册表)]
    App --> DB[(各家庭独立 SQLite)]
    Sync[独立同步 worker\n最多并行两个家庭] --> DB
    Sync <--> Cloud[Microsoft Graph / Google APIs]
    App --> Cloud
    App --> Optional[可选模型服务\n成员逐次选择]
    Backup[在线备份 + 清单校验] --> Registry
    Backup --> DB
```

| 层 | 方案 |
|---|---|
| 前端 | 新版为 React Native／Expo Router／React Native Web／Paper，npm 构建后由 Flask 同源托管；高级模块暂保留 `/classic` 原生 JavaScript／hash 界面。生产无独立 Node 运行服务，部署状态见文首 |
| Web 后端 | Python 3.12 生产容器、Flask 3.1.2、Gunicorn 23；1 worker / 4 线程，内部端口 8000 |
| 数据与安全 | SQLite WAL、事务与 revision；成员授权、CSRF/同源检查、scrypt 密码散列、加密第三方令牌、图片解码重编码 |
| 同步 | 独立 `sync_worker.py`；任务约 30 秒、日历约 60 秒到期检查，页面每 10 秒取共享状态；条件回写、持久化队列及远端读回，错误退避，实际延迟受服务商响应与家庭数量影响 |
| 文件与时间 | icalendar / recurring-ical-events、Pillow；CSV/XLSX 有界解析，拒绝公式、外链及不支持的格式；固定 `tzdata==2026.4`，旅行存当地时间、IANA 时区与确认后的 UTC 时刻 |
| 部署 | Docker Compose：app、sync、media、web 四服务；锁定基础镜像；Nginx TLS / ACME；持久化命名卷 |

平台注册目录为 `/data/platform.sqlite3`；原家庭为 `/data/household.sqlite3`；子家庭为 `/data/spaces/<随机 id>/household.sqlite3`。当前为 **54 张户内表和 2 张平台表**，财务回执已完成 53→54 显式迁移，新增 `hub_import_receipts`；旧 `hub_imports` 七列及全部原有数据、权限保持。新交易保存首次批次来源，历史未知不回填。完整结构见 [存储索引](docs/PLATFORM-ROUTES.md)、[数据模型](docs/DATA-MODEL.md) 和 [回执迁移与恢复](docs/FINANCE-RECEIPTS-RELEASE.md)。

家庭 routing cookie 只选入口，不授予登录权限；会话和令牌加密密钥按家庭派生。切换家庭会退出原会话。坏 cookie 返回带恢复入口的错误，已注册家庭缺少数据库时返回 503，不能用原家庭环境密码自动补建身份。

## 代码地图

下方文本地图保留集成阶段的原始注释；其中旅行资料标为“候选”的模块现已发布，当前状态以文首与资料契约为准。

```text
family-dashboard/
├─ app.py                      # 基础路由、身份、共享实体、模块注册
├─ member_sessions.py          # 会话登记/撤销、旧 Cookie 迁移、浏览器认证代次
├─ tv_display.py               # 每台电视的布局校验与旧配置默认值
├─ household_spaces.py         # 家庭注册/邀请/路由、成员偏好
├─ cloud_accounts.py           # OAuth、来源选择、同步协调与任务回写
├─ cloud_providers.py           # Microsoft / Google 适配器
├─ sync_worker.py              # 多家庭调度：待办发布→日历发布→云读取→例行推进
├─ household_routines.py       # 共享周期模板、逐期本地生成、历史与确认回执
├─ sync_health.py              # 只读来源新鲜度、家庭聚合与本人问题筛选
├─ calendar_publish.py         # 旅行云日历授权、发布队列与冲突
├─ task_publish.py             # 本地待办到主清单、回流与冲突
├─ dashboard_preferences.py    # 本人成员首页布局与版本控制
├─ data_portability.py         # 个人数据副本、格式与导出白名单
├─ journey_workflows.py        # 旅行及任务/采购/日程联动
├─ journey_time.py             # 当地时间、IANA/DST、航班/住宿/活动投影
├─ journey_documents.py        # 候选：成员资料、上传/下载、权限与旅行关联
├─ finance_baseline.py         # 财务基线与共享白名单
├─ finance_source_bridge.py    # 来源候选、日期/覆盖校验与 CAS 接收回执
├─ spending_observations.py    # 本人消费观察、覆盖校验与独立持久回执
├─ finance_hub.py              # 私有账本、导入确认、预算与投资
├─ investment_import.py        # 私有持仓文件、来源键、预览确认与回执
├─ financial_files.py          # 有界账单文件解析
├─ home_assistant.py           # 概览、草案、确认执行、可选模型
├─ shopping_media.py           # 采购图片与权限
├─ shopping_settlement.py      # 本人付款到采购实付的预览确认、版本及私有回执
├─ frontend/                   # Expo React Native 源码、锁文件与构建说明
├─ frontend_runtime.py         # /app 同源导出托管、/classic 和原回调衔接
├─ static/
│  ├─ experience/              # 经发布证据绑定的 Expo 导出；不手工修改
│  ├─ index.html / app.js / style.css
│  ├─ accounts-ui.js / calendar-ui.js / shopping-ui.js
│  ├─ finance-baseline.js / finance-hub.js
│  ├─ investment-import.js / investment-import.css
│  ├─ shopping-settlement.js / shopping-settlement.css  # 采购实付核对界面
│  ├─ household-routines.js / household-routines.css  # 例行模板、预览、历史与原事项返回
│  ├─ finance-source-ui.js      # 来源文件、本人预览与确认界面
│  ├─ journey-ui.js / calendar-publish.js / task-publish.js
│  ├─ journey-documents.js / journey-documents.css  # 候选：本人资料与旅行资料夹
│  ├─ home-assistant.js / household-spaces.js
│  ├─ data-portability.js
│  ├─ member-sessions.js / member-sessions.css  # 本人登录设备与撤销
│  ├─ tv-display.js / tv-display.css  # 电视设置、预览与屏幕布局
│  ├─ sync-health.js / sync-health.css  # 同步问题中心及轻量摘要
│  └─ product-shell.js / product-shell.css  # 最后加载的工作台外壳
├─ Dockerfile / compose.yaml / requirements.txt / pytest.ini
├─ deploy/                     # 源码打包、初始化、配置、备份、续期与导入
├─ tests/                      # 隔离单元/集成与浏览器回归
└─ docs/                       # 产品、接口、部署、验收与交接文档
```

新版从 `frontend/src/app/` 进入统一会话上下文，使用现有 `/api`，构建方式见 [前端说明](frontend/README.md)。`/classic` 的脚本仍以 `defer` 顺序加载，基础 `app.js` 在 DOM 就绪后启动；模块加载与公共接口见 [工作台文档](docs/WORKSPACE-UI.md)。两套页面不同时加载各自的外壳。新增资产须核对入口引用、Docker 复制范围与发布清单。

## 接口与数据契约

当前接口索引为 **149 个 Flask 方法／路径模板**，包含三个 Expo／classic 托管 GET 与新增的本人导入回执 GET；另有 WSGI `GET /space/<slug>`，HEAD/OPTIONS 不重复计数。见 [路由索引](docs/PLATFORM-ROUTES.md)和[托管契约](docs/EXPO-WEB.md)；机器结构由实际应用生成，字段与权限仍见各模块契约。

| 接口族 | 内容与权限 |
|---|---|
| 会话、资料、状态、实体、设备 | 签名与服务端有效会话共同鉴权；写请求验证 CSRF/同源；TV 仅授权只读；共享实体用 revision 防冲突 |
| `/api/sessions*` | 本人有效登录列表、退出指定会话和退出其他会话；认证记录不进入个人 ZIP，不影响已绑定云账户或电视配对 |
| `/api/accounts*`、`/api/auth/*` 与 OAuth 回调 | 第三方绑定、登录、来源与同步；账户按成员归属，回调验证 state |
| `/api/spaces/*`、`/space/<slug>` | 当前家庭入口、邀请与兑换；只有原家庭 member1 可签发邀请，邀请码不直接授予账本权限 |
| `/api/sync-health` | 只读本人账户、来源与可管理发布问题；家庭共享摘要另由 `/api/state` 返回，不自动请求服务商或重试 |
| `/api/routines/*` | 全家共享计划管理，成员专用；预览绑定发起会话、家庭、规则／当前实体版本、日期和容量，确认原子提交及回执重放；TV 无管理权限 |
| `/api/preferences` | 本人成员偏好 GET 返回 `theme/density/homeView/colorMode/revision`；PUT 仅 `{revision,changes}`，冲突 409；匿名与 TV 不可读写，见 [偏好契约](docs/MEMBER-PREFERENCES-API.md) |
| `/api/dashboard-layout` | 本人卡片顺序/隐藏 GET/PUT，完整 revision/order/hidden，冲突返回 409 |
| `/api/journeys/*` | 旅行预览、签名确认、事务更新和关联实体版本核对 |
| `/api/inventory/*` | 当前成员的物品、批次、实物流水和幂等回执；共享撤回即时核验，TV 禁止读取；见 [库存 API](docs/INVENTORY-API.md) |
| `/api/assistant/search` | 本地授权范围内只读检索物品名称／规格／位置、照片说明与地点等文字，不把结果送模型 |
| `/api/journey-documents*` | 本人/旅行资料库、上传、元数据修改、删除与认证附件下载；所有 TV 访问被拒，上传者明确决定共享范围 |
| `/api/calendar-publish/*` | 本人云账户写授权、预览确认、发布状态与冲突恢复 |
| `/api/task-publish/*` | 本地任务预览确认、目标主清单、发布状态、暂停恢复与冲突选择 |
| `/api/finance-hub/*`、财务基线与个人财务接口 | 本人私有账本、导入、预算与投资；共享内容只返回明确授权的汇总 |
| `/api/finance-hub/shopping-settlements/*` | 本人 context、preview、confirm；apply/update/revoke 明确确认，仅投影采购 actual/done，不修改账本或自动共享来源 |
| `/api/finance-baseline/imports/*` | 本人来源状态、预览和确认；默认完整财产基线，显式 spending_observation 仅更新消费观察，两种模式各自校验版本／日期／覆盖，不接受客户端直接指定共享总额 |
| `/api/assistant/*` | 本人成员概览、待办／采购草案与确认；旅行 brief 只整理本次文字，经独立向导预览和明确确认才保存，不触发云发布 |
| `/api/portability/*` | 本人数据摘要与 ZIP 下载，共享记录须显式勾选；拒绝电视访问 |

金额字段、日期、错误码和状态机按具体契约处理，不根据 UI 字符串推导。远端任务镜像、旅行关联、已核对财务金额和私有明细不能混作同一种共享实体。保存失败应保留草稿；重试需使用原操作的幂等标识，不能靠重新生成请求掩盖冲突。

已保留的跨模块流程：旅行准备／采购编辑后回到原旅行，保留草稿并区分实际超支与预留超额；缺少目标来源时可配置账户后显式返回原发布页，重新读取身份与目标，不自动勾选或发布。worker 在同步阶段之间响应停止。详见 [使用手册](docs/USER-GUIDE.md)、[连接返回](docs/CONNECTION-RETURN.md)与[运维说明](docs/OPERATIONS.md)。

## 本地开发与验证

生产镜像使用 Python 3.12，本地 Windows 已使用 Python 3.14 验证。Expo 前端使用锁文件安装和 npm 构建，Node 也运行前端辅助测试；安装、类型检查、导出与同源验收见 [前端 README](frontend/README.md)。生产只托管导出的静态资源，无需独立 Node 服务。

在本项目目录创建独立环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest playwright
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_calendar_views.js
```

手动启动前，按 [本地配置](docs/DEPLOYMENT.md#2-配置密钥与数据文件) 设置独立开发密钥、两份至少 12 字符的测试密码及临时 `DATA_DIR`。Python 应用不会自动读取 `.env`。本机 HTTP 使用 `COOKIE_SECURE=0`、`TRUST_PROXY=0` 和 `FLASK_SKIP_DOTENV=1`，只绑定回环地址：

```powershell
.\.venv\Scripts\python.exe -m flask --app 'app:create_app()' run --host 127.0.0.1 --port 8765
```

按修改范围运行对应单元、集成与浏览器检查，完整清单见 [DEVELOPMENT](docs/DEVELOPMENT.md)。`pytest` 不会自动运行 `browser_*_check.py`；这些脚本使用临时 Flask／SQLite、虚构数据和本机 Edge，具体浏览器路径见脚本。示例：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_household_routines.py tests/test_routine_journeys.py
.\.venv\Scripts\python.exe tests/browser_household_routines_check.py
.\.venv\Scripts\python.exe tests/browser_product_shell_check.py
.\.venv\Scripts\python.exe tests/inspect_contract.py
.\.venv\Scripts\python.exe tests/check_documentation.py
```

接口索引脚本只在临时数据库实例化路由与结构，不能替代完整字段契约。文档检查需要 Python、PowerShell 和 `sh`，检查链接与语法并在临时数据库运行恢复示例，不执行部署命令。截图和运行报告写入 `test-results/`，不进入通用交接包。

开发环境使用虚构数据和独立密钥。旧 `live_check.py` 等脚本可能写正式环境或重启服务，不作为默认回归入口。云发布的模拟服务商测试与真实账户验收分别记录。

## 部署方案与指导

当前部署在 **racknerd VPS / Ubuntu 24.04**，维护者使用已配置的 SSH 别名 `racknerd`，项目目录为 `/opt/family-dashboard`。Name.com 管理域名 DNS。前后端在同一个应用镜像内交付，Nginx 统一提供 HTTPS。

| 服务或目录 | 部署方式 |
|---|---|
| `app` | Gunicorn，内部 8000 端口，384 MB；UID 10001、只读根文件系统 |
| `sync` | 与 app 同源镜像，运行 `sync_worker.py`，192 MB；共享持久化卷，无公网监听 |
| `web` | Nginx，96 MB；对外 80／443，挂载 TLS 证书与 ACME 目录 |
| 数据 | 命名卷 `family-dashboard_household-data` 挂载到 `/data`；平台目录与各家庭数据库位于卷内 |
| 配置 | `/opt/family-dashboard/.env`，权限 0600；由 Compose 注入，更新保留原密钥和成员配置 |

安装、DNS、HTTPS 证书与续期、OAuth 回调、备份及恢复见 [部署指导](docs/DEPLOYMENT.md)。当前为 55 表，首次安装与已有数据更新使用各自流程；本轮固定发布及数据保全见 [电视展示发布说明](docs/EXPO-TV-RELEASE.md)。[54 表回执恢复](docs/FINANCE-RECEIPTS-RELEASE.md) 和历史 43 表发布入口仅供追溯，不能用作当前发布入口：

- **首次安装**：配置新服务器与独立密钥，初始化新数据卷，签发证书，启动 app／sync／media／web 四个服务，再绑定第三方账户。
- **已有环境更新**：冻结实际已安装 BASE 和审查后的候选，在独立目录构建与验证；通过部署演练和独立发布审查后，停止写者、核验全组备份、安装源码并分阶段核对全部数据，再开放服务。当前为 55 表；任何后续结构、依赖或配置变更需另行审查，不能重用历史 43→43 控制器或已完成的 53→54 迁移。

源代码打包命令为 `python deploy/prepare_release.py`，产物为 `release.tar.gz` 与归档内的 `RELEASE-MANIFEST.json`；它不生成登录凭据。发布白名单包括源码、文档和测试，排除 `.env`、数据库、私人财务输入与运行证据。

历史版本完成 37→40、40→42、[42→43](docs/JOURNEY-DOCUMENTS-RELEASE.md)、43→44、44→48、[48→53](docs/INVENTORY-MIGRATION.md)、[53→54](docs/FINANCE-RECEIPTS-RELEASE.md) 及 [54→55](docs/HOLDINGS-RELEASE.md)。[静态 43→43](docs/STATIC-RELEASE.md)、[SOURCE 43→43](docs/SOURCE-RELEASE.md) 和 DEPLOYMENT 第 5.2 节的历史算法均不可用于当前 55 表；已完成的一次性迁移不能重放。

备份使用 SQLite 在线备份，包含平台注册目录及全部已注册家庭，输出散列清单并保留最近 14 组。它不是跨数据库的原子快照；恢复必须核对完整备份组、配套密钥与家庭映射，按 [会话恢复要求](docs/MEMBER-SESSIONS.md#恢复后使旧成员登录失效) 使旧成员登录失效。已完成两户虚构数据的[实际 Docker 恢复演练](docs/RECOVERY-REHEARSAL.md)，包含旧登录失效、照片和隔离核对。异地备份与真实生产恢复尚未完成。

现有环境不要执行 `docker compose down -v` 或覆盖密钥。发布后已有业务写入时先保全现场，再决定恢复方式；旧镜像不能直接连接未知的新结构。日常检查与排障见 [OPERATIONS](docs/OPERATIONS.md)。

## 多 agent 联合开发

项目已建立**独立本地 Git 仓库**，基线提交 `ad667bf2b744d707db080964c662249c7cd8b056`，标签 `baseline/2026-09-15-handoff`。父 `AI` 仓库通过本机 exclude 忽略本目录，原索引保持；当前没有远端，不使用 `git pull` 部署。

**每个 agent 使用独立 `codex/<agent>-<task>` 分支与 worktree。** 提交后由另一位 agent 审查，集成人按依赖顺序合入 `codex/integration`；组合测试和再次审查通过后才合入 `main`。代码合入与生产部署是两个步骤。禁止不同 agent 共用工作目录；文件分工继续用于约定模块边界，不能替代分支隔离。命令和合并要求见 [Git 协作指导](docs/GIT-WORKFLOW.md)，自动读取的项目约定见 [AGENTS.md](AGENTS.md)。

| 建议分工 | 独立文件与集成边界 |
|---|---|
| 后端集成人 | `app.py`、模块注册、基础 schema、身份与共享守卫；统一审批接口契约变更 |
| UI 工作台 | `product-shell.js/.css`、`dashboard_preferences.py`；公共 `index.html`、`app.js` 的插入由集成人统一处理 |
| 同步状态 | `sync_health.py`、`static/sync-health.js/.css`；共享摘要、footer、连接中心和加载顺序由集成人维护 |
| 云连接与发布 | `cloud_accounts.py`、`cloud_providers.py`、`calendar_publish.py`、`task_publish.py`；`sync_worker.py` 接缝交集成人 |
| 旅行 | `journey_workflows.py`、`journey_time.py`、旅行 UI；关联实体、日期投影与发布队列通过约定契约接入 |
| 采购实付 | `shopping_settlement.py`、`static/shopping-settlement.js/.css` 与专项；采购行、私有账本和原对账返回、app 注册与导出接缝由集成人协调 |
| 财务 | `finance_hub.py`、`investment_import.py`、`financial_files.py`、`finance_baseline.py`、`finance_source_bridge.py`、来源 CLI 与对应 UI；隐私、去重、稳定映射和金额口径一起交付 |
| 助理与家庭 | `home_assistant.py`、`household_spaces.py` 及各自 UI；公共身份与路由变更交集成人 |
| 数据导出 | `data_portability.py` 与对应 UI；只读数据快照、成员边界与格式兼容 |
| 发布与独立验收 | Docker/Compose、发布白名单、文档、浏览器与隔离测试；正式发布只由一位维护者执行 |

每个任务应明确：目标、base commit、分支与 worktree、允许文件、依赖提交、接口/权限、数据迁移和验收场景。[联合开发接手说明](docs/HANDOFF.md) 提供任务模板。交付时记录 head commit、diff、测试结果、未验证范围及审查结论；未完成审查的候选留在功能分支。

采购实付、工作表和助理简报等历史候选均已合入发布，不重放旧补丁或用旧候选整目录覆盖。后续修改仍须协调共享文件：助理桥接使用 `journey-ui.js`，工作表、投资、对账与采购入口共用 `finance-hub.js`，采购入口还涉及 `shopping-ui.js`。独占负责人、BASE/RESULT 散列和同源码验证规则继续适用。

## 后续优先事项

1. 以本次已发布清单建立新任务基线；先选一个有明确输入、结果和失败恢复的真实闭环，再安排独立开发。
2. 在允许的环境完成真实手机／电视、OAuth 回跳及新增日历／待办写入的端到端验收。
3. 核对财务来源映射、贷款余额日期与脱敏账单／持仓格式；分开处理消费观察、资产余额与已核对实付。
4. 在现有合成 Docker 演练基础上，补齐异地备份、生产恢复验证、独立版本库及 CI/CD，再验证更多家庭的容量和可靠性。
5. 单独推进可选模型、Apple 提醒事项桥接、离线体验、更多角色和商业化能力，详见 [PRODUCT-PLAN](docs/PRODUCT-PLAN.md)。

## 文档导航

旅行执行的局部刷新、发布跟踪与接手测试见 [JOURNEY-EXECUTION](docs/JOURNEY-EXECUTION.md)。

接手顺序：本 README → [联合开发接手说明](docs/HANDOFF.md) → 本次负责模块的接口 → [开发与验收说明](docs/DEVELOPMENT.md)。部署人员另读 [部署指导](docs/DEPLOYMENT.md) 和 [运行与排障](docs/OPERATIONS.md)。

交接包中的 `RELEASE-MANIFEST.json` 记录逐文件 SHA-256，Git bundle 保留提交和分支。新任务从集成人确认的当前提交建立独立 worktree。服务器精确源码及 manifest 以文首和 [HANDOFF](docs/HANDOFF.md) 的当前发布记录为准；旧发布包与原清单分别保留。后续纯 Markdown 交接单列清单，不借文档变化改写原测试证据。

| 文档 | 用途 |
|---|---|
| [旅行资料与预订凭证](docs/JOURNEY-DOCUMENTS.md) | 文件格式、五个接口、私有与共享范围、幂等重放、删除旅行保留资料及迁移 |
| [旅行资料发布控制器](docs/JOURNEY-DOCUMENTS-RELEASE.md) | 一次性 42→43、候选与镜像绑定、READY 和原始证据合同、失败保全与运维边界 |
| [项目规则](AGENTS.md)／[Git 分支与审查流程](docs/GIT-WORKFLOW.md) | 独立 worktree、任务分支、审查记录、集成与主分支合并；Git bundle 联合开发 |
| [家庭例行计划](docs/ROUTINES.md) | 周期模板、未来日期、预览确认、下一期生成、共享导出与成员权限 |
| [采购实付核对](docs/SHOPPING-SETTLEMENT.md) | 本人来源、CNY 整项替换、独立完成状态、预览／确认／撤销、旅行保护与私有导出 |
| [同步状态与问题处理](docs/SYNC-HEALTH.md) | 全来源新鲜度、本人问题详情、只读接口、失败快照和原模块处理入口 |
| [电视布局与外观](docs/TV-DISPLAY.md) | 按屏幕配置卡片、主题、密度、预览与版本冲突；只读与家庭隔离边界 |
| [Expo 成员外观](docs/EXPO-APPEARANCE.md) | 已发布：本人浅色／深色、内容密度、明确保存、冲突及未知结果核对；[发布验收](docs/EXPO-APPEARANCE-ACCEPTANCE.md)，电视设置独立 |
| [投资持仓导入](docs/INVESTMENT-IMPORT.md) | CSV/XLSX 持仓、明确关联、差异预览、原子确认、重复回执、来源与本人导出 |
| [成员登录设备](docs/MEMBER-SESSIONS.md) | 本人浏览器会话、撤销接口、旧 Cookie 迁移、认证乱序边界及数据库回滚要求 |
| [产品目标与路线](docs/PRODUCT-PLAN.md) | 一站式家庭中枢目标、当前缺口、真实接通与商业化验收门槛 |
| [独立消费观察](docs/SPENDING-OBSERVATIONS.md) | 仅报告来源、滚动窗口、本人预览确认、独立存储与导出 |
| [财务来源更新与契约](docs/FINANCE-SOURCE-BRIDGE.md) | 来源转换 CLI、本人预览、日期/覆盖、CAS 确认、幂等及缺源保留旧值；真实映射与调度边界 |
| [旅行细项与时区契约](docs/TRAVEL-DETAILS-PLAN.md) | 航班/住宿/活动、当地时间与夏令时、迁期及独立编辑保护 |
| [Expo 旅行简报](docs/EXPO-JOURNEY-BRIEF.md)／[原简报契约](docs/ASSISTANT-JOURNEY-BRIEF.md) | 单页补齐、成员与预算、可选模型、可编辑计划桥接及明确保存；经典入口保留原向导 |
| [家庭成员使用手册](docs/USER-GUIDE.md) | 日程、待办、采购、旅行、财务、连接、电视与设置的操作路径 |
| [联合开发接手说明](docs/HANDOFF.md) | 线上/本地版本差异、模块接缝、独占文件、可复制的 agent 任务模板 |
| [平台架构与扩展](docs/PLATFORM.md) | 多家庭隔离、调度、助理、财务、旅行及运行约束 |
| [家庭物品交付](docs/INVENTORY-DELIVERY.md) | 入口、手工下单／收货／消耗／纠正、隐私共享、导出及迁移恢复边界 |
| [助理搜索](docs/ASSISTANT-SEARCH.md) | 本地照片说明／地点搜索与权限复核；[库存扩展](docs/ASSISTANT-INVENTORY-SEARCH.md)同样不调用模型 |
| [路由与存储索引](docs/PLATFORM-ROUTES.md) | 当前 149 个方法/路径模板、54 张户内表及 2 张平台表，字段见各模块专文 |
| [基础接口契约](docs/API.md) | 登录、CSRF、基础 CRUD、日程、采购、设备、财务基线等请求与响应；扩展字段参见对应模块文档 |
| [平台扩展接口契约](docs/PLATFORM-API.md) | 旅行计划字段、预览确认、版本幂等、助理、家庭空间与偏好的完整请求/响应 |
| [财务扩展接口契约](docs/FINANCE-API.md) | 账单预览与确认、账本、分类预算、投资字段及权限/错误约定 |
| [基础数据模型](docs/DATA-MODEL.md) | 实体 JSON、revision、照片、旧表与财务隐私；新增表以路由与存储索引及平台文档补充 |
| [工作台界面](docs/WORKSPACE-UI.md) | 页面路由、主题、可见性、脚本依赖、跨设备偏好与浏览器验收 |
| [账单导入与投资](docs/FINANCE-IMPORT.md) | CSV／GB18030／XLSX、预览确认、去重、预算、私有账本、估值口径 |
| [旅行云日历发布](docs/CALENDAR-PUBLISH.md) | 写权限升级、发布队列、幂等、远端读回、暂停与冲突核对 |
| [本地待办同步发布](docs/TASK-PUBLISH.md) | 旅行/助理/本地任务写入主清单、完成回流、冲突与不确定结果恢复 |
| [个人数据导出](docs/PORTABILITY.md) | ZIP/JSON/CSV 格式、本人范围、家庭共享勾选、限额与恢复边界 |
| [开发与多 agent 协作](docs/DEVELOPMENT.md) | 本地环境、公共接缝、文件所有权、测试和交接模板 |
| [隔离恢复演练](docs/RECOVERY-REHEARSAL.md) | 虚构两户、全新 Docker 卷、原文档恢复、登录/照片/隔离验证及自动清理 |
| [部署指导](docs/DEPLOYMENT.md) | 空服务器安装、配置、域名与 HTTPS、现有环境更新、回滚和恢复步骤 |
| [连接后返回发布页](docs/CONNECTION-RETURN.md) | 账户配置与发布页之间的显式返回、身份复核及 OAuth 回跳边界 |
| [运行与排障](docs/OPERATIONS.md) | 状态检查、日志、证书、备份和常见故障 |
| [Microsoft / Google 接入](docs/ACCOUNT-SYNC.md) | 应用注册、OAuth 回调、权限、绑定与维护 |
| [验收记录](docs/VALIDATION.md) | 各批次测试、发布证据、真实接通和未验证范围 |
| [原始产品设计](docs/DESIGN.md) | 已确认家庭需求、视觉、资金规则与大屏方向 |
| [多日视图、采购与财务基线](docs/FEATURES-20260914.md) | 基础功能的金额、数据覆盖与导入口径 |
| [Apple 接入评估](docs/SYNC-DESIGN.md) | 历史方案与未来 Mac / EventKit 桥接方向，未作为当前实时连接器交付 |
