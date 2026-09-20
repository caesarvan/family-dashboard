# 视频导入、成员播放与电视混合轮播

<a id="media-video-release"></a>

2026-09-20 17:26:15（北京时间）正式激活，17:33:17 生产只读检查通过，随后非作者独立核对通过。线上安装 source `b8c4d599257d77709f65f455bab9e1a5d5c7aff1`；后续演练工具和文档提交不改变该固定运行包。真实 Google 账号视频、实体电视和本人 A–D 完整流程仍未验收，不能以部署成功代替。

## 使用方式

1. 在「相册 → 选择照片」选择已连接的 Google Photos 账户，同意临时处理本次选择，再进入 Google 选片；支持照片和视频。
2. 等待处理，查看各项结果。只有明确勾选并保存的内容才进入相册；默认仅本人可见。视频保存前展示封面，保存后可打开播放。
3. 需要家庭展示时，明确共享并分别授予电视许可，再通过「电视与播放」控制对应屏幕。照片按间隔展示，视频按实际播放完成推进，默认静音；浏览器拒绝自动播放时显示重试入口。

原文件保留在 Google Photos。支持的源视频最多 100 MiB、10 分钟，展示副本最多 64 MiB；处理失败显示原因，不截断冒充成功。HDR 等未支持格式明确拒绝。本人／家庭原有配额仍生效，不能承诺一次保存多个大视频。详见[处理合同](MEDIA-VIDEOS.md)、[授权与持久化](MEDIA-VIDEO-INTEGRATION.md)、[电视播放接口](MEDIA-VIDEO-TV.md)。

## 运行身份与数据保全

| 项目 | 实际身份或结果 |
| --- | --- |
| 固定应用 source / tree | `b8c4d599257d77709f65f455bab9e1a5d5c7aff1` / `1ce81eb38bf9055cd650699ec0b3c7071a63b410` |
| 安装 manifest SHA256 | `20d4d43b69a8436df441283fe29a66388e535072f6cb117d1757525b78311291` |
| 包 package.json SHA256 | `e86eaf1632259195a6a96d56f1933a50edbe12b074f4a1f8111db0db5379f5ab` |
| app / sync / media 镜像 | `sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5` |
| decoder 镜像 | `sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c` |
| web 镜像 | `sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7` |
| 正式 plan SHA256，已消费 | `650ddf8b547e8c781b8184a8a6ecb0ebf18867d71f2f087a9e6bbc679b265f66` |
| 外置 operator source / 清单 SHA256 | `b61d0d51ddc65eb5ff32b5793fb36d98591f6dfd` / `954007aa8478b6a8d32af4220c0ff58515c2c87c008f823bc194ef3fd7b8aea8` |
| 最终发布批准记录 SHA256 | `62f2001d0ef110597b512a05e4a52a5b90b734fc8bcfc155aea18aa95936978e` |
| stage / activation 回执 SHA256 | `ee18daba960c1649366849f23ce23943748b20e008c39c0c3b04045f4e42128f` / `2bf3c864fc33d8d9ac6a47457b7484e8d68d27d7e032ed73373f558c531a87cc` |
| 发布保全目录 | `/opt/family-dashboard-releases/media-video-73-20260920T092409102222Z` |
| 正式候选目录 | `/opt/family-dashboard-candidates/media-video-b61-20260920-r1` |

真实一户两库完成家庭 71→73、平台 9→9。停止所有写者后备份完整库组；迁移仅新增 `media_video_cache` 和 `media_playback_progress`。app-only 启动后再次停写，核对原表、序列和逻辑指纹完整保留，新表为空，再启动五服务。生产未执行回退；完整组恢复验证来自下面的隔离演练，不能混为生产恢复。

只读检查逐一核对 1103 个安装文件，app／sync／media 各 134 个运行文件和 decoder 4 个文件。五服务运行、零重启、非 OOM，app 与 decoder 为 healthy；正常证书校验的 HTTPS `/healthz` 返回 200，备份 timer active。`.env` 保持原字节及 0600，仅记录摘要。检查使用发布时停写 proof，不打开当前生产数据库或读取用户行；服务运行不证明后台已成功处理真实用户视频。

