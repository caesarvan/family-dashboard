# 本地日程隐私：发布适配

这是独立发布候选，不是上线回执。功能源码、构建、实际浏览器、Linux 验证、具体计划审查和生产执行分别留证；本轮工具开发不执行生产、SSH、Docker、云或模型调用。

## 固定父版与运行范围

父版为已安装的日程重叠界面：source `ffb0b3cf46b6a4cf35b005d84879763b825cd822`，tree `7bf8c1ea54018713ab6a67e676af3ebd7a1911f3`。固定 package `dfbcd03256962168ae19a27f993902cf91c0d64f2d1ff5c5f43962038c219491`，manifest `f359222a790ed60b494bfcb0e555716a800b96b1b54f497f12c57c9d48b5fc52`，父镜像 `sha256:d11e94b576cc1b9497c85d1c43782b6b62fe5df4bd20d32f3337524c96edd73d`。新计划必须包含父版实际只读审计 SHA `bf4e31d64f9ea6332ac17f4239fed468a5019cbcfb8c92fd3ba4a6b70629b46b`。

固定 profile 为 `calendar-conflicts-r1-calendar-privacy`。对照父版包与 Git 差异，本批非 Expo 运行文件共 **107** 个：更新 `app.py`、`home_assistant.py`、`data_portability.py`，新增 `calendar_privacy.py`；其余 **103** 个文件逐字节保留。保全映射 SHA 为 `4f6e79df28819373843d710b818e038992e0a281aa6ebae2c342f820adba0eaa`。不能通过重写 metadata 的 changed 列表豁免第五个模块，也不能沿用旧前端专用的“106 全部不变”判断。

Docker 唯一变化是在既有 `calendar_publish.py` COPY 行添加 `calendar_privacy.py`；前后 SHA 分别为 `7fca420d3f86a35742385f7b39719c6d5ebf6c9d08c0e764333ae15ebb46763f` 与 `511cc2a0b14439278630a905db8782ab601c62c3b52ca27926192ab9577a7f19`。依赖、Compose、Nginx、环境及成员标记保持。新增前端测试显式入包，浏览器 scripts 只保留已列名的前置事项、提醒、日程重叠及日程隐私四条工具；没有目录通配扩权。正式构建的全部前端输入及导出 hash 仍须绑定，不能用旧导出覆盖变更后的界面。

## 71/9 全库保全

直接继承已审 source-update 生命周期，使用上一版严格 71/9 数据 profile 与完整快照读取器，只增加本批独立 attempt 类型。schema 是 **71→71 / 9→9**；不执行提醒 69→71 迁移、DDL、旧日程回填或 worker tick，不豁免 settings、序列、旧事件、私人数据、非空提醒状态与回执。

顺序为停定时器及全部写服务 → 全户全库备份 → 安装源码与导出 → 仅启动 app 核对 → 停 app → 比较全部 schema/行/序列/注册库 → 启动全部服务并核对权限与健康 → 恢复定时器。app-only 保全失败时保留停止状态与失败证据，禁止自动迁移重跑或自动恢复。备份验证和实际生产恢复是不同事实。

## 操作与验证

`deploy/build_calendar_privacy_release.py` 提供 `prepare / verify / build / validate / assemble`，参数沿用上一版。`deploy/activate_calendar_privacy_release.py` 提供 `stage / activate`；要求具体候选路径、计划 SHA、既有 Linux/root/共享锁与单次消费约束。38 个 operator 文件逐个绑定；本入口不凭文档推断新的包、镜像或计划身份，也不使用本地测试代替具体计划审批。候选完成服务检查后继续验证提醒匿名 GET 为 401；这不构成真实账户写入验收。

`tests/test_calendar_privacy_release.py` 只测必要打包策略、旧 profile 隔离、输入复用、operator/父审计、记录式生命周期及失败不重放。真实临时 SQLite 用例初始化两户三库，在旧共享／新私人日程、提醒状态、回执、settings 已有数据时完整备份、实际 app 重启并验证全组逻辑完全相同；任一户提醒、回执、settings、事件、注册库漂移及旧 69 表均拒绝。未重复产品后端、npm、浏览器或生产测试。实际测试分轮与原件由作者交付报告记录。
