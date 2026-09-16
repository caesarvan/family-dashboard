# NVIDIA 助理配置工具

`deploy/configure-assistant.py` 只更新一个**已经存在**的服务端 `.env` 的三个键：`ASSISTANT_PROVIDER=nvidia`、`NVIDIA_MODEL`、`NVIDIA_API_KEY`。它不加载应用，不访问网络，不调用模型或 Docker，也不启动或重启任何服务。保存配置不表示运行进程已采用配置，更不表示真实模型请求已通过。应用仍使用 [固定 NVIDIA endpoint](ASSISTANT-PROVIDER.md)，本工具没有 URL 参数。

工具仅用 Python 标准库，可独立放在服务器的已审查工具目录。运行写入 CLI 必须是 POSIX 平台，目标目录应由可信管理员独占管理；Windows 的 chmod 不等于私有 ACL，因此 Windows CLI 拒绝写入。Windows 下允许 `--check`；单元测试直接调用纯函数与文件函数只处理合成临时文件。

## 输入与安全输出

```sh
# 隐藏输入；只在已经授权的服务器目录运行。
python3 /<reviewed-tool-dir>/configure-assistant.py \
  --env-file /<authorized-directory>/.env \
  --model us/azure/openai/gpt-4o-mini

# 只检查文件，不读取密钥输入、不创建备份或锁。
python3 /<reviewed-tool-dir>/configure-assistant.py \
  --env-file /<authorized-directory>/.env --check
```

示例模型 ID 来自已有协议证据；本工具只验证格式，部署人须核对其当次可用性。允许 `[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}`，不接受空格、非 ASCII、shell 元字符或超过 200 字符的值。没有默认模型。

密钥只通过有真实终端的 `getpass` 隐藏输入，或明确指定 `--key-stdin` 后的标准输入传入。无法隐藏输入时拒绝，不降级回显。不提供 key 命令参数、环境变量回退或 key 文件参数。标准输入必须到达 EOF，最多读取 4099 字节，允许最多 4096 个 UTF-8 字节的一个非空密钥和可选 LF/CRLF 终止符。其他控制字符、Unicode 格式控制/分隔符、额外行均拒绝。前后普通空格保留，不悄悄裁剪凭据。进程内存不提供可靠擦除保证。

`--check` 只输出如下四个布尔值，不输出任何配置值、路径或密钥散列：

```json
{"ASSISTANT_PROVIDER": true, "NVIDIA_API_KEY": true, "NVIDIA_MODEL": true, "isNvidia": true}
```

前三项表示文件中存在非空字面值；`isNvidia` 只判断 provider 的字面值是否恰好为 `nvidia`。不展开 `${VARIABLE}`，不读取 shell 环境，也不验证 Compose 的最终配置、服务健康、账户权限或密钥有效性。空值返回 false。格式有歧义时整次检查失败。`--check` 不能与 `--model` 或 `--key-stdin` 合用。

成功写入仅输出固定确认句；失败仅输出固定安全错误，退出 1；取消退出 130。参数解析也不回显未知参数。公开 helper 重新抛出的异常没有原异常的 `__context__`/`__cause__`，不保留 decoder 或系统错误文本。不要另行给这些函数加入参数、局部变量或异常对象调试日志。

## 原文件保护与恢复边界

