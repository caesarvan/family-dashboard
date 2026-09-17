# Expo 照片旅行建议客户端契约

本模块是候选实现，尚未完成 Expo 界面组合、浏览器或生产验收。只新增严格解析与确认请求构造；复用现有媒体 API、`Photo` 和 `PhotoReadFence`，不新增依赖、表、请求层或存储。服务端行为见 [媒体资料](HOUSEHOLD-MEDIA-API.md) 与 [照片旅行建议](MEDIA-JOURNEY-SUGGESTIONS.md)。

## 导出与读取

`frontend/src/lib/photoJourneySuggestions.ts` 导出 `PhotoJourneySuggestion`、`PhotoJourneySuggestions`、`readPhotoJourneySuggestions(raw, photo)`、`photoSuggestionBody(photo, suggestions, journeyId)`。

读取 `GET /api/media/items/<photoId>/journey-suggestions` 的完整响应，传入当前本人照片。解析要求 `canManage=true`，照片 ID、revision、当前关联行程均与响应一致；已有旅程的 ID 与 tripId 也须合法。当前 owner 照片 DTO 的 `sourceCreatedAt` / `sourceTimeState` 若出现任一，两者都必须与建议响应相符；旧 `Photo` 类型可以同时不含这两个字段。

响应精确包含 `photoId / photoRevision / sourceTimeState / sourceCreatedAt / currentJourneyId / suggestions / limit / hasMore / reason`。列表最多 20 项，`limit=20`，有更多项时必须返回完整 20 项；不构造不存在的后续分页。每项含行程 ID、行程和旅行 revision、当前标题与起止日期、参考时区及来源、服务端 `sourceDate`、`alreadyLinked` 和日期重叠说明。ID 不重复，版本为正安全整数，日期须有效且匹配区间，已关联标记必须对应 `currentJourneyId`。当前关联不在前 20 项内是合法响应。

来源创建时间保留原始纳秒精度和偏移，不使用客户端 `Date` 重新计算日期，不用导入时间代替。v1 的 `legacy_default` 明确对应 `Asia/Shanghai`；v2 使用服务端给出的计划参考时区。客户端只检查时区字符串结构，不依赖设备时区数据库重新判断日期。未知来源时间要求 `sourceCreatedAt=null`、空建议及 `source_time_unknown`；已知但无匹配使用 `no_matching_journeys`。日期匹配不证明拍摄地点或实际到访。

解析拒绝多余或缺失字段、混合照片版本、非本人照片和不一致的状态，返回独立对象，避免原响应后续变化影响已显示建议。错误为可展示的中文 `Error`。

## 明确确认与不确定结果

用户选择当前列表中尚未关联的一项后，`photoSuggestionBody` 再次核验整份数据，产生精确四字段：

```json
{"revision":1,"journeyId":"<24 位小写十六进制>","expectedJourneyRevision":1,"expectedTripRevision":1}
```

发送至 `PATCH /api/media/items/<photoId>`，不可混入 caption、visibility、电视授权或来源信息。服务端在写锁内核验照片、行程和旅行三个版本；过期返回 409，明确成功返回 `{item: Photo}`。本协议没有持久操作 ID 或历史回执，不能添加自动重试，也不能把一次 GET 的相同关联当成原操作回执。

调用方负责同一编辑锁、草稿确认和请求发送边界。发送后的网络失败保留不确定状态，通过新的本人照片与建议 GET 核对；重新确认必须由用户基于当前版本明确发起。已成功 PATCH 后后续 GET 失败仍保留已知成功事实。

每次读取复用 `PhotoReadFence`，在前后 `/api/me` 核对成员、家庭、角色、auth_version、CSRF；隐藏、离线、离开面板或身份变化时调用 `invalidate()` 并使 `current()` 返回 false。传输的同源、超时、abort，以及发送后不确定结果由现有 PhotosScreen 调用方处理。本模块不声称仅靠 DTO 解析已完成异步权限或服务端会话保护。

## 已执行专项与边界

基线 `fd610282a24d5dbb68ee0c398a5b175b35b64276` 上执行 `node --test tests/test_expo_photo_suggestions.mjs`：14 / 14 通过，0 失败、0 跳过。测试以真实临时 Flask/SQLite 和合成照片建立 v1 / v2 行程，通过实际 HTTP 读取与确认；验证来源纳秒和偏移、旧计划与当前旅行差异、旧版本 409、精确四字段、未知来源、20 / 21 项、本人以外拒绝、畸形 DTO，以及现有 fence 的身份与生命周期边界。成功业务响应均来自实际 API；畸形边界只破坏该真实响应的副本。网络被阻止，临时数据自动清理。

原件保存在本工作树忽略目录 `test-results/photo-suggestions-model-r1/`：`node.stdout` SHA-256 `cc031849a0734c6b222b163bef74747414277b304fdb2c606d198060e21f3b5f`，stderr 为空，`evidence.json` 记录受验所有 tracked 文件及两个新增源码前后 SHA 与基线 HEAD，均未变化。

定向严格 TypeScript（新模型和所依赖 photos.ts）实际 exit 0，记录为 `typecheck-r2.json` 与同名前缀日志。首次检查因主仓没有物理 TypeScript 安装而未启动编译，其原日志保留；随后使用已存在的独立组合工作树 TypeScript，只读编译当前模型，没有安装或修改依赖。此处不代表整包类型检查、真实云照片、原生手机、浏览器视觉、实体电视或生产已通过。
