# NVIDIA 开发任务编排

本工具把获授权的开发任务发送到指定 NVIDIA 推理入口，保存结构化、**未审查**的实现建议或补丁建议。它不是产品助理，也不是可以操作工作树的代码执行 agent。没有 shell、子进程、文件读取工具、Git 写入、补丁应用、测试运行、合并、发布或审查晋级能力。

源码在 `tools/inference_orchestrator/`，仅依赖 Python 3.12+ 标准库；测试为 `tests/test_inference_orchestrator.py`。本轮不修改应用 API、数据库结构、前端、运行依赖、Docker COPY 或发布白名单。开发工具与本机运行证据不需要进入生产镜像；产品模型适配由独立分支处理。

## 已验证范围

2026-09-16 在本地作者工作树使用已授权的服务端密钥文件验证：

| 项目 | 观察到的结果 |
|---|---|
| 指定入口 | `https://inference-api.nvidia.com/v1`；TLS 正常校验，拒绝重定向 |
| 模型目录 | `GET /models`，HTTP 200，170 个模型 ID；不代表全部可以完成推理 |
| 已调用模型 | 目录内的精确 ID `us/azure/openai/gpt-4o-mini` |
| 请求协议 | `POST /chat/completions`；`messages`、`max_tokens`、`temperature: 0`、`stream: false` |
| 返回协议 | 单个 `choices`，`finish_reason: stop`，`message.content` 字符串，解析为 JSON 对象；不接受 tool/function call 或拒绝标记 |
| 正式最小探针 | HTTP 200，2031 ms；精确 JSON 核验通过；38 输入 / 9 输出 tokens |
| 小并发 | 2 项 / 2 成功，配置 2 worker，实测峰值 2；480 输入 / 327 输出 tokens |
| 需求切片 | 24 项 / 24 成功 / 24 次请求，每项一次成功；配置 24 worker、3 请求/秒，**实测峰值 14** |
| 24 项用量 | 5879 输入 / 4399 输出 / 10278 合计 tokens；延迟最小 2766、中位 3768.5、最大 7536 ms |
| 幂等重跑 | 24 项仍成功，累计推理请求仍为 24；本次推理请求 0，仅重新读取目录 1 次 |

24 项是脱敏需求分析任务，没有向模型发送家庭记录、财务数据、真实源文件或密钥。产物是建议，不是完成 24 个功能或完成测试的证据。全部 live 运行未出现 429、超时或服务故障；这些失败路径仅由本地合成测试验证。未验证全部目录模型、工具调用、stream、Responses 协议、长期吞吐、生产账号或生产部署。

`observed_max_concurrency` 统计客户端同时进行的模型请求/响应解析调用，不测量服务端调度、GPU 并行执行或原生 Codex agent 数量。`total_recorded_request_attempts` 是请求前持久化的本地尝试计数，不能单独证明网络故障时服务端实际接收或计费次数。

可读取的本地证据均在本工作树已有 ignore 规则覆盖的 `test-results/inference-orchestrator/`：

- `protocol/probe.json`：最小探针安全元数据。
- `small-probe/runs/initial-observed-summary.json`：小并发原始摘要。
- `requirements-24/plan.json`：24 项脱敏需求和分支／工作树预留名称。
- `requirements-24/runs/initial-observed-summary.json`：24 项首轮原始摘要，保留峰值 14。
- `requirements-24/runs/b75b9ffaed8f4780b6353c686b12b46c.json`：幂等重跑摘要，峰值 0、推理请求 0。
- `requirements-24/safe-observations.json`：逐任务模型、HTTP 状态、延迟、用量、产物路径和 SHA-256。
- `requirements-24/proposals/*.json`：保留模型建议与观察元数据，状态始终为 `untrusted_unreviewed_proposal`。
- `requirements-24/jobs.sqlite3`：任务状态和每次请求的开始、结束、状态及延迟；不保存密钥或原始 HTTP 响应。
- `requirements-24/source-reviewed-followup.md`：作者对照当前源码后的提炼，明确建议重合、待核查项和后续切片。

运行证据是本机文件，不随 Git 提交。最新 `summary.json` 会被下次运行替换；每次新运行同时写入独立 `runs/<run_id>.json`。早期实测摘要额外原样归档，不能将重跑的零峰值替代首轮观察。

## 使用方式

在集成人分配的独立工作树根目录运行，先读取 [Git 工作流](GIT-WORKFLOW.md)。密钥路径只通过 `--key-file` 提供；不要把文件内容放在参数、环境示例、计划、Git 或模型上下文中。工具接受单一原始 token、`NVIDIA_API_KEY=...` 等明确赋值、单一 Bearer header，或 `api_key` JSON 对象；不解析任意脚本，格式不明确时失败关闭。

以下 `<服务端密钥文件>` 和 `<已确认base>` 是需要替换的占位符。首次目录结果决定可选模型 ID：

```powershell
python -m tools.inference_orchestrator catalog --key-file '<服务端密钥文件>' --output-dir test-results/inference-orchestrator/catalog-check
python -m tools.inference_orchestrator probe --key-file '<服务端密钥文件>' --output-dir test-results/inference-orchestrator/protocol-check --model us/azure/openai/gpt-4o-mini
python -m tools.inference_orchestrator slices-plan --output-dir test-results/inference-orchestrator/example --model us/azure/openai/gpt-4o-mini --base '<已确认base的40位SHA>' --count 2
```

`slices-plan` 只准备脱敏计划，不发送请求、不创建 refs。集成人先核对任务内容、base、文件所有权和名称；预留名称不代表实际分支／工作树存在，也不自动检查它们是否已被其他任务占用。真实代码任务应由集成人提供专属计划，不能直接把需求切片当作实现验收。

