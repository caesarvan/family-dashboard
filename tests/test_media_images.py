"""Generated real images, corrupted containers and explicit Pillow limitations."""
from dataclasses import FrozenInstanceError
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import random
import struct
import traceback
import zlib

import pytest
from PIL import Image, ImageFile, PngImagePlugin

import media_images as media
from media_images import MediaImageError, Preview, sanitize_media_preview


MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
SECRET = b'SYNTHETIC_METADATA_DO_NOT_PROPAGATE'


def encoded(fmt='PNG', *, size=(80, 40), mode='RGB', color='red', **options):
    with Image.new(mode, size, color) as image:
        out = BytesIO()
        image.save(out, format=fmt, **options)
        return out.getvalue()


def unpack(result):
    assert isinstance(result, Preview)
    assert type(result.data) is bytes and result.content_type == 'image/jpeg'
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    assert len(result.data) <= 2 * 1024 * 1024
    with Image.open(BytesIO(result.data)) as check:
        assert check.format == 'JPEG' and check.mode == 'RGB'
        assert check.size == (result.width, result.height)
        assert check.info == {} and len(check.getexif()) == 0
        check.verify()
    with Image.open(BytesIO(result.data)) as check:
        check.load()
        return check.copy()


def rejected(raw, mime='image/png', code=None):
    with pytest.raises(MediaImageError) as failure:
        sanitize_media_preview(raw, mime)
    if code:
        assert failure.value.code == code
    assert failure.value.args == (failure.value.message,)
    assert SECRET.decode() not in str(failure.value) + repr(failure.value)
    return failure.value


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP'])
@pytest.mark.parametrize('size', [(80, 40), (1, 1), (2400, 1200), (1200, 2400), (3000, 1)])
def test_real_formats_decode_resize_without_upscaling(fmt, size):
    result = sanitize_media_preview(encoded(fmt, size=size), MIMES[fmt])
    with unpack(result) as image:
        assert max(image.size) <= 1600
        assert image.width <= size[0] and image.height <= size[1]
        assert abs(image.width / image.height - size[0] / size[1]) <= max(1, size[0] / size[1]) / min(image.size)
        if max(size) <= 1600:
            assert image.size == size


@pytest.mark.parametrize('progressive', [False, True])
@pytest.mark.parametrize('subsampling', [0, 1, 2])
def test_baseline_and_progressive_jpeg_supported(progressive, subsampling):
    raw = encoded('JPEG', progressive=progressive, subsampling=subsampling)
    with unpack(sanitize_media_preview(raw, 'image/jpeg')) as image:
        assert image.size == (80, 40)


@pytest.mark.parametrize('fmt,mode,color', [('JPEG', 'L', 96), ('JPEG', 'CMYK', (0, 255, 255, 0)),
                                         ('PNG', 'L', 96), ('WEBP', 'RGB', 'red')])
def test_supported_color_modes_become_rgb(fmt, mode, color):
    result = sanitize_media_preview(encoded(fmt, mode=mode, color=color), MIMES[fmt])
    with unpack(result) as image:
        pixel = image.getpixel((20, 20))
        if mode == 'L':
            assert max(abs(c-96) for c in pixel) < 3
        else:
            assert pixel[0] > 240 and max(pixel[1:]) < 15


@pytest.mark.parametrize('fmt', ['PNG', 'WEBP'])
@pytest.mark.parametrize('alpha,expected', [(0, (255, 255, 255)), (128, (127, 127, 255)), (255, (0, 0, 255))])
def test_rgba_is_composited_on_white(fmt, alpha, expected):
    result = sanitize_media_preview(encoded(fmt, mode='RGBA', color=(0, 0, 255, alpha)), MIMES[fmt])
    with unpack(result) as image:
        assert max(abs(a-b) for a, b in zip(image.getpixel((20, 20)), expected)) < 4


