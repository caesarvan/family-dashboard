# Expo 成员外观与显示密度

本页记录基线 `deab43720f9d1aa2f86593edb6b81ad911a2ca87` 上的样式候选，尚未部署。偏好 API、成员隔离和编辑面板由同轮独立分支提供；本分支只负责主题及布局消费，不保存偏好或改变业务请求。

## 主题与入口

- `makeTheme(colorMode = 'light', density = 'comfortable')` 保留无参数调用。浅色沿用 [Expo 官网参考](EXPO-SITE-STYLE.md) 的白、灰、黑；深色采用深灰背景、浅色正文和反色主按钮，保留现有字号、字重、圆角、内容最大宽度。
- 成员根布局只使用 `HouseholdProvider` 已确认的 `preferences.colorMode` 与 `preferences.density`。未登录使用浅色与舒适密度；成员身份变化后的偏好清理由 provider 负责。旧 `theme: forest/light/ocean` 不作为新版成员颜色选择。
- Web 的 `html`、`body` 背景和 `color-scheme` 跟随当前主题，退出／卸载恢复浅色；不写浏览器存储。原生环境跳过 DOM 操作。
- `/app/tv` 仍在首帧就绕开成员 provider，独立使用 `makeTheme()`。电视自己的主题、布局和照片授权不由成员外观设置改变，见 [Expo 电视](EXPO-TV.md)。

## 密度与覆盖范围

`useDisplayDensity()` 从 Paper 主题读取 `displayDensity`，普通 Paper 主题缺少扩展字段时回退为舒适。密度和窄屏断点是两个独立维度。

| 位置 | 舒适 → 紧凑 | 保留 |
|---|---|---|
| SectionCard | 宽屏内边距 28 → 20；窄屏 20 → 16 | 圆角、标题字号 |
| PageHeader | 缩小标题区间隙及下方留白 | 宽／窄屏各自字号 |
| AppShell | 缩小顶部栏及内容区留白 | 导航、至少 44px 的动作目标 |
| 首页 | 卡片间距 20 → 12、任务行上下留白 10 → 6；共同资金、概览和旅行区同步调整 | 卡片顺序／隐藏设置、金额字号、点击与请求行为 |

HomeScreen 本轮直接声明的按钮与新增外观面板按钮最小高度为 44px；待办勾选使用 Paper 图标控件，实测操作区域 44×44px，保留 checkbox 语义、禁用状态及空格操作，避免原 Checkbox.Android 固定 36px 的操作区域。账户连接、家庭资金与持仓的固定白底、说明文字和提示背景改用主题语义色，防止深色文字落在固定白底上。它们的业务逻辑和内部表格密度不变，共享卡片内边距随主题密度调整。

相册及旅行相册仍有浅色图片占位背景；这是图片区域而非白底表单。静态检查未将这些位置计为全页面深色验收。地图已有 `theme.dark` 分支，电视组件保留独立配色。本候选不能据此声称所有页面、弹窗或实体设备的深色视觉均已通过。

## 实际检查与待组合验证

`node --experimental-transform-types --test tests/test_expo_appearance_theme.mjs` 实际 **7 项通过**。它加载真实主题工厂，仅替代 Node 无法运行的 Paper／React Native 外部框架默认值；验证主题语义文字配色至少 4.5:1 对比度、深色层级、默认兼容、密度只改空间、字号一致和 44px 下限，不代表组件渲染验收。

使用已安装的真实 Expo／Paper／React Native 类型，对本分支 8 个运行文件及其导入执行严格 TypeScript 检查：仅有尚未合入的 `Preferences.colorMode` 一项依赖错误，其余无诊断。需合入同轮偏好类型／provider 后执行完整 typecheck、构建及真实浏览器检查浅深两色、两种密度、手机／电脑、保存后即时应用、身份变化恢复与电视隔离。当前未进行这些组合浏览器验证，也未新增依赖或改变数据库。
