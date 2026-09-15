# Git 与多 agent 协作

每个开发任务使用独立分支和独立 worktree。代码先提交，由另一位 agent 只读审查明确的 base/head；审查通过后，由集成人合入 `codex/integration`。组合测试和再次审查通过后，集成人才将已审查的提交合入 `main`。Git 合并不代表已经部署，也不授予生产操作权限。

## 1. 当前仓库与分支职责

本文建立时的稳定基线为 `ad667bf2b744d707db080964c662249c7cd8b056`。主仓库在 `C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard`，其 `.git` 是本项目的常规仓库目录，不再借用父 `AI` 仓库。后续任务使用集成人当次确认的提交，不永久固定在本文基线。

当前只有本地 Git 仓库，没有 remote、线上 PR 或平台强制分支保护。下列要求是协作协议，不宣称已由 hook、CI 或托管平台自动阻止违规操作。

| 分支／目录 | 负责人 | 用途与边界 |
|---|---|---|
| `main`／主仓库 | 集成人 | 稳定源码。禁止直接编辑或直接提交业务修改；仅接收审查通过的集成提交。部署仍另走发布流程。 |
| `codex/integration`／独立集成 worktree | 唯一集成人 | 按依赖顺序合入已审查分支，解决组合问题、运行组合验收；不能当作所有 agent 的公共工作目录。 |
| `codex/<agent>-<task>`／每任务独立 worktree | 本任务作者 | 仅编辑授权路径，提交实现、测试和配套文档。公共接口变更先约定。 |
| 指定提交的 detached worktree | 独立审查者 | 只读检查已提交代码；不替作者修改、不更新功能分支。按审查任务运行适用测试，使用独立临时数据；不执行生产操作。 |

worktree 建议放在 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/`。worktree 内的 `.git` 通常是指向主仓库管理目录的文件，这是正常状态。所有 worktree 共享提交对象和 refs，但各自有工作文件、索引及当前分支。

同一个物理工作目录只能由一位 agent 操作 Git。禁止跨 worktree 写文件、替另一位作者暂存／提交，或把不同 worktree 的目录内容相互覆盖。创建 worktree、维护集成分支和变更仓库配置由集成人协调；不要并行执行共享 refs 的维护操作。文件责任人仍需明确，独立 worktree 不能消除接口冲突。

禁止无授权的强推、`reset --hard`、清理、重写历史或删除分支／worktree；不要使用 `git add .` 或 `git add -A` 将无关内容一并提交。不要对父 `AI` 仓库执行本项目的暂存、重置或清理命令。

### 已保存但尚未审查合并的旅行资料代码

本项目目前保留以下尚未合入的候选分支：

- `codex/journey-documents-api`
- `codex/journey-documents-portability`
- `codex/journey-documents-ui`
- `codex/journey-documents-wiring`

这些 refs 保存了工作成果，不能据此认定功能已合入 `main`、已上线或已完成独立审查。分支之间存在模块注册、导出、UI 加载等依赖；单个分支的模块依赖可能不完整，不能直接当作完整应用运行。后续须核对每个实际 head、授权文件、依赖顺序及审查结果，再组合验收；不能重复套用旧候选目录或假设四个分支已经相互包含。

## 2. 创建任务 worktree

以下 PowerShell 示例由集成人在创建任务时执行。路径和任务名是示例，先替换为本轮约定值。已有分支或目录不得覆盖；应先检查其归属和状态。每个代码块都须检查命令退出码，不能把失败后继续执行当成成功。

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard'
$worktrees = 'C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees'
$taskBranch = 'codex/example-small-task'
$taskTree = Join-Path $worktrees 'example-small-task'
$approvedBase = '<集成人确认的完整40位base提交>'

function Invoke-CheckedGit {
    param([string[]]$GitArgs)
    $result = & git @GitArgs
    if ($LASTEXITCODE -ne 0) { throw ('Git 命令失败：' + ($GitArgs -join ' ')) }
    return $result
}

if ($approvedBase -notmatch '^[0-9a-f]{40}$') { throw '请填写真实批准的 base' }
$root = Invoke-CheckedGit -GitArgs @('-C', $repo, 'rev-parse', '--show-toplevel')
if ([IO.Path]::GetFullPath($root) -ne [IO.Path]::GetFullPath($repo)) { throw '仓库根目录不符' }
$branch = Invoke-CheckedGit -GitArgs @('-C', $repo, 'branch', '--show-current')
if ($branch -ne 'main') { throw '主仓当前不是 main' }
$dirty = Invoke-CheckedGit -GitArgs @('-C', $repo, 'status', '--porcelain=v1', '--untracked-files=all')
if ($dirty) { throw '主仓不干净，请先交由其负责人处理' }
$head = Invoke-CheckedGit -GitArgs @('-C', $repo, 'rev-parse', 'HEAD')
if ($head -ne $approvedBase) { throw 'main 已变化，需重新确认 base' }
Invoke-CheckedGit -GitArgs @('-C', $repo, 'worktree', 'list', '--porcelain')
Invoke-CheckedGit -GitArgs @('check-ref-format', '--branch', $taskBranch)
$exists = Invoke-CheckedGit -GitArgs @('-C', $repo, 'branch', '--list', $taskBranch)
if ($exists -or (Test-Path -LiteralPath $taskTree)) { throw '分支或目录已存在，不能覆盖' }
Invoke-CheckedGit -GitArgs @('-C', $repo, 'worktree', 'add', '-b', $taskBranch, $taskTree, $approvedBase)
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'status', '--short', '--branch')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'rev-parse', 'HEAD')
```