def test_palette_transparency_is_not_lost():
    with Image.new('P', (32, 32)) as image:
        image.putpalette([255, 0, 0] + [0, 0, 0]*255)
        out = BytesIO()
        image.save(out, format='PNG', transparency=0)
    with unpack(sanitize_media_preview(out.getvalue(), 'image/png')) as result:
        assert result.getpixel((16, 16)) == (255, 255, 255)


@pytest.mark.parametrize('orientation,labels', [(1, 'rgby'), (2, 'gryb'), (3, 'ybgr'), (4, 'byrg'),
                                                (5, 'rbgy'), (6, 'bryg'), (7, 'ygbr'), (8, 'gyrb')])
def test_all_exif_orientations_applied_before_metadata_removal(orientation, labels):
    colors = {'r': (255, 0, 0), 'g': (0, 255, 0), 'b': (0, 0, 255), 'y': (255, 255, 0)}
    with Image.new('RGB', (80, 40)) as image:
        for region, label in [((0, 0, 40, 20), 'r'), ((40, 0, 80, 20), 'g'),
                              ((0, 20, 40, 40), 'b'), ((40, 20, 80, 40), 'y')]:
            image.paste(colors[label], region)
        exif = Image.Exif()
        exif[274] = orientation
        exif[270] = SECRET.decode()
        out = BytesIO()
        image.save(out, format='PNG', exif=exif)
    with unpack(sanitize_media_preview(out.getvalue(), 'image/png')) as result:
        assert result.size == ((40, 80) if orientation >= 5 else (80, 40))
        positions = [(5, 5), (result.width-6, 5), (5, result.height-6), (result.width-6, result.height-6)]
        for label, point in zip(labels, positions):
            assert max(abs(a-b) for a, b in zip(result.getpixel(point), colors[label])) < 10


def test_orientation_then_resize_preserves_portrait_geometry():
    exif = Image.Exif()
    exif[274] = 6
    result = sanitize_media_preview(encoded('JPEG', size=(3000, 1500), exif=exif), 'image/jpeg')
    with unpack(result) as image:
        assert image.size == (800, 1600)


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP'])
def test_exif_xmp_icc_comments_and_names_never_survive(fmt):
    exif = Image.Exif()
    exif[270] = SECRET.decode()
    exif[315] = '../private/source-filename.jpg'
    exif[34853] = {1: 'N', 2: (12.0, 34.0, 56.0), 3: 'E', 4: (23.0, 45.0, 56.0)}
    options = {'exif': exif, 'icc_profile': SECRET + b'_ICC', 'xmp': SECRET + b'_XMP'}
    if fmt == 'PNG':
        info = PngImagePlugin.PngInfo()
        info.add_text('Filename', '../private/source-filename.jpg')
        info.add_itxt('XML:com.adobe.xmp', SECRET.decode())
        info.add_text('Comment', SECRET.decode())
        options['pnginfo'] = info
    if fmt == 'JPEG':
        options['comment'] = SECRET + b'_COMMENT'
    raw = encoded(fmt, **options)
    assert SECRET in raw
    result = sanitize_media_preview(raw, MIMES[fmt])
    assert SECRET not in result.data and b'source-filename' not in result.data
    assert 'SYNTHETIC' not in repr(result) and not hasattr(result, 'filename')
    with unpack(result):
        pass


@pytest.mark.parametrize('raw', [None, 'bytes', b'', bytearray(b'x'), memoryview(b'x'), 12])
def test_input_must_be_nonempty_bytes(raw):
    rejected(raw, code='invalid_input')


@pytest.mark.parametrize('mime', [None, 12, [], 'image/gif', 'image/svg+xml', 'image/avif', 'IMAGE/PNG', 'image/png; charset=utf-8'])
def test_mime_is_strict(mime):
    rejected(encoded(), mime, 'invalid_input' if type(mime) is not str else 'unsupported_format')


@pytest.mark.parametrize('actual,declared', [('JPEG', 'PNG'), ('PNG', 'WEBP'), ('WEBP', 'JPEG')])
def test_actual_format_must_match_mime(actual, declared):
    rejected(encoded(actual), MIMES[declared], 'unsupported_format')


