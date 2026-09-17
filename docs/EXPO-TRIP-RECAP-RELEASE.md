# 旅行回顾发布适配器（58→58 候选）

本适配器仅在本地生成九份未绑定工具。旅行回顾已完成独立临时浏览器验收；此文档不表示已发布，也不代替最终源码冻结、工具审查或服务器阶段。

## 固定父版本与范围

- 父原件目录：私有 `finance-accounts-tools-20260917-r1`，九份 SHA 固定在 `prepare.py`。
- 已安装账户包 archive：`146e8e3553e8b4fcf00363a396414ee8f3da021f5fb68ecc588cbfee69dad74e`。
- 父 manifest：`16aa062f50fb203a5b6a1da4150824613a6989f517cccf3aac65ee81a931a763`。
- 父 app／sync／media 镜像：`sha256:6974cdb6cc98869d8cdc55927c7a1be05d941aaef76382645b1fbd8dfe422ad7`。
- 仍使用 `finance_accounts58`。38 个根后端、Dockerfile、依赖、部署与 schema helper 必须保持原字节；没有新表或账户迁移。
- 只读回顾界面和入口使用现有旅程／地点／媒体 API；不增加共享、云写入或电视播放范围。

独立分支从受验回顾源 `6453339dcc6fb8d3d60b1a21953c02b2ca205f74` 开始，明确合入已审批量读取工具 `3e40e3264521e8010aff21e7af0f7f41d8afab59`，依赖基线为 `1efcd5f7f7bb4928eddb6f68737f82938c7ebc81`。新增适配器只有 `prepare.py`、专项测试和本文档三文件。

## 保全与阶段边界

激活仍先停止整组写入者、获取完整家庭／注册库快照并验证逐库备份，再安装来源。用真实 `verify_current` 验证安装前后 58 表结构，要求两份完整快照相同；账户、估值与操作回执允许非空，所有行、BLOB、序列及注册库都必须保持。新 app 启动后的快照再次与安装前相同。生成脚本不能调用 `migrate`、`verify_addition` 或旧 55 表基线检查。

post 独立核对 `before.json`／`after-app.json`／`preservation.json` 与激活报告，再在只读容器中复核完整 58 表保全。父版备份检查、正常 TLS、静态资源、TV 入口、37 个唯一匿名路径精确 401、四服务状态和环境保全守卫保持。post 的新在线备份仍是逐库快照，`liveGroupSnapshotRechecked=false`，不是全局原子快照。

不自动恢复或重放阶段。恢复需另行选择完整 58 表组备份，沿现有 `snapshot-current`／`check-restored` 语义检查；本工具不执行 restore。

## 本地生成接口

```text
python -B -X utf8 deploy/expo_trip_recap_release/prepare.py --source-root <私有 A> --output <A/expo-trip-recap-tools-新后缀> [--freeze <已审 JSON>]
```

输出目录必须不存在且直接位于私有根下。输入九份原件在生成前后校验固定 SHA；freeze 拒绝重复键、非法路径、缺项或旧父身份。缺少 freeze 时测试数为 null；有 freeze 时保留最终 collection 的精确模块／数量，不猜测 Linux 通过数。生成报告始终 `bound:false`，不会创建绑定或执行包、网络、Docker、备份与服务器阶段。

采用已审 `deploy.packager_batch_read.transform_prepare`，在核固定父脚本 SHA 后显式转换。批量 Git 读取仍绑定完整 commit，禁用 replacement refs；调用方 clean／HEAD／祖先／输入 SHA／完整选择集合、工作文件以及写前后独立检查保留。详见 [批量读取说明](PACKAGER-BATCH-READ.md)。没有跨检查缓存。

## 验证与最终冻结

八个 Linux 模块只涉及静态托管、家庭隔离、备份、58 表迁移／恢复兼容、旅程、地点、媒体及本适配器。完整列表是 `REQUIRED_TESTS`；最终数量由实际 collection 给出。需私有父脚本的批量工具测试不进入服务器业务选择。

本地专项实际 21/21 通过：真实临时 Flask／SQLite 创建账户及 0／null 估值、历史回执，再验证完整快照；实际账户行、估值、回执、旧审计行、序列和 schema 漂移都被拒绝。固定父原件 CLI 在禁止网络／生成工具子进程的边界内执行真实生成与纯守卫检查，核对 38 后端／Docker 不变、189 个完整构建输入、37 匿名接口、896 MiB 内存／640 MiB tmpfs、七入口未绑定拒绝，以及配置和选择集合负例。

```text
python -B -X utf8 -m pytest -q tests/test_expo_trip_recap_release.py
python -B -X utf8 tests/test_expo_trip_recap_release.py --source-root <私有 A> --git-repo <固定源码目录> --git-revision <完整 commit> [--freeze <JSON>] [--build-evidence <JSON>]
```

私有证据保存在作者树 `test-results/recap-release-r1`；不提交原件或真实数据。最终整合源码应分别列明已审工具／测试新增、发布后文档及 `docs/contract-inventory.json` 的精确 SHA 差异；构建输入与已受验前端／运行后端必须逐字节相同，不能以文件数量相等替代来源核验。未执行本批实际打包、绑定、服务器验收或部署；真实云、个人资料与实体设备仍不属于本地测试结论。
