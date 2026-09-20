# 电视单趟旅行回顾：真实浏览器验收工具

依据[冻结接口契约](TV-TRIP-PLAYBACK.md)。工具从 `904fde5665b6f5063ac90f9c752556a70daeb108` 开发，只新增本文和 `tests/browser_tv_trip_playback_check.py`；接口、现代 Expo 界面与正式导出须由协调者先组合。本工具静态交付不代表浏览器、生产或实体电视已经通过。

## 两条流程

1. `trip_route_media_controls`：390px 成员页从原旅行回顾选择电视和共享路线，核对真实预览并明确开始；1920px 已配对电视显示该旅行的授权媒体和路线。真实 FFmpeg 生成的八秒短片通过既有 worker、净化、加密与确认保存，浏览器观察真实解码、播放时间和原生 `ended`，同时核服务端接受一次对应进度。验证暂停／继续／下一项／家庭看板、重载保留范围，以及第二台仅路线电视保持独立。九站路线有隐藏和模糊坐标，观察第二页及暂停超过一个实际十五秒分页周期。
2. `lost_start_revocation_isolation`：1280px 成员页在真实 start 已提交后丢弃响应，等该请求确实失败再核对原 requestId；GET 不重复开始、不增加原回执或审计。随后整页重载，重新选原电视读取当前范围。另将实际预览响应延迟至真实成员登录切换后送达，验证页面尾部身份核验、旧预览不安装、恢复标识清除及他人回执不可读。检查第二家庭、未授权与私人内容、路线中间站撤共享产生不可跨接缺口、路线撤共享时本趟媒体继续、媒体许可撤销、无媒体路线、离线隐藏和恢复、删除旅行不回退全相册、撤电视后旧请求拒绝。

每流程三个成功截图，仅记录当时真实可见 viewport；失败另外保存手机／电视截图与 ARIA、原异常及此前 HTTP/数据库摘要。实际结果按选中的 case 分别记录，失败不写成整组通过；补跑只选受影响流程。

## 真实夹具与边界

- 每条流程独立临时 HTTPS Flask、SQLite 与浏览器上下文，成员经真实登录；两电视通过实际配对、批准和 poll 获得 Cookie。另一家庭通过真实邀请／兑换和签名入口创建。配对密钥与 Cookie 不写报告。
- 旅行 A 有两张获第一台许可的照片与第一流程的一段真实短视频，另有私人照片、未授权照片和属于旅行 B 但已有电视许可的负例。路线通过原 API 创建，包含精确／模糊／隐藏坐标和九站分页；另建私人路线和仅路线旅行。
- 复用 `browser_expo_media_video_check.Run` 的真实媒体与配对夹具、原旅行／路线 helper，以及 `LocalRun.completed_json` 的响应加同请求完成等待。Google Picker **仅传输替身**提供合成内容，不替换浏览器业务 DTO。外部 provider/model 被拒绝，浏览器与 Python 网络限定 loopback。
- 不继承旧视频 helper 的无界 `Response.finished()`；新等待均有截止时间，故障注入只送达／丢弃真实服务响应。视频不 seek、不改 `currentTime`、不派发假 `ended`、不加自动播放放宽参数，不加速浏览器时钟。暂停分页的十五秒观察是测试行为本身。
- 预览和回执 GET 保持原业务表、回执及审计；首次 start 仅增加一条本人成员审计、meta revision 和本次操作，媒体／原图与展示副本密文／路线／授权摘要不变。SQLite 连接显式关闭，继承非 daemon 请求线程与 listener 关闭、实际临时目录清理断言。
- 不声称真实 Google、实体 TV、原始媒体来源日期、长视频、大媒体内存、Linux 服务或本人完整场景 C 已验收。路线不是照片拍摄地点推断；已交付像素及冻结浏览器画面不能被服务器追回。

## 协调者执行

使用已有项目虚拟环境，以 `-B -X utf8` 执行新脚本。参数均填写实际冻结值：

```text
python -B -X utf8 tests/browser_tv_trip_playback_check.py
  --source-root <组合工作树> --expected-head <组合完整SHA>
  --bundle <正式Expo导出web目录> --expected-build-evidence <build-evidence.json的SHA256>
  --temp-root C:/tmp
  --ffmpeg <已核实际ffmpeg路径> --ffmpeg-sha256 <SHA256>
  --ffprobe <已核实际ffprobe路径> --ffprobe-sha256 <SHA256>
```

默认运行两条；用 `--case trip_route_media_controls` 或 `--case lost_start_revocation_isolation` 定向补验。不能使用 `-O`。FFmpeg/ffprobe 的路径、实际哈希及版本写入结果。

源码 HEAD、tree、工作区与正式构建绑定，完整 frontend、supplemental/additional 输入以及所有导出字节前后核验。若仅修本工具，显式 `--build-source-head <原构建SHA>` 只允许该祖先到当前 HEAD 的差异为上述两个路径；完整 frontend tree 必须相同，业务差异仍拒绝。每轮新建 `test-results/tv-trip-<UTC>/`，保存实际执行脚本和分流程原件，不覆盖失败轮。

当前仅准备工具及静态检查。正式组合、导出与两条 Edge 实测由协调者另行安排；没有模拟成功或预填 PASS。
