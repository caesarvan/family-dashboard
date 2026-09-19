# 已有旅行改期建议 API

本接口读取当前家庭旅行，提供待核对日期建议。它不创建旅行、不保存改期、不调用日历发布或预订服务。只有原旅行改期引擎签发快照、预览与最终回执。`assistant_plans` 的待办/采购创建流程不变。

依赖 [旅行意图适配器](ASSISTANT-TRIP-INTENT.md)、[原旅行改期接口](JOURNEY-RESCHEDULE.md)、`home_assistant._model_json` 和真实 `ImportSession`。适配器须经过独立审查后由集成人组合；作者目录不能复制未审查的其他分支源码作为测试依据。

## 注册与文件职责

```python
from assistant_trip_change_api import register_assistant_trip_change
register_assistant_trip_change(app, db, Problem, body, require_member, limited)
```

在 `register_journeys` 和成员会话初始化之后注册。完整签名为 `register_assistant_trip_change(app, db, Problem, body, require_member, limited, *, invoke_model=None)`；可选 `invoke_model(config, payload)` 仅供依赖注入/合成测试，生产默认复用现有固定供应商 transport。本模块没有 DDL、初始化 SQL、持久化业务状态或数据迁移。`app.py`、Docker COPY、发布白名单和前端接线由各自责任人修改。

## POST /api/assistant/trip-change

成员会话、同源 JSON 和当前 `X-CSRF-Token` 必须有效；匿名 401，电视/跨来源/CSRF 失败沿用全局 403。拒绝未知字段和混用两种请求形状。

初次请求：

```json
{"prompt":"把东京旅行推迟三天","useModel":false}
```

- `prompt` 必填，去首尾空白后 1–2000 字符；适配器进一步拒绝无效控制字符。
- `useModel` 可省略，默认 `false`；必须为真正的布尔值。
- `useModel:true` 使用已经配置的供应商。界面说明本次文字及必要候选旅行标题、日期和时区将发送给 AI，不增加第二个上下文确认。搜索/待办/采购前缀和非改期请求不出网。
- 本地候选最多 200，模型上下文最多 20；超限明确拒绝，绝不截断成一个候选。模型超限可在需求中写明旅行名称；家庭总量超限时可从旅行列表进入原手工改期。
- 不接受客户端候选对象、model output、provider、URL、预览 token、`selectedKeys` 或时刻覆盖。

用户选择多候选之一：

```json
{"selectionToken":"<上一响应的选票>","selectedRef":"trip_<24位小写十六进制>"}
```

`selectionToken` 为 1–16000 字符；`selectedRef` 必须精确匹配当前候选引用。JSON HTTP 正文最多 24000 字节。回选不能同时提交新 prompt/useModel；修改需求应重新发起初次请求。回选只重放选票中的已验证建议，不再调用模型。

## 成功响应

HTTP 200，`Cache-Control: no-store`。其余领域字段见适配器合同；外层固定如下：

```typescript
type Source = {
  journeyId: string;     // 24位小写十六进制，工作流ID
  tripId: string;        // 24位小写十六进制，原旅行实体ID
  revision: number;      // 工作流版本，1..Number.MAX_SAFE_INTEGER
  tripRevision: number;  // 当前旅行实体版本，同上
  title: string;         // 当前实体标题
  start: string; end: string; // 原日期，YYYY-MM-DD，不是建议日期
  sourceVersion: string; // 64位小写SHA256，非执行权限凭据
};
type TripChange = {
  version: 1;
  intent: 'reschedule_existing' | 'other';
  status: 'ready' | 'choose_trip' | 'needs_input' | 'not_found' | 'not_applicable';
  mode: 'local' | 'model';
  candidates: Candidate[]; // 原适配器完整投影，0..200，无静默分页/截断
  selected: Candidate | null;
  change: Change;          // 原适配器日期意图
  missingFields: string[];
  issues: string[];
  draft: null | {
    journeyId: string; tripId: string; revision: number;
    start: string; end: string; calendarDays: true;
  };
  requiresPreview: true;
  source: Source | null;
  selectionToken: string | null;
  selectionExpiresIn: 600 | null;
};
```

`source` 与 `selected` 同时为 null 或指向同一候选。只有 `ready` 有 `draft`，其三个身份/版本字段与 `source`、`selected` 一致；建议日期仍只是当地日历日期。只有 `choose_trip` 返回选票和 600 秒期限，其他状态两者均为 null。`needs_input` 可以已有 selected/source，但不能有可执行草稿。无 `canApply`、`previewToken`、`snapshotToken`、自动联动选择或执行回执。

标题/原日期来自当前 `entities`，不从可能过期的工作流 plan 日期推断。来源摘要包含当前候选投影和旅行实体版本；工作流版本、旅行实体版本、标题、日期、时区或候选集合变化都会使旧选票失效。此保守失效也可能由另一趟旅行变化触发。

## 身份、选票和网络边界