任务作者开始前，在自己的 worktree 重新核对 `git rev-parse --show-toplevel`、`git branch --show-current`、`git rev-parse HEAD` 和 `git status --short`，应与任务记录一致。发现非本人修改时停止操作，不自动 stash、还原或清理。测试生成物、虚拟环境等即使被 ignore，也不因此成为可以随意删除的目录。

后续示例沿用本节的 `Invoke-CheckedGit` 函数；若换了 PowerShell 会话，先重新定义函数。命令里的占位符必须替换为真实提交或授权路径，不能直接复制占位符运行。

## 3. 作者提交与交付

先约定接口与依赖，再在授权文件内实现。测试使用本任务的临时数据库、端口和虚构 fixture；参照 [开发说明](DEVELOPMENT.md) 和模块契约。不要复制生产 `.env`、密钥、数据库、真实财务输入或文件资料。不得拿旧 `live_check.py` 代替隔离测试。

需要另一个分支的代码才能测试时，先向集成人登记依赖的完整 head。集成人可安排专门组合 worktree；作者不得自行把另一个未审查分支混入自己的交付。若批准任务以一个非 `main` 依赖提交为 base，应在任务记录和审查范围中明确列出，不能把该任务通过当成其全部依赖也已审查通过。

```powershell
# 仅在自己的任务 worktree 执行。将示例路径替换为实际授权清单。
$taskTree = 'C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/example-small-task'
$allowedFiles = @('docs/EXAMPLE.md')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'status', '--short')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--check')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--stat')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--')
# 人工核对工作树和已有暂存区；存在非本任务暂存项时停止，不能一并提交。
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--cached', '--name-only')
Invoke-CheckedGit -GitArgs (@('-C', $taskTree, 'add', '--') + $allowedFiles)
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--cached', '--check')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'diff', '--cached', '--')
# 只有暂存区内容、授权路径与测试记录均核对通过后，才执行下一行。
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'commit', '-m', 'docs: describe example workflow')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'rev-parse', 'HEAD')
Invoke-CheckedGit -GitArgs @('-C', $taskTree, 'status', '--short', '--branch')
```

