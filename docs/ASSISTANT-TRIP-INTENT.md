# 已有旅行改期：规划适配器合同

状态：独立适配器候选，尚未接入产品路由或界面。它识别「把冰岛旅行推迟三天」「把冰岛旅行改到10月8日」中的已有旅行修改意图，返回待核对的日期建议。不会创建旅行简报、写数据库、调用云服务或生成执行令牌。

## 现有调用关系与接线边界

目前 `frontend/src/lib/assistantJourney.ts:isJourneyRequest` 会将含旅行／行程的非搜索请求导入新旅行简报；`home_assistant.py:model_journey_brief` 通过 `_model_json(config,payload)` 调用已配置服务。后续接线应在新简报之前识别已有旅行改期，保持显式「搜索／查找／找一下」优先；未找到修改目标也不能退回创建新旅行。

原改期流程完整保留：

1. 当前成员取得 `/api/journeys/<journeyId>/reschedule` 的新快照，核对当前旅行及版本。
2. 用户决定哪些当前允许的关联事项要联动；时区、夏令时、已预订／固定日期等仍由原引擎处理。
3. 调用原 `reschedule-preview`，使用真实 `snapshotToken`、建议的 `start/end`、用户选定的 `selectedKeys/timeOverrides`。
4. 展示原预览的差异／阻塞问题，由用户明确确认后调用原 `/api/journeys/apply`，复用其签名、CAS、幂等与原操作恢复。

本适配器的 `ready` 只表示日期建议可以进入上述读取／核对流程，不等同 `canApply`、授权或已经执行。它不生成快照、预览令牌、幂等标识、联动选项、HTTP 操作、外部消息或新执行引擎。

## 稳定 Python 接口

```python
project_trip_candidates(details, *, role, authorize) -> list[Candidate]
plan_existing_trip(prompt, candidates, *, selected_ref=None, model_output=None) -> Plan
decode_model_intent(raw, prompt, candidates) -> ModelIntent
model_trip_intent(config, prompt, candidates, *, invoke, selected_ref=None) -> Plan
```

`details` 只能来自服务端当前家庭的真实 journey detail；不能接收客户端提供的候选、权限位或模型对象。调用方在原成员／家庭会话守卫内提供 `role`，并实现 `authorize(detail)`，验证当前可修改范围。只有严格返回 `True` 的记录才会被读取与投影；失败关闭、电视拒绝。外层必须像现有 `home_assistant` 一样，在可能较慢的模型请求前后重新核对当前会话与候选来源。本纯函数不替代服务器权限控制。

候选只使用当前 `detail.trip` 的标题、起止日，不采用可能较旧的 `detail.plan` 标题或日期；时区从来源计划中提取，保留多时区及缺失／无效问题。

```ts
type Candidate = {
  ref: string; // trip_ + SHA256(journeyId) 的前24个小写十六进制字符
  journeyId: string; tripId: string; revision: number;
  title: string; start: string; end: string;
  timeZones: string[];
  sourceIssues: ('source_timezone_missing'|'source_timezone_invalid')[];
};
type Change = {
  kind: 'shift_days'|'start_date'|'unspecified';
  days: number|null; startDate: string|null; monthDay: string|null;
};
type Plan = {
  intent: 'reschedule_existing'|'other';
  status: 'ready'|'choose_trip'|'needs_input'|'not_found'|'not_applicable';
  mode: 'local'|'model'; candidates: Candidate[]; selected: Candidate|null;
  change: Change; missingFields: ('trip'|'dateChange'|'year')[]; issues: string[];
  draft: null|{journeyId:string; tripId:string; revision:number;
    start:string; end:string; calendarDays:true};
  requiresPreview: true;
};
```

`ref` 在候选排序变化时仍指向同一旅行；不是授权令牌，也不能代替 `journeyId` 的服务器鉴权。`selected_ref` 必须同时属于当前授权候选和原请求匹配的候选，否则抛出 `stale_selection` 或 `selection_mismatch`。重新获取来源时应保留用户原文，在明确展示新的日期建议后再进入原预览；不能把旧选择按序号映射到另一旅行。

默认最多 200 个授权候选。超过上限要求缩小范围，不静默截断。模型最多接收 20 个当前相关候选；候选标题搜索是有限本地文本匹配，不能宣称通用语义检索。一个具体名称恰好匹配一条时可给出建议；同名或多个匹配项保留 `choose_trip`，模型排序不能替用户选中。泛指「这个旅行」即使只剩一条也需明确选择。

## 日期、矛盾与时区

