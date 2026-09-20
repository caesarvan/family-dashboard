"""Pure, bounded image normalization. No storage, authorization or network I/O.

Pillow can repair some malformed JPEG entropy streams, even with truncation
disabled. This module checks container completeness and fully loads pixels; it
does not claim to detect every damaged JPEG that Pillow can still decode.
"""
from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from threading import Lock
from typing import Literal
import ctypes
import sys
import warnings
import zlib

from PIL import Image, ImageFile, ImageOps, WebPImagePlugin


MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_EDGE = 1600
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
JPEG_QUALITIES = (90, 85, 80, 75, 65)
FORMATS = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
_WEBP_PILLOW_VERSION = '12.3.0'
_WEBP_NATIVE_VERSION = 0x010600
_DECODE_LOCK = Lock()
_MESSAGES = {
    'invalid_input': '请提供有效的图片字节和媒体类型。',
    'input_too_large': '输入图片不能超过 8 MiB。',
    'unsupported_format': '仅支持 JPEG、PNG 和 WebP 图片，且内容须与媒体类型一致。',
    'invalid_image': '图片不完整或无法安全解码，请重新选择图片。',
    'multiple_frames': '暂不支持动图或多帧图片。',
    'too_many_pixels': '图片像素超过处理上限。',
    'output_too_large': '净化后的图片仍超过 2 MiB，请选择较小图片。',
    'unsafe_decoder_configuration': '当前图片解码配置不允许安全处理。',
}


class MediaImageError(Exception):
    """Only fixed code/message are public; decoder text is never forwarded."""
    def __init__(self, code):
        self.code = code
        self.message = _MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class Preview:
    data: bytes = field(repr=False)
    content_type: Literal['image/jpeg']
    width: int
    height: int
    sha256: str


def _invalid():
    raise MediaImageError('invalid_image')


def _jpeg_segments(raw, *, first_image=False):
    """Walk marker lengths and scan boundaries, not the JPEG entropy codec."""
    if not raw.startswith(b'\xff\xd8'):
        raise MediaImageError('unsupported_format')
    pos, saw_scan = 2, False
    while pos < len(raw):
        start = pos
        if raw[pos] != 255:
            _invalid()
        while pos < len(raw) and raw[pos] == 255:
            pos += 1
        if pos >= len(raw):
            _invalid()
        marker = raw[pos]
        pos += 1
        if marker == 0xD9:
            if (not first_image and pos != len(raw)) or not saw_scan:
                _invalid()
            yield marker, start, pos
            return
        if marker in (0, 0xD8, 1) or 0xD0 <= marker <= 0xD7 or pos + 2 > len(raw):
            _invalid()
        length = int.from_bytes(raw[pos:pos+2], 'big')
        if length < 2 or pos + length > len(raw):
            _invalid()
        pos += length
        yield marker, start, pos
        if marker == 0xDA:
            saw_scan = True
            entropy_start = pos
            while True:
                found = raw.find(b'\xff', pos)
                if found < 0 or found + 1 >= len(raw):
                    _invalid()
                following = found + 1
                while following < len(raw) and raw[following] == 255:
                    following += 1
                if following >= len(raw):
                    _invalid()
                if raw[following] == 0 or 0xD0 <= raw[following] <= 0xD7:
                    pos = following + 1
                    continue
                pos = found
                yield None, entropy_start, pos
                break
    _invalid()


def _exif_orientation(payload):
    """Read only a bounded IFD0 inline SHORT, never follow metadata pointers."""
    if not payload.startswith(b'Exif\0\0'):
        return None
    tiff = payload[6:]
    order = {'little': b'II', 'big': b'MM'}
    endian = next((key for key, value in order.items() if tiff[:2] == value), None)
    if endian is None or len(tiff) < 8 or int.from_bytes(tiff[2:4], endian) != 42:
        return None
    offset = int.from_bytes(tiff[4:8], endian)
    if offset < 8 or offset + 2 > len(tiff):
        return None
    count = int.from_bytes(tiff[offset:offset+2], endian)
    if offset + 2 + count * 12 + 4 > len(tiff):
        return None
    values = []
    for pos in range(offset + 2, offset + 2 + count * 12, 12):
        if int.from_bytes(tiff[pos:pos+2], endian) != 274:
            continue
        if (int.from_bytes(tiff[pos+2:pos+4], endian) != 3 or
                int.from_bytes(tiff[pos+4:pos+8], endian) != 1):
            return None
        value = int.from_bytes(tiff[pos+8:pos+10], endian)
        if not 1 <= value <= 8:
            return None
        values.append(value)
    return values[0] if len(values) == 1 else None


