# Expo Web 静态接入

实际上线状态以 [HANDOFF](HANDOFF.md) 为准。本模块只接入 Expo Web 编译产物与原 Flask API，不改变 Cookie、CSRF、家庭隔离、数据库或云端授权；不等同 iOS／Android 原生验收。

`frontend/app.json` 使用 `web.output: single` 与 `experiments.baseUrl: /app`。集成人把实际构建输出逐字复制到 `static/experience/`，生成并核对发布包中每个产物的 SHA；它是生成资产，不提交 node_modules、开发服务器、源码映射或秘密。Docker 必须包含 `frontend_runtime.py` 和完整 `static/experience/`（现有 `COPY static ./static`）；构建／发布脚本由集成人维护，本模块不会在容器启动时执行 Node 或下载文件。

| URL | 行为 |
| --- | --- |
| `/` | 安全的 `static/experience/index.html` 存在才 302 到 `/app`；尚未构建则显示旧首页 |
| `/app`、`/app/` | Expo index；没有构建则 404 |
| `/app/<客户端路由>` | 无扩展路径回退 index，支持刷新与直接打开 |
| `/app/_expo/...`、`/app/assets/...` | 仅实际存在且允许的 JS／CSS／字体／图片；缺失资产 404，不能回退 HTML |
| `/classic` | 独立旧前端，供尚未迁移的高级操作使用；原 hash 页面可用，如 `/classic#photos` |
| `/tv`、`/demo` | 保持旧页面和原有电视／演示判定 |

只公开 index 和允许的公共静态类型，拒绝 JSON、map、Python、隐藏文件、任意其他 HTML、路径穿越、反斜线、Windows 驱动路径及任何 symlink／junction。旧 `/static/experience/...` 别名也拒绝，防止绕开新入口检查。所有新页面及资产设置 `Cache-Control: no-store`，由正常发布包提供不可变字节；资产类型不匹配时不返回 HTML。静态目录属受控部署内容，不能接受用户写入；路径检查不承诺对同时恶意替换目录的写入者提供文件系统沙箱。

Nginx 原配置仍全部反代 Flask。`/api`、`/auth`、`/space/<slug>` 使用原服务器；不得给 SPA fallback 吞掉这些路径。现 CSP 仅允许同源 JS／连接／字体，style 允许内联；实际构建须确认没有内联 JS、eval 或外站依赖，不因模板需要放开策略。Expo 页面不应同时加载旧 `app.js`／`product-shell.js` 以免双重登录、轮询和 DOM 渲染。

启动顺序：`GET /api/me` → 未登录时 JSON `POST /api/login` → 再 `GET /api/me` → `GET /api/state`。所有 fetch 使用同源 Cookie；写请求携带新 `X-CSRF-Token`。新本地待办显式 `sourceId:""`，避免省略时写共同云清单；编辑／删除携带单条 revision，409 重读后明确确认，网络未知不自动创建重复记录。详细字段见 [基础 API](API.md)。家庭切换继续顶层导航 `/space/<slug>`，清客户端身份缓存后重新登录；该接口原有 303 返回 `/`，会由新入口继续接入。

`tests/test_frontend_runtime.py` 使用合成导出目录验证文件／路由边界，并通过真实 Flask 工厂验证 CSP、旧页面、登录、CSRF、同源检查和本地 CRUD／冲突。不代表实际 Metro 导出、React 浏览器、真实 Google 或生产已通过；这些需在组合构建后单独验证。
