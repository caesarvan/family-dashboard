# AI 已有旅行改期：66/9 → 66/9 发布合同

本批是待组合验证的源码更新工具，尚未发布。真实界面、模型、正式构建、Linux 镜像与演练的结果由集成人分别记录，本文件不预先认定通过。业务合同见[改期 API](ASSISTANT-TRIP-CHANGE-API.md)、[意图识别](ASSISTANT-TRIP-INTENT.md)。

## 固定生产起点与允许变化

新 profile 为 `finance-analysis-r1-assistant-trip-change`；只接受已经上线的本人账户分析版本，不接受更早 61/9 基线，也不执行 61→66 迁移。

| 身份 | 固定值 |
|---|---|
| 已安装 source | `f25357f935d64774922efa68d42a2ba41bb18037` |
| 已安装 tree | `1efb6a439fd8fdd95a1af5c4958296452ccfcb71` |
| 父镜像 | `sha256:21625d6e2d9768ba48cca35100bb8bf02c1c4146afa6b7ad25b9b72cb559c1d2` |
| 已安装 manifest | `30d5fe729ab9c407c43d8de3fa0129acd9c1e8ec2aa3e9473c5fb5e2485cb5f4` |
| 已安装 package | `eebaec9fdf903591ce86844ff16912a0a79e050c662404afa4f9e907328a5e66` |
| 独立生产只读审计 | `2c1afe7d812e026477033bfc6e01bb3d4939ff8d3ef940759dfcfcbb4ebf948b` |
| 原 `.env` SHA-256 | `a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07` |
| 原成功成员 marker | `d223842c531e115b21430e860ffa8e742b1fbf0616942a228d04009e66dedb93` |
| Dockerfile 前／后 SHA-256 | `b1668b82416b3afa86ed8dc138fd6183204faeb6b0f89871381f9fb633d86116` ／ `5856bdc2ef145f133084c879d92714f9aaa48301b6af5c941abaab64ef6895bd` |
| 表数 | 每户 66→66；平台 9→9 |

生产基线审计于 2026-09-19 16:20:57（北京时间）完成，实际一户两库。原件保存在私有 `family-dashboard-access/finance-analysis-production-readonly-review-r1.json` 和 `finance-analysis-production-originals-r1/`，不提交数据库或环境值。旧审计用于固定安装身份，下一次发布必须重新获取停写后的当前数据，不把旧行摘要当作新发布基线，也不要求五张分析表仍为空。

根运行文件只允许 `app.py` 接线、新增 `assistant_trip_intent.py` 与 `assistant_trip_change_api.py`；Dockerfile 只允许在 `home_assistant.py` 所在 COPY 行后追加这两模块的一行 COPY。`README.md`、前端、生成 Expo、文档、测试和发布工具沿用原框架的明确目录范围。原分析、FX、账户及其它根运行模块不得改变或删除；requirements、Compose、Nginx、依赖锁和运行配置保持。新 profile 在公共 packager 中显式接入，历史分支及固定常量不改。

## 打包、构建与组装入口

使用独立干净 Git 提交及实际构建证据，输出必须是全新目录。入口为：

```text
python -B deploy/assistant_trip_change_release_package.py prepare --repo <clean-checkout> --commit <head> --export-dir <expo-export> --build-evidence <build-evidence.json> --evidence-sha256 <sha> --output-dir <new-package>
python -B deploy/assistant_trip_change_release_package.py verify --output-dir <package> --package-sha256 <sha>
python -B deploy/assistant_trip_change_release_package.py build --package-dir <package> --package-sha256 <sha> --output-dir <new-build>
python -B deploy/assistant_trip_change_release_package.py validate --package-dir <package> --package-sha256 <sha> --image-id <immutable-image> --selection <selection.json> --selection-sha256 <sha> --output-dir <new-validation>
python -B deploy/assistant_trip_change_release_plan.py --package-dir <package> --package-sha256 <sha> --build-dir <build> --build-sha256 <sha> --validation-dir <validation> --validation-sha256 <sha> --reviews <review-files.json> --reviews-sha256 <sha> --candidate <new-candidate>
```

