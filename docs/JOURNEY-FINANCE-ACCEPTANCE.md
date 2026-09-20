# 本人旅行费用：使用与发布验收

<a id="journey-finance-release"></a>
<a id="journey-finance-candidate"></a>

**已于2026-09-21 02:38:33（北京时间）发布，02:38:56只读回读通过；非作者生产独审已通过。** 实际 source 为 `302a62d`、75张户内表／9张平台表、五服务；原财务方向列 `53ea3fd` 是本次73表父版。浏览器、Linux功能与隔离迁移执行已分别通过非作者审查，具体范围如下。本人 A–D 完整验收仍0/4。

## 最短操作路径

1. 先在本人账本保存人民币消费付款；打开已完善并保存的旅行，进入「我的旅行费用」→「选择实际付款」。没有工作流的旧旅行先沿原入口完善并保存。
2. 选择原付款，核对已关联退款和可用净额，填写「归集金额」→「预览归集」→「确认归集」。预览不保存，订单不再作为付款重复计入。
3. 回到同一旅行，核对「仅本人已归集」「需核对」和单列的「旅行共享预算」；可「查看原付款」并返回。这里只覆盖本人的部分费用，不计算家庭实际总费用或家庭剩余预算，不改共享已付、采购金额及原账单。
4. 退款、重复关系或来源变化会使旧归集进入「需核对」。本人可「调整归集」后重新预览确认，或「解除归集」→「预览解除」→「确认解除」。解除保留历史，释放该付款的旅行归集额度；原旅行／付款已删除时，从「财务 → 我的旅行费用 → 查看全部历史」解除孤立关联。
5. 保存结果不明时点击「核对原请求」，不要另建相同归集；只有明确选择「重试原请求」才重发原请求。离线／身份不明先恢复连接核对，切换成员不会展示旧人的金额或草稿。

首批仅本人 CNY 整数分归集；已明确关联的退款抵减原付款净额，不另建负数费用。跨本人所有旅行的有效关联共同占用该付款额度，待核对及孤立关联仍占用，不能绕过限额。没有分摊、报销、外币换算或第三方自动记账。接口与导出白名单见[JOURNEY-FINANCE](JOURNEY-FINANCE.md)，界面恢复见[Expo说明](EXPO-JOURNEY-FINANCE.md)。

## 已实际验证的范围

| 阶段 | 实际结果 | 边界 |
|---|---|---|
| API专项 | 作者44项新用例＋2项相邻最终通过，分轮原件保留，API非作者审查通过。 | 合成 Flask／SQLite 的权限、净额、重启、回执、并发额度、漂移、导出；不与下面Linux重复相加。 |
| 正式 Expo | `0ad4e41` 的R2两组tsc、Expo导出均成功，159前端＋9补充＋1根目录测试共169输入，23导出。 | 复用R1实际npm ci；R2不是再次fresh安装，未重跑Node套件。候选包明确记录build source并校验输入复用。 |
| 真实浏览器 | 同一 `0ad4e41` R2一次3/3，六张390／1280视口截图、stderr为空，非作者原件审查通过。 | 归集与退款调整／来源追溯及重启；真实确认响应丢失后刷新恢复且不重复写；离线草稿和迟到旧身份响应隔离。合成账单、临时HTTPS／Flask／SQLite／Edge，不是生产或本人设备。 |
| 本批 Linux | `302a62d` 的实际新镜像构建成功；精确46项（44新＋2相邻）全部通过，0失败／错误／跳过。 | 固定包／源／镜像下的功能验证，非任意混合负载或生产容量证明；执行独审已通过。 |
| 隔离迁移与恢复 | 同一候选镜像完成10阶段：验证、合成两户三库73表种子、迁移、仅app初始化、停止后保全、完整73恢复、0400故障部分迁移及整组恢复、写入非空75、重启、完整75恢复。 | 原73表／行／序列保持；初次两新表为空。每户非空夹具为3归集（有效／解除／孤立）＋1回执，直接合成存储，不冒充API用户操作。仅隔离临时库，未访问生产、未启动恢复后的服务；执行独审已通过。 |

浏览器R1为1项通过、2项工具失败（未知结果已自动恢复后的旧预期、迟到路由重复处理）；R2修正工具后实际三项通过，原件均保留。API／迁移本地首轮测试设置或Windows长路径失败、迁移准备首轮失败也保留，不将最终结果改写为首轮全绿。本次文档整理未重新执行任何测试。

## 源码与产物身份

| 对象 | 固定身份 |
|---|---|
| 实际发布包source／tree | `302a62d6c32676b4c8628bd5c0fdf967e1d143c5`／`121b31a1f5b820ffd9f935671125bfa86e51fa17` |
| Package／manifest | `eca8fbaa739fe4f9300ebc2756292bbeced290badacca16489f30c4a7adf1be2`／`9a44d4c5d6002fb600e79069a44438371461b530eda03e89194927314a32820e` |
| 实际应用镜像 | `sha256:1f957a9458cfed01108a4b028e6cdc3297e22bc0a83776c08d4bf374e09feaca` |
| Expo／浏览器source | `0ad4e41eb4f13c239104918e099e8f42880b0ea1`；302a相对它只增加发布／迁移工具、测试和文档，业务及前端输入不变。 |
| 迁移operator／runtime source | 工具 `4ec186e288ff08d8ac3c7db986b69c95139096ec`；运行源码参考 `a47372624e66cab0e8100a37f54223737780eb73`；历史73表种子固定生产源 `53ea3fdb571eae69154e61d264f3c3542631cb49`。实际镜像根模块及迁移闭包逐字节核对；不是同一Git头，也不代表工具覆盖前端。 |

