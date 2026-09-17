# Expo 旅行资料与日程清单验收

**状态：本地组合验收通过，尚未发布。** 资料 R4 的 9 条流程／12 图、日程／清单 R2 的 5 条流程／18 图分别通过并视查可见区域；各轮保持独立源码和构建身份，失败原件保留。历史经典资料服务已发布，不代表本次 Expo 界面已上线。

## 功能与固定审查

共同开发基线为 `ab35be37a06931135d05f2ef886eda98a2db10d3`，所有实现使用独立分支及物理 worktree，经非作者固定差异审查后由 Root 合并。

| 分支 | 接受的 head | 审查 |
| --- | --- | --- |
| `codex/expo-documents-model` | `2ca0d3c6c8502295efee758f44a21e21ea79fd87` | 非作者 acceptance 审查通过 |
| `codex/expo-documents-ui` | `5a0889eb6bf3b021cd4b3e303ae2bcbe0a01749e` | 非作者 acceptance 审查通过 |
| `codex/expo-documents-wiring` | `cabf625f361402c67462a113baf5cdaa29ce4b71` | 非作者 contract 审查通过 |
| `codex/expo-calendar-density` | `c0b6da418715ec443e8cee7d1a1af7ab3d44cdd4` | 初版及选中名称修正经非作者 Root 审查通过 |
| `codex/expo-documents-sessions` | `666aa3a522cd4a757dbc4074aba710acf078e17c` | 修正后非作者 acceptance 复核通过 |

最早五项组合为 `c0c8ba4f41a268901cf41920e6012cb3da3333c8`。后续 `c54fdf240400d3f7db1ca31349303e9bf2f78c7f` 修正连续受阻导航提示竞态；日程测试 `4450ac9856b70386c9972013043c4b0e3051a465` 核选中名称及真实七日范围。资料测试 `a2752182771adcd7454df2ab03ac63f22a54f31e` 仅两处重命名，避免方法与父夹具 `lifecycle` 属性撞名；`0feafe04` 改为等待真实上传及成员切换完成、旧面板卸载后再断言。修订均经非作者审查。上传默认本人私有，伙伴仅可下载明确共享文件；嵌套导航保护草稿和未知意图。日期算法、接口形状与表结构保持。

## 实际检查

- 客户端模型：12 项 Node 检查通过；固定 TAP SHA256 `23cb792e3676f2895d9aa36ab4a003e6146b543ae17cba8017e1cfa1814bfe11`，详细范围见 [客户端契约](EXPO-JOURNEY-DOCUMENTS-API.md)。
- 日程：原日期与范围算法专项通过；组件作者的定向类型检查不是实际按钮尺寸或浏览器证明，见 [密度调整](EXPO-CALENDAR-DENSITY.md)。
- 首版后端：原资料 68 项和新增 23 项会话测试一次共 91 通过；随后非作者发现合法旧版 Cookie 续期遗留事务，真实临时 Flask／SQLite 下载与上传可复现失败。原通过记录保留，不能据此接受首版。
- 后端修正：读取末尾的再次认证之后释放可能开启的隐式事务。新增旧版 Cookie 下载、新上传、原请求重放后，会话专项实际 26 项通过，39.19 秒，零失败／错误／跳过。JUnit SHA256 `7b4d49953a4aece0c57268a79b88fc700e4153cdf23642236540ddf3d6b907bf`；该次未重跑原 68 项，不将分次结果相加。见 [服务端契约](JOURNEY-DOCUMENTS.md)。
- 完整类型检查：候选物理目录安装 587 个锁定包，R2 实际代码执行 `npm run typecheck` 退出 0。安装尚未结束时的一次提前调用因找不到 tsc 失败，未算作通过。没有使用 node_modules 链接或类型占位。
- 服务器回归清单：8 个模块实际收集 236 个唯一项；R4 私有 `expo-documents-validation-20260917-r4/collection.json` SHA256 `9efd27aae6e9ac04b846c23925994ccba790b5639333c6b1c21f31338cacabe8`。目前只有 collection，不能写成 Linux 236 项通过。局部 Node、后端分次结果和浏览器流程不相加为一套通过数。

## 冻结构建与浏览器原件

以下均为独立临时 Flask／SQLite／Edge、真实 HTTP 与虚构文件／记录；没有成功业务响应替身。浏览器和 Python 外网封锁，无真实云、生产写入或实体电视操作。每轮保存原报告、执行脚本及截图，清理当轮临时夹具；不覆盖失败证据。

| 构建 | 原受验 source / tree | build-evidence SHA256 |
| --- | --- | --- |
| R1 | `4a4ceb127a8637d955174891cd22b86a476d5349` / `4d63f83cb58e7a59a141dda375819ba3e792525f` | `b17a4421745eef873ee0ef4f49c2f45b49a11ec9c8309c79a244580a76fe5c97` |
| R2 | `bf9a3b094d661347c42f706a16d919dc948859c3` / `4ce23f081364080bf2a13f08bb05d4c5479c6b08` | `180932d925a52eaadbb264b291e88df212a9bcac861c543a267a9f56b6c3ba5e` |
| R3 | `5465d5f208e327385eddfc31f4fa5315d5992c68` / `d35795121ce041463ee0a1793b17a4fb1cba8127` | `d2563469fb113e2a75c5ec6267d8ec88516981d170d586d6106b79c9f0e3423f` |
| R4 | `e4499b88b89124f19fd6eb040435d133bdfffc7d` / `7c705b53f30575cb90ccc93cae0327dfd03f6ccd` | `803cda188a11bbaf12ae41b0da958a56c8b3e6970532b1c3770f62c2844e4bde` |

