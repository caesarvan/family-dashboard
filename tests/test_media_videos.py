"""Real FFmpeg fixtures and bounded process checks; no Google or fake MP4 success."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from PIL import Image
import pytest

import media_videos as video


@pytest.fixture(scope='module')
def tools():
    values = [os.environ.get('MEDIA_TEST_'+name.upper()) or shutil.which(name) for name in ('ffmpeg', 'ffprobe')]
    assert all(values), 'Install reviewed FFmpeg/ffprobe in the test environment; never skip real video tests.'
    return video.VideoTools(*values)


def run(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-1500:]
    return result.stdout


def fixture(path, tools, *, seconds=1.4, hevc=False, audio=True, rate=15):
    args = [tools.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-f', 'lavfi', '-i', f'testsrc2=size=160x90:rate={rate}:duration={seconds}']
    if audio:
        args += ['-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={seconds}']
    args += ['-c:v', 'libx265' if hevc else 'libx264', '-threads:v', '2']
    if hevc:
        args += ['-x265-params', 'pools=1:frame-threads=1:log-level=error', '-pix_fmt', 'yuv420p10le', '-tag:v', 'hvc1']
    else:
        args += ['-pix_fmt', 'yuv420p']
    args += ['-c:a', 'aac', '-metadata', 'title=SYNTHETIC-PRIVATE-SOURCE',
        '-metadata', 'comment=SYNTHETIC-PRIVATE-SOURCE', '-metadata', 'location=+31.2304+121.4737/', str(path)]
    run(args)
    return path.read_bytes()


@pytest.fixture(scope='module')
def source(tmp_path_factory, tools):
    root = tmp_path_factory.mktemp('source-video')
    return fixture(root/'source.mp4', tools)


def probe(path, tools):
    return json.loads(run([tools.ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def error(raw, tools, tmp_path, code, mime='video/mp4'):
    with pytest.raises(video.MediaVideoError) as caught:
        video.sanitize_media_video(raw, mime, tools=tools, temp_root=tmp_path)
    assert caught.value.code == code
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert list(tmp_path.iterdir()) == []
    return caught.value


def test_actual_h264_audio_complete_decode_poster_and_metadata(source, tools, tmp_path):
    result = video.sanitize_media_video(source, 'video/mp4', tools=tools, temp_root=tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert result.content_type == 'video/mp4' and result.has_audio
    assert result.duration_ms == pytest.approx(1400, abs=100)
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    assert result.poster.sha256 == hashlib.sha256(result.poster.data).hexdigest()
    assert 'SYNTHETIC-PRIVATE-SOURCE' not in repr(result) and b'SYNTHETIC-PRIVATE-SOURCE' not in result.data
    assert b'31.2304' not in result.data
    path = tmp_path/'checked.mp4'; path.write_bytes(result.data)
    observed = probe(path, tools)
    assert [s['codec_name'] for s in observed['streams']] == ['h264', 'aac']
    assert observed['streams'][0]['pix_fmt'] == 'yuv420p'
    # Decode the entire returned output with an independently invoked tool.
    run([tools.ffmpeg, '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'])
    with Image.open(BytesIO(result.poster.data)) as image:
        image.load(); assert image.size == (result.width, result.height) and image.info == {}


def test_actual_hevc_10bit_rotates_pixels_to_portrait(tools, tmp_path):
    raw = fixture(tmp_path/'hevc.mov', tools, hevc=True, audio=False)
    run([tools.ffmpeg, '-v', 'error', '-y', '-display_rotation', '90', '-i', str(tmp_path/'hevc.mov'),
         '-c', 'copy', str(tmp_path/'rotated.mov')])
    assert probe(tmp_path/'rotated.mov', tools)['streams'][0]['side_data_list'][0]['rotation'] == 90
    staged = tmp_path/'temporary'; staged.mkdir()
    result = video.sanitize_media_video((tmp_path/'rotated.mov').read_bytes(), 'video/quicktime', tools=tools, temp_root=staged)
    assert (result.width, result.height) == (90, 160) and not result.has_audio
    assert (result.poster.width, result.poster.height) == (90, 160)
    assert list(staged.iterdir()) == []
    output = tmp_path/'rotated-output.mp4'; output.write_bytes(result.data)
    assert not probe(output, tools)['streams'][0].get('side_data_list')


def test_actual_full_ten_minutes_is_not_a_short_preview(tools, tmp_path):
    raw = fixture(tmp_path/'ten-minutes.mp4', tools, seconds=600, audio=False, rate=1)
    staged = tmp_path/'temporary'; staged.mkdir()
    result = video.sanitize_media_video(raw, 'video/mp4', tools=tools, temp_root=staged)
    assert result.duration_ms == pytest.approx(600_000, abs=100)
    assert len(result.data) < video.MAX_OUTPUT_BYTES
    assert list(staged.iterdir()) == []


def test_actual_over_ten_minutes_rejected_without_truncation(tools, tmp_path):
    raw = fixture(tmp_path/'too-long.mp4', tools, seconds=601, audio=False, rate=1)
    staged = tmp_path/'temporary'; staged.mkdir()
    error(raw, tools, staged, 'too_long')


def test_hdr_is_explicitly_unsupported_without_unverified_tonemapping(tools, tmp_path):
    fixture(tmp_path/'hevc.mov', tools, hevc=True, audio=False)
    run([tools.ffmpeg, '-v', 'error', '-y', '-i', str(tmp_path/'hevc.mov'), '-c', 'copy',
         '-bsf:v', 'hevc_metadata=transfer_characteristics=18', str(tmp_path/'hdr.mov')])
    assert probe(tmp_path/'hdr.mov', tools)['streams'][0]['color_transfer'] == 'arib-std-b67'
    staged = tmp_path/'temporary'; staged.mkdir()
    error((tmp_path/'hdr.mov').read_bytes(), tools, staged, 'unsupported', 'video/quicktime')


@pytest.mark.parametrize('fault', ['truncated', 'fake-header', 'playlist', 'mime', 'empty', 'oversize'])
def test_rejects_actual_damage_wrong_input_and_limits(source, tools, tmp_path, fault):
    raw, code, mime = source, 'invalid', 'video/mp4'
    if fault == 'truncated': raw = source[:len(source)//2]
    elif fault == 'fake-header': raw = b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00not-a-video'
    elif fault == 'playlist': raw, code = b'#EXTM3U\nhttp://127.0.0.1/private\n', 'invalid'
    elif fault == 'mime': mime, code = 'video/webm', 'unsupported'
    elif fault == 'empty': raw, code = b'', 'invalid_input'
    elif fault == 'oversize': raw, code = b'x'*(video.MAX_INPUT_BYTES+1), 'too_large'
    error(raw, tools, tmp_path, code, mime)


def test_missing_tools_fail_explicitly_without_diagnostic_leak(source, tmp_path):
    caught = error(source, video.VideoTools(str(tmp_path/'missing'), str(tmp_path/'also-missing')), tmp_path, 'tools_unavailable')
    assert str(tmp_path) not in str(caught)


def _external_dref(raw, url):
    containers = {b'moov', b'trak', b'mdia', b'minf', b'dinf'}
    output, pos = [], 0
    while pos < len(raw):
        size = int.from_bytes(raw[pos:pos+4], 'big'); kind = raw[pos+4:pos+8]; body = raw[pos+8:pos+size]
        assert 8 <= size <= len(raw)-pos
        if kind in containers: body = _external_dref(body, url)
        if kind == b'dref':
            external = b'\x00\x00\x00\x00'+url.encode()+b'\x00'
            body = body[:4]+(1).to_bytes(4, 'big')+(len(external)+8).to_bytes(4, 'big')+b'url '+external
        output.append((len(body)+8).to_bytes(4, 'big')+kind+body); pos += size
    return b''.join(output)


def test_real_mov_external_track_cannot_fetch_loopback(source, tools, tmp_path):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path); self.send_response(200); self.end_headers(); self.wfile.write(source)
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        malicious = _external_dref(source, f'http://127.0.0.1:{server.server_port}/external.mp4')
        error(malicious, tools, tmp_path, 'invalid')
        assert seen == []
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_actual_subprocess_timeout_and_output_budget(tmp_path):
    # These are real child processes, not a mocked successful decoder.
    for command, deadline, expected, watched in [
        ([sys.executable, '-c', 'import time;time.sleep(10)'], time.monotonic()+.5, 'timeout', []),
        ([sys.executable, '-c', "from pathlib import Path;Path('bounded').write_bytes(b'x'*65536)"],
         time.monotonic()+20, 'too_large', [(tmp_path/'bounded', 1024)])]:
        with pytest.raises(video._Failure) as caught:
            video._run(command, tmp_path, deadline, watched=watched)
        assert caught.value.code == expected


def test_real_windows_job_memory_limit_or_posix_rlimit(tmp_path, monkeypatch):
    if os.name == 'nt':
        monkeypatch.setattr(video, 'MAX_MEMORY_BYTES', 48*1024**2)
        allocation = 96*1024**2
    else:
        allocation = video.MAX_MEMORY_BYTES+1
    with pytest.raises(video._Failure):
        video._run([sys.executable, '-c', f'x=bytearray({allocation})'], tmp_path, time.monotonic()+20)


def test_timeout_removes_private_temporary_files(source, tools, tmp_path, monkeypatch):
    monkeypatch.setattr(video, 'TOTAL_TIMEOUT_SECONDS', .01)
    error(source, tools, tmp_path, 'timeout')
