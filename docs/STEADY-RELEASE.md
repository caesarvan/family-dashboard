# 61/9 普通源码更新

本工具此前版本已用于 2026-09-18 15:12:56（北京时间）的采购关联库存更新；15:14:36 独立只读审计通过，生产一户两库保持 61→61 / 9→9。当前源码正为售后待办候选适配新的固定基线，尚未用这版工具再次部署。此前正式镜像构建、47 项 Linux 验证和两户三库合成保全演练分别通过。固定身份及结果集中在[采购关联库存验收](SHOPPING-INVENTORY-ACCEPTANCE.md#shopping-inventory-release)。用于已完成成员迁移后的普通源码更新，家庭库保持 61 张业务表，平台库保持 9 张业务表。它不执行 `warm_once`，不退休、覆盖或重建成功迁移的 `membership-release-attempt.json`。

当前工具固定接受已独立审计的采购关联库存 R1 基线（`shopping-r1-steady`），不能通过环境变量或任意 CLI 参数切换。下面是下一次候选更新的输入；旧 R3 发布计划仍不可重放。基线身份来自上述已完成的独立只读审计，新的候选包、镜像、计划和实际发布仍须分别验证：

| 身份 | 固定值 |
|---|---|
| 父镜像 | `sha256:3ebb0a10eaf3aac44c5646478f25d49b85a66d9130007286ac869274e99b6c68` |
| 已安装 manifest | `910b4ab67459d47dd77ec32fbb986fe298e71c24baf75c39c334ebc4db89fb1e` |
| 成功迁移标记 | `d223842c531e115b21430e860ffa8e742b1fbf0616942a228d04009e66dedb93` |
| 原 `.env` SHA256 | `a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07` |

标记摘要由成功 R3 `proof/attempt/attempt.json` 重建，并已与当时只读审计绑定。它只证明迁移身份；**本次数据保全使用本次停写快照**，不会把上次迁移后的旧数据当作当前数据，允许中间发生正常业务写入。

当前源码变更范围只接受 `app.py`、`inventory_api.py`、Expo 导出、`frontend/`、文档、测试及发布工具。售后待办在 `app.py` 的候选改动只用于注入已有任务校验器；具体产品差异仍须独立审查冻结。Compose、Dockerfile、依赖与其他应用模块必须保持原字节。后续扩大产品变更或改变基线应修改代码、独立审查，不能改 manifest 绕过守卫。

## 文件与兼容性

- [steady_release_package.py](../deploy/steady_release_package.py)：固定基线的 `prepare / verify / build / validate` 入口，复用严格 Git、Expo 输入、archive 和运行时镜像验证。
- [steady_release_plan.py](../deploy/steady_release_plan.py)：离线装配独立候选目录和可审查 plan，绑定源码、工具字节、构建、实际测试原件和审查文件。
- [steady_release_controller.py](../deploy/steady_release_controller.py)：受审 plan 的 `stage / activate`，复用原控制器的 Docker 身份、环境传递、证据读取、互斥锁和失败停止逻辑。
- [steady_release_data.py](../deploy/steady_release_data.py)：完整 registry 组备份保留及新 app 初始化后 schema、全部行、序列、版本、registry 和标记保全。
- 原 `membership_release_package/build/data.py` 默认仍为原 58/2 → 61/9 合同。新入口仅显式选择代码固定的 `shopping-r1-steady`；包校验器保留此前 `memberships-r3-steady` 的显式验证合同并拒绝跨基线包；备份助手显式使用 `phase='after'`，原默认不变。

## 准备和审查

使用干净、冻结的 Git head 和真实 Expo build evidence。每轮输出到新的目录，失败原件保留。以下占位值须替换为当次实际值；这些命令本身不证明运行成功。

```bash
python -B deploy/steady_release_package.py prepare \
  --repo /path/to/frozen-source --commit FULL_HEAD \
  --export-dir /path/to/actual-expo-export \
  --build-evidence /path/to/build-evidence.json --evidence-sha256 BUILD_EVIDENCE_SHA \
  --output-dir /path/to/new-package
python -B deploy/steady_release_package.py verify \
  --output-dir /path/to/new-package --package-sha256 PACKAGE_SHA
```

在 Linux 使用已安装的本地 Docker daemon，从固定父镜像只增加清除旧 Expo 和 COPY 两层。构建与验证均无网络、无依赖安装，不挂载生产数据；用已有 pytest 依赖目录。精确 `selection.json` 字段为 `schemaVersion/sourceHead/manifestSha256/modules/nodeids/allowedSkips`，`allowedSkips` 是 nodeid 到精确原因的映射；不接受任意忽略失败。

```bash
python -B deploy/steady_release_package.py build \
  --package-dir /path/to/new-package --package-sha256 PACKAGE_SHA --output-dir /path/to/new-build
python -B deploy/steady_release_package.py validate \
  --package-dir /path/to/new-package --package-sha256 PACKAGE_SHA --image-id sha256:ACTUAL_IMAGE \
  --selection /path/to/selection.json --selection-sha256 SELECTION_SHA \
  --pytest-dependencies /path/to/existing-pytest-dependencies --output-dir /path/to/new-validation
```

另做真实候选镜像的合成 61/9 两家庭三库演练：保留标记，`begin` 完整备份 → 正常 app 初始化全部 registry 家庭 → 干净关闭 → `check_stopped`。只有本地 Git 测试不能代替这个实际镜像演练。生产专用默认 marker 摘要不可套用到合成库；演练显式传入合成 marker 摘要，此参数不从生产 CLI 暴露。

准备 `reviews.json`，其对象键为要保存的审查文件名、值为该原件绝对路径。必须包含 `selection.json`，其 SHA 与 validation 中的 `selectionSha256` 一致；其余包含非作者源码/包审查、实际镜像演练与浏览器证据。这个映射文件本身也传入 SHA。装配工具保存这些原件，不把“存在审查文件”冒充人工审查通过。独立审查者需检查内容并批准最终 plan hash。

```bash
python -B deploy/steady_release_plan.py \
  --package-dir /path/to/new-package --package-sha256 PACKAGE_SHA \
  --build-dir /path/to/new-build --build-sha256 BUILD_JSON_SHA \
  --validation-dir /path/to/new-validation --validation-sha256 VALIDATION_JSON_SHA \
  --reviews /path/to/review-inputs/reviews.json --reviews-sha256 REVIEWS_JSON_SHA \
  --candidate /opt/family-dashboard-candidates/NEW_CANDIDATE
```

candidate 必须是新目录，与所有输入目录分离。装配验证完整包、工具原字节及测试原件，但不访问 Docker、不停服务。返回的 `planSha256` 交非作者审查后才作为下述输入；不能重新生成后沿用旧批准摘要。

`candidate/source` 是挂载给容器 uid 10001 的只读公开源码子树，目录显式为 `0755`，普通文件（包括 `RELEASE-MANIFEST.json`）为 `0644`。候选根目录仍 `0700`，包、构建/测试回执和 reviews 文件仍 `0600`；私有 env 从不放入 source。Linux 合成演练需实际以 uid 10001 验证 `/release` 遍历和读取，Windows 的 chmod 替身断言不能代替该检查。

## 服务器切换

只由集成人按已有部署授权执行。CLI 只接受 Linux、root、`python -B`、固定 `/opt` 路径及本机默认 Docker，不允许 `COMPOSE_*` / `DOCKER_*` 环境选择器。沿用原发布互斥锁，避免与历史控制器并发。

```bash
python -B deploy/steady_release_controller.py stage \
  /opt/family-dashboard-candidates/NEW_CANDIDATE REVIEWED_PLAN_SHA
python -B deploy/steady_release_controller.py activate \
  /opt/family-dashboard-candidates/NEW_CANDIDATE REVIEWED_PLAN_SHA
```

`stage` 只读核对包、候选镜像实际运行时、构建/验证原件、已安装源码、Compose、四服务及配置，并生成独占 `stage.json`。stage 与 activate 停机前均通过只读卷核实际成功迁移 marker 的 SHA，只读该普通文件、不读 live SQLite；缺失或变化提前拒绝。`activate` 再核相同身份后顺序执行：

1. 保留旧源码、原 `.env`、旧镜像标签，以及 app/sync/media 各自的实际 `Config.Env`。私有 env 文件均 `0600`，不写入公开回执。
2. 停备份 timer，确认没有运行中的备份；停 web、media、sync、app，确认无数据卷使用者且全部干净退出。
3. 对完整 registry 组做当前停写快照和备份；副本原件保留在轮换目录外。所有家庭、平台、marker 和备份都通过验证后才安装源码。
4. 新 app 先启动并健康，核运行时与其原环境，然后停止并确认干净退出。完整比较本次 before/after 的 schema、记录、序列和 registry；只忽略 SQLite 文件布局字节变化，保留所有逻辑指纹。
5. 再启 app，随后 sync/media/web；逐服务核对旧环境的键值集合与新运行时字节，正常 TLS `/healthz` 通过后恢复备份 timer 并确认 active。

Compose 可能重新排列 `Config.Env`。停机前的 stage 与绑定要求原顺序摘要一致；重建后允许顺序变化，但每个服务必须与自己原来的全部键和值完全相同。拒绝重复键、换行和无法表示的环境项。

失败保留 `activation.json`、旧 source/config/images、备份、before/after 和所有原件。启动过候选后发生任何失败，尝试再次停 timer 与四服务；只有实际检查无数据卷使用者才记 `candidateStoppedAfterFailure=true`，停止失败不能声称已停止。**不自动还原、不自动重试、不复活旧应用。** 先审查失败阶段与完整备份，再决定恢复操作。历史失败发布目录完全不参与删除或修改。

发布后另行独立只读审计实际 source/runtime/plan/activation 身份、公开页面及静态资源、匿名权限拒绝、四服务状态、timer 和私有配置摘要。日志、真实数据库、env、相片和截图不得提交 Git；需要传回文档原件时仅下载 JSON/日志，排除 env 与数据库。

## 本地验证边界

新测试在 `tests/test_steady_release_data.py`、`tests/test_steady_release_controller.py`、`tests/test_steady_release_package.py`。

- data 测试实际运行合成 SQLite、多家庭备份及冻结源码的正常 Flask 初始化。`historical/materialize` 依赖本地固定 Git 对象，不应选入没有 `.git` 的服务器隔离测试包。
- package 测试创建真实临时 Git 仓库和 archive，验证基线隔离、输入重读、装配与证据篡改拒绝；镜像构建使用记录型替身，不能写成实际 Docker 构建。
- controller 测试使用记录型 Docker/systemd/TLS 替身，验证顺序、环境、失败保留与停止错误；在 Windows 仅替身模拟 POSIX `0600`。实际 Linux 权限、镜像启动与 HTTPS 仍需上述演练和发布审计。
- 回归原 membership package/build/data 测试，证明原默认合同与拒绝条件保留。每轮 JUnit 原件保存在忽略的 `test-results/` 下，失败轮保留。