沿用 `membership-expo-build` 原件、全部 Git 前端输入和逐导出散列绑定；Windows 长路径使用同一产物的扩展路径，不删资源或放宽校验。新旧四份 `.mjs` 测试输入均纳入白名单。输出文件数有界，必须包含 index、metadata 和唯一 Expo entry；不硬编码未来构建文件数。build 仍基于固定父镜像仅新增清理和完整 runtime 两层，校验配置不变；validate 仍使用精确 selection、JUnit 及加载模块／runtime 散列。组装复用已有 review 文件集合，不新增审批类型。

## 激活、保全与恢复

Linux 集成人按原审查流程使用 `assistant_trip_change_release_controller.py stage <candidate> <plan-sha>` 和 `activate <candidate> <plan-sha>`。CLI 仍限定 Linux root、`-B`、非 optimize、固定候选父目录及没有 ambient Docker／Compose selector；共用已有独占发布锁。

stage 核对父镜像、原 manifest、源码范围、候选 runtime、审查与测试证据、配置及成功成员 marker，不打开活动数据库。activate 复核 stage 中的服务与旧源码身份，然后依序：

1. 保留旧源码、Expo、配置和镜像，分别绑定 app／sync／media 原环境键值。
2. 停止备份 timer、web 及全部写入服务，核对退出状态和卷无其它写者。
3. 对当前完整 66/9 库组生成停写快照及 `backup.py` 原格式备份；逐库核对路径、散列、内容与平台注册家庭集合，将完整组保留到发布 proof。
4. 安装源码并启动真实新 app，检查健康、运行字节和原环境，再停止 app。
5. 比较完整 before／after 逻辑摘要；66 张户内表、平台九表的所有行、列、schema、序列、版本和成功成员 marker 必须保持。五张已安装分析表可非空，其已有数据同样逐项保全。
6. 核对通过后才启动 app／sync／media／web，检查正常 TLS health、运行字节与各服务环境，恢复备份 timer。

数据工具不加载 app、不运行迁移或 warm callback、不增加表、不清空新旧记录。新应用的正常启动初始化接受上述全组核对。`attempt.json` 在首次备份前独占创建；阶段失败保留原件，不能自动重试、回滚或重新激活。候选启动后的失败沿用原停止检查，无法证明停止时不会声称停止成功。

66/9 数据 profile 复用 `finance_analysis_release_data.snapshot_current`；恢复完成后的全组和 marker 比较复用 `finance_analysis_release_data.verify_restore`。恢复须匹配完整组及配套源码／镜像／配置，比较通过后按原[会话恢复规则](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)处理。旧 61/9 检查器与 61→66 迁移不能用作本批恢复；不得仅改旧表数绕过断言。

## 作者验证范围

聚焦工具检查使用临时 Git／归档、命令记录替身和真实合成 SQLite。合成当前基线直接由固定资产 source 创建双户三库，五张分析表预先有数据；覆盖真实候选 app 启动后的全组保持、整组恢复、旧行／分析行／schema／序列／marker 漂移、缺失备份、原件绑定及失败后不能重放。

Windows 作者检查分轮取得 63 个不同用例的通过结果：首轮两模块 60/60（148.82 秒）；补充旧默认 packager 回归 1 项通过；两项 WAL 边界修正夹具后 2/2（9.42 秒）通过。首轮补充检查的两项失败保留在 `test-results/assistant-trip-change-release-boundaries-r1.xml`：夹具把平台注册库也强制为 WAL，原备份注册库的只读枚举留下 sidecar，被原严格读取器拒绝。正向夹具恢复保留平台注册库 DELETE、仅户库 WAL，非空 WAL 反例仍须拒绝；没有修改或放宽原 `backup.py`／读取器。

首轮原件为 `test-results/assistant-trip-change-release-r1.xml`，WAL 补充为 `test-results/assistant-trip-change-release-wal-r2.xml`。这些是分轮结果，未声称最终提交再次执行一次全套 63 项。该作者阶段不执行 Docker、SSH 或生产操作；不能把命令替身说成 Linux 演练，不能把工具通过替代真实 UI、模型、云日历或本人场景 A 验收。
