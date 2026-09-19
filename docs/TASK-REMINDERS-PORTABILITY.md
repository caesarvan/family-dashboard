# 提醒历史的个人导出

本批基于提醒 API 候选 `eb565b85982f47c44d5b7b86bf13ee4da7499f91`，只适配个人下载，不表示前端、迁移或部署已经完成。原 [数据导出](PORTABILITY.md) 和 [提醒合同](TASK-REMINDERS.md) 保持；没有新增导入、恢复、分享或提醒重放接口。

## 下载内容与兼容性

原 `POST /api/portability/export` 仍返回五文件 ZIP，`data.json` 和 manifest 的 `schemaVersion` 均为 1。采用既有增量字段方式，在 `personal.taskReminders` 增加两个数组；无记录时为空。`includeShared` 只沿用原共同记录选择，永远不增加他人的提醒状态或操作历史，也不会把本人的提醒移到 `shared`。

| 数组 | 白名单字段 |
| --- | --- |
| `states` | `taskId`、`due`、`readAt`、`snoozedUntil`、`revision`、`createdAt`、`updatedAt` |
| `operations` | `taskId`、`occurrence`、`action`、`revision`、`readAt`、`snoozedUntil`、`committedAt` |

状态直接读取当前成员自己的持久记录，按 taskId、due 排序；不调用 worker、不物化尚未保存的提醒、不按当前任务内容补全。操作只从本人成员范围内的回执挑选上表字段并验证基本类型，按保存时间及原请求编号排序，但不导出该请求编号。`null` 保留为 `null`，`revision` 不接受布尔值或嵌套对象。

不导出 `owner`、内部 `active`、`requestId`、`intent_digest`、原始 `result`、标题快照、请求载荷、令牌、会话或凭证。原任务已删除、改期、改负责人后，本人按提醒合同保留的状态和操作历史仍可下载；这不授予重新读取原任务内容的权限。

`coverage.taskReminders` 为 `owner_state_and_minimal_operation_history_without_task_content`。README.txt 解释这是私人历史快照，不表示原任务仍适用或暂缓时间仍在未来。暂缓到期不会清除持久时间值，导出的记录不额外生成 `unread/read/snoozed` 实时派生状态。

`GET /api/portability/summary` 在 `personal` 增加 `taskReminderStates`、`taskReminderOperations` 两个本人计数，包含留存历史；`shared` 不增加提醒计数。计数只反映数据库已保存记录，可能少于提醒列表中即时投影的当前可提醒事项。

## 权限与并发

两接口使用既有 `ImportSession` 捕获当前家庭、成员、会话 ID、凭证摘要和认证版本。摘要在一致读取快照内检查身份，返回前再以新快照检查；ZIP 在读快照与压缩完成后的最终事务中检查同一完整身份。即使 owner／auth_version 未变，原会话 ID 改变仍拒绝返回旧内容。

身份失效返回原 401；电视拒绝 403；写入式导出入口仍要求原 CSRF／Origin。客户端不能通过 `owner` 参数选择他人。其他家庭使用各自数据库和成员会话。原路线／地点共享变化检查、照片授权检查、库存最终检查、64 MB 限额、并发槽与私有 no-store 响应均保留。

“只读提醒数据”指两张提醒表及原任务在导出前后不变，不意味着整个已有导出流程零写入。原有导出限流与 `personal_data_export` 审计继续存在；身份或最终检查失败不产生成功下载审计，也不返回部分 ZIP。没有提醒回填、清理、迁移或执行历史操作。

旧家庭库若尚无两张提醒表，计数为零、数组为空，不在导出时创建表。字段扩展不改变数据库结构，也不替代后续 69→71／平台 9 表的正式发布迁移。

## 数据使用边界

此 ZIP 始终是个人下载包，可能包含个人财务与提醒习惯；勾选共同记录并不会让整包成为可公开分享的数据。操作历史省略了重放所需的 requestId，也没有提供导入或覆盖 SQLite 的能力。灾难恢复仍使用经验证的整库备份流程。

定向测试使用真实临时 Flask、SQLite、成员 Cookie 和 ZIP：覆盖两成员独立历史、includeShared 不扩大权限、已删除任务历史、显式字段与类型白名单、未物化记录不回填、旧无表兼容、家庭／电视边界，以及摘要投影后和 ZIP 压缩后撤权／会话 ID 更换时丢弃响应。网络在新测试中禁止；实际数量、原件和固定提交由作者报告记录。未运行真实云、浏览器或生产发布。
