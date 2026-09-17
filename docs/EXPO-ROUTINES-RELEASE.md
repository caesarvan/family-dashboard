# Expo 家庭例行计划发布候选：55 → 55

本适配器只生成本地、未绑定的审查稿，尚未用于例行计划发布。接口见 [例行计划](ROUTINES.md) 与 [Expo 操作恢复契约](EXPO-ROUTINES-API.md)。不连接服务器、不运行 Docker，也不执行打包、绑定或生产阶段。

## 固定父版本与保护范围

[`prepare.py`](../deploy/expo_routines_release/prepare.py) 固定 `expo-documents-tools-20260917-r1` 的七个算子、实际包生成器和绑定器，校验九份原始文件的完整 SHA。父旅行资料版本已由发布执行者确认于北京时间 2026-09-17 18:13:25 激活、18:13:50 完成正常 TLS 读回；以下固定身份与实际安装一致。本适配器自身仍是未发布候选。

- 父 archive：`68eefe89a79deb6373cdeacc9f115c9e29a8fde27481b3b22ca2089911a006e4`。
- 父 manifest：`9fe4a665f724c1e54a9d28b93bdaeb94df0ec8b39f027c15b669547e02dd5b92`。
- app／sync／media 父镜像：`sha256:79d20992e17a2ed5f1c03a47acd0bd8af91625d2445f5eb8b7c79d1b7ef39019`。

保持 55 张户内表及两张平台注册表，无 DDL、迁移或新增依赖。父版 `UNCHANGED` 本来不含 `household_routines.py`，因此完整继承全部保护项；Dockerfile、备份／恢复辅助、财务、旅行工作流、电视显示与播放器等继续按旧包逐字节核对。必需变更包括例行后端、旧过期确认测试、客户端类型及入口；必需新增包括例行 model／Panel、会话／Node／浏览器测试和本适配器。最低集合不能替代最终完整 changed／added／removed 差异核验。

## 生成与发布边界

Python 必需选择为九个模块：原例行计划、例行旅行关联、新例行会话、成员会话、家庭隔离、静态托管、平台备份、55 表数据保全和本适配器。最终数量来自冻结源码的实际 collection；收集不代表执行通过，Node 测试不放入 Python-only 镜像。

`stage.py`、`validate.py`、`expo_contract.py` 保持父原件字节，验证资源仍为内存 896 MiB／tmpfs 640 MiB。activation 只替换发布前缀，保留停写、完整备份、原行／schema／序列及注册库保持、app 启动核对和恢复顺序。post 仅换前缀并新增匿名 GET `/api/routines/context` 和 `/api/routines/operations/` 加 64 个零，两项必须返回 401；既有匿名边界、TLS 静态资源、`/tv` 精确跳转与 classic 回退均保留。发布后的独立备份是逐库在线快照，不是全组全局原子快照。

按 [Git 工作流](GIT-WORKFLOW.md) 完成独立审查与最终冻结后，可由集成人在全新私有目录生成审查稿：

```powershell
python -B deploy/expo_routines_release/prepare.py --source-root <私有access绝对路径> --output <全新expo-routines-tools目录> --freeze <本轮已核对freeze.json>
```

输出必须是 access 直接子目录且不存在；无 freeze 仅生成待审稿。旧父身份、漏依赖、输入漂移、越界路径、覆盖旧结果及重复 JSON 键均拒绝。九份最终文件仍需固定字节独立审查后才能绑定；后续实际 Linux、READY、激活和读回另行验收，不重放历史候选或阶段。

## 本分支实际检查

[`test_expo_routines_release.py`](../tests/test_expo_routines_release.py) 的 24 项测试实际通过，0.36 秒；JUnit `test-results/routines-release-r1.xml` SHA：`6b1a13211e7384ce1b362bcfcbc11346503055c7860d0f5f7dff746fc57a98b9`。

另显式执行测试文件，传入私有原件目录和本分支 Git 基线 `0f0689c3e7debaeb65c504e6c09b14fe80840743`，核对九原件、旧包和真实 Docker blob，在临时目录生成九文件：29 项非法 freeze、7 个未绑定入口均拒绝；新匿名循环的 401 接受、200／403 拒绝均通过，既有端点集合仅增加两项。递归 AST、无 DDL、保全程序、896／640 资源及关键阶段字节核对通过。报告 `test-results/routines-release-pinned-r1.json` SHA：`89c4f6564978b0e739d2bc1d68a03b983c13c618cae3ba4f8f57d139adfeeb5e`。

显式检查阻断生成代码的网络／进程调用，没有打包、绑定或生产操作。合成数量 `9991` 仅验证配置透传，不是收集或运行结果；上述检查也不替代 UI、最终 Linux 或新版本上线验收。
