# 本人账户分析：验收与发布记录

<a id="finance-analysis-release"></a>

**已于 2026-09-19 16:20:25（北京时间）激活，16:20:57 独立生产只读审计通过。** main `d135e124b67c43364bea813da843f50823d4a54c` 与受验 source `f25357f935d64774922efa68d42a2ba41bb18037` 同树 `1efb6a439fd8fdd95a1af5c4958296452ccfcb71`。以下分轮证据不能相加称为一次全套通过，也不表示本人真实金融资料或 A–D 完整场景已验收。

## 使用与金额边界

入口为「财务 → 我的资产账户 → 查看我的账户分析」。分析只覆盖当前家庭中本人明确选择的手动资产／负债账户；可查看期末已知金额、覆盖缺口、日期趋势、资产分类与流动性，登记原币资金进出，并对精确区间明确确认完整性。来源报告、持仓、共同荷包和付款账本不参与加总，伴侣与电视不能读取分析明细。

未知金额、零、旧估值和缺汇率分别显示。趋势使用同一组账户；完整折算但沿用旧估值的点用空心／虚线表示，真正缺金额或汇率处断开。沿用值不代表当天实际余额，当前分类也不代表历史分类。

两端有当天已知估值并完成区间核对后，才显示「扣除资金进出后的估值变动」。该数值是余额变化扣除已核对资金后的残差，不称交易收益、年化收益或投资回报。跨币种拆分资金进出、估值残差、参考汇率影响与舍入差额；所需报价缺失时保留未能计算。

读取报告不出网；本人明确「确认更新汇率」后，服务器才访问固定 ECB 官方公共来源。保留原币、估值日、报价日、来源与版本；最多向前沿用七天、币种对采用同一天 EUR 交叉报价。失败保留已有缓存，不自动交易、换汇或启动无人值守刷新。操作步骤见[账户分析](EXPO-FINANCE-ANALYSIS.md)，字段与规则见[API](FINANCE-ANALYSIS-API.md)及[参考汇率](FINANCE-FX.md)。

## 分轮验证与失败保留

| 范围 | 实际结果 | 覆盖与限制 |
|---|---|---|
| Windows 后端组合 | 258/258，零失败／错误／跳过，346.66 秒 | 固定组合 `5071857002f29ee69eb60cb92b59af7ac6ef9128`：分析 87、FX 65、原账户 81、分析导出 3、通用导出 5、迁移数据 17；真实临时 SQLite。四个实际应用模块与最终 source 字节一致，后续没有把该套件冒充在最终 head 重跑。 |
| 全新 Expo 构建 | npm ci、两次 typecheck、Node、web export 均退出 0 | 固定 detached source `f25357f`，全新依赖目录；最终 Node **23/23**，23 个导出文件。拒绝继承 EXPO_PUBLIC_*／NODE_OPTIONS，记录构建环境，逐项绑定 Git 前端输入与导出散列。 |
| 真实 Flask／SQLite／HTTPS／Edge | 3/3 场景，3 图 | 资金事件及区间核对、修正后失效与重启保留；真实提交回复丢失后的原回执恢复与另一成员拒绝；未知金额／缺汇率及响应式总览。合成数据，零 pageErrors、零外网请求，source／bundle 前后保持。 |
| 趋势补充浏览器 | 独立 1 场景，2 图 | 同源码和导出，CNY 18 个取样点，其中 15 个沿用值、17 条虚线；390／1280 CSS px 实际原图通过独立视查。与上述三场景分别记录，未冒称实线段已经有单独视觉证据。 |
| 实际 Linux 镜像 | 244/244，零失败／错误／跳过 | 2026-09-19 07:53:41 UTC 完成；分析、FX、原账户及三份导出套件，容器及验证命令均退出 0。迁移另由下一行真实容器演练覆盖。 |
| 合成两户三库演练 | 61→66 户内表，平台 9→9，通过 | 2026-09-19 07:54:50 UTC 完成；固定父镜像建立合成基线，全组停写备份、仅增五表、候选真实 app 启动再停止后核对旧数据／schema／序列、平台及合成 marker。新表为空；不是生产数据演练或完整生产控制器的原样执行。 |
| 固定 Linux 镜像读取真实公共 ECB | 203 条报价、29 个币种，退出 0 | 查询 2026-09-10 至 2026-09-18，于 07:59:46 UTC 读取；未挂生产数据卷、未发送账户数据。不证明真实账户覆盖或未来供应商可用性。 |

