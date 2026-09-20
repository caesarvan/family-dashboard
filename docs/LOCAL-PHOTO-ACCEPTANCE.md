# 设备照片与那年今日：集中验收

<a id="local-photo-release"></a>

**2026-09-20 20:04:27（北京时间）已激活，20:05:10生产只读回读通过；随后非作者复核通过。** 实际一户两库保持73/9，没有迁移。计划已消费，禁止重放；Git合入、生产激活与只读核验分别留证。

## 用户操作

1. 打开「相册 → 选择照片 → 设备照片」；空相册可直接点「从设备选择照片」。选择 1～10 张 JPEG、PNG 或 WebP 静态照片，每张最多 8 MiB、2000 万像素，无需连接 Google。
2. 同意临时处理，点「上传并生成预览」。逐张上传只产生私密暂存；核对预览、勾选想保留的照片并明确同意保存后，才进入本人相册。
3. 打开原照片详情填写说明或关联旅行。需要伴侣看见时明确设为家庭共享；电视展示还需要对每台设备单独授权。共享、旅行关联或上传本身都不自动授予电视权限。
4. 结果不明时先点「核对本次上传」，读取原批次的实际结果。刷新后可重新选择同一原文件继续未上传项，系统会核验文件是否一致；也可明确结束本批、仅保存已成功项，不会自动另建批次或重复确认。

「相册 → 那年今日」按服务器北京时间展示本人已保存、来源日期可核对的往年同日静态照片，按年份分组，支持分页及原详情编辑返回；跨午夜或隐藏后恢复会重新读取，新日期回到第一页。没有可靠来源日期的照片显示为未知统计，不从文件修改时间、导入时间或无时区 EXIF 推测日期。首版本地照片日期统一未知，因此不会被虚构加入当天回忆；伙伴照片和视频也不进入本人回忆。

只保存经过净化、去除 EXIF／GPS 的加密展示副本，不保留上传原文件，不改设备原件。可从 iCloud 或 NAS 手动导出后选择文件，但这不是 iCloud／NAS 连接、实时同步或原图备份；本地视频、HEIC／HEIF、动画及多帧文件仍不支持。实际手机文件选择器、实体电视和本人完整 A–D 验收（0/4）仍待验证。

[设备上传合同](LOCAL-PHOTO-IMPORT.md) · [前端恢复操作](EXPO-LOCAL-PHOTO-IMPORT.md) · [回忆查询合同](MEDIA-MEMORIES.md) · [回忆界面](EXPO-PHOTO-MEMORIES.md)

## 已验证的范围

| 验证层 | 实际结果与边界 |
|---|---|
| 正式前端构建 | `bafd2cf` 上全新 npm ci、两组 TypeScript、47 个 Node 检查、23 个 Expo 导出通过。最终包复用相同完整 frontend、151 项输入和9项补充输入；不是把旧后端当作最终源码。 |
| 设备照片浏览器 | R3 在真实临时 HTTPS／Flask／SQLite／Pillow／Edge 中完整3条流程、9张图通过，涵盖三格式选择、私密确认、已提交响应丢失、部分跳过、原 ID、成员／家庭／TV 权限、撤回共享与迟到响应清屏。没有真实云或实体设备。 |
| 那年今日浏览器 | R1 的分页／原详情编辑和北京时间跨午夜两条，加 R3 的身份／撤权第三条，分段通过；不是单轮3/3。R3 保留两组异步关闭警告，实际监听器停止、临时目录删除和终态0已核验。 |
| 最终镜像与 API | 新镜像真实构建通过，恢复父用户 `dashboard`，Config 保持、仅增加清理／COPY 两层。实际191项 Linux 节点全部通过，0跳过／失败／错误；135运行文件、58个实际根模块和1156安装文件前后绑定。测试容器为1024 MiB，不能将这项通过当作384 MiB资源证明。 |
| 图像资源与代理 | R3 两个独立 Linux profile 通过。持有64 MiB显示响应期间串行上传20MP三格式照片，384 MiB应用峰值388,734,976字节，记录的 memory.max／OOM事件均为0。两家庭、两TLS入口、精确8 MiB raw上传和权限负向请求通过，Nginx临时目录监控无原图写入。测试使用固定依赖镜像加完整112文件运行覆盖，不冒称是随后生成的应用镜像。 |
| 原生解码合同 | 独立 Linux 原生 WebP 检查32组图像及7项边界检查通过，32组最终JPEG字节一致；未采集独立峰值，不代替上述资源实验。 |
| 五服务完整保全与恢复 | 实际新应用镜像执行两户三库73/9隔离演练：正常 stage、全组备份、app-only启动／停止、完整保全、五服务TLS健康；另在第二户注入真实settings漂移，停止后检查确实拒绝，再明确恢复整个三库组并核验。两个场景均通过、原计划拒绝重放；这是隔离恢复，生产本次没有恢复数据库。非作者执行复核已通过。 |
| 生产发布 | 实际激活与只读回读通过，随后非作者复核通过。一户两库73/9全表、settings、序列和对象指纹保全；1156安装文件、三个应用服务各135运行文件及decoder原4文件核对通过。五服务运行、0重启／OOM，app和decoder健康，正常TLS200、env摘要／0600、备份timer active保持。 |

