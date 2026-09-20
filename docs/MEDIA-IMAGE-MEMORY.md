# 图片解码内存修订

本分支仅修订 `media_images.py` 的缓冲生命周期。仍接受 JPEG、PNG、WebP，输入上限 8 MiB、20 MP，完整解码后按方向处理，最长边 1600，透明像素合成白底，输出无元数据的 JPEG（不超过 2 MiB）。不改权限、上传协议、并发许可、容器预算或依赖版本。

## 原因与实现

实际 Linux 上传验证中，20 MP WebP 与已持有的 64 MiB 视频响应重叠时，384 MiB 应用容器发生 OOM。仅释放 `verify()` 对象、或完整 `load()` 后再复制并关闭插件，均未充分降低本机峰值；这些试验原件保留，不能作为成功修复证据。

Pillow 12.3.0 的图片上下文退出只关闭文件指针，不释放仍被局部变量引用的插件。WebP 的普通 `load()` 同时保留 libwebp 解码器、完整帧字节和新建的 Pillow 像素副本。修订将验证放入独立作用域；WebP 通过同一个真实 `WebPAnimDecoder.get_next()` 解码完整帧，核对单帧、RGBA/RGBX、尺寸和精确的 `宽 × 高 × 4` 字节数，再释放插件和解码器，才以 `Image.frombuffer` 只读映射完整帧。RGBX 表示不透明填充，不能当成透明通道。

这是对已固定依赖的窄适配，使用 Pillow 私有插件接口。Python 包和二进制核心必须都为 **12.3.0**；版本、插件类型、模式或只读映射合同失配会安全拒绝。升级 Pillow 时必须先重新审查适配和实际资源测试，不可只改版本常量。不存在缩小解码、跳过完整像素、接受动图或截断输入的路径。JPEG/PNG 仍走公共 `load()`；所有后处理图片显式关闭。

源码依据：[Pillow WebP 插件](https://github.com/python-pillow/Pillow/blob/12.3.0/src/PIL/WebPImagePlugin.py)、[原生 WebP 解码器](https://github.com/python-pillow/Pillow/blob/12.3.0/src/_webp.c)、[Image 的关闭与映射实现](https://github.com/python-pillow/Pillow/blob/12.3.0/src/PIL/Image.py)。

## 已验证与待验证

- Windows 定向测试：`test_media_image_memory.py`、`test_media_images.py`、`test_media_jpeg_compat.py` 共 **159 项通过**，含真实完整帧与公开解码器逐像素比较、RGBA/RGBX、8 种 WebP 方向、20 MP、透明白底、压缩数据截断、动画拒绝、合同失配和重复调用的插件释放。
- 使用固定基线与本次实现分别真实处理 32 种合成 WebP（两种模式、无损/有损、8 种方向、需要缩放）：输出 JPEG 全部逐字节相同。
- 同一 Windows 子进程一直持有 64 MiB 合成缓冲，依次处理原 Linux 合成的三张 20 MP JPEG/PNG/WebP，重复三轮。最终进程峰值 **334,905,344 B**，原实现单轮峰值 **451,440,640 B**；九次输出与基线对应图片一致，调用后工作集约 95 MB。测量使用操作系统进程计数，不是 Python 对象估算。

Windows 测量不代表 Linux cgroup、Flask/SQLite/加密开销或生产容量已通过。仍需以审查后的固定源码，在原 **384 MiB / 64 MiB 响应重叠** 条件下重新执行完整上传、确认和 cgroup 检查。原 Linux 失败与已通过的独立 Nginx 流程分开保留，不重写旧结论。本次没有 SSH、Docker、生产修改或真实媒体输入。
