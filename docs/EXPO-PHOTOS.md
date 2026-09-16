# Expo 相册

`PhotosScreen(props: ScreenProps)` 使用 React Native 和 React Native Paper，在 Expo 页面内完成图库、详情、照片共享、逐台电视许可与 Google Photos 选片保存。视觉使用 [Expo 设计规范](../expo/DESIGN.md) 和公共 Paper 主题；不加载旧相册 HTML 或 CSS。当前为待组合验收的源码候选，未部署，不代表真实 Google 或原生手机验收。

## 页面与权限

- 图库分为“我的照片”和“家人共享”，每页最多 24 张。照片说明完整换行，点击后重新 GET 详情；家人共享照片只读。
- 本人可编辑说明、关联已有旅行以及选择私密或家庭共享。修改旅行关联不表示到访。解除已有旅行关联时，后端转为私密并撤销电视许可。
- 电视展示单独折叠。必须先保存为家庭共享，再选择具体已配对电视并勾选用途确认；也可以收回全部电视展示。不会把配对理解为相册全量授权。
- 移除操作需要确认，只删除看板展示副本，Google 原图保留。解绑来源会清除相应本地副本，来源选择区明确显示这一点。

## 选片与保存

展开“选择照片”后，选择本人 Google 账户，必要时显式连接或更新照片授权；只有账户 DTO 的 `capabilities.photos` 为真且不需要重新授权，才能开始选片。

1. 勾选临时处理同意，POST `/api/media/imports`，保留原 `requestId`。
2. 打开该记录的 Google Picker 页面，选择最多 20 张照片后返回。此按钮重复打开同一个会话，不发起新的创建请求。
3. 读取真实处理状态，展示成功、失败、跳过、处理中以及每项固定安全原因。只显示后端已准备好的同源预览，不读取整库或加载 provider 图片 URL。
4. 勾选要保存的照片，另行同意持久保存，再确认“仅保存当前勾选的 N 张”。POST confirm 保留原 `confirmRequestId`、照片集合和 revision；保存后显示保留的数量和失败原因。

未知的旧记录不会显示虚构的 0。历史回执仅知道保存 3 张时显示“已保存 3 张；本次其他处理结果未记录”。处理成功包含已有照片复用，不代表全部保存。视频不支持播放；格式与图片安全边界完全沿用现有后端，不推断 HEIC 或实际失败原因。

网络中断不会自动重复写入。开始和确认保存可以由用户明确重试原幂等请求；创建返回 202 后，详情或辅助状态读取失败时也保留原创建回执，不产生第二个请求标识。服务端 `create_unknown` 记录要求先取消，才允许显式开始另一轮。照片设置或电视许可提交结果未知、CAS 冲突时保留文字/旅行/共享草稿并锁住写入，用户先读取当前版本再比较确认；重新读取电视许可时以服务器当前集合替换勾选。关闭或切页不撤销已提交的请求。

## 集成接缝

根代理注册相册路由和共享 `RouteName`，按 `identityKey` 重挂屏幕。页面依赖 `useHousehold().mutate/refresh`；每个只读批次在请求前后独立 GET `/api/me`，比较成员、家庭、角色、auth version 和 CSRF 的完整签名。组件/路由失效及较旧请求代次均丢弃结果。身份变化立即清空照片、账户、导入、草稿、许可与待确认请求。电视角色不发起本页媒体请求。

每 5 秒在可见相册刷新本地状态，不直接调用 Google。照片详情版本变化不会覆盖输入；访问撤销或删除后清理详情。屏幕失焦停止轮询并使在途读取失效。

共享 `navigation.ts` 需提供 `openPhotosProvider(url, kind: 'authorize' | 'picker'): boolean`（已约定依赖 `c061fe3b83445a641d1d9ef4311d30c8482ea753`）。仅接受精确 Google HTTPS host/path、无 userinfo 的地址；授权同页，Picker 使用独立页面且断开 opener。返回 true 只说明地址被接受，不代表浏览器一定打开新标签。Picker 按钮同步打开已经过身份检查的短期会话链接，避免手机浏览器丢失点击手势而拦截新窗口；随后刷新记录。按钮再次检查当前屏幕、记录 ID 和有效期，保留再次打开同一链接的操作。

使用的业务契约为 [媒体 API](HOUSEHOLD-MEDIA-API.md)、[处理结果](MEDIA-IMPORT-RESULTS.md)、[Google Photos OAuth](GOOGLE-PHOTOS-OAUTH.md)。源码中的请求 helper 自动加 `/api` 前缀。列表辅助信息分别来自 `/accounts`、`/devices`、`/journeys`；不增加后端接口、数据库、依赖或权限。自动旅行建议与地图往返入口仍使用现有高级模块，本候选提供手动旅行关联。

## 验证与组合夹具

```powershell
node --test tests/test_expo_photos.mjs
cd frontend
npm run typecheck
```

定向 Node 测试覆盖预览路径拒绝外站/TV/错 ID、旧结果 null、固定安全错误、确认请求不可变、创建成功后读取失败保留回执、清单验证、读取前后成员/家庭/角色/auth version/CSRF 变化和迟到响应。作者执行 12 项通过。首轮 Node strip-only 不支持 TypeScript 参数属性，改为显式字段后通过；没有改依赖。单独分支尚不含共享导航 export，作者在 ignored 副本只加入上述冻结导航文件后运行 `npm run typecheck` 通过；正式组合仍需重新检查。

真实 Flask/SQLite 浏览器夹具可以复用 `tests/test_household_media.py` 的 `configured → saved`、`device`、`share`，或现有应用使用 `tests/test_media_runtime.py` 的 `ready(app, client, headers, account_id)`。这些函数通过真实媒体引擎准备净化图片，并经过真实成员确认 API 保存；没有假图库接口。完整导入可复用 `tests/browser_media_integration_check.py` 的 `SyntheticGoogle` 加真实 `MediaImportWorker`，仅 Google OAuth/Picker transport 为合成边界。390/1440 实际导出与业务浏览器在根代理组合阶段验收，本提交不声称已通过。原生 APK、真实 Google 新一轮选片和实体电视尚未验证；Windows 公共域名 DNSFilter 限制仍保留，不修改网络设置。