发布包包含1199源码文件及23导出，共1222安装文件；每个应用服务核对136运行文件（113非Expo＋23导出），decoder保留原4文件。此文档最初以候选加已审README修订的 `8b4eded` 为基线；Git/main和后续文档提交不替换上述包、构建或operator身份。发布接口与单次计划要求见[固定发布合同](JOURNEY-FINANCE-RELEASE.md)；73→75及75稳态合同见[迁移说明](JOURNEY-FINANCE-MIGRATION.md)。

## 原件索引

以下原件只在忽略目录保留，不提交账单、数据库、截图或凭据。`A` 为本机 `family-dashboard-access/`，`W=A/worktrees/`。

| 原件 | SHA256 |
|---|---|
| `W/journey-finance-combination/test-results/expo-journey-finance-combination-r2/build-evidence.json` | `c3cdeebb70ec70d469563cff6724599fa811b7c9cea32792e87c80ac7a87d6e6` |
| `W/journey-finance-combination/test-results/journey-finance-20260920T174701640402Z/result.json` | `698eaa8f29aa0115dc3bde53a61e9b8f5ad45f3a4abb671b7435c708dbb2ede7` |
| `W/journey-finance-linux-probe/test-results/journey-finance-browser-independent-r1.json` | `2042bf29704fa296b4b0ef1e826bdcbe957511a1cd28828337529858072ef293` |
| `A/journey-finance-release-candidate-r1/linux-evidence/build/build.json` | `8842ca3125888f2724b210cd301ac05ca047fce732183526d5385b3d0f2fbb15` |
| `A/journey-finance-release-candidate-r1/linux-evidence/validate/validation.json` | `e280bff8d4fcec285c05975559f9dfee67705beaa69e868e06b1259d01758d0d` |
| `A/journey-finance-migration-linux-r1/evidence/run-r1/result.json` | `7a6653ff50847f94d60d46362e8266e778a4ca234dd2ceac661619a302104dbf` |
| `W/finance-flow-release-evidence/test-results/journey-finance-linux-candidate-independent-r1.json` | `f0ab00be5b184bdba21c11901a597f7c6b5c91eb53f3e79cde58d16273389c07` |
| `W/finance-flow-release-evidence/test-results/journey-finance-migration-linux-independent-r1.json` | `ec03727481cc673625ccae48e391418d2a17a77ddcb479be49536c3e0b8a63d6` |
| `A/journey-finance-production-r1/retained-receipts/candidate/stage.json` | `2b82aa9834847c43f5e07b224e2a0f13f43c06cc5881882381389557f84577ec` |
| `A/journey-finance-production-r1/retained-receipts/candidate/activation.json` | `1b593a4120c55bc57af7b309220f776892a81bf2b1124c7de2d4da9d4cb1056f` |
| `A/journey-finance-production-r1/readback.stdout` | `3a905253dceaed3c81a28abba7a5eb8c12560f61ed0c20f530317f99b044d8a9` |
| `W/finance-flow-release-evidence/test-results/journey-finance-production-independent-r1.json` | `dac5e57fb87513995c1e7441efe9046c3d43fd6fd0c168c24c089f1012ab85b7` |

## 实际生产迁移与回读

本次 stage 无生产写入；独占计划通过后实际 activate 完成，发布目录为 `/opt/family-dashboard-releases/journey-finance-75-20260920T183632268577Z`。北京时间2026-09-21 02:38:33完成激活，02:38:56的只读回读通过。非作者生产独审已通过。

实际一户两库完成全组备份后73→75／平台9保持。旧73表的结构、行、settings和序列全部保全，两新表在app-only启动后停止核验时为空；迁移后逻辑摘要与停止态摘要均为 `50cfd61a26e50309444687b7fdfcbe598494232941066130c5685edca55964d8`。新旧全库逻辑摘要因新增表不同，不能表述为迁移前后完整库相同。

只读回读核对1222安装文件、app／sync／media各136运行文件和decoder原4文件；五服务running、无OOM、重启数0，app／decoder的健康检查为healthy，其余服务没有health状态。正常TLS健康请求200、备份timer active，环境仅以散列与模式核对，不记录值。

计划 `33e59a0988dcd1d84eac50c30c7ef4eac507f8645df046ca7a949f4620b000ca` 已消费，不可重放；实际operator为 `6165fad6636964a2c1c958cdda57ad7dabed0dbd76ed69b99aae3fd7316445a1`。本次生产没有恢复数据库；隔离73／75恢复不能冒充生产恢复。只读回读没有读取活库、重验备份数据库字节或证明worker业务tick，也未验证本人新业务操作、真实云或实体电视；A–D仍0/4。
