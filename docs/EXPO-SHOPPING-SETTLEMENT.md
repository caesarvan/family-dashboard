# Expo 采购实付核对

当前状态：采购／本人交易入口与会话修订已于 **2026-09-18 08:03:15（北京时间）上线，08:04:16 正常 TLS 读回通过**。R2 浏览器 10/10 及限定视口视觉核查通过，Linux 实际 168 通过、1 项精确 Windows 跳过；独立只读发布审计通过。[集中验收记录](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md#expo-shopping-settlement-release)说明实际安装身份、失败历史与未验范围。下文作者阶段记录保留，不能作为当前进度。

## 使用流程

1. 从采购某项或本人交易进入「核对采购实付」。查找并选择本人有效的人民币消费付款和家庭采购；订单入口只列已核对关联的付款，没有付款时返回账本处理。
2. 输入整项实付，独立选择「已买到」。实付替换原金额，不累加；付款不证明收货。未知实付与明确零元分开。
3. 「预览共享变化」显示当前／确认后的金额与状态，勾选共享说明后「确认保存」。仅整项实付和已买到状态写入家庭采购，不共享付款标题、编号、商户或来源。
4. 保存后重新读取当前关联与采购，再通知父页面刷新。本人账本、月预算、公共余额及旅行已付款不重复变化。

「本人的关联记录」可更新原关联，或预览解除。解除可保留采购现值；明确选择恢复时，仅当版本与上次投影未变化才允许恢复。付款／退款或采购变化会显示重新核对原因，不自动回滚、推算退款或改完成状态。

搜索与分页沿原接口：付款、采购及关联分别分页，每类通常 40 项；定位记录另保留。某页未见记录不证明对象不存在。外币、收入、转账、重复记录或订单不能直接作为人民币实付来源。

## 组件与接线契约

`ShoppingSettlementPanel` 默认导出，props：

```ts
{
  shoppingId?: string;
  transactionId?: string;
  onClose: () => void;
  onSaved: (result: {
    shoppingId: string; linkId: string;
    operation: 'apply' | 'update' | 'revoke';
  }) => void | Promise<void>;
  onPendingChange?: (pending: boolean) => void;
}
```

采购入口传 `shoppingId`，账本可仅传 `transactionId`。目标参数只作为当前实例的初始定位；改变目标须先通过父导航保护，再使用新实例 key。未保存输入、预览、在途请求、未知结果和成功后未完成读取均上报 pending。父回调须绑定 actor、来源和当前面板，旧实例清理不得释放新面板的导航锁。

`onSaved` 仅在收到有效确认响应、前后身份复核与 fresh context 后调用；用于父刷新，不代表关闭。父刷新失败保留成功回执，按钮「重新读取当前资料」只重新 GET／刷新，不重发确认。onClose 为明确返回；有未保存输入时显示「放弃本次输入？」与「继续核对／放弃输入并返回」。

主要 testID：`shopping-settlement-panel`、`settlement-preview`、`settlement-unknown`、`settlement-current`。标签：`查找付款或采购`、`选择付款：标题`、`选择采购：标题`、`整项实付（元）`、`已买到`、`预览共享变化`、`我确认共享整项实付和已买到状态`、`确认保存`。更新／解除按钮的 accessible name 含关联 ID，显示文案不展示该技术字段。按钮至少 44px，复用 Paper 主题、密度与 SelectionRow 键盘行为；四宽、深浅色、主要动作 44px 与所列键盘行为已在 R2 本地浏览器验收；视觉限实际可见区域，详见[集中记录](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md)。

## 原接口与恢复边界

只使用 `/api/me` 和 [已有三接口](SHOPPING-SETTLEMENT.md)：

- GET `/api/finance-hub/shopping-settlements/context`：可选 `shoppingId/transactionId/linkId/q/page`，不发送 owner。
- POST `/preview`：`apply` 精确六字段，`update` 精确六字段，`revoke` 精确五字段；当前采购和关联版本取 fresh context。金额使用现有十进制 helper 与 BigInt 转换整数分，不浮点乘法，不在客户端重算退款或可分配额度。
- POST `/confirm`：仅 `{previewToken}`。凭据 600 秒且绑定原会话，过期／新会话可能在历史回执前拒绝；没有新操作编号或 GET operations 接口。

网络／5xx／无法验证响应或后验身份时保留原意图、锁定修改，只让用户明确读取 context。当前状态不是本次操作回执；不会自动或手动重发原确认。fresh 读成功后允许单次「结束本次核对」返回，不宣称原操作成功或失败，也不自动再预览。

原定位对象 404／410 清旧详情但不丢未知意图。用户可明确「读取当前可用资料」，读取本人 context 首页而不携失效定位；原意图不变，界面明确该列表不能证明原请求结果。前后身份通过后才允许结束核对。普通确定拒绝须同时通过后验 `/me`，保留输入并重新读取／预览；未知历史不能用普通拒绝码证明未写。

每次读写前后核对 role、家庭、成员、auth_version、CSRF；写入使用此次 fresh CSRF。blur、hidden、offline、pagehide、导航失焦与 unmount 丢弃迟到响应并清当前展示。相同身份的内存输入／未知意图暂时保留，前台重新核对后才显示；身份改变卸载清空，不使用 localStorage、URL 私有 DTO 或业务日志。

## 作者阶段验证（历史）

`tests/test_expo_shopping_settlement.mjs` 从同一固定后端源码，通过真实临时 Flask／SQLite 生成 context、预览、确认、更新、退款需复核、解绑、删除后解绑及分页 DTO；所有网络连接禁用，临时数据自动清理，额外 SQLite 连接显式关闭。随后 Node 测试覆盖严格读取、原目标与金额、精确载荷、后验会话、迟到响应、未知句柄绑定与有界传输。没有伪造成功业务响应；传输单测的畸形数据仅验证拒绝。

运行使用 `SETTLEMENT_TEST_PYTHON` 指定已安装主仓 Python，`node --experimental-transform-types --test tests/test_expo_shopping_settlement.mjs`。可用 `SETTLEMENT_BACKEND_ROOT` 显式指定另一个已经固定的组合后端；报告必须记录真实 source/hash，不能把旧 API 测试当作后续会话修订验证。

本次最终实际 13／13 Node 通过，原件 `test-results/settlement-ui-final-r2/result.json` SHA256 `4badd5bad804ecb903cfcbeeb211cf7c9c333c37806825913dc4c42b33cc5554`，TAP／Node 输出 SHA256 `61ec21a45c52550b839544228d9cc061bde78dcc76137091676ba55c915a91bb`。最终合同核对区分账本来源上限 10^14 分与采购分配上限 10^11 分，补真实最大来源 DTO 验证后运行本轮；此前 `settlement-ui-final` 原件保留。真实 DTO 使用本分支基线后端，不包括后续会话修订。

完整应用 92 个根文件、测试配置 1 个根文件的 strict 类型检查均为 0 diagnostics，最终原件在上述 `settlement-ui-final-r2`，同时绑定源码及输出 SHA。仅只读映射已安装的 mapping integration 物理依赖，没有安装或改配置。R1 Node 13 通过但类型检查有两个泛型推断错误；仅补泛型／字面量类型标注后类型 R2 已通过，最终金额边界修订后再次全量检查。各轮原件保留，不与最终数量相加。检查期间所列源码哈希前后相同；本段结果文字在检查后更新。

该作者阶段未构建、运行浏览器、访问云或生产；后续组合结果见页首。真实个人账单、实际设备、TV 显示及完整 A/B 场景仍未由本批合成验证覆盖。

## 审查修订：已移除对象的关联

`ba46ba6` 审查发现：已有关联的采购或来源付款移除后，旧查询同时携带该对象 ID 与 linkId 会收到 404，挡住本可执行的明确解除。现在面板与测试共用 `settlementReadQuery`；已有 draft link 或保存回执仅按 linkId 定位，原入口 focus 与未知意图不变。无 link 的新操作继续按原入口定位；只有用户明确读取当前可用资料才去掉全部定位。

真实临时 API 回归将该 helper 生成的 URL 实际送入 Flask，核两类删除后旧查询 404、新查询 200、needs_review 原因及明确解除，不以纯对象比较代替 HTTP。当前修订实际 14／14 Node，应用／测试 strict 均 0 diagnostics；原件 `test-results/settlement-link-focus-r1/result.json` SHA256 `6007fc3eeba0f19e8aa47a5d1d507769a0a0ff075c09848b3cc7c33f0ed6af48`，所列源码前后相同。此前 13 项与类型原件保留、不累加；本段检查后追加。该修订完成时，后端会话修订与实际组合浏览器仍待验证；后续结果见页首集中记录。
