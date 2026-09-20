# 日程冲突界面的前端发布适配

本适配仅准备新的 Expo 界面发布。代码合并、正式打包、Linux 镜像及浏览器验收、阶段计划审查和生产执行分别留存证据；本文件及本地测试不表示已经发布。

## 固定父版与范围

- 父版 source：`77150610f4fa2eae1edaaadb94198e9f3093f3c5`，tree：`fa940fcb63d8ca6fe470e674539fd74492cae602`。
- 父版 package：`67720847156174e624e8a5d648f83126e3f7db23fa5dc5839a04225359ab0590`，manifest：`0690076adebf7e8c2204ecde005444ee1aa3489eb888fd08c9fd9053e7e3c727`。
- 父镜像：`sha256:a99d11dec43be931f36496368e0565f9dfc87492fcd391dfbff92d2a61470f0e`。
- 已完成的父版生产只读审计：`313e15072070f499f286c817d20227378309ec1a6129feb8e985d597f88e30f8`。新计划必须包含该原件的精确哈希。
- 固定 profile：`task-reminders-r1-expo-calendar-conflicts`。全部 **106 个非 Expo 运行文件**（52 个根 Python 文件、53 个旧静态资源、requirements）统一映射 SHA256 为 `ea4c3158b6cc40fc85994814d705d7d902db25858a2054e9760f1958b2d2a6db`，不存在后端变更豁免。

Docker、依赖、Compose、Nginx、环境与成员标记沿用父版。前端输入必须包含 `calendarConflicts.test.mjs` 以及原有测试；浏览器工具仅增加明确的 `scripts/check_expo_calendar_conflicts_browser.py`。未列名 scripts 不进入包。生成的 Expo 文件由正式构建原件逐一绑定，不能作为 Git 源码混入。文档或发布脚本变化可以复用字节相同的前端构建；任何前端输入变化必须重新构建。

## 71/9 数据保全

`activate_expo_calendar_conflicts_release.Controller` 直接继承既有 source-update Controller 的 `stage`、`activate` 与 `_activate`，不继承提醒迁移流程。新数据适配仅将现有 `DataSpec` 接到提醒版严格的 `snapshot_current` / `verify_restore`，验证每个家庭 **71 表**及平台 **9 表**。

执行次序沿用共享生命周期：停止备份定时器及全部写入服务 → 全家庭、全数据库完整备份 → 安装新源与前端 → 仅启动 app 并核对镜像/运行文件 → 停止 app → 完整逻辑保全比较 → 恢复 app、sync、media、web → 服务、匿名权限与健康检查 → 恢复备份定时器。schema 为 **71→71 / 9→9**，不调用 69→71 迁移，不修改数据表，不豁免 settings、提醒状态、操作回执或序列。

薄 `current_services` 覆写保留父方法返回的原 dict：父镜像预检不发新请求；只有候选镜像最终四服务检查后，额外验证提醒列表和操作回执的匿名 GET 均为 401。非 401 进入原有异常清理，停止候选写入服务，保留已消费阶段证据，不自动重放或恢复旧备份。匿名 GET 不是认证写入或真实账户验收。

## 操作入口与证据

固定入口 `deploy/build_expo_calendar_conflicts_release.py` 提供 `prepare`、`verify`、`build`、`validate`、`assemble`，参数与既有发布入口一致。先绑定审核后的组合 commit、构建原件 SHA 和新独占输出目录；`assemble` 再绑定实际 build、validation、review 索引 SHA，输出新的计划。35 个 operator 文件均入计划精确映射。

`deploy/activate_expo_calendar_conflicts_release.py` 提供 `stage`、`activate`，每一步都要求实际 candidate 及计划 SHA，Linux root、字节码/优化限制及共享发布锁保持原约束。须先审查具体计划，再分别单次执行，不能从本文猜测新镜像、候选目录或计划哈希。失败目录和回执必须保留。

## 本地验证边界

专项 `tests/test_expo_calendar_conflicts_release.py` 覆盖固定包范围、旧 profile 隔离、构建输入复用、计划/operator/父审计约束、记录式阶段顺序及失败不重放。记录式生命周期不会调用 Docker。合成 SQLite 用例通过真实 Flask 初始化两个家庭三个数据库，在提醒状态、操作回执和 settings 均非空时做完整备份、真实 app 重启及停止后的检查，并拒绝旧 69 表、任何状态/回执/settings/私有资料/平台漂移或缺失备份。

这些测试不代替实际 Linux、真实界面、用户云账户、实体电视或生产验收。本适配开发不会运行这些阶段，也不会重新运行提醒后端 82 项、npm、模型或线上操作。最终发布需另行绑定实际组合与验证原件。
