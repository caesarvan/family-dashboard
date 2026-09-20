# 本人确认照片日期

本人照片日期实现与接口契约。基线 `1d91a4744db5d8d9d95c07724a2cf4192c12cb50`，本批固定应用源码 `5fae5c5`；实际发布状态、分轮验证和操作入口见[集中验收](MEDIA-CONFIRMED-DATE-ACCEPTANCE.md#media-date-release)。保持75户内表与9平台表，不做DDL，保留设备上传默认来源日期未知。

## 用户流程与权限

本人已保存的设备静态照片详情增加「照片日期（本人确认）」：输入日期 → 保存；已有日期可明确清除。空值不默认今天。仅使用该日期整理本人照片，不改变原始来源时间、旅行关联、家庭共享或电视授权。继续使用现有「查看旅行建议 → 确认关联」流程；那年今日会标明依据本人确认日期。

仅当前有效成员拥有的 `ready`、`confirmed_at` 非空、静态 `photo`、真实封存 `local-upload/v1` 来源可编辑。沿 `_media_authority` 的成员／uploadSha256／source_key 绑定，不能仅凭account_id为NULL或JSON中的source判定。Google、视频、未确认、已删除、其他成员、其他家庭与电视不可写该字段。

日期存于原 `metadata_cipher.userConfirmedDate`，值为严格有效的 `YYYY-MM-DD`（0001～9999，含闰年校验）或null；缺失按null。日期仅有日精度，没有指定时区，不转换为午夜、UTC、来源拍摄时刻，不从文件修改时间或EXIF推测。

Owner Photo DTO增加 `userConfirmedDate: string|null`；不符合上述照片条件时返回null，非本人及TV完全不返回字段。只有个人媒体导出白名单增加日期，共享导出不包含。读取无副作用，不重写旧密文。

## 独立保存日期

`PATCH /api/media/items/<id>`，出现日期字段时只接受：

```json
{"revision": 7, "userConfirmedDate": "2025-09-21"}
```

明确清除使用null。不能与caption、visibility、journeyId或建议确认字段混合。沿原同源JSON、Origin／CSRF与事务内成员核验；日期写使用现有建议事务的首尾身份核验。当前revision必须一致，实际保存重新封存全部元数据、revision+1、updated_at和现有audit/quota。响应仍为`{item: Photo}`，不引入新回执表或自动重试。

日期分支只改元数据和版本／更新时间；不改visibility、journey_id、media_tv_grants、图片字节、展示副本摘要、sourceCreatedAt、source_key或导入确认时间。当前旧旅行引用缺失不能阻止修改本人日期。明确清除与保存相同日期也遵循一次CAS保存，不伪装为原操作回执。

发出写入后若丢响应或身份核验失败，应标为结果待核对，先从原GET重新读取同ID；读到相同日期只证明当前状态，不能声称找到了该请求回执。不自动重新PATCH，不偷偷使用新revision重发。原草稿可在同身份离线／后台隐藏后恢复；身份切换清空。其它照片设置存在未保存草稿时，日期操作先要求明确保存或放弃，不连带提交。

## 日期派生读取 v2

两个既有GET仅在明确查询`dateMode=confirmed-or-source`时返回v2。缺省继续原v1行为／形状，拒绝其它模式、重复或未知query。新版前端显式请求v2。日期选择共用小helper：符合编辑条件且日期有效则优先使用本人日期；否则可靠来源时刻沿原逻辑；都没有则unknown。不改变照片本身的`sourceTimeState/sourceCreatedAt`。

### 旅行建议

`GET /api/media/items/<id>/journey-suggestions?dateMode=confirmed-or-source`

v2完整顶层字段：`version:2, photoId, photoRevision, sourceTimeState, sourceCreatedAt, userConfirmedDate, dateBasis, currentJourneyId, suggestions, limit:20, hasMore, reason`。`dateBasis`为`userConfirmedDate|sourceCreatedAt|unknown`。

每个suggestion保留原`journeyId,journeyRevision,tripRevision,title,start,end,referenceTimezone,referenceTimezoneSource,alreadyLinked,reason`，将`sourceDate`改为`matchDate`；不返回旧sourceDate。本人日期按字面日历日与旅行start/end比较，不作时区换算；来源时刻仍按每趟旅行的referenceTimezone转换。reason行code仍为`date_overlap`；顶层code为`date_overlap|date_unknown|no_matching_journeys`。unknown必为空列表、hasMore=false。

手工日期提示「按本人确认日期匹配，未换算时区」；referenceTimezone仅说明旅行自己的日期口径。日期匹配不能认定地点、到访或自动关联。沿原photoRevision+journeyRevision+tripRevision明确确认，改日期后旧建议确认409；已有旅行关联不自动改变。

### 那年今日

`GET /api/media/memories/on-this-day?limit=24&offset=0&dateMode=confirmed-or-source`

v2完整顶层字段：`version:2, datePolicy:"confirmed-or-source", referenceDate, referenceTimezone:"Asia/Shanghai", scope:"mine", items, total, limit:24, offset, hasMore, unknownSourceTimeCount, unknownEffectiveDateCount`。不返回旧顶层dateBasis。

每项为`{item: Photo, displayDate, dateBasis, yearsAgo}`；dateBasis为`userConfirmedDate|sourceCreatedAt`，不返回旧sourceLocalDate。本人日期直接比较月日且年份早于referenceDate年份；来源时刻仍转上海日历日。排序displayDate降序＋ID升序，分页／跨午夜返回首页保持。2月29仅在对应闰日匹配。

unknownSourceTimeCount继续统计缺少可靠来源日期的本人静态照片（有本人日期仍属于此计数）；unknownEffectiveDateCount统计两种日期均不可用的照片。界面只以后一计数提示暂未纳入回看；不把本人日期说成可靠来源日期。共享／TV／旅行公开投影不增加日期字段。

## 前端与验证分工

沿现有Expo/Paper、DESIGN.md与原照片详情交互，不建立独立新页面。日期编辑testID：`photo-confirmed-date`、`photo-confirmed-date-input`、`photo-confirmed-date-save`、`photo-confirmed-date-clear`、`photo-confirmed-date-recheck`、`photo-confirmed-date-status`。异步请求仍须首尾核对/me、原ID/revision，离线／后台／迟到旧身份响应不显示私人内容；日期操作后失效建议、回忆及重复提示旧缓存。

- 后端分支：household_media.py、data_portability.py、新日期专项tests与必要的旧建议／回忆相邻用例；不编辑前端或本契约。
- 前端分支：photos、photoJourneySuggestions、photoMemories解析器，照片详情／建议组件，必要日期组件和Node测试；不编辑后端或本契约。
- 浏览器分支：独立新harness与简短说明，组合完成后实际执行两条端到端：设备上传确认→日期→刷新→旅行建议／回忆；丢响应核对／并发版本／切换成员／清除。
- 集成人：契约、非作者审查、分支组合、实际构建与浏览器执行，随后按75表稳态基线准备发布。代码和测试未通过前不宣称已实现或已上线。

测试验证真实持久化、净化图片字节不变、共享／TV授权不变、个人／共享导出、日期与时区矩阵、撤权及丢响应；只运行受影响范围。无需重跑全部视频、财务或再次执行已消费73→75迁移。