交付完整 base/head、分支、worktree、改变的文件、接口与数据迁移说明、实际测试命令／退出码／计数／日志和未验证项。保留文件 SHA-256、source manifest、镜像和报告散列；提交号补充源码身份，不替代发布和测试证据。提交后冻结 head；审查期间新增提交必须通知审查者，原通过结论不自动覆盖新 head。

## 4. 独立审查绑定 base/head

审查者不是本次实现作者。先核对 base 是 head 的祖先、路径在授权范围内，并读取完整 diff；不要只看作者摘要或浮动分支名。审查记录必须写明完整 base/head、审查者、实际检查内容、发现及未覆盖范围。

```powershell
$reviewRepo = 'C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard'
$reviewBase = '<任务记录中的完整40位base>'
$reviewHead = '<作者已冻结的完整40位head>'
if ($reviewBase -notmatch '^[0-9a-f]{40}$' -or $reviewHead -notmatch '^[0-9a-f]{40}$') { throw '填写实际提交' }
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'cat-file', '-e', ($reviewBase + '^{commit}'))
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'cat-file', '-e', ($reviewHead + '^{commit}'))
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'merge-base', '--is-ancestor', $reviewBase, $reviewHead)
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'diff', '--check', $reviewBase, $reviewHead)
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'diff', '--name-status', $reviewBase, $reviewHead)
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'diff', '--stat', $reviewBase, $reviewHead)
Invoke-CheckedGit -GitArgs @('-C', $reviewRepo, 'diff', '--no-ext-diff', $reviewBase, $reviewHead, '--')
```

以上只读 Git 对象，不进入或修改作者 worktree。需要完整文件树时，由集成人为审查者创建不存在的新目录，例如 `git worktree add --detach <review目录> <reviewHead>`，创建后核对 HEAD；审查者仅在自己的目录工作，禁止切换作者的分支。发现问题回报作者，作者修订并提交后重新绑定 head。通过结论不能用“已经 merge 过”或“之前测试过”代替。

## 5. 集成与合入 main

只有集成人可执行本节。先确认每个功能分支的审查通过记录、依赖顺序、完整提交以及干净开局；把待合入提交固定为 SHA，不直接合入可能移动的分支名。集成 worktree 必须由同一位集成人独占。

`codex/integration` 分支已存在；首次为其分配 worktree 时，先运行 `git worktree list --porcelain`。未被检出且目标目录不存在时才执行 `git worktree add <集成目录> codex/integration`。不要重复创建、强制检出同一分支或 reset 现有集成分支。若它不是已约定的集成 base，先审查已有提交并重新安排本轮集成，不自动覆盖。

```powershell
$integrationTree = 'C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/integration'
$expectedIntegrationHead = '<集成开始前确认的完整40位head>'
$approvedFeatureHead = '<另一agent已经审查通过的完整40位head>'
if ($expectedIntegrationHead -notmatch '^[0-9a-f]{40}$' -or $approvedFeatureHead -notmatch '^[0-9a-f]{40}$') { throw '填写实际提交' }
$branch = Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'branch', '--show-current')
if ($branch -ne 'codex/integration') { throw '不是集成分支' }
$dirty = Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'status', '--porcelain=v1', '--untracked-files=all')
if ($dirty) { throw '集成目录不干净' }
$actual = Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'rev-parse', 'HEAD')
if ($actual -ne $expectedIntegrationHead) { throw '集成分支已变化，先重新核对' }
# 在执行前确认：本目录没有未完成的 merge/rebase/cherry-pick，且依赖已按顺序审查合入。
Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'status')
Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'merge', '--no-ff', '--no-edit', $approvedFeatureHead)
Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'rev-parse', 'HEAD')
Invoke-CheckedGit -GitArgs @('-C', $integrationTree, 'status', '--short')
```

发生冲突时停止后续测试和合并。不要使用 `--ours`／`--theirs` 整体吞掉另一方改动；冲突解决属于新代码，应由相关作者核对并再次审查。只有确认**本次命令**产生了合并冲突、合并前确实干净、`MERGE_HEAD` 对应本次批准的提交且未混入其他工作时，才可在这个集成目录执行 `git merge --abort`。其它错误或不明状态先检查和协调，不能把 abort 当作通用清理。

