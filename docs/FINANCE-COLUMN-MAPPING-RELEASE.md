# 财务列映射发布适配器

本适配器从家庭成员版本九份固定工具派生，生成阶段只准备未绑定工具。本批随后已于北京时间 2026-09-18 06:56:39 激活，06:57:18 正常 TLS 读回通过；实际安装身份与独立审计状态见[集中验收记录](FINANCE-COLUMN-MAPPING-ACCEPTANCE.md)。固定父 pins 和算子不能在新版本重放。

## 固定父版本与范围

- 父工具目录：`household-members-tools-20260918-r1`，九份原件逐字节 SHA 固定在适配器中。
- 父 archive：`57cee29157d0ab96f500e760506139cef47d88fa90875409916cda4fab20e276`。
- 父 manifest：`af59bbbe1fd637930ae8c7878392e4a688f651a83f4061f015ec26cbce7b3fad`。
- 父 app/sync/media 镜像：`sha256:5fa4c5d0b89e2a5ebce3f72c1691b3f4238f665a01c7419aff19a7aae2df98cc`。
- 必需变化为 `finance_hub.py`、`FinanceImportPanel.tsx`、`financeImport.ts`；必需新增为两份 API 专项、浏览器脚本和本适配器／测试。`financial_files.py` 保持父字节。
- 38 个其他根级后端、Docker、app、成员模块和已部署迁移 helper 等 61 个唯一路径保持字节不变（保留父 tuple 中的重复保护，共 62 条）。API 已按独立审查通过的 `8c835bf` 固定 `finance_hub.py` SHA `093fb1cd54adb4cce7e486b44834800ec018be01cd7b668fc51ceb33f21d3091`；缺失或不合法时在创建输出目录前拒绝生成。

## 58 → 58，保留现有角色

使用 `household_members58` 当前结构检查器，包含已有 `users.household_role`。本批 `schemaChange=false`，没有 DDL、迁移或角色初始化操作。

激活时先停止写入并留完整家庭库／平台库备份，验证完整指纹、users 原列投影与备份不可变读取；源文件安装前再次比较快照。启动后必须与启动前的完整 58 表／全部角色值／schema／sequence／registry 快照完全相等。因此已调整成普通成员的角色不能被重置成管理员。

post 绑定 `before.json`、`after-app.json`、`preservation.json`，在实际镜像中只读复核当前结构与精确保全。父版 `inspect_backup_group`、只读容器参数和备份文件白名单完整保留；新在线备份允许正常业务继续变化，只核当前结构与自身完整指纹，不能称为跨库全组原子快照。

保留验证容器 896m 内存与 640 MiB `/tmp` 约束、加载模块／源文件／构建输入／导出证据绑定、每次重新 inspect、未知阶段不重放和原 38 个唯一匿名 URL 严格 401（父程序实际请求 39 次，其中一个重复）。validate 程序与父版字节相同。

## 验证与待验

`tests/test_finance_column_mapping_release.py` 使用临时真实 Flask／SQLite 验证非空账户、0／null 估值、回执、普通成员角色和 app 重启保全；实际数据／角色／schema／sequence／registry 漂移均拒绝。其他专项核查来源 SHA、精确 Docker、输出排他性、输入竞态、坏 freeze 与递归禁止 DDL／迁移。

私有 CLI 读取真实九原件、父包及指定完整 Git commit，临时生成后禁止所有生成工具的进程和网络调用，验证来源／白名单／构建输入、真实生成 guard、38 唯一匿名拒绝以及七入口的未绑定或无效配置拒绝。只留下 JSON 和生成差异证据，不打包应用、不绑定、不连接服务器。

本地专项两轮均实际 21/21，第二轮原件在本工作树 `test-results/mapping-release-r2/`，XML SHA `f94d1fab7e78aa1087a84861f78fe7dc25851d555700e9f9ebb86b14d3bf09be`。专项运行时 API pin 尚未填写；后来只补已审精确 pin，并通过下述真实源码 CLI 校验。两轮数量不相加。

真实父九工具 CLI 已在固定组合 `c958c1b2da6f4a79cbc828653d6d86afdfab76da` 上执行通过：196 个构建输入均被真实 selector 包含，38 个后端与父包一致，124 次来源漂移、27 个坏 freeze、两本地入口无效参数和五阶段未绑定均拒绝，38 唯一匿名地址仍要求 401。该 CLI 执行时组合只缺随后另行审查合入的本 adapter/test 两文件；当时没有最终 freeze、应用打包或生产操作。CLI 原件保留于 `test-results/mapping-release-cli-r1/`，最终报告命名澄清后的固定原件另存 `test-results/mapping-release-cli-r2/`。

最终 CLI `stdout.json` SHA `5db8d983973137772a3fad523c0b6b3d9df6f2538d6effe9953d5b3b0398dd08`，`result.json` SHA `f6fba73b7f584569fb34af43b9817510f147a36df6e105f966c027c97f47bf8c`，完整生成差异 SHA `0c404acc7f9a786b017f479b50ec8636cb46860963dae2de084bc86692cd650c`。前后 adapter/test SHA 均相等，全部本地轮次无失败；临时 freeze 中的 9991 只是校验合成输入，绝非实际测试计数。

固定组合 `c9ef18f402198a4b31a0c5d86510f4d4d06d7474` 实际收集 15 模块／497 个唯一项目；随后发布容器实际执行为 496 通过、1 项精确 Windows junction 跳过、零失败／错误／deselected。原件集中于验收页，不与本地专项相加。

本地 CLI 用法（需要已审 API pin 和固定组合源码，证据目录必须新建且为空）：

```powershell
python -B -X utf8 tests/test_finance_column_mapping_release.py --source-root <private-access> --git-repo <fixed-candidate> --git-revision <40-character-commit> --evidence-dir <empty-private-directory>
```

本批不扩展真实本人财务、云、实体电视或通用家庭成员管理的验收范围。
