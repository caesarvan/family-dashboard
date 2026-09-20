# 电视单趟旅行回顾：候选验收

<a id="tv-trip-candidate"></a>

**候选未上线。** 本页整理文档基线 `2bb5fecd5ec4fbdfffe714a5498ef3c31f2c86b2` 已有证据。稳定主线基线为 `904fde5665b6f5063ac90f9c752556a70daeb108`；当前生产仍是[助理清单版](ASSISTANT-LIST-ACCEPTANCE.md#assistant-list-release) `e8f0427`、75张户内表／9张平台表、五服务。本候选目标77/9，尚无生产迁移或上线结论。

[候选操作与恢复](TV-TRIP-USER-GUIDE.md) · [接口合同](TV-TRIP-PLAYBACK.md) · [迁移准备](TV-TRIP-MIGRATION-LINUX.md)

## 已完成的分段验证

| 固定范围 | 实际结果 | 不代表什么 |
|---|---|---|
| API `3794a8a` | 94个唯一用例分轮最终通过并独审 | 旧fixture失败保留；不是最终Linux选择的执行结果 |
| UI `6fd938d` | 40个唯一Node用例分轮最终通过，两组tsc通过并独审 | 受控请求与真实TSX处理器，不是实体电视验收 |
| 构建 `add881ed` | fresh npm ci、双tsc、23文件Expo导出退出0；170前端＋9补充输入至文档基线逐字一致 | 复用构建不等于后续后端改动已再次浏览器执行 |
| 浏览器R3第二场景＋R4第一场景 | 两条唯一流程分轮通过；六张成功截图中五张唯一图经根实际视觉审查 | 不写成一次全绿2/2，R3整轮仍失败；仅虚构家庭、本地HTTPS／Flask／SQLite／Edge |
| TVP `dc275dc` | 24项真实Flask／SQLite通过及根独审；SQLite authorizer证明TV元数据GET不读preview／video BLOB，两次快照仍拒绝撤权 | 是浏览器之后的独立增量，没有同头浏览器或容量实测 |
| schema与本地迁移 | schema专项32、完整API接缝5、本地演练R1与完整API R2各10分别留证；R2含8段真实闭合程序及完整75／非空77恢复 | 不累计成一次全量；Linux UID及0400部分失败尚未实际执行 |
| TVL `818c34e` 准备 | 运行源 `aa55f3e`，历史源 `e8f0427`；实际输入280文件（279项载荷＋input），独审通过 | 仅准备，尚无Linux十阶段结果 |

浏览器R3实际源为 `526a0784885d4f5888f2d53bd4b62d11e1ad86c8`，R4为 `6853e06a8743afe20b3b3932194643bd3a23675b`。两者运行代码均为 `add881ed6a7d455e2743ce2affa6cf8b931b47d2`，工具修订不替换业务成功响应。后续 `dc275dc72d3cf1db357f4c2394577cef3b928a25` 只优化TV元数据读取，单独保留旧BLOB读取失败反例与修后24项；当前组合未冒充浏览器实测源。

R4第一场景覆盖390手机明确开始、1920电视路线分页及真实短视频解码／ended、暂停／继续／下一项／返回看板、暂停后刷新及另一台独立route-only电视。R3第二场景覆盖1280未知结果：原请求未提交和已提交丢响应两种恢复、原回执GET、刷新后明确重新预览、两台设备隔离，以及身份／路线／媒体撤权与删除旅行不回退全相册。原R1／R2及R3第一场景工具失败保留；R3整轮退出1，R4只补第一场景退出0。

成功场景原件记录源、导出和工具前后不变，并记录监听器停止及临时数据清理；不能据此改写R3失败场景原有的清理字段。六张成功图说明本地390／1280／1920布局可读、未观察到溢出；合成媒体和浏览器视口不证明实际Google账号、手机或物理电视兼容。

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

TVL实际准备输入位于上述worktrees同级 `tv-trip-release-candidate-r1/migration-input-r3/input.json`，SHA `89720ed46ea51d88df49c643a75bf4b4d9dd0862c580fc52cf0bc23193a59578`。API／UI／schema及本地迁移原件仍分别位于 `tv-trip-ui/test-results/tv-trip-api-independent-r1.json`、`tv-trip-api/test-results/tv-trip-ui-review-r1/review.json`、`tv-trip-release/test-results/` 与 `tv-trip-linux/test-results/tv-trip-linux-local-r1`／`tv-trip-linux-local-r2`。

## 尚未完成

最终118节点选择与容量准入须按冻结发布增量独立核验，本页不预报Linux通过数量。最终候选镜像验证、384MiB实际容量、Linux75→77十阶段迁移与完整组恢复、固定计划准入及生产回读均须取得各自原件后更新。旧媒体资源只保留原解码／导入范围，不能证明新增电视回顾负载；本地检查也不能代替Linux资源测量。

每台电视仍须独立许可，路线只能使用当前共享投影，坐标隐藏处不补线。最长15秒租约失效后清内容并停播，服务器拒绝后续未授权读取；已发出的像素不能追回。本人完整A–D验收保持 **0/4**，真实云与实体电视仍待用户条件允许后验证。