本批仍为73/9，无DDL或回填；app、sync、media更新为同一新镜像，decoder保持父版镜像及其原4个运行文件。应用112个非Expo文件中105个与父版一致，其余为明确批准的本地来源、搜索撤权和图片内存修改。两处Nginx raw location仅放开精确上传路径，其他API大小／JSON规则保持。

生产的 `before.json` 与 `after.json` 原件SHA均为 `15f3024134583d25fecb2c482e338053b9c5cc2deeb2700dcf0034ecede86394`，完整逻辑摘要均为 `42a2fab80e39bab990576a977a0efe7c7ce35c3d8022f7a00e6706ec95d13675`；这是停止写入与app-only初始化后的保全时点，运行后的worker允许正常写入。只读回读核对既有备份／保全回执，未读取活库或重新核验备份SQLite字节，也未执行恢复、读取私人内容或证明worker业务tick。

所有图像实验均使用合成文件。64 MiB响应是大小专用合成缓存，不证明解码得到该大小的真实视频；约13 MiB峰值余量不保证任意图片、突发并发或主机争用。本人100 MiB／家庭200 MiB密文及预留额度继续生效，忙碌时返回可恢复错误，不扩大容量。

## 保留的失败

设备照片浏览器R1前两条通过，第三条因已撤销会话的旧预期失败；R2单条补验在无界传输完成等待处挂起，主运行者核对后终止本次进程，整体仍失败。修正为有界真实请求完成等待后，R3重新完整跑3条通过。那年今日R1第三条定位器失败、R2临时SQLite连接未关闭导致清理失败均保留，R3只补第三条。

资源R1在20MP WebP与保留响应重叠时OOM；R2虽三个HTTP上传成功，仍有133次 memory.max 事件、峰值触限，因此仍失败。修订后R3另留通过原件，不覆盖旧结果。首轮镜像构建因父用户无法清理旧Expo目录而失败；经单行用户校验、仅清理阶段切换root并恢复原用户后，新的R2包／镜像通过。各轮结果不累加为一次全量。

## 固定身份与原件索引

