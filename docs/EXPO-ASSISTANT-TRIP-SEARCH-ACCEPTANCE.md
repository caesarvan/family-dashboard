# Expo 助理查找已有旅行：验收与发布记录

<a id="expo-assistant-trip-search-release"></a>

本批已于 **2026-09-18 09:30:34（北京时间）激活，09:31:16 正常 TLS 读回通过**。安装 main `bf38f81c5d81dd3e9afd34474383e0910f460434`／source（formal）`8badc37d85889e8e8dc0c11670cb98a55a768369`，与 R3 受验组合 `52adae89741c239168d2bdf7bffac430952065d1` 同树 `4dd0ea975510a8efcf38b42f1450cafa1ba194d8`。实际工具目录为全新 `expo-assistant-trip-search-tools-20260918-r2`，首轮失败原件保留；后续纯文档提交不会改变此安装身份。独立只读发布审计已通过，09:33:38（北京时间）另一次 fresh 读回与固定安装身份一致。

## 怎么用

1. 在「家庭助理」输入「找一下冰岛旅行」「搜索 冰岛旅行」或「查找：冰岛旅行」，点「整理并预览」。关键词沿现有接口按字面匹配；找不到时调整关键词，不会自动新建旅行。
2. 在旅行结果点「查看旅行」，打开原旅行的当前详情；基础旅行与已有 v1/v2 计划均沿原详情读取。可以继续原有编辑、分段、资料与回顾操作。
3. 点「返回助理」回到原输入和查询页码。结果会重新读取；删除、权限或会话变化不能恢复旧详情。保存结果不明时先按原旅行的提示核对，不能借新入口跳出原保存。

三种显式搜索前缀即使在 AI 已勾选时也只在本地搜索，页面会提示不会发送给 AI。真正的旅行规划与明确的待办／采购指令仍走原流程；搜索不自动修改记录、推断到访或发起云操作。更多恢复说明见[家庭助理](EXPO-ASSISTANT.md)与[旅行页面](EXPO-TRIPS.md)。

## 固定来源与实现范围

| 部分 | 已审固定来源 |
| --- | --- |
| 入口与分流 | `5320576d6062390b74f46d2aff7b340f96693c7f`；[AssistantScreen](../frontend/src/screens/AssistantScreen.tsx)、[assistantJourney](../frontend/src/lib/assistantJourney.ts)、[真实 Node 入口专项](../tests/test_expo_assistant_journey_entry.mjs) |
| 浏览器验收 | `2ff717cc9da029b94bfd0839c5d3f0f1c76839c8`；[六组脚本](../tests/browser_expo_assistant_trip_search_check.py)，包含 R1 后的局部选择器修正 |
| 经典浏览器测试拆分 | `c83503090703bbf06053c26a5e26e6706c2471a8`；完整 120 行函数逐字移至 `tests/test_assistant_source_search_browser.py`，原八模块名单及业务断言保持，无 skip／deselect |
| 发布适配器 | `0518c05885b7545a97189aed8048746ac678a580`；[prepare.py](../deploy/expo_assistant_trip_search_release/prepare.py) 与[保护专项](../tests/test_expo_assistant_trip_search_release.py)，非作者审查通过 |

本批只扩充助理页面的现有旅行入口，全部后端、API、Docker、依赖和 schema 保持；发布设计为含当前角色值的 58→58 无 DDL。首页待办编辑属于独立后续候选，不包含在本批源码中。发布保全要求与父九份工具来源见[发布适配器](EXPO-ASSISTANT-TRIP-SEARCH-RELEASE.md)。

## 实际本地证据

以下 `A/` 指私有 `family-dashboard-access/`；`W/` 指其 `worktrees/`。原件不纳入仓库，不包含真实家庭或金融资料。

