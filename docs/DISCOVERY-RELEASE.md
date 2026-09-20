# 地点检索与照片重复提示发布

当前仍是未发布候选：63dc工具窄修保持455源的135运行文件、完整前端及165构建输入，沿用原R3 Expo、分段浏览器及125项Linux证据；新源实际9项Linux和四并发资源R2均通过独审。资源R1的请求前失败仍保留，旧125项未在新源重跑。R2只证明固定384／64MiB下四个元数据请求，不代表图片／视频混合峰值。尚未组装本批真实计划、stage或上线。用户入口、固定身份和失败历史集中见 [候选验收](DISCOVERY-ACCEPTANCE.md#discovery-candidate)。业务是助理打开原地点，以及本人主动核对 Google／设备照片的展示副本一致性；不改变照片原图、共享或电视许可。

## 固定范围

`build_discovery_release.py` 的静态 profile 固定实际父 source `79e5ef9`、manifest `c9723cf4`、应用镜像 `ede2e6f`，沿用 decoder `005cc30` 和 web `1ae82dc`。73/9、五服务；112 个非 Expo 运行输入中保持110个字节不变，仅允许固定审查过的 `home_assistant.py` 和 `household_media.py`。Dockerfile、Compose、Nginx、依赖和 decoder 原件保持。任意 JSON 不可选择模块或策略。

新源码仍须完整 Git／前后工作区／新 Expo 导出输入验证。23 项导出可复用的唯一条件是实际完整前端及构建输入逐字节一致；不能因为提交属于祖先或同一分支而直接使用旧包。

## 必须保留的证据

沿原 `prepare_local_photo_activation.py` 的 inputs JSON 描述符，使用 `package`、`build`、`validation`、`selection`、`parentAudit`、`image_overlap`、`nginx_raw`、`reviews`，新增必需 `duplicates`。每个资源描述符是 `{input:{root,sha256},run:{root,sha256}}`，root 是绝对独占目录，分别绑定 `input.json` 和 `result.json`，连同所有原件重读校验。独立审查角色仍为 source/browser/release/linux/resources。

旧照片资源仅证明父版完整112输入下的原媒体路径。工具先验证原112 map，再验证候选110保持与两文件旧／新固定 SHA。AST 比较只允许指定搜索、新增重复提示函数，以及预览完整性条件中 `bytes`／`sha256` 两处缺失安全读取；整个条件必须精确匹配，解密、拒绝输出与再次核权的其余语句不变，不能忽略整个预览函数。该守卫让缺少完整性字段的记录返回“暂不可用”，其定向回归单独验证。计划记录 `retained-parent-media-paths-only`；旧资源只覆盖有效元数据的原路径，不证明新异常路径或新两模块的整组资源负载。

新重复提示资源必须绑定候选镜像、完整112运行输入、23导出和实际构建记录。384MiB应用／64MiB客户端，640MiB三次主机准入、256MiB底线、250ms监控；必须实际观察四请求重叠、扫描调用、零BLOB读取和恢复200。目标1项加1001候选＝本人1002 ready记录，扫描上限1000且覆盖受限。四请求仅允许200或明确503 `unavailable`。核最终容器停止、原数据库不变、cgroup峰值和 max／oom／oom_kill全零。缺失、失败或原件不全均拒绝，不表示任意生产满载容量。具体字段见 `duplicate_resources` 与新探针合同；没有真实结果时不能组装计划。

Linux测试选择必须零skip，至少包含真实1000扫描上限与锁竞争恢复节点。测试选择仍须精确绑定实际 source/manifest/nodeids。

## 使用顺序

先运行 `python -B deploy/build_discovery_release.py prepare --help`，按原参数从固定 Git 与实际 Expo 输出打包；随后 `verify`、隔离 Linux `build`／`validate`，收齐新资源和独立审查。再运行 `python -B deploy/prepare_discovery_activation.py --inputs-file <inputs.json> --env-sha256 <摘要> --output <全新目录>`，生成不可重放计划；不读取或保存环境值。

`activate_discovery_release.py` 仅选择静态 discovery 模式，其 stage／activate／verify-rollback 沿用既有控制器与五服务生命周期。保留双历史锁、备份timer排空、整组73/9备份、app-only启动后停止态全表／行／序列／设置／非空媒体和提醒收据保全、decoder→workers→web启动及真实健康检查。不存在 migrate 动作。失败只停止本次已核CID并保留现场，不能自动回退或重放；显式完整库组恢复后仍用原 `verify_restored_group` 核验，恢复程序与生产授权边界不变。

本工具的单元测试采用真实临时Git打包、固定源码AST和明确合成证据／RecordingDocker；不是实际Expo、Docker、Linux资源或生产验收。实际运行与上线需另行独立审查。
