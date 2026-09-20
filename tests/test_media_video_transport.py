"""Real byte streams + FFmpeg. Windows socketpair is not Linux AF_UNIX evidence."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time

import pytest

from media_videos import MediaVideoError, VideoTools, sanitize_media_video
import media_video_transport as wire
import media_video_service as service


@pytest.fixture(scope='module')
def tools():
    found = [shutil.which(name) for name in ('ffmpeg', 'ffprobe')]
    assert all(found), 'Actual FFmpeg required; no fake-success fixture or skipped codec.'
    return VideoTools(*found)


@pytest.fixture(scope='module')
def source(tmp_path_factory, tools):
    directory = tmp_path_factory.mktemp('source'); target = directory/'source.mp4'
    result = subprocess.run([tools.ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=15:duration=1.2', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=48000:duration=1.2', '-c:v', 'libx264', '-threads:v', '2',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(target)], capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr[-500:]
    return target.read_bytes()


@pytest.fixture(scope='module')
def actual_preview(tmp_path_factory, tools, source):
    directory = tmp_path_factory.mktemp('preview')
    value = sanitize_media_video(source, 'video/mp4', tools=tools, temp_root=directory)
    assert not list(directory.iterdir())
    return value


@contextmanager
def peer(action):
    client, server = socket.socketpair()
    errors = []
    def run():
        try:
            with server:
                action(server)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Expected when the rejecting client closes an invalid frame.
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run, daemon=True); thread.start()
    try:
        with client:
            yield client
    finally:
        thread.join(timeout=20)
        assert not thread.is_alive(), 'Original protocol handler did not finish'
        assert not errors, errors


def request(raw, **patch):
    return {'v': 1, 'mime': 'video/mp4', 'length': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), **patch}


def test_actual_stream_decode_and_complete_video_poster_return(tmp_path, tools, source):
    workspace = tmp_path/'private'; workspace.mkdir()
    def action(sock):
        service.process_connection(sock, tools=tools, temp_root=workspace, deadline=wire.deadline_after(20))
    with peer(action) as client:
        value = wire.exchange(client, source, 'video/mp4', wire.deadline_after(20))
    assert value.content_type == 'video/mp4' and value.has_audio
    assert value.duration_ms == pytest.approx(1200, abs=100)
    assert value.sha256 == hashlib.sha256(value.data).hexdigest()
    assert value.poster.sha256 == hashlib.sha256(value.poster.data).hexdigest()
    assert not list(workspace.iterdir())
    output = tmp_path/'returned.mp4'; output.write_bytes(value.data)
    result = subprocess.run([tools.ffmpeg, '-v', 'error', '-nostdin', '-xerror', '-i', str(output),
                             '-f', 'null', '-'], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr[-500:]


@pytest.mark.parametrize('patch', [{'url':'https://private.invalid/movie'}, {'path':'/private/file'},
    {'command':'ffmpeg'}, {'length':True}, {'length':wire.SOURCE_LIMIT+1}, {'mime':'text/plain'}, {'v':2}])
def test_request_rejects_capabilities_types_versions_and_limits_before_body(tmp_path, tools, patch):
    def action(sock):
        service.process_connection(sock, tools=tools, temp_root=tmp_path, deadline=wire.deadline_after(2))
    with peer(action) as client:
        wire.send_header(client, request(b'x', **patch), wire.deadline_after(2))
        value = wire.receive_header(client, wire.deadline_after(2))
        assert value['ok'] is False and value['code'] in wire.CODES
        assert set(value) == {'v', 'ok', 'code'}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mode', ['truncated', 'digest', 'trailing', 'invalid-video'])
def test_incomplete_or_untrusted_request_never_returns_success(tmp_path, tools, mode):
    def action(sock):
        service.process_connection(sock, tools=tools, temp_root=tmp_path, deadline=wire.deadline_after(2))
    with peer(action) as client:
        raw = b'invalid-private-source'
        wire.send_header(client, request(raw, length=len(raw)+1) if mode=='truncated' else
                         request(raw, sha256='0'*64) if mode=='digest' else request(raw), wire.deadline_after(2))
        client.sendall(raw + (b'extra frame' if mode=='trailing' else b''))
        if mode=='truncated': client.shutdown(socket.SHUT_WR)
        value = wire.receive_header(client, wire.deadline_after(2))
        assert value['ok'] is False and set(value)=={'v','ok','code'}
        assert 'private' not in json.dumps(value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mode', ['video-digest', 'poster-digest', 'truncated', 'trailing', 'oversize', 'bool-width', 'extra-key'])
def test_client_rejects_partial_or_bad_response_even_with_valid_original_media(actual_preview, mode):
    value = actual_preview
    def action(sock):
        wire.receive_request(sock, wire.deadline_after(2))
        header = wire.preview_header(value)
        if mode=='video-digest': header['sha256']='0'*64
        if mode=='poster-digest': header['posterSha256']='0'*64
        if mode=='oversize': header['videoLength']=wire.VIDEO_LIMIT+1
        if mode=='bool-width': header['width']=True
        if mode=='extra-key': header['downloadUrl']='https://private.invalid/source'
        wire.send_header(sock, header, wire.deadline_after(2))
        if mode in ('oversize','bool-width','extra-key'): return
        sock.sendall(value.data)
        sock.sendall(value.poster.data[:-1] if mode=='truncated' else value.poster.data)
        if mode=='trailing': sock.sendall(b'extra')
    with peer(action) as client, pytest.raises(wire.ProtocolError):
        wire.exchange(client, b'request', 'video/mp4', wire.deadline_after(2))


@pytest.mark.parametrize('raw', [b'{"v":1,"v":1}', b'{"v":1,"length":NaN}', b'[]', b'{}'])
def test_small_header_rejects_duplicate_nonfinite_and_wrong_shape(raw):
    with peer(lambda sock:sock.sendall(struct.pack('!I', len(raw))+raw)) as client, pytest.raises(wire.ProtocolError):
        wire.receive_header(client, wire.deadline_after(2))


def test_total_deadline_is_not_extended_by_slow_header_chunks():
    raw=b'{"v":1}'
    def action(sock):
        for byte in struct.pack('!I',len(raw))+raw:
            sock.sendall(bytes([byte])); time.sleep(.02)
    started=time.monotonic()
    with peer(action) as client, pytest.raises((TimeoutError,wire.ProtocolError)):
        wire.receive_header(client, wire.deadline_after(.06))
    assert time.monotonic()-started < .5


def test_public_error_is_fixed_and_platform_capability_is_explicit(tmp_path):
    with pytest.raises(MediaVideoError) as caught:
        wire.sanitize_remote_media_video(b'x','video/mp4',socket_path=tmp_path/'absent.sock',timeout=.1)
    assert caught.value.code=='tools_unavailable'
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    if not sys.platform.startswith('linux'):
        with pytest.raises(wire.ProtocolError) as unavailable:
            service.serve(tmp_path/'test.sock',tools=VideoTools('/missing/a','/missing/b'),temp_root=tmp_path)
        assert unavailable.value.code=='tools_unavailable'  # Fail closed, not a skipped Linux success.


def test_declared_deadline_rejects_infinite_zero_negative_and_boolean():
    for value in (True,0,-1,float('inf'),float('nan'),901,'900'):
        with pytest.raises(wire.ProtocolError): wire.deadline_after(value)
