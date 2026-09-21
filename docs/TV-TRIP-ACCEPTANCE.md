# 电视单趟旅行回顾：交付与验收

<a id="tv-trip-release"></a>
<a id="tv-trip-candidate"></a>

**已发布。** 2026-09-21 08:03:18（北京时间）激活、08:03:49只读回读通过，生产非作者独审已通过。实际运行源码 `d4346d34ed5271699f2cffac7c29aa098edc8a07`，77张户内表／9张平台表、五服务。开发基线为 `904fde5665b6f5063ac90f9c752556a70daeb108`；生产由上一版[助理清单](ASSISTANT-LIST-ACCEPTANCE.md#assistant-list-release) `e8f0427` 的75/9完整备份并迁移。后续文档提交不是生产source。

[操作与恢复](TV-TRIP-USER-GUIDE.md) · [接口合同](TV-TRIP-PLAYBACK.md) · [迁移准备](TV-TRIP-MIGRATION-LINUX.md)

## 已完成的分段验证

| 固定范围 | 实际结果 | 不代表什么 |
|---|---|---|
| API `3794a8a` | 94个唯一用例分轮最终通过并独审 | 旧fixture失败保留；不是最终Linux选择的执行结果 |
| UI `6fd938d` | 40个唯一Node用例分轮最终通过，两组tsc通过并独审 | 受控请求与真实TSX处理器，不是实体电视验收 |
| 构建 `add881ed` | fresh npm ci、双tsc、23文件Expo导出退出0；170前端＋9补充输入经最终包校验复用 | 复用构建不等于后续后端改动已再次浏览器执行 |
| 浏览器R3第二场景＋R4第一场景 | 两条唯一流程分轮通过；六张成功截图中五张唯一图经根实际视觉审查 | 不写成一次全绿2/2，R3整轮仍失败；仅虚构家庭、本地HTTPS／Flask／SQLite／Edge |
| TVP `dc275dc` | 24项真实Flask／SQLite通过及根独审；SQLite authorizer证明TV元数据GET不读preview／video BLOB，两次快照仍拒绝撤权 | 是浏览器之后的独立增量；随后在最终镜像执行24项回归及下列容量检查，没有同头浏览器 |
| schema与本地迁移 | schema专项32、完整API接缝5、本地演练R1与完整API R2各10分别留证；R2含8段真实闭合程序及完整75／非空77恢复 | 不累计成一次全量；实际Linux结果单列在下方 |
| TVL `818c34e` 准备 | 运行源 `aa55f3e`，历史源 `e8f0427`；实际输入280文件（279项载荷＋input），独审通过 | 工具头、runtime头和最终镜像身份分别核验 |
| 最终镜像构建与Linux | `d4346d3`／`3c55bfba…`：118/118、零失败／错误／跳过，137运行文件、60个实际 `/app` 模块及1279份源码前后相同；非作者独审通过 | 精确118选择，不把单独排除的FFmpeg节点记作skip或Linux通过 |
| Linux容量 | 同镜像、384MiB、零swap；四个真实Flask WSGI请求全200，重叠0.514秒，2000条媒体／100站／两TV，scan6；测量请求0媒体BLOB，78张含SQLite内部表的摘要保持，仅归一会话last_seen | 累计cgroup峰值236294144字节（225.3MiB），进程RSS峰值121999360字节；不是四请求独立增量峰值、网络HTTP吞吐或解码负载 |
| Linux十阶段迁移 | 同候选镜像执行75→77／平台9、两户三库、部分失败拒重放、完整组恢复与非空77；十阶段退出0、父服务不变 | 199原件经非作者独审；实际隔离合成数据，不是生产恢复 |

浏览器R3实际源为 `526a0784885d4f5888f2d53bd4b62d11e1ad86c8`，R4为 `6853e06a8743afe20b3b3932194643bd3a23675b`。两者运行代码均为 `add881ed6a7d455e2743ce2affa6cf8b931b47d2`，工具修订不替换业务成功响应。后续 `dc275dc72d3cf1db357f4c2394577cef3b928a25` 只优化TV元数据读取，单独保留旧BLOB读取失败反例与修后24项；当前组合未冒充浏览器实测源。

R4第一场景覆盖390手机明确开始、1920电视路线分页及真实短视频解码／ended、暂停／继续／下一项／返回看板、暂停后刷新及另一台独立route-only电视。R3第二场景覆盖1280未知结果：原请求未提交和已提交丢响应两种恢复、原回执GET、刷新后明确重新预览、两台设备隔离，以及身份／路线／媒体撤权与删除旅行不回退全相册。原R1／R2及R3第一场景工具失败保留；R3整轮退出1，R4只补第一场景退出0。

成功场景原件记录源、导出和工具前后不变，并记录监听器停止及临时数据清理；不能据此改写R3失败场景原有的清理字段。六张成功图说明本地390／1280／1920布局可读、未观察到溢出；合成媒体和浏览器视口不证明实际Google账号、手机或物理电视兼容。

## 实际发布身份

| 项目 | 固定值 |
|---|---|
| source／tree | `d4346d34ed5271699f2cffac7c29aa098edc8a07`／`1bc76b9896873589de1597f6a9f50de097c1c5c5` |
| package | `d1784a3df473d41dbf9c2602e05d569b518b2cd88230d6e0db3afda29c0cecb1` |
| manifest | `f10633fd7688b8c53d6923933097f479cd53c07d44800c52ad2d8217cd387467` |
| 应用镜像 | `sha256:3c55bfbac391346af9f88253be65de96602f55179a2fee698fe694ab34e70b64` |
| 精确118选择 | `bbc1ccaa5bd00c8c0d53163d0ce62e3cd818f5c1e32587e431541bd4d3272302` |
| 已消费plan | `9b0c1f83668338810f981928418fdadf70e58e05e21161647f29ad62be3502a0` |
| operator | `cc9cdb1c7c1c5ae0014f797754d1f9c32c7209ad03033f072137379b04dd545b` |
| stage回执 | `8a70a44f403a42b0a2d46fa286013a3fc0c11758d2cb791839bbd02992910bf5` |
| activation回执 | `ed7eb32477bcc1021f8217df16cb7a5411e5bb7d40a8e91ba2bd09c198772910` |
| 生产readback.stdout | `802e5e70eac17efc8b34105e19b83f317ee4868a462c0a05eb2751e6cb970b5b` |

114个非Expo运行文件中112个逐字保留，原 `media_playback.py` 固定替换并新增 `media_trip_playback.py`；另含23个Expo文件。原解码与导入证据只沿未变路径继承，不覆盖本次改变的播放查询。本次容量检查以新镜像直接测量这些查询。

## 实际生产与恢复边界

实际release目录 `/opt/family-dashboard-releases/tv-trip-77-20260921T000117890882Z`。stage不写生产；activate消费一次计划，停止五服务写者和timer，完整备份一户两库，新增电视旅行范围与回执两表。旧75表的结构、行、settings和已有序列保留；新两表在app-only初始化后停止核对时为空。迁移后与app停止态的完整摘要一致；跨75→77的总体摘要本来会变化，不能写为迁移前后全摘要相等。

生产只读回读核对1279个安装文件、app／sync／media各137个运行文件及decoder原4文件。五服务running、0次重启／OOM；仅app和decoder有健康检查并为healthy，sync／media／web没有该health字段。HTTPS200且正常验证TLS，备份timer active、备份service inactive，环境文件保持原SHA及0600。回读不导入应用、不读取活库内容／用户行，也不重新验证备份SQLite字节或worker tick。

本次实际做了生产备份和迁移，没有生产恢复。完整75恢复和非空77恢复来自前述隔离合成Linux演练。本计划已消费，禁止重放stage／activate；后续更新须生成新计划，故障恢复按[固定发布合同](TV-TRIP-RELEASE.md)处理完整库组。非作者独审核对32份安全回执，并从原件重算旧75表、settings、序列和平台库保全；报告索引如下。

## 固定原件索引

下列路径相对本机 `family-dashboard-access/worktrees/`，仅索引未跟踪的私有原件；本提交不包含截图、数据库、凭据或运行日志。

| 原件 | SHA-256 |
|---|---|
| `tv-trip-combination/test-results/expo-tv-trip-combination/build-evidence.json` | `987b147be34065aeeba544001125db3227cfbb7d768fb90e61b2eeecfdd88336` |
| `tv-trip-combination/test-results/tv-trip-browser-independent-root-r1.json` | `fbf1fe4ec069e2d694b653bde993fcd202ceda61a6e344ef940f2c00724c0d57` |
| `tv-trip-browser-run/test-results/tv-trip-20260920T225552291184Z/result.json`（R3） | `af77f130eb3b29f19412fdc7de3fe1cad96f1c98a08e3269bd85539c25648608` |
| `tv-trip-browser-run/test-results/tv-trip-20260920T230858371938Z/result.json`（R4） | `2284a8f8266a9331b31dbfaa00ea3b12fbe1d9d04f7f09ac703deca14c60b592` |
| `tv-trip-projection/test-results/tv-playback-projection-independent-root-r1.json` | `19dbef33c7b6c50df8a5106ec24fe9848400cd63d8371f274298bad5766a50b1` |
| `tv-trip-browser/test-results/tv-trip-linux-rebind-review-r1/review.json` | `7481d862dacd1870232c92ca4079863583f07216e83bfb628508b57b24238f5e` |
| `tv-trip-browser/test-results/tv-trip-linux-build-independent-r1.json` | `99d0aaf3a2375a7cc3d9ca6cebd93220f6134b4070caebd587dc4b37f989a1f3` |
| `tv-trip-browser/test-results/tv-trip-linux-independent-r1.json` | `6d818691c0581fee3d4aaab4dd1fe332c54d3bf73331909216a338f127e90027` |
| `tv-trip-browser/test-results/tv-trip-resources-independent-r1.json` | `ee2e35de8ed3dcddf177e2695f2b218fd6a8a7c7d1d74881349cfd0aa6cda8f8` |
| `tv-trip-activation/test-results/tv-trip-migration-linux-independent-r1.json` | `da668344f4717792fccc1e7bb44a49ba3fe49a2122278e5b59f987c01c1b4dc2` |
| `tv-trip-docs/test-results/tv-trip-production-independent-r1.json` | `50cc64d543b95a582907f726061ff61bb7f674cd0f43dea4a96b18b105fce6a9` |

实际服务器原件位于worktrees同级 `tv-trip-release-candidate-r2/linux-evidence/`：`build/build.json` SHA `6dea9834cdce1288c75dcf682b9a47df88296f3dc1c1a8e0a562fdfed519fd96`；`validate/validation.json` SHA `9d4c41b9d33f1322e66078466b6250209495acb6ccd7c52e57ea701c9cc17e5e`；`validate/proof/tv-trip-capacity.json` SHA `ecdee8d8398da687c0b5aeffc2243eecc5f899ebb68745cc5ce52de8d8553153`。构建167份、验证1310份原件均已取回逐hash核验。迁移 `migration/result.json` SHA `da1b459b660c17a4263786858b2a16845f5494e6160d32d1ddfa41b15dd49966`，199份迁移原件已独审。生产原件保存在worktrees同级 `tv-trip-production-r1/retained-receipts` 与 `readback.stdout`，不提交原始回执或数据。

TVL实际准备输入位于上述worktrees同级 `tv-trip-release-candidate-r1/migration-input-r3/input.json`，SHA `89720ed46ea51d88df49c643a75bf4b4d9dd0862c580fc52cf0bc23193a59578`。API／UI／schema及本地迁移原件仍分别位于 `tv-trip-ui/test-results/tv-trip-api-independent-r1.json`、`tv-trip-api/test-results/tv-trip-ui-review-r1/review.json`、`tv-trip-release/test-results/` 与 `tv-trip-linux/test-results/tv-trip-linux-local-r1`／`tv-trip-linux-local-r2`。

## 未验范围

实际Linux118项、四个元数据请求的资源检查及十阶段迁移已有独审；生产激活与回读另留32份安全回执，生产非作者独审也已通过。这些结论不覆盖图片／视频并发读取、解码或任意家庭规模。外层主机内存采样仅作辅助观察；384MiB／零swap及无max／OOM／kill来自容器inspect和真实cgroup累计计数。

每台电视仍须独立许可，路线只能使用当前共享投影，坐标隐藏处不补线。最长15秒租约失效后清内容并停播，服务器拒绝后续未授权读取；已发出的像素不能追回。本人完整A–D验收保持 **0/4**，真实云与实体电视仍待用户条件允许后验证。
