# 旅行、地点与云日历：55→55 发布候选适配器

这是仅生成本地文件的候选工具，尚未绑定、上传或执行。当前已安装身份仍为 main `6b2bb55758fce0df02f51252d5eac2441b7c9869`／source `e0c1c6b03e14424bc170d1aa7d7c28529b381801`；实际发布记录见 [旅行协作验收](EXPO-TRAVEL-ACCEPTANCE.md#expo-travel-release)，当前产品状态见 [README](../README.md)。不能重放历史候选或迁移命令。

`deploy/trip_coordination_release/prepare.py` 读取私有 `expo-travel-tools-20260917-r1` 的九个固定 SHA 文件，生成全新的 `trip-coordination-tools-*` 目录。它复用 [此前旅行发布适配器](TRAVEL-RELEASE.md) 的纯契约、停写备份、55 表保全与读回机制，不另写一套发布流程。

## 固定输入与变更范围

- 当前 parent：`sha256:b394b59bc8e13f60d597f01e87e887c90358be81b073a928f6430d6a5b5b576f`；manifest：`4534b837252ec4cb31d7bc0ad074cfff53f1b0901117cbbfd234c6d570378e9c`；archive：`6b652f275cfebcb67f1dc382734218ef7a095d198734064f9329c0dad27e284c`。env 与 web 镜像保持原约束。
- 只更新候选目录、发布名称、以上旧版本身份、最终测试名单／计数与本轮源码完整性约束。三个文件 `expo_contract.py`、`stage.py`、`validate.py` 保持字节一致；`activate.py`、`post_readback.py` 仅替换发布名称。
- 必须包含修改后的 `calendar_publish.py`、`journey_places.py`、`TripsScreen.tsx`、`MapScreen.tsx`，以及新增的日历／地点面板、helper、会话／来源版本专项与本工具。最终 freeze 的完整 changed／added／removed 清单仍由独立审查确定，并与实际旧 archive、Git blobs 和完整新 manifest 核对。
- Docker 全文件字节不变；13 个既有 schema、依赖和备份文件保持与已安装 manifest 相同。生成程序递归检查内嵌 Python，拒绝迁移／建库调用及非只读 SQL。`migration` 绑定字段仅保留为既有 55 表定义指纹，没有生产迁移。

## 生成与绑定边界

集成人在独立审查通过后，用 `python -B deploy/trip_coordination_release/prepare.py` 的 `--source-root`、`--output` 和最终 `--freeze` 参数生成私有候选。路径必须绝对、无链接，输出为私有根目录内不存在的 `trip-coordination-tools-*` 直接子目录；旧目录不覆盖。缺少 freeze 时，只能生成测试计数为空的不可执行模板。

最终 freeze 沿用此前字段格式，绑定已审 main／integration／tree、实际构建及浏览器受验构建证据、完整源码差异、导出目录、旧 archive 和测试选择。生成的 packager 与 binder 自身也拒绝缺少必需模块／测试的 freeze，不能通过跳过生成阶段绕过校验。保留旧 11 模块，再加入日历发布、实际会话复核、地点来源 revision、地点 API 和本工具共 5 模块；最终数量必须由实际收集和运行核实，本文不预填。

九个生成文件仍需独立固定字节审查。既有 binder 只接受明确审查的七算子 SHA，并创建新 `operator-bindings.json`；不绑定则服务器入口拒绝。此工具不执行 packager、binder、Docker、SSH、数据库或服务器命令。post 仍要求显式提供独立审查的 `--reviewed-sha256`，不提供可重放旧候选的生产命令。

## 数据保全与验收边界

原执行顺序保持：停 web、备份 timer 和全部数据写入服务，核对当前 55 表／注册库，完整组备份并验证，安装源码前比较快照，先启动 app 再比较全部行、schema、序列及注册库，成功后启动 worker／web／timer。允许持仓回执非空，原回执必须保持。READY 中的 `productionWrites=0` 只属于先前只读阶段，激活报告不会继承它。

post 仍核对本次激活证明和新一次 backup service invocation，校验完整逐库在线备份；不是跨库全局原子快照，不能冒称再次核对 live 全组快照。生产数据保持、备份、TLS 和真实云日历行为须等待本轮实际发布／本人操作；生成成功不证明这些结果。

## 实际本地验证

作者使用独立临时目录执行 `python -B -X utf8 -m pytest tests/test_trip_coordination_release.py -q -p no:cacheprovider`：**13 项通过**。测试覆盖输入篡改、路径与体积限制、重复 JSON、输出排他性、输入变动、未绑定模板和递归 DDL 拒绝。

另以该测试文件的显式 CLI，读取九个真实固定原件、旧 archive 和基线 `f48c02dc51b6610a1f2af20a3b8dbc44286efda7` 的 Git Docker blob；临时生成九文件，实际执行生成的配置校验器，逐项拒绝旧 parent／manifest／archive、缺少任何必需测试或源码、Python 镜像中的 TS 桥接测试。七个执行入口在阻断所有 process／network 调用的情况下均因缺少绑定／freeze 而拒绝。三个算子完全不变、两个算子仅名称变化、递归语法检查及全字节 Docker 对比通过。

原件位于 ignored `test-results/trip-coordination-release-r1.xml` 和 `trip-coordination-operators-r1.json`。复用的 55 表非空回执／备份恢复测试继续作为强制选择；本轮未重复运行其旧用例，不把源码未变当作新一次测试通过。最终组合、Linux、浏览器与生产验证由集成人单独记录。
