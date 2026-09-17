# Expo 行程分段发布：55 → 55

本适配器是未发布候选，只生成本地、未绑定的九份审查文件。没有连接服务器、执行 Docker、打包应用、绑定或运行生产阶段。当前安装身份见 [README](../README.md)；父版例行计划已完成的阶段不得重放。

## 固定父版本与最小变更

[`prepare.py`](../deploy/expo_segments_release/prepare.py) 固定 `expo-routines-tools-20260917-r1` 的七个算子、包生成器及绑定器，逐一验证九份原始字节的 SHA-256。

- 父 archive：`41735eb43154748bc912e4216c07b7131f7fdbd91e668c8c0da8afa8e1d95e55`。
- 父 manifest：`0cb3bb21365f6dc923264b1a6504396dec303a932b766e926f336937580ad8a4`。
- app／sync／media 父镜像：`sha256:3c576cd3814f7ec8482ff190017eb3cc9a4c3b6dd2dd0aee7d9623e8d9ae7125`。

保持 55 张户内表与两张平台注册表，无 DDL、迁移或新增依赖。`UNCHANGED` 仅移除本批编辑来源快照 API 的 `journey_workflows.py`；父 tuple 其余顺序与字节守卫均保留，Dockerfile 仍必须与已安装包完全一致。

必需修改该后端和五个前端接线文件（types、HouseholdApp、TripsScreen、MapWorkspace、AssistantScreen）；必需新增分段 model、Node 测试、Panel／Fields、API 快照专项、浏览器脚本和本适配器／测试。最低集合不替代最终完整 changed／added／removed 核验。

首份实际 freeze 因 Node 测试不在父包选择器中而被拒绝，发生在创建输出目录之前；未产生工具目录或服务器操作，失败记录保留。本批仅对生成包选择器增加恰好三个必须已跟踪的来源文件：`frontend/tests/journeySegments.test.ts`、`frontend/tsconfig.tests.json`、`frontend/typecheck.mjs`。它们归档用于复现已验证构建；不在 Python 镜像执行 Node 测试。全局 `deploy/prepare_release.py`、纯合同、Docker 及完整构建输入逐项核对均不改，不开放其他测试文件、node_modules 或生成目录。

## 生成与验证边界

Python 必需选择为十一个模块：新编辑快照专项、原工作流、复杂分段、事务会话、改期、旅行日历发布复核、静态托管、家庭隔离、平台备份、55 表保全和本适配器。最终唯一用例数来自最终冻结源码的实际 collection；收集不是通过数，不能沿用父版 278，也不把 Node 测试放进 Python-only 镜像。

`stage.py`、`validate.py`、`expo_contract.py` 保持父原件字节。验证资源保持内存 896 MiB／tmpfs 640 MiB；精确 Windows junction 跳过、实际测试选择与计数、运行源码前后核对均继承。activation 只替换发布前缀，保留停写、全组备份、原行／schema／序列／注册库与 app 启动核对和恢复顺序。post 保留原 27 个唯一匿名端点，增加 `/api/journeys/templates` 和 `/api/journeys/` 加 24 个零，共 29 个唯一端点，全部严格要求 401；正常 TLS、静态路径拒绝、TV 跳转和经典回退均保留。post 必须提供已审自身 SHA。

最终九文件仍需非作者逐字节审查及独立 operator-review 后才能绑定。实际 Linux、READY、激活和读回独立进行，不自动重试未知阶段。停写完整备份与 post 新一次逐库在线备份分别核对；后者不宣称全组全局原子快照。

按 [Git 工作流](GIT-WORKFLOW.md) 冻结与审查后，由集成人使用全新私有目录：

```powershell
python -B deploy/expo_segments_release/prepare.py --source-root <私有access绝对路径> --output <全新expo-segments-tools目录> --freeze <本轮已核对freeze.json>
```

输出必须是 access 直接子目录且不存在；无 freeze 仅生成待审稿。原件校验失败、输入漂移、重复 JSON 键、错父身份、缺少必需项、非法数量或覆盖旧输出均拒绝。

## 本地测试

[`test_expo_segments_release.py`](../tests/test_expo_segments_release.py) 继承父适配器的纯合成路径／固定散列、独占输出、输入竞争、freeze、递归 AST／DDL 拒绝和 Docker 全字节守卫，并核精确新增匿名端点仅接受 401。

首版实际 24 项合成测试通过，0.88 秒；JUnit `test-results/segments-release-r1.xml` SHA-256：`b41785d9d3d0494db7d8115f128a362483042c9e9f9baa4ce681af33b9808637`。

另显式私有原件检查读取固定父包和 Git `7713ad1fd091d7390612c52d434b97e54e99f54b` 的 Docker blob，在临时目录生成九文件：33 项错误 freeze／漏项及七个未绑定／缺少审查材料入口均拒绝，29 个唯一匿名端点与新项严格 401、关键阶段字节、896／640 资源和递归语法全部核对通过。报告 `test-results/segments-release-pinned-r1.json` SHA-256：`051cadf870118a38d7a4342eefe1b2a409599a5e149b50850738085a8a01aef2`。

三文件来源白名单修正后，实际 **26 项通过，0.46 秒**，JUnit `test-results/segments-release-r2.xml` SHA-256 `235a6ff8bab9a7caae51f41f6bc4e22d4e6c11e812a21160e92c96784beb8227`。私有检查调用固定父原件和生成包的真实 `selected_sources`，对 Git `d415e8f8e373c9f4c5ba2b0ca47ae4903d9d0e8b` 与已验构建 `c7248a60…` 核全部 180 输入可选择、差集精确三个文件、缺一拒绝及其他私密／依赖／生成路径排除。报告 `test-results/segments-release-pinned-r2.json` SHA-256 `3a791a6b8289ba1f4e2332083a57ef13558516527d7b49af55fb5acf3cdcf157`；没有传入最终新版 freeze，其接受状态仍待单独核验。最终 collection 必须随测试修订重新收集，不能沿用旧 259 项。

生成代码运行期间阻断网络和进程调用，没有建立真实包或绑定。合成计数 9991 只验证配置透传，不是实际测试数量。上述结果不替代最终源码 collection、Linux、浏览器、实际云或本轮上线验收。
