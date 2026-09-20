"""Actual Linux libwebp contract comparison; no pytest, network or real media."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import random
import sys
import time
import types


BASELINE_SHA = '89e1153805604e1b2dba0ae41778570b4247bffa492dd25327c768e24b3049ef'
RUNTIME_SHA = '3a4dc65a11dd996f128c9a8559806a6c8067fb573cf790dcf9c6bacd0c21cbf1'


class CheckFailure(Exception):
    pass


def need(value, message):
    if not value:
        raise CheckFailure(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path, expected, name):
    need(path.is_file() and not path.is_symlink(), 'module must be a regular non-symlink file')
    raw = path.read_bytes()
    need(len(raw) <= 128 * 1024 and sha(raw) == expected, 'module hash mismatch')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def check(args, report):
    need(sys.platform == 'linux', 'actual Linux required; no platform emulation')
    need(args.runtime_sha256 == RUNTIME_SHA and args.baseline_sha256 == BASELINE_SHA,
         'checker is fixed to native 1531aed and original public-Pillow baseline')
    baseline = load(args.baseline, args.baseline_sha256, '_image_contract_baseline')
    runtime = load(args.runtime, args.runtime_sha256, '_image_contract_runtime')
    from PIL import Image, ImageFile, WebPImagePlugin

    need(Image.__version__ == '12.3.0' and Image.core.PILLOW_VERSION == '12.3.0', 'Pillow version mismatch')
    need(not ImageFile.LOAD_TRUNCATED_IMAGES, 'truncated loading must remain disabled')
    library = runtime._webp_native_library()  # Real CDLL/symbol/version check.
    need(library.WebPGetDecoderVersion() == 0x010600, 'libwebp version mismatch')
    report['toolchain'] = {'python': sys.version, 'pillow': Image.__version__,
                           'core': Image.core.PILLOW_VERSION, 'libwebp': 0x010600,
                           'extension': WebPImagePlugin._webp.__file__,
                           'extensionSha256': sha(Path(WebPImagePlugin._webp.__file__).read_bytes())}

    def encoded(mode, lossless, orientation):
        with closing(Image.new(mode, (1901, 971))) as source, BytesIO() as target:
            for bounds, color in [((0, 0, 950, 485), (255, 0, 0, 0)),
                                  ((950, 0, 1901, 485), (0, 255, 0, 64)),
                                  ((0, 485, 950, 971), (0, 0, 255, 128)),
                                  ((950, 485, 1901, 971), (255, 255, 0, 255))]:
                source.paste(color[:len(mode)], bounds)
            exif = Image.Exif()
            exif[274], exif[270] = orientation, 'synthetic contract metadata'
            source.save(target, format='WEBP', lossless=lossless, exif=exif)
            return target.getvalue()

    for mode in ('RGB', 'RGBA'):
        for lossless in (False, True):
            for orientation in range(1, 9):
                raw = encoded(mode, lossless, orientation)
                previous = baseline.sanitize_media_preview(raw, 'image/webp')
                current = runtime.sanitize_media_preview(raw, 'image/webp')
                row = {'mode': mode, 'lossless': lossless, 'orientation': orientation,
                       'inputSha256': sha(raw), 'inputBytes': len(raw),
                       'baselineSha256': sha(previous.data), 'runtimeSha256': sha(current.data),
                       'baselineSize': [previous.width, previous.height],
                       'runtimeSize': [current.width, current.height],
                       'byteIdentical': previous.data == current.data}
                report['matrix'].append(row)
                need(row['byteIdentical'] and row['baselineSize'] == row['runtimeSize'], 'matrix output differs')
                need(max(current.width, current.height) == 1600, 'matrix did not resize')
                need((current.height > current.width) == (orientation >= 5), 'orientation mismatch')
                with closing(Image.open(BytesIO(current.data))) as decoded:
                    decoded.load()
                    need(decoded.info == {} and not decoded.getexif(), 'output metadata remains')

    def rejected(name, raw, expected):
        observed = None
        try:
            runtime.sanitize_media_preview(raw, 'image/webp')
        except runtime.MediaImageError as error:
            observed = error.code
        row = {'name': name, 'inputSha256': sha(raw), 'observed': observed, 'expected': expected}
        report['checks'].append(row)
        need(observed == expected, 'negative check failed: ' + name)

    raw = encoded('RGBA', True, 1)
    rejected('truncated-container', raw[:-7], 'invalid_image')
    rejected('trailing-data', raw + b'synthetic-trailer', 'invalid_image')
    with closing(Image.new('RGB', (32, 32), 'red')) as first, closing(Image.new('RGB', (32, 32), 'blue')) as second, BytesIO() as output:
        first.save(output, format='WEBP', save_all=True, append_images=[second], duration=100, loop=0)
        rejected('animated', output.getvalue(), 'multiple_frames')

    # Valid RIFF/chunk sizes and readable dimensions, but incomplete pixels.
    with closing(Image.frombytes('RGBA', (127, 79), random.Random(34).randbytes(127 * 79 * 4))) as source, BytesIO() as output:
        source.save(output, format='WEBP', lossless=True)
        noisy = output.getvalue()
    pos = noisy.index(b'VP8L')
    size = int.from_bytes(noisy[pos + 4:pos + 8], 'little')
    payload = noisy[pos + 8:pos + 8 + size // 2]
    body = noisy[8:pos] + b'VP8L' + len(payload).to_bytes(4, 'little') + payload
    body += b'\0' * (len(payload) % 2)
    damaged = b'RIFF' + len(body).to_bytes(4, 'little') + body
    runtime._container(damaged, 'WEBP')
    with closing(Image.open(BytesIO(damaged))) as header:
        need(header.size == (127, 79), 'damaged fixture header invalid')
    rejected('incomplete-pixels-valid-envelope', damaged, 'invalid_image')

    with closing(Image.new('RGBA', (127, 79), (0, 0, 255, 128))) as source, BytesIO() as output:
        source.save(output, format='WEBP', lossless=True)
        transparent = output.getvalue()
    result = runtime.sanitize_media_preview(transparent, 'image/webp')
    with closing(Image.open(BytesIO(result.data))) as white:
        white.load()
        pixel = white.getpixel((63, 39))
    need(max(abs(a - b) for a, b in zip(pixel, (127, 127, 255))) < 4, 'white composite mismatch')
    report['checks'].append({'name': 'transparent-white-background', 'pixel': pixel, 'passed': True})
    # Actual mapped full-frame pixels, including opaque alpha, independently
    # compared with the public Pillow decoder before resize/JPEG can hide bugs.
    for mode in ('RGB', 'RGBA'):
        raw = encoded(mode, True, 1)
        with closing(Image.open(BytesIO(raw))) as public, closing(runtime._load_image(raw, 'WEBP')) as native:
            public.load()
            with closing(public.convert('RGBA')) as expected, closing(native.convert('RGBA')) as actual:
                need(actual.tobytes() == expected.tobytes(), 'full pixels differ: ' + mode)
                if mode == 'RGB':
                    need(actual.getextrema()[3] == (255, 255), 'opaque alpha mismatch')
        report['checks'].append({'name': 'complete-pixels-' + mode, 'passed': True})
    need(len(report['matrix']) == 32 and len(report['checks']) == 7, 'incomplete case count')
    need(not ImageFile.LOAD_TRUNCATED_IMAGES, 'decoder configuration changed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--runtime-sha256', required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    need(args.output.resolve() not in (args.runtime.resolve(), args.baseline.resolve()), 'output overlaps input')
    # Reserve the result before any decode. Never overwrite an earlier run.
    with args.output.open('x', encoding='utf-8') as destination:
        started = time.monotonic()
        report = {'kind': 'media-image-native-linux-contract', 'passed': False, 'pid': os.getpid(),
                  'startedAt': datetime.now(timezone.utc).isoformat(), 'matrix': [], 'checks': [],
                  'inputs': {'runtime': str(args.runtime), 'runtimeSha256': args.runtime_sha256,
                             'baseline': str(args.baseline), 'baselineSha256': args.baseline_sha256},
                  'boundary': 'Actual Linux C symbols and small synthetic media; not 20 MP/384 MiB resource proof'}
        try:
            check(args, report)
            report['passed'] = True
        except Exception as error:
            report['error'] = {'type': type(error).__name__, 'message': str(error)}
        finally:
            report['seconds'] = time.monotonic() - started
            try:
                report['inputBytesUnchanged'] = all(path.is_file() and sha(path.read_bytes()) == expected for path, expected in
                                                   ((args.runtime, args.runtime_sha256), (args.baseline, args.baseline_sha256)))
            except OSError as error:
                report['inputBytesUnchanged'] = False
                report['readbackError'] = type(error).__name__
            if not report['inputBytesUnchanged']:
                report['passed'] = False
            json.dump(report, destination, indent=2)
            destination.write('\n')
    print(json.dumps({'passed': report['passed'], 'matrix': len(report['matrix']), 'checks': len(report['checks'])}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
