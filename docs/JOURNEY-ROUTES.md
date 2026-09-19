# 旅行路线 API 与持久化合同

本模块是从 `520781d7c9a9872fd006d929e9b578bbe9c611f8` 开始的候选；本文件不代表已接入 app、完成真实浏览器验收或上线。

路线只保存用户选择的顺序，默认私人；用户明确选择 `visibility: "shared"` 后供当前家庭成员只读。只有路线作者能编辑／删除。地点必须当前关联同一旅行；不会创建地点、推断坐标、改变关联或到访事实，也不调用地图／云服务。电视所有接口均 403，未登录 401。

## 初始化和三表

`register_journey_routes(app, db, Problem, body, require_member)` 在地点模块之后注册，启动时在干净连接开启自己的事务、调用 `initialize_journey_routes(con)` 并提交。独立 initializer **不开始或提交调用者事务**，要求 foreign_keys=ON 和 users/journey_workflows/journey_places 已存在。迁移在自己的原子事务中使用模块的 `SCHEMA_SQL`，以其字节为 DDL 真源。户内表数 66→69，平台仍为 9；原表不做 DDL。

| 表 | 固定列与约束 |
|---|---|
| journey_routes | id TEXT PK；owner TEXT NOT NULL FK users；title TEXT NOT NULL；journey_id TEXT nullable FK journey_workflows ON DELETE SET NULL；visibility TEXT NOT NULL CHECK private/shared；revision INTEGER NOT NULL DEFAULT 1 CHECK integer >=1；created_at/updated_at TEXT NOT NULL；deleted_at TEXT nullable |
| journey_route_stops | route_id TEXT NOT NULL FK journey_routes ON DELETE CASCADE；position INTEGER NOT NULL CHECK integer 0..99；place_id TEXT nullable FK journey_places ON DELETE SET NULL；PK(route_id,position) |
| journey_route_operations | owner TEXT NOT NULL FK users；request_id/payload_digest TEXT NOT NULL；operation TEXT NOT NULL CHECK create/update/delete；route_id TEXT NOT NULL FK journey_routes；result_revision INTEGER NOT NULL CHECK integer >=1；completed_at TEXT NOT NULL；PK(owner,request_id) |

额外索引仅 `journey_routes_owner(owner,updated_at,id) WHERE deleted_at IS NULL` 与 `journey_routes_journey(journey_id,visibility) WHERE deleted_at IS NULL`。无新 trigger、settings 或广播。每户独立库；回执按当前 actor、当前家庭隔离。路线软删除清空标题／关联／站位，回执一直保留。地点硬删会留下 place_id=NULL 的槽；删除旅行后路线 journeyId=null，所有槽不可用，仍可删除或重新选择新的旅行和全部地点。

供导出复用的 `route_context(con,row,owner,household,secret)` 返回 `(detail, raw_stop_rows)`，secret 是 SECRET_KEY 的 UTF-8 bytes。它只读取调用者当前快照、不 commit，也不独立验证会话；调用者必须先筛选当前可见路线，在同一授权事务内调用、返回前执行已有 fresh session fence。对外仅使用 detail 的允许字段，绝不输出第二项 raw_stop_rows。所有隐私投影与 API 共用此函数。

回执只含请求摘要和操作标识，不存地名、坐标或响应 DTO。不调用共享 audit，不向 `/api/state`、助理摘要或电视广播私人路线活动。导出接线必须沿当前授权投影处理地点；不能把含其他成员隐藏引用的 stops 原表当作可公开 DTO。

## 请求和限制

前缀 `/api/journey-routes`。所有写入沿用成员会话、Origin 与 CSRF；读写使用真实 ImportSession，在事务前后与返回前重新验证 actor/household/session。写事务 BEGIN IMMEDIATE，路线、顺序和成功回执原子提交。

| 字段 | 限制 |
|---|---|
| id / journeyId / placeId | 24 位小写十六进制 |
| requestId | 32 位小写十六进制，同一成员跨 create/update/delete 共用命名空间 |
| revision / expectedJourneyRevision / expectedRevision | 正整数且小于 2^53，拒绝 bool |
| sourceVersion | 64 位小写十六进制，服务器不透明 HMAC；不是用户可解释的地点摘要 |
| title | 去首尾后 1..160 字符，无 Unicode C 类控制字符 |
| stops | 1..100 项，允许重复地点与往返 |
| 请求体 | 最多 32 KiB，拒绝未知字段 |
| 容量 | 每成员最多 1000 路线（包括墓碑）、10000 成功操作；不清理回执；达到上限 409，已有回执仍先恢复 |

POST `/api/journey-routes`：

```json
{"requestId":"<32hex>","title":"我的路线","journeyId":"<24hex>","expectedJourneyRevision":1,"visibility":"private","stops":[{"placeId":"<24hex>","expectedRevision":1}]}
```

仅 create 可省略 visibility（private）；不得含 revision/sourceVersion。PUT `/<id>` 必须含上述全部字段，再加 `revision` 和 `sourceVersion`。DELETE `/<id>` JSON **仅** `{requestId,revision,sourceVersion}`。

