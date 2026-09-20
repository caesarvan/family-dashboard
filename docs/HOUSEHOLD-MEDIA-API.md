# Google Photos 私有精选 API 与任务状态机

本轮设备照片日期扩展见[照片日期确认契约](MEDIA-CONFIRMED-DATE.md)：本人 DTO 增加 `userConfirmedDate`，仅本人已保存的有效设备照片可单独以 `{revision,userConfirmedDate}` 修改或清空；不能混入说明、共享或旅行修改。伙伴与电视 DTO 不含该字段。本文其余章节保留原模块协议与历史接入说明，实际上线状态以 [HANDOFF](HANDOFF.md) 为准。

此模块需要显式注册，当前候选未接 `app.py`、账号事务钩子、前端或 Docker。仅新增 `household_media.py`、专项测试和本文。图片 worker 使用同一引擎，不直接写 SQL。Google OAuth/Picker、加密与图片净化沿用已审基础组件；本文测试是合成账号、真实成员 cookie/SQLite/Fernet/Pillow，不是实际 Google 或电视设备验收。

## 注册与三表

```python
from household_media import register_media_library
engine = register_media_library(app, db, Problem, body, require_member, audit)
# app.extensions['household_media'] is engine
```

在 users/devices/cloud_accounts/journey_workflows 和 member_sessions/cloud_accounts extensions 初始化后调用。`initialize_media_library(con)` 仅接受无未提交事务、FK 已开启的连接；`SCHEMA_SQL` 可供另审迁移器在自己的事务中执行。新增三表 `media_imports`、`media_items`、`media_tv_grants`，预览密文在 `media_items.preview_cipher` SQLite BLOB 内，无外部媒体文件。当前 44 表基础接入后为 47 表，发布白名单、迁移/恢复另由集成人负责。

索引、配额、状态、owner/account/journey 等本地关联留 SQL；来源文件名/Google mediaId/显示 caption/图片尺寸/明文 SHA 和三类临时导入内容按 MediaCipher 对应 purpose 加密。metadata 绑定 row/household/owner/accountId/sourceKey/随机 previewKey，预览解密后再核明文 SHA/长度。不同 owner/household 的 source_key 不共享去重结果。只在同 owner 的 live staged/ready 范围防重复；旧 requestId 或确认回执不会复活墓碑。

`CONSENT_VERSION='media-v1'`。开始选择必须 `allowTemporaryProcessing:true`；最多20项、createdAt 起固定24h临时窗。只有第二次 `persistSelected:true` 明确选择成功的本地 itemIds 才保存。默认 private，家庭共享独立 PATCH；TV 还需 shared + 逐台 grant。旅行关联不会自动共享、授权 TV 或改变地点 visited。VIDEO 只计 skipped，不下载缩略图或视频。下载 PHOTO preview 再经净化，仅返回静态 JPEG。

每 owner **100 MiB**、每户 **200 MiB**，按所有媒体表业务密文字节加 reservation 原子计量，不含 SQLite 索引/页/备份体积。新选择先预留20×3MiB；完整清单后释放不需下载项，单张落库后将对应 reservation 换成实际密文。超额事务回滚，429。每 owner 同时最多2个流程（存储预留可能先限制）、滚动24h最多10次创建、最多2000导入回执/4000项含墓碑/1000 ready，回执不自动丢弃。

删除在当前事务清空 BLOB 与 metadata、移除 grants、保留最小墓碑/幂等摘要；不声称擦除 SQLite 旧页、已交付字节或历史备份。没有文件孤儿扫描。稳定 SECRET_KEY 是解密恢复依赖，不能将密钥遗失/改变误报为可自动重新下载。

## HTTP：固定 camelCase DTO

全部成员接口使用既有 member/CSRF/Origin 边界，并在新事务中再次核当前 session。账号 ID 采用 `cloud_accounts.py` 实际 `secrets.token_hex(16)` 的 **32hex**；media/item/journey/device ID 为24hex。输入拒绝未知字段、重复 JSON key/query、NaN/Infinity，JSON请求上限16KiB。

