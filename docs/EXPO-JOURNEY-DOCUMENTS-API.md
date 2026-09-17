# Expo 旅行资料客户端契约

基于 `ab35be37a06931135d05f2ef886eda98a2db10d3` 的客户端模型候选，尚未上线。实现为 [journeyDocuments.ts](../frontend/src/lib/journeyDocuments.ts)，复用已存在的 [旅行资料 API](JOURNEY-DOCUMENTS.md)，不新增接口、依赖或 schema。面板、导航、真实浏览器与服务端会话加固由本轮其他独立分支提供。

## 读写与身份

| 调用 | 模型入口 | 约束 |
| --- | --- | --- |
| `GET /api/journey-documents` | `documentListPath()`、`readDocumentList(raw, undefined, ownerId)` | 本人全库，最多 500 项；包含失去旅行关联的资料。 |
| `GET /api/journey-documents?journeyId=…` | `documentListPath(journeyId)`、`readDocumentList(raw, journeyId, ownerId)` | 24 位旅行 ID；本人私有及伙伴明确共享的资料，最多 100 项；返回当前分段与重新关联的旅行选项。 |
| `POST /api/journey-documents` | `readUploadPayload`、`readUploadResult` | 32 位 requestId，完整原文件、标题、共享范围与关联；返回 `{document,replayed}`。 |
| `PATCH /api/journey-documents/<id>` | `readPatchPayload`、`readMutationResult` | 资料 ID 为 **32 位**；完整五字段 `{revision,title,visibility,segmentKey,journeyId}`，不是局部 patch。 |
| `DELETE /api/journey-documents/<id>` | `readDeletePayload`、`readDeleteResult` | 只有 `{revision}`；成功为 `{deleted:true,id}`。 |
| `GET /api/journey-documents/<id>/file` | `downloadDocument` | 从已解析资料 ID 构造固定同源路径；不采用服务端 `downloadUrl` 作为下载权限或跳转目标。 |

`DocumentFence.run(me, job, current)` 前后检查成员角色、家庭、成员 ID、auth_version、CSRF 和工作代次。`current` 由面板提供，须同时涵盖挂载、页面焦点、前台、在线及当前身份；隐藏／离线时主动 abort 并 invalidate。模型本身不监听页面事件或保存组件状态。失效后不能发布迟到结果。

`documentRequest` 只允许上述 JSON 路由及 `/api/me`，使用同源 credentials、`redirect:error`、`cache:no-store`；请求 30 秒期限、JSON 流读取上限 4 MB。所有写入需要 CSRF。响应字段按 DTO 投影，拒绝重复 ID、错误关联、无效大小／版本；旅程中的伙伴共享记录可以只读，个人资料库不能混入伙伴记录。

## 结果未知和重试

`checkedDocumentWrite(guard, write)` 只将真实写端点返回的 400／403／404／409／413／415／422／429，且后置身份验证仍通过的结果视为 `DocumentRejected`。401、408、服务器异常、网络或后置身份验证失败不证明未写入。面板应在执行写回调前保留原意图，不能因本次读取失败自动重发。

上传载荷及文件对象由 `readUploadPayload` 复制并冻结。只有用户明确重试时才沿用同一份原 payload 和 requestId；禁止替换文件后复用旧 ID。成功重放返回**当前**资料：它可能已改名、移到另一趟旅行、被解除关联；不能强制它仍属于最初旅行。删除后的旧上传键不能复活内容，后端以 409 拒绝。

PATCH 和 DELETE 没有操作回执或单份元数据 GET。未知结果先读取当前列表；相同字段或资料缺失只能说明当前状态，不能证明某次请求执行。后续修改须由用户明确决定并使用读回版本，不能自动重复修改、删除或上传替代文件。解除旅行关联必须明确改为 private 并清空 segmentKey；已有孤立记录的旧 segmentKey 可在读取时保留，用于说明历史分段缺失。

## 文件与下载

`readDocumentFile(file, signal, current)` 读取浏览器实际 File 字节；最多 **5,000,000 字节**，PDF／JPG／JPEG／PNG／WebP，扩展名和非空浏览器 MIME 必须相符。浏览器 MIME 留空时按允许的扩展名给出声明，真实内容仍由后端检查。支持 120 个 Unicode 码点标题，不能把 emoji 的 UTF-16 长度错当字符数。没有原生文件选择依赖或原生下载实现，不能将 Web 文件路径当作已实现的原生能力。

PDF 仅作为附件下载；模型不渲染 PDF 或 HTML，不使用 data URI。服务端只检查 PDF 外形，不提供病毒扫描／预订核验。图片由后端解码、限单帧及 400 万像素、净化为至多 2 MB JPEG；这不是原图备份。

`downloadDocument(record, signal, guard, current)` 检查真实响应 MIME、attachment、no-store、nosniff 和流式大小，完成后置身份检查后才返回 `{blob,filename}`。不信任响应文件名、跨站 URL 或 HTML 内容。面板须在当前代次仍有效时创建临时 Blob URL 触发下载，并立即安排撤销、在退出时清理；模型不创建持久 URL、不写存储。服务端不能撤回已发字节，最后身份检查与用户浏览器保存动作之间也不是跨标签原子事务。

## 验证范围

[模型专项](../tests/test_expo_journey_documents.mjs) 使用真实 JavaScript `File`／`Blob`／`Response` 与受控 fetch 故障检查 DTO、5 MB 边界、冻结载荷、身份变化、拒绝结果来源和下载防护。它不是 Flask／SQLite、真实用户凭证或浏览器视觉验收；组合 typecheck 与真实浏览器由集成人另外执行。服务端每次事务会话复核由后端承担，客户端前后 `/me` 不能替代服务端授权。

本分支实际运行 `node --experimental-transform-types --test --test-reporter=tap tests/test_expo_journey_documents.mjs`，**12 项通过**，零失败／跳过。私有 `test-results/journey-documents-model-r1.tap` SHA256 为 `23cb792e3676f2895d9aa36ab4a003e6146b543ae17cba8017e1cfa1814bfe11`。使用已安装 TypeScript 对模型及其类型导入执行 `--noEmit --strict --skipLibCheck --target es2022 --module esnext --moduleResolution bundler --lib es2022,dom`，零诊断。首次开发检查的控制流收窄类型错误已修正；这是当前模型检查，不代表整包或原生端构建通过。
