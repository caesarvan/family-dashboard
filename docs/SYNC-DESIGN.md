# 日程与 Apple 提醒事项同步：接入评估

**已被最新方案替代**：用户改为先使用 Microsoft To Do，再增加 Microsoft / Google 统一登录、绑定和日历 / 清单同步。当前实施方案见 ACCOUNT-SYNC.md；本文件仅保留 Apple 后期迁移的技术评估。

以下为早期评估时点的记录，不描述现网状态。2026-09-14 已部署并绑定 Microsoft / Google，采用自动轮询；用户已确认有常在线 Mac，但 Apple 桥接仍暂缓。当前功能和未完成项以 [README](../README.md) 为准。

## 当时讨论的需求

用户要求日程、共同待办自动同步原应用；共同待办使用 Apple 提醒事项。设备是 iPhone + 安卓、手机 / 电脑编辑、两台电视只读。数据源始终保留原记录标识与来源，不能靠标题判断同一条记录。

## 历史待确认项

1. Mac 条件后已确认：有可常在线 Mac，暂不能 SSH 连接；桥接及安装包未完成。
2. 后已确认并实施：Microsoft/Google 任务新建与勾选回写，云日程保持只读；Apple 对应回写留待后续。
3. 双方各自使用的 Apple / Google / Outlook 账号类型和日历范围；Apple 日历客户端可能展示 Google 或 Outlook 账户，不能按客户端名称重复连接同一来源。

## Apple 提醒事项

Apple 提供 EventKit 在苹果设备上读写提醒事项，EKEventStoreChanged 通知表示设备端事件库发生变化，随后需要重新读取。该通知不是发送给 Linux 服务器的云端 webhook。

可评估的主要路径：iCloud 共享清单 → 已授权、常在线 Mac 的 EventKit 桥接程序 → racknerd 同步接口 → 看板。若需回写，则增加有版本校验的命令队列，等待 Mac 确认成功后才显示为已同步。Mac 离线时不能假装回写成功。实际端到端速度还受 iCloud 到 Mac 的同步延迟影响。

若只有 iPhone，需要先验证原生桥接应用或快捷指令的后台触发能力；不能把周期性快捷指令宣称为可靠实时同步。尚未选择或实现这条替代路径。不依赖 iCloud 网页抓取作为已验证方案。

## 日历

Google Calendar 与 Microsoft Graph 的 Outlook event 支持变更通知。拟采用“收到变更通知后增量拉取 + 定期校验”的后台服务。Webhook 需要续订、验证来源并处理重复、乱序、丢失通知；具体 OAuth 回调域名限制和组织授权策略需在选择账户后确认。

Apple 日历若已在桥接 Mac 上配置，可评估同一 EventKit 程序读取；若日历实际来自 Google / Outlook，优先直接连接对应服务。Apple 日历与 Apple 提醒事项不能未经验证就共用同一 CalDAV 接入假设。

## 统一数据与验收原则

- 只同步明确选中的共同提醒事项清单和日历，不读取全部私密提醒事项。
- 记录 provider、account、calendar/list、remote ID、远端版本、最近同步时间、删除状态。
- 原应用的新增、修改、完成、撤销完成、删除均要同步；重复日程与时区需要真实账户验证。
- 首次完整同步成功后才进入健康状态；抓取失败或权限撤销不能当作全部记录被删除。
- 身份凭证仅存服务器或桥接设备受保护配置，不交给电视浏览器，不写入日志。
- 手机和电视只消费同一份已同步的数据，保留个人财务隔离。
- 原应用 → 看板、看板 → 原应用（如果用户选择回写）分别测量延迟，报告实际值及离线行为。

## 官方资料

- Apple EventKit 变更通知：https://developer.apple.com/documentation/EventKit/updating-with-notifications
- Apple 提醒事项升级与设备兼容：https://support.apple.com/en-ca/102457
- Google Calendar 推送通知：https://developers.google.com/workspace/calendar/api/guides/push
- Microsoft Graph 变更通知：https://learn.microsoft.com/en-us/graph/api/resources/change-notifications-api-overview?view=graph-rest-1.0

资料核查日期：2026-09-14。以上为接入设计，不能替代运行验证。
