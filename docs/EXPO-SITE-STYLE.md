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
- 保留旧 `skyLight/skyMid` token 以保持调用兼容；首页和登录页不再显示旧天空视觉。共享控件不引入渐变、图片或远程请求。

## 适用范围与验证边界

组合实现覆盖 `frontend/src/ui/theme.ts`、`components.tsx`、`AppShell.tsx`、首页和登录页。所有采用 SectionCard/PageHeader 的 Expo 页面获得共享风格；桌面宽度达到 1040px 时使用横向顶部导航，窄屏保留五项底导航，正文可用宽度最大 1280px。首页保留日程范围与真实数据操作，登录保留原认证流程。经典页面与电视样式未在本轮改动。

各作者使用独立分支和 worktree，经非作者审查后组合；实际构建使用独立安装的依赖，禁止以 node_modules junction 代替受验构建来源。类型检查、浏览器视觉与操作验证、生产发布分别记录，具体结果和固定身份见 [验证记录](VALIDATION.md)、[交接说明](HANDOFF.md)。

## 财务页面的风格延伸（候选已验证，尚未部署）

`/app/finance` 延续白底、黑色胶囊按钮、浅灰大圆角区块和原有正文大小，将共同资金、本人账本和月预算分开呈现；主操作保留「导入账单」与「刷新账本」。手机以纵向卡片和可换行按钮组织操作，桌面展示并列的资金指标；账本每页 25 条，预览记录和错误各每页 24 条。工作表、金额列与来源选择使用标准 Paper Dialog／ScrollArea，长选项可换行；确认关联、预算和资金编辑仍使用 Paper 对话框。

最终真实临时浏览器覆盖 320／390／1040／1440 四宽，产出 19 张截图，其中 15 张经本轮视觉查看。所见导入确认的记录、金额、原编号和按钮完整，四宽退款确认窗稳定且关键操作可见，未观察到阻断性水平裁切或不可读内容。AppShell 使用内部滚动，`full_page` 截图仍可能只包含内部页面当前可见区域；部分手机账本／预算下半部分未获截图覆盖，不宣称全页面视觉或实体电视验收。修订历史及冻结身份见 [VALIDATION](VALIDATION.md)，操作见 [Expo 财务](EXPO-FINANCE.md)。

## 账户页面的风格延伸

2026-09-17 03:01:51发布的 `/app/connections` 继续使用当前官网的白底、黑色胶囊按钮、浅灰圆角区块和简洁文字层级，标准控件仍来自 Paper。手机按纵向卡片组织连接、来源选择和确认，搜索结果每页24项；桌面两列平台入口配合单列账户详情，长名称和按钮允许换行。320／390／1040／1440 四宽的真实临时浏览器截图含账户、来源、保存确认和断开确认，并另拍首页手机／桌面两张。最终18张均经过查看，8个对话框在入场动画完成后核对为不透明浅灰背景；原动画中截图不计视觉验收。源码、构建及发布身份分别见 [账户界面](EXPO-ACCOUNTS.md)、[验证记录](VALIDATION.md)。

## 风格首发历史：2026-09-16 23:48

北京时间 **2026-09-16 23:48:34** 激活，**23:48:49** 正常 TLS 读回通过。本表绑定当次风格首发包，不是现在的最新版本；当前身份见 [README](../README.md) 和 [验证记录](VALIDATION.md)。随后文档修订不改写该历史 manifest。

| 项目 | 固定身份 |
| --- | --- |
| main／integration | `d94f7ce746bfbc45de328c516ac9c24d640f2d40`／`5ebfd2d6db408128f8137de288f300900794b1bb` |
| 同一文件树 | `f57a232684180d72a0254d04bdbf3f1d15ae6f89` |
| 运行镜像 | `sha256:befe93434119bf8bb5a58423895174ed7093b9a1b8ae8f1e41be06f2ab87c0bc` |
| manifest SHA256 | `b598f920c49a07b9b9bebbbaa32f53e62b6e2110f33a4cf75c061962900cdf04` |
| 源码包 SHA256 | `f387fb26b5762ca8febd3328cff8b4b18079fc10c86a8b721a8af67118f742f4` |
| Expo 入口 | `entry-a0ac451d56b8db645808c1e5a9436b32.js`，23 个导出文件 |
| 发布目录 | `/opt/family-dashboard-releases/expo-site-53-20260916T154748616831Z` |

四种宽度 320／390／1040／1440 的真实临时浏览器验证及独立视觉审查通过，镜像内 Linux 63 项通过；447 源／112 运行／75 公开静态文件读回匹配。实际 1 户两库完整备份，53+2 表和配置保持。原件、计数和边界见 [验证记录](VALIDATION.md)。未以本次样式发布代替真实云账户、原生安装包或实体电视验收。
