# 从设备导入照片（源码候选）

本批提供从手机或电脑浏览器选择照片的手动入口，不是 iCloud／NAS 连接或实时同步。用户可先从这些来源导出文件，再选择上传；Google Photos 原有流程保持。没有本地视频上传，也不接受 HEIC／HEIF、动画或多帧文件。尚未发布；真实浏览器、代理配置与生产资源验收另行记录。

流程为：选择最多 10 张照片 → 逐张上传 → 结束本批并核对预览 → 明确保存选中项。上传和保存是两个动作；未确认内容始终私有，24 小时后或原会话失效时由现有维护流程回收。保存后使用原相册详情、旅行关联、明确共享和单独电视授权，电视不能上传或确认。

## HTTP 合同

除下表指定 PUT 原始字节入口，其余写操作继续只接受 JSON。所有请求沿当前家庭会话；写操作保留成员、Origin、CSRF 核验。路径前缀为 `/api`。

| 方法与路径 | 请求与行为 |
|---|---|
| POST `/media/local-imports` | `{requestId,consentVersion:'media-v1',allowTemporaryProcessing:true,files:[{clientFileId,filename,contentType,bytes,sha256}]}`；首次 201，同原请求重放 200。无需 Google accountId。 |
| PUT `/media/local-imports/<id>/files/<slotId>` | 原始文件字节，`Content-Type` 与声明相同，`X-CSRF-Token`、`X-Import-Revision`；200 返回本批实际结果。不得发送 base64、multipart 或任意来源 URL。 |
| POST `/media/local-imports/<id>/finish` | `{revision,requestId}`；200。未上传的项成为 skipped；有成功或重复项则转 awaiting_confirmation，否则 failed。不会自动保存照片。 |
| GET `/media/imports/<id>` | 原批次读取入口，核对实际状态及已提交项。 |
| POST `/media/imports/<id>/confirm` | 原合同不变：`{revision,confirmRequestId,itemIds,consentVersion,persistSelected:true}`。仅保存明确选中的原 ID。 |
| DELETE `/media/imports/<id>` | 原 `{revision}` 取消语义，清理未确认副本。 |

每批 1–10 个文件，顺序固定。requestId／clientFileId 使用原 `[A-Za-z0-9_-]{16,100}`，clientFileId 批内唯一。filename 为不带路径的文件名、UTF-8 最多 255 字节，无控制字符；仅本人读取，密文保存，不写日志。contentType 为 `image/jpeg`、`image/png` 或 `image/webp`；bytes 为 1–8,388,608 的整数，sha256 为 64 位小写十六进制。服务端重新核对实际长度和 SHA，不信任扩展名、客户端检查或声明内容。

创建、PUT、finish 返回兼容原 `ImportDetail` 的 `{import,items,upload,replayed}`：

- `import.source` 为 `local-upload`；原 Google 批次为 `google-photos`。
- `upload.files` 顺序固定，每项有 `slotId`（24 位 hex）、上述文件声明、`status` 和可选 `error:{code,message}`。
- status 为 `pending / successful / duplicate / failed / skipped`。同批重复字节可对应同一 media ID；items 只出现该 ID 一次，结果计数仍逐文件。
- 可上传时 `import.state='staging'`、`upload.canUpload=true`。finish 后不可继续上传。
- confirmed／cancelled／expired／failed 的 GET 返回 `upload:{files:[],canUpload:false}`，仅保留原统计、来源及必要幂等回执；不保留文件声明。confirm 响应仍使用原 `{import,itemIds,goneItemIds,replayed}`，不要求 upload 字段。

单个不支持的图片记为该项 failed，不丢弃其他成功项。长度／哈希不符返回 `local_upload_mismatch`（422），该 pending 项仍可重选原文件；更换声明文件必须另建批次。并发接收返回 `local_upload_busy`（503、`Retry-After: 1`）；仅精确上传路径超过 8 MiB 返回 413。权限、版本、过期、额度沿 401／403／409／410／429。错误文本固定，不返回解码异常、原始字节或本地路径。

## 未知结果与恢复

