# 采购日期与优先级发布入口

本入口已通过独立审查并合入 main；正式前后端包、真实浏览器、实际 Linux 298 项和具体离线计划均已有记录，2026-09-20 03:54:39（北京时间）激活，03:55:48 独立只读审计通过；本次计划已消费，不可重放。固定身份及最终状态见[集中验收](SHOPPING-SCHEDULE-ACCEPTANCE.md#shopping-schedule-release)。业务合同见 [SHOPPING-SCHEDULE.md](SHOPPING-SCHEDULE.md)，Expo 操作见 [EXPO-SHOPPING-SCHEDULE.md](EXPO-SHOPPING-SCHEDULE.md)；下方父版约束与作者阶段测试保持历史，不把本地生命周期测试当作真实生产演练。

## 固定身份与范围

`deploy/build_shopping_schedule_release.py` 固定 profile `expo-trip-tasks-r1-shopping-schedule`，配套 `deploy/activate_shopping_schedule_release.py`。发布计划不能自选基线、环境或运行文件豁免项。

| 已上线父版本身份 | 固定值 |
| --- | --- |
| Source | `8f7af253261f28269465f3a77b6c8433f2dc8142` |
| Tree | `f3ce2dbc584f446a750060a59bfaf2bb8c5d5710` |
| Image | `sha256:6bfdeb35d63dd55e0654f7d21f958fe7e10ffdda81ab06c4e4f5f517c782bed9` |
| Package SHA256 | `28c7389664710fe1d46aedbd1a5347ac370143187e06c1f590e8ef7bb5397487` |
| Manifest SHA256 | `8f6dbcde84adca5a63710b121904c2e9eae04d8b9bde5abf79599a01fbd7c5ad` |
| 独立生产只读审计 SHA256 | `69a3cca9d82fa544e7a1a010611b31effb12dec8aca0932968f3f33f9b7bc73d` |

非 Expo 运行文件仍为 104 个，仅允许 `app.py`、`data_portability.py`、`home_assistant.py`、`journey_reschedule.py`、`journey_workflows.py` 改变。其余 99 个文件的完整名称/哈希映射，经 `membership_release_package.encoded` 编码后的 SHA256 固定为 `a62c7ecfc1ad8b7d533e2418c290b054b21c9cbbf76e1a02d876538a99c91697`。这同时拒绝保留文件的新增、删除、改名和内容变化；重新计算外层清单不能放宽该约束。

根目录另允许 README 文档变化；前端、Expo 导出、部署脚本、文档和测试沿用既有目录边界。Dockerfile、Compose、nginx、Python 与前端依赖继续固定；环境和 membership marker 沿用已审控制器校验。前端测试名单完整保留，并新增且要求 `frontend/tests/shoppingSchedule.test.mjs`。

## 构建与审查顺序

1. 将独立作者提交经非作者审查后合入组合分支，固定完整 source head/tree。使用最终组合的 Expo 构建、原始输入哈希和导出文件哈希。只有**全部前端构建输入字节相同**时才能复用已有构建；后续可访问性修正改变前端后必须使用新导出，不能继续引用旧的 `8a633` 前端构建。
2. 用新构建入口的 `prepare` 准备不可变包，再用 `verify` 读回 package/manifest/archive 和原始构建证据。每阶段输出目录必须是新目录；不得覆盖失败或已消耗候选。
3. 集成人在隔离目录运行同一入口的 `build`、`validate`。验证选择必须绑定同一包的 source、manifest、明确 nodeid 与 JUnit 原件；本地合成 runner 的成功不计为真实 Linux 执行。
4. 将代码、包、构建、浏览器、Linux 及演练审查原件交给 `assemble`，产出 `shopping-schedule-release-plan`。计划绑定 25 个 operator 文件，包括旧数据核验链和本次两个入口。独立审查具体计划 SHA 后，集成人才进入 `stage` / `activate`。

参数契约沿用现有入口，可分别运行 `python -B deploy/build_shopping_schedule_release.py --help`、各子命令的 `--help` 和 `python -B deploy/activate_shopping_schedule_release.py --help` 查看。构建入口提供 `prepare`、`verify`、`build`、`validate`、`assemble`；激活入口接受固定候选目录和显式计划 SHA。执行环境限制仍由既有控制器检查，不得使用 `python -O` 绕过。

## 数据保全与失败处理

表数量保持家庭库 69、平台库 9；采购截止日期和优先级写入现有 JSON 字段。无 DDL、全库回填或独立迁移步骤，也不会自动补写真实采购日期或用户云端清单。

新控制器仅替换固定 `ReleaseSpec`，继承上一版的生命周期：停止旧服务、完整停机备份、安装候选、正常启动 app、核对完整数据组逻辑保全，再启动 sync/media 等后台服务。数据读写边界仍由 `assistant_trip_items_release_data` 管理；其 attempt kind 沿用 `assistant-trip-items-release-attempt`，不能因为新入口名称而改成另一种协议。

`stage` 只准备独立候选并记录 69→69 / 9→9；激活目录前缀为 `shopping-schedule-69-`。备份或启动后核验失败时保留原件和停止状态，不自动 restore，不重复消费同一 activation。上线后再由独立审计核对固定包、运行文件、服务健康、TLS 静态资源及实际数据保全回执。真实云服务和实体电视仍需分别确认。

## 本地定向测试

`tests/test_shopping_schedule_release.py` 用独立临时 Git、合成导出与记录式 runner 覆盖固定文件边界、前端证据复用、旧 profile 兼容、离线计划及 69/9 失败顺序。99 个保留文件使用实际源码字节；旧 104 文件哈希合同由已核实父包中的五项哈希与其余 99 项组成，不修改生产校验常量，不依赖源码的 Git 历史；该单项是哈希合同验证，不是旧包重放。Windows 使用新的短临时目录，避免长路径影响；测试不连接 SSH、Docker 或真实账号，不导入业务 app，不访问生产数据库。

作者本地 R2 为 47/47（本批 42 项、旧 profile 相邻 5 项），0 跳过；其中一个兼容测试随后移除对 Git 历史的依赖，R3 单项 1/1。其余测试、fixture 和三个发布实现文件均未变化。R1 因短临时目录的父目录不存在而出现 47 项 setup 错误，尚未进入测试；失败原件保留。上述结果不计为真实 Linux 或生产验证。
