# 本地照片 Linux 验证工具

2026-09-20 的 R1 已实际执行，不能作为发布通过依据：`image_overlap` 在第三张 20MP WebP 的 PUT 期间触发 app 的 384MiB OOM（`oom_kill=1`）；此前 JPEG／PNG 成功，并用第二个视频请求的 503 验证 64MiB 响应仍持有 permit。原结果 SHA `3eae83945dff6c143f2ddab3ebe4700fc459e241fb77dbbf6c0ec48dc3de0592`。独立 profile `nginx_raw` 通过，结果 SHA `6a77c1f332a912edc14ec4ae82b1d64a245878f8b2f5b9a239ad71727beeb4c0`；它不覆盖 20MP 内存重叠。生产五个服务及配置前后不变；失败容器已停止，原诊断保留。新的图片内存修复须在原限制下另行运行，不重写 R1 结果。

此工具只有两个独立实验，不构建镜像、不安装依赖、不迁移生产、不停止既有服务，也不代表发布准入。每次输出目录必须全新；失败与不确定结果保留，不自动重跑或提高内存限制。首版仅 JPEG／PNG／WebP，不能用结果宣称 HEIC、视频本地上传、实际手机或 Google 导入通过。

## 固定输入与最短命令

`prepare` 从固定 Git 读取基线 `9bff5d4d21ef178a9c067f3fa39cb445819d03f0` 的完整 Docker COPY 闭包（含 static），只允许本工具的三个文件新增。逐文件写入独占准备目录，绑定 Git head、工具／原 Nginx／适配配置和所有 fixture 的 SHA。应用依赖镜像固定 `sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5`，实际源码覆盖到 `/runtime`；启动检查 requirements 精确版本、源码字节以及实际 Gunicorn worker 的模块 `__file__`。不把父镜像旧应用当成当前应用。

传入已有独立验过的**合成** response64 fixture 目录，须包含 `display.mp4`、`poster.jpg`、`fixture.json`。工具固定核对展示副本 SHA `77bae4c5e837e3db9f86b302f83a2e6881cc722604c39f6374a4977a61e71fde`／67,108,864 字节，以及海报 SHA `cbb1abf57ac5d8e6f6f5004f45fab1185358dedf84cea18e0d8208a4974ba4f2`。这是 160×90、12,010ms、带音频的完整合成 MP4 加合法 free box，压力来自尺寸，不代表编码复杂度。无需 FFmpeg／decoder。证书、口令与所有家庭记录也仅为工具合成内容。

```text
python -B deploy/local_photo_linux_probe.py prepare --source <独占固定Git树> --head <审查后完整HEAD> --video-fixture <已验合成fixture目录> --output <全新准备目录>
# 把完整准备目录传入专用 /tmp/family-dashboard-local-photo-probe/<新目录>；独立审查 input.json SHA 后：
python -B <固定工具路径>/local_photo_linux_probe.py run --input <准备目录> --expected-input-sha256 <已审SHA> --output <全新运行目录> --profile image_overlap
python -B <固定工具路径>/local_photo_linux_probe.py run --input <准备目录> --expected-input-sha256 <已审SHA> --output <另一全新运行目录> --profile nginx_raw
```

仅集成人获授权后在 Linux 执行 `run`；作者只做离线检查。不能从 Windows 工具测试、旧视频实验或本地浏览器结果推定本工具 Linux 通过。

### 显式图片解码修复输入

为复验 R1 内存问题，可在 `prepare` 同时传入 `--image-source-head <独立审查的完整提交>` 与 `--image-sha256 <该提交 media_images.py 的SHA256>`。该提交必须继承固定运行基线；逐一读取 Git 原件，要求完整 Docker COPY、依赖、Dockerfile、原 Nginx 及共用探针中，只有 `media_images.py` 字节发生变化。参数必须成对，错 SHA、无变化或其他运行文件变化均拒绝；不会读取该候选的未提交文件，也不接受任意路径覆盖。

