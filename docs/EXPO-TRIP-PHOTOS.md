# Expo 只读旅行相册

`frontend/src/screens/TripPhotosScreen.tsx` 是地图内打开的独立只读页面。契约为 `ScreenProps & { journeyId: string; onBack: () => void }`，其中 `journeyId` 是旅行 workflow ID，不是旅行实体 `tripId`。宿主负责内存中的地图返回筛选与选中 ID；组件不写 URL、history state 或 localStorage。

页面复用 React Native／Paper，以白底、黑色按钮和浅灰圆角照片卡展示；提供「我能查看的」「我的照片」「家人共享」三个范围，每页 24 张，照片详情只读。无论读取成功、失败或正在加载，「返回地图」始终可以使用。普通 `PhotosScreen` 的导入、编辑与电视许可入口不受本组件影响。

## 读取与权限

只读入口仅访问：

- `GET /api/me`：每项业务读取前后核对 role、member ID、household ID、auth_version 和 CSRF。
- `GET /api/journeys/{journeyId}`：取得当前旅行标题与 workflow／trip ID 对应关系，只保存需要展示的标题及 ID。
- `GET /api/media/items?scope=visible&journeyId=…&limit=24&offset=0`：按所选范围与页码读取。每张照片必须仍关联本次 workflow，并匹配当前旅行实体。
- `GET /api/media/items/{id}` 与同源 `/api/media/items/{id}/preview`：打开详情时重新读取；预览只允许 DTO 中与本照片 ID 精确一致的同源地址。

此页面不访问 accounts、imports、devices 或 TV grants，不发送写入、不改变照片共享、不依据地图权限授予照片权限。照片关联同一旅行不等于拍摄于选中地点。照片来源账户、原始文件名和来源时间均不进入只读组件状态。

组件按完整身份与 workflow ID 重新挂载。页面后台、失焦或离线时清空标题、照片 DTO、详情及预览，仅保留当前范围／页码／选中照片 ID；恢复前重新核对。正常可见时约每 15 秒重新读取权限与内容，手动刷新也可触发。请求代次使迟到响应无法恢复旧照片；读取失败、撤权、照片解除关联或预览失败会清空旧显示。已交付浏览器的像素无法从远端收回。

## 验证边界

`node --test tests/test_expo_trip_photos.mjs tests/test_expo_photos.mjs` 检查 workflow／trip 区别、响应投影与分页形状、同源预览以及既有全身份读取栅栏；`npm run typecheck` 验证组件类型。真实 Flask／SQLite／浏览器交互、四种屏幕宽度、集成接线与生产发布由本轮集成单独记录；本模块提交本身不代表上线，也没有代表用户执行真实 Google 选片。
