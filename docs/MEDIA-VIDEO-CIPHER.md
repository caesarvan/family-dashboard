# 视频缓存加密格式

这是首次视频上线前的候选格式调整，不是生产数据迁移。此前未发布的视频 Fernet 候选和测试结果保留为历史记录；不自动猜测或兼容那个临时格式。当前生产照片、JSON、源 ID 派生及其旧密钥不变。调用者仍须独立验证成员、家庭、媒体权限和当前版本。

## 格式与边界

`MediaCipher.seal_bytes/open_bytes('media-video', ...)` 使用已有固定依赖 `cryptography==48.0.1` 的 `AESGCM`，不实现加密算法。HKDF-SHA256 的盐与长度分隔保持原约定，只有视频密钥域改为 `media-video/aesgcm/v1`，产生独立的 256 位密钥。每次加密从系统随机源生成 12 字节 nonce。

完整二进制包依次为：

| 部分 | 长度 | 处理 |
|---|---:|---|
| `family-dashboard/media/v1\0media-video/aesgcm/v1\0` | 48 字节 | 固定版本和用途，也作为 AAD 参与认证 |
| nonce | 12 字节 | 每次新生成，不复用 |
| 视频密文 | 等于明文长度 | 最多 64 MiB |
| GCM tag | 16 字节 | 完整验证后才返回明文 |

最大包长 **67,108,940 字节**，包含 76 字节固定开销，不再使用 base64。入口只接收不可变 `bytes`，先核对上下限及固定头，再调用完整认证解密；未知版本、截断、扩展、修改或错误家庭／密钥均返回原固定错误，不暴露输入或内部异常。解密用只读 `memoryview` 去除包头，避免再复制整个密文。

缓存 DDL、每项 reservation 和总额核算共用 `MAX_VIDEO_CIPHER_BYTES`。DDL 仍严格核对已存在对象，遇到旧候选表上限不会悄悄修改或继续写入。尚未发布的旧候选库仅供合成测试；正式上线仍需独立迁移与原数据保全检查。当前每人 100 MiB／家庭 200 MiB 配额不变。

## 实际验证范围

Windows 上对同样的合成 64 MiB 输入保留原文、加密包和还原内容，调用真实加解密并比较原文。旧 Fernet 峰值 working set 为 **605,851,648 字节（约 578 MiB）**；新 AES-GCM 为 **225,521,664 字节（约 215 MiB）**。两次均为独立 Python 进程的系统峰值，原件分别保留在 ignored `test-results/media-video-crypto-memory-windows-r1.json` 和 `media-video-crypto-memory-windows-aes-r1.json`。这只证明该加解密路径的实测改善。

新专项覆盖独立 HKDF 参考实现和已知格式、nonce、认证失败、错误家庭／用途、完整 64 MiB 边界、旧格式拒绝和 SQLite 上限。实际首轮执行旧加密兼容 125 项、新格式 24 项、真实临时 Flask／SQLite 视频导入 25 项，共 174 项；173 项通过，1 项旧配额 fixture 失败（密文缩小后，原 80 MiB 上限已能容纳一项）。把该 fixture 改为实际 reservation 下界后，仅复测此项并通过；174 个唯一用例共 175 次执行，无遗留失败或跳过，保留首轮失败原件。这些是本次 AES-GCM 结果，不复用历史 Fernet 通过数。

**还未证明当前生产 384 MiB 容器足够。** Linux 下完整下载→转码→加密→SQLite 提交、SQLite 读取→解密→HTTP 响应，以及并发响应、tmpfs、FFmpeg 子进程的峰值仍需实测。该调整不增加生产内存额度、不降低 64 MiB 上限，也不代表真实 Google 视频或实体电视已验收。

所用库的认证、nonce 和 tag 契约：[cryptography AESGCM 文档](https://cryptography.io/en/48.0.1/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM)。
