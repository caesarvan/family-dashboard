# 本地照片与那年今日：73/9 发布适配

2026-09-20 20:04:27（北京时间）实际激活，20:05:10生产只读回读通过；随后非作者复核通过。固定运行source `79e5ef9`／app镜像 `ede2e6f`。实际191项Linux、设备照片R3完整浏览器、R3图像资源与Nginx验证已通过；73→73隔离两户三库的正常／注入漂移及完整组恢复实际通过，非作者执行复核已通过。生产一户两库严格保持73/9，没有迁移；本次计划已消费，禁止重放。生产没有执行数据库恢复，完整组恢复仅在隔离演练中验证。用户路径、完整身份与分轮边界见[集中验收](LOCAL-PHOTO-ACCEPTANCE.md#local-photo-release)。

复用既有单镜像构建、五服务停机／恢复生命周期，以及 `media_video_release_data` 的完整73/9保全；不运行首次视频发布的71→73迁移，也不重放其已消费计划。

固定父版应用 source `b8c4d599257d77709f65f455bab9e1a5d5c7aff1`、manifest `20d4d43b69a8436df441283fe29a66388e535072f6cb117d1757525b78311291`，app/sync/media 使用父镜像 `75d2cf07…`，decoder 保持 `005cc30d…`。完整常量和 105 文件保留映射见 [固定构建入口](../deploy/build_local_photo_release.py)。6 个既有应用模块和新增 `media_local_upload.py` 可变；其他非 Expo 运行字节固定。新应用为 112 个非 Expo 文件与 23 个导出，decoder 专用 `media_video_service.py` 保留在安装源码中，不加入应用镜像。图像内存修复仅更新应用侧，既有 decoder 镜像不从新共享源文件重建。

`membership_release_package.py` 仅增加明确的 `media-video-r1-local-photo` baseline。五服务生命周期／控制器仅支持原默认 `video-migration` 和新增固定 `local-photo-source-update`；JSON、CLI 不能指定任意 Python module、profile、迁移算法或放宽 schema。默认旧入口保持原合同。

## 构建与准入

使用 `build_local_photo_release.py prepare/verify/build/validate` 生成全新包、镜像和精确节点测试原件。可复用既有 Expo 构建，条件是完整 required inputs 的集合及每个 Git blob、磁盘和 export 字节一致。最终应用 source、包和新镜像必须以实际结果绑定；本适配不预填未来身份。

父镜像的旧 Expo 目录可能由 root 持有，已记录首次真实构建在 `dashboard` 用户清理时遇到 `PermissionError`，原失败保留。构建器只接受经过闭合单行语法校验的 `Config.User`（名称或数字 ID，可带组名／组 ID，拒绝空值、空白、控制字符和变量展开）；仅原目录清理步骤临时 `USER 0`，随后逐字恢复父用户（本批为 `dashboard`）再执行原 COPY，不修改目录权限。原路径／符号链接检查、最终 Config 完全相同与恰好增加 cleanup／COPY 两个文件系统层的校验保持。离线配方测试不代替修订后的实际 Linux 构建。

`prepare_local_photo_activation.py --inputs-file <固定输入JSON> --env-sha256 <摘要> --output <全新目录>` 只准备候选。输入为 `package`、`build`、`validation`、`selection`、固定 `parentAudit`、`image_overlap`、`nginx_raw` 及 `reviews`。资源输入分别包含 `input` 与 `run` 的 `{root,sha256}`，绑定原 `input.json`／`result.json` 和完整原件哈希；审查角色固定为 `source/browser/release/linux/resources`，每份 `{path,sha256}` 必须实际通过。审查者需在这些报告中保留各子项来源及失败历史。任何缺失、FAIL、OOM、清理失败、原件或 runtime 不符都拒绝。

资源测试是在固定依赖父镜像上挂载完整应用 runtime 的真实 HTTP 实验，不冒称使用新生成镜像；准入要求两套 runtime 字节完全一致。最终镜像另由真实构建与精确节点验证绑定。Nginx 两处 raw location 必须精确匹配，真实两家庭／TLS／无临时原图记录及权限负向证据不可用离线工具测试代替。

资源R1中20MP WebP与保留64MiB响应重叠使384MiB应用OOM；R2三个HTTP虽成功仍有memory.max事件，两轮均保留为失败。修订后的R3图像重叠／Nginx两个profile实际通过，并绑定最终包相同的112文件运行字节；其后最终镜像和191项分别通过。资源余量和合成响应边界见集中验收，不能用单独Nginx PASS抵消图像资源FAIL，也不能用旧source替代改变后的runtime。

## 唯一计划的执行与恢复

由集成人独立审查新计划 SHA 后，使用 `activate_local_photo_release.py stage <candidate> <sha>`。stage 仅读当前五服务、原 manifest、镜像、env 摘要／权限及候选证据，不创建容器。随后显式单次 `activate`，持 `.membership-release.lock` 和 `.static-release.lock`，重新绑定原服务 ID 并独占消费计划。

激活暂停备份 timer、拒绝正在运行的备份，保留原源码／Expo／env／镜像；依次停止 web、sync、media、decoder、app，证明所有数据库和私有 socket 使用者停止。完整组 `begin` 备份后安装新源；只启动 app 并初始化所有已登记家庭，再停止 app，通过 `check_stopped` 证明所有表、settings、序列、提醒与回执、视频缓存和播放进度完全保留。没有迁移回执，也不伪造一份。只有真实备份、attempt 与 stopped-check 的计划、source、完整组和逻辑摘要吻合，才启动 app、原 decoder、新 sync/media、web。正常 TLS 健康与源／配置核验后恢复备份 timer。

失败保留所有原件及已消费标记；只收停身份明确的本次候选／helper，未能确认停止时明确失败。不会自动恢复数据库或启动旧服务。需要恢复时由集成人另行恢复**整个** 73/9 数据库组、原 source／manifest／Expo／env／镜像绑定；保持所有服务及备份停止，再显式 `verify-rollback --release <原目录>` 验证完整备份、attempt 与恢复后的 73/9。该命令仅核验，不迁移、不恢复、不启动。旧 71/9 rollback 算法不能用于本次。

## 验证边界

定向工具测试包括真实 Git 包、记录型 Docker 生命周期、真实两户三库非空 73/9 的备份／当前 app 启动／保全／完整恢复。记录型 Docker 不是 Linux 部署演练；实际 Linux 资源、最终包／镜像、独立计划审查、生产激活与只读回读分别记录。照片首批仅 JPEG/PNG/WebP，不代表设备视频、iCloud/NAS 实时连接或真实云／实体电视已验收。
