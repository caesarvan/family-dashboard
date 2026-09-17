# Expo 电视展示：本轮验收与发布记录

<a id="expo-tv-release"></a>
## 当前阶段与固定身份

**2026-09-17 14:19:19（北京时间）实际激活，14:19:53 正常 TLS 读回通过。** 本轮把电视展示本身迁入 Expo，不新增业务 API、依赖、数据库表或媒体来源。下列运行包已安装；后续纯文档提交不改变运行身份。此前 13:00 的 [设备管理与手机控制](EXPO-DEVICES-ACCEPTANCE.md) 保留为历史。

| 对象 | 已核对身份 |
| --- | --- |
| 发布 main | `2e314bf71491b96eade39e8d13525861ace4663a` |
| source／正式 integration | `54cef032658ed9ddbddf0767336edf699906d5bb` |
| 同一源码树 | `595baf255c57ad3c217afce0c0968861570754ed` |
| R2 浏览器与构建源码 | `3adaf485ba1ce0d47c5445c0659f5df3e1c5e8d9`，tree `10760ad133c23349315a0ea33ad32e32e9e59098` |
| R2 构建证据 SHA-256 | `c376d1f9094e5aa306746b88c8e47d0d5b941f5ef74f66f4e21ec8bd7ef1e240` |
| 冻结记录 SHA-256 | `bbd002fc5d4d63de77afec6cd940a9d6d79b826174deffe2921e1ce8038d0f0e` |
| 实际源码包 SHA-256 | `857e571d816ec05f1a3df9575f7982fb8756e8b8a2faba7c47c82b022efc127a` |
| 实际 manifest SHA-256 | `ca1e82499be5548e0cd59aa0d83be4296a5fde3c123274f3062190ff8bf3aa30` |
| app／sync／media 镜像 | `sha256:15f5e99ade61c694583137c88033ef6082bafc26ab06c3aa5921342bdfc62191` |
| 发布保全目录 | `/opt/family-dashboard-releases/expo-tv-55-20260917T061825405301Z` |

发布树在受验组合上只增加已审查文档；166 个构建输入与 23 个导出均核对一致。实际包含 548 个源码文件与 23 个导出，共 571 条 manifest；对已安装包完整差异为 14 个改变、17 个新增和 1 个删除。九个生成工具由非作者逐字节审查，7 个服务器算子另按实际 SHA 绑定；随后服务器隔离验证、激活及独立读回均已实际通过，分别以原件核对。私有原件在 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/expo-tv-tools-20260917-r1/`，不提交 Git，也不可重放。

## 用户入口与验证范围

电视打开 `/tv`；有效导出存在时精确跳转 `/app/tv`，`/tv?classic=1` 及没有导出的情况保留经典入口。未配对电视生成最长 10 分钟的 8 位码，手机从「更多 → 电视与播放」批准。两台电视分别保存主题、密度、卡片布局与日程范围。根布局排除成员 provider，只显示当前电视许可的共享数据；照片另取最长 15 秒的授权，暂停也续期，隐藏、离线、过期或撤权时清除。

使用与 API 边界见 [Expo 电视展示](EXPO-TV.md)，固定发布适配器见 [发布说明](EXPO-TV-RELEASE.md)。

| 实际验证 | 结果与边界 |
| --- | --- |
| TypeScript 与 Metro 导出 | 组合完整类型检查通过；R1、R2 实际构建通过，R2 为正式受验导出 |
| 播放器模型 | 8 项 Node 实际通过；不代替浏览器或实体电视 |
| 发布适配器 | 20 项实际通过；固定九原件生成、31 项非法 freeze 拒绝和 7 个未绑定入口拒绝实际通过 |
| R2 临时浏览器 | 真实 Flask／SQLite／Edge，13／13 项通过，9 张 PNG；非作者验收逐张视查 9／9，集成人另看白色 1920／4K 看板及 4K 照片共 3 张 |
| 服务器测试选择与执行 | 11 个模块、322 个唯一 node ID 先实际收集，再在 Linux 实际执行：321 通过、1 个精确 Windows 专用跳过、零失败／错误、零 deselect；114 个运行文件和 37 个加载模块在执行前后保持 |
| 服务器验证／发布 | build／validate／READY／activate／post readback 全部实际通过；571 包文件、114 运行文件和 75 项 HTTPS 静态资源核对一致，旧包保留，环境配置保持 |

R2 覆盖：两台合成电视设备的真实配对 Cookie 与独立设置、共享金额和私人接口隔离、今日／本周／前后 3 天全成员分页、长文字末尾可达、授权 JPEG 与手机播放控制、暂停续期、真实设备到期、离线／隐藏清屏、迟到照片拒绝、撤销电视许可、跨家庭迟到状态及设备撤销。548 个源码文件与 23 个导出前后保持，页面错误、外站请求和生产写入均为 0，临时 fixture 已清除。

浏览器原件在独立 `expo-tv-view-tests/test-results/expo-tv-20260917T054907984077Z/`：`result.json` SHA-256 为 `78f35210335e2a85c3b8e39d807643886e89e2b7af73af94d49c2f85784357df`，同目录 `visual-review.json` 为 `c83dfa10d564fb57fbaa82ae643a5887e133d77f026e8df49ef663e14b2196a3`。构建原件为私有 `expo-tv-build-20260917-r2/build-evidence.json`。收集原件 `expo-tv-validation-20260917-r1/collection.json` SHA-256 为 `d3a6f02f07bd5325c8f6102e57265abe11e50b1dee6fce509f13e8aa2a82dfd7`；11 个测试文件已与最终发布树逐字节核对。

## 实际发布与独立取证

隔离 Linux 唯一跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`，原因精确为 `Windows junction semantics`。实际 JUnit SHA-256 为 `268184790b16fb51d0e24691d06514b3807793018e1aded12ac31bab9ce0cefe`；不能把此前 collect-only 记录当作执行证据，也不与 Node／浏览器重复相加。

