# 那年今日真实浏览器验收工具

本工具是待独立审查的本地验收准备，不表示浏览器流程、真实 Google Photos、实体电视或生产已经通过。业务合同见 [MEDIA-MEMORIES.md](MEDIA-MEMORIES.md) 与 [EXPO-PHOTO-MEMORIES.md](EXPO-PHOTO-MEMORIES.md)。

入口 `scripts/check_expo_photo_memories_browser.py`，流程实现在 `tests/browser_expo_photo_memories_check.py`。每个流程使用独立临时家庭、真实 Flask/SQLite/HTTPS、真实成员登录和 Edge 页面。照片由 Pillow 生成，经过真实 import/claim/complete/confirm/PATCH 和加密元数据存储；只有云任务完成输入为合成素材，浏览器业务 DTO 不替换。未知来源是明确缺少来源字段的加密旧记录。禁止云、模型与非本机网络访问。

| 可独立选择的流程 | 范围 | 预期截图 |
| --- | --- | --- |
| `mobile_page_edit` | 390px，30 张往年同日分页、两个年份、2 张未知来源；当前/相邻日期不纳入；第二页沿原 ID/revision 编辑说明并返回同页，SQLite 只该原项 revision 增加 | 3 |
| `midnight_poll_resume` | 1280px，服务器北京时间连续两次午夜：真实五秒轮询的第二页与隐藏后恢复的第二页均重新读取第一页；观察 DOM，不允许新日期短暂安装旧 offset；前后业务记录不变 | 2 |
| `identity_and_revocation` | 本人、伴侣、第二家庭和真实配对 TV 的日期/未知计数隔离；离线隐藏与同身份草稿恢复；延迟真实 GET 后切换真实登录；真实 SQLite session 撤权后清屏 | 3 |

午夜仅注入实际 `MediaLibrary.clock`，不伪造日期响应或浏览器计时器；浏览器的 `Date.now`、动画与轮询自然推进。隐私流程只延迟真实授权响应，不制造成功 `/me` 或业务数据。可见性事件和离线条件为明确的测试输入，不是实体设备证明。

独立审查后由集成人提供固定源码、构建原件哈希和新导出目录：

```powershell
python -B -X utf8 scripts/check_expo_photo_memories_browser.py `
  --source-root <fixed-checkout> --expected-head <full-head> `
  --build-source-head 03debe5943746a6a1868fd1e8b03c47f6aa6d002 `
  --bundle <fresh-web-directory> --expected-build-evidence <sha256> `
  --temp-root C:/tmp
```

Windows 的长导出路径使用扩展绝对路径 `\\?\C:\...`。`--case` 可重复指定，按首次顺序去重；默认三个流程。工具只接受原构建的后代，完整 frontend 树及构建 inputFiles 字节相同，差异严格限于本工具、流程、离线测试与本文四个路径。拒绝复用业务已变化的旧导出。

每轮独占 `test-results/expo-photo-memories-<UTC>/`，保留执行工具、完整 source/export 前后哈希、真实 HTTP 与 SQLite 摘要、截图与布局指标、错误及临时服务停止证据。失败不覆盖，计数按实际请求流程；部分通过不能写成整轮通过。离线测试只核真实 Git 复用边界、独占输出、照片批次/来源/清理、实际时钟与会话撤权 fixture，不启动浏览器，也不替代正式浏览器运行。失败定位后仅重新选择受影响流程。
