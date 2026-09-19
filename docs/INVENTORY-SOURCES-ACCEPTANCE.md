# 本人订单关联库存：验收与发布记录

<a id="inventory-sources-release"></a>

**已于 2026-09-19 13:57:12（北京时间）激活，13:59:04 独立发布后只读审计通过。** 本地 API、发布工具、组合 Node 和真实浏览器分别通过；实际 Linux 候选 227/227、两户三库合成保全演练及独立审查通过。实际 stage／activate 均退出 0，生产一户两库保持 61→61／9→9。此前线上基线为[售后关联家庭待办](INVENTORY-FOLLOWUP-ACCEPTANCE.md#inventory-followup-release)，本次不代表本人真实订单或实体设备已验收。

## 用户流程与边界

从「家庭资金 → 本人账本 → 订单详情 → 登记或查看订单库存」明确选择商品，打开已有可见关联，或选择已有物品及本人登记的采购批次。本人也可选择「用此商品新建私人物品」：名称、规格仅预填为可编辑草稿，默认私密；单位和数量由本人填写，不解析数量原文或自动合并同名商品。

保存物品、保存批次和关联来源各是独立操作。预览订单行与已保存批次，再明确确认来源；取消关联保留已有物品与批次。实际到货后仍须在批次详情明确「收货」并输入数量。来源不代表已付款、退款或收到实物，不新增支出、不更改采购实付或完成状态，不将订单金额计入公共财务。

来源详情要求当前库存可见且本人是批次创建者；共享库存中的家人不能读取其私人订单来源。原订单变化显示待核对、原商品行置空，不静默把旧序号映射到新商品。原订单删除后仍可明确解除来源；解除保留关联历史、库存和实物流水，不退货或退款。未知确认结果保留原请求编号，先读取原回执，不能另建批次或另发新操作冒充恢复。返回财务保留原查询上下文并重新读取本人数据。

精确步骤见[操作与恢复](EXPO-INVENTORY-SOURCES.md)，HTTP 字段、权限及错误见[来源接口](INVENTORY-SOURCES.md)。四个来源路由由 `inventory_sources.py` 经 `inventory_api` 注册，沿用现有库存表、回执与事务，不增加 DDL。个人导出沿用现有白名单，仅给本人当前可见范围的最小来源与操作摘要；共享副本不含伙伴金融来源。整库备份另行保留完整历史。

## 已完成的本地验证

以下是不同提交与范围的独立执行，不能相加称为一次套件；真实浏览器也不能替代全部接口边界。

| 范围 | 实际结果 | 覆盖与限制 |
|---|---|---|
| API 与针对性回归 | 227/227，零失败、错误、跳过 | 来源 52、既有库存 API 68、售后 46、导出 13、淘宝分组 48；真实成员会话／CSRF、双家庭与伙伴／TV、事务内会话撤销、过期与并发、各写入点回滚、零金额和来源操作零实物增量 |
| 正式导入衔接 | 包含在上述 227 内，不另计 | 合成合并单元格 XLSX 经正式 imports/preview 与 confirm；两商品行、同文件重导幂等、关联保留、官方 PATCH／DELETE；工作表 sourceLine 不作商品身份 |
| 发布工具适配 | 102/102，零失败、错误、跳过 | 固定已安装基线、归档／运行白名单、精确 Docker COPY 变化；真实临时 Git/archive 与记录型控制器替身，不能作为真实 Linux 结果 |
| 冻结组合 Node | 26/26，零失败、取消、跳过 | 执行真实 TSX／DTO／InventoryFence；hooks、Paper 与 HTTP 为明确替身，覆盖未知结果、身份／后台清理、迟到响应和来源删除后解除 |
| 类型与 Expo 子命令 | 三个子命令均退出 0 | 完整前端 tsc、测试 tsc、Expo web export；外层 wrapper 退出 1，失败与已审恢复单列如下 |
| 真实 Edge／Flask／SQLite | 同一轮 3/3 场景通过、4 图 | 合成独立临时库及真实 HTTPS；原确认回复丢失只丢弃真实已提交响应，不伪造成功 |
| 独立视觉与证据审查 | 4/4 原图已查看，0 阻断 | 手机 390 与桌面 1280 CSS px；关键区文字、操作可见，目标稳定至少 600 ms，无目标裁切或横向溢出；不代表实体手机／电视 |

API 实际命令在 `order-inventory-api` 工作树执行：

```powershell
& 'C:\Users\caesarf\OneDrive - NVIDIA Corporation\Documents\AI\family-dashboard\.venv\Scripts\python.exe' -X utf8 -m pytest tests/test_inventory_sources.py tests/test_inventory_api.py tests/test_inventory_followup.py tests/test_inventory_portability.py tests/test_taobao_order_groups.py -q --tb=short --junitxml=test-results/inventory-sources/api-regression-r1.xml
```

组合 Node 实际命令在冻结 integration 根执行，原命令、退出码、stdout／stderr 均保留：

```powershell
& 'C:\Program Files\nodejs\node.exe' --experimental-transform-types --test frontend/tests/inventorySources.test.mjs frontend/tests/inventoryFollowup.test.mjs
```

## 受验源码与独立审查

开发基线 `b5c8169f60e3897a833a439c90c55be991add1a5`；最终受验 source／integration／浏览器 harness 为 `fe0c56ba5537e70207ae5b98213e3daa1daef95a`，tree `aefe80a65e1f41ad5c05b146d9513b529e762acc`。已合入 main `e863febba02a6a90bc4a656292152d40187240a3`，两者文件树相同。后续纯文档提交不改变已受验源码、前端导出或候选镜像身份。

API 227 实际受验 head 为 `f415edf938bb709180b855e9474fb1e8d2c65385`；最终 `d4a5ce95bd3d0a35873a9f4102e07fc273ca10c8` 仅修正文档预填说明，运行与测试 blob 相同。UI 为 `7e63ce0a1e6d7bd66e691017e4075f17d87d5fdb`；发布适配为 `982c44d09c5d0b47330f0c592096b765928b43af`；浏览器与接缝文档为 `a164ecaf00599e5af59a0182961dc216d8dca4bc`。组件分别经非作者审查，组合审查核对 26 文件 delta 与各已审作者 head 字节相同；不把作者测试重新标为在 integration 重跑。

私有证据根目录为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`，下表路径相对此根；日志、数据库和截图不入 Git。

| 原件／审查 | SHA256 |
|---|---|
| `worktrees/order-inventory-api/test-results/inventory-sources/api-regression-r1.xml` | `ec1514c284211eb9a07fbeead4adcd89f90055544fcc04b286f97bd80b9237ae` |
| `order-inventory-api-author-evidence-r1.json` | `25f79de15fba9873c37f66aed171832fbf9cea749fb21bbcbe617affe73440e3` |
| `order-inventory-api-review-r2.json` | `0dc760c1464889d1297660ccbd176bbbb2721eae661233601cc03b8860f7a8bd` |
| `order-inventory-ui-review-r1.json` | `b552ee36eb02db9bdb1ec6fc4dc582d4bc1c14144b92fe1c9d5aa9702bcd91a4` |
| `worktrees/order-inventory-release/test-results/order-inventory-release-r1.xml` | `683ce1171951b82c3723be0d810945f8e5e8c7b6794d55cb8a8368ccd9057867` |
| `order-inventory-release-review-r1.json` | `749e3e74c59be3578a201df1d316b4cb0518fa68a740a2df16ddf1ef15800daf` |
| `worktrees/integration/test-results/order-inventory-node-r1/command.json` | `9d4617c112fd57b77315f2a5ac030ec3b552ea65206d29e599033c4f2610a27b` |
| `worktrees/integration/test-results/order-inventory-node-r1/command.stdout` | `b1093c3d3e52dbd7a776d7edb837e50368580f3f27d00d322abf189930c58253` |
| `order-inventory-harness-review-r2.json` | `0d683845a0a90319eb7c43bcca7e3c4fc4245b1cb91e3102cb4e3cc576c9813c` |
| `order-inventory-combination-source-review-r2.json` | `a1f86cc4946f9876862619123004440ba40ff3c257a9a952a106b0e5e984eec9` |

## Expo 原构建失败与证据恢复

构建使用同一 `fe0c56ba` 源码，111 个完整受控前端输入，输出 `frontend/dist-order-inventory-r1` 的 23 个文件。`tsc --noEmit -p tsconfig.json`、`tsc --noEmit -p tsconfig.tests.json` 和 `expo export --platform web --output-dir dist-order-inventory-r1` 均实际退出 0。原 wrapper 在构建后的 Git 干净检查退出 1：新导出目录尚未被忽略。它不是三个构建子命令失败，也不能记成 wrapper 成功。

独立审查的恢复只增加固定导出目录的本地 Git ignore 规则，保留原失败、执行记录和 stdout／stderr；不修改 tracked 源码，不重跑子命令、不重建 bundle。恢复核对完整输入与 Git 字节相同、保留导出内容和期望标记，并生成明确的恢复记录。`originalFinalManifestUnavailable=true`：原 wrapper 已在内存枚举导出并计算 SHA，但 Git 干净检查失败后未持久化最终导出 manifest；可复核的导出 SHA 原件首次在恢复阶段保存，不能声称拥有原 wrapper 的最终 manifest 原件。

| 原件／审查 | SHA256 |
|---|---|
| `worktrees/integration/test-results/order-inventory-build-r1/failure.json` | `c650de8c78ec3a08aa007a6ff9b5f7b8620d1af97e39b4c47a50adb63fc5ec0f` |
| `worktrees/integration/test-results/order-inventory-build-r1/command-2.stdout` | `31bfca3ebbd2335550cd5174698a57df809a305f6144af40ac622d52122d075a` |
| `worktrees/integration/test-results/order-inventory-build-recovery-r1/recovery.json` | `5111f2f8a0b67d19b5d9e90eca4b5ce46f011882e58a5f4054544301c0332d60` |
| `worktrees/integration/test-results/order-inventory-build-recovery-r1/build-evidence.json` | `e681f3768bc81073de2e6214d764535c7b818665f27a30c681c7084aba3b2361` |
| `order-inventory-build-recovery-review-r1.json` | `09c1fa29cb2b7807d9d798311cf34b67def6fbebff0b41556d88c05da6e8ad05` |

## 真实浏览器三条流程

脚本 [browser_expo_inventory_sources_check.py](../tests/browser_expo_inventory_sources_check.py) 在每条流程建立独立临时数据目录、真实成员 Cookie／CSRF 和 HTTPS Flask 服务，使用真正 DPR 2 的 Edge 上下文，复用上述保留导出。每次合成合并订单 XLSX 均经过正式导入接口，含两条商品；非零财务、采购、旅行和实物哨兵参与前后比较。

| 场景 | 实际观察 |
|---|---|
| `order_stock_lifecycle` | 从本人订单明确新建私人物品；数量初始为空、本人填 6，关联前零实物流转；预览无写入，关联后仍零现有量，另一商品行未关联。再明确收货 2，得到现有 2／待收 4；返回原月份与搜索，停止并重启真实 Flask 后读回同一批次，只有一条来源和一条实物流水。 |
| `lost_source_response` | 先取得真实 confirm HTTP 200 的已提交结果，再丢弃回复；保留原 requestId 且返回入口禁用。恢复仅发原编号 GET：确认 POST 1 次、原回执 GET 1 次，真实 SQLite 核对唯一原 operation 和唯一匹配活动来源，库存／任务／审计／settings 快照及实物流水无第二次变化。 |
| `changed_source_privacy` | 共享库存仍可由伙伴管理，但其 JSON、DOM 和 aria labels 无私人订单 ID、标题、规格或数量原文，来源入口不可见；读取本人订单 404、来源 403。本人通过正式 finance PATCH 改源后为 needs_review 且 line 为 null；正式 DELETE 后 source_missing，明确预览解除保留一条 detached 历史且实物不变。撤回共享后伙伴旧详情清空，GET 为 404。 |

三条场景的金融、采购与旅行保护集合均保持，schema 和 user_version 保持；来源变化场景仅在记录的正式 PATCH／DELETE 后重新建立财务比较基线。来源关联、解除或恢复不产生实物动作；明确收货与此分开。

报告完整记录 841 个 tracked 源文件前后 SHA 与 111 个前端输入，均匹配冻结 Git blob 字节；23 个生成导出的文件集合与散列匹配恢复 manifest、浏览器执行前后记录及各临时静态副本。执行脚本副本 SHA 为 `28ccf4c2beae85aa6fc66d4847dea1ed8615e2b1b280833429f789c23e3b0768`；实际继承 fixture 的路径与散列也绑定冻结树。三个场景清理后临时目录均不存在，`pageErrors`、`externalRequests`、`scenarioFailures` 为空。浏览器只允许当前本地 origin，Python 拒绝非 loopback socket；这不是全机抓包，也不将预期的丢包与权限拒绝误写成没有任何网络错误。

原报告为 `worktrees/integration/test-results/expo-inventory-sources-20260919T051855779685Z/result.json`，SHA256 `cb5eee8b19d27d67c5a941f33d2ef811f43b05182188511ffd378efaa0f4df6a`。独立审查原报告、harness／helpers 断言和全部四张原图，记录 `order-inventory-browser-review-r1.json`，SHA256 `d70b7bc4058a40bd929e03ead9049f978215f2e203cf470873cb45b290bf7c2f`；结论为带明确覆盖限度的通过、0 阻断，没有重跑场景。临时库已清理，审查不冒充再次查询原数据库。

以下截图路径相对原报告目录；全部原图经 `view_image` 实际查看，三张手机图为 780×1688 像素／390 CSS px，桌面为 2560×2000 像素／1280 CSS px。

| 原图 | SHA256 |
|---|---|
| `order_stock_lifecycle/private-source-preview-390.png` | `5c6a3a6d1065f5bf09fd7d236260b19dc0b27fa150590e7da95021b474679106` |
| `order_stock_lifecycle/persisted-stock-batch-1280.png` | `962b1d60d35b2a04e269635e656bc5750eeacfe1462b0fc26e54cd5ed2f92687` |
| `lost_source_response/unknown-source-result-390.png` | `75b1894cd4a8a986b3d0797652831c6b53ac8fc5d24834ae02be250b3f3eaaa9` |
| `changed_source_privacy/changed-private-source-390.png` | `3a0d028dd3d034fb900234fd5d749cd9bdc40a1ff21f597daee9cf450fbcd3a5` |

手机预览／核对原操作／来源待核对卡片文字和操作可见，桌面批次现有 2／待收 4、来源入口与收货按钮可读。桌面图滚到批次区域，不是整页截图；删除来源和伙伴隐私有实际 API／DOM 断言，但没有单独保留对应状态截图。

## Linux 候选与保全演练

包 `steady-order-inventory-package-r1/` 已独立核对：863 个归档 payload 文件由 840 个选定源码和 23 个 Expo 导出组成，运行白名单 121 个文件；与浏览器完整 tracked 集合 841 的计数范围不同。`inventory_sources.py` 已进入归档、Docker COPY 和运行白名单，无 schema 变化。

| 包原件／审查 | SHA256 |
|---|---|
| `steady-order-inventory-package-r1/package.json` | `af14867bb549c64a85e39aad897ec60e7f27a76ea349c4963d68a628f65a40e5` |
| `steady-order-inventory-package-r1/release.tar.gz` | `7c17b5b080899e36c038348fa09affe59917a9a17227e0a1169b2975cd5549c8` |
| `steady-order-inventory-package-r1/release-manifest.json` | `c4d5ecc38675e6d9d97569664cb8141d4cfd030f52c6086449b8ea8d84ebf080` |
| `order-inventory-package-review-r1.json` | `790a2e61051cc9238e4fda0ad1a9dc5d48fc0e5e5cd45d1d2f2389c9a753bef8` |

候选 bootstrap／实际镜像构建均退出 0，镜像为 `sha256:32905e70879d28f36b0e584d69f03434e4a1bf38e580c0ca1aeb1ed7ae3a3cc6`；`build.json` 记录 121 个运行文件，完成时间为 2026-09-19 05:28:07 UTC。真实镜像内验证于 05:34:51 UTC（北京时间 13:34:51）完成：227/227、零失败／错误／跳过，容器和验证命令均退出 0。它与上述 Windows API 227 是不同执行，不相加为一次套件。

合成保全演练于 05:28:43 UTC 完成，实际命令退出 0：从固定父镜像建立两户三库，停写备份后启动候选真实 app，再核对各库 schema、行、序列和合成 marker 保持。户内表计数为 61／61，平台表前后为 9／9，`preservationCompared=3`。`syntheticMarkerOverride=true`、`exactProductionControllerProgram=false`；这不是生产发布或生产数据演练，不能替代实际 stage／activate 的保全证据。

成功原件已取回私有 `steady-order-inventory-linux-originals-r1/`，独立 Linux 证据审查通过；本次文档只读回原件，不重跑。关键记录：

| 原件 | SHA256 |
|---|---|
| `steady-order-inventory-linux-originals-r1/build/build.json` | `2cb399318ac011330099b2b17b22c46dcaa21c90d1f7323130b43765e27f3e1f` |
| `steady-order-inventory-linux-originals-r1/validation/validation.json` | `c21a8e73fe02027a139af58c79bb6c99faa42531fecf47595e14ebeea1d68e37` |
| `steady-order-inventory-linux-originals-r1/rehearsal/result.json` | `d64cc1007c0bed529da7a980f490d0f567d1cab8bc57c571af9f369df99e1bd7` |
| `order-inventory-linux-release-review-r1.json` | `da140d89b6634f1ebb754936d0aac17d0a33b71f1df106d2b34d77c3af671735` |

## 最终计划与发布阶段

实际候选目录为 `/opt/family-dashboard-candidates/steady-order-inventory-61-20260919-r1`。最终 plan SHA256 为 `03be6f80a01564c7770a7f55e1a4e029243f11567c47cf94495b31ddca0af721`，已通过独立审查；原计划位于私有 `order-inventory-final-plan-originals-r1/release-plan.json`。实际 stage 于 2026-09-19 05:54:40 UTC 退出 0，stage SHA256 为 `0cbe91073c7f89046330e6f195204155f33d168824e698ce2d91ed39a647c03d`。

集成人读回 stage 原件与基线后通过激活前检查，实际 activate 退出 0，于 **2026-09-19 05:57:12.305210 UTC（北京时间 13:57:12）**完成。activation SHA256 为 `753bcfd5f77157b514b2a61ccc75fb572d8fe3bd2f21314ea89cfaf8f67d068b`；实际发布目录 `/opt/family-dashboard-releases/steady-61-20260919T055542951005Z`。控制器不执行迁移，新 app 启动后的完整数据保全通过；plan、stage、activation、安装 manifest 和保全回执等允许清单中的 13 份 JSON 原件已回传至私有 `steady-order-inventory-production-audit-r1/originals/`，不包含数据库或环境密钥。

| 审查 | SHA256 |
|---|---|
| `order-inventory-final-plan-review-r1.json` | `f963300c12295a2e35159dff07cd06773e6483b06c1762ce05175b72896dc6a8` |
| `order-inventory-stage-gate-review-r1.json` | `609d9dfb2ea088346fa0357b4ea2a4113dd007b71767c4e5747281f1f15694db` |

本次固定 `followup-r1-steady` 基线与计划已消费，不可重放。下一次按[普通更新](STEADY-RELEASE.md)重新绑定实际安装身份与全库组，不重放已完成的成员迁移或任何历史发布计划。

## 独立只读发布后审计

审计观测时间为 **2026-09-19 05:59:04.739865 UTC（北京时间 13:59:04）**，单次实际命令退出 0、stderr 为空。863 个安装包文件与绑定清单匹配；app／sync／media 各 121 个运行文件匹配，四个服务 running、零重启及 OOM，app healthy。正常 TLS 读回 75 项静态资源散列匹配、16 个匿名接口返回 401；备份 timer 为 active。

实际生产为**一户两库**；本次停写阶段全量逻辑指纹前后相同，户内 61→61、平台 9→9，schema、行、序列及原成功成员迁移 marker 保持，新 app 启动保全回执已绑定。原 `.env` 与服务环境逐键映射保持，映射顺序可以变化。审计核对绑定的停写／启动证据与保留备份散列，**未读取活跃数据库，不代表再次比较当前活库的最新业务数据**；没有运行测试、触发新备份、初始化账户、修改服务或写入真实云端。

| 审计原件／审查 | SHA256 |
|---|---|
| `steady-order-inventory-production-audit-r1/command.json` | `90fbaad38d7f22c7f72b8dc5a6035d58fdd42ee6c38d1a75c3ed19860a9d496c` |
| `steady-order-inventory-production-audit-r1/stdout.json` | `304f6f10cd040f20e16b5ce63c4e082e93632e2b8bb0e1e3cca9b2755823e003` |
| `steady-order-inventory-production-readonly-review-r1.json` | `feee58ab01565aa0ed061edf013d46f7414b369e7b36b811ae849f27a18c2625` |

## 仍未验收的范围

本人实际订单样本、真实库存操作、真实云端写入及实体手机体验未在本批合成验证中验收。实体电视暂不可用，保留待验；桌面仿真不替代实体设备。原生安装、完整跨浏览器矩阵和长期使用也未由这三条场景证明。

本增量补齐本人导入订单与库存采购批次的显式来源关联，不代表全部家庭中枢功能或完整目标场景 A–D 已验收。真实采购实物、财务记录和售后家庭任务仍须分别明确处理。
