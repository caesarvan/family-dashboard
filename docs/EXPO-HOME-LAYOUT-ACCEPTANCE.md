# Expo 首页布局验收

<a id="expo-home-layout-release"></a>
## 当前状态与源码身份

**2026-09-17 14:56:51（北京时间）实际激活，14:57:27 正常 TLS 读回通过。** 以下分别记录源码、实际构建、本地浏览器、新镜像 Linux 与生产证据；文档提交不改变本次运行包。

| 身份 | 值 |
| --- | --- |
| 已审 main | `609a51afde8b6f8aa1f817fa5d2471a7a8b939ff` |
| 正式 integration／安装 source | `cac7f78a1e4148b9c4d44164d3d6fbd74aa57234` |
| 两者同树 | `d22f6d4ee78dcc83501d4c478b97b4cfa506d1bc` |
| 实际 R2 浏览器／构建 source | `0438ee9fa82c1dc4f83958aa983682234e9f8202` |
| R2 浏览器／构建 tree | `c8aa76c2e66de7cafdf122b134021bd3428dbcb9` |
| 此前安装版本 | [14:19 Expo 电视展示](EXPO-TV-ACCEPTANCE.md#expo-tv-release) |

浏览器执行身份与正式集成身份分别记录；实际发布包的 168 个构建输入、23 个导出文件已逐字节匹配受验 R2，沿用该浏览器证据，不伪称在正式 main 上重新执行过浏览器。使用和 API 见 [首页布局](EXPO-HOME-LAYOUT.md)，固定 55→55 发布流程见 [发布说明](EXPO-HOME-LAYOUT-RELEASE.md)。

## 实际本地验证

- 后端候选 `348827076efe76d636e45c3df94f947410355961`：30 项新会话测试加 17 项已有布局测试，实际 **47 通过、0 失败／错误／跳过**。覆盖真实 SQLite 锁等待、撤权、读取快照、提交前失效、成员／家庭隔离、CAS 和未来卡片保全。增强前基线记录中的 4 个失败保留。
- UI 候选 `85a83a3c881b45d26be475f42186dee2e13bc99d`：`tests/test_expo_home_layout.mjs` 实际 **12 项通过**，包括前置核验失败时写回调执行零次、后置核验错误不能当确定拒绝、迟到响应失效、无自动重发，以及旧布局轮询不能覆盖新保存／其他身份不能安装布局。此前 11 项记录保留，不重复累加。
- R1 组合在 `f6a974361ea4ee13e4aa83877184eb3ecdeed0f8` 实际完成全项目 `npm run typecheck` 和 `npm run build:web`，均退出 0；此前定向检查的两个泛型错误及修订原件保留。随后仅修订测试脚本，R2 再次实际构建；没有重绑 R1 元数据，也没有把类型检查记为再次运行。

R2 受验源码为 `0438ee9fa82c1dc4f83958aa983682234e9f8202`，tree `c8aa76c2e66de7cafdf122b134021bd3428dbcb9`；构建原件位于私有 `expo-home-layout-build-20260917-r2/`。真实临时 Flask／SQLite／Edge **9 条流程全部通过**：键盘与四宽编辑、排序／隐藏／恢复默认及重载、成员／家庭与电视设置隔离、未来卡片保全、真实 409 草稿核对、已提交丢响应后只读恢复、请求前离线及前置身份失败、后台迟到响应与同身份恢复、真实成员切换后的迟到隔离。保存后释放旧布局响应也不能回退首页；未知结果核对不自动重发 PUT，脏草稿与未知结果均保留导航保护。

执行前后 **555 个源码文件、23 个导出文件**散列一致；`temporaryFixtureRemoved=true`，零页面异常、零外网请求、零生产写入。320／390／1280／1920 宽度的编辑与保存后首页，加一张 320 键盘焦点图，共 **9 张截图均已实际查看**，所见区域无阻断。320 编辑页需内部滚动；截图仅代表当前可见区域，不覆盖全部内滚动内容。

R1 保留 **5/9 流程后失败**的原件：测试精确匹配「添加待办」未包含实际可访问名称中的图标，随后临时 SQLite 句柄未关闭导致清理失败，`temporaryFixtureRemoved=false`。测试提交 `e614257d368c6787d7132988bbbbb2674b786f8f` 仅改为末尾名称匹配并断言唯一，以及显式提交／关闭合成数据库；R2 重新执行通过。R1 遗留目录后续清理被自动审批拒绝，原失败及清理记录未覆盖；不把 R1 与 R2 计数相加。

以上是不同命令的证据，不相加成一次完整验收。私有原件位于 `family-dashboard-access/` 下的构建目录或 `worktrees/` 内各任务的 `test-results/`，不纳入 Git：

| 原件 | SHA256 |
| --- | --- |
| `expo-home-layout-api/test-results/layout-session-r2.xml` | `6f5fe0228f00bd74e6c876faaa4d2bfbadcfd741ca7c0ded8d47016da3aca818` |
| `expo-home-layout-ui/test-results/home-layout-node-r3.txt` | `08e29d1694f3843c273d35e9701cf08413d2d69b69bf12237e35b538a41c2239` |
| `expo-home-layout-ui/test-results/home-layout-typecheck-r3.json` | `60ff59d1ce0d556ec578cc81d7ccf18d1bf64d46148974eaa7584e8ec880bad2` |
| `expo-home-layout-build-20260917-r1/typecheck.log` | `5d94d62f27508ab5e111675b208ec464836bd1e95aee7ec9c4d2a67a7e265e89` |
| `expo-home-layout-build-20260917-r2/build-evidence.json` | `3273bd1d628f33946f28dec5ea6d3de1074354ab4daf9ddc4e93c4f7346716a3` |
| `expo-home-layout-tests/test-results/expo-home-layout-20260917T061514265342Z/result.json`（R1 失败） | `de60473a2397bc10f6eaf3a4fcdb197582df1b80969f82f86b64dc0bcbee9285` |
| `expo-home-layout-tests/test-results/expo-home-layout-20260917T062646115230Z/result.json`（R2） | `bbf38788e0ad863e37604baf3a99979bb0c5d6ec43c38296d53ffe7f0a3fc34c` |
| 同一 R2 目录的 `visual-review.json` | `0e4a1e4945118bb1833e10ac724f27b48d0acd1a132eccc248ddf40cda189a70` |

以上本地验证使用虚构家庭、真实本地成员／电视会话，不涉及真实云或 AI；本人实际设备、实体电视和原生安装包没有本轮验收证据，首页布局功能也不代表电视布局需要随之改变。
后续合并与发布继续遵循 [Git 协作约定](GIT-WORKFLOW.md)，不能把候选提交写成已上线。

## 发布工具与服务器验证边界

本轮发布适配器在本地实际 **20 项合成检查通过，零失败／错误／跳过**；另外对九份固定私有原件和已安装 TV 源码包进行字节及拒绝路径检查。它们证明本地生成与保护条件，不代表已经运行服务器阶段。

服务器验证清单已实际收集为 **8 模块、189 个唯一测试**；collection 来自 `b7c3d1d36ae05b8e9bc821e1d2338a5cd60a1b6b`，记录 `collectedOnly=true`、`executed=false`。collection 本身不是通过证明。随后新镜像实际 **188 通过、1 个精确 Windows 跳过、零失败／错误**；跳过身份为 `tests.test_frontend_runtime::test_windows_junction_rejected`，原因 `Windows junction semantics`，运行文件验证前后均通过。不与包含其中的 47 项 API、20 项发布工具或独立 12 项 Node、9 条浏览器流程相加。

| 私有原件（根目录同上） | SHA256 |
| --- | --- |
| `worktrees/expo-home-layout-release/test-results/home-layout-release-unit-r2.xml` | `717f8a6fc4d437ebe5beaaa6715d4c91347beedbf2d70bc9a5977702197e2383` |
| `worktrees/expo-home-layout-release/test-results/home-layout-release-private-r2.json` | `6c8e74bed7eab7e007073d03d2ba0c58a963e7eb12eec0cbec345e275cfed10b` |
| `expo-home-layout-validation-20260917-r1/collection.json` | `69d65438430b22a724bd78ded96e5ea862a47a53fe1945bb80ec26400f90b6e1` |

## 实际发布与读回

| 发布身份 | 实际值 |
| --- | --- |
| 运行 app／sync／media 镜像 | `sha256:ac795a38f4da34b6b9c9be6e47d125a160d870eb3eb4a594fb1e64c56319ee17` |
| 源码归档 | `5b3ecfca687de81e9243e1a5472a4a1a3ebf3dd75a9c055a56f71cc926df39d3` |
| manifest | `b1b6d2783ef69dbb18be23fc7841194306448ebc1921086fb22dd4d4f6a1b9dd` |
| 发布目录 | `/opt/family-dashboard-releases/expo-home-layout-55-20260917T065555104063Z` |
| 正式包 | 558 个源码文件与 23 个导出，共 581 个文件；相对此前实际包 14 改／11 增／1 删 |
| freeze | `cfff04d7aaa9c83a37a2a8e831257a03bb20765f4f87a92a60c617c7830c1dd8` |
| 9 文件独立审查／7 算子 review | `cfa8483c8bd756afaae5848f23339093f2e4a2fa36789649d6ff5dc68f4e7466` |
| 实际 binding | `91bcb2a199a960017c82d381732b6561fa338ef7850d5747bc9e68dbab7d2258` |

本轮不新增路由、依赖或表，不修改电视根路由与播放器。实际 **55→55、1 户两库停写备份**；全部旧 55 表和注册库的行／schema／序列在新 app 启动核对时保持，`allExistingDataPreservedAtAppStartup=true`。这是真实激活与服务更新，不能将构建／验证阶段的零生产操作字段扩大为整次发布未写入生产。

14:57:27 读回核对 **581 个包文件、114 个运行文件、75 项 HTTPS 静态资源**，24 个内部生成路径及 1 个退役资源拒绝；25 个唯一匿名 API 均为 401。Expo TV 正常跳转与 classic 入口保持；四服务运行、零重启，app healthy，环境保持。这里只读匿名入口，不代表本人线上登录或真实云验收。

新一次备份 service 成功、timer active；该次完整 1 户两库的散列、注册组及 55 表结构核验通过。`liveGroupSnapshotRechecked=false`：这是每库独立的在线备份，不是跨库全局原子事务或再读 live 全组快照；启动时的数据保持由激活 proof 单独证明。

独立审查者只读取回 13 份服务器原件，远端与本地散列一致，phase／proof／runtime 链通过；激活 `before` 与 `after-app` 快照逐字节相同，未下载数据库备份、未重放发布操作。阶段 stdout 保留在私有 `expo-home-layout-tools-20260917-r1/`；独立取证目录为 `expo-home-layout-published-audit-20260917T065822240445Z/`：

| 独立取证原件 | SHA256 |
| --- | --- |
| `readback.json` | `f66f3cd0555ff7bb1f145aa9578025a4952d579e35aed1a9e4b275a6ece48608` |
| `audit.json`（PASS） | `22c36ab958890df1986272d624152c629804db8271c63b00eeb8ecfb489ef201` |
| `activation.json` | `f2d03c6a53fb4e09895f73a747cb73c8a300760b887b5e5633c4ec36d6ece3bd` |
| `post-readback.json` | `2c8275c8b98ab10e3991c83d6afaabbd5bdfa192fdb818db5f6f59037dffbc11` |
| `validation/results.xml` | `bcedb29634a9c56623b38f8e731ff95a3ae225efb7d7dc50d9a8f81f191cbb6a` |

本人真实云、原生安装包和实体电视没有本轮验收证据；用户目前没有可供测试的实体电视。首页布局仅改变本人手机／电脑卡片的顺序与显示，不修改记录权限或每台电视布局。