PUT 可用 `{keepUnavailableIndex: n}` 保留原详情中的不可用槽；n 永远指原详情 index，重排不会重解释。该原槽须仍不可用、原路线 revision/sourceVersion 匹配、同一 journey，每个 n 最多用一次；不能凭此添加或复制隐藏引用。创建不允许 keep。private→shared 必须移除所有不可用槽，所有新 placeId 均当前 shared；已经 shared 的路线可以保留原不可用槽。private 已有缺口也可保留。用户可以明确移除缺口并重排，这与读取时自动跨缺口连线不同。

## 当前读取 DTO

GET collection 支持 `scope=mine|shared|visible`（默认 visible）、可选 journeyId、limit=1..100（默认100）、offset=0..10000（默认0），不接受重复或未知参数。

```text
{items:[{id,title,journeyId,visibility,revision,canManage,stopCount,unavailableCount}],
 total,limit,offset,hasMore}
```

仅当前可见路线进入查询／计数；排序 updated_at DESC,id。列表不带地点名称、坐标或 sourceVersion。GET `/<id>`：

```text
{route:{id,title,journeyId,visibility,revision,canManage,sourceVersion,
 stops:[{index,state:"available",place:<既有地点当前投影>} | {index,state:"unavailable"}]},
 segments:[{fromIndex,toIndex}]}
```

shared 路线对**所有人包括作者**使用既有地点共享投影：place.canManage=false，不含 sharedCoordinates/sharedCoordinatePrecision/sharedCoordinateGridDegrees 等作者字段；按地点当前 coordinateDisclosure hidden/coarse/exact 投影。private 路线使用当前查看者权限下的原地点投影。共享路线可用地点的名称及 owner 等原共享字段与原地点 API 一致；不可用槽只含 index/state，绝无隐藏 ID、名称、owner、revision、坐标。地点变私人、删除、撤去旅程关联或移到别的旅程后立即不可用，作者也不例外（shared 路线）。

segments 仅连接两个**原相邻 index**、都 available 且都有授权坐标的槽，不跨缺口、不跨隐藏坐标。sourceVersion 覆盖 actor/household、路线行、当前旅行工作流与 trip 版本、全部站序和全部当前地点数据（包含不可用站），用服务端密钥 HMAC 防止枚举隐藏引用。任何实际源变化均须重读核对；回执恢复不要求旧 sourceVersion 仍有效。

## 保存与结果未知恢复

POST 首次成功 201，PUT/DELETE 200，同键重放 200。GET `/operations/<requestId>` 只读本人回执、未知 404。统一返回：

```text
{operation:{requestId,kind:"create"|"update"|"delete",routeId,resultRevision,completedAt},
 replayed:boolean,current:<上面的 detail>|null}
```

completedAt 是 UTC ISO8601 微秒。GET operation 的 replayed=true。current 是请求完成后当前实时授权投影，可因后续修改与 resultRevision 不同；路线后来删除则 null，包括恢复更早 create 操作。不返回历史地点 DTO。

同成员／家庭／requestId、规范化请求相同：先恢复成功，永不再次写路线／站位／回执，旧版本与容量限制不阻碍恢复。相同键不同规范化请求或不同操作／目标返回409 request_conflict。未知结果时先按原键查询，再由用户明确重发**原请求**；不要自动更换键。重建应用与连接后，SQLite 中回执与站序继续存在。GET 回执不是撤销、重做或恢复删除路线。

错误统一 `{error,code}`：400 invalid_request；401 session_changed；403 forbidden；404 not_found；409 revision_conflict/source_changed/request_conflict/limit_reached；413 request_too_large；会话引擎缺失503 session_unavailable。不可见路线与未知路线同404；共享路线非作者写403；所选地点不可用／不属该旅行统一409 source_changed，不附地点事实。

## 验证边界

作者专项使用独立临时家庭、真实 Flask／SQLite／会话。第一轮 48 项全部通过；随后只补跑 3 项提交后响应丢失／第二次会话检查回滚／guard 后共享撤回，均通过，共 51 个不同路线用例分轮取得证据。应用重建指重新调用真实 create_app 并重开持久临时 SQLite，不宣称操作系统进程重启。12 份实际合成响应另供前端解码交叉验证，未调用外部服务。

现有地点 DTO 仅抽取公用投影 helper，原调用逻辑保持。旧 `test_journey_places.py` 与 `test_journey_place_source_revision.py` 完整执行一次：114 通过、1 失败；失败是既有 `test_module_is_registered_and_initialized_by_production_factory` 仍要求数据库恰好历史 58 表，而本批基线已 66 表。真实失败保留，未静默跳过或改成 PASS；本作者未修改该未授权旧测试。包含上述新增 3 项的第二轮实际总计 117 通过、1 失败。

原件位于作者忽略目录 `test-results/journey-routes-r1`、`journey-routes-regression-r1`，包含真实 stdout/JUnit/执行命令与源码前后 SHA；`journey-routes-wire-r1` 保存全合成实际响应。当前作者测试通过显式 fixture 注册新模块；app/Docker/迁移／导出／前端接线和组合浏览器由对应独立作者完成。固定组合、真实家庭与生产另验。
