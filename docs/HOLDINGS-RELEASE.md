# Expo 持仓：54→55 发布操作准备

本页对应 [holdings_release/prepare.py](../deploy/holdings_release/prepare.py)。这是发布操作生成器，**尚未构建、迁移或部署**。它复用已审查的财务发布代码，仅生成本地新目录；最终版本、构建、组合测试及非作者审查未冻结时，生成的服务器入口必须拒绝执行。

## 复用范围

生成器要求维护者提供源码外的私人访问目录，读取其中以下旧操作原件。每份原件必须与代码 `PINNED` 中 SHA-256 一致；任何缺失或字节变化都拒绝，不通过改名或寻找相似脚本替代。

- `expo-finance-release-20260917-r2/` 中七份已审操作：ops_common、expo_contract、build、validate、stage、activate、post_readback。
- `expo-finance-post-r3-20260917/post_readback_r3.py`：整份复用其最后通过的新备份读回流程，替代原 post_readback。
- `prepare-expo-finance-package.py` 和 `bind-expo-finance-release-r2.py`：复用从 Git 对象和 Expo 产物取包、完整源文件差异、归档读回及独立算子散列绑定。

这些私人原件没有被复制进仓库。生成器用固定散列、唯一赋值位置和精确片段替换输出新操作，不执行其中的生产代码。冻结参数校验只调用已核验原 packager 的定义代码及路径元数据校验，不启动打包、Git、网络或数据库。

本轮固定的旧版本身份如下；它们来自集成人核对，生成器不会自行连接服务器确认：

| 项目 | 绑定值 |
|---|---|
| 旧 manifest | `f5a49949e6d868533392f64fa46c4042a85df635b2f8123b3f05076a7d619976` |
| 旧 app/sync/media | `sha256:4433d1d5c97ec4ed4a1336c2402b0fae121a04e092050ff9eb2821ac61fa4798` |
| 原 web | `sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7` |
| 原配置摘要 | `a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07` |
| 新迁移 profile | `investment_operations55` |
| 新 DDL 来源 | `investment_operations.INVESTMENT_OPERATIONS_SCHEMA_SQL` |

旧运行源码为 integration `2d08258…`／main `a208105…`；后续 `2adfe068…` 等纯文档提交不替代旧安装 manifest。未来线上基线变化后必须重新审查适配器，不能重放本次固定旧身份的操作。

## 精确变化

1. 原 53→54 更换为 54→55，绑定 [check_investment_operation_migration.py](../deploy/check_investment_operation_migration.py) 的单表 DDL 和源文件散列。保留停写、全部家庭及平台注册库完整备份、原始数据/schema/序列比较、逐户原子迁移和新 app 启动后再次全组比较。
2. Dockerfile 只允许在既有 `COPY calendar_publish.py financial_files.py investment_import.py ./` 中增加 `investment_operations.py`。父镜像、安装依赖、USER、其余行均须字节不变；实际镜像继续从核验的旧镜像追加限定的 Expo 清理和完整运行文件 COPY，不执行 pip。
3. Linux 测试始终导入 `/app` 的真实镜像模块。两个嵌套迁移 helper（旧 54 与新 55）先核对 `/test-support` 来源和运行模块散列，然后仅将各自 ROOT 指向已核验的 `/app`；测试前后完整检查模块、源文件、schema 与所有运行散列。测试不改 helper 断言，不跳过迁移验证。
4. 新增 `/app/investments` 入口核对，以及三个持仓 GET 的匿名 401 检查。
5. post_readback 整体继承 r3：明确启动一次新 backup service invocation，通过本次 journal 回执和新增 manifest 唯一匹配，检查完整注册表映射及所有关闭的备份数据库。`immutable=1` 仅用于备份目录的无侧车关闭快照；**不用于 live WAL**。报告仍明确 `liveGroupSnapshotRechecked:false`，逐库在线备份不宣称跨库全局事务。

## 生成未绑定模板

在已审查源码的独立工作树运行。以下路径与目录名是示例；输出目录必须尚不存在，且直接位于指定私人访问目录下，名称符合 `expo-holdings-tools-[a-z0-9-]+`。

```powershell
python -B -X utf8 deploy/holdings_release/prepare.py `
  --source-root C:/PRIVATE/family-dashboard-access `
  --output C:/PRIVATE/family-dashboard-access/expo-holdings-tools-review1
```

