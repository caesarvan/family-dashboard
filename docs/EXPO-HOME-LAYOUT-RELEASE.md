# Expo 首页布局发布：55 → 55 候选

本适配器仅准备首页卡片布局增量，**尚未部署**。功能与本地浏览器证据另见 [首页布局](EXPO-HOME-LAYOUT.md)；本页不把工具生成、源码合入或临时浏览器结果当作生产发布。

## 固定基线与范围

[`prepare.py`](../deploy/expo_home_layout_release/prepare.py) 校验私有 `expo-tv-tools-20260917-r1` 的 7 个算子、`prepare-package.py` 和 `bind-release.py` 共 9 份原件 SHA，再生成独占新目录。它不连接服务器、不执行 Docker、不修改数据库，也不复制旧绑定。

- 已安装 TV 源码包：`857e571d816ec05f1a3df9575f7982fb8756e8b8a2faba7c47c82b022efc127a`。
- 已安装 manifest：`ca1e82499be5548e0cd59aa0d83be4296a5fde3c123274f3062190ff8bf3aa30`。
- app／sync／media 镜像：`sha256:15f5e99ade61c694583137c88033ef6082bafc26ab06c3aa5921342bdfc62191`。
- 保持 55 张业务表、2 张平台注册表，无迁移；web、环境、依赖和 Dockerfile 不变。

本轮允许 `dashboard_preferences.py` 的布局会话核验修改，以及首页编辑面板、provider 和导航接线。该后端文件不在祖先 `UNCHANGED` 集合内，现明确列为必需修改项。已发布 TV 的根布局、入口、controller、Board、Player 及服务端模块保持字节相同；财务、旅行和照片等既有服务也保留原不变约束。

Linux 验证选择布局、布局会话、成员会话、家庭隔离、静态托管、平台备份、55 表保持和本适配器共 8 个 Python 模块。最终精确数量必须来自组合源码的实际 collection，不能把先前功能累计计数当成本轮通过数。Node、类型检查和浏览器独立记录；含 Node 依赖的 Python 测试继续禁止放入 Python-only 镜像。

## 本地生成与独立审查

先按 [Git 协作](GIT-WORKFLOW.md) 冻结已审查源码、受验导出、main／integration 同树、实际基线和精确增删列表，再使用新的私有目录：

```powershell
python -B deploy/expo_home_layout_release/prepare.py --source-root <私有access绝对路径> --output <全新expo-home-layout-tools目录> --freeze <已核对freeze.json>
```

无 freeze 时只可生成未绑定审查稿，不能执行发布。目录必须是 access 的直接子目录且尚不存在；路径、原件、重复 JSON 键、测试范围和字节变化均拒绝。生成后由非作者审查 package、binder 和 7 个算子的确切 SHA，才可绑定本轮实际 freeze。旧批准和绑定不能重放。

`stage.py`、`validate.py`、`expo_contract.py` 与固定 TV 原件逐字节相同；验证资源保留 896 MiB 内存、640 MiB tmpfs。activation／post 仅改变本轮发布目录前缀，原本完整停写备份、旧 55 表与注册库行／schema／序列保持、新 app 启动后核对和新一次备份检查保留。已有操作回执允许非空，不清空或重建。内存参考 schema 校验保留，禁止对生产执行迁移或 DDL。

发布仍由集成人顺序执行本机打包、审查绑定、上传、build、Linux validate、stage、activate、post readback；本适配器任务没有执行这些阶段。保留失败原件，不因等待超时重复阶段。activation 不继承 READY 的 `productionWrites: 0` 作为整个发布结论。

## 已做检查与边界

本适配器的 20 项合成检查通过，覆盖精确原件、路径／覆盖／输入变化拒绝、非法 freeze、递归生成代码的迁移／DDL 禁止及 Docker 字节保持。另以私有九原件和真实已安装源码包运行显式本地检查：在临时目录生成工具，核对旧包与本分支 Git Dockerfile 完全相同、未改算子字节、TV 路由读回检查、测试范围拒绝与 freeze 数量传递；禁用进程／网络后验证七个未绑定入口拒绝。没有创建最终发布包、绑定或生产动作。

检查入口：[`test_expo_home_layout_release.py`](../tests/test_expo_home_layout_release.py)。合成检查和私有原件检查分开报告，不相加为 Linux 全套。最终生成算子仍须再次独立审查，实际 Linux 和生产激活／读回尚待完成。

post 保留 `/tv` 到 `/app/tv` 的精确跳转、`/tv?classic=1` 兼容入口、静态资源、匿名 API、四服务和环境保持检查。发布后备份属于逐库在线备份，非跨库全局原子快照；匿名入口读回不证明真实账号、实体电视或完整播放体验通过。
