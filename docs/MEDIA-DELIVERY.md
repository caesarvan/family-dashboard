# 相册与电视：发布交接与使用

当前已于 **2026-09-16 19:16:22（北京时间）** 发布 JPEG 主图兼容补丁，保留此前相册逐项结果诊断。镜像 `sha256:6688c51fed543794a393bf397b49ccb0c36dee8c24e19efbdb0a3715c2ebd86c`，安装 main `f603151`／integration `e2087e0` 同树；346 源文件、130 方法／路径模板、48 张家庭表及平台两表，无迁移。实际 1 户两库完整备份及原行／schema／序列保持；19:17:28 全源、运行文件和 HTTPS 静态文件读回通过。完整身份见 [README](../README.md)，分段证据见 [VALIDATION](VALIDATION.md)。本次文档只在本地更新，不修改已发布 manifest。

## 用户操作

1. 在「家庭相册」连接本人 Google 账户，允许 Photos Picker 权限。仅照片授权的账户不会要求选择日历；可从连接中心的“管理相册”返回。
2. 同意本次临时处理后，在 Google 页面选择最多20张照片；回到看板等待准备，核对每项成功、失败、跳过或待处理及安全原因；“已处理”不表示全部成功。未明确保存的展示副本最长保留24小时。
3. 勾选要保存的照片，核对“仅将当前勾选的 N 张保存”并明确同意。确认后仍可查看处理原因、已保存和成功但未勾选的数量；成功生成预览不代表已保存。照片默认仅本人可见，可另填说明、关联旅行，再明确共享给家人。
4. 逐张选择允许展示的已配对电视，并单独确认许可。家庭共享本身不会打开电视展示。
5. 在设置里的对应电视打开播放控制，可以开始、暂停、继续、翻页、调整间隔或回到看板。断网和授权过期会清除旧图；重新连接后重新核验。

连接失败或结果不明确时，先按页面提示重试／核对，不重复创建同一选择。明确版本冲突需要重新核对选片并再次确认保存；未知网络结果继续使用原请求。撤回共享或逐屏许可后，该屏幕下一次许可检查不再取得照片。成员或家庭变化会清理旧私密画面和草稿。

本人已完成 Google 授权并曾选择 10 张普通照片、保存 3 张；另外 7 项原因未记录，旧记录会显示“已保存 3 张；本次其他处理结果未记录”。不要据此猜测格式、损坏或未勾选；后续本人重试已实际保存 5 张，另外 5 张显示 `invalid_image`；错误码不证明具体解码原因。本次 JPEG 补丁仅处理完整主图、丢弃附加内容和无关 metadata，发布后本人重试并经服务器读回确认，本批 5 张均出现预览并明确保存，0 失败，实际选片→处理→保存通过；仍不确定原失败的具体原因。不会自动重下载，详见 [JPEG 兼容](MEDIA-JPEG-COMPAT.md)。诊断规则见 [处理结果](MEDIA-IMPORT-RESULTS.md) 与 [结果界面](MEDIA-RESULTS-UI.md)。

解绑账户或明确失去来源权限会撤回本地副本。需要重新登录的暂时失效保留本人已确认副本，但撤回家庭和电视共享；重新绑定不会自动恢复旧许可。这里删除的是看板内副本，未实现删除Google原片。

## 模块与接口

