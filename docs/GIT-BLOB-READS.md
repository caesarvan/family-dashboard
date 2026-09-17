# 固定提交的批量 Git blob 读取

`deploy.git_blobs.read_git_blobs(repo, full40hexcommit, paths)` 返回保持输入顺序的 `dict[str, bytes]`。它是下一批本地构建／freeze 工具可采用的独立辅助函数，**尚未接入任何现有发布 helper**，不改变本轮例行计划发布过程。

非空选择使用两个只读 Git 进程：一次 `ls-tree -r -z --full-tree` 读取指定 commit 的完整树元数据，在内存按字面路径筛选对象 ID；一次 `cat-file --batch` 只读取 commit 与所选 blob。路径不拼到命令行，两个进程的参数长度固定，避免大量路径超过 Windows 命令行上限。每个响应严格核对对象 ID、类型、长度、顺序、原始对象 SHA-1、分隔符和最终结尾；缺失或不完整结果整体报错，不返回部分字典。空列表仍核对提交对象。替换 refs 被忽略，禁用缺失对象的延迟网络获取；不 checkout、不改配置或源文件。

只接受完整 40 位 SHA-1 commit，拒绝浮动 ref、tree／tag／blob 冒充 commit。路径是仓库根相对 POSIX 字符串；拒绝重复、空段、`.`／`..`、绝对路径、反斜杠、冒号、NUL／CR／LF 和无效 Unicode。空格、Unicode、字面通配字符、二进制文件和空文件保持原字节，不经 textconv、换行转换或工作目录过滤。目录和 gitlink 不是 blob，拒绝读取；Git 中的 symlink 是 blob，只返回链接文本，绝不跟随链接。

函数假定调用方已批准本地仓库和 Git 运行环境。它只验证固定提交对象，**不替代发布安全检查**：

- 调用前后重新核对实际 branch、HEAD、tree、完整 clean 状态；固定 main／正式 integration 身份和同树要求。
- 保留 working-file、未跟踪文件、源码白名单、路径及 symlink／junction 守卫。这里读到旧 commit 的正确内容，不表示当前工作树仍干净或未变。
- 将每个 blob 的 SHA-256 与已接受 build／browser／collection 的原件逐项核对；构建输入、导出与夹具的等价规则不变。
- 写出前再核对源码和原件，保持独占新输出、绑定、非作者审查与实际服务器验证。SHA-1 是 Git 对象完整性检查，不是替代既有 SHA-256 发布证据。

原 Windows 微基准固定 `785db20b5abb1b7677fe02417cc055874772e651`，从实际 R3 构建选 30 个文件，三轮 `git show` 循环中位 1.427 秒、单次 batch 中位 0.057 秒。该旧基准尚未包含本函数新增的 `ls-tree` 映射，且未清除系统缓存；不能据此称完整 freeze 或本函数快 25 倍。私有报告 `git-blob-batch-benchmark-20260917T105740679229Z.json` SHA256 `0d2be598814fa30b8e7d8066db70e5d7262a9099d6fa7915620c3873a8b6f3a4`。

专项验证使用独立临时真实 Git 库，覆盖历史提交、工作文件变化、替换 refs、binary／Unicode／空格路径、字面通配符、缺失／目录／gitlink／非 commit 和受损 batch 协议；另构造 320 条真实树路径，其原路径参数超过 32767 字符，核对固定参数及仅请求所选 blob。不运行家庭业务、构建或部署；最终实际计数与当前 30 文件等价读回由作者交付记录，合入不代表任何 helper 已采用。

作者最终实际运行 `python -B -X utf8 -m pytest tests/test_git_blobs.py -q -p no:cacheprovider`：41 项通过，12.41 秒；私有 `worktrees/git-blob-batch/test-results/git-blobs-final.xml` SHA256 `1fb15016c1ba4dc9a94154598d9dc329836f4f40d1ae2d561ab029207f3330fb`。最终两进程函数另读上述 30 个构建输入，474988 字节与 `git show` 及原构建 SHA 全部一致；单次 0.099 秒对 1.408 秒，约 14.2 倍，仍不是整体发布性能结论。等价报告 `git-blobs-current-30-final.json` SHA256 `22719776ad06af8bd4138b6dacfca7de7585334fe03872d11e0454bf9ee6361a`，与 XML 位于同一私有目录。报告不提交代码库，测试后只补充本文记录。
