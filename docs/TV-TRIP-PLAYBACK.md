# 电视单趟旅行回顾

实现契约，开发基线 `904fde5665b6f5063ac90f9c752556a70daeb108`。本批尚未发布；当前生产仍为[助理清单版本](ASSISTANT-LIST-ACCEPTANCE.md#assistant-list-release)。

## 家庭成员的操作

旅行详情 → 旅行回顾 → 在电视回顾 → 选择已配对电视与可选的一条已共享路线 → 核对预览 → 开始电视回顾。选择后可自动读取预览，但开始必须由成员明确确认。成功后手机可暂停、继续、切换媒体、调整照片间隔或返回家庭看板。

每台电视独立保存旅行范围。只选本趟旅行当前仍获该电视许可的照片和视频；没有媒体但有可展示路线时也可以开始。没有选择路线时不从城市、地点顺序或照片推断路线。照片与路线同属旅行，不代表照片拍于某个站点。

电视同时展示旅行标题、日期、共享路线及获准媒体。路线只画服务端允许的相邻段，缺失、撤权或隐藏坐标的中间站不能被跨过连线。站点列表每页8项，标明覆盖并自动翻页；播放暂停同时暂停翻页。没有媒体时隐藏手机上一项、下一项按钮；路线翻页不伪装成媒体进度。

## 权限与实时投影

- 成员预览使用电视专用投影，不能复用包含本人私密地点和照片的成员回顾 DTO。
- 只有当前仍共享、属于原旅行、未删除的所选路线和站点可以显示；坐标沿原隐藏／模糊／精确设置，即使发起者是地点作者也不扩大精度。明确开始只设置所选电视的播放范围，不修改路线／地点共享，不创建媒体授权。
- 媒体查询先限定旅行，再沿现有 `ready + shared + media_tv_grants + source authority` 核验，最多2000项。不得读取媒体 BLOB 来统计或排序。
- 路线撤共享、删除或转到别的旅行时移除旧路线标题和坐标，显示不可用；仍获准的本趟媒体可以继续。旅行不可用时清掉旅行、路线和媒体，保留旅行范围失效状态，绝不自动退回全部相册。
- 成员会话、家庭、设备批准／到期、来源授权在服务端重新核验。电视身份只来自真实设备 Cookie，不能从请求中的成员、设备或家庭字段取得权限。
- TV 沿用 protocol 2、最长15秒显示租约及约2秒轮询。标题、路线和媒体一起受租约与页面生命周期约束；断网、后台、身份变化和拒绝读取会隐藏内容。服务器拒绝撤权后的新请求，不承诺收回已交付的像素或浏览器冻结画面。

## 数据与初始化

新增两张表，家庭库75→77，平台库9不变；原 `media_playback` 八列和 `media_playback_progress` DDL 保持。新模块 `media_trip_playback.py` 提供 `init_schema(con)`，要求调用者已开始事务并启用外键，不自行提交。新安装由现有播放模块注册，已有服务器另走完整组备份及精确迁移。

`media_playback_journeys` 每设备一行：`device_id` 主键及播放表级联外键；`journey_id`、`route_id` 分别在源记录删除时置空；`route_selected` 区分未选择和所选路线已失效；`started_by`、32位 `start_request_id` 及创建／更新时间记录发起行为。行存在即旅行范围，`journey_id=NULL` 不得解释为全部相册。源 DTO 不存历史副本。

`media_playback_operations` 用 `(owner, request_id)` 作为主键，保存规范请求摘要、原设备 ID、`journey_start`、结果 revision 与完成时间。设备 ID 不设删除级联，撤设备后仍能核对本人原回执；最新播放状态不可读取则返回 null。每成员最多10000条操作，成功重放先于新增限额检查。未授权成员不能读取他人回执。

## 接口

新增成员接口沿既有 JSON、同源、CSRF 及首尾会话核验；电视不能调用。路径 ID 为24位小写十六进制，requestId为32位。示例中的字段均为结构说明。

### POST `/api/media-playback/devices/<id>/journey-preview`

精确请求：`{revision, journeyId, routeId}`。revision为当前播放版本的整数，0表示尚无播放行；routeId为有效ID或显式null。路线非空时须属于该旅行且当前共享，否则404。预览不写数据库。

返回 `{previewToken, expiresAt, playbackRevision, sourceVersion, journey, mediaCount, routeStatus, route, canStart}`。routeStatus为 `not_selected|available`。有合法媒体或至少一个可展示路线站点时canStart为true，仅标题不构成可播放内容。Token最长5分钟，HMAC绑定用途、会话、家庭、设备、三个输入及当前授权候选摘要；不以明文摘要暴露隐蔽对象。

### POST `/api/media-playback/devices/<id>/journey-start`

精确请求：`{requestId, previewToken, confirmStart:true}`。新操作在同一写事务内核对设备、会话、预览来源及原播放revision，再原子写旅行范围、photos模式、首项进度、审计/meta和操作回执。没有半次生效。

返回 `{operation, playback, replayed}`。operation为 `{requestId, kind:'journey_start', deviceId, resultRevision, completedAt}`，playback是当前成员播放DTO。相同规范请求重放返回原回执，先于Token过期及来源变化检查；同requestId不同请求返回409，不重新开始。

### GET `/api/media-playback/operations/<requestId>`

仅本人：未找到返回 `{found:false}`；找到返回 `{found:true, operation, playback}`，当前设备状态不可读取时playback为null。回执不恢复旧路线或媒体权限。found:false不证明先前请求没有到达或永远不会提交。

### 既有播放 DTO 的新增字段

成员 `GET /api/media-playback/devices/<id>` 与 TV `GET /api/media-tv/playback` 增加：

```text
scope: 'all' | 'journey'
journeyReview: null | {
  status: 'ready' | 'journey_unavailable',
  journey: null | {id, tripId, title, start, end, revision, tripRevision},
  routeStatus: 'not_selected' | 'available' | 'unavailable',
  route: null | {
    id, title, revision,
    stops: [{index, state:'unavailable'} |
      {index, state:'available', place:{id,name,country,city,coordinates,
        coordinatePrecision,coordinateGridDegrees,status,startDate,endDate}}],
    segments: [{fromIndex,toIndex}]
  },
  sourceVersion: <64位不透明摘要>
}
```

journey日期来自当前旅行实体，路线最多100站。字段不含owner、可编辑标志、私密坐标、金融数据、原plan或媒体来源URL。route-only保留photos模式，`photoCount=0,item=null,progress=null,canStart=true`。原旅程不可用时这些值为空／零，scope仍journey，canStart=false。

现有 `start` 明确清旅行范围并开始全相册，`dashboard` 清范围并回看板。pause/resume/interval/next/previous保持范围；无媒体时next/previous拒绝。所有控制与TV进度请求重新核当前选择和授权。普通相册原语义保持。

### 错误与恢复

400字段无效；401身份失效；403权限、CSRF或无可播放内容；404设备／旅行／指定路线不可用；409版本、候选来源变化或同requestId异请求；410预览过期；429记录限额；503暂不可核验。前端使用清楚的操作提示，不展示任意错误正文或内部代号。

开始结果未知时先GET原回执，不能自动另建请求或重复开始。内存仍有原确认载荷时，明确重试只能沿原requestId与Token。刷新可仅保留成员身份、设备ID、requestId的最小恢复标识，不存Token或私人DTO；恢复前核验身份，先读回执再读当前播放。无法证明旧结果时展示当前状态和明确核对／退出入口，不声称原操作失败。成员或家庭变化清除旧内容与匹配的恢复标识，迟到响应不能回显。

## 验证与交付范围

后端覆盖真实SQLite持久化、两户两设备隔离、首尾成员校验、CAS和原回执恢复、撤路线／地点／媒体许可、删除旅行、route-only及原照片视频进度。前端覆盖字段投影、租约、隐藏、原请求恢复及路线几何。组合浏览器使用真实临时Flask/SQLite和配对Cookie，手机390px／桌面1280px加电视1920px；视频观察真实解码与ended，不用墙钟或模拟成功代替。

发布前需精确75→77迁移、旧表／数据／settings／序列保全、非空77启动、部分失败及完整组恢复的隔离验证，另做实际镜像和独立审查。真实云账号、实体电视及本人完整场景C验收另记，当前不能宣称完成。
