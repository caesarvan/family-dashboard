# 旅行 JSON 导入发布适配器

这是候选发布工具，生成不等于上线。入口为 `python -B deploy/expo_trip_import_release/prepare.py --source-root <私有access目录> --output <其中不存在的expo-trip-import-tools-*目录> [--freeze <最终冻结配置>]`。不得复用旧发布目录。

输入为已发布照片旅行建议的九个私有工具原件；每个原件的 SHA 固定在 [适配器](../deploy/expo_trip_import_release/prepare.py)。当前父镜像为 `sha256:4235322eb02f02d1533e479194331c324aa095850fe08d1540e02088342a1104`，父归档 `a14d695ed265b7ee136a0275042ef62d124179db5a0697e4457cdce69376230f`，父 manifest `da2a4cb1f44debec1e2c458b2f92a80de6b813842af04ba28cdb303333a21eb4`。实际发布前仍须比对线上身份。

仅允许已由非作者审查的 `journey_workflows.py` 会话修复字节，SHA `ed2e81503361dd4ab25a13956c7c307e872cf5b2c820131e57400ca178475295`；另外 37 个后端模块保持父版本。`household_media.py` 恢复为不可变输入，并保留上一版源码固定校验。打包端与服务器端均复核旅行源码 SHA。前端导入、接线与验收文件必须列入最终冻结配置。

沿用 finance_accounts58，58 表至 58 表，无 DDL、初始化或迁移。原有构建、停写备份、隔离验证、环境保护、静态资产及逐数据库校验机制不变。仅 app 有健康探针；不能把其他服务的空 health 状态称为健康检查通过。在线逐数据库备份不能描述为跨全部数据库的原子快照。

最终配置必须包含适配器列出的 12 个 pytest 模块，并由实际 collection 得出计数；目前未填写最终冻结配置或宣称其全过。生成结果保持 unbound，需另由非作者审查实际生成的文件和私有编排脚本，再绑定最终源码、构建、验收原件及配置。缺少绑定时所有五个生产阶段入口必须拒绝运行。

本分支实际验证：8 个 pytest 通过；针对九个真实父工具的本地检查通过，122 项保护输入篡改均被拒绝，五个未绑定入口均被拒绝。该检查阻止所有子进程与网络，使用临时 synthetic freeze 的 `9991` 仅验证配置机械流程，不是实际测试计数。原件保留在本工作树 `test-results/trip-import-release-r1/`。未打包、绑定、连接或部署服务器。

参见 [旅行导入计划](EXPO-TRIP-IMPORT-PLAN.md)、[部署](DEPLOYMENT.md)、[Git 工作流](GIT-WORKFLOW.md)。
