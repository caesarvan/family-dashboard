# 资料与照片搜索发布入口

这是采购版本之后的独立发布适配，准备入口不表示本批已经部署。业务操作见 [助理资料与照片搜索](ASSISTANT-DOCUMENT-SEARCH-UI.md)，浏览器边界见 [验收工具](EXPO-ASSISTANT-DOCUMENT-SEARCH-BROWSER.md)。本地临时打包和记录式生命周期检查不替代实际 Linux、生产激活及本人账户验证。

## 固定父版本与运行范围

构建入口 `deploy/build_assistant_document_search_release.py` 固定 profile `shopping-schedule-r1-assistant-document-search`，激活入口为 `deploy/activate_assistant_document_search_release.py`。CLI 和计划不能另选基线、环境或运行文件豁免项。

| 当前已安装的采购父版本 | 固定值 |
| --- | --- |
| Source | `67e5b0d5cafd28b50abce7e42fd64f64c8059997` |
| Tree | `3ee7134cca45d1fe6d2227b11c921fdd5833243c` |
| Image | `sha256:086e40df931f84ceef7d3fba3684bc08444e364d311f22e59ad01a372a560916` |
| Package SHA256 | `6bf6c8cf7994899c7deadd9ec25cb8c4cc8a57596e5591ede663ec9bc389c447` |
| Manifest SHA256 | `6d8324ff8a8f071c7bb0160b081f9a5b503da9070e649ef8956a034e94d3ee5c` |
| 独立生产只读审计 SHA256 | `4fce162234123a7f770d58fc875104011cdf9d52e7d77d7d397ccc15f48f9ded` |

非 Expo 运行文件仍为 104 个，仅允许 `home_assistant.py`、`journey_documents.py` 改变。其余 102 个文件的完整名称／哈希映射，按 `membership_release_package.encoded` 编码后的 SHA256 为 `c3d59eef7e79228506eea3cca6a5aa53d7b2227e671579e4d98deade61aca370`。该值从上述已安装 package 原件重新计算，当前候选逐文件核对只出现这两个运行文件差异。新增、删除、改名、重新计算外层清单均不能放宽这项约束。

根目录另允许 README 文档变化；前端、Expo 导出、部署工具、文档和测试继续使用既有范围。新增并要求 `frontend/tests/assistantDocumentSearch.test.mjs`，保留全部此前前端测试。Dockerfile、Compose、nginx、Python 和前端依赖保持固定。旧采购及更早 profile 的范围和默认语义保持独立。

## 构建、审查和候选

1. 独立审查作者提交后，由集成人合入并固定完整 source head/tree。最终前端输入必须逐字节匹配独立构建证据，不能因为变更只是提示文字而继续使用旧导出。
2. 使用新入口的 `prepare` 创建独占输出目录，再用 `verify` 读回包、清单、归档和原始构建证据。沿用已有 build-evidence 转换合同，转换记录与原始 Expo 证据须同时保留。
3. 在隔离环境运行同一入口的 `build`、`validate`。Linux selection、source、manifest、明确 nodeid、JUnit 及 runtime 来源记录须属于同一包。记录式测试不会被计为实际 Docker/Linux 验收。
4. 将代码、包、Linux、前端、浏览器和演练的审查原件交给 `assemble`。生成的 `assistant-document-search-release-plan` 固定 27 个 operator，包含前版完整链与本批两个入口。独立审查明确计划 SHA 后，集成人才可按授权执行 `stage`／`activate`。

各阶段参数可通过以下命令只读查看；每阶段必须使用新输出目录，不覆盖失败或已消费候选：

```powershell
python -B deploy/build_assistant_document_search_release.py --help
python -B deploy/build_assistant_document_search_release.py prepare --help
python -B deploy/build_assistant_document_search_release.py validate --help
python -B deploy/build_assistant_document_search_release.py assemble --help
python -B deploy/activate_assistant_document_search_release.py --help
```

支持 `prepare`、`verify`、`build`、`validate`、`assemble`；激活入口使用固定候选目录及显式计划 SHA。共享帮助文案按入口的固定 `schema_pair` 显示，本入口与采购入口为 69/9，原 66/9 入口保持 66/9；验证与执行逻辑未变。不得用 `python -O` 绕过检查，不从计划导入任意 profile。

## 分段前端证据

以下是已经取得的本地证据，各段分别记录；R2 单项不表示四条流程在 R2 上全部重跑：

| 阶段 | 固定来源／证据 | 实际范围 |
| --- | --- | --- |
| R1 前端构建 | source `03c860fc3ad47782984b834512d55bbe561e12e3`，原 build evidence `30a45d81142ddd4ebf5307fd3d7e30927983b1894a28f71e06b910904548f742` | 两组 TypeScript、171 Node、23 个导出文件 |
| R1 资料／照片浏览器 | result `acc2bba285d5c7c21a38a51e86c55746d853c2c377e62af419e7ad61eec85094` | 4/4，8 图；分页、原编号往返、原范围失效、本人未关联、撤权／删除、成员切换迟到 |
| R1 采购提示单项 | result `673ce80b938d5a25e19d6f696f00ea0944700b583fc18521b744caba53ed098b` | 1/1，2 图；原 `offline_draft` 完整错误文字高度、离线草稿及明确恢复 |
| R2 前端构建 | source `cc688863f090bb300c7e6fe3412ef011b7498958`，原 build evidence `813a0fe023ccff9d7a5c08d330cf658a4bbd27af0a8613130b73e5ad10ae16d8` | 首次照片无草稿提示修正后，两组 TypeScript、33 Node、23 个新导出文件 |
| R2 定向浏览器 | harness source `4a2e61469f2ae4793a0ef0e06ca91c4fc5ae0be5`，result `ed33a81c91c1180dfe76211cb3f4fdf19baabaec8ee092a05ec2e7bfe28dd893` | 仅 `content_pagination` 1/1、6 图；两句错误草稿提示不存在，原 HTTP／DB／布局／返回断言保持 |

最终包必须使用 R2 新导出，并验证后续源码与 R2 的全部前端输入相同。浏览器使用合成资料及照片、真实临时后端和真实 Edge；不代表真实 Google 原图库、模型、生产或实体设备通过。

## 数据保全与失败处理

本批没有 DDL、批量回填或数据迁移；家庭库 69 表、平台库 9 表保持。新 Controller 仅提供固定 `ReleaseSpec`，继承采购控制器的停止服务、完整停机备份、安装、正常启动 app、核对全数据组后启动 sync/media 的流程。继续使用 `assistant_trip_items_release_data` 的保全读写边界与原 attempt kind。

`stage` 记录 69→69／9→9，独立激活目录前缀为 `assistant-document-search-69-`。任何备份、启动或数据核对失败均保留原件和停止状态，不自动 restore，不重复消费 activation。实际发布后仍须独立只读核查固定包、运行文件、服务、TLS 静态资源及数据保全回执。

## 定向本地测试

`tests/test_assistant_document_search_release.py` 使用临时 Git、合成导出和记录式 runner，验证 102 个实际保留文件、固定豁免、旧 profile、前端证据复用、27 个 operator、计划篡改、服务读取之前的文件边界以及 69/9 失败顺序。旧采购合同测试使用已核对父包的原 `journey_documents.py` 哈希与现有其余文件映射，不修改生产 pin，也不依赖 Git 历史。测试不导入业务 app、不连接 Docker／SSH、不读取生产数据库。
