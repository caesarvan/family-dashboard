# 隔离 Docker 恢复演练

本工具面向运维人员和联合开发 agent，验证当前镜像能否按部署文档恢复完整家庭数据。它只使用新建的虚构家庭、独立 Docker 数据卷与回环 HTTP；不读取生产 `.env`、数据库或凭据，不启动同步 worker，不访问提供者。

生产恢复仍按 [DEPLOYMENT 第 6.2 节](DEPLOYMENT.md#62-根据完整-manifest-恢复一户或整个平台) 执行，恢复后旧成员登录失效规则见 [MEMBER-SESSIONS](MEMBER-SESSIONS.md#恢复后使旧成员登录失效)。演练结果不能替代生产恢复授权、异地备份或真实云端恢复核对。

## 已验证结果

2026-09-15 16:54（北京时间），在 racknerd 使用当前不可变镜像完成一次独立演练：65 项控制器检查、9 项 seed 检查、202 项恢复后检查通过，exit 0。22 个容器和 6 个新卷均已清理，原线上三个服务保持运行状态。13 项不调用 Docker 的安全测试另行通过。逐项范围和散列见 [VALIDATION](VALIDATION.md)；这仅证明本次合成恢复。

## 软件与执行入口

| 文件 | 职责 |
|---|---|
| [deploy/rehearse_restore.py](../deploy/rehearse_restore.py) | Linux Docker 主机上的标准库控制器；建立隔离资源、核对镜像源码、备份、执行文档恢复程序、验证及清理 |
| [tests/restore_rehearsal_fixture.py](../tests/restore_rehearsal_fixture.py) | 容器内的合成数据 seed/verify；使用实际 HTTP 和 SQLite 读回；不实施恢复 |
| [deploy/backup.py](../deploy/backup.py) | 原有在线备份实现；演练时源 app 已停止，完整组包含注册目录和两户数据库 |
| [tests/test_recovery_rehearsal_safety.py](../tests/test_recovery_rehearsal_safety.py) | 不调用 Docker 的安全边界测试，覆盖错误镜像、旧输出目录、资源归属变化和创建结果不确定 |

控制器从当前 DEPLOYMENT 文档提取唯一的恢复 Python heredoc，从 MEMBER-SESSIONS 提取唯一的失效 SQL；记录二者 SHA-256 后原样执行，没有独立维护第二份恢复算法。控制器和 fixture 不属于 app 镜像业务代码，不注册新 API，不修改 schema。

## 运行要求和命令

在 Linux Docker 主机上准备本源码包及已存在的相配镜像。执行账户需能调用 Docker。镜像参数必须是完整不可变 `sha256:` ID；不接受标签，也不拉取镜像。源码中的全部顶层 Python、requirements 和静态文件必须与镜像 `/app` 中对应文件逐字一致。

下面只创建新的演练报告目录。当前镜像来自 2026-09-15 16:25:03 发布；换版本时先选已验证的相配镜像，不把旧 ID 当永远有效的默认值。

```sh
cd /opt/family-dashboard
rehearsal_image='sha256:f1e4cc56979f793f32585f498fa2fca55987356bd68f67e8cc6c14f0b1b6a01d'
rehearsal_parent='/opt/family-dashboard-rehearsal-reports'
install -d -m 0700 "$rehearsal_parent"
rehearsal_output="$rehearsal_parent/run-$(date -u +%Y%m%dT%H%M%SZ)"
python3 deploy/rehearse_restore.py --image "$rehearsal_image" --output "$rehearsal_output"
```

`--output` 的父目录必须已存在，输出目录必须不存在；程序不会覆盖旧报告。也可用 `--source-root` 指向独立源码副本。不要独立对生产 app 容器执行 fixture；正常环境缺少专用 marker 和 runId 时，fixture 会拒绝运行。

## 一次演练验证什么

1. 创建默认户和一个子家庭、四成员、共享任务和采购、私有财务标记、已引用及未引用照片、两台 TV。实体、财务、图片和 TV 经实际 HTTP API 创建。虚构加密账号及进行中 OAuth 状态通过明确的合成数据库 fixture 建立；不代表实际提供者授权成功。
2. 停止源 app，通过原 backup.py 获取三库完整组；只复制 manifest 与它引用的快照到新空卷。目标卷在恢复成功前不启动 app、不创建空身份。
3. 分别用错误散列、缺失子户快照和注册目录映射错误的完整组尝试恢复。每项必须被文档程序拒绝，且没有创建目标数据库。
4. 原样执行平台恢复程序，再逐户执行文档失效 SQL，递增成员 auth_version、撤销旧会话、推进浏览器代次并清空进行中 OAuth。
5. 启动恢复后的 Gunicorn。fixture 在任何登录请求前逐表核对 schema、行、索引、外键和内部序号；只有上述四类认证变化可不同。随后通过实际 HTTP 检查新登录、旧凭据拒绝、家庭/私有隔离、照片访问与 TV 只读，核对虚构令牌仍能用原合成主密钥和家庭派生密钥解密。
6. 核对绑定的源码未改变，清理本次资源并逐项读回。清理失败会使总结果失败，报告保留资源名称和错误类型，不自动执行全局 prune。

每个容器使用 `--network none`，不发布端口，镜像根只读，仅本次新卷可写。fixture 的 HTTP 客户端也限制回环地址并拒绝跟随外部重定向。数据和 proof 卷初始化后由 UID 10001 使用；仅新卷初始化助手以 root 调整本卷权限。

## 证据与失败处理

报告为输出目录中的 `report-<runId>.json`（0600），包含不可变镜像、源码/恢复程序/SQL 散列、实际容器隔离配置、逐项检查、请求数量、失败阶段和清理结果。proof 卷含虚构 cookies 与状态，在清理时一起删除；不进入报告或通用源码包。总 `passed` 只有所有步骤和清理成功才为 true。

创建结果不确定时，控制器仍追踪已分配的唯一名称；清理前必须成功列举资源并核对准确名称及本 runId 标签。Docker 不可用或归属改变时不会冒险删除，记录清理失败。维护者根据报告核对确属本次演练的残留资源，不能把普通业务容器或数据卷作为清理目标。

控制器报告证明合成 Docker 恢复，不证明真实 token 仍有效、真实金融数据完整、历史外部写入可撤销、硬盘物理损坏可恢复、云同步队列适合重新启动或异地灾难恢复。生产恢复还要保全现场、核对配置及恢复范围，逐户核验，并在决定是否重启 sync 前检查待写队列。

实际运行结果与历史测试分开记录在 [VALIDATION](VALIDATION.md)。完整后端历史计数不包含本工具新增的安全测试；本工具不要求重复运行与其无关的 UI 测试。
