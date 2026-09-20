# 视频浏览器验收工具

本工具是待组合、待新导出的验收准备，不表示视频已上线或实际浏览器已通过。只使用合成成员、配对电视和媒体；真实 Google 账号导入、实体电视、原生应用、10 分钟/100 MiB 边界与 Linux 内存预算分别验证。

## 三条流程

| case | 实际操作与判据 | 截图 |
| --- | --- | --- |
| `member_import_play` | 390px 相册明确同意临时处理→实际创建导入→真实 Google Picker parser/worker/FFmpeg 处理→仅 JPEG 待确认封面，UI 不发视频 GET，伙伴/电视暂存读取 404→本人勾选并确认→同一 ID/revision 私密保存→伙伴和未授权电视读取 404→HTML video 解码且时间推进→停止后 Blob 撤销 | 暂存、播放各一张 |
| `television_mixed_controls` | 实际合成照片和视频明确共享并授予其中一台电视；另一台配对电视仍被拒绝。1920px 浏览器电视 JPEG→视频真实播放，手机暂停/继续，原生 `ended` 对应实际 progress POST 后回照片，再由手机“下一项”进入原视频 | 照片、视频各一张 |
| `revocation_offline_identity` | 成员播放→真实 browser context 离线清画面→恢复→真实登录切换清旧详情；随后共享视频由伙伴与电视播放，创建者收回共享后两端均停止、移除 src、撤销 Blob，实际 API 拒绝、DB 许可为空 | 390px 离线、1920px 撤权各一张 |

每条流程用独立临时 HTTPS Flask、SQLite 和浏览器会话。所有浏览器业务请求抵达真实应用；Google 网络传输替换为固定合成响应，图片由 Pillow 生成，视频由固定 SHA 的 FFmpeg 从本地 `lavfi` 生成 8 秒 H.264/AAC。视频后续沿真实 worker 净化、加密、暂存和确认。照片只是混播设置夹具，沿现有 JPEG 校验与真实队列完成接口生成。不会伪造成功 DTO、调整播放时间或加快时钟。成员播放在点击“播放视频”加载后调用实际 `HTMLVideoElement.play()`，电视使用产品自身静音播放；`currentTime` 和 `ended` 仅观察。

身份切换使用同一浏览器 context 的真实 `/api/login`，随后触发页面可见性检查事件；不伪造 `/me`。离线使用 `context.set_offline`，恢复后主动重新打开页面，不主张后台自动恢复播放。真实窗口隐藏、慢下载期间身份切换、物理遥控器与声音策略不在这三条最小流程内。

暂存授权边界沿既有合同：本人可通过已授权 API 读取临时视频字节；待确认页面只显示封面且不主动读取/播放视频。工具不新增“本人暂存视频 GET 必须 404”的限制。

## 固定输入与执行

工具分支基于 `6b52378abe751f9a61bc1d8b9d09d2b4d9f0ae93` 编写。执行必须等待后端、成员 UI、内存门禁、电视 protocol 2/CSP 的已审最终组合及全新 Expo export；不能使用当前成员版旧 bundle。TV 契约以独立候选 `0b8fcaf2b5093ad69d0912cd9e9acd48a5196b78` 的 `TVPhotoPlayer.web.tsx` 和 `/api/media-tv/playback/progress` 为准备依据，实际来源由最终 Git HEAD 绑定。

从固定且 clean 的执行 checkout 用 `python -B -X utf8 scripts/check_expo_media_video_browser.py`，提供：

- `--source-root`、`--expected-head`：最终已审来源及完整 40 位 HEAD。
- `--bundle`、`--expected-build-evidence`：全新导出的 `web` 目录及同级 `build-evidence.json` SHA-256。Windows 使用 `\\?\` 绝对长路径。
- `--build-source-head`：若仅合入本工具四个文件，可以明确传构建来源；须为执行 HEAD 的祖先，整个 `frontend` Git 树及每个 build input 字节相同。业务、后端或其它文档不同会拒绝复用。
- `--temp-root C:/tmp`：已存在的短本地目录，所有数据在独占子目录内。
- `--ffmpeg`、`--ffprobe` 和各自 `--ffmpeg-sha256`、`--ffprobe-sha256`：已经审查的本地工具绝对路径与 SHA；本工具不安装软件。
- 可选重复 `--case`：只补验明确选中的失败流程，每轮独占输出，不能把一条补验记为同轮三条通过。

初次准备只运行 `tests/test_expo_media_video_browser.py` 的工具边界测试，不启动浏览器、FFmpeg、npm 或生产。正式执行需协调者授权；建议用独占 supervisor 保存 argv、started/PID、stdout/stderr 与实际退出码，沿原 session 等到终态，不因观察超时重启。

## 原件与边界

`test-results/expo-media-video-<UTC>/result.json` 记录固定 Git tree、全部 tracked 来源前后 SHA、完整 export 前后 SHA、实际加载 fixture 字节、工具版本与 SHA、逐流程终态、六张截图及真实 body/root 横向宽度、HTTP 原请求/响应、同 ID/revision 的 SQLite 投影。失败保留 screenshot/aria/traceback；只有请求流程数、截图数、无外网/页面异常、源及工具不变、临时库/HTTPS listener 清理均通过才 exit 0。主报告不记录真实凭据，夹具全部为合成数据。

复用 [MediaRun](../tests/browser_expo_trip_recap_check.py)、[HTTPS 基础夹具](../tests/browser_expo_finance_check.py) 及已审页面溢出测量。只替换 Google transport；HTTP 记录路由执行真实 `route.fetch()` 后原样返回，未替换业务成功结果。仅 browser TV 验证，实体电视仍需本人验证。
