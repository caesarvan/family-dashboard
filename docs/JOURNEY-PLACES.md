# 手动地点：持久化、到访确认与隐私投影

本模块为家庭足迹地图提供手动地点 API。地点独立保存，可关联同户既有旅行；日期、照片和预订不会自动变成到访证据。首版没有地理编码、外站调用、路线计算、媒体关联或电视访问。

当前交付是**独立后端候选**：仅增加 `journey_places.py`、专项测试和本文，未修改 `app.py`、导航、Docker COPY、发布白名单、总体数据模型或迁移工具。测试 fixture 显式注册新模块，真实生产 factory 不注册它。没有上线声明；后续接入、44 表迁移、组合浏览器验收与发布均需独立审查。

## 注册、schema 与事务

接口为 `register_journey_places(app, db, Problem, body, require_member, audit)`，依赖既有核心用户、`member_sessions` 和 `journey_workflows`。集成人将来在旅行模块之后登记。传入的 `db()` 必须指向**当前家庭独立数据库**，并启用外键；不可改用全局共享连接。

`initialize_journey_places(con)` 显式创建新表、索引及触发器，要求已存在 `users` 和 `journey_workflows`、外键开启且调用者没有未提交事务。它自行 `BEGIN IMMEDIATE`／提交，异常回滚。`SCHEMA_SQL` 另供未来审查后的迁移工具在自己的事务中使用；仅导入 Python 模块不会初始化数据库。

新增一张户内 `journey_places` 表：

| 字段 | 类型及用途 |
|---|---|
| `id` | 服务端生成的 24 位十六进制稳定 ID，主键 |
| `owner` | 创建者用户 ID，指向本户 `users`，请求不能指定或更换 |
| `request_id`, `payload_digest` | 创建回执标识和归一化请求 SHA-256；`UNIQUE(owner,request_id)` |
| `name`, `country`, `city` | 地点名称、国家／地区、城市；后两项可空字符串 |
| `latitude_e6`, `longitude_e6` | 成对可空的整数微度；±90/±180 度，数据库限制整数与边界 |
| `status` | `visited`、`planned`、`wish` |
| `journey_id` | 可空，指向本户 `journey_workflows`，`ON DELETE SET NULL` |
| `start_date`, `end_date` | 用户输入的日期或 NULL；不自动取旅行日期 |
| `visibility` | `private` 或 `shared`，默认仅本人 |
| `coordinate_disclosure` | 对其他成员的坐标投影设置：`hidden`、`coarse`、`exact`，默认隐藏 |
| `visited_confirmed_at`, `visited_confirmed_by` | 当前到访声明的明确确认时间／成员，非服务端核实到访证明 |
| `revision`, `created_at`, `updated_at`, `deleted_at` | 并发版本、创建／更新时间和软删除标记 |

三个命名索引为 `journey_places_owner`、`journey_places_visibility`、`journey_places_journey`。触发器 `journey_places_unlinked_revision` 在父旅行删除导致关联变空时提升地点 revision 并更新时间；**保留原 visited 确认事实**。显式 PATCH／DELETE 自己提升版本，触发器不再重复提升。

每个读写事务重新执行成员校验和 `member_sessions.current(con)`，核对 owner、auth_version 与 householdId。写事务先获得 SQLite 写锁，防止旧 revision 或 quota 同时通过。撤销在该事务开始前生效时请求会被拒绝；已进入事务的操作可能先完成，不声称撤销可回滚已完成操作。审计只记录动作名和地点 ID，不记录坐标或名称。

## 权限与敏感坐标

所有五个地点 API 都要求当前有效成员。匿名 401，电视 403；地点不进入电视 state、助理上下文或现有旅行／财务响应。

- 本人可读取、修改、删除自己的地点；默认 private。
- 明确 `visibility: shared` 后，同户其他成员只读。共享不授予修改或删除权。
- 他人私密、其他家庭、已删除地点的普通 GET/PATCH 返回 404，不区分存在与否。
- 所有筛选与 total 先应用 `owner=本人 OR visibility=shared`。年份、成员、旅行与分页不能泄露私密记录计数或元数据。

本人响应的 `coordinates` 保留精确值供编辑。对其他成员，只有共享行可见，然后应用：

| coordinateDisclosure | 他人 coordinates | coordinatePrecision | coordinateGridDegrees |
|---|---|---|---|
| `hidden` | null | `hidden` | null |
| `coarse` | 固定 0.1 度网格，四舍五入 | `approximate` | 0.1 |
| `exact` | 原坐标 | `exact` | null |
| 无原坐标（任意设置） | null | `none` | null |