| 检查 | 真实结果与边界 | 原件及 SHA256 |
| --- | --- | --- |
| 组合客户端 | 在 `dbd3cae6be584c6c376eb406bbd686defd7b77fb` 执行 `node typecheck.mjs` 两配置退出 0，Node 22/22、真实 Flask flow 1/1；执行前后源码保持，上述三条命令实际使用的输入同字节；全库来源清单另有经典浏览器用例拆分的两路径差异 | `A/expo-assistant-trip-search-client-check-20260918-r1/result.json`；`b5e8a2d64e049a880388247ebd64db372966dc3de13db270114562f7841d60cf` |
| R3 实际构建 | 在拆分后候选 `52adae897` 完成真实导出；198 inputs、23 exports 与 R2 逐字节相同 | `A/expo-assistant-trip-search-build-20260918-r3/build-evidence.json`；`c3120d8f407266e8120842dcd7d22f6d8e456ae1384dab0bff7cd20e6ec16730` |
| R3 Expo 浏览器 | 6/6、四张 PNG；761 tracked、23 exports、5 fixtures 前后完全相同，六个临时环境清理，页面异常／外网／模型调用均为零 | `W/expo-assistant-trip-search-browser/test-results/expo-assistant-trip-search-20260918T010248112020Z/result.json`；`d44b9673f910c50baf77d3154d6319dc025ca36668ec254d307cfb2e3391d381` |
| R3 独立视觉检查 | Root 实际逐看全部四图，320×844／1280×1000 浅深色可见视口无阻断；按钮实测 44px，长标题和入口可读 | `A/expo-assistant-trip-search-visual-review-20260918-r3.json`；`5457794ee1aa7a1c6b936d07f4d258466f4777180558268a96c32ae7e1972015` |
| R2 Python collection | 拆分后 `52adae897` 实际收集 167 唯一节点／原八模块；此原件仅为收集，后续 Linux 执行另见下节 | `A/expo-assistant-trip-search-collection-20260918-r2/result.json`；`8d74f2962b866a9dbc186a410b061e83bcf79ddc12c6c5bed6b898f54c4bcec9` |
| 恢复后的独立组合审查 | 测试拆分及 R3 受验组合审查 PASS，随后合入上述 main／formal；不以适配器作者自审代替独审 | `A/expo-assistant-trip-search-combination-review-20260918-r2.json`；`c0a418aa1a0c79b32ac9e1623a19445bcadfb8dad6b2fa7e0b5571ab775b42ad` |
| R2 发布冻结 | 783 个文件＝760 source＋23 exports；本条记录冻结，实际激活与读回另见下节 | `A/expo-assistant-trip-search-freeze-20260918-r2.json`；`3c0f6d7e7f0695c825bd8725128ec5307f2f493259f39cfd0747b17170dabf7a` |

独立经典浏览器单项与上述 Expo 六组分别验收：拆分后 Windows／Edge 真实运行 1/1，通过原八个内部检查；零页面异常与外网请求，761 tracked 前后保持。原件 `W/assistant-source-test-split/test-results/assistant-source-test-split-r1/result.json` SHA `c62c1535b620f9f591e219e3afbc3b758b59cde5413539ae7a1b8d92b65ab0ae`；JUnit SHA `904d072ddf6c341ff71474491657161889e361d14f765a12fb50f3e309691163`。独立最终审查将源码、单项与 167 collection 分别核实，`A/assistant-source-test-split-final-review-20260918-r1.json` SHA `59bdfc1b5da8653ef466567db237e807019ae938ea0bce278f3b930af928a052`。

浏览器六组覆盖三前缀强制本地及原有新建分流、v1/v2 及第二页详情往返、查后删除与详情丢失、同成员新 Cookie／跨户迟到／隐藏离线、已提交丢回应后的原 token/key 明确重放，以及四图与键盘。故障只延迟或丢弃真实 API 响应，不替换业务成功内容，详见[浏览器验收](EXPO-ASSISTANT-TRIP-SEARCH-BROWSER.md)。

R1 原件保留：实际 2/6，通过查询分流与身份边界；其余四组在“编辑旅行”的 Paper 图标前缀与精确选择器不符处失败，下游未执行。仅生成浅色两图。原 `result.json` SHA `d24ef84a745be96fa1d78d776a4a1bc08eaf71edf3de86b50e21ea77a345ae4c`；局部选择器修正经独立审查后再做 R2 构建与完整运行，不合并两轮计数，也不改写失败结论。

## 生产状态与验证范围

首轮 Linux 验证实际为 168 项：166 通过、1 项精确 Windows junction 跳过、1 失败、0 error。唯一失败为 `tests/test_assistant_source_search.py::test_browser_source_detail_paging_revocation_and_local_preview` 缺少 Playwright；该完整浏览器用例随后独立成模块，并在 Windows／Edge 真实执行通过，没有删除、跳过或弱化断言。失败原件与校验记录 `A/expo-assistant-trip-search-validation-failure-r1/failure-review.json` SHA `48651823c8a0ed25c7a5dc707b34db7e4789285d04308ebcdf1e1f0e37908de6` 保留。首轮 main `956ee6102b914b612404113b01bd8e1e4284174c`／source `600e9c94bd8225ef72c0e6e58ad5ef372febe0f4`／tree `1c59c6268f3406c1ac2692f61e3be8275dfba283` 未被激活，不能当作已安装身份。

