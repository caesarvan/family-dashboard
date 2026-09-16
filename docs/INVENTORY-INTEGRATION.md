# 库存真实本地浏览器闭环

`tests/browser_inventory_integration_check.py` 用真实 Edge 操作 [库存 UI](INVENTORY-UI.md)，通过真实 Flask 的当前成员 Cookie／CSRF／家庭路由进入库存 API、核心和临时 SQLite。没有同名合成库存接口，没有直接插入物品／数量／回执替代点击。账户、家庭与物品都是合成内容，禁止浏览器外站和 Python 非 loopback socket，不接云或生产。

默认模式只在首请求前显式调用真实 `register_inventory`，并增加挂载 UI 的 HTML 与同源 bootstrap JS。保留应用原 CSP，不开放 inline script。两者是测试 bootstrap；结果的 `registration` 明确标记 fallback，不把它当作正式工厂或导航接线证明。

本地服务使用临时自签 TLS，`PUBLIC_ORIGIN` 与准确的 loopback 地址／端口一致，保留实际来源检查与 Secure Cookie；Edge 仅在这个隔离上下文接受临时证书。这不证明公共 TLS 或生产配置。

```powershell
python -B -X utf8 tests/browser_inventory_integration_check.py
```

正式工厂合入后，可以强制每个家庭／重启工厂都必须已自动注册；缺失则拒绝，不补注册：

```powershell
python -B -X utf8 tests/browser_inventory_integration_check.py --require-factory
```

正式 shell 的 `inventory` 路由合入后用完整界面执行；此模式同时强制真实工厂，并且不增加测试 HTML 路由：

手机视口通过实际“更多”菜单进入家庭物品，桌面通过侧栏进入；两者都要求入口可见，不使用强制点击。初版 strict 在手机误用隐藏侧栏而于业务检查前失败，该原件保留，不能计为 strict 通过。

```powershell
python -B -X utf8 tests/browser_inventory_integration_check.py --require-shell
```

流程覆盖：本人创建私密物品；采购批次和两次明确收货；另一真实成员在共享后记录消耗；拥有者归私密后撤销伙伴条目／批次／流水访问；结果未知时按原操作 ID 查回；刷新保草稿、重载和应用工厂重启后的数量／回执保持；真实邀请创建第二家庭后双向隔离。

“丢响应”试验使用 Playwright `route.fetch()` 真正把收货请求提交到本地 Flask，确认真实返回 200 后仅中断浏览器接收。UI 随后读取原 `/operations/<requestId>`；脚本核对 SQLite 中该 ID 只有一条 operation 和 movement，未伪造成功状态，也未用第二次新 ID 重放。其他业务响应原样来自真实服务。

草稿只在当前页内存保留。测试重启前先放弃未提交草稿，之后核对已经提交的 SQLite 数据；不声称页面重载能够恢复未保存草稿。默认 HTML 模式只验证实际 API 状态读取后的挂载通知；完整 shell 的 `refresh(true)` 只在 `--require-shell` 模式执行并记录。

每次生成新的 ignored `test-results/inventory-integration-<UTC>/`，保存实际 Git HEAD、完整源码前后 SHA、注册方式、通过步骤、JS／外站错误、移动和桌面截图。失败强制非零退出并保留原件；先关闭浏览器与服务器，再清理临时 SQLite。

该脚本不验证线上数据库迁移、Docker 恢复、财务来源、补货任务、AI、外部云服务或实体电视；不执行生产操作。待批准 API、UI 和接线固定组合后才能记录相应模式为通过。
