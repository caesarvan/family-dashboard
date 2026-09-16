# 家庭物品应用接入

本候选把已审 [库存核心](INVENTORY-MODEL.md)、[HTTP API](INVENTORY-API.md) 与 [库存界面](INVENTORY-UI.md) 接入真实应用。主导航及手机“更多”中的“家庭物品”进入 `#inventory`。当前为手工物品、批次和明确实物操作；没有金融订单自动入库、自动记账、补货任务或电视库存展示。

`create_app` 在成员认证及媒体注册之后调用 `register_inventory(app, db, Problem)`，使用当前户的同一请求连接，extension 为 `inventory`。子户由原 `HouseholdPlatform.child` 调用相同工厂，不另建通用库存数据库。注册核心五表后为 **53 张户内表 + 2 张平台表**；新增 13 个方法/路径组合。已有库存 DDL 必须精确匹配，漂移会拒绝启动；不会在每次请求中补表。完整备份须包含五表与不可变回执。

本分支只在独立临时数据目录执行初始化与重启验证。生产从 48 表升级到 53 表需要另行审查的迁移、备份恢复和发布准入，不能用启动新镜像来代替迁移验收。本候选没有连接服务器或操作生产库，没有修改既有迁移控制器、个人导出或媒体 worker 配置。

HTML 加载库存 CSS/JS 后再加载 product shell；Docker COPY 增加 `inventory_core.py` 与 `inventory_api.py`，发布白名单增加 API，静态目录沿用原收集方式。库存不读取外部字体、SDK、云账号或地理服务，没有新依赖或环境变量。

进入页面时调用 `InventoryUI.mount(node,{})`。同身份、同路由的看板轮询或主题刷新同步复用同一节点、还原输入焦点与选区，并通知 `notifyStateChanged()`；不重新挂载和覆盖草稿。离开页面调用 `unmount()`；登录、退出或成员/家庭/auth version/CSRF 变化调用 `notifyIdentityChanged()`。写入未知结果仍由模块保留原请求 ID 与载荷，并等待用户明确核对；切页不表示已经取消服务器操作。

电视渲染继续走原只读看板，没有库存导航、挂载或 API 请求。即使手工请求库存 API，实际 TV cookie 也被拒绝；演示模式只显示登录说明。所有主题沿用现有 CSS 变量，手机入口位于“更多”。照片和旅行路由的既有挂载与权限保持。

## 隔离验证

```powershell
python -B -m pytest tests/test_inventory_runtime.py tests/test_inventory_api.py tests/test_media_runtime.py -q
node --check static/app.js
node --check static/product-shell.js
```

新 runtime 测试直接使用真实 `create_app`，不补注册：精确五库存表/53 总表、单次路由注册、同 SQLite 连接、原请求重试与重启、邀请创建第二户及真实 WSGI 路由、四成员隔离、私有/共享撤回、CSRF、真实配对 TV 拒读、既有媒体 API、schema 漂移拒绝、发布压缩包与加载顺序。API 夹具只在 extension 缺失时补注册以保留独立模块可测试性；已接线工厂直接复用 extension。媒体 runtime 的两处总表数断言更新为 53，四张媒体表及业务断言保持。

浏览器闭环由独立候选在冻结运行源码上使用 strict factory 与原始 HTML 执行，结果单独记录，不把合成 HTTP 界面测试当作真实 API 验收。此文不声称已经完成生产迁移、Linux 镜像构建或实体电视验收。

作者实际分段验证为库存 runtime 6 + HTTP 68，共 74 项通过；既有媒体 runtime 18 项另轮通过。首轮新测试有两处测试错误（平台邀请表名称与 Windows 文本编码），原失败保留，修正后六项全部重跑；不是将失败改为跳过。三项 JavaScript 语法检查通过。日志与 JUnit 位于 ignored `test-results/inventory-runtime/`，不含真实账户或库存。
