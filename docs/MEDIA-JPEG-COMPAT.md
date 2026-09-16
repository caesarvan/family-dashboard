# JPEG 主图兼容与边界

本候选处理可合成复现的 JPEG 兼容问题，不表示已确定真实照片的失败原因。用户新一轮十张照片中五张保存、五张返回 `invalid_image`；仅凭该固定错误码不能判断尾部、EXIF、像素损坏或其他具体原因。补丁尚未部署，也不自动重新下载以前失败的照片。

完整遍历第一张 JPEG 的 marker 长度和扫描边界，只有走到真实主图 EOI 后才丢弃附加数据。APP／COM 内的 `FFD9` 不是图片结束。完整主图之后的填充、第二张 JPEG、MPO／增益图或 Motion Photo 附加部分不交给解码器；只保留首张静态主图，不播放附加视频、不合成 HDR 或保留多视角。

解码前移除 MPF、EXIF、XMP、ICC、缩略图、注释等来源 metadata，防止 Pillow 因 MPF 切换成 MPO。仅重新生成必要的 JFIF／Adobe 色彩解释标志；Adobe transform 须为合法 0／1／2。EXIF 只在有界 IFD0 内读取唯一的 inline SHORT、count=1、值 1..8 的 orientation；不跟随任意 metadata 指针。可读的合法方向被写入全新最小 EXIF 供旋转，损坏或含歧义的方向不推断，其他坏 metadata 丢弃。PNG／WebP 的 EXIF 和动画拒绝逻辑保持。

全部输入（包括丢弃的附加字节）仍受 **8 MiB** 限制；像素 **2000 万**、输出最长边 **1600**、输出 **2 MiB** 不变。保留首图完整容器校验、Pillow `verify()` 与全像素 `load()`，不启用 `LOAD_TRUNCATED_IMAGES`，不降低 warnings-as-error，不修改全局解码配置。缺少扫描、坏段长度、截断主图和额外第二张图片不能替第一张补全合法容器。Pillow／libjpeg 本来能修复的部分损坏熵流仍有既有检测限制，不宣称严格识别所有像素损坏。

解码后依旧生成全新 RGB JPEG；所有来源 metadata、APP／COM 和尾部附加字节均不留存。异常只返回既有固定错误码／文字，不输出原字节、来源 metadata 或解码器原文。原权限、worker、Picker、UI 和 schema 不变。

```powershell
python -B -X utf8 -m pytest -q tests/test_media_images.py tests/test_media_jpeg_compat.py
```

专项使用真实 Pillow 生成 JPEG／双图 MPO 和明确合成 EXIF／XMP／附加数据，覆盖八方向、大小／像素限制、完整性、颜色和输出清洁。带增益图标识的样例仅是 Ultra HDR 类封装合成，不是全部厂商 HDR／Motion Photo 格式符合性或真实 Google 验收。既有 PNG／WebP 动图仍拒绝；下一次本人实际选片才可验证本补丁是否解决这些照片的问题。
