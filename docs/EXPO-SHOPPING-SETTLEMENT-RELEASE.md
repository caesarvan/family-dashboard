# Expo 采购实付：发布适配器

本批已于 **2026-09-18 08:03:15（北京时间）激活，08:04:16 正常 TLS 读回通过**。Linux 实际 168 通过、1 项精确 Windows 跳过，零失败／错误；58→58 原数据与角色保全。独立只读发布审计通过；[集中验收记录](EXPO-SHOPPING-SETTLEMENT-ACCEPTANCE.md#expo-shopping-settlement-release)统一记录实际包、安装身份与阶段证据。父版本为已上线的[财务列映射](FINANCE-COLUMN-MAPPING-ACCEPTANCE.md#finance-column-mapping-release)，不是待执行的旧成员迁移。下述本地专项和 CLI 限制均保留为作者阶段历史。

[prepare.py](../deploy/expo_shopping_settlement_release/prepare.py) 只从维护者私有 `finance-column-mapping-tools-20260918-r1/` 的九份固定 SHA 原件生成七算子、包准备器及绑定器。父 archive 为 `3ff158acd53ec13b411f55d7b810e386e16c41c38ea65c07ccc0470846f31631`，manifest 为 `32590f6186738d9de32064fd3e80de80de259c77f96981080c0583eb7525e0c9`，app／worker 镜像为 `sha256:039f7c7f4a601273bfbffa22ea9ca9494d8de2045240bf43244d41668469ada6`。父版本北京时间 2026-09-18 06:56:39 激活，06:57:18 post、06:59:53 fresh 读回通过。

## 允许变化及保护

- 唯一可变后端为 `shopping_settlement.py`，固定非作者已审 API `1f569df9a98a1482559f31e2888d93c41dae3031` 的 SHA `90543ed9a2cbb41136a36d27da1558922fbf144030a50a689300ec15fd3e2067`。缺失／畸形摘要在创建输出前拒绝；common 和包检查器均核实际清单摘要。
- `finance_hub.py` 加回不可变集合且固定 `093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091`。app、其他后端、Docker、依赖、角色迁移检查器和原构建输入白名单保持。Docker 检查器、stage 和 validate 三文件直接保留父字节。
- 必需修改为结算后端及四个前端入口文件 ListScreen／FinanceScreen／HouseholdApp／types；必需新增为结算组件、模型、Node 测试、会话专项、浏览器脚本及本适配器与测试。具体路径以常量为准；仅受审文档可随最终明确增量加入。
- `household_members58` 当前结构，58→58、`schemaChange=false`；完整停写组备份、当前角色值及全部表的行／schema／sequence、registry、配置与权限保全。新 app 启动后完整 snapshot 必须等于启动前；不运行 `migrate`／`init_schema`，不重新初始化两位管理员。
- 原资源限制、运行源码、静态资源／经典回退、正常 TLS、独占输出、防重放、独立审查与绑定守卫保持。post 原 38 条唯一匿名 GET 全部保留，仅新增 `/api/finance-hub/shopping-settlements/context`，要求 39 条全部 401；不以匿名 POST 探测写操作。
- post 仍要求实际新一次逐库在线备份、完整备份指纹／不可变路径及角色结构核对；它不是跨库全组原子快照。恢复边界和故障保留沿用父算子，不自动回退或重放未知发布尝试。

## 有界验证

Linux 必需八模块为原结算、结算会话、旅行采购、成员迁移、家庭隔离、平台备份、前端运行及本适配器。最终测试数量只能来自固定组合的实际 collection，并在服务器验证精确节点与唯一 Windows junction 例外；此文不填写猜测数量。Node 专项不进入 Python 镜像执行。

本地 `test-results/shopping-release-r1/` 实际 8/8 发布保护专项通过，2.21 秒；随后只为私有 CLI 增加父函数逐字节比较，最终测试文件在 `shopping-release-r2/` 实际 8/8 再过，2.27 秒，零失败／错误／跳过。最终 XML SHA `c0a20ca176c4a7319b8ac0107e2cbae158293a6913d76c059fa6a8594a2e8c3e`，record SHA `06bc9c87b7561426d57c22d5def7edf2301e4d2b16e510b079f3360dcadfbc2f`；两轮分别保留、不相加。覆盖缺 pin、源文件改动／越界／大小、Docker 差异、排他生成、非法 freeze、拒绝迁移 SQL，以及真实临时 SQLite 已填资产／普通角色的备份、重启和漂移拒绝。没有运行应用业务套件。

真实父九原件 CLI 已在固定组合 `95f3e87b5b201a0695cd15dfdb0684dfec334384`／tree `b1ac9c9601cd4667cab8e47d8040e9cf0de726eb` 上完成一轮，仅在临时目录生成未绑定程序。父归档、七个受审源 pin 与其余不可变源码均符合；124 个源码漂移、24 个非法 freeze、两个本地非法入口和五个未绑定 phase 入口均被拒绝。55 个未改变的父函数逐字节相同；匿名列表为 39 唯一路径（父列表原有一项重复，因此循环共 40 项）。派生程序的子进程／网络调用被禁止，没有创建 package 或 binding。

实际 build evidence SHA `3a5b1ea424c1ed8b439c0665389e10235fa341455ea2d0a64a68f59609c76588`，原 build head `8c15b68a3ff45c6495f44f2565087fd77f716cb5` 是该组合祖先；198 个构建输入与组合 Git blobs 相同，23 个实际导出重新核对散列。selector 包含全部输入与原三个特殊本地构建源，额外私密／生成路径被排除。此固定组合尚缺本适配器及测试两个必需文件，报告明确记为 pending，不能称最终完整发行已验。

CLI 原件 `test-results/shopping-release-pinned-r1/record.json` SHA `de764d88cba2ef1b369360558cbf8735b15ec7a8df5740399df5e35dff56981f`；stdout SHA `5087854e3340ea2636e60f0355b327d431fecfff0aed5da3c5f0384d2ebdfaad`，stderr 为空；`generated/generated-delta.patch` SHA `1b9ae9cf06346f7ce7d0dc11eb533385df8d2acb9dbb1013f16e91f2b4f4c0cc`。只有 synthetic freeze 使用测试计数 9991，绝不是实际 collection；运行前后作者源与组合 HEAD／clean 保持。

实际打包、独立七算子审查、绑定、上传及每个服务端阶段均由集成人另行执行；生成成功不代表这些阶段已经通过。临时数据和原始 stdout／stderr／XML／报告不进入仓库。
