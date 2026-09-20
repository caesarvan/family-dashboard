# 日程时间重叠：使用与发布验收

<a id="calendar-conflicts-release"></a>

## 当前状态

2026-09-20 08:47:27（北京时间）激活成功，08:49:19 独立生产只读审计通过。源码经 [PR #14](https://github.com/caesarvan/family-dashboard/pull/14) 合入 main `6fdf36e89e52354b70b2b1b47571148c8c02bdb5`，与实际安装 source 同树。后续文档提交不改变运行包身份。

本批更新 Expo 日程界面和派生计算，没有新业务接口、云端写入或数据库迁移。已消费的部署计划不得重放。

## 怎样使用

1. 在首页选择「今日／本周／前后 3 天」及成员侧重。有时间重叠时，点击「N 组时间重叠 · 查看」进入日程。
2. 日程页的重叠区域按当前整段范围计算。展开一组即可查看双方完整标题、地点和实际重叠时段；每次显示三组，可继续展开。
3. 本地安排点击「调整安排」，编辑原记录并保存。刷新后重新计算；重叠消除后自动移除，当前范围和所选日期保留。旅行安排使用已有旅行调整入口。

同步日程显示只读提示，应在原应用调整；此处不会复制日程或写入云端。修改时使用原 ID 和 revision，版本冲突保留草稿；结果不明时先核对，不自动再创建一份。

「组数」是两两日程的时间交叠数量，不表示工作量、人数或必须调整的冲突。全天日程、首尾相接、无效时长不计入；跨日同一对只计一组。忙碌时长仍使用已有区间并集计算。成员侧重是展示筛选，不是可见性权限。

## 实际验证与边界

| 范围 | 已取得的证据 |
| --- | --- |
| 核心计算 | 12 项新用例和 1 项原日历用例通过，覆盖跨日、成员范围、无效值、稳定键及原对象引用 |
| 正式前端构建 | 独立 fresh npm 安装、两组 TypeScript、34 项 Node 通过；138 个前端输入、9 个构建辅助输入与 23 个导出文件均绑定实际字节 |
| 真实临时浏览器 | 三条流程分段通过：R1 的范围／只读及草稿／身份两项，R2 仅补验修改原日程消除冲突；共 8 张有效截图，覆盖 390 与 1280 宽度 |
| 浏览器失败记录 | R1 第一项实际原 ID 更新成功，但截图检查误报合法横向滚动；该项未算完整通过。修正检查工具后仅重验第一项，保留原失败与关闭警告 |
| 发布适配 | 32 个独立用例分轮通过：首轮 30 项通过、两条测试假设修正后 2 项窄重验。包含真实临时两户三库、非空提醒／回执／settings 的备份与启动保全 |
| 实际 Linux 镜像 | 3/3 通过、零跳过：鉴权与 CSRF、重复日历导入去重、单日日程结束边界；核对实际镜像 129 个运行文件。未重复提醒后端的 82 项测试 |

生产只读审计核对 1043 个安装文件与三个应用服务各 129 个运行文件；4 个服务运行、零重启、app healthy。75 个 TLS 静态资源和三个页面一致，29 项固定匿名 GET 及另 3 项助理 GET 均返回 401。

这些分段结果不能相加为一次完整测试，也不代表真实云账户写入、实体电视或 A–D 本人完整验收。A–D 仍为 0/4；电视暂无法验证。本地日程私密可见性是下一批独立候选，不包含在本次运行包中。

## 固定发布身份

| 项目 | 值 |
| --- | --- |
| source | `ffb0b3cf46b6a4cf35b005d84879763b825cd822` |
| tree | `7bf8c1ea54018713ab6a67e676af3ebd7a1911f3` |
| package | `dfbcd03256962168ae19a27f993902cf91c0d64f2d1ff5c5f43962038c219491` |
| manifest | `f359222a790ed60b494bfcb0e555716a800b96b1b54f497f12c57c9d48b5fc52` |
| archive | `88cb37cf4be6bb12ace7f0325bc1e08b7f663c09a3f2ff0f9e5cdfa9198ccc20` |
| image | `sha256:d11e94b576cc1b9497c85d1c43782b6b62fe5df4bd20d32f3337524c96edd73d` |
| plan（已消费） | `f7c13561572b1f264e671e8ec47de41f0fd4a2155a2e6c590deb49edec85a5c3` |
| stage | `81739550a3b55e3432420dd3ccacad4b5240f83fb8150901bb2598eee168b7f0` |
| activation | `0224c197b8ca7d4233591c39f2348765043053b71e588b2cd00b0833d2301b6f` |
| 实际 Linux build | `c23894f5d6b974f4deb6f75285bebadb35e1ef3019985e51485372db4f03c636` |
| 实际 Linux validation | `8a51722cb3912e615c0fa93318d39b5678021967d079b445a91e2d3ba2411311` |
| 独立生产只读审计 | `bf4e31d64f9ea6332ac17f4239fed468a5019cbcfb8c92fd3ba4a6b70629b46b` |

父版为[本人站内提醒](TASK-REMINDERS-ACCEPTANCE.md#task-reminders-release)，父镜像 `sha256:a99d11dec43be931f36496368e0565f9dfc87492fcd391dfbff92d2a61470f0e`，独立生产审计 `313e15072070f499f286c817d20227378309ec1a6129feb8e985d597f88e30f8`。全部 106 个非 Expo 运行文件与父版相同，Compose、Nginx、依赖和环境保持原配置；1043 个安装文件、129 个运行文件、35 个发布工具均由正式包绑定。

生产一户两库保持家庭库 71→71、平台注册库 9→9。停写后备份完整数据库组，先仅启动新 app，停止后严格比较全部表、settings、序列及提醒状态／回执，再恢复全部服务。该窗口前后逻辑摘要均为 `3fe6226aa462ab90fbbe8a95163c1da4f40c3850473f55b855456f96cb1a1c98`，不限制恢复服务后的正常同步和用户写入。两份停机备份字节已核对，备份定时器 active；未在生产执行恢复。匿名 GET 拒绝不代替 POST 授权或本人流程验收。

## 交接与原件

仓库内的[计算合同](CALENDAR-CONFLICTS.md)、[界面说明](EXPO-CALENDAR-CONFLICTS.md)、[浏览器工具](EXPO-CALENDAR-CONFLICTS-BROWSER.md)和[发布适配](EXPO-CALENDAR-CONFLICTS-RELEASE.md)说明可复用接缝。后续必须基于当前实际安装身份创建新的候选和计划。

操作机证据根目录为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`：正式包与唯一阶段原件在 `calendar-conflicts-release-20260920-r1/`；构建、组合／包／Linux／计划独审及生产审计在 `worktrees/calendar-conflicts-build-r1/test-results/`；真实浏览器 R1/R2 原件在 `worktrees/calendar-conflicts-browser/test-results/`。原件留在操作机，不把截图、日志、环境或数据库提交到 Git。

服务器已消费候选为 `/opt/family-dashboard-candidates/calendar-conflicts-71-20260920-r1`，保留的发布目录为 `/opt/family-dashboard-releases/expo-calendar-conflicts-71-20260920T004545260364Z`。