所有依赖合入后，冻结集成 head，运行约定的组合测试。检查接口注册、依赖、Docker／发布白名单、脚本加载、schema／迁移、权限与跨模块返回链；测试失败不能推进 `main`。修正必须作为独立可审查提交，随后重新核验受影响测试。另一位 agent 对 `main` 基线到最终集成 head 的完整结果再次审查，并记录具体 head、测试证据及未验证边界。

```powershell
# 仅在组合测试和再次审查通过后，由集成人在主仓独占执行。
$repo = 'C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard'
$approvedMainBase = '<组合测试和再次审查所绑定的main完整40位提交>'
$approvedIntegrationHead = '<组合测试和再次审查通过的完整40位提交>'
if ($approvedMainBase -notmatch '^[0-9a-f]{40}$' -or $approvedIntegrationHead -notmatch '^[0-9a-f]{40}$') { throw '填写实际提交' }
$branch = Invoke-CheckedGit -GitArgs @('-C', $repo, 'branch', '--show-current')
if ($branch -ne 'main') { throw '不是 main' }
$dirty = Invoke-CheckedGit -GitArgs @('-C', $repo, 'status', '--porcelain=v1', '--untracked-files=all')
if ($dirty) { throw 'main 工作树不干净' }
$actual = Invoke-CheckedGit -GitArgs @('-C', $repo, 'rev-parse', 'HEAD')
if ($actual -ne $approvedMainBase) { throw 'main 已变化，需重新集成测试和审查' }
Invoke-CheckedGit -GitArgs @('-C', $repo, 'merge-base', '--is-ancestor', $approvedMainBase, $approvedIntegrationHead)
Invoke-CheckedGit -GitArgs @('-C', $repo, 'merge', '--no-ff', '--no-edit', $approvedIntegrationHead)
# main 合并提交的文件树应与通过组合验收的集成提交完全一致。
Invoke-CheckedGit -GitArgs @('-C', $repo, 'diff', '--exit-code', $approvedIntegrationHead, 'HEAD', '--')
Invoke-CheckedGit -GitArgs @('-C', $repo, 'rev-parse', 'HEAD')
Invoke-CheckedGit -GitArgs @('-C', $repo, 'status', '--short', '--branch')
```

仅从确认的祖先 main 合入已审查集成 head，不应产生内容冲突；如果出现异常，停止发布并查明原因，不自动 reset 或改写 main。最终 main merge commit 与集成 head 不同，但上面的文件树比较应相同。发布记录同时绑定最终 main commit、已测集成 commit、相同源码树和实际构建产物。

## 6. 给其他 agent 传递完整历史

共享本机仓库的 agent 直接使用集成人分配的 worktree。需要把仓库交给另一台机器或独立环境时，可以创建 Git bundle。它包含所选 refs 的可达历史，**不是脱敏工具**；先检查全部分支和历史没有真实 secret、`.env`、数据库、财务输入、资料 BLOB 或私人测试产物。`.gitignore` 不会清除已经提交的内容。发现敏感历史先停止交付并单独处理，不能擅自重写历史。

在所有作者确认已提交并短暂停止 refs 更新的交付窗口，由集成人执行；输出文件必须是不存在的新文件，并放在源码目录之外：

```powershell
$repo = 'C:/Users/caesarf/OneDrive - NVIDIA Corporation/Documents/AI/family-dashboard'
$bundle = 'C:/Users/caesarf/Documents/Codex/family-dashboard-access/family-dashboard-reviewed.bundle'
if (Test-Path -LiteralPath $bundle) { throw 'bundle 已存在，换新文件名保留旧证据' }
Invoke-CheckedGit -GitArgs @('-C', $repo, 'for-each-ref', '--format=%(refname) %(objectname)')
# 完成内容与历史审查后，才创建包括功能分支在内的 bundle。
Invoke-CheckedGit -GitArgs @('-C', $repo, 'bundle', 'create', $bundle, '--all')
Invoke-CheckedGit -GitArgs @('-C', $repo, 'bundle', 'verify', $bundle)
Invoke-CheckedGit -GitArgs @('-C', $repo, 'bundle', 'list-heads', $bundle)
Get-FileHash -LiteralPath $bundle -Algorithm SHA256
```