T-r2 已完成本地包与绑定，真实服务器 build、validate、stage 各一次成功且 stderr 空。Linux 原八模块共 167 个唯一节点，集合与 collection 全集相同；实际 166 通过、1 项精确 Windows junction 跳过、0 failure／error／deselect，JUnit 用时 167.575 秒，运行文件前后核验通过。`A/expo-assistant-trip-search-tools-20260918-r2/validate-command.stdout` SHA `e8934000ea2abeb65034429489b0517e3dd3405b5fa4c9175e3eb05a17c184be` 是本地命令 stdout 的散列，不冒充远端存储报告的散列。

| T-r2 实际安装包 | 固定值 |
| --- | --- |
| archive | `0ef195375d6984a192e7272926006e95f8751ed9c63b6db87a36a82e91401452` |
| manifest | `db3a984f570d38b88c62cb040181f3b4f9d812ace04193ac21c509f899c4c246` |
| binding | `4bf1c840a8401e654241f52b764a474c59053714a2d44c149746236e050a5a2c` |
| 实际构建镜像 | `sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2` |

T-r2 的 build／validate／stage／activate／post 均一次成功；实际 release 为 `/opt/family-dashboard-releases/expo-assistant-trip-search-58-20260918T012935493119Z`。激活于 UTC `2026-09-18T01:30:34.569966+00:00` 完成，正常 TLS 读回于 UTC `2026-09-18T01:31:16.702862+00:00` 完成；对应北京时间为 09:30:34／09:31:16。激活命令 stdout SHA `cae8b266fb352fd0c38a276ac6ed85ea71123d4f57961e2610bb2a15f0d4d3fc`，post 命令 stdout SHA `eb2a4eec4726d98eea8fc28c3d20104c8afa77f0897b20e67c0bd075bb73d83d`；两者均标记为 stdout，不与远端存储 JSON 原件散列混用。

发布为 58→58 无 DDL，停写整组备份覆盖 1 户、2 库；原有行、schema、sequence、当前角色与 registry 在 app 启动前后保全。运行验证记录 116 个文件与 39 个已加载模块；post 核对 783 个包文件、116 个运行文件、75 个 HTTPS 静态资源、24 项生成资源拒绝、1 项退休资源拒绝和 39 个唯一匿名接口 401。四个服务均 running、零重启；仅 app 报告 `healthy`，其余空 health 不代表健康检查通过。

post 新一次逐库在线备份为 `manifest-20260918T013112355519Z.json`，SHA `fcf5950f7e2cd511223b6877e7575edbd606e59cf86dcade793f9309363d7314`，Invocation ID `8dcc65d15d13469d86da00b58a223d43`，timer active。它与发布前停写整组备份不同，不能宣称是运行中跨库全局原子快照。

独立只读审计 PASS：`A/expo-assistant-trip-search-published-audit-20260918-r2/audit-review.json` SHA `0e4cf0c91b95923c25f4c824219b85da1686ff369328f84c499830ee5346b9f2`，核对 47 份本地与 8 份远端原件，远端前后散列与本地保存字节相等；存储 phase JSON 内容与命令 stdout 解析相同，但序列化散列分开保留。正常 TLS fresh 读回时间为北京时间 `09:33:38.791512`，再次确认安装身份、匿名拒绝、服务状态和配置摘要／0600 权限。

| 独立审计原件（相对上述审计目录） | SHA256 |
| --- | --- |
| `remote-evidence/activation.json`（存储原件） | `506bafbb830c81cc24190ef68e7e02caa1658b0de84ca47bcb4b5fff452c2871` |
| `remote-evidence/post-readback.json`（存储原件） | `b011b571cc740fb6ca3cebe08f6b8176d35c06e436b9d975230d435c4618b675` |
| `remote-evidence/validation/results.xml` | `0f0b4dd7f4107a8d8d3afcf9e79a6d49e1783eb5f7765b3ee214e44a9a5a18f0` |
| `fresh-readback.stdout` | `6377d44834c8d2e3350cf26f67b95fe909444b59d28bd5fa47b0ca41528617d7` |

审计只回读已授权原件并做一次 fresh 检查，没有重放发布阶段、备份或测试，没有下载数据库、数据指纹正文或 `.env` 内容；不是本人登录后的生产用户操作验收。

本轮本地验收使用合成家庭和旅行，证明页面至真实本地 API 的操作链。未验真实模型提供方、本人真实云账号／旅行资料、原生手机或实体电视；四图只覆盖实际滚动视口，不代表整页。查询和打开详情是不同次读取，不宣称它们是同一瞬间快照。
