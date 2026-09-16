# 地图候选的 Linux 镜像内测试

`tests/run_places_linux_validation.py` 只运行调用方已经审查的 pytest 脚本组。它不构建镜像、不安装依赖、不使用 Compose、不读取生产配置或数据卷，也不生成 READY 或执行发布。输入专项使用合成文件和 Docker 命令替身，不代表已经执行 Linux/Docker 测试。

## 冻结输入

- `--source` 为 `/opt/family-dashboard-candidate-journey-places-*` 的绝对、无链接目录；`RELEASE-MANIFEST.json` 及其文件由 `--manifest-sha` 绑定，runner 自身也必须在清单内且字节相同。
- `--image` 必须是本机已有的 `sha256:…` Linux 镜像。禁止拉取；镜像不能声明匿名数据卷。
- `--groups` 是可信集成人审过的 JSON，`--groups-sha` 固定其原字节。最多两组，按顺序运行；每个脚本必须是候选清单中的 `tests/test_*.py`，不接受 shell、pytest 任意参数或节点表达式。脚本不得跨组重复。
- 每组给出 `name`、`scripts`、`expectedCount`，可选 `timeoutSeconds` 默认 600，范围 60–1800 秒。预期计数应来自本轮真实 Windows JUnit 与明确测试范围，不能沿用旧发布计数；计数只作断言，不当成运行结果。
- `--output` 可指定 `/opt/family-dashboard-places-tests-*` 的全新目录；省略时使用新 UUID。已有目录一律拒绝，不覆盖以前的成功或失败。

结构示例（数字只是示例，执行前换成实际审定范围并重新计算 JSON SHA）：

```json
{"groups":[{"name":"backend","scripts":["tests/test_journey_places.py"],"expectedCount":91,"timeoutSeconds":600}]}
```

```text
python -B tests/run_places_linux_validation.py --source CANDIDATE --manifest-sha MANIFEST_SHA --image sha256:IMAGE_ID --groups REVIEWED_GROUPS_JSON --groups-sha GROUPS_SHA
```

要求 Linux、`-B`、无 `PYTHONPYCACHEPREFIX`，并拒绝 `DOCKER_*` / `COMPOSE_*` 环境选择器。Docker 明确使用本机 Unix socket，不依赖用户当前 context。没有 SSH 或远端命令功能。

## 依赖与镜像身份

测试库仅从以下已冻结原件同级 `deps` 只读复用：

```text
/opt/family-dashboard-test-journey-documents-56975378c9e244c5bab40495fdb389b4/result.json
SHA256 25da3126006089256813b118850ad07c3ca31cf6ae2c19cc25dc9a115f820979
```

目录全部文件必须精确等于其 `dependencyHashes`；不接受额外或缺失文件、symlink/junction。原目录包含已被散列绑定的依赖字节码，这与不允许候选源码缓存是两件事。原报告的测试成功、后端源码和旧基线均不复用；不要求旧后端等于当前候选。

分别用原报告的不可变镜像 ID 与本次镜像运行无网络 Python 探针，精确比较 `sys.version`、实现名、cache tag、SOABI 和架构。旧镜像缺失或不兼容即失败，不自动下载、重建、修改依赖。新镜像实际导入该只读依赖中的 pytest，并记录版本；禁用第三方插件自动加载。

## 隔离与源码

新私有目录只从 manifest 复制测试支撑：`tests/`、`deploy/`、`docs/`、`.cursor/`，四份 `tools/inference_orchestrator` Python 文件，以及 pytest/Docker/Compose 源码示例、README、AGENTS、DESIGN 和忽略规则。这里只复制候选的 Compose 文本作为测试输入，绝不加载生产 Compose。支撑副本逐字节复核后才只读挂到 `/app` 相应位置；不挂载根 Python、`static/` 或 `requirements.txt`，这些必须来自镜像。

候选及支撑副本拒绝任何 `.pyc/.pyo`、文件/目录符号链接和 junction；`-B` 只禁写，不能替代拒绝旧缓存。每组 pytest 前后枚举镜像根 Python、完整 static 与 requirements 的精确集合和 SHA，重新校验挂载支撑文件，并保存实际 Python 身份。宿主再次核对候选、依赖、支撑和组配置原字节。

容器使用新 UUID 名称与专用 label、明确不可变镜像、`network none`、只读 rootfs、UID/GID 10001、去除能力、no-new-privileges、内存/PID/CPU 限制、禁用镜像 healthcheck；只写本组全新临时目录。创建后核对 image/name/label/network/user、挂载全集、无端口与无特权，再启动。不开 worker，不传真实账户或模型配置。

## 原件、失败与清理

每组保存 `targeted.log`、真实 `targeted.xml`、`runtime-proof.json`；两份 Python 探针日志与实际组 JSON 也列入最终 `result.json` 的 SHA 引用。JUnit 用实际 testcase 计数，核对所有指定脚本都有用例且无其他脚本；失败、错误、跳过或计数不符均不能通过。两组分开记录，不与 Windows 或旧发布相加为一次全套。

超时只记录原日志并停止自己创建的容器，不自动重跑。清理前重新核对名称、专用 label、镜像与网络；不属于本轮的资源不会停止或删除。清理失败、输入漂移、原件路径异常均使整轮失败。输出和合成临时测试文件保留，便于独立审查；输入预检在创建目录前失败时不会伪造运行报告。

这个工具不证明真实迁移、44 表恢复、生产控制器或真实用户场景；这些需分别运行并保留报告。只有实际新镜像中本轮脚本的通过原件，才能用于后续发布证据归一化。
