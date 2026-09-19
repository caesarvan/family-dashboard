# 本人订单关联库存

本接口把已导入的本人订单行明确关联到本人创建的采购批次。它只新增或解除私有来源关系，不创建支出、不分摊订单金额、不更改采购实付或完成状态，也不把付款、订单状态、数量原文当作收货证据。实际收货继续使用原库存 movement 接口。

实现为 `inventory_sources.py`，由每个家庭的 `inventory_api.register_inventory` 显式注册，沿用 `inventory_source_links` 和 `inventory_operations`，无新表或 DDL 变化。`inventory_core.py` 的 `apply_with_receipt` 负责回执、当前库存 ACL、双 revision 和事务 savepoint。本文是接口契约，部署与浏览器验收另记录。

## 使用路径与隐私

从本人财务订单详情进入，明确选择一条商品行；可打开已有可见关联，或选择一个库存物品及本人创建的 `purchase` 批次。只有本人明确点击「用商品新建私人物品」后，才将所选商品的名称、规格预填为可编辑草稿；默认保持 `private`，不自动保存或共享，单位和数量仍须本人手动填写。已有新物品／新批次表单继续负责数量、单位、共享范围和可选采购关联。创建后再预览并明确关联，取消关联不会删除已创建的物品或批次。每个创建操作沿用自己的既有回执，未知结果先查询原操作编号，不能重新建一份。

订单、来源详情和预览只给本人当前成员会话；来源详情还要求当前库存可见且本人是批次 creator。物品 owner 不能因此读取另一位批次 creator 的财务来源。共享库存投影和操作结果不嵌入订单正文、金额、原订单号、商品 URL、来源摘要或付款资料。电视、另一家庭和无有效会话均拒绝。来源 getter 对其他 creator 返回 403，库存撤回共享后为 404；已归档库存为 410。

## JSON 类型与只读路由

以下示例 ID 都是假数据。`orderId` 是本库 `hub_transactions.id`，不是商家的原订单号。

```json
{
  "id": "111111111111111111111111",
  "revision": 1,
  "title": "合成商品等 2 项商品",
  "date": "2026-09-19",
  "status": "交易成功"
}
```

以上为 `Order` 类型。`SourceLine` 为 `{lineKey,title,variant,quantityText}`，全部是字符串，数量只展示原文。普通无 `orderItems` 的订单是一条 `lineKey="order"`；有商品列表的订单按持久化数组顺序使用 `item:0`、`item:1`。不使用工作表 `sourceLine`、商品名称、金额或 URL 识别商品行。

当前财务 API 不允许修改订单商品数组；重复导入保留已有记录，有内容差异报告冲突。行序号只在同一持久化快照内有意义；保存的订单 revision 或完整正文 digest 变化后标为待核对，不把旧序号悄悄对应到新商品。

`GET /api/inventory/orders/<orderId>?limit=50&offset=0`：本人 `kind=orders` 才可读；payments 等其他类型或其他 owner 的记录为 404。`limit` 为 1..100，`offset` 为 0..100000；重复、未知或非法查询参数为 400。订单最多读取 5000 条商品行，每页最多 100 条。

```json
{
  "order": {"id":"111111111111111111111111","revision":1,"title":"合成订单","date":"2026-09-19","status":"交易成功"},
  "lines": [{"lineKey":"item:0","title":"合成商品","variant":"合成规格","quantityText":"两盒",
             "linkState":"none","link":null}],
  "total": 2, "limit": 1, "offset": 0, "nextOffset": 1
}
```

`linkState` 为 `none/linked/unavailable`。仅 `linked` 时 `link` 为 `{sourceLinkId,sourceRevision,itemId,acquisitionId}`。关系属于本人但库存已不可见、已归档，或订单快照变化时返回 `unavailable` 和 `link:null`，不返回隐藏的库存 ID。`sourceRevision` 是关系的 revision。

`GET /api/inventory/acquisitions/<acquisitionId>/source` 不接受查询参数，返回：

```json
{
  "itemId": "222222222222222222222222",
  "acquisitionId": "333333333333333333333333",
  "link": {
    "id": "444444444444444444444444", "revision": 1,
    "status": "active", "state": "current", "reviewReasons": [],
    "orderId": "111111111111111111111111", "lineKey": "item:0", "orderRevision": 1,
    "order": {"id":"111111111111111111111111","revision":1,"title":"合成订单","date":"2026-09-19","status":"交易成功"},
    "line": {"lineKey":"item:0","title":"合成商品","variant":"合成规格","quantityText":"两盒"}
  }
}
```

