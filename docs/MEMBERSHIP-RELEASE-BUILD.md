# 成员候选镜像构建与隔离验证

`deploy/membership_release_build.py` 依赖已固定的 `membership_release_package.py`（作者提交 `006b38b7a155ef53a269600983eaf5a73571fdfd`），只接受由该脚本完整读回验证的包。自身脚本也必须与候选包字节相同。它不执行 SSH、安装依赖、生产迁移、备份或激活；Docker 只连接本机 Unix socket。每次使用全新输出目录，失败保留日志，不覆盖原尝试。

```sh
python -B deploy/membership_release_build.py build --package-dir /absolute/package --package-sha256 SHA --output-dir /absolute/new-build
python -B deploy/membership_release_build.py validate --package-dir /absolute/package --package-sha256 SHA --image-id sha256:IMAGE --selection /absolute/selection.json --selection-sha256 SHA --pytest-dependencies /absolute/existing-test-deps --output-dir /absolute/new-validation
```

构建固定继承父镜像 `sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2`。Dockerfile 只有 FROM、限定删除 `/app/static/experience` 的 RUN、完整 runtime COPY。不开构建网络、不拉取新父镜像，不运行 pip/apt。完成后检查父层为精确前缀、只增加清理和 COPY 两层、父 Config（除 Docker 的 Image 字段）完全保持；以无网络只读临时容器实际逐文件核 `/app` 与 runtimeFiles 精确相同。`build.json` 记录 imageId、sourceHead/tree、package/manifest SHA、parentConfig、runtimeHashes 与 Dockerfile SHA。

冻结 selection 的字段必须精确为：

```json
{
  "schemaVersion": 1,
  "sourceHead": "40位候选提交",
  "manifestSha256": "64位包manifest SHA",
  "modules": ["tests/test_example.py"],
  "nodeids": ["tests/test_example.py::test_example"],
  "allowedSkips": {"tests/test_example.py::test_example": "精确跳过原因"}
}
```

模块均须属于包，nodes 必须唯一且覆盖每个模块；真实 pytest collection 必须逐项等于冻结集合。没有隐含 deselect。只接受 allowlist 中精确 node 和原因的 skip（移除 pytest 展示前缀 `Skipped: `）；xfail、额外 skip、缺项、失败、异常均不通过。JUnit 数量及每项身份再次核对；预先收集集合不是执行通过。

验证容器运行实际 `/app` 源码。完整候选挂载 `/test-support:ro`，现有 pytest 依赖挂载 `/test-deps:ro`（不安装），冻结输入另只读挂载；仅新 proof 目录可写。网络 none、根文件系统只读、UID 10001、无 capabilities、no-new-privileges、资源限额，临时 `/tmp` 放合成数据。没有生产 data/env 挂载或凭据传入。每次只清理本次 `docker create` 返回的容器 ID。

`runtime.json` 的 before/after 是完整 runtime 哈希；loadedBefore/loadedAfter 是每个根 Python 模块的真实 `/app/name.py`，不能被 test-support 同名文件遮蔽。sourceBefore/sourceAfter 是 manifest.files 全集（不含 RELEASE-MANIFEST.json，后者另核），依赖目录也在宿主与容器内前后核完整哈希。四个既有迁移检查器仍来自只读 support，仅其 ROOT 指向已核 `/app`，真实 schema 模块与定义前后保持，不改生产逻辑或测试断言。

`validation.json` 含 imageId/sourceHead/tree/manifestSha256/packageSha256、exitCode、containerExitCode、allPassed、counts、selectionSha256、dependencyHashes，及 `evidence:{relative:sha256}`、junitPath/runtimePath。容器退出 0 而证据失败时 exitCode 仍为 1；不以单个进程成功代替完整守卫。原始 stdout/stderr、命令、日志、XML、runtime 记录均排他保存。

作者专项范围是记录命令的 Docker 替身与真正临时 Python/pytest/SQLite：覆盖父配置/层/实际文件漂移、失败无成功封口、只清理本次容器、精确选择与 skip、影子模块、测试和运行文件写后变化、JUnit 同数异名。它不证明实际 Linux Docker 或最终业务选择已经通过；这些由上层在明确候选包上运行。

首轮实际 20／20 通过（25.05 秒），XML `61d0eb4d767633c2071146eac1fddc6ee05de48f7ca1f8c9bc3045f4d4d2330c`。随后补宿主侧封口四项，4 通过／20 未选择（6.55 秒），XML `dd02c770e7dce7208c3f0282ea7593d14f269a34f2e4d40564443ccd27796dd5`；命令输出／超时原件保存两项，2 通过／24 未选择（0.41 秒），XML `9b02050de514c7d225e9c9eef065526ba59c657fa9267df05cce169537653076`。各轮无失败／错误／skip、测试期间源码前后相同；是分轮 26 个不同检查，不是最终 26 项同轮全跑。作者树 `test-results/membership-build-helper-r1/` 至 `r3/` 保存完整原件。
