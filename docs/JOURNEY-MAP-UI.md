# 家庭足迹地图界面

此候选只提供 `static/journey-map.js`、`static/journey-map.css` 和合成契约浏览器测试；应用注册、主导航、静态发布与 Docker 接入由集成人负责。它消费持久化地点 API，不在浏览器本地保存地点。功能分支的合成 API 测试不能替代组合后真实 `/api/journey-places` 的验收。

## 接入契约

先加载原应用提供的 `api`、`user`、`csrf`、`isTV`、`isDemo`、`canEdit`、`openModal`，再加载地图脚本；地图 CSS 与应用主题共同加载。现有 `api('/journey-places')` 自动加 `/api` 前缀，模块没有独立鉴权、外部网络服务或密钥配置。

```javascript
const view = JourneyMap.mount(container, {
  openJourney: (journeyId, options) => JourneyUI.open(journeyId, options)
});
// options 为 {placeId}；journeyId 是 workflow.id。
// 主页面地图保留在原地，关联旅行使用既有 JourneyUI 对话框。
JourneyMap.notifyStateChanged(); // 同一身份普通轮询：不刷新或清空编辑草稿
JourneyMap.notifyIdentityChanged(); // 登录、家庭、身份版本、CSRF 或电视身份变化时立即调用
JourneyMap.unmount(); // 离开路由
```

`mount` 返回 `{refresh, unmount}`；同时只保留一个实例。`JourneyMap.openView({openJourney})` 可在现有宽对话框中挂载，关闭对话框即清理。一般地图入口优先使用主页面 `mount`，让关联旅行自然返回地图；不要重写现有旅行内部返回桥。

宿主每次重绘时必须保留同身份、同路由地图的原容器节点，在同一个同步调用中取下并重新接回。模块的 MutationObserver 在微任务时检查连接状态；跨微任务卸载容器会清空模块状态。离开地图或身份变化直接清理，不能靠隐藏节点保留成员私密数据。宿主应在修改身份/家庭/CSRF 的同一同步流程调用身份通知，且登录界面也调用。

本模块不增加电视入口；TV、演示及非成员在 `mount` 即拒绝读取地点，TV 的 `openView` 直接返回。后端仍必须独立拒绝全部 TV 地点 API。

## API 与隐私

首次读取将 `/api/journey-places`、`/api/state`、`/api/journeys` 与同源底图合为只读批次，以 `/api/me` 在批次前后核对成员 ID、家庭 ID、auth_version 与 CSRF。每次操作还绑定当前节点、路由、实例及请求代次，旧响应不会写回新成员界面。身份通知和卸载立即清理 DOM、列表、成员、旅行选项与草稿内存；仅公共底图允许跨实例缓存。Cookie 在最终身份检查后单独变化无法被网页原子观察，宿主身份通知和后端权限检查仍是必要边界。

地点协议以 [JOURNEY-PLACES.md](JOURNEY-PLACES.md) 为准，全部字段 camelCase。三种状态为 `visited` / `planned` / `wish`；年份按开始至结束日期区间筛选，不会按过去日期自动推断到访；成员筛选是记录创建者，不表示同行成员。旅行筛选与写入使用 workflow.id，打开关联旅行传 `place.journey.id`。

默认仅自己可见、隐藏共享坐标。自己编辑时保留原精确经纬度，详情另列后端返回的 `sharedCoordinates`。其他成员只能查看后端投影：hidden 不显示，coarse 显示 0.1° 网格并标注约略位置，exact 才显示精确坐标；`canManage=false` 不提供修改与删除。约略网格不是城市定位。共享的名称、国家、城市、日期仍可透露位置，文字中的住址不会自动净化；录入处明确提示。

记录到访或修改已到访地点的名称、城市、国家、坐标、日期、关联旅行时需要明确勾选确认；仅改变共享范围不要求重复确认。手工经纬度与地图选点均可用；世界概览点选仅作粗略定位，用户可修订为最多六位小数的坐标。地点不依赖照片、预订、财务记录自动创建或标记到访。

## 写入与失败