| 方法与路径 | 请求 / 结果 |
|---|---|
| POST `/api/media/imports` | `{requestId,accountId,consentVersion,allowTemporaryProcessing:true}` →202 `{import,replayed:false}`；同 key/同内容200重放，不同内容409。可选 `previousUnknownImportId,acknowledgePossibleExistingSession:true` 记录明确重开未知创建。 |
| GET `/api/media/imports` | 仅本人；limit1..50/offset0..4000 →`{items:[Import],total,limit,offset,hasMore}`，列表不含 pickerUri。 |
| GET `/api/media/imports/<id>` | `{import:Import,items:[{id,status:'successful'|'duplicate',item:Item}]}`；id就是确认用的本地媒体ID。失败/视频无可确认id，只计counts。 |
| POST `/api/media/imports/<id>/confirm` | `{revision,confirmRequestId,itemIds,consentVersion,persistSelected:true}` →`{import,itemIds,goneItemIds,replayed}`；同 key精确选择重放不受旧revision影响，已删项进入goneItemIds，不复活。 |
| DELETE `/api/media/imports/<id>` | `{revision}` →`{cancelled,cleanupPending,replayed}`；已确认流程409，不借取消批次删除已有重复收藏。 |
| GET `/api/media/items` | scope=`mine`默认/`visible`/`shared`（他人共享）、journeyId、limit1..100/offset0..4000 →`{items,total,limit,offset,hasMore}`；先按权限过滤再分页。 |
| GET `/api/media/items/<id>` | `{item:Item}`；本人可读有效staged/ready，他人仅shared ready。 |
| PATCH `/api/media/items/<id>` | `{revision,caption?,journeyId?,visibility?}` →`{item}`；仅本人ready。解绑旅行/改private同事务撤TV，旅行为当前workflow.id。 |
| DELETE `/api/media/items/<id>` | `{revision}` →`{deleted,cleanupPending:false,replayed}`；同第一次原revision可重试。 |
| GET `/api/media/items/<id>/preview` | 完全缓冲JPEG，private/no-store/nosniff，无Range/ETag/304；不发起Google请求。 |
| GET/PUT `/api/media/items/<id>/tv-grants` | GET `{revision,deviceIds}`；PUT `{revision,deviceIds,consentVersion,allowTvDisplay:true}` 整组替换，最多20台。空数组撤销无需true；回复同GET形状。 |
| GET `/api/media-tv/items` | 只认证真实 household_tv cookie，即使同时有成员cookie也不替代。limit/offset分页，`{items,limit,offset,hasMore,validUntil}`。 |
| GET `/api/media-tv/items/<id>/preview` | 只认证该TV，当前approved/expiry+item shared ready+grant全部成立。 |

Import：`id,revision,state,createdAt,expiresAt,nextPollAt,counts:{selected,ready,skipped,failed},error:{code,message}|null,canConfirm,cleanupPending`。只有本人有效 waiting_selection 详情返回 pickerUri；token、provider sessionId、原始来源URL、account subject、租约从不进入公共DTO。confirm后临时清单被清除，counts归零，以确认回执 itemIds/goneItemIds 和图库为准。

Item：`id,revision,caption,width,height,contentType,previewUrl,visibility,journey:{id,tripId,title}|null,createdAt,canManage`。本人另有 `accountId,displayFilename,source:'google-photos'`；他人不获来源文件名/账户信息。TV item仅 `id,width,height,previewUrl`，地址是对应 `/api/media-tv/items/<id>/preview`。前端正常成员候选/图库URL固定 `/api/media/items/<id>/preview`。

私密/跨户不存在404，共享他人修改403；版本冲突409、本人墓碑410、额度429、不可读密文503。错误固定 `error/code`，不含上游正文、URL或凭据。源需要重新授权用本地409，避免让客户端误判本人成员登录失效。read-only GET不调用Google；worker另行驱动状态。

## Worker 公共协议 v1

`MediaLibrary(app, *, clock=time.time)` 使用当前家庭的 MemberSessions DB 和 CloudAccounts；不会隐式建表。公开 `accounts` 供worker每一步重新调用 `photos_access_token(accountId,owner)`；新token须建立新Picker并完整重列，不能跨步骤复用baseUrl。

