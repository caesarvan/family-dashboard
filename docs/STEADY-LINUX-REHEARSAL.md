# 61/9 无结构变更发布的合成 Linux 演练

`deploy/steady_linux_rehearsal.py` 只验证正式包在独立两户三库合成数据上的正常 app 初始化保全。它依赖同一已审组合内的 `steady_release_package.py`、`steady_release_data.py` 及既有隔离构建工具；单独作者分支不能用于发布。

流程固定为：

1. 校验正式 package/manifest/source、脚本及 helper 字节；候选 image 必须在稳态固定父镜像 `c8e3da…` 上增加两个已核对层，配置不变，实际 runtime 文件等于包。
2. 父镜像用真实 app 登录、家庭邀请/兑换、任务和角色 API 建立两户三库。合成私人行和 audit 序列由显式夹具写入；确认每户 61 表、平台 9 表、每户一位管理员与一位普通成员。该进程结束。
3. 候选镜像运行 `steady_release_data.begin`，完成全组停写快照、备份验证与保留。
4. 新的隔离进程调用正常 `app.create_app()`，并逐一 `platform.child()` 初始化注册家庭；进程退出后才继续。
5. 独立只读数据挂载运行 `check_stopped`，核对所有库的 schema、原行、序列及 marker。源包再次校验后才记录 passed。

这里不调用 `warm_once`，不重放成员迁移、不启动同步/媒体 worker，不读生产 volume、`.env` 或运行服务。容器沿用 `membership_release_build.Executor/isolated`：本机固定 Unix Docker socket、无网络、只读根、UID 10001、丢弃 capabilities；可写目录仅该新演练输出内的 data/proof 与临时 tmpfs。失败不重试、不删除库组或证据；已结束的临时容器由现有隔离工具清理。

## 明确的证据边界

合成数据库由正常父镜像创建，不具有真实 R3 迁移收据。脚本在空合成根目录写入明确标为 synthetic 的 marker，并给 begin/check 显式传入它的散列。它从包中记录生产 `MEMBERSHIP_MARKER_SHA256`，但没有验证真实生产 marker。

`exactProductionControllerProgram=false`、`syntheticMarkerOverride=true` 会写入契约及结果。程序复用固定包中的 DATA_PREFIX/RUNTIME_PROGRAM；begin/check 使用带 synthetic override 的适配程序，**不是原样执行生产控制器**。`plan_sha256` 在本演练指的是独立 `rehearsal-contract.json` 散列，不是将来生产 release plan。

结果记录源码 head/tree、package/manifest、完整 source/runtime hashes、固定父/候选镜像、控制器散列、每段实际程序散列、合成/生产 marker 的区别和全部 proof 文件散列。`commands/` 保留实际隔离命令、退出码和 stdout/stderr；`proof/` 保留 identity、合成契约、seed、全组 before/after、备份组和验证结果。整个输出含合成数据库，应保留为私有验证资料，不提交 Git。

## 执行（仅由发布协调方运行）

先完成独立审查及组合，在新候选目录准备正式 package 和匹配 source，并构建候选镜像。Linux root 使用该候选包中的脚本；output 必须是从未存在且不与候选重叠的目录，父目录已存在。

```bash
python -B /path/to/candidate/source/deploy/steady_linux_rehearsal.py \
  --candidate /path/to/candidate \
  --package-sha256 <已核对的包散列> \
  --image-id sha256:<已构建的候选镜像> \
  --output-dir /path/to/new-private-rehearsal
```

不能把静态语法检查、本地合成 fixture 检查或命令模板当成 Linux 演练已通过。真实执行、独审、生产停写/备份/环境绑定和最终上线分别留证；本脚本不部署或激活服务。