无历史关系时 `link:null`；优先返回活动关系，否则返回最新解除的关系。`status` 为持久化 `active/detached`；`state` 为派生 `current/needs_review/detached`。`reviewReasons` 可含 `source_missing/source_changed`。来源丢失时 `order/line` 均为 null；来源变化时 `line:null`，`order` 是本人目前可读的订单摘要。解除后的历史仍可带待核对原因。原始正文和旧快照不复制保存。opening 批次不支持来源，返回 400。

## 预览与明确确认

两条 POST 都要求当前家庭真实成员、CSRF、Origin 检查，严格 JSON 字段和 16 KiB 上限。`requestId` 是 32..64 位小写 hex，客户端在本次意图开始时生成并保留。ID 为 24 位小写 hex；revision 必须是 1..2^53−1 的整数，不接受 bool。

`POST /api/inventory/sources/preview` 关联请求：

```json
{
  "requestId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "operation":"attach", "acquisitionId":"333333333333333333333333",
  "itemRevision":2, "revision":1,
  "orderId":"111111111111111111111111", "lineKey":"item:0", "orderRevision":1
}
```

解除请求：

```json
{
  "requestId":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "operation":"detach", "acquisitionId":"333333333333333333333333",
  "itemRevision":3, "revision":2,
  "sourceLinkId":"444444444444444444444444", "sourceRevision":1
}
```

两种请求均返回 200：`{requestId,operation,item,acquisition,order,line,link,previewToken,expiresInSeconds:900}`。`item/acquisition` 为现有库存投影；attach 的 `order/line` 为所选本人来源、`link:null`；detach 的 `link` 为要解除的关系，来源已丢失时 `order/line` 可以为 null。预览不产生来源、库存动作、回执、审计或 meta revision 变化。

token 绑定家庭、owner、真实 session id、credential hash、auth_version、requestId、规范意图与订单正文 digest；只包含必要 ID、revision 与摘要，不含订单商品正文和金额。

`POST /api/inventory/sources/confirm`：

```json
{
  "requestId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "previewToken":"<原预览凭据>",
  "confirmSource":true
}
```

首次成功和重放都返回 200、现有 `InventoryResult={operation,item,acquisition}`；`operation` 另含 `sourceLinkId/sourceRevision`，`replayed` 为 false/true。来源关联与解除只提升 item、acquisition 各一个 revision；数量、状态、日期、共享范围及金融数据保持。attach 永远写入 `settlement_id=NULL`，不暗示或创建付款关联。

在同一 `BEGIN IMMEDIATE` 中重新认证、验证 token 与当前 ACL；旧成功回执先于可变依赖及 token 年龄检查恢复。新操作要求预览仍在 900 秒内、双库存版本正确、订单 owner/revision/digest/line 仍匹配、唯一约束满足。新 detach 检查本人关系 revision 和目标批次，但不依赖原订单仍存在或仍相同。回执、关系、两级 revision、审计和 settings.meta 一起提交；失败全部回滚。历史关系和回执不删除，容量限制沿用库存核心。

同一 owner/订单/行最多一个活动关系，同一批次最多一个活动来源。换来源先明确解除旧关系再预览新关系；解除不会退货、退款或反转原实物动作。

## 失败与恢复

未知结果查询既有 `GET /api/inventory/operations/<requestId>`，只返回本人仍可见库存的最小历史操作结果和当前库存投影；恢复不需要原 token。token 有效签名且绑定同一当前会话时，原成功意图即使 token 过期、来源删除或已解除，仍可重放原回执；同一操作编号换意图为 409 `request_conflict`。换会话不能继续使用原 token，但本人新会话可以读自己的历史操作编号。

非法输入、未成功且预览过期为 400 `invalid`；未明确确认是 400 `confirmation_required`；认证变化 401；TV、错误来源权限或 token 会话不匹配 403；不可见/不存在 404；归档 410；revision/唯一性/正文变化 409 `conflict`；容量 409；忙碌或存储失败 503。来源在预览后被删除时确认失败 404，用户应重新读取；失败不会保存回执。错误仅返回既有中文消息和固定 code，不回显源数据、SQL、凭据或原异常。

本模块测试使用真实合成 XLSX 导入、真实 Cookie/CSRF 和独立临时数据库，覆盖重导、来源修改/删除、隐私/家庭/会话、并发、未知结果、各写入点回滚以及无金额和库存数量变化。实际执行结果以当次测试记录为准；本文不声称已上线或已在真实家庭数据验收。
