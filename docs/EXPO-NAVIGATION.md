# Expo 页面与视觉接缝

本轮以 `expo/DESIGN.md` 为网页视觉来源：纯白背景、黑色主按钮、近黑文字、冷灰辅助文字、细边框、8px 控件和 12px 卡片。标准交互继续使用 React Native Paper。登录介绍区使用淡天空蓝渐变，其余业务页面不铺渐变；字体使用 Inter 优先的系统回退，中文不依赖远程字体。

用户已明确不继续旧主题风格。Expo 不再按已保存的 forest/ocean 值套用旧配色，也不再提供旧主题菜单；服务端值保留供经典页和电视使用，不进行用户数据迁移。现有三种主题的历史验收不是本轮视觉验收。

## 页面与操作

- `/app`、`/app/calendar`、`/app/tasks`、`/app/shopping`：已实现日常功能。
- `/app/trips`、`/app/photos`、`/app/assistant`：本轮组合相应模块的真实操作，不再把主入口跳转经典页。
- `/app/finance`：保留资金概要；个人账本及详细财务管理仍在经典页。
- 手机保留五个常用底导航；二级页面顶部可一步返回更多。电脑侧栏直接进入旅行、相册、助理。
- 首页和顶部“计划旅行”用受限内部 query 携带一次请求标识及可选旅行 ID，跨路由后由旅行页打开表单或详情；URL 本身不触发保存。
- Google Photos 授权成功固定返回 `/app/photos`；普通账户绑定继续原日历/清单选择页，错误继续原可解释提示。仅转发预定状态，不把 code、token 或任意 next 转给前端。

## 边界

所有业务写入沿用服务端身份、CSRF、revision 和对应模块的幂等确认。屏幕按完整 session signature 重新挂载，账户变化时清空草稿；模块仍自行检查读请求的身份和代次。签名只作内存比较，不保存到浏览器存储或页面文字。

提供方导航只接受 HTTPS、无用户名密码、默认端口的 Google 固定主机。授权只允许 `accounts.google.com/o/oauth2/v2/auth`，选片只允许 `photos.google.com`；选片另开带 `noopener,noreferrer` 的页面，原状态页保留。函数返回值只表示 URL 校验通过，不证明浏览器允许打开标签。

原生 iOS/Android 的账户 Cookie 流程及安装包未在此阶段验收；同源 Expo Web 是实际交付目标。本文件描述候选代码，是否上线以 README、HANDOFF 和独立发布证据为准。
