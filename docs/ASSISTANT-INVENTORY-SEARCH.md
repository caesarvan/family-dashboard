# 助理中的家庭物品搜索

在家庭助理输入「搜索：电池」或「查找：收纳盒」，结果包含当前成员自己的物品，以及同户伙伴明确共享的物品。点击结果进入既有「家庭物品」详情，可继续核对批次与实物记录。归档、撤回共享、跨家庭及电视访问沿用现有库存权限。

本增量只读本地数据，明确搜索即使勾选 AI 也不调用模型。不自动补货、下单、收货、共享或记账。库存名称与规格也不会加入自由表达规划的模型上下文。

## 接口

复用 `GET /api/assistant/search?q=...&limit=20&offset=0`。q 为去首尾空格后的 1～100 字；limit 1～30，offset 0～20000；重复或未知参数拒绝。原 `query/matches/total/limit/offset/nextOffset` 不变，全部种类统一按 kind、id 排序、统一计数和分页。

物品匹配 `title + ' ' + variant + ' ' + location` 的 Unicode casefold 字面子串。可按名称、规格或存放位置查找；`%`、`_` 只当普通文字。不搜索批次备注、购物/订单来源或操作回执。

```json
{
  "kind": "inventory",
  "id": "aaaaaaaaaaaaaaaaaaaaaaaa",
  "title": "充电电池",
  "variant": "5 号 · 低自放电",
  "location": "玄关抽屉",
  "unit": "节",
  "visibility": "private",
  "revision": 3,
  "onHandQty": 2,
  "inTransitQty": 2,
  "plannedQty": 3
}
```

请求捕获当前 browser generation、credential、owner 与 auth_version；同一家庭数据库读事务内再次核验真实成员、家庭和捕获上下文，再排除归档和无权限的候选。明确 `/plan` 搜索沿用该请求最初捕获的上下文。命中项调用 `inventory_core.project_item` 核验领域 ACL，然后只返回上面 11 个字段；不返回 owner、库存来源、金额、批次或回执。三个数量始终使用现有服务端投影：现有库存、已下单/运输中的剩余待收、尚未下单的计划量分别展示，不合并为一个可用数量。总量和分页同样只计算当前有权读取的结果。沿用搜索的短事务语义，每次翻页重新读取，不承诺跨请求快照。

搜索结果只代表本次读取时的快照；不能用它的 revision 或数量直接提交实物操作。打开条目后必须重新读取 `/api/inventory/items/:id`，并沿用详情中的当前版本与写入确认。撤共享后下一次搜索不返回该条目，原详情访问返回 404；归档为 410。响应 `Cache-Control: no-store`，电视全部拒绝。

`POST /api/assistant/plan` 的明确搜索复用同一查询，继续返回 `id:null/actions:[]/mode:local`，不把搜索结果写入 `assistant_plans`。现有模型、计划确认及库存写接口均不改变。

## 经典页前端接缝

- `ProductShell.openInventory(itemId)` 只接受 24 位小写十六进制 ID、真实成员和已加载的库存模块；沿用普通库存导航，因此原地图照片上下文会清除，不新增 URL 参数或存储。
- `InventoryUI.openItem(itemId)` 等待首次读取结束，复用原 `job/verify/details` 读当前物品及批次。可以直接打开不在库存第一页的物品；不从助理结果复制详情。
- 已有库存草稿需明确同意放弃才打开另一物品。进行中的请求或尚未核实的写入回执会阻止跳转，保留原 requestId 与载荷。拒绝放弃时仍停留原草稿。
- 读取完成前后使用现有 `/api/me` 与界面身份检查；失效会话、撤共享或归档时清除原详情，迟到的响应不能填入另一成员的页面。助理结果标题与规格按文本转义。

## 验证与限制

`tests/test_assistant_inventory_search.py` 使用临时 SQLite、真实应用工厂、成员 cookie、CSRF 与双户路由，覆盖安全投影、ACL、撤共享、归档、名称/规格/位置、字面匹配、分页、重启、电视拒绝、失效会话、browser generation 和模型隔离。真实采购批次收货/使用/退回/另设计划后核对三种数量，SQL authorizer 拒绝本次搜索读取金融、库存来源和库存回执，或在搜索读事务内写入；原购物实体和计数保持。浏览器专项使用真实本地 Flask/Edge 和正式 ProductShell/InventoryUI；不替代业务 API，竞态场景丢弃一次已提交的真实写响应，或在真实详情读出后登出再返回响应。

本轮以 `67614bf16d2a6649a4743462a3a4e6535e5c8a82` 为基线移植旧候选 `bf5f112` 并补充位置/数量与会话代次校验，保留原候选 refs。没有增加 schema、依赖、路由、模型或云调用。React Native 新界面由独立分支使用上述契约；本文件只说明后端和经典页接缝，不能以源码候选替代合入、组合浏览器、部署或用户实际库存验收。

Linux 纯后端可显式 `--deselect=tests/test_assistant_inventory_search.py::test_browser_real_inventory_navigation_and_fences`；这是环境范围声明，浏览器测试须在有 Edge 的 Windows 单独执行，不能记为 Linux 浏览器通过。

本轮 Windows 已执行：三个受影响模块 `test_home_assistant.py`、`test_assistant_inventory_search.py`、`test_inventory_api.py` 共 86 passed、1 显式 deselected（Edge节点）；该 Edge 节点单独 1 passed，七项真实经典页流程通过、页面错误和外站请求均 0。照片/地点搜索后端另跑 29 passed、1 明确 deselected（未在本轮重跑的历史来源浏览器），不能混算为一个全套或真实云端验收。此前测试因旧 URL glob 不匹配 `/classic#inventory` 失败；修正测试后重新通过，失败日志保留。
