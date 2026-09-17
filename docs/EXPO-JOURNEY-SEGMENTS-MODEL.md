# Expo 复杂行程客户端契约

客户端模型已接入新版分段页面并发布，实际证据见 [发布验收](EXPO-JOURNEY-SEGMENTS-ACCEPTANCE.md#expo-segments-release)。不新增 API、表、依赖，不改变普通旅行编辑或现有改期模块。若进入编辑前准备／采购已被单独删除、解除关联（包括实体 tripId／journeyId 与当前工作流不一致），或准备截止日已清空，现有完整计划 API 不能无损保留该差异，本模型明确拒绝编辑并提示先核对旅行清单，绝不重建或补回旧值。未来应通过部分更新协议改善，本批不改 apply。后端依据 [v2 时间契约](TRAVEL-DETAILS-PLAN.md)；模型位于 `frontend/src/lib/journeySegments.ts`，仅支持已有 journey 的预览／保存。

## UI 接口

- `readCapabilities(raw)` 接收 `/api/journeys/templates` 的 `supportedSchemaVersions` 或列表的 `capabilities.schemaVersions`。必须同时声明版本 2 及 `capabilities.editSourceSnapshot:true` 才得到 `canWriteV2:true`；缺失则禁止新版分段写入，未知版本拒绝，不自动降级。
- `readJourneyDetail(raw, expectedId?)`、`editSegmentDraft(detail)` 读取 v1／v2，建立 `{journeyId,tripId,revision,sourceVersion,plan,observed,expectedEntities}`。旧 v1 可以不带 schemaVersion。草稿从当前 trip、准备及采购覆盖允许编辑的同名字段，保留整数分、未知预算 null、出行成员、稳定 key 与日期；独立日程修改仍由后端三方比较处理。
- `upgradeToV2(draft, referenceTimezone, destinationTimeZones, capabilities)` 是唯一显式升级入口。必须为每个旧目的地明确提供时区；原日期段成为同 key 的 `legacy_day`，不重建关联 ID。已经 v2 的计划无需再升级。
- `previewPayload(draft, capabilities, currentMemberIds, conflictResolutions={})` 返回完整 `{journeyId,revision,expectedEntities,plan,conflictResolutions}`，不支持新建旅程、trip adoption 或降级。`expectedEntities` 是进入编辑时全部关联 trip／tasks／shopping／events 的 ID→revision，绑定 `observed`；发送前 GET 只能比较，不能偷偷改成新的 map。格式错误由服务端拒绝，集合或版本变化返回 409 `stale_edit_source`。最多 20 个目的地、100 段／准备／采购；所有集合 key 唯一，关联目的地存在，成员／负责人来自当前家庭。历史保留日期可超出概览，最终资格由服务端核验，客户端不发绕过标记。
- `readSegmentPreview(raw)` 返回规范化 v2 plan、token、有效期及完整 summary。冲突字段限定 `timing/title/location/note/owner`，选择值仅 `current/plan`；`canApply:false` 必须无 token，不能确认。保留、解决、云复核与 warning 分开呈现。只依据具体事件实际字段展示，不假设每个 warning 都带 entityId。
- `detailFingerprint(detail)` 覆盖 workflow 与全部关联实体 revision。读回发现变化须显式核对；用户确认保留草稿时调用 `rebaseSegmentDraft(draft, latestDetail)`，仅覆盖草稿的 destinations／segments／referenceTimezone，其余成员、金额、准备及采购采用最新授权数据。重核不是自动保存，旧冲突选择和旧预览必须清除。

## 分段与时间

`Segment` 是 `flight | stay | activity | legacy_day` 判别联合。activity 通过 `dateRange` 有无区分全天日期与定时 start/end，不增加后端不存在的 mode。flight 保留两端 airport/city/local/timeZone；stay 保留退房排除日期、未知时刻空串及服务端 nights；legacy_day 的 end 是包含日期。所有预订状态是人工标记，不表示已核对或取消外部订单。

`newDestination(key?)`、`newSegment(kind,key?)` 生成稳定随机 key，其余必填时间／地点留空；不猜航班、城市时区或酒店时钟。`updateTimePoint(point,patch)` 修改 local/timeZone 时清旧 offsetMinutes/instant；`updateStayTiming(stay,patch)` 清对应端的派生时刻与失效 nights。不随概览日期自动平移，不使用设备时区计算 UTC 或 DST。

预览 HTTP 400 可能为 `{error,code,field,choices}`。以 `readTimeIssue(error.body,draft)` 绑定当次草稿，再 `applyTimeChoice(draft,issue,offset)` 选择服务端实际提供的偏移。仅支持确切的 `segments[n].departure/arrival/start/end/checkInTime/checkOutTime`；草稿变化或未知字段拒绝旧选项。选择只提交 offset，UTC 仍由服务端正规化。无效／不存在的当地时间要求用户改日期或时分，不能猜一个时间继续。

## 身份与未知结果

`SegmentFence` 使用完整 role／householdId／member id／auth_version／CSRF 前后 `/me`，并检查 epoch/current。UI 在隐藏、离线、失焦、卸载时立即 invalidate、abort 和隐藏授权数据；同身份恢复先重新核对，真正身份变化清内存草稿。`segmentRequest` 只允许本模块 GET 与 preview/apply POST，same-origin、no-store、redirect:error、15 秒截止，不自动重试。它不代替页面生命周期或导航锁。

UI 应保存一次预览所对应的草稿与来源，任意编辑立即丢弃旧预览；确认按钮只针对仍有效的当次预览。实际发送 apply 前调用 `createSegmentIntent(preview,draft,key?)` 保存原 token／idempotencyKey；`checkedSegmentWrite` 只有实际端点明确拒绝且后验身份成功才产生 `SegmentRejected`。首次明确提交前拒绝可以释放意图，`failedSegmentIntent` 对已经 unknown 的操作保持原载荷，不能因后来的 404／409 清除。

`readSegmentReceipt(raw,intent)` 校验原 journey、trip、revision+1 与 ordinary-edit 回执。`GET /api/journeys/operations/<key>` 经 `readSegmentOperation` 校验 found／原 key 后，只对历史结果补 `replayed:true`；服务端历史 result 本来没有该字段。GET 404 `operation_not_found` 不证明未提交。普通 preview 有效期 1800 秒，过期 apply 为 **409**，不能套用例行计划 410 恢复语义；过期后仍可 GET 原 key。确认后读取当前 detail，不用历史结果恢复旧记录。回执中的 `cloud:not_requested` 是现有普通接口原字段，并不证明既有持续同步绑定已成功；云状态到日历面板另查。

## 验证边界

`frontend/tests/journeySegments.test.ts` 通过独立临时 Flask／SQLite 生成真实 v1/v2、实际 apply／replay／operation、三方冲突／保留／解决与 DST choices，然后执行纯 Node 边界断言。成功业务 JSON 不伪造；仅 transport 负例使用合成 HTTP 拒绝，且临时后端禁止网络连接。开发期可由 `JOURNEY_MODEL_BACKEND_ROOT` 指定 Root 已审的单一后端组合源码，默认用本测试所在仓库；实际源 head 另记，不拼接模块。Python 可由 `JOURNEY_MODEL_PYTHON` 指定，Node 使用 `--experimental-transform-types --test frontend/tests/journeySegments.test.ts`。旧 v2 后端缺少快照能力时新版提交测试应失败，不能伪造成功 capability。没有 npm 安装、前端导出、浏览器、实际账号、云写、生产或 native 安装验收。作者交付记录区分专项／定向类型检查和后续组合验证，不把模型通过当 UI 已上线。

固定 API `6c9261e4655bb24932dc747920c1539d60e1e6f1` 的真实临时 DTO 与当前模型最终 21 项 Node 专项全部通过（1.934 秒），定向 strict TypeScript 检查退出 0，前后模型／测试及后端全部 tracked 字节不变。原件在作者工作树 `test-results/segments-model-20260917T115849665330Z`，result SHA-256 `0d8b686b0981b8b94c84f13e5b4597c07afa55090b2d4c55f3722238395972f3`，Node stdout SHA-256 `a1b84a468bb029d040d27b4f5231c568b9b980cd77d345fe51ad8d6da134e5a7`。上一轮 18 通过／1 失败原件保留于 `segments-model-20260917T115234280634Z`：旧负例误把实际支持的 owner 当非法字段，修为不存在的 budget 组后重新全跑；没有放宽接口断言。更早旧 API 的 13 项仅为开发历史。上述为作者阶段记录；后续组合 typecheck、构建、浏览器及生产验收见 [发布验收](EXPO-JOURNEY-SEGMENTS-ACCEPTANCE.md#expo-segments-release)。