| 范围 | 实现与契约 |
|---|---|
| 账户增量授权、权限状态 | `cloud_accounts.py`、[OAuth说明](GOOGLE-PHOTOS-OAUTH.md) |
| Google Picker协议 | `google_photos_picker.py`、[协议说明](GOOGLE-PHOTOS-PICKER.md) |
| 图片净化和加密 | `media_images.py`、`media_crypto.py`、[JPEG 主图兼容](MEDIA-JPEG-COMPAT.md) |
| 持久导入、私有与共享、逐台许可 | `household_media.py`、[媒体API](HOUSEHOLD-MEDIA-API.md) |
| 异步导入与逐项结果 | `media_import_worker.py`、[worker契约](MEDIA-IMPORT-WORKER.md)、[结果契约](MEDIA-IMPORT-RESULTS.md) |
| 相册界面与草稿恢复 | `static/household-media.js/.css`、[界面说明](HOUSEHOLD-MEDIA-UI.md) |
| 手机控制和电视轮播 | `media_playback.py`、`static/media-tv.js/.css`、[播放API](MEDIA-PLAYBACK.md) |
| 数据导出 | `data_portability.py`、[导出范围](MEDIA-PORTABILITY.md) |
| 部署与注册 | `app.py`、`compose.yaml`、`Dockerfile`、[运行接线](MEDIA-RUNTIME.md)、[迁移](MEDIA-MIGRATION.md) |

全部媒体API复用当前家庭的成员会话、CSRF、对象权限和revision；TV只有读取当前许可照片的接口。完整方法/路径清单由 [源码索引](PLATFORM-ROUTES.md) 提供。展示副本为SQLite加密BLOB；个人ZIP只有照片信息，整库备份包含密文并需要原密钥才能恢复。

## 运行与部署

Compose四个服务：`app`提供Flask API及静态文件，`sync`处理现有日历/待办，`media`处理Picker导入，`web`提供Nginx HTTPS。三个Python服务使用同一应用镜像和同一数据卷，密钥仅来自服务器 `.env`。本次不增加Python依赖；`media`是串行图片处理worker，按家庭轮转，内存限制384 MiB。

工厂在媒体库之后注册播放控制；`media-tv.js`在`tv-display.js`之前加载。身份变化主动清图，TVDisplay负责挂载手机控件和电视显示层。发布白名单纳入所有运行模块；未注册的 `inventory_core.py`仅随源码交接，不进入运行镜像。

18:05 的首次媒体发布按 [媒体迁移](MEDIA-MIGRATION.md) 从 44 表增加四表；18:57 诊断发布与 19:16 JPEG 兼容补丁都保持 48 表及原 AI／Google／Microsoft 配置和密钥。**当前已经是 48 表，不能重放本轮 44→48，也不能使用历史 43→44／43→43 控制器。** 下一次发布应重新绑定实际基线。媒体两户三库隔离恢复已在实际候选镜像完成，见 [媒体恢复](MEDIA-RECOVERY.md)；这不是生产覆盖恢复。

## 验证范围

基础适配、账户、媒体引擎、worker、界面和播放模块均有独立作者与非作者审查。实际临时Flask/SQLite/Edge已验证本人授权回调、选择→净化/加密→明确保存→旅行/共享→逐屏许可→撤销→刷新/重启；Google传输是合成替身。正式工厂与实际HTML的电视测试另验证手机控制、多个屏幕、断网恢复、授权期限、迟到响应和身份变化。

JPEG 本轮 Windows 作者图片 139 项、worker／结果 60 项；非作者图片 186 项、worker／结果 60 项及桥接 1 项分段通过；实际 Linux 一轮 199 passed／36.50s。此前诊断发布的 Windows、UI／桥接和 Linux 105 项单独记录在 [VALIDATION](VALIDATION.md)。首次媒体发布原 Linux 182 passed／1 failed 与随后单项 1 passed、两户三库恢复 1 passed 保留历史记录，不与本轮混算。

**已确认与待验收：** 本人已授权；保留历史十选三未知和后来十选五的逐项 `invalid_image` 记录。JPEG 发布后本人实际重试 5 张，预览、明确保存与服务器读回全部成功，0 失败；本批真实导入闭环已验证，原失败的具体原因仍不能确定。长期真实 Google 配额／网络行为、实体电视固件与长期展示仍待验收。**仍未实现：** 视频、iCloud／NAS、自动旅行关联建议和回忆精选。库存核心、API、界面与真实临时闭环在独立候选，正式库存接线／迁移／上线不属于此次 48 表版本。