def _jpeg_primary(raw):
    """Keep the complete primary codestream; discard secondary data/metadata.

    MPF must be removed before Pillow opens the JPEG, otherwise its factory can
    switch to an MPO decoder. Keep only generated color markers and, if valid,
    a generated orientation-only EXIF block. Malformed unused EXIF is never
    passed to Pillow; its pixel warning/error policy is unchanged.
    """
    clean = bytearray(b'\xff\xd8')
    orientations = []
    for marker, start, end in _jpeg_segments(raw, first_image=True):
        if marker is None or not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            clean.extend(raw[start:end])
            continue
        # Skip optional FF marker fill bytes; the walker checked the length.
        pos = start
        while raw[pos] == 255:
            pos += 1
        payload = raw[pos+3:end]
        replacement = None
        if marker == 0xE1:
            orientation = _exif_orientation(payload)
            if orientation is not None:
                orientations.append(orientation)
        elif marker == 0xE0 and payload.startswith(b'JFIF\0') and len(payload) >= 14:
            replacement = b'JFIF\0\x01\x01\0\0\x01\0\x01\0\0'
        elif marker == 0xEE and payload.startswith(b'Adobe'):
            if len(payload) < 12 or payload[11] not in (0, 1, 2):
                _invalid()
            replacement = b'Adobe\0\x64\0\0\0\0' + payload[11:12]
        if replacement is not None:
            clean.extend(bytes((255, marker)) + (len(replacement)+2).to_bytes(2, 'big') + replacement)
    if len(orientations) == 1:
        # IFD0 has one inline SHORT and no next IFD. No source bytes survive.
        exif = (b'Exif\0\0II\x2a\0\x08\0\0\0\x01\0\x12\x01\x03\0\x01\0\0\0' +
                orientations[0].to_bytes(2, 'little') + b'\0' * 6)
        clean[2:2] = b'\xff\xe1' + (len(exif)+2).to_bytes(2, 'big') + exif
    return bytes(clean)


def _container(raw, fmt):
    if fmt == 'JPEG':
        for _ in _jpeg_segments(raw):
            pass
        return
    if fmt == 'PNG':
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise MediaImageError('unsupported_format')
        pos, first = 8, True
        while pos + 12 <= len(raw):
            size = int.from_bytes(raw[pos:pos+4], 'big')
            kind = raw[pos+4:pos+8]
            end = pos + 12 + size
            if end > len(raw) or first and (kind != b'IHDR' or size != 13):
                _invalid()
            if zlib.crc32(memoryview(raw)[pos+4:end-4]) != int.from_bytes(raw[end-4:end], 'big'):
                _invalid()
            if kind in (b'acTL', b'fcTL', b'fdAT'):
                raise MediaImageError('multiple_frames')
            if kind == b'IEND':
                if size or end != len(raw):
                    _invalid()
                return
            first, pos = False, end
        _invalid()
    if fmt == 'WEBP':
        if len(raw) < 20 or raw[:4] != b'RIFF' or raw[8:12] != b'WEBP':
            raise MediaImageError('unsupported_format')
        if int.from_bytes(raw[4:8], 'little') + 8 != len(raw):
            _invalid()
        pos = 12
        while pos + 8 <= len(raw):
            kind = raw[pos:pos+4]
            size = int.from_bytes(raw[pos+4:pos+8], 'little')
            end = pos + 8 + size
            if end + (size % 2) > len(raw):
                _invalid()
            if kind in (b'ANIM', b'ANMF') or kind == b'VP8X' and size and raw[pos+8] & 2:
                raise MediaImageError('multiple_frames')
            pos = end + size % 2
        if pos != len(raw):
            _invalid()


def _check_image(source, fmt):
    if source.format != fmt:
        raise MediaImageError('unsupported_format')
    if source.width < 1 or source.height < 1 or source.width * source.height > MAX_PIXELS:
        raise MediaImageError('too_many_pixels')
    if getattr(source, 'n_frames', 1) != 1 or getattr(source, 'is_animated', False):
        raise MediaImageError('multiple_frames')


