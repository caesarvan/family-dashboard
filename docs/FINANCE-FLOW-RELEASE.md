# 收支方向列：固定发布合同

本适配仍是候选，未执行 Linux 构建、stage 或生产激活。它把已审的通用支付流水方向列映射推进到既有五服务发布流程；不修改业务代码、数据库结构、运行限额或恢复算法。

## 固定身份与范围

- 实际父版：source `63dc63476b046856bf9893c19595e2971ebc13c7`，tree `0767de6bdcc85dda4be520242274b7f07b578a90`；manifest `7b77dfbc5c3a1f132706817fa10fbbf0f01c022ce27207c58999df60b5645d3f`，package `57d835b23db00e28408cbd405024be0b588bf8a822b75c02ec701a745d68ec7c`。父版生产独审 SHA `0d77aeaf6be26223ef8f9aec069f4ccb2b27960c482beb6a4de7e33c807a2a8c`。
- 应用父镜像 `sha256:b63c1f57eac42a5b25c30d03b342030788796b57f9b51775569f126ae7997fa2`；decoder 与 web 保持原固定镜像。非 Expo 112 文件只允许 `finance_hub.py` 变为已审 `27ef835bca9a472a2ef1b98f06bbf1c19fdd4ed0ade03bf0862b7c9d530fdf88`，其余 111 个文件按完整映射固定。
- 静态 profile 为 `discovery-r1-finance-flow`，controller mode 为 `finance-flow-source-update`。Docker、Compose、Nginx、依赖和 decoder 来源固定；73/9 → 73/9，无迁移。JSON 不能指定任意策略模块。
- 可复用固定 `9ee62cb` 的已审 fresh Expo 导出，但必须比对全部前端输入、9 个 supplemental 输入和额外 `tests/test_expo_finance_import.mjs` 的字节；文档头变更不需要重建。旧父版浏览器/资源证据不等于新财务功能已运行。财务实际三场景及边界见 [浏览器验收](FINANCE-FLOW-BROWSER.md)。

## 构建与准入

`deploy/build_finance_flow_release.py` 提供 `prepare`、`verify`、`build`、`validate`，参数沿 discovery 入口：

```text
prepare --repo REPO --commit HEAD --export-dir WEB --build-evidence EVIDENCE --evidence-sha256 SHA --output-dir NEW_PACKAGE
verify --output-dir PACKAGE --package-sha256 SHA
build --package-dir PACKAGE --package-sha256 SHA --output-dir NEW_BUILD
validate --package-dir PACKAGE --package-sha256 SHA --image-id IMMUTABLE_ID --selection SELECTION --selection-sha256 SHA --output-dir NEW_VALIDATION
```

新镜像仍只增加清理/COPY 两个文件层并保持父镜像最终配置；实际 Linux 验证必须绑定新 package、manifest、镜像、完整运行输入和导入路径。选择严格为原作者 JUnit 的 33 个节点（26 项方向列、7 项相邻），3 个测试模块也固定 SHA，`allowedSkips={}`；排序节点列表的 `package.encoded` SHA 为 `51ecf844ed7c4f4cc4131095b229f8645a4c1e9ae5885b34054078b589ac6609`。不能以任意 33 项或通过摘要代替。

`deploy/prepare_finance_flow_activation.py --inputs-file INPUTS --env-sha256 SHA --output NEW_CANDIDATE` 接受现有 package/build/validation/selection/parentAudit、五类独立 reviews，以及三个原资源描述符 `image_overlap`、`nginx_raw`、`duplicates`。另外必须提供：

```json
{"retainedDiscovery":{"package":{"root":"/absolute/old-package","sha256":"57d835..."},"build":{"root":"/absolute/old-build","sha256":"18caab..."},"plan":{"path":"/absolute/consumed-parent-plan.json","sha256":"542b77..."}}}
```

示例省略号不是合法输入；完整常量在源码。父 plan 仅作为已消费的只读原始证据索引，绝不重放。原 package、manifest、归档内容、build 全原件、资源 input/run SHA 与父 plan 的 `verifiedEvidence` 精确核对。为保持旧 packager 自校验，不让新 packager 冒充旧包，也不动态执行包内策略。

继承时使用实验当时的原 112 文件 map 和原 image/source，交给原 discovery 资源验证器核读真实 HTTP、数据库、cgroup 和清理原件。候选只证明另 111 个运行文件不变，且财务模块只有 `_import_conflict`、`_column_controls`、`parse_import` 三个已钉源码函数内部变化。媒体解码/播放、上传及四并发重复提示的实测范围可以继承；**这不是新财务导入内存、并发或混合负载测试**，也不改变旧实验容量结论。缺失、失败、换源或改动的证据均拒绝。

## 激活与失败恢复

`deploy/activate_finance_flow_release.py` 沿用已审控制器的 `stage`、`activate`、`verify-rollback` 参数及双锁。stage 重新只读核对实际父源、环境摘要、固定五服务与镜像；activate 消费单次计划、停止 timer 和 writers、完整库组备份、安装源码、app-only 启动后停止并全表/settings/序列保全，再按 decoder、workers、web 顺序恢复。保留环境、decoder 与既有权限。

失败只停止本次已核候选进程并保留证据，不自动恢复旧源码/数据库，不重试已消费计划。显式完整库组恢复和 `verify-rollback` 沿 [现行数据保全流程](LOCAL-PHOTO-RELEASE.md)，不能只恢复一个家庭或一张表。本适配的录制 Docker 单元检查不代表真实 Linux 生命周期又执行一次；实际发布仍需固定计划非作者审查、授权执行及只读回读。财务原件、凭据、数据库和测试输出不入 Git。
