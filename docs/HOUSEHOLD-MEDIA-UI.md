# 家庭相册界面

本模块是成员手机／电脑工作台，入口为「家庭相册」和「旅行 → 旅行相册」。使用现有应用与根 `DESIGN.md` 的字距、留白、卡片和清晰主操作，并适配森林、晨光白、海岸蓝主题。照片网格在窄屏为两列，详情在手机上移到网格前；电视不挂载成员相册界面。

## 使用流程

1. 连接 Google Photos，在 Google 页面亲自授权。原有日历／清单授权由后端分别处理。
2. 明确允许临时处理本人选择的照片，再打开 Google 的选片页面。不会读取整个图库。
3. 等待预览完成，勾选要保留的照片，并确认保存到个人私密相册。未确认预览最长保留 24 小时。
4. 打开照片详情，可编辑说明、关联旅行或改为家庭共享。取消旅行关联会依据服务端结果收回共享及电视许可。
5. 需要电视展示时，在共享照片详情单独勾选已配对屏幕，并再次确认电视展示范围。家庭共享本身不授予电视权限。

支持查看本人、可见或家庭共享照片，按旅行筛选、分页、重开最近的选择记录、取消导入及移除看板副本。Google Photos 原图始终保留。当前只支持照片预览；不宣称视频播放、原图备份、相册全量同步或真实电视验收已完成。

## 接口与加载

`static/household-media.js` 暴露 `HouseholdMedia.mount/unmount/notifyIdentityChanged/notifyStateChanged`。`index.html` 在 `product-shell.js` 之前加载本模块及 CSS；product shell 挂载 `#ps-media-workspace` 并在看板刷新时保留原节点和编辑草稿。退出登录、切换家庭／成员或离开页面时清理私密 DOM、候选、草稿及定时器。

使用现有 `api/write` 的同源凭据及 CSRF。写入前与异步结果返回后复核 `/api/me` 的成员、家庭、授权版本和 CSRF；变更后不能让迟到结果重新显示前成员内容。后台选片状态按服务端提示、4–15 秒间隔读取；可见照片至多约每 15 秒重新核对，重新聚焦页面时也核对。服务端逐请求权限仍是实际授权边界；离线时显示连接失败。

| 用途 | 方法与路径 | 响应形状 |
|---|---|---|
| 照片授权 | POST `/api/accounts/google-photos/bind` | `{url}`；成功回跳 `auth=photos-connected` |
| 创建／历史 | POST／GET `/api/media/imports` | 创建 `{import,replayed}`；列表 `{items,total,...}` |
| 预览与进度 | GET `/api/media/imports/<id>` | `{import,items:[{id,status,item}]}` |
| 保存／取消 | POST `/api/media/imports/<id>/confirm`；DELETE `/api/media/imports/<id>` | 确认回执／导入状态 |
| 相册／详情 | GET `/api/media/items`；GET `/api/media/items/<id>` | 列表 `{items,total,hasMore}`；详情 `{item}` |
| 编辑／移除 | PATCH／DELETE `/api/media/items/<id>` | 修改后读回详情 |
| 电视许可 | GET／PUT `/api/media/items/<id>/tv-grants` | `{revision,deviceIds}` |

三个同意步骤使用同一版本 `media-v1`，但分别提交 `allowTemporaryProcessing`、`persistSelected`、`allowTvDisplay`，不能相互替代。创建和保存发生响应丢失时保留原请求 ID 和完整载荷重试；明确的保存冲突（409/410）要求本人点击“重新核对本次选择”，读取最新状态并重新同意后建立新的保存请求；普通状态刷新不会自行覆盖原请求。照片修改冲突保留草稿，由用户明确读取最新版本再确认。请求结果未知时锁定创建账户，保存期间锁定编辑字段，避免显示账户与实际载荷不符或丢失新输入。未知创建结果再次新建需本人确认。

只允许精确同源 `/api/media/items/<24hex>/preview` 成为图片地址。OAuth 仅导航到 `https://accounts.google.com`，选片链接仅接受 `https://photos.google.com`，不嵌入 Google 页面；文本均转义。浏览器不保存 provider token、远端媒体下载地址或私密相册到 localStorage。

## 验证与交付边界

`tests/browser_household_media_check.py` 使用真实 Edge 与隔离的合成 API 合约，覆盖三个同意、创建／保存响应丢失后的原请求重试、409 草稿恢复、电视范围、旅行解除后的服务端读回、草稿刷新、四种视口、共享撤回、同源图片地址及迟到响应身份隔离。合成接口不等于真实 SQLite 后端、Google 授权或实体电视；后端与 worker 组合后须另验这些接缝。

`tests/browser_product_shell_check.py` 和 `tests/browser_connection_return_check.py` 检查受影响的导航与已有授权回跳。本 UI 分支不修改 Docker、数据库或服务注册；必须与媒体 API、worker 及应用接线共同审查后才能发布。
