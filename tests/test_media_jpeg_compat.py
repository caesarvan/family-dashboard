"""Synthetic complete-primary JPEG compatibility; no real user photos."""
from io import BytesIO
import struct
import warnings

import pytest
from PIL import Image, ImageFile

import media_images as media
from test_media_images import SECRET, encoded, rejected, unpack


def segment(marker, payload):
    return bytes((255, marker)) + (len(payload)+2).to_bytes(2, 'big') + payload


def assert_clean(raw):
    result = media.sanitize_media_preview(raw, 'image/jpeg')
    assert SECRET not in result.data
    segments = list(media._jpeg_segments(result.data))
    assert segments[-1][0] == 0xD9 and segments[-1][2] == len(result.data)
    assert all(marker is None or not (0xE0 <= marker <= 0xEF or marker == 0xFE)
               for marker, _, _ in segments)
    with unpack(result):
        pass
    return result


@pytest.mark.parametrize('progressive', [False, True])
@pytest.mark.parametrize('tail', [b'\0', b' \r\n', SECRET, b'\0\0\0\x18ftypmp42' + SECRET])
def test_complete_primary_accepts_and_discards_padding_or_motionphoto_like_tail(progressive, tail):
    raw = encoded('JPEG', progressive=progressive)
    assert assert_clean(raw+tail) == assert_clean(raw)


def test_only_first_image_of_concatenated_jpeg_is_decoded():
    first = encoded('JPEG', color='red')
    second = encoded('JPEG', color='blue')
    assert assert_clean(first+second+SECRET) == assert_clean(first)


@pytest.mark.parametrize('hdr_metadata', [False, True])
def test_real_mpo_primary_and_ultrahdr_like_metadata_are_removed(hdr_metadata):
    with Image.new('RGB', (80, 40), 'red') as first, Image.new('RGB', (80, 40), 'blue') as second:
        out = BytesIO()
        first.save(out, format='MPO', save_all=True, append_images=[second])
    raw = out.getvalue()
    with Image.open(BytesIO(raw)) as image:
        assert image.format == 'MPO' and image.n_frames == 2
        image.seek(1)
        image.load()
    if hdr_metadata:
        # An MPF/XMP-like envelope, not a standards-complete Ultra HDR sample.
        raw = raw[:2] + segment(0xE1, b'http://ns.adobe.com/xap/1.0/\0hdrgm:Version="1.0"' + SECRET) + raw[2:]
    result = assert_clean(raw)
    assert b'MPF' not in result.data and b'hdrgm' not in result.data
    with unpack(result) as image:
        red, green, blue = image.getpixel((20, 20))
        assert red > 240 and green < 15 and blue < 15


@pytest.mark.parametrize('marker', [0xE1, 0xE2, 0xED, 0xFE])
def test_embedded_eoi_in_metadata_is_not_the_primary_end(marker):
    raw = encoded('JPEG')
    patched = raw[:2] + segment(marker, SECRET + b'\xff\xd9\xff\xd8') + raw[2:]
    assert assert_clean(patched) == assert_clean(raw)


@pytest.mark.parametrize('order', ['<', '>'])
@pytest.mark.parametrize('orientation,labels', [(1, 'rgby'), (2, 'gryb'), (3, 'ybgr'), (4, 'byrg'),
                                               (5, 'rbgy'), (6, 'bryg'), (7, 'ygbr'), (8, 'gyrb')])
