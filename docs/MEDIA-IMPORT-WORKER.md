# Google Photos 导入 worker

`media_import_worker.py` 是独立 worker，不修改日历／待办 `sync_worker`。它仅推进用户已明确创建的 Google Photos 导入；不会扫描照片库、自动确认持久保存、共享媒体或授权电视。真实 Google OAuth、真实媒体、生产运行及新三表迁移仍须分别验证。

## 调度与调用接口

`MediaScheduler(platform).tick()` 从既有 `HouseholdPlatform.households()` 枚举家庭，按家庭 ID 排序并轮转；每次只加载一个 `platform.child(household)`，调用该应用 `extensions['household_media']` 的 worker。繁忙、空闲或加载失败的家庭同样推进游标，避免固定第一个家庭占用所有轮次。整个进程串行执行，最多一个解码任务。

`MediaImportWorker(engine).tick()` 返回是否取得了任务，不能把 `True` 当成照片导入成功。`claim_next` 内部先执行一次 engine 的有界维护，再领取一个动作，worker 不重复扫描。每次调用只执行一个 create、poll、完整 list、单张 download 或 cleanup；不循环消耗同户任务，不在方法内 sleep 或重试。

入口 `python -B media_import_worker.py` 使用应用工厂及已有家庭平台，每次调度后等待一秒。SIGTERM/SIGINT 只设置停止标志：已进入的有限步骤允许结束，随后不再领取任务。应用注册、Docker COPY、单独服务及资源限制由集成人接线；仅有本文件不代表服务已经运行。

数据库唯一状态机由 `household_media.MediaLibrary` 持有。worker 不建表、不执行 SQL，也不另造任务状态：

| 接口 | 职责 |
|---|---|
| `maintenance()` | 有界处理固定 24 小时期满、失效授权、逾期租约及本地清理，释放 reservation |
| `claim_next()` | 短写事务重新核对会话、账户、明确 Picker 授权、期限与额度，取得不可预测租约和 revision；create 先持久记录 attempted |
| `validate_job(job)` | 新短事务核对当前授权、租约、revision 和原期限；不能沿用旧 SQLite snapshot |
| `complete(job, result)` | I/O 后再次执行 CAS；加密元数据及净化 JPEG BLOB 原子写入 SQLite，并核对实际密文额度 |
| `fail(job, code, ...)` | 仅接收固定错误码；持久记录最多五次读取重试、退避、失败或不明结果 |
| `accounts.photos_access_token(accountId, owner)` | 每一步重新取得当前授权 token；该调用期间不得持有媒体数据库写事务 |

job 包含 `id,owner,accountId,action,leaseToken,revision,expiresAt,session,manifest,media,attempts,cleanupUnknown`。session 与 manifest 是 adapter 的安全规范形状；不含访问 token 或下载 baseUrl。它们仍属于私有内部资料，不可直接打印或返回浏览器。

`complete` 的结果：create/poll 为规范 session；list 为完整规范媒体数组；download 为 `{mediaId,manifest,preview}`，其中 `preview` 是 `media_images.Preview`；cleanup 为 `None`。worker 只传内存对象，engine 负责 `MediaCipher` 用途隔离和 metadata 的 row／household／owner／source／随机 previewKey／SHA 绑定。预览使用 SQLite 加密 BLOB，没有另一个文件存储或孤儿扫描模块。

## 单步外部操作

每一步都先复核 job，再调用 `photos_access_token`；token 刷新后再次复核，构造本次全新的 `GooglePhotosPicker`。离开步骤即关闭实例并清理其临时下载能力，不缓存 token、client 或 baseUrl。