| 方法 | 契约 |
|---|---|
| `claim_next()` | 自带一次 `maintenance()`，返回 job 或 None。原子租约600s，随机leaseToken和revision；不在SQL事务中做HTTP/解码。 |
| `validate_job(job)` | 重新核会话/browser generation/owner/auth_version/account subject/client/scope/lease/版本/固定期限；false丢弃结果。 |
| `complete(job,result)` | 原子CAS；返回bool。create成功即使validate已false也交回已知session，engine只保留绑定正确账户的清理能力，不发布pickerUri、不复活导入。 |
| `fail(job,code,*,retryable=False,outcome_unknown=False,reauth=False,retry_after=30)` | 固定safe code归一化；普通读取最多5次，指数退避最少30s。create never retry，未知结果终态create_unknown。 |
| `maintenance()` | 每次最多100条活动导入游标轮转，清理24h/会话撤回；崩溃creating归unknown；崩溃cleanup归只读核对。返回本轮终结数。 |

job 是服务端内部对象，不得日志/返回前端：`{id,owner,accountId,action,leaseToken,revision,expiresAt,attempts,cleanupUnknown,accountIdentity,session,manifest,media}`。action=`create|poll|list|download|cleanup`；accountIdentity 用于已取消create返回后的来源绑定。manifest 为 adapter 完整 public metadata 列表，无baseUrl。

complete结果：create/poll=adapter session dict；list=完整 selected metadata list；download=`{mediaId,manifest:本次新token重列的完整清单,preview:media_images.Preview}`；cleanup=None。清单按id→全部public metadata比较，忽略顺序；集合或稳定字段变更导致整个暂存失败。单张不支持图片可失败后继续其它已选项。保存BLOB前再次授权/CAS；已取消的下载不落库。

首次发create之前持久标记creating/create_attempted，进程即使在实际发送前崩溃也按unknown，牺牲可用性避免重复创建。Google操作的原始poll截止与会话到期取最小值，后续poll不可延长；全部字节已取回后，awaiting_confirmation可持续到本地24h，不再依赖已清理的Google session。

cleanup首次claim先持久checking；DELETE结果未知或lease过期后的job `cleanupUnknown=true`，worker只能GET读回。404后complete；仍存在/其它不明确情况fail cleanup_unknown，停止并标unavailable。取消后的清理不要求原browser仍登录，但必须账户身份/当前权限及租约仍正确；不授权重列或下载。Google会话无法清理不等于本地副本无法删。

## 必须由集成人接的事务钩子

- `on_account_removed(con,account_id)`：与账号解绑在同一显式写事务调用，取消imports/清本地密文/撤TV。schema额外BEFORE DELETE trigger作为账号删除兜底，不能删除清理回执。UI必须披露来源解绑会清本地精选，Google原件不变。
- `on_account_authority_changed(con,account_id,reason)`：`removed/scope_revoked/photos_revoked/identity_changed` 清来源副本；`reauth` 保留本人已保存副本但取消未确认、降private/撤TV。正常令牌更新且权限未变不要调用撤回hook。两hook拒绝无事务调用，不自行提交。
- `fail` 观察明确 reauth/invalid_token 时，同事务标账户needs_reauth，关闭媒体共享；临时network/429不删除已保存副本。远端控制台撤回没有即时推送，只能在后续API/refresh观察，不宣称即刻检测。
- journey FK SET NULL触发revision提升/private/撤TV；保留本人已确认副本。device FK DELETE立即撤逐台grant，新配对不继承。普通成员logout/撤session只使未完成操作的context失效，不抹已提交的持久/共享同意。

JPEG读取在解密后新建读事务，重新核成员会话或真实TV cookie hash、设备、授权和item revision。撤回若先于最终校验提交则拒绝返回；已经发出的字节不能回收。TV前端可依validUntil15s过期清屏，仍须真实电视型号/浏览器验收；此模块未替UI宣称屏幕安全擦除。

## 本地验证

`python -B -m pytest tests/test_household_media.py -q` 使用真实成员登录/CSRF、真实电视配对、双家庭SQLite、真实Fernet和Pillow，阻断网络。覆盖双同意、私有/共享/逐TV权限、加密重启、幂等/墓碑、取消与迟到create、创建/清理崩溃、原期限/24h、去重、BLOB清除、配额预留、旅行unlink、来源解绑/reauth、I/O中撤session与解密后撤TV、并发同key。另由worker作者/非作者针对固定两head跑协议和SQLite纵向；最终实测数量/日志由候选交付报告提供。
