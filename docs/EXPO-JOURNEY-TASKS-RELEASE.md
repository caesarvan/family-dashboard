# 旅行待办同步：UI 发布适配

本文说明候选发布工具，**不表示本批已打包、在 Linux 验证或上线**。产品操作见[旅行待办同步](EXPO-JOURNEY-TASKS.md)，浏览器验收见[浏览器检查](EXPO-JOURNEY-TASKS-BROWSER.md)。Git 提交、构建、模拟提供方与真实云端验收分别记录。

## 固定基线与变化范围

本入口只接受已安装的旅行准备/采购版本作为父版本：source `882dce5d0bc7bba182d4fe4ba1175c040123e6fd`、image `sha256:dc5ecb91f25017a19a7e59a992e94d8d281a7e68f1e97e0ca0b5dfeaf2872bd6`、manifest `47dec854a77262458bc74573f0b36083c856b772c940587d8d1644d44e032b70`；基线独立生产只读审计 SHA 为 `4ad1226c392ab0d371df7f1ca36331c03da52e00815c2bd06aacb992a49580d7`。

家庭库保持 69 表、平台库保持 9 表。固定的 104 个非 Expo 运行文件包括 50 个根目录 Python、53 个旧静态资源和 requirements.txt。它们的名称与 hash 映射经 `membership_release_package.encoded` 序列化后，必须匹配 `70b5a4fd7ad2fe27237d27013b32912c4bd2d58408ec210539b0bcc9713afc02`；任何修改、增删或改名都不能作为本批 UI 包通过。Dockerfile、Compose、Nginx、依赖、env 和 membership marker 保持固定。

## 工具入口与复用

| 文件 | 职责 |
| --- | --- |
| `deploy/build_expo_trip_task_publish_release.py` | 固定 profile；`prepare`、`verify`、`build`、`validate`、`assemble` 转发给现有打包、Linux 构建与验收、plan assembler |
| `deploy/activate_expo_trip_task_publish_release.py` | 新的 plan kind 和 release prefix；继承已审 69/9 controller，只替换固定 SPEC |
| `deploy/membership_release_package.py` | 本批 profile 注册、taskPublish 输入白名单及 104 文件映射校验；原默认与旧 profile 保持 |
| `tests/test_expo_trip_task_publish_release.py` | 临时 Git/包原件、拒绝漂移、离线 plan 和记录式 controller 检查；不调用 Docker/网络 |

构建须提供 clean detached commit、全量前端输入 hash、真实退出码与导出 hash。后续只增加 deploy/tests/docs 时，现有打包器允许 `sourceHead` 与 `buildSourceHead` 不同，但必须确认两份 Git 提交的全部前端输入集合及字节完全一致。只要前端输入改变，就不能沿用旧导出。

Linux image 仍由当前固定父镜像增加现有 cleanup + COPY 两层，核对父配置和完整运行文件。`validate` 需要真实收集后冻结的 selection 和独立测试依赖；不继承其他批次的通过数量。使用 `--help` 查看每个入口的必需参数；候选路径、head 和 SHA 必须来自本批实际原件，不提供可误用的旧生产执行命令。

`assemble` 必须产生全新独立目录，绑定本批 package、image、selection、测试和审查原件。非作者审查通过后，集成人才可 stage/activate。不能重放旧 candidate、plan 或已经消费的激活记录。

数据层继续使用未经修改的 `assistant_trip_items_release_data`：全库 stopped backup → 真实候选 app 启动 → 停机核对完整 69/9 logical fingerprint → 启动服务和备份 timer。它的 attempt kind 仍为 `assistant-trip-items-release-attempt`，但强绑定本批新 plan SHA、source identity、before fingerprint 和 marker；没有迁移、warm callback 或自动 restore。旧 43/43 static-only 入口不适用于本批。

## 验证边界

本机定向测试证明打包边界和记录式调用顺序；测试内的临时 plan 不属于生产计划，记录式控制器不证明真实 Docker 或真实库保全。候选还需要本批 Expo/browser 结果、实际 Linux image/validation、发布回执和独立只读读回。模拟提供方不证明真实 Microsoft To Do / Google Tasks 写入，实体电视及本人完整场景另验。

本次本机检查覆盖新入口及既有 trip-items 发布测试，共 48 个唯一用例。首轮 40 项通过、8 项因 Windows 临时路径过长（WinError 206）失败；保持代码不变，改用短临时目录后只重跑失败的 8 项，全部通过。首轮失败与重跑原件均保留，不将两轮重复用例累加为新覆盖。打包/策略测试需要本机 Git；Linux 验收可使用已冻结的待办 API 用例，不为本批额外安装 Git 或修改镜像依赖。
