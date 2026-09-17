# Expo 电视展示发布：55 → 55 历史适配器

本文件记录已用于 2026-09-17 14:19:19 激活、14:19:53 正常 TLS 读回的固定历史适配器；本轮发布已完成，不能重放。当前实际身份以 [README](../README.md) 与 [电视展示验收](EXPO-TV-ACCEPTANCE.md#expo-tv-release) 为准；新发布必须重新核对已安装基线与全部候选字节，不能复用本轮绑定。

## 固定基线与范围

`deploy/expo_tv_release/prepare.py` 只读取并校验已审查的本地算子，生成一个全新目录中的未绑定候选；不连接服务器、不执行 Docker、不修改数据库。本轮生成时绑定以下 2026-09-17 13:00 设备管理版本作为输入基线；它已不是当前安装身份：

- 原源码包 SHA256：`a8d823f475079ac0afe9a3a5c42496ffe98c562ece580ab9ef31002ae26f99ba`。
- 原 manifest SHA256：`c51883945ec77ec0c6eb4fa1377cad4d60a4600d2daf36c1ee808b1b9815c3d8`。
- 原 app／sync／media 镜像：`sha256:9a4e032f5817de67a995cd2a849f7c02c8c90ca8f87ffeb3644764b9f0fd2f62`。
- 继续使用 `investment_operations55`，55 张业务表与 2 张平台注册表；无 schema、依赖或 Dockerfile 变化。

输入来自私有 `expo-devices-tools-20260917-r2` 的 7 个算子与 binder，以及原包真正的生产者 `expo-devices-tools-20260917-r1/prepare-package.py`；9 个原件分别固定 SHA。R2 的验证资源 896 MiB 内存／640 MiB tmpfs 保持，不能重放旧轮次。

本轮验证选择电视状态、显示权限、播放、成员会话、家庭隔离、静态托管和备份／55 表保持相关的 11 个 Python 模块。未改的财务、旅行、照片服务、同步、依赖和部署配置继续执行逐字节不变校验；不因历次发布积累而自动重复所有旧功能测试。本轮实际收集 322 项，Linux 实际 321 通过、唯一精确 Windows junction 跳过，零失败／错误，JUnit 唯一节点与运行文件均核对；下一次数量仍须来自新候选的真实收集与执行。浏览器、Node、类型与构建验证另行记录。

## 生成、审查与执行

按 [Git 协作](GIT-WORKFLOW.md) 先冻结审查通过的功能树、受验构建、main／integration 同树、真实 installed 基线和精确文件增删列表。只使用新的私有目录：

```powershell
python -B deploy/expo_tv_release/prepare.py --source-root <私有access目录> --output <全新expo-tv-tools目录> --freeze <已核对freeze.json>
```

占位路径需替换为真实绝对路径。未提供 freeze 时只能生成供审查的未绑定工具，不能发布。每一轮都由非作者审查生成的 package／binder 与 7 个算子，绑定实际 SHA；现成历史审查记录不能用于新包。

本轮实际执行顺序为本机 package → 审查并绑定 → 上传 → build → Linux validate → stage → activate → post readback；post readback 须显式传入 `--reviewed-sha256` 与非作者确认的实际脚本 SHA。原件、退出码、失败记录保留，不因观察超时重复执行任何阶段。stage／activate 继续使用完整停写备份、原 55 表与注册库行／schema／序列精确保持、旧镜像和旧源码保留及新 app 启动后的保持检查。发布后的在线备份是逐库快照，不是跨库原子事务。

## 路由与验收边界

新版 `/tv` 在完整导出存在时 302 到 `/app/tv`，不转发参数；未构建时继续原电视页。`/tv?classic=1` 保留显式兼容入口。post readback 分别核对新版入口、精确跳转、经典兼容入口与 CSP；静态资源字节、未授权 API 拒绝、服务镜像／健康和新备份检查保持。

电视浏览器真实运行仍需独立验收：不得以匿名 HTML 读回证明登录、配对、照片播放或实体电视通过。本人 Google Photos 的历史成功也不能替代此次播放、私人媒体隔离、两屏控制和断网清屏测试。实体型号、遥控器、休眠与长期常亮在实际设备缺失时明确标为未验收。
