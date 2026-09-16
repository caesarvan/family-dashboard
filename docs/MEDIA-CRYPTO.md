# 媒体静态加密 helper

`media_crypto.py` 是独立服务端 helper，使用现有 `cryptography` 依赖；没有 app、数据库、路由、文件写入、网络或日志接入。本候选不包含在当前地图发布中，不代表 Google Photos 已接入或真实账户已验收。

```python
from media_crypto import MediaCipher, MediaCryptoError

# 两个参数必须来自服务端可信配置／当前已授权家庭，不接受客户端自报身份。
cipher = MediaCipher(secret_key, household_id)
encrypted = cipher.seal_json('picker-session', {'sessionId': 'synthetic-session'})
session_data = cipher.open_json('picker-session', encrypted)
preview_blob = cipher.seal_bytes('media-preview', normalized_preview_bytes)
preview_bytes = cipher.open_bytes('media-preview', preview_blob)
source_id = cipher.source_key(owner, account_subject, media_id)
```

## 接口与大小

| 方法 | 允许的 purpose | 输入／输出 |
|---|---|---|
| `seal_json` / `open_json` | 精确的 `import-context`、`picker-session`、`picker-manifest`、`media-metadata` | 顶层 dict ↔ bytes；完整 UTF-8 明文包络最多 256 KiB |
| `seal_bytes` / `open_bytes` | 精确的 `media-preview` | bytes ↔ bytes；原始预览明文最多 2 MiB，可为空 |
| `source_key` | 内部独立 `source-key`，不可用作加密 purpose | 三个字符串 → 64 位小写十六进制 HMAC-SHA256 |

JSON 包络为 `{"version":1,"purpose":"picker-session","value":{...}}`，完整包络计入 256 KiB，包括格式开销。写入使用紧凑、键排序、不转义有效 Unicode 的 JSON；读入要求顶层包络精确三个字段，版本必须是整数 1，purpose 必须与调用一致，value 必须是对象。拒绝任意层重复键（包括 Unicode 转义后同名）、NaN、Infinity、溢出为 infinity 的浮点数、无效 UTF-8／孤立 surrogate、额外尾部内容、循环和超过 64 层的数据。深度包含包络；Python 输入仅接受原生 dict/list/str/int/float/bool/None，不静默转换非字符串键、tuple 或自定义对象。

预览加密前加固定二进制头 `family-dashboard/media/v1\x00media-preview\x00`；解密必须匹配此头。它只是格式版本，不负责 MIME、图像解码、EXIF 清除、恶意文件扫描或尺寸归一化；这些属于预览处理模块。此 helper 不接受完整照片／视频作为任意大小对象。

密文必须是原生 bytes 和规范 URL-safe base64 Fernet token，不接受 str、空白、额外 padding 或其他 alphabet。解密前按 Fernet 格式公式限制编码长度：明文上限为 N 时，`4 * ceil((57 + 16 * (floor(N / 16) + 1)) / 3)`；预览 N 另加固定头长度。认证解密后再次检查实际明文长度，避免分组 padding 的余量放过超限数据。没有压缩路径。

## 密钥与来源标识

HKDF-SHA256 生成 32 字节密钥，namespace / salt 为 `family-dashboard/media/v1`，info 由 namespace、家庭 ID、purpose 各自 UTF-8 字节的四字节大端长度前缀与内容拼接而成。五个加密 purpose 独立派生，另为 `source-key` 派生 HMAC 密钥；加密密钥经 URL-safe base64 后交给 Fernet。相同密钥、家庭和用途可重建解密器；不同家庭、用途或 secret 不能互解。本模块不复用 OAuth token 的旧派生方式。

`source_key(owner, account_subject, media_id)` 的 HMAC 消息按相同长度前缀规则编码 namespace 和这三个字段。家庭绑定在派生密钥中；owner 和 Google subject 必须为业务确认的真实标识，不能用展示邮箱替代。相同输入稳定；不同 owner、家庭、subject、media ID、secret 隔离，不跨成员或家庭去重。不会返回原始 source 字段。该确定性标识仍可关联同一范围内的重复输入，应作为内部数据处理。

secret 必须是非空、非全空白的严格 UTF-8 字符串，最多 65536 字节；家庭 ID 最多 256 字节，支持现有 `default` 和 24 位十六进制 ID，不强制 UUID。owner 最多 256 字节、subject 最多 1024、media ID 最多 4096，同样要求非空、非全空白。保留原值，不 trim、不大小写转换、不 Unicode 归一化；前导空格与组合字符不会被静默合并。

HKDF 是密钥派生，并不把弱口令变成强服务器密钥；部署仍须提供高熵 SECRET_KEY。helper 不保留原始 secret 为实例属性，也不在 repr 展示派生密钥／家庭。更改 secret 或家庭标识会改变全部密钥和来源标识；密钥轮换、旧密钥保留、备份与重新加密由后续上层明确安排，本版本没有自动回退。

## 错误与权限边界

公开方法及构造失败统一抛 `MediaCryptoError`，固定消息为“媒体加密数据无效或无法处理”；不附带输入、原异常、token 或 secret，不保留原异常的 `__cause__` / `__context__`。模块不记录日志。调用者也不能记录明文、密钥、捕获局部变量的 traceback 或序列化内部属性；Python helper 无法提供进程内秘密隔离或可靠内存擦除。

加密不替代成员／家庭授权、OAuth scope、用户选择、会话有效期、CSRF、共享／删除确认或事务检查。同一家庭同一 purpose 的合法密文可以被互换；上层应在包络 value 中保存并核对 owner、account、session、record 等业务绑定。到期和撤销由业务检查，本模块不对 Fernet 设置 TTL，也不自动确认地点到访。

Fernet 认证密文仍暴露生成时间和大致长度，适合有界内存数据；不是隐藏所有元数据的容器。[Fernet 官方说明](https://cryptography.io/en/latest/fernet/)、[HKDF 官方说明](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#hkdf)。

## 验证

`tests/test_media_crypto.py` 使用真实 HKDF/Fernet/HMAC 与合成数据，涵盖四用途 JSON、二进制、密文篡改、不同家庭／secret／用途、独立 RFC 5869 参考派生、来源标识稳定与分隔歧义、实际字节边界、认证后的错误包络、重复键／非有限数／Unicode／深度、解密前大小拒绝及安全错误。无真实 Google 或生产访问。

```powershell
uv run --no-project --link-mode copy --with-requirements requirements.txt --with pytest python -B -m pytest tests/test_media_crypto.py -q --junitxml=test-results/media-crypto.xml
```

最终提交和实际测试证据由作者交接，独立审查后才可进入下一阶段集成；本模块没有修改现有应用加载、schema、Docker COPY 或发布白名单。
