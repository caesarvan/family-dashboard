# 旅行路线：使用与分段验收

<a id="journey-routes-release"></a>

**2026-09-19 22:56:47（北京时间）已上线，22:57:29 独立只读审计通过。** R2 正式 Expo 构建、四场景真实临时浏览器和视觉核对、固定镜像 Linux 189 项零跳过及合成迁移／恢复演练分别通过。实际生产一户两库完成户内 66→69、平台 9→9 保全；四服务运行，app 健康、0 重启。A–D 本人真实完整验收仍为 0/4，真实云写入与实体电视另验。

## 使用路径

1. 在「旅行」打开已有旅行详情，进入「旅行路线」。没有地点时，点「前往旅行地点添加」，登记有权访问的旅行地点后返回。
2. 点「新建路线」，填写名称、添加站点并调整顺序。同一地点可以重复加入，最多 100 站；默认「仅我自己」，核对后保存。
3. 地图默认聚焦可见站点，编号与列表顺序一致；邻近或重合站点合并显示编号，完整顺序仍可在列表查看。可切换「查看全图／聚焦路线」。连线只表示计划顺序，不是导航、距离或实际走过的轨迹，不会修改到访状态。
4. 需要分享时选择「家庭共享」，逐项核对地点名称和坐标共享范围，再明确保存。私人地点不能加入共享路线。其他家庭成员在「家庭共享」查看，只读；作者也只看到共享投影，不会借路线重新暴露原始精确坐标。
5. 已保存路线可点「查看旅行照片」，再「返回旅行路线」。照片沿用原有许可与旅行关联，不按路线地点推断归属，不授予电视访问权。

只有路线作者可以编辑或删除，删除需要确认；删除路线不会删除地点、照片或到访记录。地点撤回、删除或变得不可访问时保留不可用槽，隐藏其名称和坐标，相邻线断开，不跨缺口连接。已有缺口可按合同保留；从私人改为共享前须明确移除不可用槽。

## 冲突与恢复

- 保存遇到版本变化时保留草稿，依次使用「读取最新内容」和「按当前地点核对草稿」，检查名称、权限与顺序后再保存。
- 请求结果未知时先核对原操作；找不到回执时可「按原内容重试」，使用原内容和原请求编号。不会自动换编号重建或将未知结果当作成功。
- 仅当原样重试得到相应版本冲突、同一授权地点或路线的当前版本严格大于原期望版本，且再次核对原操作仍无回执时，才显示「保留草稿并重新核对」。其含义是“原内容的版本已过期；这次重试未保存”，不表示原编号已封存或原操作已取消。新回执优先；不能取得该证明时继续核对原编号。
- 切换成员／家庭、撤权、后台或失焦、离线时清除可见私人结果；返回后重新核对身份并读取。草稿与待核对请求只存在当前身份的内存中，不写 URL 或浏览器持久明文存储；不承诺关闭页面后仍能恢复未保留的请求编号。

## 固定发布身份

这里的 SHA 均为完整 SHA-256；Git source／tree 为 Git 对象 ID。验收附件未提交数据库、环境值或私人业务内容。

| 项目 | 固定值 |
| --- | --- |
| 最终包 source | `a9d3261116a5ad83fafb28ebda168bcd628367b4` |
| 最终包 tree | `c82b4e24a4e8093290611ac5e09701cb7f406c83` |
| 发布时 main（与最终包同树） | `eb9d28f1fad710bc32d9fc3703a3b3499c4643be` |
| R2 构建／浏览器 source | `a5e295d7cc0e7e2ce57240319165cdc1dc0899c6` |
| R2 构建／浏览器 tree | `b1e99bece5da892a8d7c6378a389874bd84142ae` |
| `package.json` | `c54dec688fbe99fef64b00ec92344d599259e134f328dbe49f0315b397dd22ef` |
| `release-manifest.json` | `0ec456641fc66d9e5a71c067e7731479fa5fd6fb7a05aa4ee84b1b27b5e7b070` |
| `release.tar.gz` | `f4d603689f0691f3096961ffd88e0619e56e70ef0df11d87b667f5e34eb5fb05` |
| R2 Expo 构建证据 | `df862b82159383a44c1aa2aa41d6937bb14bdfd4279c468fe97a313fbf220c09` |
| 生产运行镜像 | `sha256:9a966634bb220e7ce2a071fa130f011414b4c413eeecac0f9b3d3eccd5fb5bbc` |
| Linux 镜像构建原件 | `8d2537bfb682825e8084b446ee5ea107ee9640c382fc6d85cd622d67caf1dadf` |
| 最终发布计划 | `4564260d0272d6652fd07060fdefe20dc02082ba5f1e0926ddcd8ecefe56f493` |
| stage 回执 | `ec88fc33e72d41a7b0a85c50c56df524b609d8889592012b0ac9f05617a4e57c` |
| activation 回执 | `b1574b960859177efd335dd8ce62c47c53afb254e232f086b6a2c15731045594` |
| 独立生产只读审计 | `a7742fb97173fcf3024c4a81ea85cfc433067af6939ade507a66447c9d147e61` |
| 实际 release 目录 | `/opt/family-dashboard-releases/journey-routes-69-20260919T145500916670Z` |