使用当前家庭数据库中的 `journey_workflows → journey_links(item_key=trip) → entities(kind=trips)`。旅行属于家庭共享对象；`created_by` 只是来源信息，不构成本人专属权限。只查询当前家庭真实工作流，独立旧旅行实体不会被伪造成可改期工作流。

模型只接收本次需求及匹配候选的 `ref/title/start/end/timeZones`。实际 ID、预算、已付金额、备注、任务、采购、附件、私人地点、财务、账户和会话凭据均不作为模型上下文。用户自己输入的文字按本次 `useModel` 意图发送。

初读与响应读均采用 `ImportSession.read()`，释放 SQLite 快照后再重查身份。公开模型请求在事务外执行；成功或失败都先 `fresh()`，身份撤销优先于展示模型错误。返回之前重读候选并核对来源摘要；网络期间改动返回 409。

选票使用独立 `household-assistant-trip-selection-v1` 签名空间，期限 600 秒，绑定 actor、家庭、当前真实会话摘要、原 prompt、完整候选来源摘要以及经过严格 decode 的模型 advisory。它不是改期快照，也不能送往 `/journeys/apply`。每次回选重新读取实际会话与当前家庭候选，不能重放旧权限。签名选票可以包含原请求和已验证 advisory，客户端仅内存保留、原样回传，不展示技术 token、不记日志。

初次请求与原助理共用 `assistant_plan`：每 IP 每小时 30 次；回选使用 `assistant_trip_selection`：每 IP 每 10 分钟 60 次。`limited()` 自行提交，因此位于领域事务之外。身份元数据与限流计数可以更新，旅行、财务、审计、工作流和执行回执不因建议请求改变。

## 原改期流程接线

1. 助理输入先保留本地搜索前缀优先，再将已有旅行修改意图分流到本接口，最后才处理新旅行简报。
2. 多候选必须明确选择；缺年份、否定、冲突、部分修改或时间/时区不明确时显示缺失项，不自动补全。
3. 用户从 `ready` 建议进入原 `JourneyReschedulePanel`，实际读取 `GET /api/journeys/<journeyId>/reschedule`。比较 journeyId、revision、快照中 `key=trip` 的原标题和原 start/end，与 source 不符即保留建议并要求重新核对，不自动重算。
4. 现有快照 DTO 未暴露 tripId/tripRevision/sourceVersion，不能假装前端已经比较它们。上述实体版本已在建议响应前和回选服务端重查；进入原面板后，以新快照的签名来源保护后续全体实体/私人地点/日历绑定版本。
5. 比较一致后只一次性初始化新 start/end，`selectedKeys=[]`、`timeOverrides={}`，不覆盖之后用户输入。用户自行选择可联动事项。
6. 继续原 `POST /journeys/<id>/reschedule-preview`，显示原日期→新日期、保留项、采购无日期提示、固定/已订/已完成项目和 DST 阻塞。用户明确确认后才 `POST /journeys/apply`。
7. 未知保存结果保留原 previewToken/idempotencyKey，通过原 `/journeys/operations/<key>` 核对；不得重新生成改期来掩盖未知结果。云端状态仍由原界面另行核对。

## 错误

本模块错误为 `{error: 固定提示, code: string}`，不附带 provider body 或来源记录。原登录/CSRF/限流错误仍可只有 `error`。

| HTTP | code | 后续动作 |
|---|---|---|
| 400 | invalid_request / invalid_trip_intent | 核对输入 |
| 400 | invalid_selection / selection_mismatch | 保留需求，重新选择或整理 |
| 400 | candidate_limit / model_candidate_limit | 缩小名称范围或进入原手工改期 |
| 400 | selection_too_large | 精简需求 |
| 403 | selection_identity / access_denied | 隐藏内容，重新核对当前登录身份 |
| 409 | selection_expired / stale_source / stale_selection / invalid_candidate | 原建议已失效，重新读取并整理 |
| 413 | request_too_large | 精简请求 |
| 429 | 原限流错误 | 稍后重试，无模型调用 |
| 502 | invalid_model_output | 保留文字并提示未改期 |
| 502/503/504 | model_unavailable | 沿用现有供应商安全错误语义，无自动降级/换供应商 |

## 验证边界

`tests/test_assistant_trip_change_api.py` 使用真实 Flask 登录/CSRF、临时家庭 SQLite、真实签名和原改期快照/预览/保存/回执接口；仅供应商网络返回为合成。涵盖无业务写入、共享旅行与跨家庭隔离、会话撤销、网络期间版本变化、短期票/未知选择、隐私上下文、共用限流，以及实际改期一次和原回执重放。测试注册包装仅补齐作者基线尚无的新 app 接线，不替换认证或旅行业务实现。

实际测试结果须记录固定组合源码、运行命令和原始输出。未完成前端接线、浏览器完整流程和真实用户旅行验收之前，此模块不能宣称产品入口已可用或场景 A 已验收。
