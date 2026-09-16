# 家庭中枢前端

使用 Expo 57、React Native 0.86、React 19、Expo Router、React Native Web 与 React Native Paper。项目由官方 `create-expo-app` 创建，已实际运行 `npx getdesign@latest add expo`，设计参考保存在仓库 `expo/DESIGN.md`。常用控件复用 Paper，不另建 HTML/CSS 控件库。

## 当前范围

- 原生 React Native 组件：首页、今日／本周／前后 3 天日程、待办、采购、登录和导航。待办支持新增与勾选；采购支持预算、数量、参考图片。
- 相册支持真实图库、详情编辑、家庭共享、逐电视许可和 Google 选片/确认；旅行支持基本计划、准备/采购、预览和确认；助理支持真实请求预览、选择性保存和执行回执。资金仍提供概要，详细财务、复杂旅行分段/资料/云发布、地图、库存及账户管理可进入明确标注的 `/classic` 功能。
- 本期交付浏览器版本。代码具有 iOS／Android 平台配置，但尚未制作或验证原生安装包。电视继续使用已部署的只读 `/tv`。

## 视觉规范

网页按用户最新要求参考 [Expo 官网](https://expo.dev/) 当前界面，具体依据见 [官网风格与应用](../docs/EXPO-SITE-STYLE.md)：白底、近黑文字、黑色胶囊按钮、浅灰大圆角区块和清楚的标题层级。登录页去除天空渐变，业务页面继续使用 Paper 组件；输入框保留适合编辑的 8px 圆角。Inter 优先，中文使用系统回退，不加载外部字体。当前实页参考优先于较早生成的 `expo/DESIGN.md` 视觉描述。

按用户最新要求，Expo 不继续旧 forest/ocean 风格或旧主题切换；旧服务端偏好只供经典页和电视使用。前端统一 tokens 在 `src/ui/theme.ts`。配套契约见 [页面与视觉接缝](../docs/EXPO-NAVIGATION.md)、[相册](../docs/EXPO-PHOTOS.md)、[旅行](../docs/EXPO-TRIPS.md)和[助理](../docs/EXPO-ASSISTANT.md)。具体安装版本仍以根 README 和发布记录为准。

桌面视口宽度达到 1040px 时使用顶部横向导航，直接进入首页、日程、待办、采购、旅行、相册和助理；更多菜单收纳资金、家庭物品、地图与设置。窄屏保留首页、日程、待办、采购、更多五个底部入口。账户与新建菜单沿用原有操作，修改样式不改变数据或授权规则。

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
