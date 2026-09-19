# 旅行路线接入与个人数据副本

本文件描述路线候选的接线与导出合同，不代表已上线。业务接口和唯一 DDL 见 [旅行路线](JOURNEY-ROUTES.md)。

`app.py` 在旅行工作流、资料、地点注册之后调用 `register_journey_routes`，在个人数据导出注册之前完成三表初始化。子家庭使用同一 `create_app`，每户有自己的路线、站点顺序和操作回执。`Dockerfile` 显式复制 `journey_routes.py`；发布包和 66→69 迁移须同时包含该文件，平台仍为 9 表。仅复制前端无法启用本功能。

`POST /api/portability/export` 的 `personal.journeyRoutes` 包含本人未删除路线；只有明确 `includeShared:true` 才加入 `shared.journeyRoutes` 中其他成员当前共享的路线。自己的共享路线只在 personal 出现一次。`GET /api/portability/summary` 在 personal/shared 中分别提供 `journeyRoutes` 数量。

每条路线仅包含 `id,title,journeyId,visibility,revision,stops,segments`。站位和连线沿用 API 当前授权投影；共享路线的作者也只能导出共享坐标。不可用站点仅为 `{index,state:"unavailable"}`，没有隐藏地点编号或历史坐标，也不会跨缺口连线。可用地点按显式字段白名单导出，不带 `canManage` 或作者的共享预览附加字段。

`coverage.journeyRoutes` 为 `current_visible_ordered_stops_without_receipts`。顺序不代表实际导航或已经到访；副本不含路线删除墓碑、原站点外键、请求编号、源版本 HMAC、请求摘要和历史回执。完整数据库备份另行保留上述恢复资料。个人 ZIP 仍不是可直接导入的数据库恢复文件。

生成 ZIP 后、发送前，在新的写事务内重新核对成员／家庭及所有导出的路线和地点投影。如果共享撤回、位置精度变化、路线删除或内容变化，返回 409 并要求重新导出；会话失效返回 401，不返回过期 ZIP。未发生变化时才记录既有导出审计并发送副本。

专项测试在 [test_journey_routes_portability.py](../tests/test_journey_routes_portability.py)，覆盖真实临时 Flask／SQLite 的导出、显式共享、隐藏槽、坐标精度、生成期间撤权、会话失效以及应用重建后的顺序／回执保存。测试必须在路线 API 与接线合并的候选运行；作者分支只有接线时不能声称运行通过。
