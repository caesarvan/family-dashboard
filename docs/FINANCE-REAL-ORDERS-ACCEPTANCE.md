# 真实订单文件的本机隔离验收

2026-09-19 17:44:31–17:44:40（北京时间），对既有、已授权的淘宝 XLSX 与拼多多 CSV 原始文件完成同一临时 Flask/SQLite 环境的订单导入验收，进程退出码为 `0`。使用真实注册的 API，没有替换业务响应；这不是本人线上 UI 验收，也不代表完整财务场景 B 已完成。

## 实际覆盖

| 来源 | 确认订单数 | 结构化明细数 | 再上传识别为重复 | 再次新增 |
|---|---:|---:|---:|---:|
| 淘宝 XLSX | 299 | 394 | 299 | 0 |
| 拼多多 CSV | 910 | 0（本格式未产生结构化明细） | 910 | 0 |

两份文件依次经过预览、确认、原回执查询与精确重放、重新上传预览与确认、完整分页读回。每条业务值和首次来源位置在内存中与持久化记录、API 返回逐项比对；重新创建应用后再次读回通过。预览未写财务表，重复上传未改变原订单或首次来源，合计保留 1,209 条订单。

订单仍为 `unknown` 或 `excluded`；没有把订单状态解释成实际付款或退款，没有计入净支出。两份原始格式均缺明确币种列，解析器使用的默认 `CNY` **未经独立核实**。预算、核销、其他受检查财务表与共享财务设置保持不变。

## 固定身份与本地证据

- 受验业务源码：`8d35905ef14937703d0488c7190ad0fa16ae79e9`，tree `8647c0398949d063b3e1a8aef10647b6a69e3a74`。源码文件前后哈希一致。
- 实际执行工具：[tests/finance_real_orders_acceptance.py](../tests/finance_real_orders_acceptance.py)，SHA-256 `057ea8caa8f2c4734f962b44d8ec7e1128fa3d4398d54f8673ae6fddb2d6e340`。
- 此 worktree 的忽略目录 `test-results/real-order-acceptance-r1/result.json`：SHA-256 `9ba182e7ff1d1b935d8db1a647cb2b3761ae925b3d77d440205c79e13589ad5d`。包括输入前后哈希、计数、检查结果、受验源码哈希和未验收项；不含业务原值。
- 同目录 `stdout.tool-capture.txt`：SHA-256 `70da0f0f24f8848d6ee37a0ff2cf2e039edff5aca3e5b400b037e0fc34af8e28`；`execution.tool-capture.json`：SHA-256 `34280a8e3a3667e892ba8d96290eedbc3080ceccfe55a4029fd46d798db7ff90`。两者是运行完成后归档的终端工具返回文本及退出码记录，不是进程启动时重定向产生的原件，也不是再次运行。
- 先前只读兼容性索引：同级 worktree `finance-taobao-order-groups/test-results/actual-order-group-compatibility.json`，SHA-256 `43b5d1b4564bd859ae26362f48ed1593fba4ea6f39e3cd301643fca5b6ba55b4`。本次先核对该索引与输入哈希，再执行真实确认；没有把旧预览结果当作本次确认。

原文件前后哈希不变，兼容性索引未变；受保护业务阶段被拦截的网络／子进程尝试均为 `0`，预检使用只读 Git 命令。临时数据库已删除，结果目录只保留脱敏 JSON 与终端摘要。没有联网、上传、生产写入、解密压缩包、读取邮箱或密钥，也没有保留数据库、订单行、金额、商户、姓名、账户或订单号。

## 工具运行方式

仅在获准的独立 worktree 中显式执行；不会被 pytest 自动收集。输入位置由参数传入，不在代码或文档中保存私有路径。输出必须是本 worktree `test-results` 下尚不存在的新目录。工具要求兼容性索引精确哈希和原文件哈希匹配，拒绝链接路径；临时库仅建立在输出目录中。

```powershell
& '<python.exe>' -B -X utf8 tests/finance_real_orders_acceptance.py `
  --taobao '<authorized-order-source.xlsx>' `
  --pinduoduo '<authorized-order-source.csv>' `
  --compatibility-index '<existing-compatibility-index.json>' `
  --compatibility-index-sha256 43b5d1b4564bd859ae26362f48ed1593fba4ea6f39e3cd301643fca5b6ba55b4 `
  --source-head '<exact-current-source-commit>' `
  --output '<this-worktree>/test-results/<new-output-directory>'
```

本次原件已保存，无需为核对报告重复读取私有文件。工具提交后仅增加验收工具与本文，实际运行时的业务源码身份仍以上述固定 base 为准。

## 场景 B 仍待完成

还缺同一临时环境内真实付款流水、独立退款记录及其与订单的可证实关联、相应预算闭环，以及币种依据与本人界面验收。订单原件本身不能补足这些证据；本次不创建合成付款或退款来代替真实来源，也不将本次通过计为完整 B 通过。
