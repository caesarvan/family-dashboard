# 助理预算与支出查询：集中验收

<a id="assistant-finance-query-release"></a>

**已于2026-09-19 19:42:01（北京时间）上线，19:42:33独立生产只读审计通过。** 本批增加本人预算／支出、明确共享消费及手工公共快照的只读查询。生产实际一户两库保持66/9；本次线上审计仅验证安装与匿名拒绝，不代表本人真实查询或再次实际模型调用。A–D 本人真实完整端到端验收仍为 **0/4**，本人线上财务操作和实体电视仍未验收。

使用步骤见[Expo 查询](EXPO-FINANCE-QUERY.md)，接口与金额口径见[API 合同](ASSISTANT-FINANCE-QUERY.md)，发布及故障停止边界见[发布工具](ASSISTANT-FINANCE-QUERY-RELEASE.md)。

## 本批行为

从「更多 → 家庭助理」输入问题或点「查询支出」，进入「预算与支出」。默认本地解释，省略条件时明确显示本人／北京时间本月；可明确允许模型理解额外口语。金额来自当前授权账本，按原币分组、扣除对应退款，不把订单、转账或确认重复算作消费。全部预算与分类预算不相加，未记录支出仍是覆盖缺口。

共享查询只显示已有共享汇总允许字段；公共荷包只显示已确认的人民币手工当前快照，未知值不显示为零。身份切换清除旧问题与结果，财务页面返回和前台恢复按相同范围本地刷新。查询不创建计划、不写账本／预算／公共余额，不调用银行或电商接口。

## 固定运行身份

| 项目 | 值 |
|---|---|
| 合入 main | `520781d7c9a9872fd006d929e9b578bbe9c611f8` |
| R2 source | `68631bfe02d822434e8557aa247f0148d4e9d7dd` |
| R2 tree | `136dec1288fe7fe5ea94b59b0ea2282de32c8ebf` |
| R2 package SHA-256 | `509fe53dc0c5504aa4c64aa60ff9ab293458110687135123481a66627c080f78` |
| R2 manifest SHA-256 | `21e0588d81730eda5e45fad16f25e9599e5f4f8bbb491b2aa65320d33d6b8270` |
| R2 archive SHA-256 | `44f87501e38ac66663bafd41868911d897625c984ff882a8224298ba19dfe1a2` |
| R2 selection SHA-256 | `7878cce9d32674e67f5f80a6bca96dcdaf3406d483e2c18e879b78524d1bc138` |
| Linux 镜像 | `sha256:73f18b95d870e49296320347d0988bb0232f120c9481d5f881bba0ad2748abac` |
| 最终 plan SHA-256 | `2a8e6cb9dff90c9b245b8568103c8882c8057999f5c425cb5fdd94c088c4e4ff` |
| stage SHA-256 | `13d623c2e89cfdbf5678a80501a826c03f4a8bb568e3782908f97ef1a6e700b5` |
| activation SHA-256 | `223b49c0b9e7921f419f6387f7f70157f01f7e47252eb30bf85c6c213a83684c` |
| 正式发布目录 | `/opt/family-dashboard-releases/assistant-finance-query-66-20260919T114029600122Z` |
| 选择范围 | 8 模块、298 个精确节点，空跳过白名单 |
| 包内与读回覆盖 | 922个源文件、126个运行文件、23个Expo导出、75个HTTPS静态资源 |
| 数据合同 | 户内 66→66／平台 9→9，无新表或迁移；原分析五表可非空 |

正式 Expo 构建基于 `8fedd4f698ecf6d79a74719f41a3baf1a66f8ab4`／tree `79467735898eeb09ecfafcda9960290b442cfd2a`。R2 保留该前端字节和构建产物；后续差异为已审导入会话缺引擎修复、对应测试／发布范围及浏览器测试器修订，不声称重新构建了前端。

## 分段验证与失败保留

以下各轮范围不同且可能重叠，不相加为独立测试总数，也不替代本人完整场景 B。