[PR #22](https://github.com/caesarvan/family-dashboard/pull/22) 已合入main `fd4497ba28cc64c8761ff8d4be0de7d3326313ab`，与下列应用source同树。后续文档提交不改变这些运行身份。原件保存在获授权工作区，不随Git提交；以下 `A` 指 `C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W=A/worktrees`，`U=W/media-video-usability/test-results`。

| 身份 | 完整值 |
|---|---|
| 应用 source | `79e5ef912517c796f3b6a4183762f8bcbf5464ba` |
| tree | `18626b20bfe3c4ab09e220e9f7e32c491e6f9670` |
| package SHA256 | `d305d95ba169718b71856e6aa2f2b2459a4c9f6a7b89d3a13e9e631e3e741873` |
| manifest SHA256 | `c9723cf4df9a2e2ee36f2300d4374cfd6a0358e91ebd5d5a9392151f20da8f76` |
| app／sync／media镜像 | `sha256:ede2e6f716a75e5d245ed6d90c485d39fd0847108abb6e24e42de8e4f272a1c2` |
| 保持的decoder镜像 | `sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c` |
| plan SHA256 | `f18ba1bdfd1123e4890a2f93bf2817078366bcaec57c6129ba053633ec3a2710` |
| 外置operator SHA256 | `257bbf258f6fefb306ec17b7b9b645307fe3058f4fdec31551cb5dc9ff0ce86c` |

计划目录为 `/opt/family-dashboard-candidates/local-photo-79e5ef9-20260920-r2-activation`，输入证据仍在其独立R2候选目录。stage实际检查通过（SHA256 `2ef0815bdafc8821a0a59b9fc300449f2fb27cbc1426cb58cecfc1c1d4d1d145`），其本身没有生产写入。activation于 `2026-09-20T12:04:27.189131+00:00` 完成，SHA256 `97e85738224c61acf1e71934cfe20e3634532228fe62498b2072b8ac1eafe73f`。releaseDirectory为 `/opt/family-dashboard-releases/local-photo-73-20260920T120239732967Z`。本计划已消费，不得重放。

| 原件或非作者审查 | 定位与SHA256 |
|---|---|
| 正式前端构建 | `A/local-photo-release-candidate-r2/package/build-evidence.json`：`dc8afa80dfb704ac33e54fcc9e86d476f238088c3eaf809f57fb2db5ca50edbe` |
| 设备照片R3独审 | `U/local-photo-browser-execution-independent-r3.json`：`887a3f0de97a8c79bc7ff8b66482e4e5398d7c5a750297797e8c531486d1f1d5` |
| 资源与原生合同R3独审 | `U/local-photo-linux-execution-independent-r3.json`：`22498a910a4a2ebf9b4ad9ad4913108c26b8c28e00577a3a3283781c5c728553` |
| 最终镜像与191项独审 | `U/local-photo-linux-candidate-independent-r2.json`：`96a10bb80828948aec2747a4a97cfecc71df823ce8f02d60b5712951fb92aeb5` |
| 那年今日分轮原件 | `W/media-video-usability/test-results/photo-memories-browser-independent-r1.json` 及 `W/media-video-controller-rehearsal/test-results/photo-memories-browser-independent-r3.json`；后者绑定R1的复用范围及原失败。 |
| 73→73演练实际结果 | `A/local-photo-controller-rehearsal-r1/linux-evidence/run-9f49c550c8ac2b88/result.json`：`e08033cb91eb7859ddc0c075d9fb108059f7fb42329bc747cc771d4d120771e5`；非作者执行复核已通过。 |
| 73→73演练非作者复核 | `W/media-video-controller-rehearsal/test-results/local-photo-controller-execution-independent-r1.json`：`6524ee86f7d88eca93e047acde62ee38fa6ec70a4e4960a9ae7c06f4d712d7c0`；原6848件、完整三库恢复、严格漂移拒绝及收尾已核。短健康探针超时／停机137记录保留，不扩成性能或实体播放证明。 |
| 生产只读回读 | `A/local-photo-production-r1/readback.stdout`：`6454f0dd69ff31f5956163ef28a5779ec657cc8fad753ca6fe3fea6cbfec592f`；25份安全JSON回执在同目录 `retained-receipts/`，无env／数据库内容。最终非作者复核通过，报告见下行。 |
| 生产最终非作者复核 | `U/local-photo-production-independent-r1.json`：`95426d1d937dc29a4d927cd37ae35916389444e5eb46283f2801a05f58d58e83`；25份安全原件、28条只读命令与原句柄终态核对通过。 |

[发布与故障恢复](LOCAL-PHOTO-RELEASE.md) · [Git协作](GIT-WORKFLOW.md)。隔离控制器工具单独保存在 `codex/local-photo-controller-rehearsal` 的固定提交 `d36b779bf375f54b59ddf0affe382e42ae671ab1`，其运行原件按上表定位。本页不声称真实Google视频、手机原生选择器、实体TV、iCloud／NAS连接或后续助理地点入口已随此包验收。