- 原文件最多 1 MiB，要求有效 UTF-8，可有 BOM；拒绝 NUL、裸 CR、非普通文件、硬链接、symlink 与父目录 symlink/reparse point。输出同样不能超过 1 MiB。
- 解析限定为普通 ASCII 键名、可选 `export`、`=`/`:`、空行/注释及单/双引号多行值。任何重复键、裸键、未闭合引号、闭引号后非注释文本、含引号的未加引号值或续行式未加引号值均拒绝；不会修复不确定语法。与完整 Compose dotenv 语法相比，这是明确收窄的子集。
- 三键必须一起提供，其他更新键拒绝。未涉及的 record 保留 UTF-8 原字节，包括多行、注释、BOM 和混合换行；需追加键时可以在原末行后补换行。被更新的 record 整体重写，其旧注释不保留。新值使用与 OAuth 工具相同的双引号转义，转义 `\\`、`"` 和 `$`，防止插值；语义依据 [Compose dotenv 解析器](https://github.com/compose-spec/compose-go/blob/main/dotenv/parser.go)。原 OAuth 工具及其 allowlist 不变。
- 同目录独占 `.env.assistant-lock` 防止本工具的并行更新；已有锁直接拒绝。中止后可能遗留锁，管理员先确认没有存活写入进程，再私下处理；不会凭时间自动删锁。
- 先以独占创建、0600 写出 `.env.assistant-backup-<UTC>-<random>`，内容是原文件完整字节；再以 0600 创建同目录临时文件，flush/fsync 后核对原文件的设备/inode/大小/时间及内部 SHA-256，最后 `os.replace` 原子替换，并 fsync 目录。内部散列永不输出。备份包含秘密，不进入 Git、源码包、附件或公共日志，不自动轮换/删除。
- 替换前失败保持旧文件，尽力清理本次临时文件及锁，已完成备份保留。并发编辑或同字节替换均拒绝覆盖。临时文件名碰撞不会删除别人文件。替换完成后目录 fsync 失败属于结果未确认：新文件可能已经生效，备份仍保留，不能把所有非零退出当成“绝无写入”；须先用 `--check` 和管理员的私密检查确认再重试。
- 锁仅约束本工具；不能保证阻止不遵守锁的编辑器在最终检查与 replace 之间写入，亦不是对恶意本地管理员的文件系统沙箱。部署窗口必须独占 `.env`。原子替换后的文件属于执行者，部署人应使用正确文件所有者运行。自动回滚、服务重载和备份恢复均不在本工具中。

## 通过 SSH 标准输入注入的独立操作示例

以下只是供集成人审核后执行的命令说明，**本次实现没有读取真实密钥、执行 SSH 或写生产配置**。首先把已审查脚本交付到授权服务器路径；该交付和运行不属于普通源码候选自动发布流程。替换下面所有占位符，保留密钥只在进程内存和 SSH stdin 中传递。示例文件必须仅含一行原始凭据；若获授权的原文件带标签或其他结构，使用已审查的内存解析方式，不把原文件整体发送或另落地一个明文副本。

PowerShell 中用 Python 标准库直接把字节交给 SSH stdin，避免 PowerShell 管道改写编码或把密钥放进 shell 命令：

```powershell
$taskSender = @'
from pathlib import Path
import subprocess
import sys

try:
    with Path(r"<authorized-local-key-file>").open("rb") as stream:
        credential = stream.read(4099)
    raw = credential[:-2] if credential.endswith(b"\r\n") else credential[:-1] if credential.endswith(b"\n") else credential
    if not 1 <= len(raw) <= 4096 or b"\r" in raw or b"\n" in raw:
        raise ValueError()
    # Paths/host are reviewed literals. No credential appears in argv or env.
    result = subprocess.run([
        "ssh", "-T", "<authorized-ssh-host>",
        "python3 /<reviewed-tool-dir>/configure-assistant.py "
        "--env-file /<authorized-directory>/.env "
        "--model us/azure/openai/gpt-4o-mini --key-stdin",
    ], input=credential, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    expected = b"Configuration saved with a private exact backup. Services were not restarted.\n"
    success = result.returncode == 0 and result.stdout == expected and not result.stderr
except Exception:
    success = False
print("Configuration saved; activation remains separate." if success else
      "Configuration result unconfirmed; inspect privately before retrying.")
sys.exit(0 if success else 1)
'@
& '<authorized-local-python>' -c $taskSender
if ($LASTEXITCODE -ne 0) { throw 'Configuration result unconfirmed.' }
```

远端路径与 SSH host 示例必须替换为可信固定值，不拼接不可信输入。SSH 使用已有主机密钥校验，不关闭校验、不使用 PTY。输出捕获后只做固定确认匹配，不把远端原始 stdout/stderr 打印或保存。传输超时可能发生在远端替换之后，不能自动重试。确认 `.env` 后，运行进程的采用与真实合成模型验收另行授权安排；本工具没有激活功能。

## 验证

`tests/test_assistant_configuration.py` 使用合成文件/凭据，覆盖纯 render、严格解析、真实 CLI、字节/大小边界、重复键拒绝、多行保留、并发变化、文件名碰撞、备份精确字节、写入失败、固定错误及秘密不进入输出。Linux 运行还验证真实 0600 和 stdin 成功路径；Windows 跳过 POSIX 专项，不能冒充 Linux 文件权限验收。原始 pytest/JUnit 及运行平台信息保存在本任务 ignored `test-results/assistant-configuration/`，不进入 Git。尚不包括真实服务器、真实密钥或服务重启后的模型使用。