输出包括 `operators/` 七份脚本、`prepare-package.py`、`bind-release.py` 和 `generation.json`。报告 `bound:false`、`finalFreezeProvided:false`；模板的测试数量为 null、选择为空，且不生成 `operator-bindings.json`。即使有人写入 `{bound:true}`，仍被“没有最终冻结”检查拒绝。模板用于审阅差异，不作为可部署版本。

已有目录绝不覆盖，原失败候选和日志保留。生成器在落盘前重新核对全部原件，使用独占创建并逐文件读回；不修改仓库、原操作目录、旧包或原配置。

## 最终冻结与独立审查

在所有功能分支、组合测试和非作者审查通过后，由集成人准备完整 freeze JSON，并在另一个新的输出目录重新生成：

```powershell
python -B -X utf8 deploy/holdings_release/prepare.py `
  --source-root C:/PRIVATE/family-dashboard-access `
  --output C:/PRIVATE/family-dashboard-access/expo-holdings-tools-final1 `
  --freeze C:/PRIVATE/family-dashboard-access/holdings-final-freeze.json
```

freeze 沿用已审 packager 完整字段：`schemaVersion/main/integration/tree`，最终与浏览器实际测试的 build evidence 路径和 SHA，导出目录，旧 archive 路径及 SHA，旧 manifest／镜像／配置摘要，迁移 SQL SHA，完整 `changedFiles/addedFiles/removedFiles`，`validationTests/expectedTestCount`。不得以工作中提交冒充最终 main；最终构建必须与实际浏览器验证的所有输入及导出字节相同。路径、摘要、源文件差异或最终 Git 状态不符时，实际 packager 拒绝。

`expectedTestCount` 来源于最终指定模块的实际组合执行，不能将重叠运行相加。必须含新操作、文件导入、finance_hub、新迁移、新导出和 frontend_runtime 测试；其余受影响模块及本适配器的测试由集成人纳入最终选择。Linux 仍实际运行全部选中用例，唯一可接受的跳过是：

```text
classname=tests.test_frontend_runtime
name=test_windows_junction_rejected
message=Windows junction semantics
```

原 JUnit 用例数、唯一用例、失败、错误、精确跳过身份与实际 passed 数共同检查。没有 deselect；报告显示 `N-1 passed / 1 skipped`，不能写成 N passed。

最终重新生成后仍为 `bound:false`，还需另一位 agent 审查生成后的九份脚本及精确差异。审查通过后，集成人运行本地 `prepare-package.py --freeze ...` 建包，再用 `bind-release.py --operator-review ... --operator-review-sha256 ...` 绑定已审七份服务器算子。review JSON 必须恰含 `operatorDirectory/operatorHashes`；绑定器再次核对全部冻结输入、Git、源码、归档和原件，只创建一次包内 `operator-bindings.json`。

## 实际执行顺序及证据

完成上述本地审查后，集成人再核对服务器当前身份，并向报告指定的全新 serverCandidate 目录传入已审七份算子、归档、metadata、build evidence 和绑定文件。此文没有执行上传或提供替代 SSH 授权。

服务器按 `python -B build.py` → `validate.py` → `stage.py` 顺序产生实际证据；Linux 失败不进入 stage，stage 的 `baselineCheckPending:true` 不能写成生产基线已验证。审查实际 build/validation/READY 后才运行 `activate.py`。激活的失败保留状态，不盲目重放、重新初始化或自动恢复。成功后使用已审 `post_readback.py --reviewed-sha256 <该文件实际SHA>` 完成 HTTPS、新静态资源、匿名权限、服务及新备份读回。

发布身份、停写备份、单表迁移、新 app 启动数据核对、服务恢复和最后读回分别保留原始报告。新用户云操作、本人真实账单和实体电视不会由这些发布检查自动变成已验收。

## 本地验证

```powershell
python -B -X utf8 -m pytest tests/test_holdings_release.py -q
python -B -X utf8 -m tests.test_holdings_release `
  --source-root C:/PRIVATE/family-dashboard-access `
  --report test-results/holdings-local-operator-guards.json
```

第一条为 21 项可独立运行的合成 guard 测试，无私人原件依赖、无额外平台跳过。第二条另行使用实际固定原件，在临时目录生成九份真实脚本，逐一调用五个服务器入口，确认缺绑定时均在外部操作前拒绝，并验证未冻结模板拒绝伪造绑定；所有 subprocess 和网络调用均被硬阻止。它还用合成 XML 核对实际 JUnit 解析器的精确跳过、唯一用例和计数规则，并验证实际 r3 函数拒绝旧 invocation、非新增 manifest 和失败的备份服务。两者分开报告，不把合成 guard 或入口拒绝当成实际 build、Linux、迁移、备份或生产部署成功。