def test_eight_mib_input_limit_is_inclusive_before_decode():
    rejected(b'x' * (8 * 1024 * 1024), code='unsupported_format')
    rejected(b'x' * (8 * 1024 * 1024 + 1), code='input_too_large')


def test_twenty_megapixels_is_supported_but_above_it_is_rejected():
    raw = encoded('PNG', size=(5000, 4000))
    with unpack(sanitize_media_preview(raw, 'image/png')) as image:
        assert image.size == (1600, 1280)
    altered = bytearray(raw)
    altered[16:20] = struct.pack('>I', 5001)
    altered[29:33] = struct.pack('>I', zlib.crc32(altered[12:29]))
    rejected(bytes(altered), code='too_many_pixels')


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP'])
@pytest.mark.parametrize('cut', [1, 8, 30])
def test_detectable_truncation_is_rejected(fmt, cut):
    rejected(encoded(fmt)[:-cut], MIMES[fmt], 'invalid_image')


@pytest.mark.parametrize('fmt', ['JPEG', 'PNG', 'WEBP'])
def test_trailing_payload_or_second_image_is_rejected(fmt):
    raw = encoded(fmt)
    rejected(raw + SECRET, MIMES[fmt], 'invalid_image')
    rejected(raw + raw, MIMES[fmt], 'invalid_image')


@pytest.mark.parametrize('fmt', ['PNG', 'WEBP', 'MPO'])
def test_real_multi_frame_files_are_rejected(fmt):
    with Image.new('RGB', (32, 32), 'red') as first, Image.new('RGB', (32, 32), 'blue') as second:
        out = BytesIO()
        first.save(out, format=fmt, save_all=True, append_images=[second], duration=100, loop=0)
    error = rejected(out.getvalue(), 'image/jpeg' if fmt == 'MPO' else MIMES[fmt])
    assert error.code in ('multiple_frames', 'invalid_image', 'unsupported_format')


def test_single_frame_apng_animation_container_is_rejected():
    raw = encoded('PNG')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    # Pillow optimizes save_all of one frame to ordinary PNG. Construct valid
    # APNG control chunks around its real generated IDAT and verify real decode.
    animation = chunk(b'acTL', struct.pack('>II', 1, 0))
    animation += chunk(b'fcTL', struct.pack('>IIIIIHHBB', 0, 80, 40, 0, 0, 1, 10, 0, 0))
    raw = raw[:33] + animation + raw[33:]
    with Image.open(BytesIO(raw)) as image:
        assert image.n_frames == 1
        image.load()
    rejected(raw, code='multiple_frames')


