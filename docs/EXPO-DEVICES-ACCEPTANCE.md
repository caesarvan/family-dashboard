# Expo 电视与播放：验收记录

已于 2026-09-17 13:00:01（北京时间）激活，13:00:47 正常 TLS 读回通过。设备和播放接口保持，55 张业务表无迁移；此前 [11:09 旅行改期版本](JOURNEY-RESCHEDULE-ACCEPTANCE.md#journey-reschedule-release) 作为本次安装基线与历史证据保留。

## 使用与权限

从「更多 → 电视与播放」或相册进入，在电视浏览器打开 `/tv` 后用手机批准配对。每块屏幕独立设置侧重成员、日程范围、卡片布局和主题；照片必须由本人明确共享并许可指定电视，才能从手机开始播放、暂停、翻页或返回看板。设置和播放各用独立版本，结果不明先只读核对，不自动重发。完整步骤见 [使用与接口](EXPO-DEVICES.md)。

设备管理在本家庭实际成员会话内执行，批准配对码至多一次。等待写锁期间撤权、提交前到期或审计失败均不能留下半次设备修改；电视只读、个人财务权限和逐设备照片许可保持。后端改动限定于 `app.py` 设备／配对段，经典界面兼容保留。

## 本地实际证据

首轮固定组合 source `d82b4355dc35229637b7fe4e3ade70fcb52611c2`，tree `764ceee7144d2a848cf6087ca06fe8d200029989`。构建 `expo-devices-build-20260917-r1` 的 158 项输入／23 个导出与受验源码绑定；build evidence SHA256 `d0d6e1c631cdf7e0bf9bf37b16793d51a13e71446c0942bea2223678b180643c`。

| 验证 | 已观察结果与边界 |
| --- | --- |
| 后端设备与关联回归 | 五模块实际 196 通过：新设备会话 30、电视显示 44、基础 app 8、播放 53、成员会话 61；其后仅换行和文档调整，最终字节再跑新专项 30 通过。使用临时真实 SQLite、双连接撤权／竞争和审计异常回滚；未操作生产 |
| 前端与工具 | 14 项 Node、20 项发布适配器分别通过。独立真实旧包／九算子检查通过，38 项冻结缺项／旧基线拒绝、7 个未绑定入口拒绝；不是生产发布 |
| 设备浏览器 r1 | 真实临时 Flask／SQLite／Edge 16 项功能检查通过、14 张 PNG；source／bundle 前后不变，0 pageErrors／externalRequests／productionWrites。合成媒体使用真实净化、加密、确认与许可流程，不是真实 Google 来源 |
| r1 视觉阻断 | 验收 agent 逐张查看全部 14 图；Root 查看其中 6 张（1440 设备列表、390 播放、320 布局、1920 电视布局与照片、320 冲突）。TV `light` 旅行卡深色文字落在旧 `.travel-card:after` 暗渐变上，日期另有浅色硬编码；其余 13 图当前可见区域通过，不代表完整长表单视觉覆盖。修复仅针对 `body.tv.tv-display[data-tv-theme=light]` 两条旅行卡规则，不更换整个电视主题。原 JSON 的 `passed:true` 只代表自动功能断言，该阻断在正式 r2 复验后关闭，r1 原件保留 |
| 设备浏览器 r2 | 修复后同 head／同构建正式验收 16／16 通过，14 张 PNG 由验收 agent 逐张查看；Root 查看电视布局、1440 设备列表和 390 播放共三图。0 pageErrors／externalRequests／productionWrites，源码／bundle 前后相同、临时 fixture 已清理。只证明当前可见区域，不冒称完整长表单或实体电视验收 |
| 既有旅行改期回归 | 同 `d82b435`／同构建实际 16 项检查、18 张截图通过；UI agent 人工查看其中 2 张。仅 FakeRemote 验证稳定事件创建／更新，不是真实云改期；0 生产写入 |
| 最终服务端选择 | 23 模块实际收集 759 个唯一 node ID，exit 0；533 个 tracked 文件前后散列一致。首轮 Linux 实际 743 通过／15 错误／1 个精确 Windows 跳过；R2 保留全部 759 项，实际 758 通过／唯一精确 Windows 跳过、零失败／错误／删选 |

修复后的组合为 `e6671e5d41d2348277bf89bc676e9d38cb1dbeef`／tree `a1b3bd81d492f235b0ca0d63ea60e2557aba06df`，仅比 r1 多 `static/tv-display.css` 三行／两条规则。r2 构建 evidence SHA256 `78cc93b0d6b4da32ef2432f104c5e5648105c3f4e72ff33b2f7cd7b9d4da35ae`；23 个导出，JS 与 r1 同字节，但证据的源码身份不同，不能混用报告。正式设备浏览器 r2 已通过，源码和 bundle 在运行前后保持。最终 source 候选 `e6671e5` 经非作者审查后合入正式 integration `d0f660a8ead9f39126a35157f170e7fb6a1ad8b4`、main `5f41b61980481aba7d88e58b21b0806e59891fe2`，均为上述 `a1b3bd81` 文件树；Git 合入仍不等于部署。

独立 CSS probe 实际验证三种电视主题（light／forest／ocean）各自空状态和已有旅行状态，共 6 项／6 图；UI agent 全部查看，Root 查看两张 light 图，通过当前可见区域检查。probe 使用修复分支 `4f9fa7e` 的静态资产与旧 r1 构建，明确只允许该 CSS 差异，不是同 head 的最终组合验收。此前一次预检被散列守卫拒绝，未据此放宽其他输入。原件 `expo-tv-light-probe-20260917/20260917T035354361141Z/result.json`，SHA256 `5b813c28a9af5ae6bc2516271ee431042aa7016d55ead6364b79d0f784e62065`；无外网或生产写入。原电视旅行卡未展示预算文本，不声称此次检查覆盖预算呈现。Python 依赖未改变，原收集与既有旅行回归可按精确字节沿用。

以上结果分次取得，有重叠，不相加成一次全套。私人原件保留在独立 worktree 的 ignored `test-results/` 与访问目录；不会提交截图、数据库、配对凭据或个人财务。

关键原件索引：

- 设备 r2：`expo-tv-devices-tests/test-results/expo-devices-20260917T035552058158Z/result.json`，SHA256 `cb7829179f476efd6eea8343e8150b30502bb7f153d24d36fd396148818a74d9`。
- 设备 r1：`expo-tv-devices-tests/test-results/expo-devices-20260917T034709890144Z/result.json`，SHA256 `97b8a40b6a57168d01be7c1e6f21e806a789c856bac1b8dab2d7daf8b5d38f67`。
- 旅行改期回归：`expo-tv-devices-integration/test-results/expo-journey-reschedule-20260917T034726640736Z/result.json`，SHA256 `611e8e688efe300540095bbc0ea357623e98b6eabcc4b89cfa6868f7b9d215e8`。
- 后端 196 项：`expo-tv-devices-api/test-results/device-sessions-combined-r2.xml`，SHA256 `06db47a305bc502f57b0186bf69c415329de9ed587dae59d88028389ba810895`；最终字节 30 项：`device-sessions-final.xml`，SHA256 `464fba1dae98b8d48e2de1e5b6ba7c3180d560fad380a46a94a5da9ba9647d9a`。
- 收集：`expo-devices-validation-20260917-r1/collection.json`，SHA256 `e9efe3958724b8cdbb235809516a44e11ce4a38e4c61a11042035a007f763c06`；记录完整 node ID 和源码散列，不代表执行成功。

<a id="expo-devices-release"></a>
## 发布状态

已经实际部署。本地最终源码、正式 integration／main、修复后构建及 r2 浏览器已核对。实际生成的九份算子经独立审查后完成包绑定，11 份候选文件上传并逐项读回 SHA 相同；服务器镜像构建已通过。首轮 Linux 759 项实际 743 通过、15 个 setup 错误、1 个精确 Windows 跳过，exit 1；`test_tv_display` 最后 15 项因 SQLite 临时空间耗尽而未能执行。开始和结束的 114 个运行文件核对均通过，37 个真实模块来自 `/app`。首轮未进入 stage／激活；R2 Linux、READY、实际激活及正常 TLS 读回随后分别通过。发布工具只接受新的冻结身份，不能重放此前候选；流程与数据保全约束见 [发布适配](EXPO-DEVICES-RELEASE.md)。

本次实际安装包与构建身份（R1 审查／绑定另作失败历史保留）：

| 项目 | 实际记录 |
| --- | --- |
| 包文件集合 | manifest 555 条，包含 23 个 Expo 导出；运行镜像核对 114 个文件 |
| archive SHA256 | `a8d823f475079ac0afe9a3a5c42496ffe98c562ece580ab9ef31002ae26f99ba` |
| manifest SHA256 | `c51883945ec77ec0c6eb4fa1377cad4d60a4600d2daf36c1ee808b1b9815c3d8` |
| 新镜像 | `sha256:9a4e032f5817de67a995cd2a849f7c02c8c90ca8f87ffeb3644764b9f0fd2f62` |
| R1 九算子审查记录 SHA256 | `8aa3b43e77bf416fc52602a963cb1fba485e38bdcd6d1ba47ad3f3905a40d6d7` |
| R1 七算子执行绑定 SHA256 | `635e037b51cbcdc6d2cd1511e809be6c27f11127b1cb62a1d04256492f2bd49b` |

原件位于私有 `expo-devices-tools-20260917-r1`；`build-command.stdout` 已核对上述身份，SHA256 `da01f893d5f4217fe0135a18a56ee0db28237de22b0427b08cf8ad331cec68bf`。构建没有改动生产运行版本。

首轮验证保留于同目录 `validate-command.stdout`，SHA256 `01fde7ff83ebf77c35ef56e0e670de599824d40c406f26e4c7197933c3c1babb`；唯一平台跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`（`Windows junction semantics`），没有隐藏失败或删选测试。

R2 已在全新 `expo-devices-tools-20260917-r2` 生成，资源由内存 768 MiB／tmpfs 512 MiB 调整为 896／640 MiB；六份原包文件字节不变，原测试选择和业务／前端源码不变。七算子只改候选路径及两处资源值，其余五份字节相同；binder 保留 R1 原打包器来源，已通过独立审查并建立新绑定，旧 binding 未复制。`resource-adjustment.json` SHA256 `ea9a829d5a1cb614e9a8b41ec6c4deb65f768673ce80041c4a919b7541c4a8db` 记录精确差异和原失败引用。R2 已完成 11 文件上传及逐项散列读回，实际构建仍为上述同一镜像；Linux 已实际 758 项通过、唯一精确 Windows 跳过，零失败／错误／删选，运行文件前后核对均通过，验证报告为 `productionOperations:false`；生产切换只在后续独立激活阶段执行。R2 `operator-review.json` SHA256 `b2bf1e0b86ec47fdb34a0e3ac13ba5ea3e810717eb1906804b0a0c160ae412b7`，新 binding `009ebe7dcccc57e4f3a982cc4b726972283370636ccc26b5f40920f7b07bd654`；`upload-evidence.json` SHA256 `1ce7a8bff325d52368a3e070d5bbdd0a42bf9cb53c753f16efed63aa475e6ec8`、`build-command.stdout` SHA256 `dcdfbfca2a9ee554cc46cf514aa7de78de719d463b5fbdc3d15cebc984833f18`。

R2 验证原件 `validate-command.stdout` SHA256 `54cc52c1a74b6811ed7dbbc6764646d1c2421b674cf37c64fe986471d443bc16`；报告所绑定的 `validation.log`／`results.xml`／`runtime.json` SHA256 分别为 `44454be54ffc88aadca8403069ad2b73754ea4cb1a444753de876ddf3b16fa66`、`f21798584323aa02cb4cdce858bdf857e1b146a9140b99d3b823deb38cf5d677`、`7365d0f8ffda2d00b9692b0fdb6bbdc4465c86e951cec36917166c5a9dd06ce9`。

## 实际激活与发布后读回

安装 main `5f41b61980481aba7d88e58b21b0806e59891fe2`／source 与 integration `d0f660a8ead9f39126a35157f170e7fb6a1ad8b4`，同树 `a1b3bd81d492f235b0ca0d63ea60e2557aba06df`；发布目录 `/opt/family-dashboard-releases/expo-devices-55-20260917T045903038259Z`。激活于 UTC `2026-09-17T05:00:01.281741+00:00` 完成，正常 TLS 读回于 `2026-09-17T05:00:47.035735+00:00` 完成，对应北京时间 13:00:01／13:00:47。后续文档提交不改变这些已安装身份。

停写后核对完整 1 户／2 库备份，户内 55 张业务表及平台注册库的原行、schema、序列在新 app 启动后保持；`before.json` 与 `after-app.json` 散列相同，无 schema 变更。生产投资操作回执为 0 行，不能据此声称实际非空回执也曾经过本次生产保全，合成非空覆盖另见工具验证。app／sync／media 使用新镜像，web 保留旧镜像；四服务运行、零重启，app 健康，环境保持。

正常 TLS 读回核对 555 个源文件／114 个运行文件／75 个静态资源，24 个生成内部文件及 1 个退役资源拒绝访问，25 个匿名 API 返回 401；Expo 入口和经典入口均通过。发布后新的 backup invocation 成功、timer active；闭合备份组为 1 户／2 库、户内 55 表及平台注册映射通过。它是逐库在线备份，不是跨库原子事务，也未再次取得 live 全组快照（`liveGroupSnapshotRechecked:false`）。本人真实财务、真实云服务和实体电视本轮均未验收。

R2 `activate-command.stdout` SHA256 `234c4dbc6a206a10051d09b579491860f238295219954d6ee53f71e7b20f6c99`，`post_readback-command.stdout` SHA256 `e84cbb0f1b8fc7e48658842c444721d6b570f1179c1acb2a07ad19f2a63f134b`。服务器 13 份原始报告／保全证明已逐份与远端 SHA 核对，保存在私有 `expo-devices-published-audit-20260917T050147540925Z`；`readback.json` SHA256 `781ef6f89705a1e8b7b7fd5ab6609c96af6ff56a98cce69763f220ea33794f3d`。其中原始 `activation.json` SHA256 `b800a01ebaec3b896bcbaeba65fdf486c587da912935d48a0d97a575c17de46a`，`post-readback.json` SHA256 `66a9da93a25b88869b640322c8375da62fb3b05340b08d1df0527d86a2d64444`；不得把包装脚本 stdout 的重新格式化字节当作原报告散列。非作者已完成跨阶段、原运行文件与五份保全证明的完整核对，结论 PASS；同目录 `audit.json` SHA256 `aefcf0d0fb80b8c614def97aaa2f66aab588d6c39e146585f13b76e441cc56bc`，未下载数据库或重放发布算子。

## 未验收范围

实体 50／75 英寸电视、实际遥控器、休眠唤醒和长期常亮未验；没有因此要求本人立即重复授权。此前本人 Google Photos 五选五保存成功事实保留，本轮合成媒体不能替代真实来源到实体屏幕的整条验收。视频、精选完整回顾、iCloud／NAS 仍未完成，完整产品场景 C 不因本轮功能通过而完成。离线屏幕可能保留旧画面，撤销不能远程收回已交付的图像字节。
