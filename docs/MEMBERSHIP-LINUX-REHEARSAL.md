# 成员迁移 Linux 合成演练

`deploy/membership_linux_rehearsal.py` 是待审、待实际运行的独立演练入口。使用已核候选包与本地不可变镜像，验证控制器真实 Linux UID 权限、停写三库备份、两户 58→61／平台 2→9 的完整保全，以及再次应用初始化后不漂移。工具完成或本地专项通过不代表 Docker 演练已通过。

作者基线经明确授权从 `25fddc71984988c0f181669925381b6feea381d9` 快进到 `d8025597866574e0ee352b53455bc217a5c005de`，复用已审 `membership_release_build.Executor/isolated` 的本地 Unix Docker、network none、只读根、UID 10001、受限 capabilities、临时 tmpfs、原始命令记录与仅本次 container ID 清理。只新增本脚本、专项测试及本文；不修改控制器或数据核验器。

```sh
python -B deploy/membership_linux_rehearsal.py --candidate /absolute/candidate --package-sha256 SHA --image-id sha256:NEW_IMAGE --output-dir /absolute/new-rehearsal
```

Linux root 用于创建并 chown 唯一新输出内的 data/proof 为 `10001:10001`、目录 0700。candidate 必须含 package 四原件与完全一致的 source/RELEASE-MANIFEST.json；执行脚本、包核验器、隔离 helper 都与候选字节绑定。新镜像须完整 runtime 哈希等于包、固定旧父镜像两层后继、Config 保持。输出与候选不得重叠，已有输出拒绝，不自动重试或回滚。

旧父固定为 `sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2`。它在空的合成 data 内运行真实 Flask test client：登录、创建／消费平台邀请、创建第二家庭和各户任务；再显式写入合成私有财务行、audit 行及普通 member 角色，保留会话、registry、旧 schema/index/sequence。准备阶段不挂载新 source，不能误用新应用初始化。该进程退出且其独占容器清理后才备份；没有其它写者。

从已核 candidate 控制器以 AST 读取原样 `DATA_PREFIX`、`BACKUP_PROGRAM`、`WARM_PROGRAM` 与 runtime probe，不使用多代字符串替换。新镜像顺序执行完整备份并在 proof 外存副本、一次 warm/migration、另一个新进程调用同一 controller warm callback 做再次 create_app，再以只读 data 挂载执行 `check_current_after`。warm_once 的持久 attempt 保护仍由原数据模块执行，不盲目重放。每个阶段的程序 SHA、命令 stdout/stderr、before/after/backup/attempt/重启保全原件都留存。

`result.json` 只有全链成功才 passed=true；包含包／source/tree/image/controller 身份、程序 hash、步骤、三库保全摘要与完整 proof 文件 hash。失败保留当前目录和失败阶段，不删除合成库或备份。敏感真实数据、生产 volume/env、网络、镜像 tag、compose、systemd 均不涉及；所有环境变量在源码中明确为合成值。实际镜像和文件权限必须由后续获授权的 Linux 执行证明，不能由 mocked Docker 或 Windows 检查代替。

本地专项仅检查真实控制器原程序 AST 等价、限定挂载参数、排他路径、不可变镜像格式、三库证据摘要缺失／部分／漂移拒绝，以及非 Linux 入口提前拒绝。摘要样本明确是测试构造的 JSON，不是执行迁移证据；实际数据保全由已审控制器和数据 helper 在真正 Linux 演练中检验。

作者本地合同专项 18／18 通过（0.86 秒），无失败／错误／skip，XML `a4365155cf9c591b9650498dca6a88d975f0fa2815c01a4c26b5071f378573c4`。随后按 Root 审查修正 seed 全部 Flask client 请求均使用 `base_url=PUBLIC_ORIGIN` 的 HTTPS URL，避免默认 localhost 与 Origin／Secure cookie 不一致。该 seed 在固定旧源 `8badc37d85889e8e8dc0c11670cb98a55a768369` 提取的根 Python 文件上，独立本地进程真实执行成功（2.80 秒）：两户三库、58/58＋2、各户 admin 1/member 1；源码前后相同、临时目录清理、stderr 空。只把 `/app` 身份断言及 `/data`、`/proof` 改为临时绝对路径，原 seed 与实际程序各自散列留存；这是本地真实 API 准备检查，不是镜像或 Linux 权限验证。原件在作者树 `test-results/membership-linux-rehearsal-contract-r1/`、`test-results/membership-linux-seed-local-r1/`。
