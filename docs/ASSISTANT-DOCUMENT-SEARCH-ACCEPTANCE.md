# 助理资料与照片搜索：使用与集中验收

<a id="assistant-document-search-release"></a>
## 本批状态

代码经 [PR #9](https://github.com/caesarvan/family-dashboard/pull/9) 合入 main `7ff58c446f3396d13e69ad4668e8df6fb01b5daa`，与正式 source `fd3ef3692528a18e3e6afc779fb15efe8463d559` 同树。本地构建与浏览器分段验证、实际隔离 Linux 175 项已通过；固定计划已独立审查。**2026-09-20 05:15:29（北京时间）实际激活成功，05:16:46 独立生产只读审计通过。** Git 合并、计划准入、激活和审计是分别记录的事实。

本批新增助理搜索已保存旅行资料，并将资料和照片结果接到原详情；返回保留搜索词与页码。还修正首次照片无草稿却出现恢复提示，以及采购错误提示在窄屏的垂直裁切。保持家庭库 69／平台库 9 表，无 DDL、回填、新第三方授权或模型调用。

## 最短使用路径

1. 打开「更多 → 家庭助理」，点击「找资料照片」，将预填关键词改为自己的资料标题、文件名或旅行名称；也可直接输入 `搜索：旅行凭证`。明确执行搜索后查看结果。
2. 点击「查看资料」重新读取当前有权查看的资料列表并定位原资料；需要文件时另点「下载资料」。搜索不会自动下载或从旧结果生成下载权限。本人未关联资料可以在个人资料库中打开。
3. 点击「查看照片」重新读取原照片的当前权限和详情。第一次打开没有已有草稿时，不显示草稿恢复说明；真实未保存修改及版本冲突仍沿用原核对提示。
4. 返回搜索，继续原关键词与页码；页面会重新读取当前可见结果。若资料移出原旅行、照片删除或共享被撤销，先返回重新搜索，再从新结果明确打开。

资料匹配标题、文件名及当前关联旅行标题；照片沿用已保存说明和旅行标题搜索。只查询看板已保存、当前成员有权访问的元数据，不读取 PDF 正文、OCR 或 Google 原图库。显式搜索留在本地，即使此前选择了可选模型也不把资料送入模型。

仅本人资料不会因搜索共享；伙伴只能查到仍关联现存旅行的共享资料。原旅行消失时，旧结果不能自动跳到本人资料库；本人可重新搜索，再按新的未关联范围打开同一资料。搜索分页不是冻结快照，并发增删时结果及总数可能变化。

成员、家庭或会话变化会清除旧内容，迟到响应不能写入新身份页面。打开详情和下载各自重新核权。搜索、查看或返回不自动保存照片修改、完成任务或增加电视许可。

## 已完成的分段验证

各行独立记录，存在重叠，不能相加为一次全量检查或本人完整验收。

| 阶段 | 实际结果 | 证明范围与限制 |
| --- | --- | --- |
| 本地后端作者分段 | 175 个不同 API 节点有通过证据 | 新资料搜索 34 项，以及原资料、会话、库存／来源搜索和助理。初轮测试误计旧日程的失败保留；不称一次全量运行。 |
| R1 正式 Expo 构建 | 两组 TypeScript；171 Node；23 个导出 | source `03c860fc3ad47782984b834512d55bbe561e12e3`，独立依赖与构建输入前后核对。 |
| R1 资料／照片真实临时浏览器 | 4/4、8 图 | 搜索分页／原 ID 返回、原旅行失效、本人未关联、共享撤回／删除、成员切换迟到；真实 HTTPS／Flask／SQLite／Edge，合成资料和照片。 |
| R1 采购提示定向浏览器 | 原 `offline_draft` 1/1、2 图 | 390／1280 的完整错误文字高度、离线草稿和明确恢复；没有因此重跑采购后端或真实模型。 |
| R2 新 Expo 构建 | 两组 TypeScript；33 Node；23 个新导出 | source `cc688863f090bb300c7e6fe3412ef011b7498958`；修复初次照片无草稿的误导提示后重新构建。 |
| R2 增量浏览器 | 仅 `content_pagination` 1/1、6 图 | 390／1280 首次照片打开不出现两句草稿提示；保留原 HTTP／DB、原 ID、分页返回及布局检查。不是 R2 四条全部重跑。 |
| 实际隔离 Linux | 175/175，0 失败、错误、跳过 | 六个指定模块的精确 nodeid，992 源文件及 127 运行文件前后绑定同一包；无网络、只读根、非特权用户、临时库和空 provider 凭据。 |

Node 组件使用合成宿主；浏览器数字布局检查另有截图目视审查。R1 首次照片提示问题及 R2 修正分段保留；旧失败或限制不改写为当时通过。Linux 明确排除相邻模块的 Edge 浏览器节点，由上述独立浏览器验收承担，不以 skip 隐藏该边界。

## 固定包与计划身份

| 项目 | 固定值 |
| --- | --- |
| Source | `fd3ef3692528a18e3e6afc779fb15efe8463d559` |
| Source tree | `419b5b62f962cb06e1fa52a8f2af541e44189452` |
| Expo 构建源码 | `cc688863f090bb300c7e6fe3412ef011b7498958`；全部前端输入与最终包一致 |
| Package SHA256 | `3da0f27a68eb375f5fddd0ad69c227018b869a7266ae93442935458cc87dfe9a` |
| Manifest SHA256 | `da779fc25df1b6df3c71c50851355bb452fb0afa65cde7b829a8b2604bd23b0c` |
| Archive SHA256 | `af53613ebb993ac9b85566ea2e633b0a85ba5284605938bf204d0ed3ffcd2565` |
| Image | `sha256:3c572b73396b71dd651e1a02e9774484f06d50476d6d3b6a2a50b6306bb1b747` |
| Linux build SHA256 | `2eaad0388254313ad367aab707af039a72cf19a929e3c246e0a653dc8c89a401` |
| Linux validation SHA256 | `532d88fe88fde8f8b62b3d67c488e946043ff421fed4cada3228072b18e9f3fd` |
| Linux selection SHA256 | `c888eef631dd1cefb024b5a03503556a874fc2cf7b568d32b3757b6b0b88c7ee` |
| Linux JUnit SHA256 | `73cb710e59c6fc2d20c8d5b6752829ed40ab02da7c7491bd0b4be3217d3e110d` |
| 离线计划 SHA256 | `44f2f110ab269842a56387a9aabfb6f37229c411a83833ddbb963933919cd690` |
| Candidate | `/opt/family-dashboard-candidates/assistant-document-search-69-20260920-r1` |
| Release directory | `/opt/family-dashboard-releases/assistant-document-search-69-20260919T211354193433Z` |
| Stage receipt SHA256 | `c7c374c7b57c045f6480af9b60de9c3bc2e2f756eb2c57174766a9e93bc86e61` |
| Activation receipt SHA256 | `137d26a28b8d7a737408ac72b51f450758d2f15c2c16c126fc06e443851cd17b` |

R2 原 `build-evidence.json` 已是 `membership-expo-build`，直接绑定原件，不需转换。非 Expo 运行文件仍为 104 个，仅 `home_assistant.py`、`journey_documents.py` 改变；其余 102 项映射 SHA256 为 `c3d59eef7e79228506eea3cca6a5aa53d7b2227e671579e4d98deade61aca370`。依赖、Docker／Compose／nginx 与既有权限边界不因本批改变。

## 实际发布与独立只读审计

实际 stage／activate 均退出 0，激活回执完成时间为 `2026-09-19T21:15:29.308368+00:00`，即上述北京时间。本次计划已消费，不可重放；后续纯文档提交不改变固定运行包身份。

独立审计观测时间为 `2026-09-19T21:16:46.946953+00:00`，实际执行退出 0。核对 992 个安装文件，app／sync／media 各 127 个运行文件；104 个非 Expo 文件中的 102 个保持父版，另两个匹配本包。四服务 running、0 重启、app healthy；75 项正常 TLS 静态资源与包一致，备份定时器 active。

生产为 **一户两库**，家庭库 69→69、平台库 9→9。停止写入时的发布前原件与新 app 启动保全原件的完整 schema、行、列及序列保持，组合逻辑 SHA256 均为 `0b08a2df4f30b1762023fb6320f7b0a0003680fe56b96c651e8c14fd7dde232b`。审计没有重新查询活跃数据库，启动后的正常业务仍可变化。既有非空财务和路线表按实际内容保全，不要求清空。

保留的两份停机备份已验证字节 SHA256：家庭库 `4052a25a29ec374903a549525cc67609b006509e5d4741fa451ba4917e382d94`、平台库 `c55d9896eb65ed09e3e17e67970aa7a4303aab32fe9931b571ded7f6549087c8`。**未执行恢复**，不能称为生产恢复演练。环境文件及成员迁移 marker 保持；三个应用服务的环境键值映射一致，环境数组顺序改变，未将顺序变化误报为配置值变化。

27 项匿名 GET 拒绝探针及另外 3 项助理 GET 探针均为 **401**；这只证明匿名 GET 被拒绝，不证明 POST 授权、模型调用或本人操作。审计无业务／提供方写入、app／SQLite 导入、活跃库查询、bootstrap、服务变更、备份创建或恢复。

原件为 `worktrees/assistant-document-search-linux-prep/test-results/production-audit-r1/assistant-document-search-production-readonly-r1.result.json`，SHA256 `0cab19c440085447f5db199a0797a231bd9fc3c2096eb9a04d04604bf31c103b`；同目录实际执行回执 `assistant-document-search-production-readonly-r1.execution.json`，SHA256 `de0dbef65bc33cef7a04b5713ffa8b2401151197899cccad5583a848c333a7f4`。文档整理只读取这些已完成原件，没有再次执行审计或部署。

## 证据定位与未验事项

本地受限原件位于 `family-dashboard-access/document-search-release-20260920-r1/reviews/`，14 份审查／选择原件由固定计划逐一绑定，不提交 Git。R1/R2 原始结果 SHA256 如下，完整工具边界见[浏览器说明](EXPO-ASSISTANT-DOCUMENT-SEARCH-BROWSER.md)。

| 原件 | SHA256 |
| --- | --- |
| R1 build-evidence | `30a45d81142ddd4ebf5307fd3d7e30927983b1894a28f71e06b910904548f742` |
| R1 四流程 result | `acc2bba285d5c7c21a38a51e86c55746d853c2c377e62af419e7ad61eec85094` |
| R1 采购单项 result | `673ce80b938d5a25e19d6f696f00ea0944700b583fc18521b744caba53ed098b` |
| R2 build-evidence | `813a0fe023ccff9d7a5c08d330cf658a4bbd27af0a8613130b73e5ad10ae16d8` |
| R2 单流程 result | `ed33a81c91c1180dfe76211cb3f4fdf19baabaec8ee092a05ec2e7bfe28dd893` |
| `linux-independent-review.json` | `94a264cec0654acb613cc5b7cb24ac716591a6650fdfedf75237e3408452c650` |

本人完整 A–D 验收仍为 **0/4**；真实家庭连续使用、真实云账户及实体电视不由分段结果替代。当前电视无设备，待可用后验证。本批显式搜索不调用模型，未再执行真实模型或真实 Microsoft／Google 云写入。任务依赖 PR #10 是下一候选，站内提醒仅完成调查方案；均不包含在此固定包。

相关合同：[搜索 API](ASSISTANT-DOCUMENT-SEARCH.md) · [界面与身份边界](ASSISTANT-DOCUMENT-SEARCH-UI.md) · [发布入口](ASSISTANT-DOCUMENT-SEARCH-RELEASE.md) · [完整验收场景](ACCEPTANCE-SCENARIOS.md)。