实际 1 户两库停写备份通过；原 55 张业务表、`sqlite_sequence` 与平台两张注册表的全部行／schema／序列在新 app 启动后保持，前后摘要原件字节相同，无 schema 迁移。生产持仓回执记录数为 0，非空回执保持由既有合成专项覆盖，不能称生产实际验证了非空回执。

正常 TLS 核对 Expo 根／子路由、`/tv` 精确跳转 `/app/tv` 与经典回退，75 项静态资源字节匹配；24 个生成私有资产和 1 个退役 JS 拒绝，25 个不同匿名 API 均 401。四服务运行、零重启，app healthy；web 原镜像和环境配置保持。发布后新一次备份 invocation 成功、timer active，闭合 1 户两库及 55 表／注册库；它是每库 online backup，不是跨库全局原子事务，也不是再次 live 全组快照（`liveGroupSnapshotRechecked=false`）。

独立审查从服务器只读取回 13 份报告／验证／保全原件，逐项核对远端与本地 SHA，并额外重新读取当前 571 个安装文件摘要、环境摘要及权限和四服务身份／健康；未执行发布算子、未下载数据库。私有证据目录为 `expo-tv-published-audit-20260917T062037325328Z`，其 `readback.json` SHA-256 为 `d5f6b437a7eedea044e5829f92b1fba82ce4387e0de66867f28d65cf748ed8e2`，`audit.json` 为 `c93d1203cfbea84add9a780275477077a0a27ad83ccfa6dda7d25af11121c6f1`，独立结论 PASS。activation 原件为 `65ac009aabfcc1005ffb287384e1c59f4ce13fb36d76159f693e102eeea95bcb`，post readback 为 `e523bdf7904633e61dbc319dbd7c30ebbf0bc85b3011c0f9b4873f8a5ad51ceb`。这些证据不代替已登录真人体验或实体电视验收。

## 保留的失败与未验收事项

R1 完整类型检查与构建通过，但浏览器只完成 13 项中的第 1 项就中止：卡片选择器把 Paper 内部节点也计入，导致顺序断言失败。只修测试选择器后用 R2 重跑；不把 R1 写成整套通过，也不把这次测试断言误判写成产品故障。R1 原件 `expo-tv-20260917T054020942688Z/result.json` SHA-256 为 `068e7c35711453327b4933cd04c688fece749cf33abb4572035256791fc524e1`，仍保留。

照片测试使用实际净化、加密和授权流程的合成 JPEG，未重新调用真实 Google。隐藏状态使用明确模拟的 `visibilitychange`；展示时钟加速不改变单调授权截止。截图仅证明当时视口：320 配对页底部未完整入图，长文本通过分段到达末尾，纯色照片不代表真实照片质量。

50／75 英寸实体电视、遥控器、休眠／常亮与长期运行、真实云照片播放均未验收。历史本人 Google Photos 5／5 预览并保存成功保留，不能替代本轮播放或完整场景 C；精选回顾、视频、iCloud／NAS、通用角色及多家庭成员关系仍在 [产品计划](PRODUCT-PLAN.md)。