```powershell
python -m tools.inference_orchestrator run --key-file '<服务端密钥文件>' --output-dir test-results/inference-orchestrator/example --plan test-results/inference-orchestrator/example/plan.json --workers 2 --requests-per-second 1 --max-tokens 700 --max-attempts 2
python -m tools.inference_orchestrator status --output-dir test-results/inference-orchestrator/example --plan test-results/inference-orchestrator/example/plan.json
```

默认并发 2，范围 1–24；速率默认每秒 1 次，范围 0.1–5 次；每次输出上限默认 700 tokens，范围 32–1500；每个任务累计最多 1–3 次请求，默认 2。计划最多 100 项；所有请求共享速率门和服务端冷却期。不会为了达到并发数字重复发送已成功任务。CLI 成功退出码为 0，有失败／不确定／待执行任务为 1，配置、协议或本地异常为 2。

## 任务与输出契约

计划顶层字段必须恰好是 `version: 1`、`base_commit`、`model`、`data_classification: synthetic_or_approved_source`、`tasks`。声明并不能自动识别个人数据；计划负责人必须核对发往服务端的内容属于已授权的脱敏或源代码范围。

每个任务必须只有：

| 字段 | 含义 |
|---|---|
| `id` | 独立、稳定的任务名称 |
| `branch` | 集成人预留的 `codex/<name>` 名称；工具不创建或切换 |
| `worktree_name` | 集成人预留的目录名称；工具不创建工作树 |
| `instruction` | 具体、有限的任务目标，不超过 8000 字符 |
| `context` | 直接附带的脱敏上下文／源码片段，不超过 8000 字符；不会据路径读取文件 |
| `allowed_paths` | 最多 20 个相对路径；拒绝目录穿越、隐藏目录、密钥／数据库目标；`[]` 仅允许文字建议 |

模型只能返回 `task_id`、`summary`、`patches`、`checks`、`limitations`。`patches` 中每项只含 `path` 与统一 diff 字符串，目标必须在任务白名单内，diff 文件头也必须匹配。校验不证明补丁语义正确、可以应用或安全；`checks` 只是建议执行的验收步骤，绝不执行。附加 shell、工具、执行状态等字段会被拒绝。

输出以任务 ID 为文件名，完全不使用模型提供的路径创建文件。补丁仍被当作普通 JSON 字符串保存。所有产物固定 `applied: false`、`tests_executed: false`、`review_status: untrusted_unreviewed_proposal`。下一轮由独立作者在获分配的工作树复核和实现，非作者审查固定 base/head，通过后才由集成人合并。

## 恢复、错误与安全边界

SQLite 绑定完整计划的 SHA-256；计划任何内容改变都必须使用新的状态目录。成功任务重复运行时不再发出推理请求，失败任务不自动重新排队。OS 文件锁防止两个进程同时操作同一队列，进程异常退出后锁由系统释放。

请求前先持久化 attempt。进程在请求与结果保存之间中断时，下一次读取将 `running` 标为 `uncertain`，不会自动重发；网络超时和连接错误也保留不确定状态。此处幂等保证仅在本地队列成立，服务端是否已生成或计费可能未知，不声称网关支持幂等请求键。

只有 429、500、502、503、504 在累计预算内自动重试，使用指数退避、抖动和全队列 `Retry-After` 冷却。服务端要求等待超过 120 秒时，本轮失败结束，不提前重试。401／403、格式错误、截断、拒绝响应和模型输出越界不自动重试。目录发现单次失败直接返回安全错误，不能用缓存冒充当前可用。

需人工决定重试不确定任务时：

```powershell
python -m tools.inference_orchestrator requeue --output-dir test-results/inference-orchestrator/example --plan test-results/inference-orchestrator/example/plan.json --task-id household-isolation --max-attempts 2 --acknowledge-possible-duplicate-generation
```

此操作只改变本地状态，之后仍须运行 `run`。已达到累计上限的任务拒绝再排队。新状态目录会形成新任务，可能产生新生成请求，不能当作无成本重试。

默认 socket 超时 30 秒，允许 1–60 秒；分块读取时检查耗时与大小，目录响应最多 2 MB、推理响应最多 250 KB。操作系统 DNS 和已进入的阻塞 socket 读取不能提供严格的整体墙钟截止保证。Ctrl+C 停止后续排队请求，并等待已经开始的请求结束；强制结束进程后按不确定请求恢复，不声称取消了服务端生成。

密钥仅保留在服务端进程内的凭据对象和 HTTP Authorization header。禁止重定向，客户端固定指定 origin；默认沿用系统代理与 TLS 信任，不关闭证书验证。错误只输出固定代码／HTTP 状态，不记录 provider body、request headers、原始异常或 traceback。请求内容、原始响应、解码后的外层 JSON 和内层模型 JSON 均检查密钥回显，防止 Unicode 转义绕过。没有密钥轮转、跨用户授权管理或价格估算功能；本工具不替代产品服务端权限校验。

## 本地验证

```powershell
python -m unittest discover -s tests -p test_inference_orchestrator.py -v
git diff --check
```

测试使用虚构密钥、临时目录和合成 transport，不调用真实模型。覆盖凭据解析、原始／转义回显、HTTP 错误脱敏、超时、429 冷却、拒绝／工具／截断输出、大小限制、计划／路径／补丁越界、并发与限速、单进程锁、持久化重放、崩溃恢复、取消及每次运行证据保留。实际模型故障恢复、持久化运行服务和产品端到端流程仍须单独验收。

作者最终专项结果：**27 passed，0 failed / error / skipped**；原件为 `test-results/inference-orchestrator/validation/unit-tests.txt` 和 `.json`。编译检查与 CLI help 通过。此数字不包含应用原有测试，也不替代非作者对固定提交的审查。
