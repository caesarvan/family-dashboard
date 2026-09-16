# 家庭中枢前端

使用 Expo 57、React Native 0.86、React 19、Expo Router、React Native Web 与 React Native Paper。项目由官方 `create-expo-app` 创建，已实际运行 `npx getdesign@latest add expo`，设计参考保存在仓库 `expo/DESIGN.md`。常用控件复用 Paper，不另建 HTML/CSS 控件库。

## 当前范围

- 原生 React Native 组件：首页、今日／本周／前后 3 天日程、待办、采购、登录和导航。待办支持新增与勾选；采购支持预算、数量、参考图片。
- 家庭资金、旅行提供概要；账本编辑、详细旅行、相册、地图、库存、助理、账户绑定等通过同页跳转进入 `/classic` 中的已有功能。
- 本期交付浏览器版本。代码具有 iOS／Android 平台配置，但尚未制作或验证原生安装包。电视继续使用已部署的只读 `/tv`。

## 开发与构建

在此目录运行：

```sh
npm ci
npm run typecheck
npm run build:web
```

构建产物在 `dist/`，不提交 Git。生产基路径为 `/app`。将经过验证的整个导出复制到仓库 `static/experience/` 后，由 Flask 的 `frontend_runtime.py` 提供同源访问；`/` 进入 `/app`，客户端路由刷新仍可访问。没有导出时根路径保留已有界面。禁止直接在生产运行开发服务器。

本地全链路验证也应由 Flask 同源托管导出，以便验证 session cookie、CSRF 和生产 CSP。`npm run web` 只适合界面开发；跨端口访问不能代替登录／保存验收。`EXPO_PUBLIC_API_ORIGIN` 是可选公开 API 地址，不得放密钥，原生端 cookie／OAuth 返回链路尚待单独适配。

## 代码与接口

- `src/app/`：路由、Paper 主题和统一会话上下文。
- `src/ui/`：现成组件库上的布局、主题、导航及编辑弹窗。
- `src/screens/`：各业务页面。
- `src/lib/api.ts`：同源 `/api` 请求；会话只由服务器 cookie 管理。
- `src/lib/household.tsx`：身份验证、状态刷新、偏好和带 CSRF 的写入。
- `src/lib/calendar.ts`：北京时间范围与重叠时间计算。

复用服务器 `/me`、`/state`、`/preferences`、`/dashboard-layout`、`/items/:kind`、`/photos` 等接口，不新增财务计算或账户密钥。详情见 `docs/API.md` 与 `docs/EXPO-WEB.md`。写操作先确认成员／家庭身份，修改带 revision；冲突保留草稿，结果不明禁止直接重复提交。

## 协作与发布

每位 agent 使用独立 `codex/` 分支与 worktree，经非作者审查、组合验证后合并。构建锁文件、源提交、导出文件 SHA-256 与发布 manifest 必须对应；不能把未经验证的 `dist` 覆盖到线上。运行数据、凭据、截图和测试产物不入库。完整部署入口与当前安装身份以根 README、`docs/HANDOFF.md` 和发布记录为准。
