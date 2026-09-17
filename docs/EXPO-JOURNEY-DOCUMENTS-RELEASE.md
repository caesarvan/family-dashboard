# Expo 旅行资料发布候选：55 → 55

本适配器尚未用于发布。它只从已核对的九份私有原件生成未绑定的本地审查稿，不连接服务器、不运行 Docker，不执行打包、绑定或生产阶段。资料接口见 [旅行资料](JOURNEY-DOCUMENTS.md)，客户端见 [Expo 资料模型](EXPO-JOURNEY-DOCUMENTS-API.md) 和 [资料面板](EXPO-JOURNEY-DOCUMENTS.md)。

## 固定输入与保护范围

[`prepare.py`](../deploy/expo_documents_release/prepare.py) 固定 `expo-appearance-tools-20260917-r1` 的七个算子、实际 `prepare-package.py` 和 `bind-release.py`，逐份校验原字节 SHA。输入基线是 2026-09-17 16:17 已安装的成员外观版本：

- 安装 main `e5b12c33b325359dc7629e19bf8a4d0b95f9b2ca`、source `c75676222406a6845e0c8527f43ef99d0143454d`，同树 `81e170870848042bee9f6a5ad7e984d7b70fbe1c`。
- 原包 `4244790d034ae3602a6d734982165cdd7c6eb83962cdffc24a09a032ae0d2e65`；manifest `14374023ae120c9c3d6ddbe009c0f1b97a4ab845d104ce5bc7fd05b8de2cff11`。
- app／sync／media 父镜像 `sha256:6c1650d84ecfdff6f46fc9358ddd332a11b1f812a95279d5621fb63735fc447e`。web、环境、依赖及 Dockerfile 继续按既有约束保持。

仍为 55 张户内表与两张平台注册表，无 DDL 或迁移。上一版不变文件集合本来不含本轮变更的 `journey_documents.py`，因此完整保留该集合：财务、旅行工作流、媒体、备份／恢复辅助、电视入口与播放器等继续按旧包字节校验。本轮必需修改项包括资料后端、客户端类型与旅行／地图／助理／更多导航，以及日历、清单密度；必需新增项包括资料 model、Panel、资料会话与模型测试、资料浏览器脚本及本适配器。

上述必需集合只是最低依赖。最终 freeze 必须核对完整 changed／added／removed 清单、实际源码和构建输入；后续日历浏览器脚本等新增文件仍纳入完整差异，不以尚未冻结的文件名作为预设要求。

## 生成与验收边界

必需 Python 选择为八个模块：原资料、资料会话、成员会话、家庭隔离、静态托管、平台备份、55 表数据保全及本适配器。最终 `expectedTestCount` 来自冻结源码的真实 collection，收集数量不代表执行通过。Node／TypeScript 测试不能放入 Python-only 镜像。

生成的 `stage.py`、`validate.py`、`expo_contract.py` 与父原件逐字节一致，保留已使用的 896 MiB 内存／640 MiB tmpfs。activation／post 只替换本轮目录前缀，保留停写、完整备份、原 55 表与注册库行／schema／序列保持、新 app 启动核对及服务启动顺序；允许既有非空回执，不能清空重建。post 保留 `/tv` → `/app/tv` 精确跳转、classic 回退、TLS 资源和独立备份核验。发布后备份是逐库在线快照，不是跨库全局原子或再次 live 全组快照。

集成人按 [Git 工作流](GIT-WORKFLOW.md) 审查最终源码、同树 main／integration、受验构建、实际 collection 和完整差异后，在全新私有目录生成：

```powershell
python -B deploy/expo_documents_release/prepare.py --source-root <私有access绝对路径> --output <全新expo-documents-tools目录> --freeze <本轮已核对freeze.json>
```

输出须是 access 的直接子目录且不存在。无 freeze 仅生成审查稿；原件漂移、路径逃逸、覆盖旧结果、重复 JSON 键、旧父版本和遗漏必需依赖均拒绝。最终九份生成文件还须独立固定字节审查，之后由集成人另行打包、绑定、上传、构建、Linux 验证、stage、激活及读回。不能因等待超时重放阶段，不能把 READY 的零生产写入外推为激活未写入。

## 本分支实际检查

检查入口为 [`test_expo_documents_release.py`](../tests/test_expo_documents_release.py)：

- `python -B -X utf8 -m pytest tests/test_expo_documents_release.py -q -p no:cacheprovider`：最终源码实际 **20 passed，0.41 秒**。私有 `test-results/documents-release-final.xml` SHA256：`29205a4bbdb00bc9ea699f00bb10061cf1b6bd0d13f6b03bf05a5d5dd8dee370`。
- 显式运行该测试文件，传入 `--source-root <私有access>`、`--git-repo <本分支绝对路径>`、`--git-revision c0c8ba4f41a268901cf41920e6012cb3da3333c8`：核对真实九原件、旧包及 Git Dockerfile，在临时目录生成九文件；Docker 字节与关键阶段保持，运行白名单包含资料模块，**33 项非法 freeze、7 个未绑定入口**均拒绝，递归语法与无迁移检查通过。私有 `test-results/documents-release-pinned-final.json` SHA256：`ba4694c51d32468ca152e3c2b5599af2512e847389037d084fab55d9c454bf42`。

显式检查对生成代码的网络／进程调用设置失败保护，不执行生产或打包。测试中的 `9991` 仅验证合成 freeze 的数量透传，不是实际 collection。以上均为本地适配器检查，不代表客户端、Linux 新镜像、真实账号或生产发布已通过。
