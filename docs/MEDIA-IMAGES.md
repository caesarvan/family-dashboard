# 精选媒体的图片预览净化

`media_images.py` 是纯字节 helper：不访问 Google、文件系统或网络，不做成员权限、存储、加密或应用注册。使用现有固定依赖 Pillow 12.3.0；本候选尚未接入媒体功能或生产。未来调用者必须自己负责媒体许可、请求限流、并发与内存预算，并在解码后的持久化事务中重新验证成员会话和家庭。

```python
from media_images import sanitize_media_preview, MediaImageError

preview = sanitize_media_preview(raw_bytes, 'image/png')
# frozen dataclass Preview，data 本身为不可变 bytes，repr 不包含 data。
# preview.data: bytes
# preview.content_type: Literal['image/jpeg']
# preview.width / preview.height: int
# preview.sha256: 返回 JPEG 字节的 SHA-256 小写十六进制
```

输入必须是非空 `bytes` 和精确 MIME `image/jpeg`、`image/png` 或 `image/webp`。不接受 bytearray、路径、URL、data URL、MIME 参数或大小写别名。原始输入最多 **8 MiB（8×1024²）**，总像素最多 **20,000,000**；等于上限允许。实际图片格式必须与 MIME 一致。GIF、APNG/WebP 动画、多帧/MPO、格式不符、可检测截断和尾部附加内容都拒绝。

## 处理契约

1. 校验输入大小与容器边界：JPEG marker 长度、scan 边界和最终 EOI；PNG chunk 长度、CRC 与最终 IEND；WebP RIFF 总长、chunk 边界及动画标志。容器后不接受额外数据或第二张图片。
2. Pillow 打开后显式检查格式、像素数和帧数，执行 `verify()`；重新打开并执行完整 `load()`，不在解码前用 draft/缩小规避实际尺寸检查。Pillow 的打开是惰性操作，`verify()` 不能替代像素解码。[Pillow Image 接口](https://pillow.readthedocs.io/en/stable/reference/Image.html)
3. 应用 EXIF 方向后等比缩至 **1600×1600** 内；小图不放大。RGBA 及透明调色板图片合成到白色背景，再复制到全新 RGB 画布。颜色配置不从源文件继承，也不以 ICC 做色彩管理。
4. 从新画布编码 JPEG，质量依次尝试 **90、85、80、75、65**，固定 4:2:0 和 optimize；最多五次，不继续扩大或缩小尺寸。移除所有 APP/COM 段，包括编码器新生成的 JFIF APP0，所以输出没有 EXIF、GPS、XMP、ICC、文件名、注释或源 metadata，Pillow 重读时 `info` 为空。
5. 第一份不超过 **2 MiB（2×1024²）** 的结果返回；全部超限则失败。SHA-256 仅描述本次返回字节，不承诺不同 Pillow/codec 版本产生相同 JPEG 或哈希。

不会更改 `Image.MAX_IMAGE_PIXELS` 或 `ImageFile.LOAD_TRUNCATED_IMAGES`。像素上限独立显式检查，Pillow 自身更严格的限制仍可能提前拒绝。若全局已启用 `LOAD_TRUNCATED_IMAGES`，helper 固定报配置错误而不临时切换全局状态；调用代码也不得在并发处理期间改变这些全局设置。

图片处理可能同时持有解码、方向转换及输出缓冲；20M 像素不是峰值内存保证。helper 用进程内锁串行化自身的 Pillow 解码/编码及 warning context（Python 3.12 的 warning filters 并非线程局部状态），不更改 Pillow 全局配置。未来独立媒体 worker 推荐一次处理一张，不在 Web 请求中批量并发调用；其他模块也不应同时修改 warning filters 或开启 PIL 的 metadata 调试日志。helper 不引入后台线程、队列或跨进程资源控制。

## 损坏检测的实际边界

**不保证识别所有可被 Pillow 修复的 JPEG 熵损坏。** 本地真实探针将 JPEG scan 截至 10%、50%、90%，再补 EOI；Pillow 12.3.0 在 `LOAD_TRUNCATED_IMAGES=False` 下仍可 `verify()`、完整 `load()`。其官方解码器实现抑制 libjpeg 警告，当前没有通过这些公开接口取得所有警告的严格模式。[Pillow JPEG 解码实现](https://github.com/python-pillow/Pillow/blob/12.3.0/src/libImaging/JpegDecode.c)

这些输入可以被本 helper 接受，但返回的是解码像素重新生成的 JPEG，原始压缩段、元数据和附加字节均不传播。测试把此边界记录为 `accepted-normalized`，不会写成“已严格拒绝所有截断”。正常缺失尾标记、断裂 chunk、CRC 错误、无法解码的像素数据等仍拒绝。这里不实现自制 JPEG 熵解码器，也不以此为由禁用常见 progressive JPEG。

净化不等同于安全扫描、来源真实性检查或视觉隐私判断；像素里可见的文字、脸部或地址不会被抹除。媒体模块须依据用户选择及独立成员/电视许可决定展示，不以该 helper 代替权限校验。

## 安全错误

`MediaImageError` 只公开固定 `code` 与中文 `message`。常规 decoder 异常和警告转为固定错误，隐藏原始异常链，不把 metadata、原始字节、文件名或 decoder 文本写入日志。不会记录输入或返回原始异常。

| code | 含义 |
|---|---|
| `invalid_input` | 参数类型或空输入不正确 |
| `input_too_large` | 输入超过 8 MiB |
| `unsupported_format` | MIME/实际格式不支持或不一致 |
| `invalid_image` | 容器/解码/元数据解析失败，或 decoder 警告 |
| `multiple_frames` | 动画或多帧容器 |
| `too_many_pixels` | 显式像素上限或 Pillow 防解压炸弹限制 |
| `output_too_large` | 五档编码后仍超过 2 MiB |
| `unsafe_decoder_configuration` | 全局已开启宽松截断处理 |

该模块不绑定 HTTP 状态。调用方只能投影以上安全字段，不能暴露 Python traceback 或局部变量。

## 验证

`tests/test_media_images.py` 使用 Pillow 实际生成的 JPEG/PNG/WebP、progressive/subsampling、灰度/CMYK、RGBA/调色板、全部八种 EXIF 方向、真实 ICC/XMP/EXIF/GPS/注释，以及实际 APNG/WebP 动画/MPO。包括 20M 像素边界、8 MiB 边界、真实噪声触发质量降阶、截断/CRC/尾部内容和上述补 EOI 可修复边界。输出均重新 verify/load，检查尺寸、RGB、完整 SHA-256 和空 metadata。

仅极小输出额度、异常文本与 warning 路径使用局部测试注入；不把它们写成真实 codec 失败。首跑单帧 APNG fixture 被 Pillow 优化成普通 PNG，修正为带有效单帧动画控制块并可真实解码的 fixture 后重新执行；失败原件保留于 ignored `test-results/media-images/`。未验证真实 Google 返回、生产容器、媒体权限、加密/保存或电视展示，这些属于后续模块。