前三条浏览器场景由 [browser_expo_finance_analysis_check.py](../tests/browser_expo_finance_analysis_check.py) 执行，不伪造成功业务响应；丢失响应场景保留真实已提交结果后阻断返回。浏览器原件与五张图分别经非作者核对。此前仅全缺口图不能证明有值曲线，故另补上述趋势场景；该补充不重跑其它已通过场景。

第一次浏览器准入因 Windows 普通路径未枚举到长路径字体而失败（22/23）；原文件实际存在。保留失败原件后，以同源码、同构建的扩展路径重新校验并执行，未删除资源或放宽哈希规则。作者阶段的控件替身／异步断言失败、旧 Docker pin fixture 修订，以及旧 55→58 测试仍假定两张平台表的 `registry_tables` setup errors，继续保留于各模块说明和原件；没有把这些历史失败包装为一次全套通过，也没有放宽旧迁移检查器。

## 固定发布身份

此前生产基线为[本人订单关联库存](INVENTORY-SOURCES-ACCEPTANCE.md#inventory-sources-release)，本批包有 884 个 payload 文件（861 个选定源码及 23 个 Expo 导出），运行白名单 123 个文件。源文件计数与浏览器完整 Git 跟踪集合不是同一口径。

| 身份／原件 | 完整值或 SHA-256 |
|---|---|
| main / 受验 source | `d135e124b67c43364bea813da843f50823d4a54c` / `f25357f935d64774922efa68d42a2ba41bb18037` |
| 同树 | `1efb6a439fd8fdd95a1af5c4958296452ccfcb71` |
| `finance-analysis-package-r1/package.json` | `eebaec9fdf903591ce86844ff16912a0a79e050c662404afa4f9e907328a5e66` |
| `finance-analysis-package-r1/release-manifest.json` | `30d5fe729ab9c407c43d8de3fa0129acd9c1e8ec2aa3e9473c5fb5e2485cb5f4` |
| `finance-analysis-package-r1/release.tar.gz` | `fda188ab841374dd3bbef26045c465ccbc5b5c2434ac9ccce682c42e37490bdc` |
| 候选镜像 | `sha256:21625d6e2d9768ba48cca35100bb8bf02c1c4146afa6b7ad25b9b72cb559c1d2` |
| 固定父镜像 | `sha256:32905e70879d28f36b0e584d69f03434e4a1bf38e580c0ca1aeb1ed7ae3a3cc6` |
| 旧 manifest | `c4d5ecc38675e6d9d97569664cb8141d4cfd030f52c6086449b8ea8d84ebf080` |
| 最终 plan | `9c83d3a22e41a9d573ab68fea1031ed159027bcd3e459835e9555e6346c2d8e9` |
| 实际 `stage.json` | `aa3d42c7ac188d9c94240374300b48472913e2a354c16658a36567d0e356e304` |
| 实际 `activation.json` | `2ecf31d4543988635ce9e0611ab1ac1272b8d7ee7525297b29b279120a22c57e` |
| `finance-analysis-production-readonly-review-r1.json` | `2c1afe7d812e026477033bfc6e01bb3d4939ff8d3ef940759dfcfcbb4ebf948b` |
| 全新 Expo `build-evidence.json` | `4d93ff144a81fbf9ff04405b8fb5286aad05c4d627b90ea35b92cba5431eb281` |
| Linux `build.json` | `33c6eb942e742482aa135af8796735c20bf1c6d713fbe475ed529e46fd5bac99` |
| Linux `validation.json` | `70e7c80bd496f70fbcfdb61c1992c7af2319e06c26e236efd412c126e8eb220b` |
| Linux `rehearsal-result.json` | `7b6acb7d8508b4bd874aa519dd97f3dd0ddaf49429a2592d9fcccdb7c08c1e5f` |
| 浏览器三场景报告 | `2c0bd0b9f62eb077e9b94c0b2fe8921d3d64796732171160085704f4c11d77bb` |
| 趋势补充报告 | `730d30cf0cd70b9931cf6c97265073e333467b18227d42e605bd34ae7a03f5ee` |
| ECB 响应正文摘要 | `4b3018feeea36332f4f08c58c70bd84d181a0f62fcf55c52ebc1ca49a86912e0` |

原件留在私有 `family-dashboard-access/finance-analysis-reviews-r1/`、`finance-analysis-reviews-extra-r1/`、`finance-analysis-linux-originals-r1/`、`finance-analysis-production-originals-r1/`（16 份生产 JSON 原件）；独立生产审计为同根目录 `finance-analysis-production-readonly-review-r1.json`。正式构建和浏览器原件还保留在 `worktrees/asset-analysis-build-r1/test-results/`。源码仓库不提交截图、真实账户、数据库、环境或密钥。

## 迁移、导出与实际发布

候选目录为 `/opt/family-dashboard-candidates/finance-analysis-66-20260919-r1`，实际发布目录为 `/opt/family-dashboard-releases/finance-analysis-66-20260919T081850158134Z`。stage 与 activate 实际退出 0，七个激活阶段完成；激活原件完成时间为 `2026-09-19T08:20:25.220120+00:00`，独立审计为 `2026-09-19T08:20:57.296276+00:00`。本批固定 `order-inventory-r1-finance-analysis` 起点已消费，不得重放。

本批只增加 `finance_account_profiles`、`finance_account_cashflows`、`finance_account_reviews`、`finance_analysis_operations`、`finance_fx_rates` 及声明索引，平台保持九表。完整备份覆盖注册库、默认户及全部注册家庭；停写期间核对所有旧表、行、列、schema、序列和原成功成员 marker。生产实际为一户两库，户内 61→66、平台 9→9。`before`、`migrated`、`after`、迁移 attempt／result 与新 app 启动保全原件相互绑定；旧 61 表的全部行、schema、序列及平台逻辑保持，`after` 与 `migrated` 完整逻辑摘要一致。五张新表为空只指迁移后及新 app 启动再停写核对的时点，不声称目前运行中的新表仍为空。

| 生产数据证明原件 | SHA-256 |
|---|---|
| `proof/before.json` | `e8c083c7e84dac096caed89061df036946c40c118a3f2451c87146bad81b7bb6` |
| `proof/migrated.json` 与 `proof/after.json`（同字节） | `ac490783af87d7a52a478822fc593ac0c7ae9a0bd9204cf1dd48763a209bbdbe` |
| `proof/migration-result.json` | `bdb51ee9d4a3f009be9545e9984cdd81524cd816ac4b2e9e0bebd587a89d781c` |
| `proof/result.json` | `663af06ea9f37424e512ca4ae028af90cfc1230bc77a6ec54885937c85b9cf48` |

16:20:57 的独立审计逐项匹配 884 个包文件、app／sync／media 各 123 个运行文件和 75 个正常 TLS 静态资源，20 个匿名受保护接口均返回 401。app、sync、media、web 当时均 running、零重启、未 OOM，app healthy；备份 timer active。原 `.env` 字节、服务环境键值、原 web 镜像、成功成员 marker 及完整两库备份保持。审计未登录、未返回环境值或数据库内容，没有直接打开活动业务库；数据保全结论来自已完成的停写及启动证明，健康结论限于该观测时点。

本人 ZIP 新增分析资料、资金事件、区间核对和最小操作摘要，`includeShared` 不扩大到他人数据。公共报价独立导出，最多 10,000 条并明确总数／导出数／截断覆盖；不承诺据此重建全部历史报告。失败和恢复规则见[发布合同](FINANCE-ANALYSIS-RELEASE.md)。

## 尚未验收与未实现

本批发布不包含并行开发的 AI 已有旅行改期。本人真实金融来源、实际账户资金事件和区间核对尚未验收。第三方银行／券商连接、自动持续刷新、实时行情及交易级收益计算没有因本批实现；估值残差不能替代它们。全量金融覆盖、本人真实跨家庭操作、云端写入和实体电视也不能由这些测试推断。

**A–D 本人真实完整端到端验收仍为 0/4。** D 的合成连续链 6/6 与本人 Google Photos 保存 5/5 各有独立证据，不能折算为整场景通过。此文档增量不改变已冻结运行源码或发布包身份。
