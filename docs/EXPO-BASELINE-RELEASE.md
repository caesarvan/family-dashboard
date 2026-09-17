# Expo 本人资产与来源报告：55→55 发布适配器

本适配器是下一批候选，只在本地生成未绑定审查稿，没有执行打包、远端阶段或部署。编写时父 segments 镜像已构建，Linux 验证正在进行，尚未收到激活及独立读回结论；必须由集成人确认父版本实际发布完成后，才能将其作为安装基线。

## 固定输入与范围

父原件为私有 `expo-segments-tools-20260917-r1/` 的七份算子、`prepare-package.py` 和 `bind-release.py`；九份 SHA 固定在 `deploy/expo_baseline_release/prepare.py`，全部按实际 `generation.json` 核对。父身份：

| 字段 | 固定值 |
| --- | --- |
| archive | `7e49d1ff34cdb5930f33646dec596dab4ca2572c8fb884b74c9d74287a846cf6` |
| manifest | `88de50dabe7bd2309f8f0d46f69ffbe3a3f9f3ecf03449445410f816564124bd` |
| app／sync／media image | `sha256:f06313c2495f9e348a6f82fef00d09ef16aa73e07367e2554761876042f26c9b` |

本批要求本人资产读取、来源导入及独立消费观察三个后端、财务入口的实际变更，并要求模型、面板、Node 模型测试、真实浏览器及两个会话专项进入最终源码。没有新运行模块、路由或 DDL；Docker、依赖、环境、备份、原 55 表和注册库保全守卫保持。

父版本已经显式纳入的 `frontend/tests/journeySegments.test.ts`、`frontend/tsconfig.tests.json`、`frontend/typecheck.mjs` 原样保留；不重复注入，也不将它们再次列为新增文件。完整构建输入仍须与最终 Git、manifest、导出逐字节核对；本地构建文件不是镜像内 Node 测试。

## 生成及执行边界

在独立候选源码内，使用 `python -B`；路径必须为绝对路径、非 symlink／junction，输出直接位于私有 access 根下且此前不存在：

```powershell
python -B deploy/expo_baseline_release/prepare.py --source-root <private-access-root> --output <private-access-root>/expo-baseline-tools-<new-id>
```

未提供 `--freeze <new-final-freeze.json>` 时，测试集合／数量不绑定，不能执行服务器阶段。最终 freeze 必须来自已审查源码、构建、浏览器和实际 collection，不复用父数量；即使提供 freeze，生成结果仍未绑定。还需独立核九份字节、审查七算子、绑定实际 metadata，之后才能由集成人使用新包装脚本操作。不得运行或覆盖旧批次算子。

`stage.py`、`validate.py`、纯 contract 保持父原字节；验证资源为内存 896 MiB、tmpfs 640 MiB。阶段防重入、未绑定拒绝、原身份与源散列、受控路径、完整停写备份、新 app 启动前后 rows／schema／sequence／registry 比较和后续逐库备份守卫均沿用。逐库在线备份不等于全局原子快照。

post 保留原 29 个唯一匿名路径，新增以下五项，合计 34；每项只接受 401，200／403 也视为边界错误：

- `/api/finance-baseline/private`
- `/api/finance-baseline/imports/status`
- `/api/finance-baseline/imports/status?mode=spending_observation`
- `/api/finance-baseline/imports/status?mode=baseline&operationId=<64个0>`
- `/api/finance-baseline/imports/status?mode=spending_observation&operationId=<64个0>`

## 本地已做验证

`tests/test_expo_baseline_release.py` 普通专项 24 项通过；覆盖原字节篡改、排他输出、输入变化、越界／超量／重复 freeze、递归 DDL 拒绝、Docker 原字节和新增匿名检查。

同一测试文件的显式 CLI 另读取九份私有固定原件和父归档，在纯临时目录生成并检查实际代码。它禁用生成代码的进程和网络调用，实际验证 7 个未绑定入口拒绝、38 个坏 freeze 拒绝、完整父选择器及新选择器相等、三个本地输入缺失拒绝、敏感／额外生成文件拒绝，以及五个新增 URL 的 401／200／403 分支。

真实候选 `0c906583120d49c1225824a850179e4d72e55fb5` 的构建证据 `289b3c097ffb3648f42db79cb7f2d35952059d7e0cc3e7e0a8544665e02f99b2` 含 182 个输入，全部被实际选择器覆盖并与固定 Git blob 散列匹配。该受验树尚不含本适配器／测试及 `test_finance_import_sessions.py`，报告明确列出三项待集成，不称最终发布源码已齐；带实际 freeze 的最终验证会拒绝任何缺项。

原件在作者 worktree 的 ignored `test-results/`：`baseline-release-r1.xml` 和 `baseline-release-pinned-r1.json`。它们分别是 24 项测试与实际固定原件检查，不累加成业务或 Linux 验证通过数。

最终 Linux 范围为 10 个模块：两个会话专项、原 baseline／source bridge／spending observation 三模块、frontend runtime、家庭隔离、平台备份、持仓迁移和本适配器；准确数量由最终 collection 提供。当前未运行本批服务器验证、未绑定新包，也不代表真实账号导入、外部同步、实体电视或原生设备验收。页面实际本地证据见 [候选验收](EXPO-BASELINE-ACCEPTANCE.md)。
