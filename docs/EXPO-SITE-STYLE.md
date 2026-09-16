# 当前 Expo 官网视觉参考

本轮按用户要求直接参考 [expo.dev](https://expo.dev/) 当前界面。根代理于 2026-09-16 使用真实 Edge 留存桌面、功能区和手机截图，以及 `computed-styles.json`；私有参考目录为 `family-dashboard-access/expo-site-reference-20260916/`。本模块作者已查看三张截图与实测字段。它们是视觉依据，不是家庭看板的已发布截图。

本次参考优先于较早获取的 `expo/DESIGN.md` 中出现的浅蓝天空、12px 卡片等旧描述。旧文件和发布历史保持原样。本轮将官网的文字层级、黑色胶囊按钮、浅灰大圆角区块转为适合家庭操作界面的共享样式，不复制 Expo 标志、产品插画、文案或营销内容。

## 实测与应用

| 项目 | 官网观察 | 本轮共享控件 |
| --- | --- | --- |
| 主文字／背景 | `#1c2024`／白色 | `expoTokens.ink`／`canvas` |
| 浅灰区块 | 功能区采用浅灰大圆角，约 32–40px | `canvasSoft: #f8f8fa`；SectionCard 桌面 32px、手机 24px |
| H1 | Inter，48／52.8，600，字距 -1.2 | `displayMedium` 对应实测值；普通页面标题缩为桌面 36／40、手机 28／32 |
| 操作按钮 | 黑色，主 CTA 高 40px、胶囊形，14px／600 | Paper Button 使用黑色 primary、14／20／600；默认 40px 高时为胶囊 |
| 内容最大宽 | 1280px | 暴露 `contentMaxWidth: 1280`，由外层 AppShell 使用 |
| 正文与清单 | 14–16px，字重 400 | 现有正文、清单和说明字号保留，不放大为营销标题 |

字体仍使用现有 Inter 优先的系统回退栈；不下载字体、不增加依赖。没有本机 Inter 时会回退系统字体，因此不声称字体文件与官网相同。手机页面标题按产品操作需求采用 28px，而非逐字复制官网手机 48px 的宣传标题。

## 稳定 API 与样式字段

- `makeTheme(): MD3Theme`、`SectionCard({title,action?,children,style?})`、`PageHeader({title,description?,action?})`、`EmptyState({title,description?,action?})` 的调用接口保持。
- `SectionCard` 使用 Paper contained、0 elevation、无强边框浅灰表面。视口宽小于 `compactBreakpoint: 768` 时圆角 24／内边距 20；其余圆角 32／内边距 28。调用者已有 `style` 仍最后应用，可明确覆盖。
- `PageHeader` 同一断点选择 28／32 或 36／40 的 600 字重标题；描述仍为 14px，长标题和操作继续允许换行，不设置截断。
- 新增 `buttonRadius: 999` 供较高的独立 CTA 明确使用；`cardRadius: 32`、`cardRadiusCompact: 24`、`contentMaxWidth: 1280` 和 `compactBreakpoint: 768` 供其他作者保持一致。
- 全局 Paper `roundness: 5`：当前已安装 Paper 的 MD3 Button 乘 5 得到 25px，在默认 40px 高按钮上形成胶囊；普通 Card 乘 3 为 15px，TextInput 默认 5px。不会把所有控件都变成 999px 圆角。共享 SectionCard 显式设置 32／24；业务输入框继续显式 `outlineStyle={{borderRadius:8}}`，对话框继续按各自约定控制。
- 保留旧 `skyLight/skyMid` token 以保持调用兼容；本轮首页／登录作者独立移除旧天空视觉。共享控件不引入渐变、图片或远程请求。

## 适用范围与验证边界

改变只涉及 `frontend/src/ui/theme.ts`、`components.tsx` 和本文。所有采用 SectionCard/PageHeader 的 Expo 页面会获得共享风格；首页、登录、AppShell 的具体布局由各自独立分支负责。未改业务请求、权限、数据、路由、表单行为、经典页面或电视，也未构建 bundle。

本分支用已安装的 `expo-n2` 依赖仅执行 TypeScript 检查。不会将依赖 junction 用于 Metro 构建。实际组合外观与手机／电脑浏览器行为，须在合并候选中另验；单独类型检查不代表视觉验收或已发布。
