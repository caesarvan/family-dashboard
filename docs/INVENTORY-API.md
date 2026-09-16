# 手动库存 HTTP 接口

本候选把已审 [库存核心](INVENTORY-MODEL.md) 接成可供手机 UI 使用的 API：私密物品、明确共享、采购/期初批次、分次收货、消费/处置/退回/更正、追加式反转和本人幂等回执。只关联本家庭真实购物记录 ID，不解析金融订单、不写支出/付款/退款、不改购物完成或实际花费、不自动补货或创建任务。

当前模块需要集成人显式接线；**没有修改 app、Docker、导出、迁移或生产**。本候选不声称完整“订单→金融来源→库存”目标已完成。

## 注册与安全边界

```python
from inventory_api import register_inventory

# users/entities/member_sessions 已注册；db() 是当前户 request-local 连接。
inventory = register_inventory(app, db, Problem, initialize=True)
```

返回 `InventoryAPI`，存入 `app.extensions['inventory']`。`db()` 必须始终返回当前家庭数据库的同一请求连接，开启 foreign_keys，并有正确关闭钩子；不能传默认家庭固定连接来服务子户。每个子户工厂同样调用此注册函数。默认初始化调用核心 `initialize_inventory` 并严格核验已有 DDL；单独完成审查迁移后可明确 `initialize=False`，不是请求时补 schema。

每个读取开启 `BEGIN`，写入开启 `BEGIN IMMEDIATE`。模块在事务内调用真实 `member_sessions.current(con)`，对比当前 actor 的成员、auth_version 与 householdId；没有凭请求 owner 字段认证的入口。TV 与 `X-Display-Mode:tv` 全部拒绝，包括列表、回执与元数据；仅配对电视 cookie 不授予库存访问。写入再次验证 CSRF 与同源 Origin；应用原有统一认证/JSON/CSRF 门禁继续生效。

核心写入、不可变回执、审计和 settings.meta 在同一连接/事务；只有 `replayed:false` 才新增一条 `inventory.*` 审计并把 meta revision 加 1。任一步失败全部回滚。禁止调用者在同连接已有事务时进入 API；模块不会提交调用者未完成的其它事务。SQLite/内部异常转换为固定安全错误，不输出原请求、SQL 或异常上下文。

HTTP GET 响应依赖现有应用 `Cache-Control:no-store`，不在 `/api/state` 或电视投影添加库存。完整库备份/恢复须保留核心五表和回执；个人导出应由集成人另行接核心白名单导出，不能把数据库原始记录 jsonify。

## 路由与分页

所有路由前缀 `/api/inventory`，均限当前真实家庭成员：

| 方法与路径 | 用途 |
| --- | --- |
| GET /items | 当前可见物品，有界分页/搜索 |
| POST /items | 新建默认私密物品 |
| GET /items/:id | 物品详情 |
| PATCH /items/:id | owner 编辑字段/共享/撤回共享 |
| DELETE /items/:id | owner 明确归档，核心要求库存零且批次已关闭/取消 |
| GET /items/:id/acquisitions | 当前可见物品的批次分页 |
| POST /items/:id/acquisitions | 登记采购或期初批次 |
| GET /acquisitions/:id | 批次与当前物品详情 |
| PATCH /acquisitions/:id | 按能力编辑批次，双 revision |
| GET /acquisitions/:id/movements | 安全事件历史分页 |
| POST /acquisitions/:id/movements | 明确实物变动 |
| POST /acquisitions/:id/movements/:movementId/reverse | 明确反转原事件 |
| GET /operations/:requestId | 本人操作回执与当前安全投影 |

ID 都是 24 位小写十六进制；requestId 为 32–64 位小写十六进制。所有列表接受 `limit`（默认 50，1–100）和 `offset`（默认 0，0–100000）；只允许十进制整数字符串，无重复参数。物品列表另接受 `scope=all|mine|shared`（默认 all）和 `q`（最多 100 字符，按 title/variant/location 子串搜索；`%`、`_` 作为普通文字）。mine 仅本人，shared 包括自己与另一成员的已共享物品；all 为本人私密/共享加另一成员共享。ACL 和未删除条件先于过滤、count 和分页。

物品/批次按 ID 升序，事件按 createdAt DESC、ID DESC。示例空列表：