清单分别记录探针 `sourceHead`、原 `runtimeBase`、新 `runtimeSourceHead` 及只含图片文件的 `runtimePatch`（原／新 SHA），运行前再次核对完整 runtime 文件清单与绑定。原探针三文件边界、镜像、限制及负载不变。每次修复使用全新准备／运行目录和新的 input SHA；R1 输入和失败原件保持不变。此参数及其真实 Git 离线测试仅证明输入约束，不代表新解码器已通过 Linux 验证。

## 两条实际路径

- `image_overlap`：在测量前生成三张各 20MP、压缩后 ≤8MiB 的图片：EXIF 方向 6 的 JPEG、含 alpha 的 PNG／WebP。应用先合成一条加密 64MiB 视频记录，然后用全新 Gunicorn 1 worker／4 threads 服务，所有照片经过真实登录→声明→原始 PUT→finish→明确 private confirm→原详情与 JPEG 读取。客户端保持视频响应未读，并在照片处理前、每次照片处理后用真实第二视频 GET 的 `503 video_busy` 验证该响应尚持有 permit；最后完整流式校验视频 SHA，关闭后再读第二次完整响应。任一处不能证明持有则失败／不确定，不能用并发启动替代重叠证据。视频种子由已授权合成记录生成，不是本地视频导入证明。
- `nginx_raw`：固定原 Nginx 镜像，保留原两个精确 raw location，仅适配虚构主机名、合成 TLS 证书、8080／8443、临时目录和日志位置。实际 TLS 分别经过命名／默认 server，真实创建两家庭、签名 space cookie 路由，走同一原始 PUT URL；验证恰 8MiB 合法 JPEG、超限 413、非 raw 路由 415、CSRF／Origin 403与跨家庭 ID 404。Linux inotify 在 Nginx 启动前监听全部指定 client／proxy／fastcgi／uwsgi／scgi 临时目录，全程记录创建、写入、移动和删除；事件队列溢出、监控失效判不确定，不以最终目录为空冒充未落盘。发现任何临时文件活动则不能宣称“原始上传没有落盘”。

两个 profile 都核对最终真实 SQLite 行、私密性、原 ID／revision、加密字段与确认次数；不用 fake DTO、业务 monkeypatch 或 pytest 测试客户端完成被测照片请求。

## 隔离、预算与原件

应用 384MiB、Nginx 96MiB、流式客户端 64MiB（均禁止 swap），加 128MiB 余量，共 672MiB 准入；即使第一条仅两容器也不降低门槛。连续三次、间隔 1 秒读实际 MemAvailable，全部达标才创建新内部网络与容器；250ms 独立监控，低于 256MiB／采样异常停止本次已核 CID。该预算只属于本工具，不改变旧 1280MiB 视频实验或任何发布政策。

容器只在独占 internal bridge 上互联，无外网／主机发布端口、生产数据／凭据／Docker socket 挂载；非 root UID10001、只读根、cap-drop、no-new-privileges、CPU／PID／tmpfs 限制。Nginx 同样以 UID10001 在非特权端口运行。只保存创建返回且名字／标签／ID 相符的容器，未知创建不猜名字重试或清理。原控制器、业务代码和 Compose 字节不变。

输出包括命令 argv/PID/终态/stdout/stderr、输入 SHA、宿主内存连续样本、各实际 cgroup 的 current／peak／events／limit、HTTP 时序、数据库读回、Gunicorn 源码导入证明及已停止容器状态。峰值包含启动／合成种子阶段，不伪装成仅图片净化峰值；两次实验不能相加推断生产并发。停止只作用于本次 owned CID，随后核零 PID 再移除容器／专用网络，合成目录与所有失败原件保留。

临时文件事件、监控覆盖丢失或关闭错误仍判失败；监控描述符最多关闭一次，异常不阻断本次 owned 容器与网络收尾、宿主内存及最终结果留证。离线回归使用真实文件描述符和协调者、合成事件与 Docker 替身，不等于实际 Linux inotify／容器已验。

离线测试验证配置边界、真实 Pillow 合成输入和恰 8MiB JPEG 净化等，不执行 Docker／SSH／Linux 负载。真实执行仍可能出现 OOM、线程／临时文件行为或超时；只有新运行原件可以确定这些结果。