| 阶段 | 已观察结果与边界 |
|---|---|
| 正式 Expo 构建 | 全新依赖安装、产品／测试两项 TypeScript 检查、64/64 Node 行为测试、Expo web 导出共五阶段均 exit 0；120 个前端输入、23 个导出绑定。不是本人设备验收 |
| 真实模型第一次 | 单次 NVIDIA 请求，query 正确但 scope 原文证据过长，严格拒绝为 502；合成账本不变 |
| 真实模型第二次 | 单次请求，原文证据正确但 query 使用中文范围／月份，仍严格拒绝为 502；未放宽解析器 |
| 真实模型第三次 | 明确规范化字段与原文证据两段合同后，单次请求返回 200 ready，合成预期金额核对通过；每次均独立保留原件。只发送合成问题，业务写入为 0，不代表私人财务或生产模型验收 |
| 浏览器早期失败 | 业务场景运行后，身份场景清理临时 SQLite 遭遇 Windows 文件占用，整轮失败；另有长路径预检问题，均保留，不能算完整通过 |
| 浏览器修订及 R2 | 固定 R2 source 上三场景通过：预算／月份导航；无记录／歧义／搜索；身份与前后台。真实临时 Flask／SQLite／Edge 请求，0 页面错误、0 外网、0 provider 尝试，临时 fixture 清理完成 |
| 视觉检查 | Root 实看 390px 与 1280px 两张稳定截图，原币分列、金额与按钮可读，所见视口无横向截断；范围仅截图可见区域，不是整页滚动或实体设备验收 |
| Linux R1 | 296 项中 294 通过、2 失败、0 跳过。既有导入缺会话引擎用例暴露初始化顺序问题；没有删用例或降低 503 预期 |
| 缺引擎修复 | 原两个失败先在未修改源码上复现；一行数据库初始化移至引擎检查后。修后本机原导入会话56项与查询权限14项共70通过，0失败／错误／跳过。原导入测试逐字节保持 |
| Linux R2 | **298/298，通过，0失败／错误／跳过**；8模块精确节点、126个runtime文件、922个包文件及49个实际导入模块散列绑定。R1全部296节点保留，原两项失败现已通过；仅增加两个缺引擎查询用例 |
| 生产安装与只读审计 | 实际一户两库66/9保持；922源文件和三个应用服务各126运行文件匹配；75个HTTPS资源匹配，20个既有匿名GET、新查询GET及无cookie空JSON POST均401；四服务running、app healthy、0重启 |
| Linux R2 数据演练 | 两户三库、66/9，既有五张分析表预填非空记录；完整备份、新app实际启动后行／schema／序列与marker核对通过。使用合成marker替换，`exactProductionControllerProgram=false`，不声称生产控制器原样演练 |

模型实际提供方为 `nvidia`／`us/azure/openai/gpt-4o-mini`；三次各仅一次 provider 和 HTTP 调用，没有自动重试。两次失败促成提示词澄清，未允许模型扩大身份／月份／分类范围或输出未经账本计算的金额。临时浏览器只走本地查询，不把浏览器通过冒充实际模型通过。

## 原件定位

`A` 指本地 `C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W` 指 `A/worktrees`。下列报告只作本地取证，原始 JSON、截图、stdout、临时数据库和配置均不提交 Git。

