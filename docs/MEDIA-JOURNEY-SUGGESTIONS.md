# 按照片来源时间建议关联旅行

本轮增加 `?dateMode=confirmed-or-source` 的 v2 查询，设备照片可按本人明确保存的日期匹配旅行。精确字段与兼容规则见[照片日期确认契约](MEDIA-CONFIRMED-DATE.md)；下文继续描述不传该参数的 v1 来源时间查询。本人确认日期只按年月日比较，不转换成拍摄时刻，也不证明到访地点。本轮扩展的上线状态以交接记录为准。

实际上线状态见 [媒体交付](MEDIA-DELIVERY.md) 与 [交接记录](HANDOFF.md)；本文描述接口，不代替本人 Google 验收。它读取已保存照片的来源创建时间，提示日期相符的当前旅行；只有本人明确确认后才关联。不会猜地点、确认到访、共享照片、授权电视、写财务、调用模型或访问 Google。

## 来源时间与旧记录

Google Picker 的 [`createTime`](https://developers.google.com/photos/picker/reference/rest/v1/mediaItems) 是媒体创建时间，不是本地导入时间，也不能据此证明照片拍摄地点。新导入把已经校验的 RFC3339 字符串保存到现有 `metadata_cipher`，沿用 row／household／owner／source／previewKey 加密绑定。允许 Z、有效时区偏移和最多九位小数，保留原字符串精度；没有新表或迁移。确认与远端清理后仍可读取。

本人照片 DTO 新增 `sourceCreatedAt:string|null` 与 `sourceTimeState:'known'|'unknown'`。伙伴和电视投影不含这两个字段；本人个人 ZIP 的元数据导出包含它们，共享导出不包含。`createdAt` 仍是本地导入时间，不能当来源时间使用。

旧记录没有保存来源时间时返回 `unknown/null`，不给日期建议。不扫描旧图片、重下载、从导入时间补填或改写旧行；重新选择同一来源的 duplicate 也不暗中补填原照片。旧照片仍可通过原手工旅行下拉框关联。

## 只读建议

`GET /api/media/items/<id>/journey-suggestions` 不接受 query 参数，仅本人已确认的 ready 照片可用。它在一个读事务内核对当前成员／家庭及照片拥有者，并读取当前 workflow 与 trip：

```json
{
  "photoId": "24hex",
  "photoRevision": 2,
  "sourceTimeState": "known",
  "sourceCreatedAt": "2026-12-01T16:30:00.123456789Z",
  "currentJourneyId": null,
  "reason": {"code": "date_overlap", "message": "请核对来源日期和旅行，再明确确认关联。"},
  "suggestions": [{
    "journeyId": "workflow的24hex",
    "journeyRevision": 1,
    "tripRevision": 1,
    "title": "合成旅行",
    "start": "2026-12-02",
    "end": "2026-12-04",
    "referenceTimezone": "Asia/Shanghai",
    "referenceTimezoneSource": "plan",
    "sourceDate": "2026-12-02",
    "alreadyLinked": false,
    "reason": {"code": "date_overlap", "message": "来源创建时间在该参考时区的日期落在旅行起止日期内；这不证明拍摄地点或实际到访。"}
  }],
  "limit": 20,
  "hasMore": false
}
```

使用 workflow `journey.id`，不是 `tripId`。来源时刻转换到该旅行 plan 的 `referenceTimezone`，其日期须落在**当前 trip** 的 start/end 之间，包含两端。标题和日期取当前 trip，不能用旧 plan 覆盖用户后续修改。legacy v1 旅行使用原约定 `Asia/Shanghai`，明确标 `referenceTimezoneSource:'legacy_default'`；v2 为 `'plan'`，无效时区或日期不会猜默认值。排序为当前 trip 开始日期倒序、workflow ID 升序，最多二十条；更多匹配以 `hasMore:true` 表明，没有自动关联或不完整结果冒充全部的行为。

顶层 `reason.code` 固定三种：`date_overlap` 有匹配、`source_time_unknown` 缺少来源时间、`no_matching_journeys` 当前日期无匹配。后两者 `suggestions:[]`。已有照片关联通过 `currentJourneyId` 和 `alreadyLinked` 标记，只读接口不更改它。

未知／其他家庭／他人照片（包括共享）返回 404；本人已删除返回 410；未确认返回 409 `not_ready`；电视 403，失效成员沿原认证边界拒绝。API 不披露 Google ID、来源 URL、原 metadata 或账户信息。

## 明确确认与冲突

复用 `PATCH /api/media/items/<id>`，建议确认精确发送四个字段：

```json
{
  "revision": 2,
  "journeyId": "选择的workflow的24hex",
  "expectedJourneyRevision": 1,
  "expectedTripRevision": 1
}
```

两个 expected 字段必须同时为正整数，journeyId 必须非空。这个确认模式不接受 caption／visibility，避免把未保存的编辑草稿顺带提交。在同一个写事务中重新核当前成员、拥有者、照片 revision、workflow revision 和当前 trip revision；任一过时或旅行已移除返回 409 `conflict`，无部分修改。前端应重新读取照片和建议，让用户再次明确确认，不能自动用新版本重发。请求成功只修改照片关联及其 revision／审计，保留现有共享与电视许可，不新增任何授权；重复旧 revision 返回冲突，不重复执行。

原手工 PATCH（`revision` 加 caption、journeyId 或 visibility）保持兼容，不要求 expected 字段。原手工取消旅行关联时的降私密／撤电视策略保持。

## 验证范围

`tests/test_media_journey_suggestions.py` 使用真实临时 Flask、成员 cookie、SQLite、加密 metadata 和旅行预览／应用接口；照片、账号与时间均为合成输入，禁止网络。覆盖来源时间保存／清理／重启／本人导出、旧 unknown 与 duplicate 不补填、纳秒与偏移／日期线／DST、本人与伙伴／电视／跨户隔离、当前 trip 与旧 plan 区分、二十条确定排序、只读不改数据库、三版本冲突、明确关联不影响共享／电视／地点及手工兼容。适用的媒体引擎、worker、结果和导出回归另按实际执行记录交付，不把合成结果等同真实 Google 验收。