```json
{"items":[],"total":0,"limit":50,"offset":0,"nextOffset":null}
```

nextOffset 非 null 表示可继续当前查询。没有历史快照 token；并发增删可能改变后续页，用户刷新时从第一页读取。详情、回执和写请求不接受任何查询参数。批次/历史详情不嵌套无界列表。

## 公开对象

`GET /items/:id` 返回 `{"item":...}`。完整 item 合成示例：

```json
{
  "id":"111111111111111111111111","owner":"member1","visibility":"private",
  "title":"电池","variant":"AA","unit":"节","location":"玄关抽屉",
  "revision":4,"onHandQty":2,"inTransitQty":4,"plannedQty":0,
  "reorderPoint":3,"belowThreshold":false,
  "canRead":true,"canMutate":true,"canManage":true,
  "createdAt":"2026-09-16T09:00:00.000000+00:00",
  "updatedAt":"2026-09-16T09:10:00.000000+00:00"
}
```

数量严格沿核心定义。付款不会增库存、退回不减少累计 receivedQty，调整不制造收货事实；`belowThreshold` 比较 onHandQty+inTransitQty 与阈值，只显示建议。canManage 仅 owner；共享成员 canMutate 表示可登记批次与实物变动，不可改物品 ACL/单位/名称。

`GET /acquisitions/:id` 返回 `{"item":上述当前对象,"acquisition":下列对象}`；批次列表 items 也是下列对象：

```json
{
  "id":"222222222222222222222222","itemId":"111111111111111111111111",
  "shoppingId":null,"kind":"purchase","orderedQty":6,"orderState":"in_transit",
  "orderedOn":"2026-09-16","expectedOn":"2026-09-20","warrantyUntil":null,
  "afterSalesState":"none","note":"合成批次",
  "revision":2,"itemRevision":4,"canMutate":true,"canManageSources":true,
  "canEditAllFields":true,
  "editableFields":["afterSalesState","expectedOn","note","orderState","orderedOn","orderedQty","shoppingId","warrantyUntil"],
  "createdAt":"2026-09-16T09:00:00.000000+00:00",
  "updatedAt":"2026-09-16T09:10:00.000000+00:00",
  "onHandQty":2,"receivedQty":2,"returnedQty":0,"remainingExpectedQty":4,
  "fulfillmentState":"partial"
}
```

fulfillmentState 为 unreceived/partial/received。物品 owner 或该批次 creator 为 canEditAllFields=true；其他共享成员 editableFields 仅 `afterSalesState/expectedOn/note/orderState`。canManageSources 只是核心的 creator 能力标志，本候选**不提供金融来源接入路由**，UI 不应据此声称金融授权成功。shoppingId 是既有家庭采购清单关联，其 owner 字段是负责人，不是私人账本 ACL；接口仅核验真实存在且 kind=shopping，不读取购物金额/文本做推断。

事件列表白名单：`id/acquisitionId/actor/kind/deltaQty/occurredOn/reason/reversesId/createdAt/canReverse`。无 requestId、来源摘要、金融字段或原数据库 result。canReverse 表示原事件不是反转且尚未被反转，最终提交仍需当前数量与双 CAS 满足，可能返回 409 quantity。发生反转时原事件仍保留，新增 reverse 事件引用原 ID。

## 写请求