def _verify_image(raw, fmt):
    # ImageFile.__exit__ only closes file pointers. End this scope before opening
    # the decoding image so WebP's retained decoder/canvas is also released.
    with closing(Image.open(BytesIO(raw), formats=[fmt])) as checked:
        _check_image(checked, fmt)
        checked.verify()


def _webp_frame(raw):
    # This narrow adapter depends on the pinned Pillow WebP plugin. Its normal
    # load() keeps the decoder canvas, returned frame bytes and a copied raw
    # pixel core alive together. Fully decode first, then leave this scope to
    # release the plugin/decoder before mapping the complete frame below.
    if (Image.__version__ != _WEBP_PILLOW_VERSION or
            Image.core.PILLOW_VERSION != _WEBP_PILLOW_VERSION):
        raise MediaImageError('unsafe_decoder_configuration')
    with closing(Image.open(BytesIO(raw), formats=['WEBP'])) as source:
        _check_image(source, 'WEBP')
        if type(source) is not WebPImagePlugin.WebPImageFile:
            raise MediaImageError('unsafe_decoder_configuration')
        size, _, _, frames, rawmode = source._decoder.get_info()
        if (size != source.size or frames != 1 or rawmode not in ('RGBA', 'RGBX') or
                rawmode != source.rawmode or source.mode != ('RGB' if rawmode == 'RGBX' else 'RGBA')):
            raise MediaImageError('unsafe_decoder_configuration')
        frame = source._decoder.get_next()  # Actual libwebp full-frame decode.
        if (type(frame) is not tuple or len(frame) != 2 or type(frame[0]) is not bytes or
                len(frame[0]) != size[0] * size[1] * 4 or type(frame[1]) is not int):
            raise MediaImageError('invalid_image')
        return size, rawmode, source.info.copy(), frame[0]


def _webp_metadata(raw):
    # The plugin allocates animation canvases even for one frame. Return only
    # small metadata, letting this entire plugin/decoder die before allocating
    # the destination buffer or invoking the single-frame decoder.
    with closing(Image.open(BytesIO(raw), formats=['WEBP'])) as source:
        _check_image(source, 'WEBP')
        if type(source) is not WebPImagePlugin.WebPImageFile:
            raise MediaImageError('unsafe_decoder_configuration')
        size, _, _, frames, rawmode = source._decoder.get_info()
        if (size != source.size or frames != 1 or rawmode not in ('RGBA', 'RGBX') or
                rawmode != source.rawmode or source.mode != ('RGB' if rawmode == 'RGBX' else 'RGBA')):
            raise MediaImageError('unsafe_decoder_configuration')
        return size, rawmode, source.info.copy()


def _webp_native_library():
    # Use only the already imported Pillow extension and its linked libwebp.
    # Never search the system, honor an environment library path, or fall back
    # to the higher-memory decoder after a Linux ABI/configuration failure.
    if (Image.__version__ != _WEBP_PILLOW_VERSION or
            Image.core.PILLOW_VERSION != _WEBP_PILLOW_VERSION):
        raise MediaImageError('unsafe_decoder_configuration')
    try:
        library = ctypes.CDLL(WebPImagePlugin._webp.__file__)
        library.WebPGetDecoderVersion.argtypes = []
        library.WebPGetDecoderVersion.restype = ctypes.c_int
        if library.WebPGetDecoderVersion() != _WEBP_NATIVE_VERSION:
            raise ValueError('unsupported libwebp version')
        # Public libwebp 1.6.0 decode.h, no private C struct layout assumptions.
        library.WebPGetInfo.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        library.WebPGetInfo.restype = ctypes.c_int
        library.WebPDecodeRGBAInto.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                             ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_int]
        library.WebPDecodeRGBAInto.restype = ctypes.c_void_p
        return library
    except (AttributeError, OSError, ValueError):
        raise MediaImageError('unsafe_decoder_configuration') from None