四个实际 Expo 构建分别位于私有 `expo-documents-build-20260917-r{1,2,3,4}/`，各导出 23 文件。相同 JS 入口名称本身不证明等价。最终冻结若接受 R2 日程证据，须逐项核最终运行文件、全部构建输入、导出字节及其 harness／fixture 相同，并保留原 source／build 身份；不能称日程 R2 与资料 R4 来自同次或同 head。

私有原件根为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/worktrees/`；下表目录位于对应工作树的 `test-results/`，SHA 为该目录的 `result.json`。

| 流程与目录 | 实际终态与修正 | result SHA256 |
| --- | --- | --- |
| 日程 R1：`expo-calendar-browser/test-results/expo-calendar-density-20260917T091902274379Z` | 3／5，18 图；选中按钮未暴露 checked，整体失败。产品 `c0b6da4` 明确可访问名称，测试 `4450ac9` 保留选中可读与持久化检查。 | `73c1096b6dba2b52433bdb737fb002601efe54fcc80abf5e143af8cb1cd6599a` |
| 日程 R2：`expo-calendar-browser/test-results/expo-calendar-density-20260917T092844726907Z` | **5／5，18 图全部逐张视查可见区域，无阻断。** 591 源文件／23 导出前后不变，清理完成、零页面错误／外网请求。 | `de208b2292159ddb4fff8b268256be8a4367a474e1e71c64d8b108082fc19191` |
| 资料 R1：`expo-documents-browser/test-results/expo-journey-documents-20260917T092050954804Z` | 3／9，8 图；导航保护仍在，但连续提示被旧 Snackbar dismiss 清除。产品 `c54fdf2` 修正并经独立审查。 | `b81f8f2e889776c6e102d1dd7cc76c3bd69801a0d0270d27b8e01ac022209307` |
| 资料 R2：`expo-documents-browser/test-results/expo-journey-documents-20260917T092854137948Z` | 6／9，12 图；测试方法被父夹具 `ExitStack` 属性覆盖，发生 TypeError。测试 `a275218` 只重命名两处，不改变业务断言。 | `a2ee51fe18a7cbc1cebf573d5494f5e0a2c0fb51f0f03045d4daf1a38dad8087` |
| 资料 R3：`expo-documents-browser/test-results/expo-journey-documents-20260917T093410362758Z` | 7／9，12 图；测试把编辑器隐藏误当写入完成，早于真实 201／换 Cookie 完成便检查 `sent` 并清理。`0feafe04` 修正等待边界，未改产品或放宽旧身份隔离断言。 | `ee4bc745ba87168f8b81d7edb3a8614f3de3881b49c47be45c416f68462478d4` |
| 资料 R4：`expo-documents-browser/test-results/expo-journey-documents-20260917T094400300384Z` | **9／9，12 图由执行作者逐张视查可见区域，无阻断。** 591 源文件／23 导出前后不变，清理完成、零页面错误／外网请求。 | `e4a5afdc48e9942f4c6521dd24a4a1954238576db5519f5dc77974086694c425` |

日程 R2 的 `visual-review.json` SHA 为 `cd91f9cd7e2f0855d39ed8980e4c72d3e68336550ed8d99ee7e5163527cc9a91`。100 个实际点击框满足对应 44px／48px 下限；同一 390px 视口下三类短行各减少 8px，字号不变。范围一次 PUT 跨刷新保留完整选中名称、七日日期和 SQLite 原行，待办／采购各一次 Space 只产生一次 PATCH，合成只读同步投影零写。18 图只覆盖当前视口，内部滚动之外的内容不算视觉覆盖。

资料 R4 的 `visual-review.json` SHA 为 `09f7a7907a670e88342a04da99b68f3bea05b5addae1773497c914626ec488d0`。真实流程覆盖 PDF／图片文件选择及附件字节、默认私有／明确共享、跨户和配对 TV 拒绝、409 草稿合并、已提交与未到达请求的未知恢复、原载荷重试防重复／删除后不复活、重新关联及 13 份记录搜索分页、后台／离线与迟到身份隔离、地图／本地解析助理／更多的导航保护。12 图含四宽及浅深主题，320px 上部与确认位置另拍；库内滚动未全覆盖。不使用真实模型、云账户或本人文件。

## 待完成与边界

最终等价冻结、Linux 镜像检查及生产发布读回仍待完成。本地两个专项通过不代表已经部署，也不抹去前序失败；不能用源码样式声明、Node 或类型检查代替实际结果。

用户暂时无法使用实体电视验证，保持待确认，不据此阻塞其他开发。真实手机系统选片／下载、原生安装、本人公网账户操作、真实云同步和实体电视均不在上述已验范围。服务端最后复核之后已经开始发送的文件字节无法撤回；上传的 PDF 不提供预订核验或病毒扫描。