包清单为 **942 文件、127 运行文件、23 Expo 导出文件**。最终包比 R2 构建／浏览器 source 仅增加 Linux 演练及其测试两个文件；两者 **Git tree 不同**。独立组合审查核对了前端、业务运行输入及原件的字节适用性，不将旧 source 的执行改写成在最终 source 重新执行。此后的纯文档提交也不改变该运行包身份。

## 本地与浏览器证据

各行是不同范围，不相加为“总通过数”，也不按测试数量估算产品完成度。

| 范围 | 实际结论与边界 |
| --- | --- |
| API 与真实 app 接线 | 独立接线组合专项 67 项通过，0 失败／错误／跳过；包括正常 app 注册、路线 API、导出与精确 69 表。使用临时合成数据。 |
| R2 fresh Expo | 独立目录 `npm ci`、app TypeScript、测试 TypeScript、Node、Expo export 五阶段均退出 0；Node 73/73，0 失败／跳过；123 前端输入及 3 补充输入与 Git 原件匹配，前后不变，23 导出文件逐一核对。 |
| R2 真实浏览器 | 四个独立场景通过，四张 390／1280 图；真实临时 Flask／SQLite、loopback HTTPS 与浏览器 HTTP，无伪造业务成功响应。页面错误、外部请求、模型调用均为 0；监听与临时目录清理完成。 |
| R2 视觉 | 已实际查看四图：路线默认聚焦，重复／邻近编号可读，缺口不暴露隐藏站点，不出现横向溢出；移动与桌面地图高度受控。全图切换由组件测试覆盖，未另作浏览器视觉验收。 |
| 本机迁移专项 | 独立组合 20/20，0 失败／错误／跳过；真实临时两户三库，五张已有分析表非空，验证迁移、实际 app 启动、漂移拒绝、失败恢复与非空路线／回执恢复。此行不是 Linux 或生产执行。 |

R2 浏览器四个场景分别覆盖：

1. 私人路线创建、重复站点、键盘排序、读回与真实 app 重启；旅行照片往返，原地点与到访事实不变。
2. 明确共享、伙伴只读、作者与伙伴相同共享投影；坐标粗化、撤回中间地点后的缺口及撤回路线后的拒绝。
3. 真实并发 409 保留草稿；真实提交后丢失响应，通过原回执恢复。另一次未送达请求经原操作 404、地点版本递增、原样重试 409，再经版本证明与第二次 404 显式保留草稿核对、重新保存。
4. 后台／失焦／离线隐藏，真实切换成员后迟到的私人响应被丢弃，数据库无额外改动。

主要原件位置相对于本地 access 根目录；worktree 与附件原件保留，不是仓库内的生产业务导出：

| 原件 | SHA-256 |
| --- | --- |
| `worktrees/journey-routes-build-r2/test-results/journey-routes-build-r2/build-evidence.json` | `df862b82159383a44c1aa2aa41d6937bb14bdfd4279c468fe97a313fbf220c09` |
| `worktrees/journey-routes-ui/test-results/journey-routes-build-r2-independent-review.json` | `55eb525fdced7cf36b862ea346937757645864741dda7b0a080e88ecd18fa0f9` |
| `worktrees/integration/test-results/expo-journey-routes-20260919T142013903170Z/result.json` | `20bc4142ccfb610c94628f3d172f96bab3fc810d87f5ae5ebe4ec74787597d96` |
| `journey-routes-browser-root-visual-r2.json` | `e8c9dc9c269d3175b451ec278b97e8c04d696e82f04636b04827a0650ecc60c3` |
| `worktrees/github-handoff/test-results/journey-routes-local-combination-independent-review-r2.json` | `8b84e764308e50caffe9a2bed05fc97fcabd559613a4cd763037f1b35f9aa2f2` |
| `worktrees/integration/test-results/journey-routes-wiring-r1/result.json` | `e868744ea1892e5df3911ff61020952115d927bac1aa868e282f2a7b3689cff7` |

组合审查结论为 `PASS_LOCAL_COMBINATION_LINUX_PENDING`，只说明该审查当时的本地范围。浏览器外层退出 0 来自执行 session `37695` 的完成记录；未另存的 stdout 不伪列为附件。

## Linux 验证与生产发布

固定镜像验证进程于 **2026-09-19 22:31:16 至 22:37:28（北京时间）** 执行并退出 0；JUnit **189 通过、0 失败／错误／跳过**，全部证据文件 SHA 逐一匹配，非作者独立复核通过。完整原件为 `jr-linux-validation-r1/validation/validation.json`，SHA-256 `a3fbb04cc7e60cbd9cfd3433529cf0ed26c7d8652d62d4f13e7858c39060cfda`。