| 原件（相对 A） | SHA-256 |
|---|---|
| `worktrees/assistant-finance-query-ui/test-results/assistant-finance-query-production-readonly-review-r2.json` | `571afbe62c191018bab5c5d9ae63af1b12a4a73f7078a04f32bd3df17fe1575c` |
| `assistant-finance-query-package-r2/build-evidence.json` | `5c43132bea9f2628677def3d42edbb3d3355f5b7bc4c217d7bc263bd391a2bca` |
| `worktrees/integration/test-results/live-finance-query-20260919T103034847782Z/result.json` | `74ba06e6b23c4de9439f20a0d8362c35110fc518890909774176d3beb9b73749` |
| `worktrees/integration/test-results/live-finance-query-20260919T103548520379Z/result.json` | `adaea6588057017cb54cad4999bf97a2d1437b59b09bff2eebeacba3b33e0a3c` |
| `worktrees/integration/test-results/live-finance-query-20260919T103956280426Z/result.json` | `d27cf54c2150104515c277722586ff596ed5f10bba466cc1a198fc4ee92031cf` |
| `worktrees/integration/test-results/expo-finance-query-20260919T104645863103Z/result.json`（清理失败） | `1dbac3911c27b9a79ce730002e5af9b865499d1a505a520148011a0980242055` |
| `worktrees/integration/test-results/expo-finance-query-20260919T111247755309Z/result.json`（R2） | `94a937c1830fb9bd50564a65c6a1c1d2c6bb29ccf3d922950e9fa0131cb4fa87` |
| `worktrees/finance-query-session-guard/test-results/session-guard-verification-r1.json` | `c866194e25d4b3073a3300f517a3fc7ddf87710e23fa3250b78560fdd83f92f1` |
| `assistant-finance-query-linux-validation-r1/validation/validation.json`（294／2） | `b1438cb3647403921754057b22d4df994e172954a963248c2b42f72920981658` |

正式构建的命令、stdout／stderr 在 `W/assistant-finance-query-build-r1/test-results/assistant-finance-query-build-r1/`。早期浏览器用临时测试器适配取得的三场景报告 `expo-finance-query-20260919T105248690280Z/result.json` 保留其当时范围；最终 R2 以表中固定 source 的新报告为准。视觉原件为 `A/assistant-finance-query-browser-root-visual-r1.json`，对应的是早期稳定截图，不声称再次视查最终 R2 截图。

Linux R2原件位于 `W/assistant-finance-query-release/test-results/finance-query-linux-originals-r2/`。独立审查 `assistant-finance-query-linux-validation-independent-review-r2.json`（同worktree的 `test-results/`）SHA256为 `bfabfbd3af7d95f1ee2587efc329535c4ea8c64bd768a920edeccf40314a6a4a`；其中验证原件 `validation/validation.json` SHA256为 `d3215a02bc380f4395f7e82e99645390544631434a7974301a64472c44ee2977`。main同树记录 `A/assistant-finance-query-main-merge-r2.json` SHA256为 `d5f6ee14f0389c022c0f21feaaa607a96c2d04fc01c5601dbcec1622ea47d2aa`，该记录生成于实际激活之前，其历史 `productionActivated=false` 不被重写。

## 发布与未验边界

实际激活于 `2026-09-19T11:42:01.964312Z` 完成，外层传输及子进程退出0。原件 `A/assistant-finance-query-final-r2-activate-transport.json` SHA256为 `20a1ea62f3eb6da0c1f4f4935c55597b978a148535b213c12eb9fa9b49e05110`，与同名前缀stdout的SHA互相绑定。独立只读审计于 `2026-09-19T11:42:33.102666Z` 返回PASS，原件SHA见上表；其调用stdout与transport记录位于同目录 `assistant-finance-query-production-readonly-r2.*`。

本次完整库组停写备份及新app启动后的证明绑定了全部66张户内表、9张平台表的原行／schema／列／序列和marker相等；既有分析表允许非空，不假设活动库仍为空或后续无人修改。备份仍保留，原环境键值在服务器上私下比对保持，备份定时器active，web镜像保持。审计没有重新查询活动业务库，也没有返回数据库内容或环境值。新POST仅发送无cookie的空JSON并确认401，不含问题、财务结果或模型调用；没有登录用户验收。本次计划与固定基线已消费，不能作为下批发布重放。

这项能力不补齐真实付款／退款关联、完整来源覆盖和预算验收，也不替代此前本机真实订单导入的受限事实。私人账本不会发送给模型；本人线上交互、银行／电商连接、完整场景 B、真实云写入与实体电视仍须分别验收。