def test_png_crc_and_internally_truncated_deflate_are_rejected():
    raw = encoded('PNG', size=(128, 128))
    corrupt = bytearray(raw)
    corrupt[-5] ^= 1
    rejected(bytes(corrupt), code='invalid_image')
    pos = raw.index(b'IDAT') - 4
    size = int.from_bytes(raw[pos:pos+4], 'big')
    body = raw[pos+8:pos+8+size//2]
    chunk = struct.pack('>I', len(body)) + b'IDAT' + body
    chunk += struct.pack('>I', zlib.crc32(b'IDAT' + body))
    # Valid outer lengths/CRC and IEND, invalid compressed pixels.
    rejected(raw[:pos] + chunk + raw[pos+12+size:], code='invalid_image')


@pytest.mark.parametrize('fraction', [0.1, 0.5, 0.9])
def test_documented_jpeg_repair_boundary_is_normalized_not_claimed_strict(fraction):
    with Image.frombytes('RGB', (160, 160), random.Random(1).randbytes(160*160*3)) as image:
        out = BytesIO()
        image.save(out, format='JPEG')
    original = out.getvalue()
    damaged = original[:int(len(original) * fraction)] + b'\xff\xd9'
    # libjpeg warnings are not exposed by Pillow: verify()+load() accept these.
    result = sanitize_media_preview(damaged, 'image/jpeg')
    assert result.data != damaged
    with unpack(result) as decoded:
        assert decoded.size == (160, 160)


def test_bad_marker_length_and_missing_scan_are_rejected():
    rejected(b'\xff\xd8\xff\xe1\xff\xff' + SECRET + b'\xff\xd9', 'image/jpeg', 'invalid_image')
    rejected(b'\xff\xd8\xff\xd9', 'image/jpeg', 'invalid_image')


def test_real_noise_uses_bounded_quality_reduction(monkeypatch):
    with Image.frombytes('RGB', (1600, 1600), random.Random(42).randbytes(1600*1600*3)) as noise:
        out = BytesIO()
        noise.save(out, format='PNG')
    raw = out.getvalue()
    assert len(raw) <= 8 * 1024 * 1024
    save, qualities = Image.Image.save, []
    def track(self, target, format=None, **options):
        qualities.append(options['quality'])
        return save(self, target, format=format, **options)
    monkeypatch.setattr(Image.Image, 'save', track)
    result = sanitize_media_preview(raw, 'image/png')
    with unpack(result) as image:
        assert image.size == (1600, 1600)
    assert 1 < len(qualities) <= len(media.JPEG_QUALITIES)
    assert qualities == list(media.JPEG_QUALITIES[:len(qualities)])


def test_output_budget_failure_has_finite_attempts(monkeypatch):
    raw = encoded()
    monkeypatch.setattr(media, 'MAX_OUTPUT_BYTES', 1)
    save, calls = Image.Image.save, []
    def track(self, target, format=None, **options):
        calls.append(options['quality'])
        return save(self, target, format=format, **options)
    monkeypatch.setattr(Image.Image, 'save', track)
    rejected(raw, code='output_too_large')
    assert calls == list(media.JPEG_QUALITIES)


def test_immutable_preview_does_not_repr_bytes():
    result = sanitize_media_preview(encoded(), 'image/png')
    with pytest.raises(FrozenInstanceError):
        result.width = 12
    assert 'data=' not in repr(result) and not hasattr(result, '__dict__')


def test_never_mutates_pillow_global_configuration(monkeypatch):
    previous = Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES
    sanitize_media_preview(encoded(), 'image/png')
    rejected(b'bad')
    assert (Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES) == previous
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', True)
    rejected(encoded(), code='unsafe_decoder_configuration')
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True
    assert Image.MAX_IMAGE_PIXELS == previous[0]


def test_explicit_pixel_limit_does_not_depend_on_pillow_global_limit(monkeypatch):
    raw = bytearray(encoded())
    raw[16:24] = struct.pack('>II', 20_000_001, 1)
    raw[29:33] = struct.pack('>I', zlib.crc32(raw[12:29]))
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', None)
    rejected(bytes(raw), code='too_many_pixels')
    assert Image.MAX_IMAGE_PIXELS is None


def test_parallel_calls_leave_warning_filters_and_pillow_flags_unchanged():
    import warnings
    inputs = [encoded(fmt, size=(300, 200), color=color) for fmt, color in
              [('JPEG', 'red'), ('PNG', 'blue'), ('WEBP', 'green')]]
    before = list(warnings.filters), Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(sanitize_media_preview, inputs, list(MIMES.values())))
    for result in results:
        with unpack(result):
            pass
    assert (list(warnings.filters), Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES) == before


@pytest.mark.parametrize('kind', ['warning', 'exception'])
def test_decoder_exception_text_and_warning_metadata_are_sanitized(monkeypatch, capsys, kind):
    import warnings
    raw = encoded()
    def unsafe(*args, **kwargs):
        if kind == 'warning':
            warnings.warn(SECRET.decode())
        raise OSError(SECRET.decode())
    monkeypatch.setattr(Image, 'open', unsafe)
    with pytest.raises(MediaImageError) as failure:
        sanitize_media_preview(raw, 'image/png')
    assert failure.value.code == 'invalid_image'
    rendered = ''.join(traceback.format_exception(failure.value))
    assert SECRET.decode() not in rendered
    output = capsys.readouterr()
    assert SECRET.decode() not in output.out + output.err
