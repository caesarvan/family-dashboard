# Expo 前端交付

已于 **2026-09-16 21:59:19（北京时间）** 实际上线，21:59:51 服务器正常 TLS 读回通过。本期把常用操作迁入 React Native／Expo Router／React Native Web／React Native Paper，保留原 Flask API 与数据；当前身份也见 [HANDOFF](HANDOFF.md)。

## 使用范围

- 登录、首页、今日／本周／前后三天日程、待办和采购使用新版。手机底导航、电脑侧栏、新建菜单及晨光／森林／海岸主题统一；首页默认先显示日程和共同资金，保留已保存的卡片顺序与隐藏偏好。
- 本地待办可新增、修改、勾选；采购可记录数量、预算、备注和参考图片。revision 冲突保留草稿；创建结果不明时禁止重复保存，先关闭并读回核对。采购预算不会自动计入支出。
- 财务与旅行提供概要，详细账本、旅行编辑、相册、地图、家庭物品、助理、账户连接及布局管理仍在 `/classic`；这是阶段性保留的工作入口。`/tv` 继续配对后的只读电视界面。
- 既有 Cookie、CSRF、当前成员／家庭和服务端权限保持。新增待办前可选择已连接的共同清单或“看板本地待办”；已有主清单时默认选中该清单。本地选项显式使用空 `sourceId`，已有事项的独立发布仍走原流程。

安装有效导出后 `/` 进入 `/app`；已知 OAuth 连接状态返回 `/classic` 原来源选择／照片导入流程。`/app` 页面与 `/classic` 不混载两个外壳；直接打开或刷新客户端页面仍从同源托管读取。公开入口仅提供允许的静态类型，JSON／source map／任意 HTML 和路径绕过被拒绝，详见 [托管契约](EXPO-WEB.md)。

## 设计与开发

项目实际由官方 `create-expo-app` 创建，并执行过 `npx getdesign@latest add expo`；生成的 [expo/DESIGN.md](../expo/DESIGN.md) 是设计依据。使用 Paper 现成控件和图标，不把旧 CSS 覆盖层作为新版交付。

在 `frontend/` 按 [开发说明](../frontend/README.md) 执行 `npm ci`、`npm run typecheck`、`npm run build:web`；输出 `dist/`。本次构建使用 Node `v24.19.0`、npm `11.17.0`，锁文件与输入哈希一并记录。实际登录、保存、CSRF 和 CSP 验证必须使用 Flask 同源托管，不能由跨端口开发预览代替。生产仅托管静态输出，不运行 Metro 或 npm 安装。

本期是浏览器交付；原生 iOS／Android 配置不代表已制作或验证安装包，原生 Cookie／OAuth 返回链路仍待适配。新云写入、本人最终体验与实体电视没有因浏览器测试而自动验收。此前本人 Photos 5／5 预览与明确保存已成功，本期未重做真实 Google 测试。

## 固定构建身份

| 项目 | 值 |
|---|---|
| main | `c74e72c79daa64a9fb9b575db496375b5803b91d` |
| integration／sourceHead | `e00e5c25e0c64f0981913780ffb2024e77a384a7` |
| tree | `967ba95a0438bea7c405e1590adaa82af22d141e` |
| 发布包 manifest | `ac7409cfd150b45cfc575007187138cf90f7b38f1c1f2e212d5d8c5877a1fa9b` |
| 源归档 SHA256 | `45dd88b5a2a9b21f5ef1c6e70ce0eab6d82a44547eba403666176c30fee4446b` |
| 构建证据 SHA256 | `4ed5633ec1c6bd6e553af7b0c30a3e6f15763d95fedd82ef5ba6bb2517652c23` |
| 不可变镜像 | `sha256:91857b8df087feb942a730f876cdbb9392a76508046e59ba50ec133885f95400` |
| 导出入口 | `entry-9f8043b59bbd1eff3305729bc114375b.js` |
| 范围 | 427 源文件／112 运行文件／23 导出文件；53 张户内表与 2 张平台表，无迁移 |

导出证据最初绑定 sourceHead `deacbef`，与上述 main／integration 同树；后续 Git 合并没有改变构建输入字节。75 项公开静态资源已通过正常 TLS 逐项读回；23 个导出文件中的构建 metadata 不对公网开放。Windows、真实临时浏览器、视觉和 Linux 结果按各次原件分别记录于 [VALIDATION](VALIDATION.md)，不拼成一轮全套测试。

## 发布与恢复边界

本轮私有 `expo-release-20260916/` 操作将新导出与既有运行文件绑定在同一来源清单：隔离构建和 Linux 验证后，核对旧源／镜像／配置，停止全部写入者，保存完整家庭与平台库备份及旧源码／镜像，新 app 启动后核对完整 53 表及平台注册库保持，再开放 worker／web 并做 HTTPS 读回。实际 1 户两库完成备份和无迁移发布，原配置保持；四服务运行且重启 0、app healthy，发布后备份 service success／timer active。

发布目录 `/opt/family-dashboard-releases/expo-53-20260916T135833130576Z`。原始证据在私有 `expo-package-20260916/server-evidence/` 的 `activation.json` 与 `post-readback.json`，哈希与分段验证见 [VALIDATION](VALIDATION.md)。当前 Windows 的线上浏览器访问被网络过滤页 `Website Filtered` 替代，未进入应用、未完成线上登录操作；服务器正常 TLS 读回与本地真实八组浏览器通过仍分别成立，未改 DNS／代理／安全配置。

可复用的是上述校验步骤；该目录的脚本固定绑定一次发布输入，不能在新基线上重放。不要使用历史 43／44／48 表迁移或要求库存五表为空。恢复仍按 [库存与媒体完整恢复](INVENTORY-RECOVERY.md) 和 [媒体恢复](MEDIA-RECOVERY.md)，恢复前重新核对备份时点之后的权限撤回，media worker 保持停止直至确认。本文为独立交接文档，不改变已冻结的包、导出和构建证据。