def test_only_valid_inline_orientation_survives_corrupt_other_exif(order, orientation, labels):
    colors = {'r': (255, 0, 0), 'g': (0, 255, 0), 'b': (0, 0, 255), 'y': (255, 255, 0)}
    with Image.new('RGB', (80, 40)) as image:
        for region, label in [((0, 0, 40, 20), 'r'), ((40, 0, 80, 20), 'g'),
                              ((0, 20, 40, 40), 'b'), ((40, 20, 80, 40), 'y')]:
            image.paste(colors[label], region)
        out = BytesIO()
        image.save(out, format='JPEG', quality=95, subsampling=0)
    # Valid IFD0 structure; XResolution points outside payload. Ignore this
    # metadata without asking Pillow to parse it or suppressing pixel warnings.
    exif = b'Exif\0\0' + (b'II' if order == '<' else b'MM') + struct.pack(order+'HIH', 42, 8, 2)
    exif += struct.pack(order+'HHI', 274, 3, 1) + struct.pack(order+'H', orientation) + b'\0\0'
    exif += struct.pack(order+'HHII', 282, 5, 1, 0xFFFFFFF0) + b'\0' * 4 + SECRET
    raw = out.getvalue()
    with unpack(assert_clean(raw[:2] + segment(0xE1, exif) + raw[2:])) as image:
        assert image.size == ((40, 80) if orientation >= 5 else (80, 40))
        positions = [(5, 5), (image.width-6, 5), (5, image.height-6), (image.width-6, image.height-6)]
        for label, point in zip(labels, positions):
            assert max(abs(a-b) for a, b in zip(image.getpixel(point), colors[label])) < 15


@pytest.mark.parametrize('payload', [b'Exif\0\0bad', b'Exif\0\0II\x2a\0\xff\xff\xff\xff',
                                   b'Exif\0\0II\x2a\0\x08\0\0\0\xff\xff'])
def test_unreadable_exif_does_not_prevent_complete_pixel_decode(payload):
    raw = encoded('JPEG')
    assert assert_clean(raw[:2] + segment(0xE1, payload + SECRET) + raw[2:]) == assert_clean(raw)


@pytest.mark.parametrize('value,kind,count', [(0, 3, 1), (9, 3, 1), (6, 4, 1), (6, 3, 2)])
def test_invalid_orientation_is_discarded_without_following_pointers(value, kind, count):
    raw = encoded('JPEG')
    exif = b'Exif\0\0II\x2a\0\x08\0\0\0\x01\0'
    exif += struct.pack('<HHII', 274, kind, count, value) + b'\0'*4
    assert assert_clean(raw[:2] + segment(0xE1, exif) + raw[2:]) == assert_clean(raw)


@pytest.mark.parametrize('cut', [1, 2, 8, 30])
def test_truncated_primary_cannot_be_repaired_by_second_jpeg(cut):
    raw = encoded('JPEG')
    rejected(raw[:-cut] + encoded('JPEG', color='blue'), 'image/jpeg', 'invalid_image')


def test_malformed_primary_metadata_length_or_absent_scan_still_rejected():
    rejected(b'\xff\xd8' + b'\xff\xe1\xff\xff' + SECRET + encoded('JPEG'), 'image/jpeg', 'invalid_image')
    rejected(b'\xff\xd8\xff\xd9' + encoded('JPEG'), 'image/jpeg', 'invalid_image')


def test_whole_input_budget_includes_all_discarded_tail_bytes():
    raw = encoded('JPEG')
    assert_clean(raw + b'\0' * (media.MAX_INPUT_BYTES-len(raw)))
    rejected(raw + b'\0' * (media.MAX_INPUT_BYTES-len(raw)+1), 'image/jpeg', 'input_too_large')


def test_jpeg_pixel_limit_before_full_decode_is_unchanged():
    raw = bytearray(encoded('JPEG'))
    for marker, start, end in media._jpeg_segments(raw):
        if marker == 0xC0:
            raw[start+5:start+9] = struct.pack('>HH', 4000, 5001)
            break
    rejected(bytes(raw)+SECRET, 'image/jpeg', 'too_many_pixels')


def test_adobe_cmyk_color_interpretation_survives_metadata_removal():
    raw = encoded('JPEG', mode='CMYK', color=(0, 255, 255, 0))
    assert b'Adobe' in raw
    with unpack(assert_clean(raw+SECRET)) as image:
        red, green, blue = image.getpixel((20, 20))
        assert red > 240 and green < 15 and blue < 15


def test_unknown_pixel_warning_is_still_rejected_and_flags_are_unchanged(monkeypatch, capsys):
    raw = encoded('JPEG')
    previous = list(warnings.filters), Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES
    def warning(*args, **kwargs):
        warnings.warn(SECRET.decode())
    monkeypatch.setattr(Image, 'open', warning)
    rejected(raw+SECRET, 'image/jpeg', 'invalid_image')
    assert (list(warnings.filters), Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES) == previous
    assert SECRET.decode() not in capsys.readouterr().err
