# 家庭助理：本地照片与地点搜索

本候选以 `f9f7301` 为基线，只修改助理模块及其界面，未修改数据库 schema、媒体引擎、地图模块、应用注册或部署。需经非作者审查与集成；源码完成不代表生产启用。照片展示依赖已接入的 `household_media`，地图依赖 `journey_places`。新增路由需由集成人同步路由索引和发布源码清单。

## 用户流程

在家庭助理中输入 `搜索 酒店`、`查找：海边` 或 `找一下 旅行标题`。明确搜索始终在本地完成，即使勾选 AI 也不会发送搜索文字或结果。搜索记录标题/地点、本人及当前可读共享照片的说明/关联旅行标题、本人及共享地点的名称/国家/城市/关联旅行标题。不会搜索照片原文件名、账户信息、图片内容、坐标、个人财务或未确认的导入内容。

结果可翻页；照片及地点点击后在助理中显示只读安全详情，再可打开现有家庭相册或足迹地图入口。入口进入对应页面，不承诺定位该页内部的特定卡片。原有待办、采购、日程及旅行仍打开已有记录。照片说明和其他元数据只作为文本显示，不执行 HTML 或指令。界面不为电视读取这些来源。

## API

`GET /api/assistant/search?q=<query>&limit=20&offset=0`：当前家庭成员登录。`q` 去除两端空白后 1～100 字，大小写折叠后字面匹配，不解析 SQL 通配符；`limit` 为 1～30，`offset` 为 0～20000，拒绝重复或未知参数。排序为 `(kind,id)` 升序，先应用 ACL 再计数、分页。没有持久化搜索缓存或索引；每次重新读取授权来源。

```json
{
  "query": "海边", "total": 2, "limit": 20, "offset": 0, "nextOffset": null,
  "matches": [
    {
      "id": "111111111111111111111111", "kind": "media", "title": "海边散步",
      "journey": null, "visibility": "private", "revision": 2
    },
    {
      "id": "222222222222222222222222", "kind": "places", "title": "海边公园",
      "country": "合成地区", "city": "合成城市", "status": "wish",
      "journey": null, "visibility": "shared", "revision": 1
    }
  ]
}
```

`journey` 非空时仅为 `{id,tripId,title}`。照片 `title` 是说明；无说明但匹配关联旅行时为“精选照片”。地点 `status` 沿用 `visited/planned/wish`，不推断已到访。旧记录 match 仍为 `{id,kind,title,start,due,owner}`；无值字段为 null。所有来源均无坐标/账号/文件名/预览字节。

`POST /api/assistant/plan` 保持既有请求 `{prompt,useModel,includeHouseholdContext}`。明确搜索的响应为 `{id:null,summary,actions:[],mode:"local",matches:[...],search:{query,total,limit,offset,nextOffset}}`，首页 limit=20；不写 `assistant_plans`。继续分页使用 GET，不能对搜索结果 apply。搜索词为空或超过100字为400。非搜索任务/采购计划继续保存原有动作草案，返回真实 plan id，确认和幂等 apply 不变。

HTTP 400 表示参数无效，401/409 表示真实成员会话或发起上下文已失效，403 表示权限/CSRF/电视限制。媒体或地点被撤权后，其原详情接口返回404，界面清除旧搜索及详情，不重试写操作。API沿用应用 `Cache-Control: no-store`。

## 权限与安全投影

- 助理事务使用当前家庭的连接，`member_sessions.current(con)` 与全局 guard 的成员、auth_version、家庭比较；共享照片再使用媒体 `_member`、`_authority`、`_item_dto`。仅 `state=ready`，不扫描预览 BLOB；共享给他人的照片须仍有有效来源授权。本人已确认的本地展示副本按媒体模块原规则仍可读。
- 地点序列化函数是注册闭包，没有可直接调用的公用 DTO helper。搜索读取严格的文字列，使用与地点详情相同的 `owner OR shared`、非 tombstone 规则；不读取坐标列。点击通过原 `/api/journey-places/<id>` 再核验 ACL，界面仍不显示坐标。坐标展示及粗化由原地图页面负责。
- 每次 GET 为当前数据库快照；并发增删/撤权可能改变下一页位置和 total，不承诺跨请求快照游标。候选扫描受原实体、照片、地点配额约束，响应最多30条。不增加云调用或地理编码。
- 照片点击只接受完全匹配 `/api/media/items/<24位十六进制id>/preview` 的同源地址，禁止跳转，验证 JPEG 类型及 ≤2MiB，先复核详情，下载后再核验身份、权限及 revision 才创建临时 Blob URL。
- 展示中的来源每10秒复核，15秒未成功续验会清除，失联、失败、撤权、revision改变、页面隐藏、关闭或离线事件均清除展示副本并撤销 Blob URL。浏览器及网络事件存在调度延迟，此期限用于手机助理详情，不改变独立的电视播放 lease。新的搜索/刷新/重开重新查询权限，不直接重绘缓存搜索结果；迟到的下载不能覆盖新身份页面。

## 模型请求与执行的会话复核

模型网络调用前用 `member_sessions.capture(member=True)` 捕获真实 browser generation、credential、owner、auth_version，并对比当前请求身份；不持有 SQLite 事务跨网络等待。`/plan` 返回后在 `BEGIN IMMEDIATE` 内同时调用 current 和 validate_context，再规范化动作、保存并返回；`/journey-brief` 返回前同样复核，不创建旅行。

`/plans/<id>/apply` 在 `BEGIN IMMEDIATE` 事务内重新核验真实成员与当前 capture 上下文，再查询本人计划、检查和执行动作、写一次回执及审计。已完成计划的重试也必须经过这一步。任何一步失败回滚。捕获上下文只保护本次请求，不将草案永久绑定到创建时浏览器：同一本人的合法新登录仍可确认未过期本人草案，保留原兼容语义。

模型仅继续接收用户主动提交的非搜索文字，以及明确勾选的近期事件/待办标题 allowlist。照片、地点、私有财务、账户和文件名均不加入模型上下文。

## 验证

`python -m pytest tests/test_assistant_source_search.py` 使用临时 SQLite、真实 Flask/member cookies、合成加密照片和真实 Edge/loopback。覆盖私有/共享/来源撤权/删除、旅行关联解绑、双家庭路由、重启与分页、CSRF/TV/旧会话、模型等待期间注销/改密版本/browser generation变化、apply回执重试及竞争、模型上下文隔离。Edge场景包含手机预览、元数据文本、相册/地图入口、翻页、离线清屏、恶意预览 URL 拒绝、撤共享、下载期间退出登录丢弃迟到响应。恶意 URL 响应投影和挂起续验为注入异常，其余来源读写走真实本地 API；未调用真实模型、Google或生产。

失败日志和最终报告保存在 ignored `test-results/assistant-source-search/`。原有助理、旅行简报和 NVIDIA 适配的专项另跑，不将虚构测试计为真实用户或实体设备验收。