- 推迟／延后／延迟／后移为正日历天，提前／前移为负日历天。当前支持 1–366 的阿拉伯数字，以及一位和十位常用中文数字；未支持写法要求补充，不由模型猜测。
- 「改到2026-10-08」与「改到2026年10月8日」给出明确出发日，并保持当前旅行日历天数；「10月8日」保留 `monthDay: '10-08'` 和 `missingFields: ['year']`，不根据今天或原旅行年份推测。
- 日期范围与原引擎一致，为 2000–2100 年。相对首尾日期直接调用原 `journey_reschedule.shifted`；不以毫秒或 UTC 小时推移。跨年、闰日由原日历计算处理。
- 同时给出多个日期动作、互相矛盾的改期、否定、混合新增、只改返程或仅改某部分、指定时刻／时区，都保留问题且不输出可用 `draft`。重复同一动作不会被静默折叠为一次，也不会累计执行。
- 来源中的多时区保留；无效／缺少必须时区阻止日期建议。适配器不判断具体航班／活动时刻是否跨夏令时缺口或重叠：那是原改期预览的职责。测试明确验证日期建议能够交给原 `move_segment`，并由原引擎返回不存在的当地时刻问题。

`issues` 为固定代码，包含 `invalid_shift_days`、`invalid_start_date`、`multiple_date_instructions`、`conflicting_date_requests`、`negated_request`、`mixed_create_and_modify`、`alternative_request`、`ambiguous_shift_range`、`partial_change_requires_manual_review`、`time_or_timezone_requires_manual_review`、`model_intent_conflict`、`model_date_conflict`、`model_target_conflict`、`unchanged_dates`、`date_out_of_range` 及来源时区代码。UI 应据代码给出简明澄清，不能将 `not_found` 当作不存在这趟旅行或可以新建的证明。

## 实际模型适配

调用方仅在用户明确选择模型规划（例如 `useModel: true`）时，注入现有传输；界面说明会使用必要的旅行标题、日期、时区。此模块不另加确认字段或网络传输：

```python
result = model_trip_intent(app.config, original_prompt, current_candidates,
    selected_ref=selected_ref, invoke=home_assistant._model_json)
```

发送的 payload 仅为现有接口支持的 `instructions`、`input`、`max_output_tokens: 1800`。模型只看到用户本次文字，以及 `{ref,title,start,end,timeZones}`；不发送原对象、预算、备注、成员、家庭标识、真实对象 ID、配置或令牌。明确搜索即使被误传到模型包装器，也保留本地分流，不出网。没有提供方回退、重试或第二套网络实现；现有安全 `ModelProviderError` 原样交由外层处理。

模型 JSON 合同如下，拒绝额外字段、无效引用、写指令、对象 ID、令牌及错误日期结构。文本 JSON 解码还拒绝重复字段、非有限数字与非对象值。

```json
{
  "intent": "reschedule_existing",
  "targetText": "冰岛旅行",
  "change": {"kind":"shift_days","days":3,"startDate":null,"monthDay":null},
  "candidateRefs": ["trip_服务端提供的当前候选引用"]
}
```

`targetText` 必须逐字来自用户本次文字。模型可辅助从较长表达中定位目标名称，但不能使原来多候选的集合自动变成选中一条。日期必须与本地提取的明确原文完全一致；模型增补年份、天数或日期时返回冲突，不能进入预览。候选标题与用户文字以 JSON 数据传递，不能替换系统指令；模型即使受到其中提示注入影响，也不能输出适配器接受的任意写动作。此约束不声称模型语义理解不会出错，所以所有建议仍须原预览与本人确认。

多候选回选可以由外层短期签名票绑定原文、经过 `decode_model_intent` 校验的模型建议、当前来源摘要及会话身份。回选时重新读取授权候选并调用 `plan_existing_trip`，无需再次调用模型；来源变化应要求重新规划。外层来源版本应同时包含 workflow revision 与 live trip entity revision，而不是只比较本 DTO 的 workflow revision。进入原改期界面时重新获取真实快照，逐项核对 ID、版本、标题和原起止日，再初始化建议日期；联动项目仍从未选择状态开始。签票、来源摘要与 HTTP 状态属于接线分支，本模块不提供或声称已经实现。

## 本分支验证与剩余接线

`tests/test_assistant_trip_intent.py` 使用合成记录和模型输出，60 项通过。涵盖日期有／无年份、正负日历天、闰日与原 DST 阻塞、矛盾／否定／多动作（包括第二动作未提供可解析日期）、同名候选、已选引用与原请求一致、当前权限过滤、模型字段与引用限制、隐私投影、提示注入作为数据、提供方失败不回退及无网络。

本机系统 Python 没有 pytest；最终执行使用主项目既有 `.venv/Scripts/python.exe` 的依赖，在本独立 worktree 运行。本批未安装依赖、修改共享文件、增加表或调用真实模型。没有完成 Flask 路由、UI、完整端到端 AI 接入、真实用户旅行、云写入或生产发布；上述接线由独立分支实现和验收。该模块文件还需由集成人加入实际加载／Docker／发布白名单，不能只合入纯函数就宣称产品可用。
