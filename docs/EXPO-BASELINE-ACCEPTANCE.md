# Expo 本人资产来源报告验收

本批已于 2026-09-17 21:58:49（北京时间）发布，21:59:22 正常 TLS 读回通过；实际包和独立取证见下方[发布记录](#expo-baseline-release)。新版从财务进入「我的资产与来源报告」，只读取本人已存资产、负债、历史收入、消费观察与来源说明。资产与负债共享汇总仍沿原家庭资金口径；账户和消费明细不向伴侣或电视共享。

## 实现与限制

六个分类支持整类搜索和每页十条浏览。金额使用整数分，未知与零分开；外币保留原币，不混入人民币小计，不与持仓、交易账本或公共荷包重复相加。历史收入不推断为当前工资，记录日期、来源覆盖及消费观察更新时间分别展示。来源路径仅为文字，不能点击读取本地文件。

页面只调用本人 GET 与身份 GET。「重新读取来源报告」不会刷新邮箱或外部金融平台。后台、离线、离开及身份变化会清除私人内容和搜索词；重新进入须重新读取。返回财务保留已选月份，并核对当前身份重新读取原页面。

本批没有实现新版来源导入确认、完整资产账户管理或历史估值；高级来源更新仍用既有入口。使用与 DTO 约束见 [页面方案](EXPO-BASELINE.md)、[服务端读取](EXPO-BASELINE-READ-API.md)、[入口接线](EXPO-BASELINE-INTEGRATION.md)及[浏览器脚本](EXPO-BASELINE-BROWSER.md)。

## 独立分支与审查

起始基线 `7713ad1fd091d7390612c52d434b97e54e99f54b`。API `362051f911d517aa7bd2d944789c08200560157c` 经 Root 非作者审查；UI 最终 `78e64a38a52a80303ffd6c9f731fff434681bc32` 及 Root 接线 `228f837a47c56efee49e33cd9f9147ad6b1226ef` 经 API 作者独立审查；浏览器脚本 `a19c8c3524049530db7d09af1c7c709c4dc079be` 经 Root 审查。

UI 首版错误拒绝省略秒数的合法时间。审查者通过真实临时导入／GET 重现，最终修正增加带时区的省略秒、空格分隔、紧凑日期／偏移和 ISO 周日期兼容，并保留非法日期、无时区拒绝。客户端只归一化显示，不改写原记录。

服务端本人读取使用一致快照，并在读取结束后再次检查最初捕获的真实会话，覆盖 null 响应、过期、撤销、认证版本和家庭变更。没有新增接口或表。读取分支先将旧测试中虚构 actor 的检查改为真实成员／配对电视，并将八项来源测试暂改查持久化。后续导入会话分支已把整组来源夹具迁移为真实 app／登录，恢复这八处 HTTP GET；最终组合不再保留过渡的 stored_private 辅助函数。

## 实际验证

以下原件路径以私有 `family-dashboard-access` 为根；合成数据不进入版本库。

- **API：207 项通过，零失败／错误／跳过**，包含 28 项新会话专项、19 项基线、106 项来源桥接和 54 项消费观察。`worktrees/expo-baseline-read-api/test-results/baseline-read-r1.xml` SHA256 `1e2bfc6e5c172ff8e51d582f632c86eb8566967362cb72d1a80716256ec374a1`。源码采样开始于运行中，结束时散列一致；不宣称存在独立的启动前采样。
- **模型：13/13 通过**。使用固定 API `362051f…` 的真实临时 Flask／SQLite 导入及 GET DTO，含八种时间变体与 Python 时区结果对照。最终 `worktrees/expo-baseline-ui/test-results/baseline-model-r5.tap` SHA256 `58ce262fcc2e8a2028772e18da5c41c22ab014d13cb12b2e72d4e692be096d0b`。首轮连接未关闭及后续时间 fixture 不一致的失败保留，各轮不相加。
- **类型与构建：通过**。完整应用与 Node 测试两套 TypeScript 配置在组合 `fb40a55530ca968bc3c54a715e9ae53c4521a769` 通过，`expo-baseline-typecheck-r1.log` SHA256 `5de7fdf3acb96f57de6e3319f22ee4da8982640c7695db6ae2c47a6080a68043`。随后仅加入浏览器脚本及文档，未改前端，构建源码为 `0c906583120d49c1225824a850179e4d72e55fb5`，树 `b424e42581b116ed9a813d3631c33db583655cec`。Expo 真实导出 23 文件，`expo-baseline-build-20260917-r1/build-evidence.json` SHA256 `289b3c097ffb3648f42db79cb7f2d35952059d7e0cc3e7e0a8544665e02f99b2`；入口 `entry-a500c266136682a6cdb111c55ee11294.js`。
- **浏览器：9/9 通过，12 张截图**。真实临时 Flask、SQLite、HTTPS loopback 与 Edge；覆盖空／旧资料、金额与来源口径、完整分页、成员／双家庭／配对 TV、两类身份变化后的迟到读取、离线／后台、读取失败及返回路径。`worktrees/expo-baseline-browser/test-results/expo-baseline-20260917T124716920935Z/result.json` SHA256 `a9c3ed0045488375bb139fbfb7319afac9a18bbbaf3756b60ac479e3bb6703c7`。全部九套临时数据清理，页面错误与外部请求为零，源码／导出前后保持且 HEAD 干净。

截图覆盖 320、390、1280、1920 四宽的概览、长标题资产及深色紧凑消费观察。浏览器作者已逐张查看 12 图并核对散列，Root 另抽查三图，可见区域无剩余阻断；同目录 `visual-review.json` SHA256 `fd5dd1cd9ae6b602cb3a550fa6fab274f88ebf58ad3b6150d321177598251363`。这仅覆盖当前内部滚动可见区域，不代表整个表单；模拟前后台事件及浏览器网络离线不等于实体设备验证。

上述结果不代表 Linux 发布检查、生产部署、真实财务数据正确性、当前外部同步或本人实际设备验收。实体电视当前无法验证；完整产品目标仍有后续工作。


## 导入会话修复后的 R2 组合

独立修复 `05ee656825a7209c8b5c903c3eb94067fc7d00a0` 经非作者审查后合入 `75900b4f2a0d9cb3c7795f958fd2e13917123bff`，树 `b9f15482af17608962d9d849e17dfb7a796d6c08`。唯一测试冲突使用已审真实 HTTP 夹具替代上述过渡持久化读取；全部六文件与作者固定字节一致，读取模块保持原 `362051f…`，合并结果再次独立审查通过。

来源预览及状态读取使用一致快照和实际会话最终复核；确认在取得写锁及提交前检查，失败完整回滚。新增稳定 operationId 与本人精确历史回执查询，已提交操作可在过期或重新登录后核对，不恢复当前数据；未提交旧操作仍按原会话、有效期及版本校验。接口和原 216 项作者专项见[恢复说明](FINANCE-IMPORT-SESSION-RECOVERY.md)。新版恢复页面尚未包含在本批，现有高级入口继续可用。

新组合实际运行 **263 项通过，0 失败／错误／跳过，132.33 秒**：读取 28、导入会话 56、基线 19、来源 106、观察 54。`expo-baseline-combined-20260917-r2/results.xml` SHA256 `e9d1feb405232beaf6b4b0dd3c2a1ff0e1b8fde71b257242544f283a78e1510b`；日志 SHA256 `f35fb9b5d2fe98337960972cb326c070b3ab1d49ba04b45d2ca0ae5b3133da38`。完整跟踪源码在启动前、结束后相同，HEAD 与工作区保持；不把作者三模块或旧 R1 重复累加。

新 R2 构建针对上述同一组合，182 输入／23 导出，`expo-baseline-build-20260917-r2/build-evidence.json` SHA256 `73ef6d54bcebb82da5a7c63210133aa514fa548c3e8903131cd59670ddc47112`。前端子树与 R1 相同，入口仍为 `entry-a500c266136682a6cdb111c55ee11294.js`；因实际后端变更重新冻结构建并验浏览器，不重复原已通过的 TypeScript 检查。


R2 对上述同一源码和新构建单次执行原浏览器脚本，**9/9 通过，12 张截图经独立审查者逐张实际查看，无可见阻断**。`worktrees/expo-baseline-browser/test-results/expo-baseline-20260917T132907475470Z/result.json` SHA256 `5ae16e80d442d6652e830e80c3cc0915e69a052b5d48a962ea64897d475b436e`；同目录 `visual-review.json` SHA256 `2c19b7365342745556e1f3307b3842e8a661392dce8b81d61da310cf56fbf653`。stdout SHA256 `772fd5c68f7ae63ebd0df9ad7f1a9236df744c94ef1b36cdcd86f0106f0983c3`，stderr 为空，退出 0。

639 个跟踪源码文件和 23 导出前后不变，HEAD 干净，九套临时数据均清理；页面错误、外部请求及生产写入均为零。四宽和截图范围与 R1 相同，只涵盖滚动后的可见区域。结果使用合成财务及真实临时后端；模拟 visibility、浏览器 offline 不扩大为实体设备或本人真实资产验收。该 R2 浏览器阶段尚未执行服务器发布；其后的独立发布见下节。


<a id="expo-baseline-release"></a>
## 实际发布与独立读回（2026-09-17）

北京时间 **21:58:49 激活，21:59:22 正常 TLS 读回，22:01:55 独立只读复核通过**。固定候选 `f931516d2ec00def3c6dcb24b6ca669a256deb2d` 经复审后合入 integration/source `f0317fb6038d0b177f35376479ddeee4b787c3f3`，再合 main `0bd330a6203f968c15f43bd03fae7df5623af715`；文件树均为 `f9f14984abef8318424133771cfbaa4c145f2c28`。当前页面与上述导入会话后端已实际部署；后续纯文档不改变安装包身份。新版来源导入面板仍在独立候选验收，本批保持原高级更新入口。

| 实际对象 | SHA256／标识 |
| --- | --- |
| 发布目录 | `/opt/family-dashboard-releases/expo-baseline-55-20260917T135750601674Z` |
| archive | `bee0c0e751f5aca0599920560bb20fadaeeb1de7779a81f9949fe4e39fe5bef8` |
| manifest | `265830d1037696d39f1712a7f19cec25780de788071406cc0442956b06eb3252` |
| app／sync／media 镜像 | `sha256:4e3de8d45b39e251a7c0d3a068847c758617957028652b2f7dcc1f80e01cc5f2` |
| Linux JUnit 原件 | `30c10fab27aafbf771c05f560ad1c93d925dad86c900e9851c617b20274972c4` |
| activation.json 原件 | `f805d5deb72996ea1f51eb327780309e21404560e6f909aa00d6ee3df0730e2c` |
| post.json 原件 | `9d03ed3d7b7704156753742d7aa3f4c6eb82709db6bf6f95bb2d669ba0d4000b` |
| 启动数据保全报告 | `9b8c0b9b4a06a13554fe04eaea9580ea0fa0fec6585e922f9a4ba1e09c407bfc` |

私有实例 `expo-baseline-tools-20260917-r1/` 完成 build、validate、stage、activate、post_readback，五阶段各执行一次、均退出 0；固定算子不可重放。包共 **661 文件＝638 源文件＋23 Expo 导出**。独立审计将全部源码与最终 Git 逐一比对，核对 182 构建输入与全部导出；R2 浏览器至最终源码精确相差 16 个 Markdown 文件，collection 至最终源码精确相差 6 个 Markdown 文件，无可执行例外。浏览器 639 项跟踪采样中仅 `frontend/.gitignore` 未进入 638 项包源码选择器，包独有项为空；不是仅凭数量认定相同。

Linux 实际 **348 项＝347 通过＋1 跳过，0 失败／错误／排除**，十模块和全部测试标识与 collection 对齐。唯一跳过为 `tests.test_frontend_runtime::test_windows_junction_rejected`，原因精确为 `Windows junction semantics`。不把此前 API、Node、浏览器或 Windows 组合测试相加为另一套通过数。

本批 **55→55，无 DDL**。实际 1 户、家庭库及注册库两库在停止写者后完成完整备份；原 55 张家庭表与 2 张注册表的 schema、行和序列在新 app 启动后保持。`before.json` 与 `after-app.json` 字节一致，SHA256 `fbe2cab10e62756eb3bdd8cdd18fea1f7036d902287a4a6f0479e65843cd65c2`。环境配置散列保持、权限 0600，web 镜像不变。随后新逐库在线备份 `manifest-20260917T135918144749Z.json`（SHA256 `9bf4f4823c7ea78c86892f0d6a0080b380add2e4cad95f0c7135f8a5ca4d8366`）成功；它不是跨库全局原子快照，也没有再次执行 live 全组快照比较。

运行及 HTTPS 读回核对 **114 运行文件、75 静态资源、24 个生成内部资源拒绝与 1 个退役资源拒绝**；34 个唯一匿名 API 均为 401。四服务 running、重启数 0；app 为 healthy，另外三项没有配置 healthcheck，不能称为全服务健康探针通过。备份 service 成功、timer active。

独立审计目录 `expo-baseline-published-audit-20260917T135020363048Z/` 只取回 13 份发布证据原件，另读远端原件 SHA 后逐一匹配，再检查当前容器、manifest、配置散列／权限及公开 TLS。未执行发布算子、备份或业务写入，未下载数据库或配置正文：

- `audit.json` SHA256 `86358d4a77f074f9ff581c0efdab7e3c5ef2aed4d096494658a245f7afb8ac87`。
- `readback.json` SHA256 `b06e2a674b7203f897ce88876e05323b6ec4f0e6ed4a6027c88b522119d48e40`。
- `fresh-readback.json` SHA256 `04143def1fa381164487b712ee2438c00d79953bddeedf3f70526f975729957b`。

实际本人财务公网操作、真实云来源刷新、手机原生文件交互及实体电视仍未验收。服务器回执记录数量为零不构成真实导入成功；本地合成财务的流程与生产部署证据分别成立。完整资产账户、估值历史和跨平台持续同步仍属于后续工作。