所有写入固定本次意图的 requestId；修正输入或并发冲突后的新意图需用户核对，不自动重发。数据字段的长度、日期、单位及数量规则见 [核心字段契约](INVENTORY-MODEL.md#公共函数与字段)。所有 JSON 对象拒绝重复键和未知字段；请求最大 16384 UTF-8 bytes，拒绝 NaN/Infinity。revision 与 quantity 必须是整数，bool/浮点/字符串不接受。

创建物品：

```json
{"requestId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","data":{"title":"电池","unit":"节","visibility":"private","reorderPoint":3}}
```

data 允许 title/unit/variant/location/visibility/reorderPoint，title/unit 必填。PATCH 物品为 `{"requestId":"...","revision":4,"patch":{"visibility":"shared"}}`；patch 非空。DELETE 为 `{"requestId":"...","revision":4,"confirmArchive":true}`。

创建批次：

```json
{"requestId":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","itemRevision":1,"data":{"orderedQty":6,"orderState":"in_transit","shoppingId":null}}
```

data 允许 kind/shoppingId/orderedQty/orderState/orderedOn/expectedOn/warrantyUntil/afterSalesState/note，仅 orderedQty 必填。kind 默认 purchase、orderState 默认 planned；opening 必须明确 orderState=closed，shoppingId/orderedOn/expectedOn 为 null，且创建批次不自动入库。批次 PATCH 为 `{"requestId":"...","itemRevision":4,"revision":2,"patch":{"expectedOn":"2026-09-22"}}`；kind 永远不可改，其他字段按 editableFields。

明确分次收货：

```json
{
  "requestId":"cccccccccccccccccccccccccccccccc","itemRevision":2,"revision":1,
  "data":{"kind":"receive","quantity":2,"occurredOn":"2026-09-16","reason":"核对实物两节"},
  "confirmReceived":true
}
```

kind 与唯一确认字段：receive→confirmReceived，consume→confirmConsumed，dispose→confirmDisposed，return→confirmReturned，adjust→confirmCorrection。只接受对应字段且值必须是布尔 true；不允许多余确认键。receive/consume/dispose/return 的 quantity 是正整数，adjust 是非零有符号整数；绝对值≤1000000。occurredOn 必填合法日期；除 receive 外 reason 必填非空。所有动作明确选批次，不从日期、付款、退款或照片推断实物事实。

反转：

```json
{"requestId":"dddddddddddddddddddddddddddddddd","itemRevision":4,"revision":3,"data":{"occurredOn":"2026-09-16","reason":"原退回实际未发生"},"confirmReversal":true}
```

反转数量由原事件决定，不接受客户端 quantity/kind。原事件不能跨批次、不能是 reverse、不能重复反转，也不能导致负库存或超收。

成功 envelope：`{"operation":核心最小回执,"item":当前投影,"acquisition":当前批次投影}`。没有批次的写入省略 acquisition；归档成功只返回 operation（含 deleted:true）。operation 含 itemId/itemRevision/replayed，按操作可含 acquisitionId/acquisitionRevision/movementId/quantityDelta/deleted。创建物品/批次首次返回 201、同请求重放 200，其余写入 200。

## 重试、撤权和错误

核心同 actor/requestId/原载荷先查回执，再检查可能变化的购物依赖；相同意图重试不重复入库、反转、审计或 meta 更新。不同内容复用 requestId 返回 409 request_conflict。原意图的版本是摘要的一部分，不能擅自换新 revision 再发同 requestId。

网络结果未知先 `GET /operations/:requestId`：仅本人成员可读、重新检查当前条目 ACL；返回与成功写一致的 envelope，operation.replayed=true。operation 版本表示当时成功结果，item/acquisition 是当前投影，UI 应以后者更新当前版本。未完成/不存在/他人 requestId 为 404；撤回共享后旧请求与回执均 404；已归档条目为 410，包括归档本身的回执恢复，不能复活。失败没有回执。原购物被删除后有效回执仍可恢复，其 acquisition.shoppingId 已变 null，两级当前 revision 已提升；不得把原回执版本当成未变的当前版本。

模块错误为 `{"error":"固定安全中文","code":"..."}`：400 invalid/confirmation_required；401 unauthorized；403 forbidden/csrf；404 not_found；409 conflict/quantity/capacity/request_conflict；410 gone；503 busy/storage/schema/transaction_required。现有应用统一 guard 的 401/403/415 可能仅有 error 字段，前端按 HTTP 状态兼容处理。409 不携带另一人的私有快照；客户端重新读当前可见详情再决定。基础授权失败和格式错误不记录库存操作回执。

## 真实验证范围

`tests/test_inventory_api.py` 在临时目录显式注册模块，包括真实 HouseholdPlatform 子户工厂、成员 cookie、CSRF、实际配对只读电视和 SQLite。验证私密/共享/撤权、列表 count/搜索/分页、批次能力、分次收货/消费/退回/反转/更正、购物 FK 解绑、回执先于可变依赖、同 requestId 与不同请求的双连接竞争、重启恢复、审计失败原子回滚、安全错误与事务内会话再验证。购物实体/非 meta settings/金融表作未修改哨兵；网络被禁止。

证据与初始失败保存在 ignored `test-results/inventory-api/`。本范围没有浏览器 UI、云订单、实户账单、迁移/恢复/Docker或生产写入；这些须在各自独立候选与组合验收记录。
