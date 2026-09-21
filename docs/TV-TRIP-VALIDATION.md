# 电视旅行回顾：受限 Linux 验证入口

`deploy/tv_trip_validation_runner.py` 为本批镜像验证设置 384 MiB RAM、零容器 swap。它复用现有 `build_tv_trip_release.validate`，只转换那一次已知验证命令的内存参数；共享 builder 不变。实际 Docker inspect 必须在容器启动前证明内存、swap、无网络、只读根、非 root 身份及权限限制符合要求，否则删除本次创建的容器并报错。

在已解包且核验过的候选源目录，以 Linux `python3 -B` 运行：

```text
python3 -B deploy/tv_trip_validation_runner.py --package-dir <绝对目录> --package-sha256 <SHA256> --image-id <sha256:镜像ID> --selection <精确节点JSON> --selection-sha256 <SHA256> --output-dir <不存在的绝对目录>
```

依赖默认使用共享 builder 的已存在 pytest 目录；替换时显式提供 `--pytest-dependencies`，真实依赖字节仍由原 validator 前后核验。入口自身也必须与候选包内源码逐字一致。它不构建镜像、不迁移、不部署，不挂载生产数据。

每次输出保存原始／实际 Docker 命令和 stdout/stderr、启动前 inspect、`memory-contract.json`、原 `validation.json` 及容量 proof。失败原件保留，另建目录才可再次运行。Docker 限额配置不等于负载验证通过，仍需容量用例观测实际 Linux cgroup 及四个并发 WSGI 请求。录制 runner 单测只验证拒绝边界和清理语义，不作为 Linux 容量证据。
