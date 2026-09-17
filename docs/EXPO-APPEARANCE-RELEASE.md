# Expo 成员外观发布：55 → 55

本适配器已用于 2026-09-17 16:17 成员外观发布，完整运行身份、原件与边界见 [本轮验收](EXPO-APPEARANCE-ACCEPTANCE.md#expo-appearance-release)。生成器本身只生成未绑定的本地审查稿，不连接服务器、不运行 Docker；审查后的打包、绑定与服务器阶段由集成人另行执行。此次固定绑定已使用，不能重放。外观实现见 [样式与密度](EXPO-APPEARANCE-STYLE.md)，成员事务与 CAS 见 [偏好 API](MEMBER-PREFERENCES-API.md)。

## 本次使用的历史输入与边界

[`prepare.py`](../deploy/expo_appearance_release/prepare.py) 固定私有 `expo-home-layout-tools-20260917-r1` 的七个算子、实际 `prepare-package.py` 和 `bind-release.py`，逐份校验九个原件 SHA。本次输入基线为当时已安装的 2026-09-17 14:56 首页布局版本；当前已升级，不能重放本次或更早的绑定：

- 安装 main `609a51afde8b6f8aa1f817fa5d2471a7a8b939ff`，source `cac7f78a1e4148b9c4d44164d3d6fbd74aa57234`，同树 `d22f6d4ee78dcc83501d4c478b97b4cfa506d1bc`。
- 源码包 `5b3ecfca687de81e9243e1a5472a4a1a3ebf3dd75a9c055a56f71cc926df39d3`；manifest `b1b6d2783ef69dbb18be23fc7841194306448ebc1921086fb22dd4d4f6a1b9dd`。
- app／sync／media 父镜像 `sha256:ac795a38f4da34b6b9c9be6e47d125a160d870eb3eb4a594fb1e64c56319ee17`。web、环境、依赖和 Dockerfile 保持原字节／身份约束。

仍是 55 张业务表与两张平台注册表，无 DDL 或迁移。仅将本轮确需改动的 `household_spaces.py`、成员根布局 `_layout.tsx` 移出上一版不变文件集合；未改的 `dashboard_preferences.py` 加入该集合。电视入口、controller、Board、照片播放器，以及财务、旅行、媒体等既有服务保留原字节约束。

必需修改项包含偏好 API、成员主题／provider／首页与账户资金屏幕、经典 `static/product-shell.js` 客户端及 API／界面说明；必需新增项包含 Preferences helper、AppearancePanel、主题和偏好模型测试、实际浏览器验收脚本及本适配器。最终 freeze 仍须记录完整的 changed／added／removed 清单，并与旧包和最终 Git 源逐项核对，必需集合不是完整改动清单的替代。

## 验证选择与生成流程

Linux 选择九个 Python 模块：成员偏好、成员会话、家庭隔离、首页布局、布局会话、静态托管、平台备份、55 表数据保持和本适配器。偏好专项已包含真实电视拒绝与设备／布局数据保持；未复跑无关的历史全套。`expectedTestCount` 等最终冻结源码实际 collection 得出；collection 不是执行通过。Node／TypeScript 桥接测试仍禁止放入 Python-only 镜像。

生成的 `stage.py`、`validate.py`、`expo_contract.py` 与固定首页布局原件逐字节相同，验证资源保持 896 MiB 内存／640 MiB tmpfs。activation／post 只改变本轮目录前缀；保留停写、完整备份、原 55 表与注册库行／schema／序列保持、新 app 启动核对、worker／web 启动顺序及独立备份读回。已有回执可以非空，不清空或重建。post 保留 `/tv` → `/app/tv` 精确跳转及 `/tv?classic=1` 回退验证。

按 [Git 工作流](GIT-WORKFLOW.md) 冻结并审查最终源码、受验构建、同树 main／integration、实际 collection 与完整差异后，集成人使用新的私有目录：

```powershell
python -B deploy/expo_appearance_release/prepare.py --source-root <私有access绝对路径> --output <全新expo-appearance-tools目录> --freeze <本轮已核对freeze.json>
```

输出必须是 access 的直接子目录且尚不存在。原件变化、路径逃逸、覆盖旧结果、重复 JSON 键、旧父版本、遗漏必需文件或测试均拒绝。无 freeze 只能生成审查稿；不得据此绑定或执行发布。最终九份生成文件还须非作者固定字节审查，之后由集成人另行打包、绑定、上传、构建、Linux 验证、stage、激活与读回。不得因等待超时重放阶段，也不能把 READY 的 `productionWrites: 0` 当作整个发布的结论。

## 本分支实际验证

检查入口为 [`test_expo_appearance_release.py`](../tests/test_expo_appearance_release.py)：

- `python -B -X utf8 -m pytest tests/test_expo_appearance_release.py -q -p no:cacheprovider`：实际 **20 项通过**。私有 `test-results/appearance-release-r1.xml` SHA256：`d030e86d98d9574352d3c926d72c10231c7ebb23091d8efd2874bcb585cce17d`。
- 显式以私有九原件、真实已安装 archive 和本分支 base `5a963e1f1d0fa192249ee01d1a63b08072d145e1` Git Dockerfile 运行本地检查：临时目录生成九文件、Docker 字节相同、43 项非法 freeze 拒绝、七个未绑定入口拒绝、递归语法与无迁移检查通过；测试阶段阻断生成代码的一切网络／进程调用。私有 `test-results/appearance-release-pinned-r1.json` SHA256：`8ba16b5768dbb3dc48c5df1575e7f3e64eb8b27da5f8a84c21fe0a319e466d9e`。

上述两类检查发生在本地适配器阶段，当时未执行生产操作。后续独立审查、正式打包／绑定／上传，以及 build、validate、stage、activate、post_readback 五阶段均一次退出 0。Linux 实际 226 通过、唯一精确 Windows junction 跳过，正式 55→55 保全与 TLS 读回见 [本轮验收](EXPO-APPEARANCE-ACCEPTANCE.md#expo-appearance-release)，不将分段数量相加。实体电视、真实云和本人公网新流程仍未验收；发布后备份为逐库在线快照，不是跨库全局原子或再次 live 全组快照。
