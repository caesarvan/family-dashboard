# 手动库存 HTTP 接口

接口把已审 [库存核心](INVENTORY-MODEL.md) 接成可供手机 UI 使用的 API：私密物品、明确共享、采购/期初批次、分次收货、消费/处置/退回/更正、追加式反转和本人幂等回执。只关联本家庭真实购物记录 ID，不解析金融订单、不写支出/付款/退款、不改购物完成或实际花费、不自动补货或创建任务。售后待办必须通过下述专用 POST 明确创建，每批次至多一条本地家庭任务。

当前库存已由应用工厂显式注册；售后待办已于 2026-09-19 发布，应用注册增加统一任务校验器注入，不改变该次发布的 Docker、导出或 DDL。[发布验收](INVENTORY-FOLLOWUP-ACCEPTANCE.md#inventory-followup-release)分别记录前端、浏览器、Linux 与生产证据，不由本地 API 测试推断完整“订单→金融来源→库存”目标已完成。

## 注册与安全边界

```python
from inventory_api import register_inventory

# users/entities/member_sessions 已注册；db() 是当前户 request-local 连接。
inventory = register_inventory(app, db, Problem, initialize=True, validate=validate)
```

返回 `InventoryAPI`，存入 `app.extensions['inventory']`。`db()` 必须始终返回当前家庭数据库的同一请求连接，开启 foreign_keys，并有正确关闭钩子；不能传默认家庭固定连接来服务子户。每个子户工厂同样调用此注册函数。默认初始化调用核心 `initialize_inventory` 并严格核验已有 DDL；单独完成审查迁移后可明确 `initialize=False`，不是请求时补 schema。

`validate` 是应用已有的 `validate(kind, value, db)`，售后创建以同一事务连接调用任务校验；可选参数保留旧独立注册兼容。未注入校验器时首次创建售后待办返回 `503 storage`，既有库存读写与已存在回执的重放不受影响。

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
| GET /shopping/:shoppingId/acquisitions | 从当前家庭采购查询本人可见的关联库存与批次 |
| GET /acquisitions/:id | 批次与当前物品详情 |
| PATCH /acquisitions/:id | 按能力编辑批次，双 revision |
| POST /acquisitions/:id/followup | 明确创建一条本地家庭售后待办，双 revision 与本人回执 |
| GET /acquisitions/:id/followup | 当前库存权限下读取待办关联与当前任务状态 |
| GET /acquisitions/:id/movements | 安全事件历史分页 |
| POST /acquisitions/:id/movements | 明确实物变动 |
| POST /acquisitions/:id/movements/:movementId/reverse | 明确反转原事件 |
| GET /operations/:requestId | 本人操作回执与当前安全投影 |

ID 都是 24 位小写十六进制；requestId 为 32–64 位小写十六进制。所有列表接受 `limit`（默认 50，采购关联查询默认 12，1–100）和 `offset`（默认 0，0–100000）；只允许十进制整数字符串，无重复参数。物品列表另接受 `scope=all|mine|shared`（默认 all）和 `q`（最多 100 字符，按 title/variant/location 子串搜索；`%`、`_` 作为普通文字）。mine 仅本人，shared 包括自己与另一成员的已共享物品；all 为本人私密/共享加另一成员共享。ACL 和未删除条件先于过滤、count 和分页。

物品/批次按 ID 升序，事件按 createdAt DESC、ID DESC。示例空列表：

```json
{"items":[],"total":0,"limit":50,"offset":0,"nextOffset":null}
```

nextOffset 非 null 表示可继续当前查询。没有历史快照 token；并发增删可能改变后续页，用户刷新时从第一页读取。详情、回执和写请求不接受任何查询参数。批次/历史详情不嵌套无界列表。

## 从采购查询已登记批次

`GET /api/inventory/shopping/:shoppingId/acquisitions?limit=12&offset=0` 是新增只读候选。沿用正式库存注册、当前家庭请求连接和事务内成员核验，不增加表、不改写入协议、不读取金融来源或操作回执。

返回形状为：

```text
{
  shopping: { id, revision, title, quantity },
  items: [{ item: InventoryItem, acquisition: Acquisition }],
  total, limit, offset, nextOffset
}
```

`shopping` 恰含这四个字段。`id` 为当前家庭真实采购 ID，`revision` 为当前正整数版本，`title/quantity` 为原始字符串；数量如“两盒六节”仍是文字，不推算物品单位或实收数。不会返回采购金额、负责人、备注、照片或私人账单来源。每行 `item/acquisition` 复用下文既有安全详情投影；`acquisition.shoppingId` 等于查询来源，`acquisition.itemId` 等于同行 `item.id`，能力字段依当前成员返回。

只接受 `limit/offset`，按批次 ID 升序。同一读事务先确认当前户采购存在，再在 SQL 中按本人或明确共享的物品权限、物品与批次未归档条件过滤，之后计数、分页及调用领域投影。未归档的已结束／已取消批次仍返回，方便继续查看售后与历史；归档不暴露存在性或数量。没有可见关联时为 `200` 和空页，不代表其他成员未私下登记。每次读取重新核验当前权限和来源，不提供跨页快照。

来源不存在、已删除或 ID 实际属于其他实体为 `404 not_found`；非法 ID、越界、重复或多余查询参数为 `400 invalid`。匿名／过期会话为 `401`，已配对电视为 `403`，跨户来源不匹配返回 `404`；`X-Display-Mode:tv` 在外层选择设备凭据，没有有效设备 Cookie 时为 `401`，有效电视仍不得读取库存。外层会话边界可先拒绝不属于本户的 Cookie。原采购删除后仍按既有外键行为清空批次 `shoppingId` 并保留实物历史，不因同名新采购自动接回。

查询不创建库存、不确认收货、不改变采购完成／实付或财务。一次采购可以有多个合法批次，不增加 `shoppingId` 唯一约束；新增批次与收货仍使用原确认、双版本及本人 `requestId` 回执协议。实际前端入口、浏览器组合及部署需要独立验收，不能由查询接口通过推断整链上线。

新增 `tests/test_inventory_shopping_query.py` 使用正式应用工厂、临时 SQLite、真实成员／电视 Cookie 和双家庭路由。27 项覆盖当前数量与安全投影、禁止金融／来源／回执读及任何库存事务写入、ACL 后计数分页、撤共享、归档与结束批次、同采购多批次、原采购删除／同名重建、重启、严格参数和会话撤销。没有外部网络、真实家庭数据、浏览器或生产操作。

作者实际记录分轮保留在 `test-results/inventory-shopping-query-*`：R1 新旧 API 合计 95 项，91 通过、4 失败；其中三项为新夹具误用采购 POST 的最小回执及电视显示模式错误码，另一项为旧夹具全局移除会话引擎后提前触发 SQL 授权守卫。精确基线 API 的单次隔离复现仍失败。新专项夹具修正后 R2 为 27/27；旧故障夹具随后仅对库存适配层的可选 `.get` 模拟依赖缺失，保留全局 SQL 守卫的真实引擎及原 503／零写入断言，不声称全局引擎缺失可返回 503。R3 实际完整 95/95，75.35 秒，358 个 Python 输入前后不变，XML SHA-256 `a843cebf2dd1b23a735dfb0d88ff050b20823d4d5ee6cdebd9f356663be8620a`；业务 API 自 R1 起未改，失败原件没有覆盖。

## 明确创建售后待办

`POST /api/inventory/acquisitions/:id/followup` 严格接受：

```json
{
  "requestId":"0123456789abcdef0123456789abcdef",
  "itemRevision":3,
  "revision":2,
  "data":{"title":"联系售后","owner":"shared","due":"2026-10-02","note":"核对处理进度"}
}
```

`data` 必须有 `title`，只允许 `title/owner/due/note`，提供的值必须是字符串；拒绝 `done/tripId/sourceId/sync/entityId` 等字段。统一任务校验器会去除标题和备注首尾空白：标题 1–100 字符、备注至多 500 字符；`owner` 默认 `shared`，也可指定当前户有效成员；`due` 默认空串，非空必须是有效日期。新任务固定 `done:false`、无旅行或云来源。标题与备注只来自明确输入，不自动拼入私人物品名称、批次备注、金融来源或金额。

任务属于当前家庭共享待办，**负责人是分工，不是隐私权限**。即使源物品仅本人可见，明确创建的任务文字仍可能在家庭清单与电视展示；撤回库存共享或归档库存不会删除已创建的家庭任务。客户端应在确认创建前说明这个边界。

同一个 `BEGIN IMMEDIATE` 事务内核验当前家庭/成员会话、CSRF、库存 ACL、物品与批次双版本，再校验首次创建时 `afterSalesState == open`、当前批次没有历史 `create_followup` 回执、任务字段和本户 tasks 数量小于 2500。owner 与可见该共享库存的其他成员均可明确创建。直接插入本户 `entities(kind='tasks')`，不调用普通任务 POST 或 `cloud_accounts.task_write`；配置了云清单也不会触发外部写入。

不增加表、列、索引或来源关系。不可变 `inventory_operations` 的 `create_followup` 回执 `entityId` 是唯一关联依据，保留原 actor/requestId 幂等范围。首次成功返回 `201` 和既有 `{operation,item,acquisition}` 信封，`operation.entityId` 是任务 ID；物品和批次 revision 各加 1，新增一条 `inventory.create_followup` 审计，settings.meta 加 1。实物数量、收货/退回历史、采购预算/实付/完成状态、金融来源及支出保持。任务、双版本、回执、审计和 meta 任一步失败均整笔回滚。

同一 actor、原 `requestId`、原始完整内容及原双版本重放返回 `200`、`operation.replayed:true`，不重复创建任务或审计。先查原回执，再执行可变业务校验：后来关闭售后、变更库存版本、停用原负责人、任务容量已满或任务已删除都不会阻断原意图重放；响应的库存投影仍是当前状态。仍必须具备当前会话和库存权限，撤权/撤共享或归档不能借旧回执绕过。相同 key 改内容返回 `409 request_conflict`。

不同 key 或其他成员创建同一批次时，即使双版本已更新为最新，也返回 `409 conflict`，不会生成第二条任务；SQLite 写事务串行化并发检查。历史任务删除、完成或售后重新打开均不自动重建。另一批次可拥有自己的待办。首次非 open 状态或双版本过期为 `409 conflict`，达到任务上限为 `409 capacity`，字段/负责人无效为 `400 invalid`。无权查看的物品为 `404`，归档库存按既有规则 `410`。

`GET /api/inventory/acquisitions/:id/followup` 不接受参数，在同一读事务先校验当前库存权限，再读取关联和当前 task。固定响应：

```text
{
  itemId, acquisitionId,
  state: "none" | "linked" | "deleted",
  task: null | { id, revision, title, owner, due, done, note }
}
```

从未创建为 `none`；任务存在为 `linked`，其内容、完成状态和 revision 随普通家庭待办编辑实时读取；曾创建但任务已删除为 `deleted`，`task:null`。GET 不要求售后仍开放，不返回另一 actor 的回执、requestId、payload digest、历史标题或云/旅行来源。历史创建结果仍只通过原 actor 的 `/operations/:requestId` 恢复；删除后的回执会保留原 `entityId`，不能把回执等同于任务当前存在。关联扫描已有有界回执表，不新增索引；完整库备份保留关系，现有个人导出未增加售后关系导出。

`tests/test_inventory_followup.py` 专项采用真实 Flask 工厂、临时 SQLite、成员/电视 Cookie、两家庭路由与双连接并发；外部网络被禁止。覆盖原 key 恢复、跨成员跨 key 唯一性、当前权限/撤共享、任务编辑/删除、原负责人停用、容量/校验失败，以及任务→双版本→回执→审计→meta 六个写入边界故障的回滚。保留物理库存、采购、私人财务与 schema 哨兵；仅模拟故障触发器及禁止云入口，未使用真实家庭或云账户。

作者本地原件分轮保留在 `test-results/inventory-followup-r1/r2/r3`：R1 系统 Python 无 pytest，未收集测试；R2 为 45 通过、1 失败，原因是测试误把查询回执的 `replayed:true` 与首次创建的 `false` 直接比较。仅修正断言后 R3 实际 46/46，通过且无跳过，pytest 报告 41.99 秒，368 个 Python 输入前后散列一致；业务实现自 R1 起未变。R3 JUnit SHA-256 `5e4e135ca821a3623d17de83b2bdacfedeafccfdf6cd39b560b5da4c07f6ea22`，结果记录 SHA-256 `24801de2eb0b90482310f77d8d40983ed9b935a26b00b47f84b2c0d23090ff2b`。这些是 Windows 本地专项结论，未运行前端、浏览器、Linux、生产或真实外部云；失败原件没有覆盖。

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
