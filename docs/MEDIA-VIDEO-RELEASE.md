# 视频源码包与双镜像构建准备

这是尚未上线的候选准备工具，不是发布控制器。当前生产仍为隐私日历 source `8d3e6376a606155ff66a0388e43d04cb7562fe9f`；源码保存、打包和两个镜像构建成功都不表示服务已切换。五服务停写、完整库组备份、71→73／平台 9 表迁移、app-only 保全、启动／回退和独立生产审计仍须另行实现、审查及使用新计划，不能重放旧计划。

## 固定来源与导出

`media_video_release_package.py` 是独立新策略，只复用已有 Git blob、路径、摘要、JSON、归档写入工具，不修改旧 profile 或其 Docker／Compose 固定门禁。基线为 `db3786666d293c9a473f519766fa4112816f2b04`／tree `57939f9ebab4d52766a7b15032279a7d5989904a`，完整 1076 个来源文件的摘要表被固定；候选只能新增本批四个文件。后续控制器或产品修改需先审查并显式更新此边界。

接受同一候选的新 Expo 构建，或明确复用 B2 source `dfeaf22cf2e5a5bb87564f861418c1d847c9e830`／tree `1846590b38f09452042022dfebe4f5ce847171a4`。后一种核对的是确切八项差异：应用 Dockerfile、compose、decoder Dockerfile、迁移检查器、73 表保全模块、两篇容器／迁移文档及迁移测试；每项两端 SHA 被固定，此外只允许本批四文件。不会因为某提交是祖先就允许复用。所有 frontend 输入、九项 supplemental 输入和全部 23 个导出必须与证据、两个 Git 来源逐字节对应；五阶段 npm ci、两组 tsc、Node 和 Expo 退出码均须为零，dotenv／环境变量隔离标记须成立。构建原始日志的非作者复核仍独立于此摘要校验。

打包只读干净工作树的固定 40 位 Git 提交、实际导出和指定 SHA 的构建证据。拒绝链接、越界／重复／大小写冲突路径、`.env`、凭据、数据库、上传目录、备份、`test-results`、依赖目录及未知来源变更。输出必须是源码／导出之外全新的目录；失败保留现场，不覆盖原包。包包含源码归档、完整 manifest、原构建证据和包元数据；离线验证只在内存检查归档，绝不把未校验路径直接提取到磁盘。

## 两个独立上下文

- **应用**：按已固定应用 Dockerfile 的 COPY 指令精确收集 Python、requirements、经典静态资源及新 Expo 导出，加该 Dockerfile 和 `.dockerignore`。不把完整源码库、文档、测试、Compose 或任何运行数据送入构建上下文。
- **decoder**：只有固定 decoder Dockerfile，以及 `media_video_service.py`、`media_video_transport.py`、`media_videos.py`、`media_images.py` 四模块。没有 app、Flask、Google 凭据、数据卷或整份 requirements。

两个 recipe 都固定 Python 基础镜像 digest；decoder 固定 FFmpeg `7:7.1.5-0+deb13u1` 和 Pillow `12.3.0`。实际新镜像构建需要下载依赖，因此 `build` 明确使用构建网络；运行字节验证容器则 network none、UID 10001、只读、cap-drop、禁止提权，并设 CPU／内存／pids 限额，不挂任何宿主或生产路径。工具只使用本机 Unix Docker daemon，不使用 SSH，不运行 Compose，不创建或覆盖任何镜像 tag。

分别保存 `app/build.json`、`decoder/build.json`、原 stdout/stderr、实际 `sha256:…` 镜像 ID、精确上下文、镜像命令与运行文件摘要；decoder 另记录安装版本及 ffmpeg／ffprobe 实际二进制 SHA。只有两者独立成功、镜像 ID 不同且所有输入复核不变，才生成顶层成功 `build.json`。第二个失败不会隐藏第一个已构建镜像，也不会产生整体成功；失败写 `failed.json` 并保留全部尝试，重试须新目录。依赖间接版本由实际镜像结果固定，本工具不承诺跨时间构建得到相同 image ID。

## 调用与后续边界

入口为 `python -B deploy/build_media_video_release.py`：

| 命令 | 必填参数 | 行为 |
|---|---|---|
| `prepare` | `--repo --commit --export-dir --build-evidence --evidence-sha256 --output-dir` | 本地打包，不调用 Docker 或网络 |
| `verify` | `--output-dir --package-sha256` | 只读校验包与两个 context 分区 |
| `build` | `--package-dir --package-sha256 --output-dir` | 仅在另获执行授权后于 Linux 构建、核验两个新镜像 |
| `verify-build` | `--build-dir --build-sha256 --package-dir --package-sha256` | 只读核对两份成功记录及原 contexts，不启动容器 |

本轮测试使用真实临时 Git／文件／归档与记录型 Docker 替身，证明输入拒绝、分区和失败处理；不是实际 Docker、Linux IPC／资源、Google、浏览器或实体电视验收。源码包也不授予生产操作许可。后续五服务发布必须重新绑定实际线上父身份和两个候选镜像；停止 worker 排空、decoder 生命周期、73 非空数据保全、陈旧 socket、完整库组回退均不能沿用旧四服务流程冒充完成。
