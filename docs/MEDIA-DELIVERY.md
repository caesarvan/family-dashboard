# 相册与电视：开发交接与使用

本地候选已把账户、媒体库、后台worker、相册界面和电视照片轮播接入实际应用工厂。默认家庭及独立家庭都初始化48张家庭表；平台目录保持两表。线上发布身份仍以 [README](../README.md) 为准，代码合入和合成浏览器通过不等于真实Google授权或物理电视验收。

## 用户操作

1. 在「相册」连接本人 Google 账户，允许 Photos Picker 权限。仅照片授权的账户不会要求选择日历。
2. 同意本次临时处理后，在 Google 页面选择最多20张照片；回到看板等待准备。未明确保存的展示副本最长保留24小时。
3. 勾选要保存的照片并确认保存。照片默认仅本人可见，可另填说明、关联旅行，再明确共享给家人。
4. 逐张选择允许展示的已配对电视，并单独确认许可。家庭共享本身不会打开电视展示。
5. 在设置里的对应电视打开播放控制，可以开始、暂停、继续、翻页、调整间隔或回到看板。断网和授权过期会清除旧图；重新连接后重新核验。

解绑账户或明确失去来源权限会撤回本地副本。需要重新登录的暂时失效保留本人已确认副本，但撤回家庭和电视共享；重新绑定不会自动恢复旧许可。这里删除的是看板内副本，未实现删除Google原片。

## 模块与接口

| 范围 | 实现与契约 |
|---|---|
| 账户增量授权、权限状态 | `cloud_accounts.py`、[OAuth说明](GOOGLE-PHOTOS-OAUTH.md) |
| Google Picker协议 | `google_photos_picker.py`、[协议说明](GOOGLE-PHOTOS-PICKER.md) |
| 图片净化和加密 | `media_images.py`、`media_crypto.py` |
| 持久导入、私有与共享、逐台许可 | `household_media.py`、[媒体API](HOUSEHOLD-MEDIA-API.md) |
| 异步导入 | `media_import_worker.py`、[worker契约](MEDIA-IMPORT-WORKER.md) |
| 相册界面与草稿恢复 | `static/household-media.js/.css`、[界面说明](HOUSEHOLD-MEDIA-UI.md) |
| 手机控制和电视轮播 | `media_playback.py`、`static/media-tv.js/.css`、[播放API](MEDIA-PLAYBACK.md) |
| 数据导出 | `data_portability.py`、[导出范围](MEDIA-PORTABILITY.md) |
| 部署与注册 | `app.py`、`compose.yaml`、`Dockerfile`、[运行接线](MEDIA-RUNTIME.md)、[迁移](MEDIA-MIGRATION.md) |

全部媒体API复用当前家庭的成员会话、CSRF、对象权限和revision；TV只有读取当前许可照片的接口。完整方法/路径清单由 [源码索引](PLATFORM-ROUTES.md) 提供。展示副本为SQLite加密BLOB；个人ZIP只有照片信息，整库备份包含密文并需要原密钥才能恢复。

## 运行与部署

Compose四个服务：`app`提供Flask API及静态文件，`sync`处理现有日历/待办，`media`处理Picker导入，`web`提供Nginx HTTPS。三个Python服务使用同一应用镜像和同一数据卷，密钥仅来自服务器 `.env`。本次不增加Python依赖；`media`是串行图片处理worker，按家庭轮转，内存限制384 MiB。

工厂在媒体库之后注册播放控制；`media-tv.js`在`tv-display.js`之前加载。身份变化主动清图，TVDisplay负责挂载手机控件和电视显示层。发布白名单纳入所有运行模块；未注册的 `inventory_core.py`仅随源码交接，不进入运行镜像。

从当前44表更新必须先停写、完整库组备份，再按 [媒体迁移](MEDIA-MIGRATION.md) 增加四表并校验旧数据。不能重放历史43→44或43→43控制器。保留当前AI/Google/Microsoft配置，禁止重新生成密钥。新应用及media worker启动前须分别完成Linux镜像检查和隔离恢复验证。

## 验证范围

基础适配、账户、媒体引擎、worker、界面和播放模块均有独立作者与非作者审查。实际临时Flask/SQLite/Edge已验证本人授权回调、选择→净化/加密→明确保存→旅行/共享→逐屏许可→撤销→刷新/重启；Google传输是合成替身。正式工厂与实际HTML的电视测试另验证手机控制、多个屏幕、断网恢复、授权期限、迟到响应和身份变化。

尚未验收：用户本人的Google Photos授权及照片、真实Google配额/网络行为、实体电视固件、生产新版本。视频、iCloud/NAS、自动旅行关联建议和回忆精选仍未实现；界面不将这些功能伪装为已接入。