def _webp_native_frame(raw):
    library = _webp_native_library()
    size, rawmode, info = _webp_metadata(raw)
    width, height = ctypes.c_int(), ctypes.c_int()
    if not library.WebPGetInfo(raw, len(raw), ctypes.byref(width), ctypes.byref(height)):
        _invalid()
    if (width.value, height.value) != size:
        raise MediaImageError('unsafe_decoder_configuration')
    # Dimensions already passed _check_image's 20 MP limit. No scaling or
    # incremental/partial decode: this API returns only after a complete frame.
    pixels = bytearray(size[0] * size[1] * 4)
    destination = (ctypes.c_uint8 * len(pixels)).from_buffer(pixels)
    result = library.WebPDecodeRGBAInto(raw, len(raw), destination, len(pixels), size[0] * 4)
    if not result:
        _invalid()
    if result != ctypes.addressof(destination):
        raise MediaImageError('unsafe_decoder_configuration')
    # libwebp writes alpha=255 for opaque images. Mapping as RGBX preserves
    # Pillow's existing opaque-mode resampling behavior without another copy.
    return size, rawmode, info, pixels


def _load_image(raw, fmt):
    if fmt == 'WEBP':
        size, rawmode, info, pixels = (_webp_native_frame(raw) if sys.platform == 'linux'
                                      else _webp_frame(raw))
        # RGBX is opaque padding, never an alpha channel. Both modes are mapped
        # read-only by pinned Pillow; the image owns a reference to these bytes.
        image = Image.frombuffer(rawmode, size, pixels, 'raw', rawmode, 0, 1)
        if image.mode != rawmode or image.size != size or not image.readonly:
            image.close()
            raise MediaImageError('unsafe_decoder_configuration')
        image.info = info
        return image
    source = Image.open(BytesIO(raw), formats=[fmt])
    try:
        _check_image(source, fmt)
        source.load()  # Do not use draft/thumbnail before full decode.
        return source
    except BaseException:
        source.close()
        raise


def _encode(clean):
    for quality in JPEG_QUALITIES:
        output = BytesIO()
        clean.save(output, format='JPEG', quality=quality, subsampling=2, optimize=True)
        raw = output.getvalue()
        # Even fresh Pillow JPEGs have a generated JFIF APP0 marker. Drop all
        # APP/COM markers so the returned JPEG carries no metadata segments.
        stripped = bytearray(b'\xff\xd8')
        for marker, start, end in _jpeg_segments(raw):
            if marker is None or not (0xE0 <= marker <= 0xEF or marker == 0xFE):
                stripped.extend(raw[start:end])
        if len(stripped) <= MAX_OUTPUT_BYTES:
            return bytes(stripped)
    raise MediaImageError('output_too_large')


def sanitize_media_preview(raw: bytes, mime_type: str) -> Preview:
    if type(raw) is not bytes or not raw or type(mime_type) is not str:
        raise MediaImageError('invalid_input')
    if len(raw) > MAX_INPUT_BYTES:
        raise MediaImageError('input_too_large')
    if mime_type not in FORMATS:
        raise MediaImageError('unsupported_format')
    # Never toggle process-wide Pillow flags, even temporarily. Refuse an
    # explicitly relaxed decoder instead of silently relying on it.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise MediaImageError('unsafe_decoder_configuration')
    fmt = FORMATS[mime_type]
    try:
        if fmt == 'JPEG':
            raw = _jpeg_primary(raw)
        _container(raw, fmt)
        # Decoder warnings may contain source metadata. Convert them to fixed
        # errors rather than forwarding their text to logs or the caller.
        # Serialize this helper's allocations and warning contexts. In the
        # Python 3.12 runtime warning filters are not context-local per thread.
        with _DECODE_LOCK, warnings.catch_warnings():
            warnings.simplefilter('error')
            _verify_image(raw, fmt)
            with closing(_load_image(raw, fmt)) as source:
                ImageOps.exif_transpose(source, in_place=True)
                source.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                with closing(source.convert('RGBA')) as rgba, closing(Image.new('RGB', source.size, 'white')) as clean:
                    with closing(rgba.getchannel('A')) as alpha:
                        clean.paste(rgba, mask=alpha)
                    result = _encode(clean)
                    width, height = clean.size
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise MediaImageError('unsafe_decoder_configuration')
        return Preview(result, 'image/jpeg', width, height, sha256(result).hexdigest())
    except MediaImageError as error:
        code = error.code
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        code = 'too_many_pixels'
    except Exception:
        # Includes corrupt EXIF/chunks, codec failures and rejected warnings.
        code = 'invalid_image'
    # Raising inside an except block, even with "from None", would retain
    # the original exception object in __context__. Leave the handler first.
    raise MediaImageError(code)
