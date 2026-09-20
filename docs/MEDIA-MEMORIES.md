# 本人照片 · 那年今日 API

本轮日期确认扩展采用显式 `dateMode=confirmed-or-source` 的 v2 响应，完整字段、日期优先级和未知日期计数见[照片日期确认契约](MEDIA-CONFIRMED-DATE.md)。下文是未传该参数时继续保留的 v1 协议；v2 不用本人确认日期改写 `sourceCreatedAt`。本轮扩展的上线状态以交接记录为准。

该成员只读查询已随[设备照片与那年今日批次](LOCAL-PHOTO-ACCEPTANCE.md#local-photo-release)发布；本文保留 v1 协议，日期确认扩展的状态见[本批验收](MEDIA-CONFIRMED-DATE-ACCEPTANCE.md#media-date-release)。查询不新增表、媒体副本、任务、依赖或云调用，原照片 ID、revision、共享及电视许可保持。

## 查询

`GET /api/media/memories/on-this-day?limit=24&offset=0`

仅接受 `limit`（1–100，默认 24）和 `offset`（0–4000，默认 0）的十进制整数字符串。未知参数、重复参数、空值、负数、浮点数和越界值返回 `400 invalid_input`。不接受客户端日期、时区、owner、家庭、scope 或 journeyId。POST／PUT／PATCH／DELETE 不提供写入口。

返回示例：

```json
{
  "referenceDate": "2026-09-20",
  "referenceTimezone": "Asia/Shanghai",
  "dateBasis": "sourceCreatedAt",
  "scope": "mine",
  "items": [{
    "item": "此处为原 GET /api/media/items/<id> 的完整本人 Photo DTO",
    "sourceLocalDate": "2025-09-20",
    "yearsAgo": 1
  }],
  "total": 1,
  "limit": 24,
  "offset": 0,
  "hasMore": false,
  "unknownSourceTimeCount": 0
}
```

示例中的 `item` 占位文字仅说明类型；实际 API 返回原照片对象，包含原 ID／revision／previewUrl／caption／visibility／journey 及本人字段，不创建回顾记录。前端必须通过原 ID 重新读取照片详情，不能把回顾快照当作新的保存对象或长期授权。

## 日期与排列

- 服务器在一次查询开始时取北京时间（IANA `Asia/Shanghai`）的今天，响应明确给出 `referenceDate` 和时区。客户端不能改“今天”。查询期间过午夜保持本次日期一致，下次读取返回新日期；前端发现日期变化须回到第一页，避免拼接两个日期的分页。
- 权威日期为已经保存的 `sourceCreatedAt`，即 Picker 来源创建时间。先转换到上述时区，再选出**年份早于今年、月日与今天相同**的照片。本地导入 `createdAt`、编辑 `updated_at` 不能代替来源时间，也不从文件名或说明猜日期。
- 2 月 29 日只匹配往年的 2 月 29 日；非闰年 2 月 28 日不额外收录闰日照片。不由来源时间推断拍摄地点或实际到访。
- 依来源北京时间日期倒序，同一来源日期以原 ID 升序；匹配月日固定，所以年份由近到远。同一年同日不按时分秒重新排列。来源字符串及其最多九位小数仍原样保留，不改写元数据。
- `total` 是本次匹配数；`unknownSourceTimeCount` 是当前本人候选静态照片中缺少、非法或无法在参考时区表示来源日期的数量，均排除在结果外。不会回填旧数据。损坏的加密元数据返回原 `503 unavailable`，不能伪装成“没有回忆”。

## 隐私与现有语义

只查询当前真实成员、当前家庭中 `owner` 为本人、`state=ready` 且已确认的静态照片。旧记录未存 `mediaType` 时沿原规则视为照片；视频及其他类型不进入结果或未知日期统计。当前本人已确认图库最多 1000 项，扫描只投影元数据列，绝不读取图片 BLOB 或视频缓存来生成列表。

来源时间目前只在本人 DTO 中提供；家人已共享的照片仍不进入本人的回顾，避免按日期筛选间接公开伙伴来源时间。伙伴、其他家庭、暂存、已删除和未确认记录不贡献结果或计数。TV 账户即使获某张照片展示许可，也不能访问这个成员回顾入口。

复用原照片建议的事务身份检查：读取前核实成员／家庭／原会话，读取后释放 SQLite 快照再核实原会话；撤销、到期、auth_version 改变或换成另一有效会话时丢弃整个响应。响应沿全站 API `Cache-Control: no-store`。读取采用当前一次数据库快照；后续照片编辑、删除或分页重读须重新读取原对象，不能承诺跨多次请求的冻结快照。

来源需要重新授权但既有策略保留本人副本时，回顾继续遵循原保留规则；不会另行要求云端重新下载。来源解绑或删除引起的现有本地清理保持原语义。接口不自动关联旅行、共享照片、授予电视、写财务、调用模型或访问 Google。

## 定向验收

`python -B -m pytest tests/test_media_memories.py -q` 使用真实临时 Flask／SQLite、成员登录／配对、加密照片元数据与合成静态图片。只在来源导入测试辅助协议中使用合成输入；不宣称真实 Google、视频解码或实体电视通过。

覆盖服务器跨午夜与闰日、来源偏移、午夜纳秒边界及日期／ID 稳定排序、分页／参数、旧未知时间、原 DTO／原 ID、重启和只读保全、两成员／两户／TV 隔离、真实独立 SQLite 连接提交的读取中撤权，以及通过 SQLite authorizer 拒绝 BLOB 读取的验证。前端和组合浏览器另批实现和验收。