- 创建时生成 `crypto.randomUUID()` 作为 requestId，网络或 5xx 结果未知时锁住原表单，保留完整原 payload 与原 requestId 重试。后端回执保证幂等；已删除回执的 410 不会自动创建新地点。
- 明确保存成功但 GET 读回失败，只提供读取已保存地点的按钮，不再次创建。读回之后重取实际当前筛选页，再显示数量。
- PATCH 使用 revision。409 或修改结果未知时先读最新记录，保留原草稿，禁止直接继续保存；用户选择使用最新记录或保留草稿采用新版本后，再显式保存。不自动重做未知的修改。
- DELETE 必须经过文字确认并传原 revision，只删除地点、保留旅行。结果未知重试原删除请求；冲突先读当前记录。
- 关闭、返回、切换身份不能取消已经发送到服务端的写入；放弃草稿提示这一点。模块不自动重试写入，草稿仅存在当前成员、当前页面内存中。
- 读取失败清空旧筛选结果，保留当前编辑草稿并给出重试入口。成员或旅行选项读取不全会提示限制；底图不可用仍可用列表与经纬度表单。

列表每页最多 100 条，按 ID 去重，不累积跨页结果。地图仅绘制当前筛选当前页已取得且有可见坐标的地点，并显示总数、本页数、无可见坐标数。服务器分页不保证跨页历史快照，数据变化后应重新读取，不能将当前图宣称为全部家庭足迹。

## 视觉、底图与可访问性

遵循根 DESIGN.md 的白色画布、近黑文字、黑色主操作、Inter/中文系统字体回退、4px 间距节奏、8px 控件与 12px 面板圆角。保留应用 `light` / `forest` / `ocean` 主题设置，两个深色主题使用模板的深色表面与浅色正文。无远程字体。低对比的模板辅助灰与浅红不直接用于正文，改用可读的正文色和深红错误色。

列表、表单标签、键盘操作和状态文字提供地图的等价访问路径。地图点有 44 CSS 像素命中区域，状态同时用文字与圆/三角/菱形区分；不只依赖颜色。地图选点可用方向键移动、Shift 加速、Enter 选定、Escape 返回，并恢复焦点。手机改为单列，控件至少 44px，遵循 reduced-motion，无动画依赖。屏幕阅读器与真实触控设备仍需要独立人工验收，浏览器自动化不代表这些人工检查已完成。

底图只能从 `/static/journey-map-land.geojson` 同源加载，预期为 Natural Earth 110m land FeatureCollection，支持 Polygon/MultiPolygon，投影为简单等经纬度 SVG。它展示公共海陆概览，不提供街道导航、地理编码、外部瓦片、SDK 或位置推断。根资产候选由集成人独立审查/接入，UI 分支不复制该 GeoJSON。资产解析限制要素、顶点和坐标范围；加载失败回退到可读列表。

## 本候选的验证方式

```powershell
node --check static/journey-map.js
uv run --no-project --python 3.14 --link-mode copy --with Flask==3.1.2 --with playwright python tests/browser_journey_map_check.py
```

测试使用真实本地 Edge 和模块代码，以合成内存 API 模拟投影、回执、失败和 revision 冲突；不导入或验证实际新地点后端，也不使用真实家庭数据。底图从当前工作树已集成文件或只读 `git show 05855471f407d41337a842e1fea05c76dddc03f0:static/journey-map-land.geojson` 取得；证据记录实际资产 SHA-256，不写回源文件。测试限制网络到 loopback，记录源码前后哈希、控制台错误、合成截图及 JSON 结果到忽略目录 `test-results/journey-map-ui/`。首次准备 Python 包需要开发环境包下载，浏览器用例运行本身禁止外站请求。

组合后集成人需补真实 SQLite API 的成员/家庭/TV/CSRF、创建重放、共享撤回、删除回执、旅行删除解绑、持久化刷新，以及真实主导航轮询、身份切换与 JourneyUI 返回验收；同时核对脚本/CSS/GeoJSON 的加载顺序、Docker COPY 和发布白名单。源码审查通过不等于已接入或部署。
