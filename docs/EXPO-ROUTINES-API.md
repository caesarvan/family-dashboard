# Expo 例行计划客户端契约

本轮独立开发候选，基线 `e4499b88b89124f19fd6eb040435d133bdfffc7d`；未部署。复用 [ROUTINES](ROUTINES.md) 的共享规则、当前事项、worker 与三张现有表，不增加 schema、云写入或新调度器。

## 读取、预览与确认

`GET /api/routines/context` 保留原 DTO：分页 40，聚焦 planId 可另加一项；每条 plan 有 `id/revision/state/status/kind/template/schedule/createdBy/createdAt/updatedAt/current/nextDates/history`。计划 ID 当前生成 32 位小写十六进制，原接口仍接受最长 100 字符的字母、数字、下划线、连字符 ID。当前／历史 occurrence 为 `{index,scheduledOn,entityId,state,entity}`，历史最多十项；实体 ID 为 24 位小写十六进制。当前项可缺失，不能自动复活。

`template.owner` 仅分工，允许 shared 或本户真实成员；计划本身对双方共享且均可管理，不是私有资产。采购预算为整数分或 null，0 表示明确零；每期不复制实付、图片或私人来源。日期计算与月末规则只由服务器提供。

`POST /preview` 原操作请求不变，新增响应 `operationKey`（64 位小写十六进制）。客户端须同时保留服务器返回的完整 previewToken 与 operationKey，不能自己构造、改写签名或把普通草稿摘要当回执编号。预览零业务写入，600 秒时效仍约束首次写入。

`POST /confirm` 仍只接收 `{previewToken}`；成功为 `{operation,plan,generated,replayed,operationKey}`。generated 为 null 或 `{id,kind,revision,scheduledOn}`。历史回放即使预览已过期仍返回原 plan／generated，仅补 operationKey 并标记 replayed:true；应再 GET context 获取当前计划，不用历史快照覆盖现状。

## 精确历史读回与未知结果

`GET /api/routines/operations/<operationKey>` 的成功完整形状：

```json
{
  "found": true,
  "operationKey": "64位小写十六进制",
  "operation": "create",
  "planId": "原计划ID",
  "revision": 2,
  "generated": {"id": "原实体ID", "kind": "tasks", "revision": 1, "scheduledOn": "2028-01-31"},
  "createdAt": "2028-01-01T00:00:00+00:00"
}
```

仅发起成员本人、当前户的有效会话可读取；成员重新登录后也可读自己的历史摘要。响应不包含完整 plan／模板／会话／签名，禁止缓存。既有回执无需改写，读取不生成事项、不延长 token。

- GET 404 `{error,code:"routine_receipt_not_found"}` 只表示暂未找到；不得宣称未执行、自动换 token 或新建计划。
- confirm 在写锁内先核身份与签名上下文、查既有回执，再检查首次写入时效。过期且锁内无回执才返回 410 `{error,code:"preview_expired_unapplied"}`，允许保留草稿重新预览。已经执行的旧 token 不走此分支，删除／归档／worker 推进后也不复活旧事项。
- 首次请求的明确 400／403／409 等拒绝不等于另一条已丢响应请求的回执。未知状态优先查原 operationKey；需要明确重试时保持原 token，不自动重发。
- 401、身份变化、超时和非法成功响应不得当成成功或确认未写。客户端须前后 fresh `/me` 核完整成员／户／CSRF／角色／auth_version；后台、离线、迟到响应隐藏资料与失效结果，保留同身份原意图和导航保护。

## 会话及事务边界

服务端核当前 MemberSessions.current 与请求捕获的真实 session ID；context／preview／receipt 释放 SQLite 读快照后复核，旧 Cookie 解析可能产生的隐式事务随后 rollback。确认持有 BEGIN IMMEDIATE，完成 audit 后、commit 前再次复核；撤权等待写锁时、新有效期或认证版本变化均按真实数据库处理。不声称可撤回已经发送的响应字节。

## 专项验证

[新增专项](../tests/test_routine_sessions.py) 使用临时 Flask／SQLite、真实两连接锁竞争与真实 session 撤销；覆盖过期历史读回、锁后时效、本人／伙伴／跨户／电视、旧 Cookie、读取快照撤权、提交前到期、audit rollback、删除／归档后回放不复活。与 [原规则专项](../tests/test_household_routines.py)、[跨模块专项](../tests/test_routine_journeys.py) 联合运行；实际计数与报告随固定提交交付，不将测试源码存在当成已通过。真实云、本人计划与实体设备不在本候选范围。
