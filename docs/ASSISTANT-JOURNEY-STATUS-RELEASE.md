# 助理旅行准备查询：77/9 源码更新发布合同

本批是独立候选，尚未打包、构建、执行 Linux 或部署。入口复用已有五服务控制器，数据库保持户内 77 表、平台 9 表；不得调用 75→77 迁移或重放父版已消费计划。

## 固定父版与源码边界

- 生产父源 `d4346d34ed5271699f2cffac7c29aa098edc8a07`，树 `1bc76b9896873589de1597f6a9f50de097c1c5c5`。
- 父包 `d1784a3df473d41dbf9c2602e05d569b518b2cd88230d6e0db3afda29c0cecb1`，manifest `f10633fd7688b8c53d6923933097f479cd53c07d44800c52ad2d8217cd387467`。
- 父 app 镜像 `sha256:3c55bfbac391346af9f88253be65de96602f55179a2fee698fe694ab34e70b64`；decoder、Compose、Nginx、Dockerfile 与父版一致。
- 非 Expo 运行文件仍为 114 个；仅 `journey_workflows.py` 可按独审固定 SHA 变化，其余 113 个必须逐字保持。父完整映射与保留映射均有固定摘要；不接受任意模块或通配路径。
- API 固定 `bc3619d05553b62cdf3a83893e92b54bcc279467` 的 `journey_workflows.py` SHA `0320ade60437b4907ebbb41b65cc40617ac69059c3ceac3fd495a4c044aafd51`；Linux 选集固定 47 节点（45 新项、2 相邻项）、2 个执行模块和 2 个递归 fixture 模块，禁止 skip 或增减。作者分轮通过不等于候选 Linux 已运行；Expo 输入与导出仍需真实完整构建证据。

## 复用入口

`deploy/build_assistant_journey_status_release.py` 只提供固定 baseline `tv-trip-r1-assistant-journey-status` 的 prepare / verify / build / validate，参数沿共享 builder。`deploy/prepare_assistant_journey_status_activation.py` 只接受 package、build、validation、selection、parentAudit、retainedTvTrip、reviews；五个独立角色为 source、browser、release、linux、resources。

`retainedTvTrip` 包含父 package/build 根目录和摘要、父 plan 路径和摘要。准备器只读核对实际归档、manifest、构建原件、固定计划及运行文件，不执行旧计划。继承范围仅为未变的媒体运行代码；不据此宣称新状态查询的并发容量或新的混合负载通过。

`deploy/activate_assistant_journey_status_release.py` 固定 mode `assistant-journey-status-source-update`，release 前缀 `assistant-journey-status-77-`。默认与所有历史模式保持原合同。

## 保全顺序与失败处理

stage 仅核生产状态并写候选回执。activate 使用新独占计划，保留源与配置，停止备份 timer，排空五服务后完整备份所有家庭库及平台库；随后安装源、app-only 初始化全部家庭、停止 app、用 `tv_trip_release_data` 对 77/9 全组核对，再启动五服务、校验 HTTPS / 镜像 / 运行文件 / 环境并恢复 timer。

本模式没有 migrate action。`media_playback_journeys`、`media_playback_operations` 可非空，必须与其余旧表、DDL、设置、已有序列一起完整保留；不能套用上次迁移的“新表为空”断言。

失败保留备份和已消费 attempt，停止已绑定候选进程，不自动恢复数据库或重启父版。人工明确恢复必须完整恢复所有库到原根路径；`verify_restored_group` 只读验证原 plan、源身份、marker、备份及完整 77/9 数据组。部分恢复、错误源/计划或数据变化一律拒绝。

## 验证边界

本分支的定向检查使用记录型 Docker 验证顺序、错误父版、故障收停和禁止自动恢复；另外用真实 SQLite 两户三库验证非空 77/9、真实 app 初始化后全组保全与完整恢复。18 个唯一检查分三轮最终通过：R1 11/11；固定业务摘要后 R2 7/8，唯一失败为测试误期待未知前端输入被静默排除（实际会严格拒绝整包），仅修测试后 R3 1/1。旧通过项不重跑，原失败保留。父版真实包/build/plan 另做只读核验；Windows 长路径初读失败保留，使用同路径扩展前缀后成功，发布源码未变。合成数据不包含真人资料，不代表 Linux 容器、实际发布或真人端到端验收。

旧迁移、实体 TV、真实云和用户 A–D 验收的边界继续参见 [电视旅行验收](TV-TRIP-ACCEPTANCE.md)。本批业务合同为组合依赖 `docs/ASSISTANT-JOURNEY-STATUS.md`（冻结 `949c55ad49c718572bf49db6f3110e7686f82372`）；此发布分支不复制合同或业务实现。
