# 跨来源展示副本重复提示

独立后端候选，尚未接入界面或上线。仅比较当前家庭本人已保存、已确认的照片，在 Google Photos 与本地上传两个不同来源之间提示一致的**展示副本**。不判断原图相同或视觉近似，不自动合并、删除、上传、共享或授权电视。

## 读取接口

`GET /api/media/items/<photoId>/duplicates?limit=20&offset=0`

使用当前家庭的真实成员会话；只有拥有者可查询，即使目标已经共享，伴侣也不能查询。电视不能查询。`limit` 默认 20、范围 1–20；`offset` 默认 0、范围 0–4000。拒绝重复参数及 `owner`、`scope` 等其它参数。

```json
{
  "photoId": "原目标 ID",
  "photoRevision": 1,
  "matchBasis": "display-copy-sha256",
  "label": "展示副本一致，原图未核验",
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0,
  "hasMore": false,
  "coverage": {
    "scope": "mine",
    "scanLimit": 1000,
    "scanned": 0,
    "capped": false,
    "unverifiable": 0
  }
}
```

`items` 每项沿用已有拥有者 Photo DTO：原 `id`、当前 `revision`、`caption`、`previewUrl`、`width`、`height`、`mediaType: "photo"`、`contentType: "image/jpeg"`、`visibility`、`journey`、`createdAt`、`canManage`、`accountId`、`displayFilename`、`source`、`sourceCreatedAt`、`sourceTimeState`。Google 来源为 `google-photos`，本地来源为 `local-upload`。不返回内容散列、存储键或新的照片对象；打开详情/预览仍走原 ID 的现有权限校验。

返回条件为净化 JPEG 的现有加密元数据中 `sha256`、`width`、`height`、`bytes` 四项完全相等，且与目标来源不同。旧 Google 元数据未显式写 `source` 时仍按既有 Google 来源处理。重新编码、裁剪或不同净化版本可能没有结果；零结果不证明原图不同。

## 范围、排序与时效

- 仅当前拥有者的 `ready` 且 `confirmed_at` 非空记录；排除目标本身、待确认、删除和视频。来源必须当前有效，本地来源还需加密的 `sourceVersion` 和原上传指纹绑定；不能把已失效 Google 账户的 NULL 当作本地来源。
- 按原照片 ID 升序分页，每次重新读取。`total` 是本次实际检查范围内的匹配数，不是整个图库的重复总数。两次请求间的新增、删除、撤权或编辑可能改变页码；客户端刷新应重新读取第一页。
- 每次最多读取 1000 条本人已确认 ready 媒体元数据，另取一条判断截断；无需读取图片/视频 BLOB 或再次解码。上限也包含随后排除的视频，确保扫描工作量有界。目标单独读取，不消耗此额度。
- `scanned` 为其中具有有效来源和指纹的本人照片数量；`unverifiable` 为来源失效、缺少有效指纹或无法读取元数据的记录数量，不含已识别的视频。`capped` 表示仍有本人 ready 记录未检查。任一 `capped=true` 或 `unverifiable>0` 时，界面必须说明“仅检查了部分已保存照片”，不能宣称查遍图库。
- 初始只读快照释放后，重新读取目标和整段范围，包括指纹、当前 revision、来源权限和计数。最终短暂 SQLite 写入预留锁仅用于阻止投影过程中并发修改，执行只读查询并回滚，不修改数据/审计。原会话在读取前、最终投影前和释放快照后核验；过期或成员改变时不返回旧照片内容。

## 错误与既有行为

未登录/会话失效 401；电视 403。不属于本人、不存在、待确认、删除或视频目标均 404，不给其它拥有者的存在或计数提示。目标来源无效为 409 `reauth`，目标指纹不可核验为 503 `unavailable`；候选不可核验则只增加本人 `unverifiable`。最终读取预留锁遇数据库忙时返回 503 `unavailable`，可由本人刷新重试，不返回旧结果；其它 SQLite 错误不会伪装成成功。参数非法为 400 `invalid_input`。

这项提示要求有效来源，不改变已确认 Google 私密照片在连接需重新授权时仍可由本人查看的既有语义。共享、电视、删除和原确认收据均不改。无 DDL、迁移、持久化重复缓存或新图像处理任务；每次在有界范围解密元数据，成本随该范围线性增长。

## 验证边界

定向测试使用真实 Flask、成员/家庭/配对电视会话、临时 SQLite、加密元数据和 Pillow 合成图片。覆盖双向跨源一致、四项指纹、相似但重编码不匹配、其它拥有者/家庭不可见、无 BLOB 查询、只读不变、撤权/删除/标题修改发生在快照之间、会话失效、稳定分页及实际 1000 条扫描边界。合成云选择通过现有任务状态机；不访问真实 Google、原用户照片、浏览器或生产。