- **create：** 仅 `create_session(max_item_count=20)` 一次 POST。engine 必须在 claim 时持久记录 attempted；陈旧 creating 租约变成 create_unknown，不能重新创建。网络、解析、5xx 或提交结果不明不自动重发。即使创建返回时授权已撤回，worker 仍把已知 session 交给 `complete`；engine 只能加密保存待清理能力，不能公开 pickerUri 或发布结果。
- **poll/list：** 遵守 engine 保存的首次 pollingConfig 截止、Google expireTime 与本地截止的较早值，后续响应不能延长期限。完整 list 限制 20 项、40 页；任何分页失败都不能提交半份清单。
- **download：** 在新 token／新 Picker 上重新完整 list，将 ID→完整公开 metadata 与原清单精确比较；只忽略数组排列和 adapter 本就不公开的临时 baseUrl。不接受增加、删除或修改的选择。随后最多下载一张 PHOTO，使用 `preview,1600×1600`。完整重列、下载和 Pillow 净化后分别重新复核 job；最终仍由 engine 执行事务 CAS。
- **净化与保存：** 下载最多 8 MiB；已有 `sanitize_media_preview` 检查格式、像素、多帧和容器，移除原元数据并输出最多 1600 边长、2 MiB JPEG。worker 不存原图。engine 按每户 200 MiB、每 owner 100 MiB 的密文加 reservation 上限核验后落库。单张图片格式不支持可记为该项失败，其余项继续；身份或完整清单变化终结整批暂存。
- **cleanup：** 已知 session 的 DELETE 是单独步骤。DELETE 不明时标记 `cleanupUnknown`，后续只做 GET 读回；404 确认已无会话，仍可读则标 unavailable，不再盲目 DELETE。无权限／无法核实时如实保留失败状态，不能声称 Google 会话已删除；Google 原照片永不删除。

读取类暂时错误由 engine 持久指数退避、最多五次，并受原总期限限制。worker 提供 5 秒加 0..5 秒 jitter；429 提供 30 秒加 jitter。engine 将它与自身至少 30 秒的指数退避取较大值。create 不走自动重试。adapter 自身不重试，避免两层重试相乘。

默认 adapter 的完整列表和媒体下载各有 120 秒预算，OAuth 刷新使用原有超时；一个 download 步骤可以包含两者和解码。租约须覆盖该有限步骤，并在结果提交时仍有效。超出租约则丢弃结果，不能为了可用性绕过 fence。进程终止后由 engine 的持久状态恢复，而非重新执行未知 POST。

## 隐私与验证边界

worker 不记录异常文本、令牌、Google ID、文件名、Picker URI、图片字节或 job repr。调度失败只输出固定消息；adapter／图片错误归一化为有限错误码。数据库、密文与业务日志权限由应用及部署层管理；生产 SECRET_KEY 必须保持稳定。

`tests/test_media_import_worker.py` 包含两层合成验证。单步测试使用真实 Picker＋Pillow，覆盖新 token／新实例、清单变化与重排、完整分页失败、I/O 中撤权、创建 unknown、清理读回及家庭公平轮转；协议替身只实现 engine 公共调用，不复制 SQL 状态机。纵向测试依赖共同候选中的真实 `household_media.MediaLibrary`，通过真实登录及 Photos OAuth 合成 transport 建立账户，再执行创建、轮询、完整清单、下载、净化、加密 SQLite 和清理。还覆盖进程领取后丢失的 POST、实际 logout、scope 缩减、原会话期限、24 小时回收、部分暂存后清单变化、密文重启读取和持久五次退避。额度及 HTTP 展示权限另由 engine 测试覆盖。

在同时包含 worker 与 `household_media.py` 的候选中运行 `python -B -m pytest tests/test_media_import_worker.py`。worker 作者基线尚未包含后者时，纵向测试必须显式使用相应 engine 候选；不能用替代 DDL、静默跳过或复制另一作者未提交文件制造通过。独立模块结果与最终固定 Git 组合结果分开记录。

所有输入为合成图片和凭据。实际 Google 账户、真实媒体、生产配置、电视设备及新三表的 Docker 迁移／恢复不在本模块的本地测试结论内。
