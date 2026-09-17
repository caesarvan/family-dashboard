# Expo 旅行地点

本页描述新增组件候选，实际部署以 README 为准；入口与地图返回由集成人接线。

旅行详情打开「旅行地点」，从已经保存的目的地中选一项。面板重新读取当前旅行，再带入城市、国家和停留日期；用户核对后点「确认保存地点」。新地点默认为**已计划、仅本人可见、隐藏共享坐标**。位置可以留空，只有手工填写的经纬度进入提交，不推测坐标、地理编码或实际到访。

本次旅行已有地点每页 24 条，保留无坐标地点；本人可编辑，家人明确共享的地点只读。没有自动去重或目的地与地点的一对一绑定，不把第一页当完整列表。共享需要明确选择，并提示名称、城市及日期同样会被共享；不自动授权照片或电视。已有到访地点修改事实字段须重新明确确认，入口不会把计划自动变成到访。

保存后可「在地图查看这个地点」，或者返回旅行。地图导航只传本次 workflow ID、选中地点 ID、页码与筛选；重新读取当前权限和关联，私密 DTO、草稿、原操作标识不写入 URL 或 localStorage。取消草稿不会创建地点。

## 接口与实现

`JourneyPlacesPanel` 默认导出，参数为 `{journeyId: string, onOpenMap: (view: MapView) => void, onBack: () => void}`。内部从 `useHousehold` 取得完整身份；父组件负责旅行与地图往返。`journeyPlaces.ts` 严格投影目的地、校验日期、Unicode 字符数、手填坐标及新建字段，不接受源数据中的 owner、共享、坐标或到访指令。

复用 `GET /api/journeys/<workflowId>` 和 [地点 API](JOURNEY-PLACES.md) 的分页、详情、创建及修改。POST／PATCH 携带可选 `expectedJourneyRevision`，在既有 `BEGIN IMMEDIATE` 事务内核对旅行版本；PATCH 同时核对地点 revision。未携带的新旧地图操作保持既有契约，没有新路由、schema、依赖或外部服务。

旅行或地点版本变化时保留输入，读取最新版本后展示比较，由本人点「已核对最新旅行」再提交；目的地已移出旅行则需取消草稿后重新选择。POST 结果未知时冻结原 body／requestId／expectedJourneyRevision，点击「核对原创建」安全重试；之后的错误不抹除第一次未知结果。历史成功请求先重放当前地点，再检查新建依赖，不因旅行改期或删除而重复创建；软删除原地点返回 410，不复活。PATCH 未知时先读取当前地点并保留输入，重新确认才可再次修改。

请求成功与错误均经过前后 `/me` 复核，包含家庭、成员、认证版本、CSRF 与当前代次；离线、后台、路由失焦隐藏私人内容，恢复只读取并核对，不自动重发。完整身份变化重新挂载并清除旧输入。

## 验证边界

`tests/test_expo_journey_places.mjs` 使用合成 DTO 验证白名单、最多 20 个目的地、Unicode／日期／坐标、planned/private 默认值、到访确认、两种 revision、未知意图保留和身份 fence。`tests/test_journey_place_source_revision.py` 使用实际临时 Flask／SQLite 验证事务版本冲突、原摘要兼容、历史重放及零写失败，另跑既有地点 API 回归。

组件作者的 Node／语法和 API 检查不代替组合 TypeScript、浏览器、四宽视觉或真实用户验收。地图底图与坐标选取沿用原地图入口；云日历、真实模型、实体电视及完整跨模块场景不在本增量范围。

本分支作者实际验证：Node 11 项通过，helper 严格 TypeScript 与 TSX 语法检查通过；两组 API 共 115 项通过（64.92 秒）。首轮 114 通过、1 项失败，原因是既有工厂测试仍断言旧 53 表；改为当前 `check_investment_operation_migration` 的精确 55 表集合后完整重跑，未忽略额外或缺失表。原件保留于 ignored `test-results/journey-place-source-revision-r1.xml`／`r2.xml`，两次不相加。
