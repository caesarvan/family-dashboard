# 旅行准备、采购与成员分工：使用与验收

<a id="assistant-trip-items-release"></a>

**已于 2026-09-20 01:13:38（北京时间）激活，01:23:44 独立生产只读审计通过。** 本页集中记录旅行准备、采购与成员分工的使用、分段验证和固定发布身份。实际生产一户两库保持 69/9，完整停写备份与启动前后保全通过；Linux 两户三库是另行记录的合成演练。A–D 本人完整验收仍为 0/4，真实云写入和实体电视另验。

## 使用路径

1. 从「更多 → 家庭助理」输入旅行安排，点击「整理并预览」；也可点「规划一次旅行」直接填写。只有明确选中「使用 AI 整理这段文字」才请求模型。
2. 在简报中核对基本安排，展开「准备事项」和「采购清单」，修改标题、负责人、准备截止、采购数量和预算。无法确定的负责人须手选；采购预算可以保持未知，不能用 0 代替。
3. 点「核对并继续编辑」进入旅行编辑页，再预览并明确确认保存。前面的整理和核对不创建旅行；保存后可在该旅行中查看关联的准备与采购。
4. 修改出发日期时，「随出发日期调整」的准备截止随之重算；固定日期保持不变。采购本批没有结构化截止或改期联动，有关要求只保留在备注并提示核对。