0.1 度仅为粗略概览，不表示精确城市定位、街道路由或匿名保证。`visibility: shared` 仍会共享名称、国家、城市、状态与日期；不会识别或擦除名称中手写的家庭地址。UI 必须说明这一范围。坐标筛选、bbox 搜索或按距离排序未提供，避免以精确坐标参与共享过滤。

本人另收到 `sharedCoordinates`、`sharedCoordinatePrecision`、`sharedCoordinateGridDegrees`，用于预览所选共享坐标设置；它们不表示当前记录已经共享。他人响应不含这三个编辑字段，也不含原始坐标、requestId、payloadDigest 或数据库内部字段。

## API 和完整合成响应

`GET /api/journey-places` 返回 `{items,total,limit,offset,hasMore}`，每次请求使用同一数据库读事务。

| 查询参数 | 可用值 |
|---|---|
| `scope` | `visible` 默认、`mine` 仅本人、`shared` 仅明确共享行 |
| `status` | `visited`／`planned`／`wish` |
| `year` | `0001`–`9999` 四位年份；用户日期区间与该年相交，无日期的记录不匹配 |
| `owner` | 当前户已有 `users.id`，如 `member1`；不是任意家庭成员查询 |
| `journeyId` | 当前户存在的 workflow ID，非 trip 实体 ID |
| `limit` | 1–200，默认 100 |
| `offset` | 0–3000，默认 0 |

未知／重复参数均 400。排序为 `updatedAt` 降序、ID 升序；没有跨页历史快照保证，分页期间更新可能移动记录。UI 刷新后按 ID 去重，不能把一次分页结果当作长期完整缓存。不存在或跨户的旅行过滤为 404；筛选返回的计数仅为当前可见结果。

下面是**虚构的本人响应**，供前端契约使用：

```json
{
  "items": [{
    "id": "111111111111111111111111",
    "owner": "member1",
    "name": "合成公园",
    "country": "合成地区",
    "city": "合成城市",
    "coordinates": {"latitude": 31.2304, "longitude": 121.4737},
    "coordinatePrecision": "exact",
    "coordinateGridDegrees": null,
    "coordinateDisclosure": "coarse",
    "status": "visited",
    "journeyId": "222222222222222222222222",
    "journey": {"id": "222222222222222222222222", "tripId": "333333333333333333333333", "title": "合成旅行"},
    "startDate": "2026-06-01",
    "endDate": null,
    "visibility": "shared",
    "visitedConfirmedAt": "2026-09-16T06:00:00.000000+00:00",
    "visitedConfirmedBy": "member1",
    "revision": 1,
    "createdAt": "2026-09-16T06:00:00.000000+00:00",
    "updatedAt": "2026-09-16T06:00:00.000000+00:00",
    "canManage": true,
    "sharedCoordinates": {"latitude": 31.2, "longitude": 121.5},
    "sharedCoordinatePrecision": "approximate",
    "sharedCoordinateGridDegrees": 0.1
  }],
  "total": 1,
  "limit": 100,
  "offset": 0,
  "hasMore": false
}
```

其他成员读取上例时，`coordinates` 为 `{latitude:31.2,longitude:121.5}`、precision 为 approximate、grid 为 0.1、`canManage:false`，且删除三个 `shared*` 编辑字段。详情 `GET /api/journey-places/<id>` 使用相同投影，仅包装为 `{place: ...}`。

旅行候选复用既有 `GET /api/journeys`，关联键为 workflow.id；响应 `journey.tripId` 可打开原 trip。成员候选来自当前已授权成员上下文。地点 API 不新增成员目录或读取隐藏记录的年份汇总端点。

### 创建与幂等

`POST /api/journey-places` 必填 `requestId`、`name`；其他字段可省略：

```json
{
  "requestId": "synthetic-place-request-0001",
  "name": "合成公园",
  "country": "合成地区",
  "city": "合成城市",
  "coordinates": {"latitude": 31.2304, "longitude": 121.4737},
  "status": "wish",
  "journeyId": null,
  "startDate": null,
  "endDate": null,
  "visibility": "private",
  "coordinateDisclosure": "hidden",
  "confirmVisited": false
}
```

