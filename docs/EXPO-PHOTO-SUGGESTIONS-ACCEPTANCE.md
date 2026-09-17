# 照片旅行建议：验收与发布记录

## 当前状态与入口

**已于 2026-09-18 02:35:52（北京时间）激活，02:36:22 正常 TLS 读回，02:37:48 再次只读检查通过。** 本页集中记录实际安装身份、本地与服务器验收、失败历史及未验边界；最终独立本地审计于 02:41:30 通过。

入口为「相册 → 我的照片 → 照片详情 → 查看旅行建议」。本人核对来源日期、当前旅行日期及标题，选择后明确确认；日期匹配不证明照片拍摄地点或实际到访。关联不自动共享、不授予电视许可，也不夹带其他未保存修改。来源未知或无匹配时仍可手动关联。使用及未知结果恢复见[使用说明](EXPO-PHOTO-SUGGESTIONS.md)，日期规则见[建议 API](MEDIA-JOURNEY-SUGGESTIONS.md)。

<a id="expo-photo-suggestions-release"></a>
## 实际发布身份与保全

| 项目 | 实际记录 |
|---|---|
| 安装 main | `f6da7584809e79891b2a21896fa4fc3fb54e51b3` |
| 安装 source／integration | `0dc419d82761f99ca8efdc3314ec96a461938bde` |
| 安装 tree | `bbb5231e73ed2c336422ccb97dfbbbe5a286272a`，与 R2 浏览器组合相同 |
| app／sync／media 镜像 | `sha256:4235322eb02f02d1533e479194331c324aa095850fe08d1540e02088342a1104` |
| archive SHA256 | `a14d695ed265b7ee136a0275042ef62d124179db5a0697e4457cdce69376230f` |
| manifest SHA256 | `da2a4cb1f44debec1e2c458b2f92a80de6b813842af04ba28cdb303333a21eb4` |
| 实际 Linux 执行 | 9 模块、223 项＝222 通过＋1 精确 Windows junction 跳过；0 failure／error／deselected，313.912 秒，115 个运行文件／38 个已加载模块前后一致 |
| 包与读回 | 718 文件＝695 个选中源文件＋23 个导出文件；191 个构建输入、115 个运行文件；75 个 HTTPS 静态文件核对，24 个生成文件及 1 个退役资源禁止公开访问 |
| 权限与服务 | 37 个唯一匿名 URL 均为 401；四服务 running、重启数 0，仅 app 有 `healthy` 健康检查，其余 health 为 null；环境散列保持、权限 0600 |
| 数据保全 | 58→58，无 DDL；1 户、2 库停写备份并核验完整组；原 58 表的行／schema／序列与平台注册库保持，启动前后快照散列相同 |

发布目录为 `/opt/family-dashboard-releases/expo-photo-suggestions-58-20260917T183453063325Z`。后置备份服务实际 `success`、timer `active`；该次新备份是逐库在线备份，**不是跨数据库的全组原子快照**，`liveGroupSnapshotRechecked=false`。停写阶段的完整保全证据与恢复运行后的在线备份不能混为一项保证。

独立审查者 `expo_finance_contract` 核对 44 份本地原件，含 8 份下载的阶段／验证原件；存储报告与阶段 stdout 一致，JUnit 的 223 个唯一节点与收集集合完全相同，post／fresh 读回通过。保全复核依据已审算子的完整比较报告及启动前后 proof 散列链，没有再次下载数据库或原 proof 文件，也没有重放发布、备份或测试。

本页及后续纯文档提交不改变上述已安装身份。

## R2 固定输入与本地结果

| 项目 | 实际记录 |
|---|---|
| 组合源码 | `02836ec9d77041dd132233a134430a11c05ed0cb` |
| 源码树 | `bbb5231e73ed2c336422ccb97dfbbbe5a286272a` |
| 浏览器脚本提交 | `e0557732513ddfde7d7d817f49a5555ba43d8726` |
| 脚本 SHA256 | `b8f31aad5fe1145db589aa9f25136b94ca3b398db68c2ae26b1015356a0d60cd` |
| 完整类型检查 | 实际退出 0；源身份与上表相同，检查后干净 |
| 实际 Web 构建 | `npm run build:web`；191 个构建输入、23 个导出文件 |
| 浏览器 | 12／12 独立流程通过；12 张 PNG；696 个 tracked 源文件与 23 个导出文件前后一致 |
| 隔离与清理 | 12 份临时夹具均清理；0 页面错误、0 外网请求、0 生产写入 |
| 视觉 | Root 逐张查看全部 12 PNG，`PASS_VISIBLE_VIEWPORT`；四宽 320／390／1280／1920，浅深色、长标题、键盘及内部滚动后的确认区；新建议操作实测至少 44px |
| Linux 测试收集 | 9 模块、223 个唯一 node ID，`collectedOnly=true`、`executed=false`；此项不是执行通过数 |

成功业务响应来自真实隔离 Flask／SQLite／HTTPS loopback／Edge。故障仅丢弃或延迟真实 GET／PATCH 传输，不模拟成功 DTO；合成媒体夹具不构成真实云服务验收。

覆盖的主要行为：

