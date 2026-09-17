# Expo 旅行 JSON 导入：首批实现契约

状态：只读勘察后的候选方案，基于 `f6da7584809e79891b2a21896fa4fc3fb54e51b3`；尚未实现或验收。
本批只完成「文件／粘贴 → 新旅行预览 → 明确保存 → 当前详情」，不覆盖已有旅行、代订行程或写云日历。

## 现有能力与缺口

- [经典 journey-ui.js](../static/journey-ui.js) 的 `readImportFile/importPlan` 支持 JSON 文件与粘贴、直接计划或 `{plan: ...}`。
  文件上限 200,000 字节，粘贴上限 200,000 字符；调用现有 preview 归一化后回编辑器，再预览／确认。
- [journey_workflows.py](../journey_workflows.py) 已负责 v1／v2、成员、整数分、日期／时区、清单默认值、签名预览与事务幂等。
  缺省准备清单会生成模板，`[]` 明确不生成；省略分段与空分段也不同，导入不得提前补成空数组。
- [TripsScreen](../frontend/src/screens/TripsScreen.tsx) 有新建、预览、确认与当前详情，但没有文件／粘贴入口。
  [trips.ts](../frontend/src/lib/trips.ts) 的 `initialPlanningDraft` 仅接受 v1 助理草案，不能用它转换 v2 或携带导入回执。
- [journeySegments.ts](../frontend/src/lib/journeySegments.ts) 的 `readPlan(raw,true)` 可读归一化 v1／v2，身份围栏和固定路径请求可复用。
  其 `readSegmentPreview`、`SegmentIntent` 面向已有 v2 编辑；新建不得伪造目标 ID／版本以套用它们。

## 最少用户步骤

1. 「更多 → 旅行计划 → 导入旅行」：选择 JSON 文件或粘贴；可下载现有虚构 v1／v2 示例查看格式。
2. 点「预览导入」：展示服务端采用的日期、成员、预算、城市、准备／采购与各分段内容、将新增的数量和警告。
   v2 明示当地时间与时区、住宿未知时刻、全天结束日及人工预订状态；不是只显示“读取成功”。
3. 核对后点「确认创建旅行」；成功后打开重新读取的旅行详情。需改内容时返回输入，旧预览立即作废。

首批不增加第二套可编辑分段表单；改原 JSON 后重新预览，保存后沿已发布「行程分段」编辑。
当前编辑／保存／未知结果期间禁重复确认及离开；未提交草稿只需明确放弃，不让用户处理技术凭证。
沿 Paper 浅深色、密度与 44px 控件；长清单可展开／分页，不截断重要字段，错误、空态和离线均有出口。

## 输入与复用边界

- 复用 [FinanceSourceImportPanel](../frontend/src/components/FinanceSourceImportPanel.tsx) 的 Web 隐藏 input、FileReader 中止与 epoch 模式；
  使用独立旅行限额，文件及粘贴统一最多 200,000 UTF-8 字节、非空，容许开头 BOM，非法编码／JSON明确拒绝，不自动修补。
- 只提取计划对象；拒绝输入指定已有旅行／实体目标、实体版本、预览令牌、幂等键、冲突决策或发布选项，最终预览请求严格为 `{plan}`。
  外层导出包装不成为请求上下文；内容及说明都当数据，不执行 HTML、脚本、链接或文件内指令。
- 保留稳定 key、CNY 整数分、采购预算 `null`／0、当前家庭成员、日期和 v2 类型；不计算汇率／UTC／DST，不猜时刻或预订状态。
  原始输入只做有界 JSON／结构检查；服务端归一化后才使用 `readPlan`，不能因合法省略字段而提前拒绝。
  v1 缺省版本合法；最多 20 个目的地，各准备／采购／分段集合最多 100 项，重复 key 与非法 owner 由现有接口拒绝。
- GET templates 核对 `supportedSchemaVersions`；不支持 v2 则保留原输入并明确拒绝，不降级。
  `editSourceSnapshot` 是已有旅行编辑保护；本批新建不发送虚构 `expectedEntities`。
- 现有同源示例 `/static/examples/journey-plan-v1.json`、`journey-plan-v2.json` 保持原件；无上传云端、OCR、AI 抽取或新依赖。

## 既有 API 与结果语义

| 请求 | 本批用途／约束 |
|---|---|
| GET `/api/me`、`/api/journeys/templates` | 每次业务前后核完整身份；读取能力，无业务写入 |
| POST `/api/journeys/preview` `{plan}` | 只校验／生成预览；读取归一化 plan、summary、canApply、previewToken、expiresIn |
| POST `/api/journeys/apply` `{previewToken,idempotencyKey}` | 用户明确确认后发送一次；安全随机 key 与原 token 固定；新建成功通常 201，原请求重放 200 |
| GET `/api/journeys/operations/<key>` | 本人历史回执；200 为 `{found:true,idempotencyKey,result}`，404 `operation_not_found` 仅表示当前未查到 |
| GET `/api/journeys/<id>`、`/api/journeys` | 保存／恢复后读当前详情；必要时只读核对旅行列表，历史回执不装作当前状态 |