## 各阶段验证及边界

| 阶段 | 已实际验证 | 限制 |
| --- | --- | --- |
| 正式 Expo 构建 | 两组 TypeScript、60 项 Node、23 个导出文件 | 固定 B2 构建，不把其他候选构建混入 |
| 本地视频浏览器 | 3 条流程、6 张截图，390px 成员及 1920px 电视；真实 Flask／SQLite／HTTPS／FFmpeg 与视频解码 | Google transport 为模拟，保留 8 条关闭阶段 TargetClosed 警告；无真实云视频或实体电视 |
| Linux 迁移 | 两户三库、app-only 保全、非空新表及完整组恢复、部分迁移失败 | 隔离合成数据，不是生产恢复 |
| Linux 媒体资源 R2 | worker100 实际 IPC／FFmpeg／加密／SQLite；response64 实际 64 MiB 读取、关闭与 busy 权限 | 两个独立负载，不代表最坏编码复杂度或持续并发；不能相加峰值 |
| Linux 完整控制器 R5 | success 与注入第二户只读失败两场景都完成真实控制器、完整组三库恢复及回退核验；431 条命令原件 | fixture timer、内部 bridge HTTP、960 MiB 场景预算；不代替生产计划准入、TLS 或容量验证 |
| 正式生产 | stage、activate、71→73 保全、固定源码与五服务身份、TLS、timer 和独立只读原件 | 不含本人真实视频、实体电视、长期负载或后台业务 tick 的验收 |

R5 使用固定演练 source `971487d3d51ad7d307a9f7adc29ccc831780a74e`，221.053 秒终态 0；成功场景恢复后为 71/71/9，失败场景先观察 73/71/9，再完整组恢复并核验。5347 份下载原件重新校验，所有已核本轮容器停止，父生产服务及配置在演练期间保持。独立审查 SHA256 `f68988679b1dd585bb67f6f2327b0ca690d7fc14bf98260c35c259fc29c28b34`，范围为实际隔离控制器演练。

此前 R1 种子来源校验、R2 内部网络健康路径、R3 恢复前重复备份准备、R4 部分失败观察器侧文件校验均失败，原件保留，不能改写为通过。最终 R5 窄修后在全新场景完成两条链，未重放已消费计划。过程见[控制器演练](MEDIA-VIDEO-CONTROLLER-REHEARSAL.md)。

## 接手与后续发布

发布操作见[五服务控制器](MEDIA-VIDEO-ACTIVATION.md)与[部署指导](DEPLOYMENT.md)。上述正式计划已经消费，禁止重放。下一次发布必须绑定当前 73/9 基线与新计划，不能运行旧四服务或 71 表首次迁移入口。

非敏感状态和固定 SHA 进入 Git；原执行输出、临时截图及检查报告留在 ignored 的 `test-results/` 或仓库外。生产读回位于协调者目录 `family-dashboard-access/media-video-production-r1`：`readback.stdout` SHA256 `cb9a4469c4cb8f074c26781a3bb78c94eb5eab84fe77aa799f38b2bc2a13c741`；32 份安全 JSON 原件的下载清单 SHA256 `919469021c7cc01630b2bbf0845cdbe012958909819d3e0ec62c531c285db895`。环境值、数据库与备份字节没有下载进这些审核原件，也不进入 Git。独立生产审计报告 `media-video-production-independent-r1.json` SHA256 `7b2b848631f54246159a23a67791941bc70b099a0462fdda9a19ad8bb4188ce8`；核对 32 份回执、28 条实际只读命令、固定服务身份与完整停写逻辑指纹，未重新读取备份数据库字节。

本批不含「那年今日」或设备本地照片上传；它们仍在独立候选 PR。iCloud／NAS、本地视频、HDR、原生安装包和真实实体电视验收亦未由本批完成。本人 A–D 完整验收仍为 0/4；分模块通过不能替代完整场景。