- 显式读取、选择与四字段 PATCH；实际读回关联，照片说明、共享、电视许可、地点和旅行数据保持。
- v1／v2 当前旅行日期与时区、纳秒来源文本、来源未知、无匹配，以及 20 项上限和 `hasMore`；前端不猜测时间转换或地点。
- 照片／workflow／trip 三版本冲突后先读最新再重新选择；提交前丢失、提交后丢失及成功后读回失败均只读核对，不自动重发。
- 五类未保存草稿不夹带；伙伴、跨户、电视拒绝；换照片、离线、失焦、后台及身份替换后的迟到结果不能恢复旧建议。
- 后台期间另一客户端取消真实选片记录；恢复前 fresh GET，旧预览和保存入口不复活，未知编号不自动重发；明确结束本地核对不写服务器。

后端会话专项和原建议／媒体回归的独立 100 项通过记录见[会话保护](MEDIA-SUGGESTION-SESSIONS.md)。它们与本页浏览器及实际 Linux 结果分别报告，不累加为一次全套执行。

## 原件索引

以下均为未入 Git 的本机私有原件。`A` 为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W` 为 `A/worktrees`。
R2 浏览器目录为 `W/expo-photo-suggestions-browser/test-results/expo-photo-suggestions-20260917T181447399920Z`；其中保留执行脚本、各场景结果与截图。

| 原件 | SHA256 |
|---|---|
| `A/expo-photo-suggestions-build-20260918-r2/build-evidence.json` | `7a75ef19b2acd487a8491a445af92acb2a3fca88eb8e6ff7d63cc4d4129b640d` |
| 同目录 `typecheck.json` | `d2df349927a8165fb21fc229fbd1aa9d79dd81d69c02e09d2b219bde8d7a18b2` |
| R2 浏览器目录 `result.json` | `e9152aa0f351c660e1635806e949cbb14880aa8adf81b5cd42ec66e1737f5455` |
| R2 浏览器目录 `visual-review.json` | `2663ac347d36b2cd36f8a24c8aac10ae0f10fb1b2bc4865253f852ac62e94086` |
| `A/expo-photo-suggestions-validation-20260918-r2/collection.json` | `d3396814c28cb3dde150c346e163bbdb9a79d9faf03352b571ad3b37578e925c` |

生产工具目录为 `A/expo-photo-suggestions-tools-20260918-r1`。独立审计目录 `D` 为 `A/expo-photo-suggestions-published-audit-20260918-r1`，下载原件在其 `remote-evidence` 子目录；全部 44 项散列由审计报告索引。

| 生产／审计原件 | SHA256 |
|---|---|
| `D/audit-review.json` | `c2315c5869c98c638584c4622d74a88a54d5e63e11731095999230c3615fa80b` |
| `D/fresh-readback.json` | `589e3c5ba36cd9f8f481ced09711652d85af54e5d55bf5bac7e24089bb531822` |
| `D/remote-evidence/activation.json` | `8f87e40531bc8e6dbec4fb42c869c7ff2caa46762fcc618fc85ea247ecd21cdb` |
| `D/remote-evidence/post-readback.json` | `525a234778c9174cc7da8409fcbd0c35d11d5e2e6d24c5bd820e68266e02cfda` |
| `D/remote-evidence/results.xml` | `8d4968de3ab2c8ca41e686b3f3e7eea4002f995dacce1391bb0cf544081a9363` |
| `D/remote-evidence/runtime.json` | `b74c5e1e97b9b69c7644a421b5f9e13881796bf62b2af9fdf9e94fd9f8824b29` |

调用原件另保留在 `W/expo-photo-suggestions-browser/test-results/photo-suggestions-r2-invocation-20260917T181446650921Z`，包含 invocation、stdout、stderr 和 completion；实际退出 0。

## R1 失败与修复保留

R1 实际 **10／12 通过**，不能称为全通过，也不与 R2 相加。源码为 `9c142b96f2e86502e05664e0be26895e2d29e363`，构建证据 SHA 为 `3bc89228f052ae75d5e795b6ef31fe8628e96708debdb698c9fcef624074079a`。原结果目录为 `W/expo-photo-suggestions-browser/test-results/expo-photo-suggestions-20260917T180017514726Z`，`result.json` SHA 为 `94c4ff774a2d41534e5b8ce7d9b2b5ac516d043fb993049ad6492871e2c0324a`；失败堆栈、截图及全部原件保留。

- `empty_manual`：第二次快速手动关联时 Paper 菜单 `visible=true`、`rendered=false`，旧隐藏动画回调覆盖打开。产品修复 `240a95718e9b7f11c947dd821ce316f13c96cd9c` 仅将本页两个菜单的局部动画设为 0，保留 anchor、焦点和流程。
- `lifetime_isolation`：Python Locator 的 `.first()` 调用触发 TypeError。测试修复 `e0557732513ddfde7d7d817f49a5555ba43d8726` 仅改为 `.first` 属性，保留全部业务断言。

两项固定增量均经非作者审查；R2 在新组合源码上重新构建并完整执行原快速交互，没有添加等待或重试掩盖失败。

## 剩余验收边界

本地照片和资料均为合成数据。实际个人照片的新流程、真实云端新写入、原生设备与实体电视仍未验收。视觉结论只覆盖 12 张稳定可见视口；手机长详情需正常内部滚动，不能推断所有内容同时可见。来源日期只用于建议，不自动改变共享、电视许可、地点或到访状态。
