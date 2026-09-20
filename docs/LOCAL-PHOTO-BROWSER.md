# 本地照片上传的真实浏览器验收

本工具是待执行的验收准备，不表示三个产品流程已经通过。运行者须先审查固定 Git HEAD，并使用已验证的 Expo 构建。只运行隔离的临时 Flask、HTTPS、SQLite 和 Edge；不连接真实账号、不访问生产、不调用 Google 或模型。

## 固定输入与运行

入口为 `scripts/check_expo_local_photo_browser.py`，业务浏览器流程位于 `tests/browser_expo_local_photo_check.py`。以实际冻结 HEAD 和构建 SHA 替换以下占位符；路径必须指向专用干净 worktree 和已有短临时根：

```powershell
python -B -X utf8 scripts/check_expo_local_photo_browser.py `
  --source-root <专用worktree> --expected-head <已审40位HEAD> `
  --build-source-head bafd2cfddd67bb6db3b0e6b9598e68eca20aca89 `
  --bundle <media-local-photo-build/test-results/expo-local-photo-combination/web> `
  --expected-build-evidence dc8afa80dfb704ac33e54fcc9e86d476f238088c3eaf809f57fb2db5ca50edbe `
  --temp-root C:/tmp
```

必须禁用 `.pyc`，不能使用 Python `-O`。输出新建于 `test-results/expo-local-photo-<UTC>/`，不会覆盖失败原件。Windows 导出复制使用扩展路径。`--case` 可重复指定下列名称，去重后按首次顺序执行；默认三项，完整运行预期 9 张截图，每项 3 张。补跑只声明实际选择的范围。

构建来自 `bafd2cf`；运行后端包含已审撤权修复 `da7e78a9429750030f2b8fa0a1e2d85ba30967bc`，组合基线为 `9bff5d4d21ef178a9c067f3fa39cb445819d03f0`。复用仅允许本工具四个新增路径，以及 `home_assistant.py`、`tests/test_media_search_revocation.py`、`docs/LOCAL-PHOTO-IMPORT.md` 三个已审后台路径。后三者须逐一与 `da7e78a` Git blob 相同，且该提交必须是运行 HEAD 的祖先。完整 frontend 树和构建记录全部输入均须相同，其他后台差异拒绝。此处复用的是前端导出，不把旧 `bafd2cf` 后端声称为已含撤权修复。

## 三个独立流程

| 名称 | 真实操作和断言 | 截图 |
| --- | --- | --- |
| `mobile_private_save` | 390px，无 Google 账户；实际文件选择器选择合成 JPEG、PNG、WebP；逐张 raw PUT 经过 Pillow 生成加密暂存；确认前不是已保存；用户勾选私密保存后沿原确认 API 持久化，刷新仍是原 ID/revision，详情说明来源是设备。 | 选片、确认前预览、保存后详情 |
| `lost_responses_partial_skip` | 1280px，真实创建/首张 PUT/结束批次已提交后丢失响应；创建仅以原 body/requestId 核对；页面重载使原 File 消失，读取原批次后明确结束，未上传项准确显示“尚未上传，已跳过”；只保存成功项。核原 slot/hash、单上传、单 finish、单确认及实际 DB/audit。 | PUT 结果待核对、部分跳过原因、一次保存后的相册 |
| `identity_and_acl` | 390px，本人真实上传/保存后伙伴、另一家庭和已配对 TV 默认不可读；通过真实 API 明确共享和逐 TV 授权后可读，收回共享后伙伴页面清除详情和图片，字节接口再次拒绝；另一次实际 PUT 成功后、原响应返回前通过真实登录切换身份，旧文件/详情不得显现或触发 finish/confirm。 | 伙伴共享详情、撤销后页面、迟到响应身份切换后的页面 |

权限场景的建户、配对、共享/撤销与身份切换使用真实 API 设置情景，不宣称这些配置动作的 UI 已验收。文件选择使用真实 Playwright FileChooser 和本地文件，不注入 File、成功 DTO 或图片列表。故障拦截只在 `route.fetch()` 取得真实服务器提交结果之后 abort 或延迟返回原响应；不伪造提交成功。

第三项先保存真实 PUT 原响应和暂存库证据，再切换身份。同一浏览器重新登录会撤销原会话，因此原上传者以新会话读旧批次时，预期 `items=[]`、文件声明为空且不能继续上传；这不代表已提交暂存消失。核对原 PUT 中的媒体 ID 仍为加密、私密、未确认的 `staged` 行，并通过明确的负向 API 探针验证 finish/confirm 均为 410、库状态不变。负向探针与“浏览器没有自动发出 finish/confirm”的请求计数分开记录。

首轮正式运行的前两项通过，第三项在旧 `len(pending.items)==1` 预期处失败，保留原件。两个实际 JPEG 的长度和 SHA 不同，不能归因为重复内容。该轮失败前未保存迟到 PUT 的完整响应，不能补造；修订版在断言前落盘原响应和数据库记录。真实 Flask/SQLite 的单项窄复现确认上述会话撤销合同，但第三项浏览器仍需独立补验。

## 原件与范围

记录实际 HTTP 请求/响应、原始标识与声明摘要、临时 SQLite 状态/密文长度/audit 次数、净化 JPEG 实际解码及摘要、截图与布局。记录前后全部 Git 文件、构建导出和加载模块 SHA，拒绝外部请求，逐场景关闭浏览器上下文、Flask 线程/连接并验证临时目录清理。报告可能保留具体 teardown 警告，不能将场景通过等同所有异步警告消失。

离线专项只验证固定来源准入、输出不覆盖、真实三格式文件和 SQLite 证据连接关闭；它们不等于上述浏览器验收通过。正式结果需读取实际 `result.json`、截图和子进程终态。这一工具不覆盖真实设备文件选择器、实体电视显示、真实 Google、iCloud/NAS 同步、本地视频或生产部署，也不替代原 API 上传大小/像素/并发矩阵。
