# 采购日期与优先级：使用与集中验收

<a id="shopping-schedule-release"></a>
## 本批状态

代码已通过独立审查，经 [PR #7](https://github.com/caesarvan/family-dashboard/pull/7) 合入 main `efa6e41c786215b4ea3dde509e01ab6c8af9c5cf`；正式包仍绑定源码 `67e5b0d5cafd28b50abce7e42fd64f64c8059997`。本地组合、正式 Expo 构建、真实临时浏览器、一次真实模型请求及实际隔离 Linux 验证分别通过。**2026-09-20 03:54:39（北京时间）实际激活成功，03:55:48 独立生产只读审计通过。** Git 合并、离线计划组装、激活和独立审计分别记录。

本批支持采购截止日期、低／普通／高优先级、旅行采购草案与明确选择的截止联动。保持家庭库 69／平台库 9 表，无 DDL 或旧数据回填，不自动改真实采购、财务、库存、订单或云端清单。资料搜索及另一个分支的共享 HelperText 修复不在本批包中。

## 最短使用路径

1. **直接安排采购**：「采购 → 新增或编辑」，填写可选截止日期、三级优先级、预算和负责人，明确保存。日期留空表示不设截止；默认普通。清单先显示未完成项，再按最近截止、同日优先级排序；无日期排在有日期之后，条件相同保留原次序。未完成项显示今天截止／逾期，完成项不标逾期。
2. **从旅行需求生成草案**：「更多 → 家庭助理」，先填写旅行名称、出发／返程日期和目的地，再附采购行，例如下方完整输入。点击「整理并预览」→ 核对人员及草案 →「核对并继续编辑」→「预览变更」→「确认保存旅行」。可不使用模型；选择模型也不能跳过本人确认。孤立的采购行会进入普通清单整理，不能当作完整旅行输入。
3. **调整已有旅行**：「旅行 → 原旅行 → 调整日期」，采购默认不勾选。仅未完成、有日期且由本地管理的采购可移动；明确选中后，核对前后日期再确认。未选、完成、无日期或云来源采购保持原日期，并显示原因；预算、优先级、图片、负责人和原实体关联保持。

旅行输入例子与[已验证的浏览器输入格式](../tests/browser_expo_shopping_schedule_check.py)一致；请替换为自己的行程并核对：

```text
旅行名称：冰岛旅行
出发日期：2027-10-01
返程日期：2027-10-07
旅行类型：境外
总预算：20000元
冰岛/雷克雅未克 2027-10-01 至 2027-10-07
采购：转换插头 | 负责人：我 | 数量：2件 | 预算：100元 | 截止：出发前3天 | 优先级：高
```

相对天数只在当前草案按出发日换算为绝对日期，保存后没有隐含的自动平移规则。有效截止允许晚于返程，预览会提示核对。付款、收货或生日日期不直接成为采购截止；模糊或跨事项语句保留原文，需本人补充。

编辑时以当前采购实体为准：已清空的截止和已降为普通的优先级不会从旧旅行计划恢复。旧客户端省略字段会保留当前值；显式 `due: ""` 清空日期，`priority: "normal"` 降回普通。旧记录读取不写库，日期限 2000—2100 年有效 `YYYY-MM-DD`。

保存结果不明时，普通采购先关闭并刷新核对，不连续重发新增；旅行保存和改期沿原操作编号核对回执，重复确认不会再次平移。版本冲突保留草稿，读取最新后重新预览。日期／优先级不是下单、付款、收货或外部同步状态。

## 已完成的分段验证

各行是独立证据，存在覆盖重叠，不能相加为一次全量测试或本人完整验收。

| 层次 | 实际结果 | 证明范围与限制 |
| --- | --- | --- |
| 本地组合后端 | 229／229，0 失败、错误、跳过 | 采购、改期和助理事项三个模块；真实临时 Flask／SQLite，合成数据。该 229 个 nodeid 全部包含在后续 Linux 298 项中。 |
| 正式 R3 Expo 构建 | 两组 TypeScript 退出 0；106／106 Node；23 份导出 | 独立 npm 依赖，129 个构建输入及 5 个附加测试输入前后哈希核对。Node 组件使用合成宿主，不替代浏览器。 |
| R3 临时真实浏览器 | 4／4 流程，390／1280 宽各 4 图，共 8 图 | 普通采购、助理本地草案保存、仅所选采购改期、离线草稿恢复；真实临时 HTTPS／Flask／SQLite／Edge。原始响应及持久化数据另核对，pageErrors、外部请求及意外 provider 调用均为 0。 |
| 真实模型 | 1 次合成输入请求；29 条检查记录通过 | `us/azure/openai/gpt-4o-mini`；包含 28 个唯一检查名，重复成员登录不算新场景。覆盖整理、预览、明确保存、原回执重放及临时应用重建；只比较指定 8 张业务表，不能称为全库保全、模型准确率或真实家庭验收。 |
| 实际隔离 Linux | 298／298，0 失败、错误、跳过 | 7 个指定模块，同一 selection／JUnit／分阶段原件绑定；980 源文件、127 运行文件前后与包一致。容器无网络、只读根、非特权用户、无生产挂载，未调用真实提供方。 |
| 发布适配器 | R2 47／47，R3 修订单项 1／1 | R2 含本批 42 项和旧 profile 相邻 5 项；R3 单项移除测试对 Git 历史的依赖，其余实现／fixture 不变。记录式生命周期验证不冒充实际生产演练。 |

浏览器 R2 的 3／4 结果保留：优先级视觉状态正确但未暴露 `aria-checked`，第四项在离线步骤之前失败。采用现有 SelectionRow 修复后，R3 新导出用原四场景断言完成复验；旧失败没有改写成通过。发布适配器 R1 的 47 个短临时目录 setup 错误及后续通过原件也保留，不重复计数。

**已知 UI 限制：** 390px 离线表单的 HelperText 在“核对后再”处截断；“结果未知”、关闭／刷新核对的提示和明确核对按钮仍可见，保存已禁用。该视口无横向溢出不代表所有错误文字完整可见。共享 HelperText 的独立修复尚未随本包发布；不以本次截图推断真实手机、屏幕阅读器或全部视口已通过。

## 固定包与计划身份

| 项目 | 固定值 |
| --- | --- |
| Source | `67e5b0d5cafd28b50abce7e42fd64f64c8059997` |
| Source tree | `3ee7134cca45d1fe6d2227b11c921fdd5833243c` |
| Expo 构建源码 | `85b3f8fa581e3d5375390343fbe6d00a761fedad`；其全部前端输入与最终包一致 |
| Package SHA256 | `6bf6c8cf7994899c7deadd9ec25cb8c4cc8a57596e5591ede663ec9bc389c447` |
| Manifest SHA256 | `6d8324ff8a8f071c7bb0160b081f9a5b503da9070e649ef8956a034e94d3ee5c` |
| Archive SHA256 | `fe5ca8ad4493352639b1c9620a5dc38b785032d915c5e78bced791dca47ae350` |
| Image | `sha256:086e40df931f84ceef7d3fba3684bc08444e364d311f22e59ad01a372a560916` |
| Linux build SHA256 | `dc76fa93f6d87f066f0dff5d57b46d20128b492e7fe0bfd359f8ed3deb3edfb1` |
| Linux validation SHA256 | `73cec0ddc48c039713584e3ebaa6bd233d630ac7eddce1e7f80827bc0cc01007` |
| Linux selection SHA256 | `8ad6e38d4edfb99a0dc0e97d1f2f9f6938ac65ac40eee7db5dc8dd19e43e8a03` |
| Linux JUnit SHA256 | `f32c426bce624bcded07898767467bf9d133f6aabcf7baffa7acfd2f3cfb76ec` |
| 16 份审查索引 SHA256 | `496f00b9edcb8af01d93839a0c32f996fc9dd01c5fb89637f49ecbc58cab077e` |
| 审查文件哈希索引 SHA256 | `ab9fa85d7bb3ecac3064d92983e89ea609a654ceec2b7f90586efebb3a38c19d` |
| 离线计划 SHA256 | `30d163a5eca484b1028b9522f198a01fd300cc04e9a22385d251ce25fa2a5775` |
| Candidate | `/opt/family-dashboard-candidates/shopping-schedule-69-20260920-r1` |
| Release directory | `/opt/family-dashboard-releases/shopping-schedule-69-20260919T195306926814Z` |
| Stage receipt SHA256 | `98ca4c7fbf7c35d23cd2babe499934493c3dc2a6e9842e28ef0c6b6d63e41ec4` |
| Activation receipt SHA256 | `7c3a4b41b34102bd111d2feb2d168211d07fa3353740034f9d97d5a3b6ae76ed` |

此后纯文档提交不改变运行包身份。父版及 104 个非 Expo 运行文件中的 99 项保留约束、25 个 operator、停止／备份／核对顺序见[发布入口](SHOPPING-SCHEDULE-RELEASE.md)。本次计划已实际消费，不可重放；失败原件保留，不自动恢复。后续发布仍需新候选、具体计划独立审查与逐阶段执行。

## 实际生产只读审计

本次生产为 **一户两库**，家庭库 69→69、平台库 9→9。停写前与新 app 启动保全原件的完整 schema、行、列及序列一致，组合逻辑 SHA256 均为 `11d39a9179c88f2d2afb6eae8fd7dc4b5e930fc395c92c2a6d8b5a4cff56c2a9`。既有财务和路线表按实际内容保全，不要求空表；审计没有重新查询活跃数据库，启动后正常业务仍可继续变化。

独立审计核对 980 个安装文件，以及 app／sync／media 各 127 个运行文件；104 个非 Expo 文件中 99 个保持父版，另 5 个匹配本包。四服务 running、0 重启、app healthy，75 个正常 TLS 静态资源与包匹配，env／membership marker 保持，备份定时器 active。

24 项匿名 GET 拒绝探针和另 3 项助理 GET 探针全部为 **401**；它们证明匿名 GET 被拒绝，不能证明 POST 授权、模型调用或本人操作。审计没有业务写入、提供方调用、SQLite／app 导入、bootstrap、服务重启或恢复操作。

两份保留的停机备份字节哈希已核验：家庭库 `564d8a649e9b751feedd96318dda77ace7e81972bf14e07d7e25d4313533ec38`，平台库 `c55d9896eb65ed09e3e17e67970aa7a4303aab32fe9931b571ded7f6549087c8`。**未执行备份恢复**，不能将字节核验描述为恢复演练。

审计原件为 `worktrees/shopping-schedule-linux-prep/test-results/shopping-schedule-production-readonly-r1.result.json`，SHA256 `4fce162234123a7f770d58fc875104011cdf9d52e7d77d7d397ccc15f48f9ded`；实际执行回执 `shopping-schedule-production-readonly-r1.execution.json`，SHA256 `fd67776ab8ee909d525aea96c8381e86f37648832dc805c342a2f60c2ed57ef2`，退出码 0。观测时间为 `2026-09-19T19:55:48.385835+00:00`，即上述北京时间。

## 证据定位与未验事项

受限本地原件位于 `family-dashboard-access/shopping-schedule-release-20260920-r1/reviews/`，不提交 Git。最终 index 与 hashes 文件固定 16 份原件，重点入口如下：

| 原件 | SHA256 |
| --- | --- |
| `backend-combination.json` | `55a7d33edd54ada4471685a9a883baac8b542d427d2354a7cef5f467e8042de4` |
| `build-independent-review.json` | `f2acb6a6a2acc963f490ad43b2665d7a5fd95c6a4a37fa9e1a487eace43904b1` |
| `combined-independent-review.json` | `1891ad7958e8786d61aadea13c6110b5ddf35d69c89cc3ac617790a8c4b19313` |
| `real-model-result.json` | `64790daa05c40fbca4391fa7555e0ea0534cf9864acf4e854f8862819a358c01` |
| `real-model-independent-review.json` | `224419579d76a853874922bfae281180e8a9fa639dffa32b87b20602ea59d148` |
| `linux-independent-review.json` | `b22f605f9cf3f73acccc0d566ae5aad9fcdd5df7d4f80ff2e99c358ee2651b38` |

正式构建原件 `worktrees/shopping-schedule-build-r3/test-results/expo-shopping-schedule-build-r3/build-evidence.json` 的 SHA256 为 `9d0570c27441b626f44fd1e34e1e5573514c3756daf6b5f5fbb58339dd419a9e`；同 worktree 的 `test-results/expo-shopping-schedule-20260919T190030609891Z/result.json` 为 `2be3ef9f0b5a8f83fbb5784d358ba90cba8d771ec71edf9a74bbf50fc8e9eb90`。独立审查已核验这些原件与最终包之间的字节绑定；本页整理文档未重跑模型或业务检查。

本人完整 A–D 验收仍为 **0／4**；真实微软／Google 云操作、真实家庭连续使用与实体电视不由上述分段结果替代。电视设备当前不可用，待设备可用后验证。资料搜索属于下一独立开发批次，不能在本批使用说明中声明已经上线。

相关合同：[后端](SHOPPING-SCHEDULE.md) · [Expo 交互](EXPO-SHOPPING-SCHEDULE.md) · [助理草案](ASSISTANT-SHOPPING-SCHEDULE.md) · [四个完整场景](ACCEPTANCE-SCENARIOS.md)。