`requestId` 是 16–100 个 ASCII 字母、数字、`_`、`-`，支持 `crypto.randomUUID()`。名称 1–160 字符，国家／城市最多 100 字符，可空；不接受控制字符。坐标为成对的有限 JSON 数字，最多六位小数，或 null；不能传部分坐标、数字字符串、NaN／Infinity。日期为有效 `YYYY-MM-DD`，空字符串归一化为 null；结束日期须有开始日期且不早于开始日期。默认 status=wish、visibility=private、coordinateDisclosure=hidden。未知字段（包括 owner、revision）拒绝。

新建返回 **201** `{place,replayed:false}`。相同 owner/requestId 和相同归一化原始内容返回 **200** `{place:当前元数据,replayed:true}`；不会产生第二条地点或审计。相同标识但不同内容为 409。即使原旅行后来被删除，先查原回执再检查当前依赖，所以正确重放仍能返回已解绑地点。若原地点已删除，原创建请求返回 **410**，绝不复活。

每户记录总量上限 3000，**包括软删除回执**。删除不会释放创建回执配额；不自动裁剪旧回执，也不以清理回执换取可能重复创建。达到上限仍可修改／删除已有点和重放原回执；更多容量需维护者单独制定保留与迁移方案。

### 修改、到访声明和删除

`PATCH /api/journey-places/<id>` 必填正整数 revision，至少一个业务字段，允许修改上述除 requestId 外的字段及 confirmVisited；不接受响应投影字段、owner、创建时间等。成功返回 **200** `{place}`。相同内容不提升版本；真正变更提升一次 revision。版本不匹配返回 409，由 UI 保留草稿、重新读取后让用户决定，不自动覆盖。

```json
{"revision": 1, "status": "visited", "startDate": "2026-06-01", "confirmVisited": true}
```

新建或切换到 visited 必须显式 `confirmVisited:true`。在 visited 状态修改名称、国家、城市、坐标、日期或旅行关联，也须再次确认；只改 visibility／coordinateDisclosure 不需重复确认。true 不允许用于其他状态；从 visited 改为 planned／wish 清空当前确认字段。照片、过去日期、旅行完成或媒体 metadata 都不会自动确认到访。

用户修改关联与自动删除父旅行不同：父旅行删除由外键清空 journeyId，提升 revision，保留地点、共享设置与原 visited 确认事实。旧版本修改／删除会冲突。地点删除不会删除旅行、资料、任务或采购。

`DELETE /api/journey-places/<id>` 仅接受 `{revision:1}`。成功 **200** `{deleted:true,id,revision:2,replayed:false}`。原 revision 重试删除返回相同新版本和 replayed=true；其他版本冲突。删除后仅保留 id、owner、创建请求标识／摘要及版本时间回执，名称、城市、坐标、关联与确认字段清空。普通 GET/PATCH 返回 404。

错误沿用 `{error:"中文说明"}`：400 格式／确认错误、401 会话无效、403 TV／非创建者修改、404 不存在／不可见／旅行不存在、409 revision／请求内容／容量冲突、410 原创建请求已删除、415 非 JSON、503 暂不能核对会话。没有将验证失败伪装成已保存的路径。

## 验证与后续接入

专项测试在临时 SQLite 中通过 fixture 显式注册模块，使用真实登录、CSRF、WSGI 家庭切换、设备配对与线程竞争；网络连接被测试夹具禁止。覆盖 CRUD/重启、精确/隐藏/粗化投影、过滤计数、私密/共享/撤销、跨家庭同 ID、visited确认、并发创建/CAS/容量/父旅行删除、tombstone重放、失败回滚、schema重复运行和备份读回。没有真实家庭数据或生产操作。

作者最终验证：**95 passed，0 failed / error / skipped**（91 项地点专项 + 4 项既有旅行资料／家庭隔离回归），48.72 秒。原件为本工作树 ignored `test-results/journey-places-api/pytest-output.txt` 和 `pytest-results.xml`。首轮83项结果只作开发过程记录，不与最终95项相加。该结果尚不包括地图UI、真实应用接线、迁移或生产部署。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_journey_places.py
```

下一步由集成人负责：模块注册及新 schema 迁移、数据模型与API索引、Docker/发布白名单、导出覆盖、地图UI接线与组合浏览器验收。本模块没有接入现有个人 ZIP 导出；SQLite 整库备份会保存新表，但当前生产升级／恢复工具的 43 表断言尚未修改。**不能用仅 43→43 的 SOURCE 发布流程直接上线这项新增表。**