创建响应丢失时保留原 requestId 和完整文件声明，重发同一个 POST 核对原批次；不同意图使用相同 ID 返回 409。上传使用固定 batch／slot／声明哈希，不能通过重试替换照片；已完成 slot 的同字节重放只返回原状态，不再次解码或创建副本。旧 revision 且仍 pending 时先 GET。

刷新后浏览器的 File 对象不能从服务端取回。客户端可重新选择与原声明长度、类型和 SHA 相同的文件继续 pending 项，或明确结束本批、保留已成功项供确认；不得自动换 requestId、自动新建批次或重复确认。finish 的原 requestId／revision 在结果未知时原样保留。确认沿原 confirmRequestId；后续 `/me` 读取失败不能把已提交的写操作当作明确拒绝。

客户端不把文件字节、预览或凭据写入 sessionStorage。文件选择器导致失焦后，重新核对 `/me` 和前台身份才可接收 File 或发起上传；身份变化、后台、离开页面及时隐藏私人内容。

## 来源、权限与存储

不新增表、列、索引或触发器，不回填旧数据。现有 media_imports／media_items 的 account_id 可为空，但空值本身绝不是本地许可。只有服务端密封的版本化 `local-upload` 上下文／metadata、原 owner、sourceKey 与文件指纹一致才识别本地来源；旧 Google 账户删除造成 NULL 不会变成本地照片。

共享媒体读取、电视列表／播放、助理搜索和共享导出复用同一按原行核验的来源权限；成员停用即不可再读共享内容。 助理搜索在响应前的最终授权事务中重新读取媒体原行与当前来源权限，丢弃第一份快照中的媒体结果，并按当前标题／旅行信息重新匹配及计算总数；搜索期间撤回共享、删除或来源失效不会沿用旧媒体快照。本人已确认保存的私人照片保留既有离线留存语义，不因 Google 连接失效而删除。该修订不读取图片／视频内容 BLOB，不改变数据库或前端合同。个人原图不因批次暂存而共享，电视仍需 ready＋shared＋该设备独立许可。Google 重授权、撤销和清理规则保持。

复用既有图片净化器：最多 2,000 万像素，方向纠正，生成边长最多 1600、最多 2 MiB 的无 EXIF／GPS 展示 JPEG。只存加密展示副本和必要 metadata，不保存上传原文件，不改设备／iCloud／NAS 原件。本地来源首版拍摄日期统一 `null/unknown`，不把 File.lastModified、导入时间、文件名或无时区 EXIF 当精确 UTC，因此不会伪造“那年今日”或日期旅行建议。

去重仅识别同家庭本人上传的完全相同原始字节，使用独立 local-upload 域的现有 HMAC；不跨成员暴露存在性，不声称完成 Google 预览与设备原图之间的跨源或感知去重。重复项保留原 ID、说明、共享及电视状态，不复活墓碑。个人导出仍仅含 metadata，不能当原图备份。

沿既有本人 100 MiB／家庭 200 MiB 密文及 reservation 配额，和原活动批次／每日批次／总记录限制。本地按声明数量预留；Google 与视频占用不会被忽略。现 worker 不领取本地上传项，仍执行既有来源工作及统一过期／撤权维护。

## 资源与代理边界

进程内单 permit 在读取原始 body 前取得，覆盖读取、净化与提交；解码不持 SQLite 事务，提交前重新检查真实成员会话、家庭、批次租约和 revision。忙时立即 503，不让多线程同时积存原图；异常清理大缓冲后释放。此设计与源码测试不等于已证明 384 MiB 上限。

`deploy/nginx.conf` 两个 HTTPS server 的精确上传 location 保留 8m 上限，禁 request buffering，使用 HTTP/1.1 转发，避免 body 写入 Nginx 临时文件。现多家庭 `/space/<slug>` 只设置签名 cookie，后续 API 仍为同一个 `/api/...` 地址，因此同一 location 覆盖所有家庭。其他 API 大小和 JSON 规则不扩大。

`tests/test_local_photo_import.py` 以合成文件、真实 Flask／SQLite／Pillow 验证；外网禁用。实际 Nginx 行为、大图峰值和完整浏览器上传仍需相应候选的真实验收，不用已有 Google 或视频 IPC 结果替代。
