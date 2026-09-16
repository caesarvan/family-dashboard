# 地点迁移的真实 Docker 演练

`tests/rehearse_journey_places_migration.py` 在 Linux Docker 主机上使用两个已在本机的不可变镜像，以及全新 UUID/label 标识的卷和容器，演练原 43 表升级至 44 表。它不读生产 Compose、环境变量文件或数据卷，不启动同步 worker，不调用云服务或模型，不执行生产发布控制器。它只为迁移、应用启动及原登录/文件可读性提供证据；生产控制器仍须独立审查及验证。

输入是已审完整候选目录、候选/实际基线 manifest SHA、父/新镜像 SHA 和不存在的报告目录。候选必须同时包含已审地点检查器与支持 `legacy43` 的恢复 fixture；单独检出此作者分支不代表所有依赖已齐备。必须使用 `-B` 且不设置字节码缓存前缀；每次源码复核拒绝整个候选树中的 `.pyc/.pyo` 及文件/目录 symlink 或 junction，不跟随外部缓存目录。仅禁写不能阻止 Python 读取旧缓存。

```text
python -B tests/rehearse_journey_places_migration.py --source CANDIDATE --parent OLD_IMAGE --image NEW_IMAGE --manifest-sha CANDIDATE_MANIFEST_SHA --base-manifest-sha BASE_MANIFEST_SHA --output NEW_REPORT_DIRECTORY
```

过程验证两份镜像的完整 Python/static/requirements 集合及散列，用旧镜像和 `legacy43` fixture 经真实 HTTP 创建两个虚构家庭、四位成员、八份旅行资料及其他数据，然后干净停止旧应用。新镜像中的检查器显式运行 snapshot、备份、备份验证、warm、check；启动新应用后再次检查原表、序列、认证和备份完全保持，新增地点表为空。检查器本身来自只读源码挂载，其 schema literal 绑定已经核验的 `/app/journey_places.py`。

之后使用原成员 cookie 读取空地点集合与原资料，并确认两台虚构电视均不能访问地点接口。认证 GET 允许 `member_sessions.last_seen_at` 单调更新，其余表和会话字段不变；不会把这段认证操作说成全库字节不变。最后复核源码，清理自己创建且名称/label 匹配的资源；清理失败会使整轮结果失败。备份和 fixture 的虚构秘密仅存在本轮卷中，报告保存散列和固定检查项。

报告中的 `realDocker`、`passed` 和镜像/manifest/schema 绑定来自实际运行。输入专项仅验证文件边界和嵌入脚本语法，不能作为 Docker 通过证据。此演练不做恢复；还需另行运行 `deploy/rehearse_restore.py --profile journey_places44`，验证实际 44 表数据恢复及旧登录撤销。两类原始报告分别保存，不把合成 READY 声明当成验收结果。
