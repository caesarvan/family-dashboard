# 成员账户恢复浏览器验收

工具：[browser_expo_membership_recovery_check.py](../tests/browser_expo_membership_recovery_check.py)。这是独立测试工具，不改变应用；本提交先固定执行代码，实际结果保留在作者树独立 `test-results/expo-membership-recovery-UTC/`，不预先声明通过。

先原样继承既有 [成员浏览器脚本](../tests/browser_expo_memberships_check.py) 四组场景及断言，全部通过才继续两组恢复。每组独立合成 Flask/SQLite/HTTPS/Edge 环境；API 仅准备两户、同个人账户的明确绑定和私人资料，以及核对持久结果。

两组均关闭并重建服务器。第一组装入无效签名的旧家庭路由 cookie；第二组实际移走临时默认家庭库，保留平台和可用第二家庭，然后冷启动。浏览器新 context 打开真实 `/app`，点击「我的家庭账户」，填个人凭据、点击「登录个人账户」，明确「进入家庭」和确认。验证恢复到目标本人/家庭、读到目标私人资料而不泄露原家庭资料；缺库不得重建，移出的原库字节不变。没有业务成功响应替身、数据库直接造成功回执、提供方调用或真实家庭资料。

应用 HEAD 与构建 HEAD 分开记录。原构建 HEAD/tree 必须真实存在并为受验应用祖先；107 个实际构建输入在原 Git、受验 Git 和物理源码中逐字节相同，23 个导出使用支持 Windows 长路径的完整 `os.walk` 散列并逐场景复核复制品。应用全部 tracked 文件、复用 fixture 实际路径/散列、脚本自身固定提交及导出都在前后核验。接受此限定的构建输入等价，不声称应用两个完整源树相同。

运行参数为 `--source-root`、`--expected-head`、`--bundle`、`--build-evidence`、`--expected-build-evidence`；使用 `python -B -X utf8`。必须在固定干净作者树运行；脚本只读受验树和导出。临时目录使用短前缀；Python socket 与浏览器请求均禁止离开本地地址。每组失败保留堆栈和可得的截图，不将未运行组记为通过；不自动重跑。报告分别记录实际检查、失败、来源及临时目录清理。

原四组计划六图，新增两组各一张恢复目标可见视口，共八图供独立视觉审查；不是全页或实体设备验收，也不覆盖生产迁移、云服务或真实用户账户。

R1 对应用 `05232a15a189c4d3e8b89f1392445da7c5112097` 实际执行六组：原四组及坏 route 恢复通过，默认库缺失冷启动失败，共 5／6、七图。失败时 `/api/me` 返回匿名 200；独立真实冷启动 probe 进一步确认原默认库缺失时被重新创建 61 表，合成成员名称与密码 hash 重置，移走的原库仍保持。原 report SHA `198efb541f3ffd0027f580996a28901d28111b1d52bfb499dd543e915f806f8d` 与 probe SHA `d3ae09ff8e0866158b292c5ccc20d24eb79c9469ad19f863a2321ffbe8f953e9` 均保留；796 tracked／107 输入／23 导出、复用 fixture 前后相同，六临时目录清理，无页面异常或外网请求。此为真实冷启动缺口，未把期望放宽到接受重建。

后续可用 `--scenario missing_default_cold_recovery` 仅补该失败组；报告必须为 `requestedChecks=1`、`fullSuite=false`，不得称六组整轮重跑。补验也在启动后立即断言缺失默认库未被重建，其余真实登录、切换、隐私与源守卫保持。默认参数仍执行六组。
