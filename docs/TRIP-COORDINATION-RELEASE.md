# 旅行、地点与云日历：55→55 发布记录与适配器

本轮 r2 已于 2026-09-17 09:25:21（北京时间）实际激活，09:25:52 正常 TLS 读回通过。运行 main `f7126dd59348eecfc749534953423d1df45dea14`／source `5d8a0c4d5e96a209ad80e6dddd80a086969f31d9`，534 源文件／113 运行文件，55→55 不迁移；完整身份和原件见 [本轮发布验收](EXPO-TRIP-COORDINATION-ACCEPTANCE.md#expo-trip-coordination-release)，入口见 [README](../README.md)。r1 的 Linux 因 tmpfs 用满失败，未 stage 或激活；r2 544 通过＋1 个精确 Windows 跳过后独立复核并发布。不能重放本轮固定算子或历史迁移。

以下固定输入是本次发布使用的旧基线和生成器约束，**不是下一次发布可直接复用的当前身份**。此前 main `6b2bb55758fce0df02f51252d5eac2441b7c9869`／source `e0c1c6b03e14424bc170d1aa7d7c28529b381801` 的历史记录见 [07:38 旅行协作发布](EXPO-TRAVEL-ACCEPTANCE.md#expo-travel-release)。

`deploy/trip_coordination_release/prepare.py` 读取私有 `expo-travel-tools-20260917-r1` 的九个固定 SHA 文件，生成全新的 `trip-coordination-tools-*` 目录。它复用 [此前旅行发布适配器](TRAVEL-RELEASE.md) 的纯契约、停写备份、55 表保全与读回机制，不另写一套发布流程。

## 固定输入与变更范围

- 本轮使用的 parent：`sha256:b394b59bc8e13f60d597f01e87e887c90358be81b073a928f6430d6a5b5b576f`；旧 manifest：`4534b837252ec4cb31d7bc0ad074cfff53f1b0901117cbbfd234c6d570378e9c`；旧 archive：`6b652f275cfebcb67f1dc382734218ef7a095d198734064f9329c0dad27e284c`。env 与 web 镜像保持原约束。
- 只更新候选目录、发布名称、以上旧版本身份、最终测试名单／计数与本轮源码完整性约束。三个文件 `expo_contract.py`、`stage.py`、`validate.py` 保持字节一致；`activate.py`、`post_readback.py` 仅替换发布名称。
- 必须包含修改后的 `calendar_publish.py`、`journey_places.py`、`TripsScreen.tsx`、`MapScreen.tsx`，以及新增的日历／地点面板、helper、会话／来源版本专项与本工具。最终 freeze 的完整 changed／added／removed 清单仍由独立审查确定，并与实际旧 archive、Git blobs 和完整新 manifest 核对。
- Docker 全文件字节不变；13 个既有 schema、依赖和备份文件保持与已安装 manifest 相同。生成程序递归检查内嵌 Python，拒绝迁移／建库调用及非只读 SQL。`migration` 绑定字段仅保留为既有 55 表定义指纹，没有生产迁移。

## 生成与绑定边界

集成人在独立审查通过后，用 `python -B deploy/trip_coordination_release/prepare.py` 的 `--source-root`、`--output` 和最终 `--freeze` 参数生成私有候选。路径必须绝对、无链接，输出为私有根目录内不存在的 `trip-coordination-tools-*` 直接子目录；旧目录不覆盖。缺少 freeze 时，只能生成测试计数为空的不可执行模板。

最终 freeze 沿用此前字段格式，绑定已审 main／integration／tree、实际构建及浏览器受验构建证据、完整源码差异、导出目录、旧 archive 和测试选择。生成的 packager 与 binder 自身也拒绝缺少必需模块／测试的 freeze，不能通过跳过生成阶段绕过校验。保留旧 11 模块，再加入日历发布、实际会话复核、地点来源 revision、地点 API 和本工具共 5 模块；最终数量必须由实际收集和运行核实，本文不预填。

九个生成文件仍需独立固定字节审查。既有 binder 只接受明确审查的七算子 SHA，并创建新 `operator-bindings.json`；不绑定则服务器入口拒绝。此工具不执行 packager、binder、Docker、SSH、数据库或服务器命令。post 仍要求显式提供独立审查的 `--reviewed-sha256`，不提供可重放旧候选的生产命令。

**本轮资源修订只在私有 r2 算子中。** 当前 Git 生成器仍沿用内存 512 MiB／tmpfs 256 MiB 默认值；首轮验证空间不足后，集成人把 r2 私有 `validate.py` 的两值改为 768 MiB／512 MiB，经独立复审和重新绑定后运行。包、业务源码、前端、测试和镜像保持同字节；不是生成器自动产生新资源配置。以后重新生成必须核对实际资源需求并重新审查，不能重放本轮 r1／r2 固定算子。

## 数据保全与验收边界

原执行顺序保持：停 web、备份 timer 和全部数据写入服务，核对当前 55 表／注册库，完整组备份并验证，安装源码前比较快照，先启动 app 再比较全部行、schema、序列及注册库，成功后启动 worker／web／timer。允许持仓回执非空，原回执必须保持。READY 中的 `productionWrites=0` 只属于先前只读阶段，激活报告不会继承它。

post 核对本次激活证明和新一次 backup service invocation，校验完整逐库在线备份；不是跨库全局原子快照，不能冒称再次核对 live 全组快照。本轮实际 1 户两库、原 55 表和注册库保全、备份、TLS 已通过，证据见顶部链接；真实云日历行为仍须本人操作。生成成功本身不证明这些结果。

## 实际本地验证

作者使用独立临时目录执行 `python -B -X utf8 -m pytest tests/test_trip_coordination_release.py -q -p no:cacheprovider`：**13 项通过**。测试覆盖输入篡改、路径与体积限制、重复 JSON、输出排他性、输入变动、未绑定模板和递归 DDL 拒绝。

另以该测试文件的显式 CLI，读取九个真实固定原件、旧 archive 和基线 `f48c02dc51b6610a1f2af20a3b8dbc44286efda7` 的 Git Docker blob；临时生成九文件，实际执行生成的配置校验器，逐项拒绝旧 parent／manifest／archive、缺少任何必需测试或源码、Python 镜像中的 TS 桥接测试。七个执行入口在阻断所有 process／network 调用的情况下均因缺少绑定／freeze 而拒绝。三个算子完全不变、两个算子仅名称变化、递归语法检查及全字节 Docker 对比通过。

工具专项原件位于 ignored `test-results/trip-coordination-release-r1.xml` 和 `trip-coordination-operators-r1.json`。适配器作者阶段未重复旧的 55 表非空回执／备份恢复用例；之后集成人在新镜像实际执行固定 545 项集合，结果、重叠范围及首轮失败另见顶部发布验收，不把专项与总集合相加。生产当次持仓回执为 0 行，不能冒称生产非空回执验证。
