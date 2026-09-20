# 本地照片：隔离五服务 73→73 控制器演练

这是候选工具，实际 Linux 运行需另行授权并保存终态。旧视频 R5 的 71→73 演练不能替代本流程。本工具不访问生产、不做迁移、不复用旧计划，也不把离线测试或合成资源上限当生产容量证明。

入口为 `deploy/local_photo_controller_rehearsal.py`，三个显式子命令：

```text
python -B deploy/local_photo_controller_rehearsal.py prepare --repo <固定工具checkout> --head <完整工具head> --package-dir <真实新包> --package-sha256 <包SHA> --build-dir <真实单镜像build目录> --build-sha256 <build.json SHA> --output-dir <全新输入目录>
python -B <输入目录>/operator/deploy/local_photo_controller_rehearsal.py verify --bundle <输入目录> --input-sha256 <input.json SHA>
python -B <输入目录>/operator/deploy/local_photo_controller_rehearsal.py run --bundle <输入目录> --input-sha256 <input.json SHA> --output-dir /tmp/family-dashboard-local-photo-controller-rehearsal/run-<16hex>
```

准备阶段只读实际包与构建原件，绑定完整源码、23 个 Expo 导出、runtime、父镜像配置、构建上下文和命令日志。工具从 `88524d58` 仅新增本工具／测试／本文；应用包相对该基线只允许已分配的构建权限修复三个路径和这三个工具路径，未来提交身份由真实包读取。运行必须从生成的 `operator` 目录启动；执行中的每个 operator 文件也核对哈希。缺失或失败的构建记录不能进入实验。

复用 `media_video_controller_rehearsal` 的固定 Docker socket、只拥有容器收尾、双发布锁、完整数据库组恢复脚本及主机预算：app192、media192、sync128、web64、decoder384 MiB；合计960 MiB，helper384 MiB。启动前三读各间隔1秒全部至少1088 MiB，运行每250ms监测、低于256 MiB或采样异常终止，保持原失败证据。没有自动加限、等待偶然高点或重跑。全部网络仅本次 internal Compose 网络／decoder none；仅临时新卷和合成 `.env`。

两侧都是真实五服务：父应用75d2cf07、固定decoder005cc30d，候选应用由真实build绑定。父app经真实登录／邀请码创建两个家庭和三个库，合成73/9种子包含非空媒体、视频缓存、播放进度、提醒状态和操作回执；小型密文占位只证明保全，不称视频解码或真实用户资料。原图、Google和模型不参与。

正常场景使用实际 `activate_local_photo_release.Controller` 的 stage、activate、data_call 和 verify_rollback：完整组备份；app-only初始化所有家庭；停止后全表、settings、序列、对象、提醒和回执严格保全；之后才启动decoder、worker和web。通过新生成合成证书／CA、精确SNI及已核对的内部Nginx端点执行实际HTTPS `/healthz`，不使用 `-k`，不称验证了公网入口。

失败场景在真实app-only停止且数据／socket卷无写者后，只修改第二家庭一个明确的合成settings哨兵；实际 `check_stopped` 必须报 `assistant_database_drift`，候选和helper收停且不会自动恢复。随后显式使用原文档的三库恢复算法，并由实际 `verify_restored_group` 核对完整73/9组、保留备份、原路径和来源绑定。两种场景均检查消费计划在任何新Docker命令前拒绝重放。

适配边界会写入 `adaptations.json`：合成manifest／marker／项目名／卷／Compose上限、TLS配置和最小父源码文件；systemd timer为显式fixture状态机，非真实systemd证明。仅生成的helper进程设置合成marker常量与begin/check的同一默认值，数据算法和所有控制器生命周期方法原样继承；没有源码覆盖或宽松profile。生产完整准入仍需正式包、资源、测试、独立审查及新不可变计划。

原件包括 `input.json`、每条Docker命令的started/stdout/stderr/终态、每个场景的seed、stage、backup、app-only结果、TLS、故障注入、显式恢复、owned-cleanup，以及主机监测和最终result。任何一段缺失或失败，都不能用另一段PASS替代。
