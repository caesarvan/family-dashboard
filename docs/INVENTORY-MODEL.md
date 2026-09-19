# 库存核心：存储、数量与事务契约

本文件对应独立 `inventory_core.py`，最初以 `6f3d97855613e9b8ff78df5850652180e083ea76` 为开发基线。模块仅使用标准库与 SQLite，无 Flask、外站、worker、文件读取或自动应用注册。核心和手动库存 HTTP 接口现已由应用工厂显式接入并部署，最近的售后待办发布与独立审计见[发布验收](INVENTORY-FOLLOWUP-ACCEPTANCE.md#inventory-followup-release)。订单来源解析与 HTTP 预览/确认仍需独立模块接入和验收，不能由手动库存已上线推出。核心不会修改购物 `done/actual`、财务记录、预算、公共余额或旅行 `paid`。

第一版确定边界：整数数量、单一明确单位；物品默认本人私密，明确共享后另一成员可做实物动作，owner 管 ACL；手动位置与保修日期；每订单行最多一个活动批次、批次可分次收货。文本 quantityText 不自动转数值，同名不合并，付款不等于收货，退款不等于退货。

## 认证和事务前提

调用者须先选对当前家庭的数据库，在同一个 `BEGIN IMMEDIATE` 事务内通过真实 `member_sessions.current(con)` 核验 owner/auth_version/household/当前会话；读操作至少 `BEGIN`。`actor` 是已核验的本户用户 ID，不是凭据，传入 `member1` 本身不证明登录。TV 必须由 HTTP 层显式拒绝。核心只验证 actor 确实在该库 users 中、连接已在事务、foreign_keys=ON，再执行 ACL 和 CAS；它无法鉴别传入 ID 是否来自真实 Cookie，也无法只凭本户重复用户 ID 确认家庭。

每个写 helper 自建 savepoint，失败回滚本次变化，不结束外层事务；成功也不 commit。外层必须将 session 验证、预览依赖、用户明确确认、核心写入、审计与 settings.meta 更新一起提交；任一步失败回滚。HTTP 层只在 replayed=false 时新增审计。核心使用空 UPDATE 确认 SQLite 写锁，即使调用者误用 deferred transaction 也在读取业务状态前取得写预约；Python 无公开接口辨别 BEGIN 的具体模式，不能声称核心检验了 SQL 文本。并发锁失败返回 busy，不自动重发。

```python
con.execute('BEGIN IMMEDIATE')
try:
    actor = authenticated_current_household_member(con)  # C 层实现，不能用请求 owner 替代
    result = inventory_core.append_movement(
        con, actor, acquisition_id, item_revision, acquisition_revision,
        {'kind': 'receive', 'quantity': 2, 'occurredOn': '2026-09-16', 'reason': ''},
        request_id,
    )
    if not result['replayed']:
        audit('inventory.receive', result['movementId'])
    con.commit()
except BaseException:
    con.rollback()
    raise
```

示例的 `authenticated_current_household_member` 不是现有公共函数。C 还须检查 JSON/CSRF/Origin、token 的本人会话绑定、confirmReceived/confirmReturned/confirmCorrection 等明确用户确认；这些 HTTP 字段不传进核心的严格 data。

## 显式初始化与五表

`SCHEMA_SQL` 是精确 DDL，只有调用 `initialize_inventory(con)` 才执行。初始化要求 foreign_keys=ON、没有已有事务，users(id PK) 与 entities(id PK,kind,revision) 已存在。成功独立提交；已有完整同结构返回，部分表、缺索引或 DDL 漂移拒绝而不修复。后续迁移应在已冻结旧 schema 的副本上执行同一 DDL 和数据保持校验，不依赖 app 启动碰巧建表；并发初始化冲突可由维护者重新读取后再调用，不在此自动迁移。

| 表 | 字段 / 约束 |
|---|---|
| inventory_items | id 24 hex PK，owner→users，不可改；visibility private/shared；title≤100、variant≤200、unit≤20、location≤100；reorder_point 可空非负整数≤1000000；revision、created_at、updated_at、deleted_at。首次事件后 unit 不可改；tombstone 不复活 |
| inventory_acquisitions | id，item_id→items RESTRICT，created_by→users，shopping_id→entities SET NULL；kind purchase/opening；ordered_qty 1..1000000 整数；order_state planned/ordered/in_transit/closed/cancelled；ordered_on/expected_on/warranty_until 可空合法日期；after_sales_state none/open/closed；note≤500；revision/时间/tombstone。id/item/creator/kind 不可改 |
| inventory_movements | id，item_id/acquisition_id，actor，kind receive/consume/dispose/return/adjust/reverse，非零 delta_qty（绝对值≤1000000），occurred_on，reason≤300，reverses_id UNIQUE，request_id，created_at；UNIQUE(actor,request_id)。禁止 UPDATE/DELETE；反转只能引用同批次同条目的非反转事件，delta 必须精确相反 |
| inventory_source_links | id，owner→users，acquisition_id，order_id、line_key、source_digest(64 hex)、source_revision、settlement_id 可空、status active/detached、revision/时间。活动唯一(owner,order_id,line_key)，同批次最多一个活动来源；owner 必须是 purchase 批次 creator。不可改 id/owner/acquisition 或物理删除。仅有 schema，本模块不创建/解析金融来源 |
| inventory_operations | id，actor→users，request_id，payload_digest，operation，item_id/acquisition_id，result 白名单 JSON，created_at；UNIQUE(actor,request_id)，禁止 UPDATE/DELETE。保留所有幂等回执，不因对象删除或达到容量清除 |

数量 SQL CHECK 强制 SQLite integer，Python API 额外拒绝 bool（SQLite 参数 bool 会变成1，SQL无法还原原 Python 类型）。日期检查包括实际日历日期；SQL 与核心都保护负批次库存、超收、反转配对、采购 kind 和关键不可变字段。触发器不替代当前会话认证；B/C 不得绕过核心直接改 movement、operation、item 或 acquisition 并声称已做 ACL/CAS。

每户硬上限含所有 tombstone/历史：items 5000、acquisitions 20000、movements 100000、source_links 20000、operations 100000。Python 写 helper 与 SQL 插入触发器双重限制；此版本无删除回执/裁剪历史通道。各批次 onHandQty≤1000000，跨批条目总数按 SQLite 整数相加，在上述记录数上限下仍低于 JavaScript 安全整数；不把某条目同名的别处库存算入。

自动删除原采购时，FK 清空 shopping_id，触发器提升批次和物品 revision，并更新时间；保持数量、事件、来源历史。手工更新关联自身显式提升两级 revision，不重复触发。删除库存采用 archive_item，须所有批次 closed/cancelled 且存量为0；不删除批次、事件、操作或金融记录。当前核心没有独立 archive_acquisition API。

## 公共函数与字段

`InventoryError` 含固定 `code` 和中文文本，写路径丢弃原异常上下文/原因，不输出输入或 SQL。错误码：invalid、transaction_required、not_found、forbidden、conflict、gone、quantity、capacity、request_conflict、schema、busy、storage。HTTP 状态映射由 C 负责；建议 invalid400、not_found404、forbidden403、gone410、conflict/quantity/capacity/request_conflict409，transaction_required 是调用/认证前提失败，不能把核心仅查 users 的成功当认证成功。

`normalize_item(data, previous=None)`：新建必填 title/unit；允许 title/variant/unit/location/visibility/reorderPoint。默认 variant/location=''、visibility='private'、reorderPoint=null。previous 必须是调用者已读到的规范业务字段，不是任意输入；未知字段拒绝，字符串去首尾空格，拒绝 Unicode 控制字符。金额/owner/数量总值都不允许。

`normalize_acquisition(data, previous=None)`：新建必填 orderedQty；允许 kind/shoppingId/orderedQty/orderState/orderedOn/expectedOn/warrantyUntil/afterSalesState/note。默认 purchase、planned、空日期/关联、none、空备注。opening 必须明确 orderState='closed'、shoppingId/orderedOn/expectedOn 都为 null。创建 opening 不自动增库存；用户随后明确收录已有数量。日期为合法 YYYY-MM-DD 或 null，expectedOn 不能早于 orderedOn，不根据日期推状态。

所有写函数的 request_id 都是32–64小写hex。`revision/item_revision` 是严格1..2^53−1整数。返回最小操作结果（ID/版本/变动数量），不是当前对象全部状态；需另行读取投影。

| 函数签名 | 权限与效果 |
|---|---|
| create_item(con, actor, data, request_id) | owner=当前 actor；返回 itemId/itemRevision=1/replayed |
| update_item(con, actor, item_id, revision, patch, request_id) | 仅 owner，CAS；patch 仅 ITEM_FIELDS，不能改身份/总量。返回新版 itemRevision |
| archive_item(con, actor, item_id, revision, request_id) | 仅 owner；检查无存量/未关闭批次；返回 deleted=true，保留历史 |
| create_acquisition(con, actor, item_id, item_revision, data, request_id) | 私密本人或共享成员；creator=actor；验证采购存在且kind=shopping；提升 item revision。返回 itemId/itemRevision/acquisitionId/acquisitionRevision=1 |
| update_acquisition(con, actor, acquisition_id, item_revision, revision, patch, request_id) | 双 CAS；owner 或批次 creator 可改业务字段，另一共享成员仅 orderState/expectedOn/afterSalesState/note。kind始终不可改，orderedQty不得小于已收事实。提升两级revision |
| append_movement(con, actor, acquisition_id, item_revision, revision, data, request_id) | data严格为kind/quantity/occurredOn/可选reason；receive/consume/dispose/return的quantity正整数；adjust有符号非零；除receive外reason必填非空。所有动作都显式选批次，双CAS后追加事件，提升两级revision |
| reverse_movement(con, actor, acquisition_id, movement_id, item_revision, revision, data, request_id) | data只含occurredOn/reason；原事件不能是reverse或已反转，不能跨批次；结果 quantityDelta 与原事件相反，保留原事件，双CAS |
| quantity_summary(con, actor, item_id) | ACL后返回 onHandQty/inTransitQty/plannedQty；不提供财务估值 |
| project_item(con, actor, item_id) | 显式安全白名单投影与 canRead/canMutate/canManage；无私人来源 |
| project_acquisition(con, actor, acquisition_id) | 继承条目ACL，白名单批次/数量投影；无order/payment/lineKey/digest/settlement。canManageSources仅表示该成员是creator，不代表来源授权已验证 |
| get_operation(con, actor, request_id) | 仅本人的回执，重新验证当前条目ACL；删除 gone，撤回共享 not_found。不会重建或返回旧共享详情 |
| export_inventory(con, actor, include_shared=False) | 返回 personal/shared/sources/operations 四数组；只导出可见未删库存、白名单事件、当前本人来源业务关联与本人操作元数据。include_shared必须bool |

数量定义：receivedQty=累计receive加其有效反转；return不减少 receivedQty、不重开待收。returnedQty=累计return减其反转。onHandQty=该批全部delta之和，不负。closed/cancelled剩余期待量为0，其他状态 remainingExpectedQty=max(orderedQty−receivedQty,0)。purchase closed/cancelled拒绝新增receive，但可消费、退货、明确更正；opening可明确补录到orderedQty上限。库存调整不改receivedQty，也不制造付款/退款。

fulfillmentState 根据receivedQty 为 unreceived/partial/received。只有 ordered/in_transit 的剩余期待量计入 inTransitQty，planned单独返回，不能被当成已下单。belowThreshold 是 onHandQty+inTransitQty<reorderPoint，null阈值为false；仅作建议，零后台动作。

合成公开投影示例：

```json
{
  "id":"111111111111111111111111","owner":"member1","visibility":"shared",
  "title":"电池","variant":"AA","unit":"节","location":"住处 A",
  "revision":4,"onHandQty":4,"inTransitQty":2,"plannedQty":0,
  "reorderPoint":2,"belowThreshold":false,
  "canRead":true,"canMutate":true,"canManage":false,
  "createdAt":"2026-09-16T08:00:00.000000+00:00","updatedAt":"2026-09-16T08:10:00.000000+00:00"
}
```

批次投影另有 id/itemId/shoppingId/kind/orderedQty/orderState/orderedOn/expectedOn/warrantyUntil/afterSalesState/note/revision/canMutate/canManageSources/createdAt/updatedAt，加 onHandQty/receivedQty/returnedQty/remainingExpectedQty/fulfillmentState。没有无界嵌套列表；C 实现有界列表、cursor/filter，并先做ACL再count/filter，不直接把私有SELECT结果jsonify。

## B/C 的回执接缝

```text
apply_with_receipt(con, actor, request_id, operation, payload, action,
                   *, item_id, item_revision,
                   acquisition_id=None, acquisition_revision=None)
```

只允许 operation 为 attach_source/detach_source/create_replenishment/create_followup。这是**内部可信代码回调**，不是接受客户端函数或执行模型指令的接口。核心先验证 item ACL/CAS，提供 acquisition 时验证同 item、ACL/CAS；source操作必须提供批次且 actor=creator。然后在savepoint中执行action。B负责订单/行/实际source ownership与revision/digest、settlement同购物关联验证；C负责用户确认和其他实体依赖。回调不得commit/rollback、修改连接配置、另启事务或做网络/文件I/O。

action结果必有 itemId/itemRevision；提供批次则必须带相同 acquisitionId及实际新 acquisitionRevision。允许另有 movementId/quantityDelta/deleted/entityId/sourceLinkId/sourceRevision；ID都是24hex、revision严格整数、deleted严格bool。核心拒绝任何原订单内容、金融字段或其他未知返回字段，复核结果指向原目标及其真实当前revision；失败回滚callback和本次回执。callback自己创建本地task/shopping时应由C调用注入的原实体validator并同事务写入，不走可能自动选择云清单的普通 tasks POST。

source_links的订单外键故意不绑定hub_transactions：来源删除不会删库存历史。来源缺失/变化需要B派生状态，本核心不会查询金融表。source insert的SQL触发器校验purchase批次creator和当前库存可见性；SQL不能检查金融owner，因为那是B职责。B必须使用此事务接缝，不以触发器代替当前session与账本授权。每行唯一约束基于B生成的稳定line_key；本模块不判断sourceLine是否稳定或quantityText含义。

幂等摘要包含operation、所有目标/期望revision及payload（最多16384 UTF-8字节）。同actor/requestId同内容成功后重试先读旧回执，再检查可变依赖；不同内容request_conflict。当前认证和当前条目ACL始终先满足，删除或撤回共享后不能靠历史回执重放。成功结果的revision是当时结果，不保证当前版本；token过期后的恢复由C的get_operation接口读回。失败没有回执，允许修正重试；未知结果必须先按原requestId查回。回执不含token、Cookie、session上下文或原输入正文。

导出不含请求ID、payload/source digest、line_key或数据库原result。本人sources可含orderId/settlementId，绝不进入shared数组；source已关联的条目不在当前导出可见范围时也不导出。TV与另一家庭须在外层先拒绝。整库备份保留tombstone与所有回执，与个人导出用途不同。

## 核心模块验证与应用验收边界

专项使用两户独立临时SQLite、本地多连接线程、合成购物/金融哨兵：整数/bool/字段/日期/SQL约束，分次收货、超收、负库存、退货与反转，双方共享实物操作/owner管理/撤回，来源唯一与私有导出，采购FK自动解绑双revision，幂等重放/冲突/tombstone不复活，事务失败回滚、持久重启、两连接同revision仅一方成功以及同requestId只一事件。原始失败与最终日志/JUnit在ignored test-results/inventory-core保存。

上述历史结果只证明核心存储行为，不证明 HTTP/session/CSRF、浏览器或生产。应用接入、当前会话、导出和发布的后续证据分别见[库存接口](INVENTORY-API.md)、[采购关联库存验收](SHOPPING-INVENTORY-ACCEPTANCE.md#shopping-inventory-release)和[售后待办验收](INVENTORY-FOLLOWUP-ACCEPTANCE.md#inventory-followup-release)。当前已部署家庭库为 61 张业务表、平台库为 9 张业务表；新模块仍须检查实际 schema，不可把历史“增加五表”当作下一次迁移指令。真实订单来源、本人实际操作和实体设备按各自验收记录判断。
