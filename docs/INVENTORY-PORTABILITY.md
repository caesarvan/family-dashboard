# 家庭物品个人导出

个人 ZIP 导出接入 [库存核心](INVENTORY-MODEL.md) 的 `export_inventory` 安全投影，沿用 `/api/portability/summary` 与 `/api/portability/export`，不新增接口、表、依赖或后台任务。只导出当前成员在当前家庭可以读取的手工库存记录，没有金融订单导入、自动记账、库存恢复或生产迁移。

默认只包含本人物品。勾选“附带共同记录”才加入伙伴当前共享物品；本人已共享物品仍只在 personal 中出现一次。`summary.personal.inventoryItems` 是本人未归档物品数，`summary.shared.inventoryItems` 是伙伴当前共享且未归档的物品数；这些计数在同一个只读事务内重新验证当前成员会话。

## ZIP 字段

ZIP 保持原五个文件：`data.json`、`transactions.csv`、`investments.csv`、`README.txt`、`manifest.json`。库存不增加 CSV，不参与金额或财务汇总；manifest 仍记录各文件大小和 SHA-256。`data.json` 的 `coverage.inventory` 为 `manual_records`。

| JSON 路径 | 内容与范围 |
| --- | --- |
| `personal.inventory.items` | 本人物品，每项包含 `acquisitions` 批次与 `movements` 实物流水 |
| `personal.inventory.sources` | 仅本人、且关联本次选定可见物品的最小来源关联；伙伴共享物品上的本人批次来源只有勾选共同记录时才纳入 |
| `personal.inventory.operations` | 仅本人、且关联本次选定可见物品的最小操作摘要 |
| `shared.inventory.items` | 仅勾选共同记录时出现：伙伴当前共享物品、批次和实物流水；此对象没有 sources 或 operations |

固定字段白名单在 `data_portability.py`，不直接导出 SQLite 行或完整回执 JSON：

- 物品：id、owner、visibility、title、variant、unit、location、revision、onHandQty、inTransitQty、plannedQty、reorderPoint、belowThreshold、createdAt、updatedAt，以及 acquisitions／movements。
- 批次：id、itemId、shoppingId、kind、orderedQty、orderState、orderedOn、expectedOn、warrantyUntil、afterSalesState、note、revision、createdAt、updatedAt、onHandQty、receivedQty、returnedQty、remainingExpectedQty、fulfillmentState。
- 流水：id、acquisitionId、actor、kind、deltaQty、occurredOn、reason、reversesId、createdAt。共享实物流水允许呈现操作成员，不能由此读取其私人来源。
- 来源：id、acquisitionId、orderId、settlementId、status、revision。没有 line_key、source_digest、source_revision、原订单内容或伙伴来源。
- 操作：id、operation、itemId、acquisitionId、createdAt。没有 requestId、payload_digest、result 或授权上下文。

归档物品及其回执不会进入个人 ZIP，服务器整库备份仍保留历史。仅有批次/来源关联不证明已经付款、退款或收货；实物数量取核心投影。导出不会删除、更改库存或写入财务记录，只记录原有的个人导出审计。

## 压缩完成后的重新核对

初次读取使用原 `BEGIN` 快照。ZIP 完全压缩并关闭后，进入新的 `BEGIN IMMEDIATE`，通过原 `member_sessions.current` 再核对会话，保留既有媒体撤权验证，然后重新取得库存的相同固定字段投影并比较。共享撤回、删除/归档、版本或批次/流水/本人来源变化使整包返回 409 JSON，提示重新导出，不发送旧 ZIP。即使共享先撤回又重新打开，revision 变化也会被识别。未选择的伙伴内容变化不影响仅本人导出。

此比较也可能在新增可见物品或本人操作后要求重新导出，是保守的最新状态核对，不提供跨请求历史快照。最终检查与导出审计在同一写事务内提交；已交付的文件无法远程收回。会话在压缩期间退出时按原 current 门禁返回 401，错误路径释放导出并发槽位。原 64 MiB 未压缩总量限制、CSV 公式保护和 no-store 保持。

## 隔离验证

```powershell
python -B -m pytest tests/test_inventory_portability.py tests/test_data_portability.py tests/test_media_portability.py tests/test_member_session_portability.py -q
node --check static/data-portability.js
```

专项用真实临时工厂、成员 cookie、CSRF、API 与 SQLite 验证本人/伙伴/独立家庭范围、最小字段、归档排除；在真实 ZIP 关闭后改变共享、版本、批次、流水、来源或退出会话，确认不交付旧文件。来源尚无本候选 HTTP 写入流程，测试仅向已审 schema 填写合成本人来源以验证投影，不把它当作金融来源接入成功。没有生产、云账号、Docker 恢复或实体电视操作。

作者首轮 13 项库存专项与 12 项既有个人/照片/会话导出回归共 25 项通过。摘要改为直接计数、避免加载全部流水后，13 项库存专项再次全部通过；这不是 38 个独立用例。JavaScript 仅说明和计数文字变化，语法检查通过，未改下载授权或身份防护流程。JUnit 与日志保存在 ignored `test-results/inventory-portability/`。