bundle 不会自动携带未提交或未跟踪文件、未入库的工作目录配置和虚拟环境，也不保留原 worktree 布局；密钥与生产数据是否存在于提交历史，必须由上述交付前审查确认。交付 bundle 的 SHA-256、refs／完整提交清单和各分支“已审查／待审查／未合入”的状态；不得把含未合分支的 bundle 描述为全部功能已通过。

接收端选择不存在的新目录。显式检出 `main`，避免把其他分支当作稳定版本。为保持当前源码与 manifest 的字节一致，本项目沿用 `core.autocrlf=false`；bundle 不携带仓库配置，因此 clone 时须显式设置，行尾规范化须单独审查，不混入功能提交：

```powershell
$bundle = '<收到并核对SHA256的bundle绝对路径>'
$cloneDir = '<不存在的新仓库绝对目录>'
if (Test-Path -LiteralPath $cloneDir) { throw '目标已存在，不覆盖' }
Invoke-CheckedGit -GitArgs @('clone', '--config', 'core.autocrlf=false', '--branch', 'main', $bundle, $cloneDir)
Invoke-CheckedGit -GitArgs @('-C', $cloneDir, 'branch', '--all')
Invoke-CheckedGit -GitArgs @('-C', $cloneDir, 'rev-parse', 'HEAD')
Invoke-CheckedGit -GitArgs @('-C', $cloneDir, 'remote', '-v')
```

常规 clone 只检出一个工作分支；本例明确为 `main`，不是把所有功能分支同时放入工作树。其它已传递的分支可在 `origin/codex/...` 查看；这里的 `origin` 是本地 bundle 路径，不是托管平台、可推送远端或持续同步服务。若该接收目录只由一位 agent 使用，可在确认干净后执行 `git switch --track origin/codex/<agent>-<task>` 建立对应本地分支。多人继续开发时，由接收方集成人从对应 ref 分配独立 worktree，例如 `git worktree add --track -b codex/<agent>-<task> <新worktree目录> origin/codex/<agent>-<task>`；已有同名分支不得重复创建。要开始新的开发任务，应另建新任务分支并注明依赖，不改写归档分支。

## 7. 任务与审查记录模板

```text
任务／作者／唯一集成人：
工作目录／分支：
main 基线（完整 SHA）／任务 base（完整 SHA）：
依赖分支与冻结 head（没有则写无）：
允许编辑路径／公共接缝及负责人：
目标／API 字段与权限／数据迁移／明确不在范围内的事项：
测试计划（临时数据、端口、命令、依赖范围）：

作者交付：
最终 head／变更路径／行为变化：
实际命令、退出码、passed/skipped/failed、日志和截图：
运行前后源码散列／未验证项／已知问题：

独立审查：
审查者／base／head／实际只读检查范围：
发现／修复复核／通过或未通过及限制：

组合交付：
各已审查 head／合并顺序／最终 integration head：
组合测试与再次独立审查（绑定最终 head）：
main 合并提交／文件树一致性／源码与报告清单：
部署状态（未部署或单独发布记录链接，不凭 Git 推断）：
```

应用运行、依赖和隔离测试见 [DEVELOPMENT](DEVELOPMENT.md)；当前候选与责任登记见 [HANDOFF](HANDOFF.md)；API 和模块契约见 [API](API.md)；构建、备份、迁移、恢复和部署见 [DEPLOYMENT](DEPLOYMENT.md)。本指南没有执行任何部署、数据导入、密钥变更或真实云写。