例如可输入「2027-10-01 至 2027-10-07 去冰岛，总预算人民币 20000 元；我在出发前三天核对护照；小林买两只转换插头，采购预算 200 元」。使用 AI 后仍须补齐和核对名称、停留日期、出行成员及分工；“小林”必须是当前家庭中可唯一识别的成员，否则保持待选择。本地模式可直接填写表单，或使用[明确标注的文字格式](ASSISTANT-JOURNEY-BRIEF.md#本地提取与模型边界)。

模型失败或预览失败时保留本页草稿，可继续修改后重试。若保存后网络中断、结果不明，使用原旅行编辑页的「核对原保存」；它沿用原操作编号，可能完成尚未成功的保存。先核对已有结果，避免另建一份。草稿仅在当前页面内存中，刷新或离开后不保证恢复。

## 本批实现与边界

- 同一份简报提取准备、采购和分工，沿用原旅行预览与明确保存。总预算与单项采购预算独立，金额按整数分处理；未知和明确零预算有区别。
- 模型只接收这次需求文字。服务端在请求结束后重新核对当前成员，将“我”、共同负责及唯一精确姓名解析为候选；不向模型发送家庭记录或成员清单。不存在、已离开或重名负责人不猜选。
- 可新增、移除和编辑清单；修改期间迟到的模型结果不覆盖新输入。切换成员后不保留上一成员的简报；恢复网络或回到前台不自动再请求模型。
- 结构化旅行需求不会因含预算、护照或签证准备被误送至财务查询；同时明确询问“本月花了多少”的混合请求保留财务询问，沿用现有澄清流程。
- 两位成员同名时用“我／另一位成员”区分；多个同名非本人仍待明确。复杂口语及模型输出仍需本人核对；本批不创建付款、预订或云日历／待办发布队列，不提供签证政策结论。

接口及字段见[简报合同](ASSISTANT-JOURNEY-BRIEF.md)，交互和恢复细节见[Expo 简报](EXPO-JOURNEY-BRIEF.md)，部署合同见[发布工具](ASSISTANT-TRIP-ITEMS-RELEASE.md)。接口与交互页保留各自作者阶段的状态；本页集中记录后续组合验证与正式上线结果。

## 固定发布身份

以下固定包已经安装到生产。[PR #3](https://github.com/caesarvan/family-dashboard/pull/3) 已合入 main `ec344d58ddfaaa5ff356f398fbcbd0f5073032c7`；main 比下述打包源码增加两份验收文档，运行、前端、测试与发布工具字节一致。后续纯文档提交不改变该包的源码绑定，也不代表服务器文档已同步更新。

| 项目 | 固定值 |
| --- | --- |
| 组合源码与 Expo 源码 | `882dce5d0bc7bba182d4fe4ba1175c040123e6fd` |
| 源码树 | `71ce91c011b89e70aa95cab17ae44b41fa182e3b` |
| `package.json` SHA-256 | `a740a95187ee2d62fc61483c1799953b6fb769ccc9e5a9444a9144bace8b61b4` |
| `release-manifest.json` SHA-256 | `47dec854a77262458bc74573f0b36083c856b772c940587d8d1644d44e032b70` |
| `release.tar.gz` SHA-256 | `41f8fa56a023043aa453bd0f247d2fe04e06f6aa98c7843754bcb3c4666e6bad` |
| R2 Expo 构建原件 SHA-256 | `558f1c435a243ed59940d4f5250d3814f1cd2e704c98d405286cd34fe4fa55f7` |
| 生产 app／sync／media 镜像 | `sha256:dc5ecb91f25017a19a7e59a992e94d8d281a7e68f1e97e0ca0b5dfeaf2872bd6` |
| 包文件 / 运行文件 / Expo 产物 | 957（934 源码 + 23 产物）/ 127 / 23 |
| 数据合同 | 户内 69→69 表、平台 9→9 表；无本批 DDL |

## 已完成的分段验证

各轮范围不同且存在重叠，不相加为一个总通过数。

| 层次 | 实际结果及范围 |
| --- | --- |
| 组合后端首轮 | `5ae5eb4fa6affd0e3fff5a3a82958419e5c19551` 上四模块 173 项通过，0 失败／错误／跳过；这是模型接缝修正之前的基线。 |
| 模型接缝增量 | API 最终提交 `28822ab351052ceb001339518a694b6fe1168ee5`；R5 45 项、R6 18 项分轮通过，均零跳过，覆盖实际失败输出回放、引用分句边缘及省略负责人。R6 对应最终字节。 |
| 实际 NVIDIA 模型 | 在上述 API 提交上，R2 一个合成需求、一次实际请求，28 个检查通过；核对一项准备、两项采购的本人／另一成员／共同分工、截止、精确金额和未知预算，真实预览、保存、重放及重建 app 后读回。业务快照覆盖八张表，云队列保持空。 |
| 正式 R2 Expo | 独立 detached checkout，自有 `npm ci` 依赖；两组 TypeScript、71 项 Node 检查及导出均 exit 0，0 Node 失败／跳过，23 个产物。前端及补充输入前后相同。 |
| R3 实际浏览器 | 临时 HTTPS Flask／SQLite／Edge 四条流程全部通过：提取并保存、未知及重名分工、编辑／日期／原保存恢复、迟到模型响应与实际成员登录切换。仅模型原始输出使用合成替身，其余走真实业务 HTTP。 |
| 浏览器画面 | 390、1280 宽度的提取与保存结果共四张图；采样视口未检测到横向裁切，集成人已逐图查看。不能外推到所有滚动位置或实体电视。 |
| 发布工具本机专项 | 作者冻结提交 `f243f8ea9d8f7be0ac2d3b4c0dd6a9b911244b3c` 上 43 项通过，0 失败／错误／跳过；含合成非空 69/9 和旧默认 66/9 的备份、实际 app 重建、保全及文档恢复核对。控制器测试记录命令，不等于执行 Docker 或生产部署。 |
| 实际 Linux 构建与测试 | 同一固定包构建 exit 0；原父镜像配置保持，增加两层，运行文件按包核对。实际隔离容器按冻结选择执行四模块 199 项，199 通过、0 失败／错误／跳过，容器和验证入口均 exit 0。 |
| 实际 Linux 两户三库保全 | 固定旧路线父镜像真实创建 69/9 合成库，每户财务五表各一行、路线三表各两行（含软删及操作回执）；完整停写备份后用候选镜像启动全部家庭，再停机核对整组行、schema、序号及 marker，逻辑指纹相同。本轮未执行备份恢复，未访问生产卷。 |

浏览器及实际模型中的“重启”均指重建 app 实例并重新读取同一临时数据库；浏览器还重建监听器，不声称重启操作系统或生产服务。R3 无外部请求、页面错误或生产写入，源码、产物、fixture 均保持，临时库已清理。实际模型只使用虚构旅行和本地临时家庭，没有发送真实家庭资料。

Linux 构建于 2026-09-20 00:50:30、两户保全于 00:54:19、199 项测试于 00:57:01 完成（北京时间）。保全演练复用隔离执行器、合成凭据及合成 marker，明确不是生产控制器的原样执行；本机恢复检查不能改写为本轮 Linux 已恢复。三个原件已按下表散列读回；独立审计已核对同一 199 项选择及 JUnit、前后运行与依赖散列、实际命令退出码、两户完整逻辑指纹和三份备份文件散列，结果通过。

## 实际发布与独立生产审计

- `stage`、`activate` 均实际 exit 0，完成时间为 2026-09-20 01:13:38（北京时间）；计划已消费，不可重放。发布目录为 `/opt/family-dashboard-releases/assistant-trip-items-69-20260919T171203879464Z`。
- 实际生产为 **一户两库**，户内 69→69、平台 9→9，无 DDL。`stoppedBackup.verified` 与 `preservation.verified` 均为 `true`；停写前与新 app 启动后再停写的完整 schema、列、行及序号逻辑指纹同为 `2939f5ad0ef7b4003fdb24860a6a80d76bfbe30442de58305d0ad9680381575b`。
- 01:23:44 的独立只读审计核对 957 个安装包文件、app／sync／media 各 127 个运行文件、75 个正常 TLS 静态资源的 200 与散列；23 项匿名 GET 拒绝探针均为 401。`/app`、`/app/assistant`、`/app/tv` 与 `/healthz` 返回 200；四服务运行且重启计数为 0，app 健康。
- 原 `.env` 文件、实际环境变量映射和成员 marker 保持；备份定时器 active，两份保留的停写备份文件散列与记录一致。环境变量排序不同不视为配置内容变化，原件未输出密钥或数据库内容。

审计只核对发布原件、保留备份文件散列、安装及运行文件、容器状态和匿名 GET。未打开活动 SQLite、执行 POST、调用模型或云服务、写入业务、恢复数据库或重启服务；上述 GET 结果不证明 POST 认证或本人工作流通过。启动后的实际业务数据可以继续变化，不能把发布前后停写指纹当作持续实时快照。

## 保留的失败与修正

1. **实际模型 R1 未通过。** 引用片段带分号／句号，以及模型省略“我／一起”的负责人字段，导致部分来源与分工未正确对应。修正在 `28822ab…` 中仅处理引用首尾分句符，并从匹配原句保守恢复明确主语，再校验当前成员。原始失败输出作为虚构回归 fixture 保留；真实模型 R2 重新请求并通过，未改写 R1。
2. **浏览器 R1、R2 未通过。** R1 在复制长路径资源时失败，尚未进入业务流程；调用方改用 Windows 扩展路径。R2 暴露结构化旅行被误分到财务查询的产品问题；最终路由修正 `aed98c0d99257d7b9e28197e2f1710e0abf0c0e4` 保留混合财务询问，并重新构建后运行 R3。原四场景脚本及失败原件均保留，没有删减失败场景。
3. **R2 构建在 `npm ci` 完成后中断。** 原 phase 0 已有 exit 0 与日志，后续无产物；确认旧进程终止后，独立审查续跑脚本核对原五个文件、源码与依赖目录，只执行原 phases 1–4。最终证据包含历史 phase 0 和后续四个实际退出码，不称整段未中断执行，也未重复安装依赖。

## 原件索引

原件保存在本地忽略目录，不进入 Git。下表 `A` 表示 `family-dashboard-access` 审计根目录，`W` 表示 `A/worktrees`。报告内还保存命令、输入、日志及子原件散列；这里列出用于复核的主记录。

| 原件 | SHA-256 |
| --- | --- |
| `W/integration/test-results/assistant-trip-items-backend-r1/execution.json` | `a8a87a4d18ec7f6bf36d21badb8fb5d955c1b2ec8cc802a62e1dd489e02e4d42` |
| `W/assistant-trip-items-api/test-results/assistant-trip-items-model-seam-delta-verification-r3.json` | `cfa8899ee0d4bcdbd2de6b61c10350a0dfd4e1da8535adf2403d1666f014bd23` |
| `W/assistant-trip-items-integration/test-results/assistant-trip-items-real-model-r1.json` | `b6e70d57200656f77320475099207142d2aa82a5db11b9ae5beb4245b5cda1c4` |
| `W/assistant-trip-items-integration/test-results/assistant-trip-items-real-model-r2.json` | `c2a7630e3780ed74065d1281ee88e8f4457e77cc0fb1e8ec2242ee27440f1b5f` |
| `W/assistant-trip-items-build-r2/test-results/assistant-trip-items-build-r2/build-evidence.json` | `558f1c435a243ed59940d4f5250d3814f1cd2e704c98d405286cd34fe4fa55f7` |
| `W/integration/test-results/expo-assistant-trip-items-20260919T155824973403Z/result.json`（R1） | `fd158501bbc1ea23b7f6e691aa97553c2db8e8d969ffb962466535207c2629c9` |
| `W/integration/test-results/expo-assistant-trip-items-20260919T160202735000Z/result.json`（R2） | `49a0b7dcf9d4bb46442eac66c47bbae810073d7af4cc6a097127f6572b0ee4bd` |
| `W/integration/test-results/expo-assistant-trip-items-20260919T164451854455Z/result.json`（R3） | `5d18d15f8e7d2b4d26fd052012151261f6624f6e249e18d7053bf793bea0dd97` |
| `W/assistant-trip-items-release/test-results/assistant-trip-items-release-verification-r1.json` | `6578e7063ce33164ac370307ee9619ebc2a0b9068a3e02a4dbb8338797d37dbd` |
| `A/assistant-trip-items-package-r1/package.json` | `a740a95187ee2d62fc61483c1799953b6fb769ccc9e5a9444a9144bace8b61b4` |
| `W/trip-final-review/test-results/assistant-trip-items-linux-independent-review-r1.json` | `4bc7644f936e5c2482597e7a0122745769454922bc0844b98fa6e8f1f1d6d5ad` |
| `W/trip-final-review/test-results/assistant-trip-items-final-plan-independent-review-r1.json` | `4bd72f770e82d79535616c2adbebf3bbf807c54fe4aa6121439843549b695f23` |
| `W/trip-build-resume/test-results/assistant-trip-items-production-readonly-review-r1.json` | `4ad1226c392ab0d371df7f1ca36331c03da52e00815c2bd06aacb992a49580d7` |

服务器原件中，`V` 为 `/opt/family-dashboard-candidates/assistant-trip-items-verification-20260920-r1`，`R` 为 `/opt/family-dashboard-candidates/assistant-trip-items-rehearsal-20260920-r1`。它们均为隔离候选／演练目录。

| Linux 原件 | SHA-256 |
| --- | --- |
| `V/build/build.json` | `8a6839b424152904e12c818778e1a58d299deb4ed5dc7f0e07e39132fccb0758` |
| `V/validation/validation.json` | `df9c7968e9c849773aca3468a976bd96bc7a2f62717bbf2b7993e0ef0221cdb1` |
| `R/result.json` | `bf40d7cd096055c96e61d80555fbe7179a6f86364604b6a0f59ebee3f9eb052d` |

服务器正式计划与回执所在 `C` 为 `/opt/family-dashboard-candidates/assistant-trip-items-69-20260920-r1`。上述独立审计绑定本次实际回执与发布目录。

| 正式发布原件 | SHA-256 |
| --- | --- |
| `C/release-plan.json` | `1eee1f9d1974657c4c267b70cddfc44836265ce76c7fb49bc03b214b3cbeafe3` |
| `C/stage.json` | `ad17aaefffb2d5c5969af466d096288dc3236e5fce488ae661f1de94d6dcb819` |
| `C/activation.json` | `cf936f7a3bb31a96d885da1f8b686ba19786932d21541447c476cd7bbd4bc3c0` |

## 发布结果与本人验收

| 项目 | 当前证据边界 |
| --- | --- |
| Linux 结果与最终组合独立审计 | 已通过；同一固定源码、正式 Expo 原件、Linux 199 项和合成两户保全分别绑定，正式计划另经独立只读审查。 |
| main 合入、生产 stage／activate | PR #3 已合并为 `ec344d58ddfaaa5ff356f398fbcbd0f5073032c7`；本页固定包已实际安装，stage／activate 均成功。 |
| 生产读回、完整停写备份与新启动后保全 | 一户两库完整保全及独立只读审计通过；保留备份文件已核对，但本批未执行生产恢复。不得重放已完成计划或旧 66 表迁移。 |
| 本人真实旅行、实际指定日历／清单、改期协作及电视 | 未验收；本批分段结果不能宣布完整场景 A–D 通过。 |

采购结构化截止与改期联动、多个同名非本人成员的进一步识别，以及刷新后的草稿恢复仍是后续产品事项，未作为本批完成能力。
