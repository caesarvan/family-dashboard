# 手动资产账户：55→58 发布候选

本适配器仅生成本地、未绑定、待独立审查的九份发布工具。
当前未进行账户生产迁移或部署；源码提交和本地检查不代表已上线。
父版本为已激活的来源导入 R2，独立发布审计由集成人另行记录。

## 固定来源与范围

- 父原件：私有 `expo-finance-source-tools-20260917-r2` 的七算子、packager 和 binder，九份实际 SHA 固定在适配器中。
- 父 archive：`93426c1c8feac4c8f8c8f2626c74637ed9d1ba6fb884da276cbab49393fce5f5`。
- 父 manifest：`f11d9d58971fa9bcf91ac2a53f19ad23c426fbd833f9f6b1a575c0dfb4e1f7c0`。
- 父 app/sync/media image：`sha256:6b886eb5123916673d8c9ac38810390cb7ec6b46db5941c651602835769cab68`。
- web 镜像、环境散列、依赖、资源限制及来源报告／持仓／其他业务实现沿用父守卫。

[prepare.py](../deploy/finance_accounts_release/prepare.py) 仅允许新输出目录
`finance-accounts-tools-*`，且必须直接位于私有 access 根下；拒绝符号链接、junction、
已有输出、来源字节漂移、重复 JSON 字段和非法路径。未绑定算子拒绝所有五阶段入口。
最终冻结必须提供实际完整 changed/added/removed 清单、正式 Git 身份、受验 export、
构建输入及独立收集的测试数量；不预填本轮 Linux 成功数。

Dockerfile 只允许在既有 COPY 行新增 `finance_accounts.py`，其他字节必须一致。
明确允许 app 注册、个人导出、发布白名单和账户前端接线改变；35 个已有根后端保持。
继续完整收录三个既有本地构建来源，不重复新增或把它们当作镜像运行模块。

## 迁移与恢复边界

使用 [55→58 检查器](FINANCE-ACCOUNTS-MIGRATION.md) 的 `finance_accounts58` profile，
绑定账户模块源 SHA、SQL SHA 和新 schema；不在算子内复制 DDL。
Linux 测试的三个 schema helper 分别绑定真实 `/app` 中的 `finance_hub`、
`investment_operations` 和 `finance_accounts`，测试前后检查来源与 schema 不变。

激活依次停止 web、备份定时器及全部数据卷写入者，保留旧源码／配置／镜像，
读取完整 55 表及注册库快照，创建并验证完整组备份并另存副本。
只有上述核对通过后，调用一次显式迁移，仅新增三张空表；原 55 表的行、schema、
列、外键、自增序列及注册库必须保持。保存迁移结果和迁移后快照，再安装源码启动 app；
app 启动后完整快照必须与迁移后完全相同，并再次核对原表及空表增量，之后才启动 worker/web。

中断或失败保留全部证据，不自动重放、继续服务或恢复数据库；恢复是另行明确操作。
post 再核验迁移前／迁移后／app 后证据及真实增量，检查运行文件、正常 TLS、静态资源、
私有生成资源拒绝与电视入口。保留父 34 个匿名路径，并新增账户列表、估值历史、
原操作查询，共 37 个唯一路径，均须精确返回 401。
post 新备份仍是逐库 online backup，不能称为全组原子快照。

## 本地检查

[测试](../tests/test_finance_accounts_release.py) 的普通 pytest 使用纯临时夹具，覆盖
来源／输出／freeze 拒绝、受控 Docker 增量及迁移调用边界。
另有显式 CLI 读取实际九父原件和真实固定 Git 树：

```text
python -B -m pytest tests/test_finance_accounts_release.py -q
python -B tests/test_finance_accounts_release.py --source-root <私有access> --git-repo <账户组合repo> --git-revision <完整固定commit>
```

CLI 在临时目录生成工具并检查实际选择器、schema/绑定、迁移顺序和原件散列；
模拟 HTTP 状态只用于执行生成的匿名拒绝循环，不代替产品验收。
生成工具检查期间禁止网络和子进程，七入口只验证拒绝未绑定／缺少输入，不执行发布。
`--build-evidence`／`--freeze` 可在最终组合后补充完整受验输入校验。

作者最终本地专项实际 **23 passed／0.38 秒**；固定九原件 CLI 检查退出 0。
在账户候选 `dfd7695eb6e725db70245d18d570289001a9e213` 核得 187 个完整构建输入，
35 个已有根后端与父包同字节；本适配器及测试两文件仍待进入集成源。
原件位于本 worktree 的 `test-results/accounts-release-final/`，两份执行源前后散列一致。
JUnit SHA `599d9f3fccacf5cd162f58cdeeb0a503d9ed700bac9e1db8cf510e372d2c6f0d`；
CLI stdout SHA `921af4ccd165246ef02b46d8172f6cb9dc41dac674b65bb2b3a9befe0319ba18`。
未提供最终构建证据或 freeze，不能把这次源选择器检查当作最终包验证。
待验事项仍包括最终组合收集、
浏览器、真实 Linux 镜像及服务器迁移／启动／读回；本人实际财务和实体电视未验。
