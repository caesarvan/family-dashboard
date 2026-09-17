# Expo 旅行资料与日程清单验收

**状态：已审查功能候选，尚未发布。** 本文分别记录源码、局部测试、组合验证和生产结果。历史经典旅行资料服务已发布，不代表本次 Expo 界面已上线。

## 功能与固定审查

共同开发基线为 `ab35be37a06931135d05f2ef886eda98a2db10d3`，所有实现使用独立分支及物理 worktree，经非作者固定差异审查后由 Root 合并。

| 分支 | 接受的 head | 审查 |
| --- | --- | --- |
| `codex/expo-documents-model` | `2ca0d3c6c8502295efee758f44a21e21ea79fd87` | 非作者 acceptance 审查通过 |
| `codex/expo-documents-ui` | `5a0889eb6bf3b021cd4b3e303ae2bcbe0a01749e` | 非作者 acceptance 审查通过 |
| `codex/expo-documents-wiring` | `cabf625f361402c67462a113baf5cdaa29ce4b71` | 非作者 contract 审查通过 |
| `codex/expo-calendar-density` | `8a9213ce57a87b2840b39c6ba23a199d38ba702f` | 非作者 Root 审查通过 |
| `codex/expo-documents-sessions` | `666aa3a522cd4a757dbc4074aba710acf078e17c` | 修正后非作者 acceptance 复核通过 |

五项组合为 `codex/expo-documents-integration` 的 `c0c8ba4f41a268901cf41920e6012cb3da3333c8`，tree `8b90b9745af0abfe9a35930081dbefa5a65b2d2d`。正式 integration、main 及生产暂未变更。资料上传默认本人私有，伙伴仅可下载明确共享的文件；旅行、地图、助理和更多的导航接线保护未保存修改。日程及清单调整留白与操作区域，日期算法保持。

## 实际检查

- 客户端模型：12 项 Node 检查通过；固定 TAP SHA256 `23cb792e3676f2895d9aa36ab4a003e6146b543ae17cba8017e1cfa1814bfe11`，详细范围见 [客户端契约](EXPO-JOURNEY-DOCUMENTS-API.md)。
- 日程：原日期与范围算法专项通过；组件作者的定向类型检查不是实际按钮尺寸或浏览器证明，见 [密度调整](EXPO-CALENDAR-DENSITY.md)。
- 首版后端：原资料 68 项和新增 23 项会话测试一次共 91 通过；随后非作者发现合法旧版 Cookie 续期遗留事务，真实临时 Flask／SQLite 下载与上传可复现失败。原通过记录保留，不能据此接受首版。
- 后端修正：读取末尾的再次认证之后释放可能开启的隐式事务。新增旧版 Cookie 下载、新上传、原请求重放后，会话专项实际 26 项通过，39.19 秒，零失败／错误／跳过。JUnit SHA256 `7b4d49953a4aece0c57268a79b88fc700e4153cdf23642236540ddf3d6b907bf`；该次未重跑原 68 项，不将分次结果相加。见 [服务端契约](JOURNEY-DOCUMENTS.md)。
- 完整类型检查：候选物理目录执行 `npm ci --no-audit --no-fund` 安装 587 个锁定包；安装结束后 `npm run typecheck` 退出 0。安装尚未结束时的一次提前调用因找不到 tsc 失败，未算作通过。没有使用 node_modules 链接或类型占位。

## 待完成与边界

真实临时 Flask／SQLite／Edge 的资料操作、日程及清单尺寸／键盘／密度、Expo 导出、Linux 镜像检查及发布读回仍待本轮执行。不能用源码样式声明、Node 或类型检查代替这些结果。

用户暂时无法使用实体电视验证，保持待确认，不据此阻塞其他开发。真实手机系统选片／下载、原生安装、本人公网账户操作、真实云同步和实体电视均不在上述已验范围。服务端最后复核之后已经开始发送的文件字节无法撤回；上传的 PDF 不提供预订核验或病毒扫描。