首次下载在 Windows 深路径解压中断；原压缩包 `journey-routes-linux-results-r1/validation-originals.tar.gz` 保留，随后仅在本机重新解压到上述短路径。原目录的 `validation` 残留不是完整证据，Linux 测试没有重跑。

Linux 合成演练于 **22:36:06 至 22:37:05** 退出 0，约 59.2 秒。`journey-routes-linux-results-r1/rehearsal/result.json` SHA-256 为 `8a79aca01ff53e70d6bcdc9989cf654c48641ecf8d126d67c3bfc02db54b9ea9`。演练使用两户三库，将户内 66 表升级为 69 表，平台 9 表保留，已有五张分析表非空；覆盖旧 66 表内容恢复、新 69 表非空路线／软删除／回执的实际 app 重启及独立内容恢复。

演练是隔离的合成数据库内容恢复：使用合成 marker，不是完整生产 controller；为精确比较保留会话，恢复后的服务没有启动。它不代表生产切流或完整灾备已验收。

最终计划经非作者审查为 `PASS_READY_FOR_STAGE` 后执行。stage 与 activation 实际退出 0；**22:56:47.779250** 激活完成，**22:57:29.002781** 独立只读审计通过。发布时 main 与受验 source 同树；GitHub PR 合并与生产激活分别核对，合并本身不视为上线。本次计划已消费，不可重放。

生产审计核对了 **942 源码及导出文件、127 运行文件、75 个正常 TLS 资源、3 个页面入口和 23 个匿名 GET 拒绝**。新增路线集合、单条详情和操作回执三个匿名 GET 均为 401；这不代表已在生产执行登录后的路线 POST／PUT／DELETE 或本人旅行验收。app／sync／media／web 均运行，app 健康、各服务 0 重启，备份 timer 恢复活动。

完整停写备份覆盖实际一户两库，核对升级前、迁移后及真实 app 启动后保全回执，户内 66→69、平台 9→9；原有数据、角色、环境映射与成员迁移 marker 保持。审计核对保留备份和回执，不读取活动数据库，也不输出数据库或环境内容。三张新表为空只用于迁移与首次启动校验，不作开放服务后的永远为空断言。

| Linux／发布原件 | SHA-256 |
| --- | --- |
| `worktrees/github-handoff/test-results/journey-routes-linux-build-rehearsal-independent-review-r1.json` | `d7e2f83126cca718a4a2c99b33cc942157c8444aa3f78543b0007baf8f8e84e1` |
| `worktrees/github-handoff/test-results/journey-routes-linux-validation-independent-review-r1.json` | `f2fe5c08a0748637d32cb5edae9f159193b77d6a6b50aab427546f65724c2b7b` |
| `journey-routes-final-plan-r1.json` | `4564260d0272d6652fd07060fdefe20dc02082ba5f1e0926ddcd8ecefe56f493` |
| `worktrees/github-handoff/test-results/journey-routes-final-plan-independent-review-r1.json` | `dedbf3cf14796df8dfdab7d467f64e66fc139e88dbcd343bb07d87d97ec409f3` |
| `journey-routes-stage-r1.json` | `ec88fc33e72d41a7b0a85c50c56df524b609d8889592012b0ac9f05617a4e57c` |
| `worktrees/journey-routes-release/test-results/journey-routes-production-readonly-review-r1.json` | `a7742fb97173fcf3024c4a81ea85cfc433067af6939ade507a66447c9d147e61` |

activation 原始执行输出保留在 `journey-routes-final-r1-activate-transport.{json,stdout,stderr}`；审计中的 `receipts["activation.json"]` 及其他回执是脱敏投影与原件哈希，不能把投影重新编码后当作原始回执文件。上表首份 Linux 构建／演练审查当时仍等待测试验证，后续 validation 审查给出 `PASS_LINUX_BUILD_VALIDATION_AND_SYNTHETIC_REHEARSAL`，不改写早期审查结论。

## 保留问题与验收边界

R1 浏览器业务四场景通过，但实际看图发现世界全图下编号重叠、手机文字过小和桌面地图过高，不能算视觉通过；已在独立视口修订后执行 R2 fresh 构建与四场景复验。更早审查发现的测试器默认参数重复会在 HTTP 前抛出异常、Windows 长路径辅助检查清理失败及首轮旧表数断言均保留原记录，不以最终通过覆盖历史问题。

**A–D 本人真实完整验收仍为 0/4。** 本轮使用合成旅行、地点、成员和照片来源作本地／浏览器／Linux 验证；未替本人真实旅行操作，未调用真实照片云源，未完成外部日历写入、实体电视或完整场景 A。路线没有自动导航、自动到访认定或照片归属推断，也不增加电视许可。

[前端交互与保护](EXPO-JOURNEY-ROUTES.md) · [API 合同](JOURNEY-ROUTES.md) · [迁移与发布流程](JOURNEY-ROUTES-RELEASE.md) · [交接入口](HANDOFF.md)
