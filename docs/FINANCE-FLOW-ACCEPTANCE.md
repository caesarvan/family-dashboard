# 通用账单收支方向列：使用与发布验收

<a id="finance-flow-release"></a>

**已于2026-09-21 00:26:30（北京时间）激活，00:27:04只读回读通过；非作者生产审计已通过。** 实际安装source仍为固定53ea，保持73/9和五服务，无DDL。此前线上为 [discovery 批次](DISCOVERY-ACCEPTANCE.md#discovery-release)。[PR47](https://github.com/caesarvan/family-dashboard/pull/47)功能代码已合main；[PR50](https://github.com/caesarvan/family-dashboard/pull/50)发布工具经审查合入integration；后续文档合入不改变实际部署source53ea。

## 最短操作路径

1. 从「财务 → 导入」选择本人 CSV／XLSX，使用通用支付流水；XLSX 先选择工作表。
2. 核对日期、金额、标题、币种四列；在「收支方向（可选）」选择原文件方向列，或保持「自动识别」。方向列不能与四个必填列重复，未知值不按金额正负猜方向。
3. 修改列后点「按所选列预览」，核对收入、支出、未知及重复／冲突提示，再「确认导入 · 仅本人」。旧预览不能直接确认新映射。
4. 返回账本核对预算和来源。同一文件重新导入不双记；方向与已保存记录不同会报告冲突，不能通过重新导入静默覆盖。需要纠正时核对原交易。

若保存结果不明，点击「核对保存结果」；不要重新发起同一导入。离线或身份不明时不继续确认。伴侣、其它家庭和电视不能读取个人账本。已知平台和订单解析保持原行为；本入口不连接银行、券商，不自动共享财务明细。接口见 [FINANCE-API](FINANCE-API.md#通用支付流水的可选收支方向列已发布)。

## 实际验证与限制

| 阶段 | 已有结果 | 覆盖边界 |
|---|---|---|
| fresh Expo | 固定 `9ee62cb`：fresh npm ci、两组 tsc、22项财务 Node、23项导出全部成功。157前端＋9补充＋1根目录测试，共167输入。 | 固定53ea候选逐字节复用这些输入与导出；不是新源码再跑一次构建。 |
| 本地浏览器 | 同一9ee62一次执行3/3、六图，非作者审查通过。CSV选择方向→重预览→私密确认→预算／去重；XLSX确认丢响应后原回执恢复；离线、身份切换及迟到预览隔离。 | 真实临时 HTTPS／Flask／SQLite 和虚构文件，不是本人账单、真实设备或生产操作。 |
| 发布工具 | 固定 `53ea3fd` 的33项新适配检查通过，另实际只读核验父版包、构建、已消费计划及三组资源原件。 | 这33项是发布策略／拒绝边界／录制 Docker 接缝检查，不是下面的33项财务后端测试，不证明真实生命周期又执行了一次。 |
| 新镜像与 Linux | 固定53ea/package44f8/imagecdbe实际构建成功；精确33项＝26项方向列＋7项相邻，0失败／错误／跳过／deselected／xfail。1198安装输入、135运行文件、58个实际 `/app` 模块前后绑定，独审通过。 | 隔离 Linux 功能容器为1024MiB；不证明生产384MiB下财务导入内存、并发或混合负载。 |
| 继承证据 | 112个非Expo输入仅 `finance_hub.py` 变化，其余111不变；三处已审财务函数外 AST 相同。原媒体、上传及重复提示资源保留原 source/image/map身份；旧73→73完整库组正常／失败恢复演练按未变生命周期继承。 | 没有新财务资源负载、任意混合峰值、新完整恢复演练或生产恢复证明；不将旧实测身份改成新候选。 |
| 本人验收 | A–D完整本人场景仍0/4，真实账号、手机和实体电视另验。 | 合成流程、Linux与部署均不能代替本人验收。 |

浏览器 stderr 保留一条 `Response.finished`／`Target closed` 异步观察警告；没有应用 traceback、HTTP 5xx、页面错误或外网请求。stdout与stderr无共同时间戳，不能推断警告精确时序或所有观察者均正常结束。旧测试宿主失败、继承读回的长路径失败及本地辅助脚本语法失败也保留；不改写成首轮全绿。

## 固定部署身份

| 对象 | 固定值 |
|---|---|
| Source／tree | `53ea3fdb571eae69154e61d264f3c3542631cb49`／`cf243a21008a73a421b3a4128ccd49af1f814b31` |
| Package／manifest | `44f8d8c3fd9a5a91e5cfde9e1893c89be345a2d5445b2636c77e3d5733e3466f`／`e6898a234eb21c20a28b08a9bc48241202380c3857210f18b0278ad02a3b0ed9` |
| 应用镜像 | `sha256:cdbe4702e9fc1b7557e8cefb84b664b6d8c369fb0d9788e0235ff426f3c18ac2` |
| 父版 | source `63dc63476b046856bf9893c19595e2971ebc13c7`，manifest `7b77dfbc5c3a1f132706817fa10fbbf0f01c022ce27207c58999df60b5645d3f` |
| decoder／web | `sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c`／`sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7`，保持原镜像 |

1198安装文件＝1175源码文件＋23导出；应用运行文件135，decoder原4文件。发布合同为73/9→73/9五服务源码更新，无DDL；业务变动限定已审财务模块和Expo导出，Docker／Compose／Nginx／依赖保持。本次单次计划已消费，禁止重放；后续变更需要绑定当时父版的新计划。

## 原件索引

以下均为本机忽略目录，原件不提交Git。`A` 为 `family-dashboard-access/`，`W` 为其 `worktrees/`；只记录证据身份，不含账单、账户、凭据或数据库内容。

| 原件 | SHA256 |
|---|---|
| `W/finance-flow-combination/test-results/expo-finance-flow-combination/build-evidence.json` | `9e84b1bc937f0c8b9a8dc7d4aaf729b3cd8d5845ca4d06f818565257af0d3638` |
| `W/finance-flow-combination/test-results/finance-flow-20260920T150130152959Z/result.json` | `0e73ee4be09923eef2a4834a18fdaafc39350b57ec15a89c981ad7517f74851b` |
| `W/media-video-usability/test-results/finance-flow-browser-independent-r1.json` | `e24fcb0504b997bcd8ef686ee8844f65f42f93f69cf35622de3a537554d38970` |
| `W/finance-flow-release/test-results/finance-flow-release-author-r1.json` | `88bfa8834f6cd9c0963a196c2400c107a543a7b934d9d81fe3bcd00d5dab470a` |
| `W/media-video-usability/test-results/finance-flow-release-independent-r1.json` | `e1dd74d1b4b544e62e65aadf15262ba2865a89d8b0316ec9018c600ff952a3ea` |
| `W/finance-flow-release-evidence/test-results/finance-final-source-reuse-r1.json` | `35d1d136a9ce7301b7d8f3c38a338ad2662f2d3eb9368122859d3b103b827c62` |
| `A/finance-flow-release-candidate-r1/linux-evidence/build/build.json` | `a880823a491b44e1568dd20c95026205e3e547f985ae0b6dce5e5bb51996e1e6` |
| `A/finance-flow-release-candidate-r1/linux-evidence/validate/validation.json` | `b6ea220bf4277f6bb360b5daa9815039a9e5072cb1dfbeeeefcb70c90152ad28` |
| `W/finance-flow-release-evidence/test-results/finance-linux-candidate-independent-r1.json` | `6e9de30c3152422a4513ba4fa828e8f1a02957df5e6a5ede77081dd13a31d59d` |

操作合同见 [固定发布适配](FINANCE-FLOW-RELEASE.md)。实际生产回执与非作者审计见下节。

## 本次实际生产结果

stage、activate和只读回读的原进程均exit0。激活完成于2026-09-21 00:26:30（北京时间），00:27:04回读通过；release为 `/opt/family-dashboard-releases/finance-flow-73-20260920T162441084645Z`。一户两库保持73/9，完整库组备份与app-only停止后的全部表、settings、sequence保全通过；逻辑摘要前后均为 `b1c9210c96e2b2da9503aaef52df696a0ee80991ffc42733fbcef52169060260`，没有迁移或DDL。

1198安装文件、app／sync／media各135运行文件及decoder原4文件与固定包一致；五服务running、无OOM和重启，仅app／decoder具备healthy健康检查。HTTPS正常TLS校验返回200，备份timer active；环境仅比较摘要及0600权限，未输出内容。

回读核对的是停写／备份／保全回执和当前进程、运行字节、TLS状态；不读活库、用户行或备份SQLite字节，没有运行恢复，也不证明worker业务tick、本人新导入或实体电视可用。与父版隔离恢复演练分开记述。

| 本次回执 | SHA256 |
|---|---|
| 单次plan（已消费） | `8185025cdb0a65cd8fd8f0e30c968c14e4bea1f4dbcec5100af6a3765f632c34` |
| operator／admission | `54b5484fa9fd88f98d364bdb59440fdac2f55c1ede50ec33afd172af6493248f`／`508ad2aec05503f48037ce44af00f4919a55efc52be6d0b735f7a0865dd0f599` |
| stage | `cbf7a08ba673d5262ba58bb9b239fb005c0912feaf2ecd95c4655354877b0307` |
| activation | `34faff028515449866c50eef391d2016129044e61c53e79c07c2b20a49771abe` |
| `A/finance-flow-production-r1/readback.stdout` | `e695fbd260c2d25a0765c89b209dfa7d5bf35ac9791bf8d54222ef290e70210a` |
| `A/finance-flow-production-r1/receipt-download.json`（25份安全JSON原件） | `92beeb72d1853dcc5de47d01842199b670f745c719f2e7ae0ac074b6352b8057` |

实际stage／activate／readback进程回执及上述原件位于 `A/finance-flow-production-r1/`，其中保全材料位于 `retained-receipts/`。非作者生产独审已通过，报告为 `W/media-video-usability/test-results/finance-flow-production-independent-r1.json`，SHA256 `0fd34df78ff372ab3589c75643743169b9ad802dba393572a8470af84fde2cfb`；审查读取实际回执，没有再次执行部署或读取活库。