薄 DTO reader 校验预览与新建回执；apply 有 `replayed`，operations 的存储 `result` 没有该字段，不混用强制要求它的 reader。
普通新建预览有效期 1800 秒；**过期 apply 会在查询旧回执前返回 409**，不同于 reschedule 的过期重放规则。
因此已经未知的保存不能因后来 400／409 或回执 404 就清除原 key、换 token 再创建。
无未知写入时，明确拒绝或预览过期可保留输入重新预览；DST 400 显示服务端 field／choices，用户修正原字段后再预览。
若提供偏移选择按钮，只应用服务器返回且仍绑定当前输入的 choice；不根据浏览器时区选默认值。

## 身份、导航与失败恢复

- 每次 `/me → 业务 → /me` 比较 role、household、member、authVersion、CSRF，写入用当前核验的 CSRF；电视不可进入。
  复用现有围栏／请求工具，保持同源、no-store、拒重定向、超时及结果大小上限；需要列表路径时只作明确白名单扩展。
- 文件读取、解析、预览、确认都带 epoch 与最新回调；换输入即废弃旧预览，旧文件／网络成功和错误都不得覆盖新草稿。
- hidden／blur／offline／pagehide 隐藏内容并中止异步；同一完整身份仅内存保留草稿／未知意图，回来先重新核验再展示。
  身份变化清空私有输入、预览及写入载荷；最多保留按家庭＋本人隔离的原操作编号，供该本人新会话只读查询，不自动重发。
- 只有实际尝试 apply 时才进入未知保护；确认前 `/me` 失败保留输入并可明确重试，不伪装成未知写入。
  网络／5xx／畸形成功结果先查原 operations；仍持有有效原请求时可明确重试同一 body，绝不自动 POST。
- 读到历史回执后再 GET 当前详情；已确认保存后的详情读取失败只提供「重新读取旅行」，不重新 apply 或恢复旧可操作预览。
- 若原请求无法再用、回执仍未找到，先 fresh `/me`＋列表＋原 operations＋`/me`；明确说明原请求仍可能完成。
  允许用户明确「结束本次核对」并保留可复制编号，不宣称失败；另建旅行可能重复，必须由用户独立重新输入并确认。
- dirty／busy／unknown 经 `onPendingChange` 报 root 独立导航锁，覆盖文件读取；明确退出才释放，旧回调不得清新面板的锁。
  不用 localStorage、URL、日志或共享 provider 存私人 JSON；关闭浏览器不保证草稿恢复，也不能撤回已发请求。

## 预定文件所有权

| 作者边界 | 最小变更 |
|---|---|
| 模型／界面 | 新 `lib/tripImport.ts`、`components/TripImportPanel.tsx`；复用计划 reader、请求与 Paper，不复制后端规范化 |
| root 接线 | TripsScreen 列表入口／保存后 fresh 打开；types、HouseholdApp 的独立 pending 回调及必要嵌套导航保留 |
| 契约 | `TripImportPanel({onBack,onSaved,onPendingChange?})`；onSaved 只传校验后的 `{journeyId,tripId}`，不传私人详情快照 |
| 验证／文档 | 新 Node 真实 DTO 测试、独立真实浏览器 harness 与使用说明；经典、后端、schema、依赖保持 |

## 最少必要验收

1. 真实临时 Flask／SQLite：v1／v2 文件和粘贴、合法省略／空数组、CNY 整数分及采购预算 null／0、默认值与 stable key 归一化一致。
2. 超大／空／坏编码／畸形 JSON、外部目标／令牌、非法成员／日期／时区被拒；预览不创建旅行，DST选择不猜测。
3. 真实 UI 导入两版本，预览完整关键字段；确认只建一份旅行及关联事项，刷新／重启可读，返回详情可进入分段编辑。
4. 真提交丢响应、未送达、双击、原 token 重试、过期后 GET 回执、404 仍未知、明确结束及保存后 GET 失败分别核对写入次数。
5. 迟到文件／预览、改输入、离线／窗口失焦／隐藏、换成员／家庭、TV拒绝、导航锁与明确放弃；不泄露或复活旧内容。
6. 320／390／1280／1920、浅深色、长中文、键盘与新控件 44px；先源码审查，再冻结组合 types／构建／真实浏览器。

本轮只读写下此契约，未执行上述测试、构建、云端操作或部署；原 A–D 文档草稿保持独立。
