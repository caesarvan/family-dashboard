# 发布打包源码批量读取

`deploy.packager_batch_read.transform_prepare(source: bytes) -> bytes` 是下一批发布适配器可显式调用的转换函数。它只返回新的 `prepare-package.py` 字节，不执行 Git、打包、绑定或部署。本次没有修改或接入正在使用的账户九份发布工具，也没有修改任何业务模块、数据库、Docker 或发布白名单。

调用方先按该批已审查 SHA-256 读取父打包脚本，再应用转换，最后像以往一样核完整生成差异、记录新 SHA，并由非作者审查。函数只接受账户打包脚本的确定结构；缺失／重复关键片段、已转换输入和意外函数集直接拒绝，不回退到猜测性替换。它保留其他函数和顶层内容；下一批自己的前缀、迁移、基线和依赖更新仍由独立适配器负责。

每次 `inspect_inputs` 都重新执行：

- 实际 main 分支、HEAD、完整 clean 状态、正式 integration、同树和祖先关系核验。
- 原始完整 `tracked_files` 的路径／mode 检查，继续拒绝 symlink、gitlink、隐私及生成路径；[批量 reader](GIT-BLOB-READS.md) 的原始 blob 能力不代替该策略。
- 从本次固定 main commit 读取 `deploy/git_blobs.py`，验证已审 SHA-256 `c71a4e60e65b45581899d0e2347f2e510bdc37fd508559155db1df8d3c3cd89b` 后编译这些字节；不从可变工作文件 import。
- 保持完整构建输入集合，两份构建／受验记录各自的 commit/tree、原始 SHA-256、导出集合、working-file 字节、大小上限、包分区、旧归档、Docker、未改模块、完整 delta、迁移 SQL 和测试来源守卫。

Git 读取统一不跟随 replacement refs，不懒加载缺失对象，不允许交互凭据请求。一次检查内按完整 commit 复用刚读出的 blob，函数返回后即丢弃。`prepare` 原有写前／写后两次完整检查、binder 的独立检查和全部最后读回不变；不能用一次成功结果代替后续检查。

## 本地定向验证

`tests/test_packager_batch_read.py` 需要显式 `PACKAGER_BATCH_PARENT` 指向固定账户父脚本，且自身再核父 SHA。未提供私有原件时明确 skip，不下载或寻找其他版本；本模块不加入服务器业务回归。定向测试覆盖转换边界、未改守卫 AST、真实临时 Git 身份／工作文件／替换 refs、固定 reader 来源，以及危险路径和 mode 拒绝。

同文件的显式 CLI 接受 `--parent`、`--freeze`、`--source-repo`、`--output`。它用独立临时 Git 仓库和本地对象 alternates 重建冻结 main／integration；仅该临时目录有 refs、索引和文件写入，共享仓库只读。随后调用父版与转换版的 `inspect_inputs`，逐项比较完整六值返回结果，计时并统计实际 Git 进程；再次执行批量版验证无跨调用缓存。进程守卫仅允许本地 Git 读命令，网络禁止，不调用 `prepare`／`bind`。

基准继续用临时副本注入工作文件、integration ref、tree、构建证据／输入集合、导出、旧归档、delta、SQL 摘要漂移，确保下一次检查拒绝；已忽略的临时私有文件不会进入包。真实父工具、freeze、构建证据、导出与旧归档前后逐文件 SHA 核对，输出新独占报告。只读核验返回值的等价不等于已实际生成相同归档，也不代表下一批发布工具已集成或生产耗时已改善。

实际基准使用 main `40fa82ceba456e48b56ac181f51828bd7d4ff953`、正式 integration `545a890c7f53fbb21e35e097fb65d0d756bcd52c`，与账户 R2 构建证据 `cca46bcf1450f1650ce061781ec5fb5bd57e45d4f54058e7fa39bbd9fdc2d11f`：692 个源／导出文件、187 个构建输入，完整六值结果全等。原版一次 1433 个 Git 进程／86.287 秒，批量版 19 个／2.713 秒；独立再检查 19 个／2.597 秒。九类漂移实际拒绝，忽略文件未入包，临时仓库已关闭清理，所有外部原件前后 SHA 一致。未清系统缓存，只能报告本机本次 `inspect_inputs` 耗时，不能外推完整打包、绑定、上传或服务器速度。

私有基准原件在 `worktrees/expo-packager-batch-read/test-results/batch-benchmark-r2/result.json`，SHA-256 `650a30dd02316f582e4011474d58cf73a0bc2ae68f3ff9a81226a70787284db2`。最终同字节定向测试 18/18，通过时间 11.63 秒，`test-results/batch-final/tests.xml` SHA-256 `c494282e3c9a445c837662ffa072f8f3dc8c3f7c676b472b826febf62432f19c`，源码前后 SHA 相同。首轮定向负例只替换了一个重复 profile 标识，未构造预期损坏；后改为完整移除该标识。首轮基准因临时 Git alternates 的 Windows CRLF 在初始化阶段拒绝，改为该文件明确 LF 后才完成上述实际比较；失败 XML／报告均保留，没有修改父工具。
