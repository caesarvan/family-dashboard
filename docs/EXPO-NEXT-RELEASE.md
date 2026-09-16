# Expo 统一设计与旅行、助理、相册

本轮已于 **2026-09-16 23:02:11（北京时间）上线**，23:02:30 发布后读回通过。旅行、助理和相册主流程直接在统一 Expo 界面完成；以下记录功能范围、实际发布与验证边界。此前 21:59 的安装记录保留于 [首期 Expo 发布](EXPO-RELEASE.md)。

## 可以完成的操作

- **统一界面：** 网页按 [expo/DESIGN.md](../expo/DESIGN.md) 使用纯白背景、黑色主按钮、近黑／冷灰文字、细边框、8px 控件和 12px 卡片。登录介绍区保留规范中的淡天空蓝；标准控件来自 React Native Paper。Expo 不再显示森林／海岸主题菜单；旧偏好保留给经典页与电视，无数据迁移。
- **旅行：** 列表与详情、基本日期和目的地、预算、准备清单与采购可在新版操作。先预览变更，再明确保存；首页“查看行程”先进入详情，需要修改时再点“编辑旅行”。冲突保留草稿，结果不明沿用原预览和幂等请求，不能另建一份冒充重试。旅行预算、采购实付不会自动记入财务或重复合计。见 [旅行契约](EXPO-TRIPS.md)。
- **家庭助理：** 默认本地整理；可逐次选择已配置 AI，并独立选择是否发送近期标题。预览后勾选需要的待办／采购，再确认保存并查看实际回执。搜索当前可见的日程、清单、旅行、照片说明和地点文字，不调用模型，不含尚未合入的库存搜索。结果不明先读最新清单，再由用户明确继续原计划 ID 和选项，不按标题猜测是否执行。见 [助理契约](EXPO-ASSISTANT.md)。
- **相册：** 本人／家人共享图库、照片说明和手动旅行关联、私密／家庭共享及逐台 TV 许可。Google 选片先同意临时处理，预览后另行同意持久保存，并明确只保存当前勾选的 N 张；成功、失败、跳过、处理中与已保存分开显示，历史缺失结果标为未知。创建已返回而后续 GET 失败时保留原 requestId。照片仅以同源授权预览展示；共享家庭不等于授权所有电视。见 [相册契约](EXPO-PHOTOS.md)。

电脑从侧栏进入旅行、相册和助理；手机从“更多”进入。Google Photos 授权成功返回 `/app/photos`，普通账户连接与错误仍衔接原流程。身份变化清空页面草稿和私密结果；每次读写继续核对当前家庭、成员、CSRF 和版本。新建普通待办仍可选择已连接共同清单或本地；助理确认创建的待办／采购只写看板本地，不自动发布到云端。

## 仍使用 classic 的能力

详细个人财务、家庭物品、地图与地图相册往返、照片按时间推荐旅行、账户及设备管理、首页布局设置继续通过明确标注的 `/classic` 入口使用。旅行的复杂 v2 航班／住宿／时区编辑、资料夹、云发布与逐项冲突选择也暂保留经典页；新版编辑会保留现有 v2 数据，不降级。资金概览仍在 Expo，电视维持原 `/tv` 只读布局。

不自动下单、订票、付款、写金融账或确认到访。视频播放、自动回忆精选、原生 APK／iOS 包及原生 Cookie／OAuth 返回链路尚未验收；本期是同源 Expo Web。

## 构建与验证

项目实际执行过官方 `create-expo-app` 与 `npx getdesign@latest add expo`。在独立前端目录按锁文件运行 `npm ci`、`npm run typecheck` 和 `npm run build:web`；开发步骤见 [前端 README](../frontend/README.md)，同源静态及回调边界见 [EXPO-WEB](EXPO-WEB.md)。生产只托管导出，不运行 Metro 或 npm 服务。

本轮早期共享 node_modules junction 曾让 Metro 解析旧源码，导出已被拦下。改用独立安装后，r3 构建证据绑定 `95c73ed11e3df9442bd125f4b6e6309d40f33fbb`／tree `a405fd56c4e710f7273964b82a12461622432165`，实际入口 `entry-88801b3aec5aad3ae711a561d7a55e91.js`；`build-evidence.json` SHA256 `8bc45329a8ac708bcfca0e8481b658d368410069ed96b95d3e0b5f6054c577ac`。Node `v24.19.0`／npm `11.17.0`，完整输入和导出 SHA 同时保留；源码新而 bundle 旧不能作为有效交付。

实际临时 Flask／SQLite／Edge r2 14 组、r3 6 组增量分别通过；视觉实际查看 r2 24 张及 r3 两张对话框，覆盖 320／390／1440，中文长标题与地址可读且未出现横向溢出。模块单独专项与组合执行分列，不拼成一次全套；报告、失败与修订见 [VALIDATION](VALIDATION.md)。Google transport／合成图片与真实本地业务 API 分开记录，没有访问真实账号或生产数据。

此前本人 Google Photos 已实际选片、预览并保存 5／5；本轮没有重做本人真实云操作或实体电视验收。Windows 公共站点曾被 DNSFilter 替换成 `Website Filtered`，此网络下线上登录尚未验证，未改 DNS、代理或安全设置。

## 发布与恢复

实际安装 main `5c59ffb7fd535828222c05938d54fbe75f6ce87a`／integration `95c73ed11e3df9442bd125f4b6e6309d40f33fbb`，同树 `a405fd56c4e710f7273964b82a12461622432165`。包含 444 源／112 运行／23 导出文件；archive SHA256 `66aad61ec9e9f002eb21ab23b04fc0baafb0a40a77abc7305652374e52d66298`，manifest SHA256 `42a9c32b105384d682f0e41e0040d682b35491fdf6ce294b4ef644fe3ae13e69`。

镜像 `sha256:c922946015345343810baae3ac16727b51602cca4c8ff4ab06f691b1ac1ff310` 内四模块实际 **63 passed，0 failed／error／skipped**，明确 deselect 一项 Windows junction 检查。发布目录 `/opt/family-dashboard-releases/expo-next-53-20260916T150125849654Z`；本次 53→53 无 schema 迁移，实际 1 户两库完整备份，全部 53 表行、schema、序列及平台注册库在新 app 启动时相同，配置保持。

23:02:30 正常 TLS 读回核对全部源／运行／75 项公开静态文件；24 个内部生成路径与 20 个退役资源为 404，十个匿名 API 均 401。四服务 running／restart 0、app healthy，发布后备份 service success／timer active。原始 JSON 位于私有 `expo-next-package-20260916/`：`activation.json` SHA256 `bf84b3453964140312cd56ad4f53d7e0927f1536d97813ffa808ad4d30317748`，`post-readback.json` SHA256 `db975f6f7bf8bc39980bbe7228ed0b690089191af3aba16b69f6e8534c516fb1`，`validation.json` SHA256 `915a174bf17cf9b96a03cc0451ed218bb531c212005f38c846a0c7e4d6498cb4`。这些服务器读回不替代受网络过滤影响的 Windows 线上浏览器验收。

发布已停止全部写入者，保留旧源码／镜像／配置和完整库备份，新 app 数据核对后才开放 worker／web。数据相等结论限于启动核对时点，之后允许正常业务变化。可复用这些校验步骤，不能重放绑定旧版本的一次性私有脚本，也不能重放 43／44／48 表迁移或要求库存五表为空。恢复按 [库存与媒体完整恢复](INVENTORY-RECOVERY.md)，特别重新核对备份之后的照片共享与 TV 撤回，确认前保持 media worker 停止。本篇为发布后交接，不改变已安装 manifest。
