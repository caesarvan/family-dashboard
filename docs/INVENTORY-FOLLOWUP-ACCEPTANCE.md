# 售后关联家庭待办：候选验收

本记录对应采购批次的售后协作增量。**当前为候选，尚未部署**；上线须补实际候选镜像、Linux 验证、数据保全演练及发布后审计。已上线基线仍见 [采购关联库存验收](SHOPPING-INVENTORY-ACCEPTANCE.md#shopping-inventory-release)。

## 用户行为与边界

从「采购 → 登记或查看库存 → 批次详情」，将售后状态保存为处理中后，可明确创建一条家庭待办。标题默认为「跟进售后」，备注为空；界面说明这条待办在家庭清单中共享。负责人表示分工，不表示私密范围。私人物品名称、原采购备注和价格不会自动复制。

批次显示关联待办的当前负责人、截止日和完成状态；编辑或完成仍在家庭清单进行。完成待办与结束售后各自保存，不自动收货、退款或改动支出。已删除待办保留关联历史，不会因刷新、重试或重开售后而自动补建。

写入结果未知时，保留原请求编号与草稿，通过原回执恢复；伙伴先创建时，重新读取已有关系。离开、切换家庭及权限撤销沿用现有身份与草稿保护。此入口创建本地家庭待办，不代表 Microsoft To Do 或其他外部平台已接收。

接口和操作说明分别见 [库存 API](INVENTORY-API.md)、[Expo 库存](EXPO-INVENTORY.md)、[用户指南](USER-GUIDE.md)。无需新增数据库表；关联以现有库存操作回执的任务 ID 为准。完整备份保留关系，个人数据导出尚未包括这项关联。

## 已完成的验证

所有数据均为合成数据，浏览器使用隔离 HTTPS、真实 Flask 与临时 SQLite。以下为不同范围的结果，不能相加称为一次测试。

| 范围 | 实际结果 | 覆盖与限制 |
|---|---|---|
| 新售后 API | 46/46，零失败、错误、跳过 | 双家庭权限、事务回滚、双连接并发、原键重放、删除历史、库存/财务不变 |
| 既有库存 API 与采购查询 | 95/95，零失败、错误、跳过 | 原有接口回归，源码未变 |
| UI 状态与类型 | 13/13，类型检查通过 | 执行生产 TSX；React hooks、Paper、HTTP 是记录型替身，不是浏览器 |
| 发布工具基线适配 | 54/54 | 固定父镜像与旧 manifest、控制器、原成员发布默认合同 |
| 新前端测试文件打包 | 3/3 | 实际临时 Git/archive；新测试允许，未知前端文件仍拒绝 |
| 真实浏览器 R1 | 四条流程通过 | 创建并完成后重启保留、已提交响应丢失、伙伴冲突与删除历史、私有库存撤销共享 |
| 真实浏览器 R2 | 三次独立单流程各通过 | 对前三条流程补充稳定截图；未重复 R1 的第四条权限流程 |

R2 截图等待字体、目标可见和至少 600ms 稳定几何，确认输入框标签没有稳定重叠。**黑色主按钮文字仍有可见叠影，根因与修复验收尚待完成；不能据功能测试宣称视觉通过。**

## 源码及原始记录

主仓本批基线 `8ac89b50df03ae66da1dc3b63c116f00344d9128`；功能组合 `5dc4decf8614453c417187d11d9c10c21b614ff3`，tree `0384dd51475ad93de14dc255e8f954d6eaecf579`。API `dbb9d2d7fe6d74e2a20a7f88daed5f1d62158ef1`、UI `124f0a2e84acf927582a0d1c2776ece6f3529095` 和发布适配、浏览器脚本、接口文档均独立分支开发并由非作者审查后合入。

私有证据根目录为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`；日志和截图不入 Git。关键原件相对该目录：

| 记录 | SHA256 |
|---|---|
| `inventory-followup-api-review-r1.json` | `560c2a3950bb90c7c9a55533e8dc4911c4f58f3458b7b41c3360fa655e802e4a` |
| `inventory-followup-ui-review-r1.json` | `476f5461cb57bbb966fcc2f5383ee0f7fa415d74b9102b4d2b4f4948d7071ae4` |
| `inventory-followup-release-review-r2.json` | `025a043fe79b0f046aacd977e5581f70caeed7ed83327a4a6017628312d360f4` |
| `inventory-followup-browser-review-r1.json` | `2b875d093c286204e163ba11ec6c292d87d39a596bdb6ff09b0604d96115b7c0` |
| `worktrees/inventory-followup-browser/test-results/expo-inventory-followup-20260918T074708795442Z/result.json` | `d19d9af58319d827ae5770eaf27a1d85450a945f149ea579ac92c4a269333120` |
| `worktrees/inventory-followup-browser/test-results/expo-inventory-followup-20260918T075729308202Z/result.json` | `3cd9fe0face584d31aa0c99872f414697eee9299389be005fd1b38eaa3cc1c03` |
| `worktrees/inventory-followup-browser/test-results/expo-inventory-followup-20260918T075910202651Z/result.json` | `6186c0469104719ff0c378e38a11fa59dbe4b89ebb7df58f043f2a46fa74b4e8` |
| `worktrees/inventory-followup-browser/test-results/expo-inventory-followup-20260918T075910199944Z/result.json` | `0631a8eeb58a3217d53b64ccbed2140219330a48ff294f46c29d611d2c2bc5c8` |

R1 实际 Expo 导出来自 `adbb1d87c58fff11fd5b06ce3ee84b53d35251d5`，108 个输入、23 个导出。两次 TypeScript 检查及 Expo 子进程均退出 0；外层脚本因不识别中文字串的 JS Unicode 转义退出 1。该失败和原始工具回执保留，独立审查后的恢复记录为 `worktrees/integration/test-results/inventory-followup-build-r1/build-evidence.json`，SHA256 `36a0258a72b46fb85465d24981d9442b8ad14531658435cfa3e6ca7843bc035b`。如产品前端发生修复，须重新构建，不沿用旧 bundle 冒充修复结果。

## 未完成事项

- 稳定按钮视觉验证、最终候选构建与组合审查。
- 候选 Linux 镜像测试、两家庭三库 61/9 保全演练、生产发布与独立只读审计。
- 本人实际库存流程、外部任务同步以及实体电视未在本批验收。用户暂时无法使用电视，保留待验，不阻止其他开发。

本增量只补售后与家庭任务的关联，不代表完整采购链、全部家庭中枢功能或目标场景 A–D 已验收。
