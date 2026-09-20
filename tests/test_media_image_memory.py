"""Real WebP decode compatibility and lifetime boundaries, not an RSS budget test."""
from contextlib import closing
from io import BytesIO
import random
import weakref

import pytest
from PIL import Image

import media_images as media


def webp(*, mode='RGBA', size=(127, 79), lossless=True):
    channels = len(mode)
    pixels = random.Random(34).randbytes(size[0] * size[1] * channels)
    with closing(Image.frombytes(mode, size, pixels)) as source, BytesIO() as output:
        source.save(output, format='WEBP', lossless=lossless)
        return output.getvalue()


@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
@pytest.mark.parametrize('lossless', [False, True])
def test_complete_mapped_pixels_match_public_pillow_decoder(mode, lossless):
    raw = webp(mode=mode, lossless=lossless)
    with closing(Image.open(BytesIO(raw))) as expected:
        expected.load()
        with closing(expected.convert('RGBA')) as rgba:
            expected_pixels = rgba.tobytes()
    with closing(media._load_image(raw, 'WEBP')) as actual:
        assert actual.size == (127, 79) and actual.readonly
        assert actual.mode == ('RGBX' if mode == 'RGB' else 'RGBA')
        with closing(actual.convert('RGBA')) as rgba:
            assert rgba.tobytes() == expected_pixels
            if mode == 'RGB':
                assert rgba.getextrema()[3] == (255, 255)


def test_verifier_and_decoder_are_released_before_postprocessing(monkeypatch):
    raw = webp()
    original_open, original_transpose = Image.open, media.ImageOps.exif_transpose
    plugins = []

    def opened(*args, **kwargs):
        assert all(ref() is None for ref in plugins)
        image = original_open(*args, **kwargs)
        plugins.append(weakref.ref(image))
        return image

    def transposed(image, **kwargs):
        assert len(plugins) % 2 == 0
        assert all(ref() is None for ref in plugins)
        return original_transpose(image, **kwargs)

    monkeypatch.setattr(Image, 'open', opened)
    monkeypatch.setattr(media.ImageOps, 'exif_transpose', transposed)
    outputs = [media.sanitize_media_preview(raw, 'image/webp') for _ in range(4)]
    assert len({item.sha256 for item in outputs}) == 1
    assert len(plugins) == 8 and all(ref() is None for ref in plugins)


@pytest.mark.parametrize('attribute', ['python', 'binary'])
def test_different_pillow_version_fails_closed(monkeypatch, attribute):
    raw = webp()
    target, key = (Image, '__version__') if attribute == 'python' else (Image.core, 'PILLOW_VERSION')
    monkeypatch.setattr(target, key, '12.4.0')
    with pytest.raises(media.MediaImageError) as failure:
        media.sanitize_media_preview(raw, 'image/webp')
    assert failure.value.code == 'unsafe_decoder_configuration'
    assert failure.value.__context__ is None


@pytest.mark.parametrize('fault,code', [('rawmode', 'unsafe_decoder_configuration'),
                                     ('short-frame', 'invalid_image'),
                                     ('not-bytes', 'invalid_image')])
def test_decoder_contract_mismatch_is_rejected_after_real_decode(monkeypatch, fault, code):
    raw = webp()
    original_open = Image.open

    class Altered:
        def __init__(self, decoder):
            self.decoder = decoder

        def get_info(self):
            info = self.decoder.get_info()
            return (*info[:4], 'L') if fault == 'rawmode' else info

        def get_next(self):
            pixels, timestamp = self.decoder.get_next()
            return (pixels[:-4] if fault == 'short-frame' else memoryview(pixels)), timestamp

    def opened(*args, **kwargs):
        source = original_open(*args, **kwargs)
        source._decoder = Altered(source._decoder)
        return source

    monkeypatch.setattr(Image, 'open', opened)
    with pytest.raises(media.MediaImageError) as failure:
        media.sanitize_media_preview(raw, 'image/webp')
    assert failure.value.code == code and failure.value.__context__ is None


def test_valid_webp_envelope_with_truncated_compressed_pixels_is_rejected():
    raw = webp()
    position = raw.index(b'VP8L')
    size = int.from_bytes(raw[position + 4:position + 8], 'little')
    payload = raw[position + 8:position + 8 + size // 2]
    body = raw[8:position] + b'VP8L' + len(payload).to_bytes(4, 'little') + payload
    body += b'\0' * (len(payload) % 2)
    damaged = b'RIFF' + len(body).to_bytes(4, 'little') + body
    media._container(damaged, 'WEBP')
    with closing(Image.open(BytesIO(damaged))) as readable_header:
        assert readable_header.size == (127, 79)
        with pytest.raises(OSError):
            readable_header.load()
    with pytest.raises(media.MediaImageError) as failure:
        media.sanitize_media_preview(damaged, 'image/webp')
    assert failure.value.code == 'invalid_image'


def test_maximum_rgba_webp_keeps_capacity_and_white_composite():
    with closing(Image.new('RGBA', (5000, 4000), (0, 0, 255, 128))) as source, BytesIO() as output:
        source.save(output, format='WEBP', lossless=True)
        raw = output.getvalue()
    assert len(raw) <= media.MAX_INPUT_BYTES
    result = media.sanitize_media_preview(raw, 'image/webp')
    assert (result.width, result.height) == (1600, 1280)
    with closing(Image.open(BytesIO(result.data))) as actual:
        actual.load()
        assert max(abs(a - b) for a, b in zip(actual.getpixel((800, 640)), (127, 127, 255))) < 4
        assert actual.info == {}
