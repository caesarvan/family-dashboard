"""Bounded byte-only v1 decoder IPC. No URL, account, path or command payloads."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
import time

from media_images import Preview
from media_videos import MediaVideoError, VideoPreview

VERSION = 1
HEADER_LIMIT = 2048
SOURCE_LIMIT = 100 * 1024**2
VIDEO_LIMIT = 64 * 1024**2
POSTER_LIMIT = 2 * 1024**2
TIMEOUT_LIMIT = 900
CODES = frozenset(('invalid_input', 'too_large', 'too_long', 'unsupported', 'invalid', 'timeout', 'tools_unavailable'))
MIMES = frozenset(('video/mp4', 'video/quicktime'))


class ProtocolError(Exception):
    def __init__(self, code='invalid'):
        self.code = code
        super().__init__('Decoder protocol rejected')


def deadline_after(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= TIMEOUT_LIMIT:
        raise ProtocolError('invalid_input')
    return time.monotonic() + timeout


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise ProtocolError('timeout')
    return value


def _send(connection, value, deadline):
    view = memoryview(value)
    for start in range(0, len(view), 65536):
        connection.settimeout(remaining(deadline))
        connection.sendall(view[start:start+65536])


def _receive(connection, length, deadline):
    data = bytearray(length)
    view = memoryview(data)
    offset = 0
    while offset < length:
        connection.settimeout(remaining(deadline))
        got = connection.recv_into(view[offset:offset+65536])
        if not got:
            raise ProtocolError()
        offset += got
    return bytes(data)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError()
        result[key] = value
    return result


def send_header(connection, value, deadline):
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode('ascii')
    if not 0 < len(raw) <= HEADER_LIMIT:
        raise ProtocolError()
    _send(connection, struct.pack('!I', len(raw)) + raw, deadline)


def receive_header(connection, deadline):
    length = struct.unpack('!I', _receive(connection, 4, deadline))[0]
    if not 0 < length <= HEADER_LIMIT:
        raise ProtocolError()
    try:
        value = json.loads(_receive(connection, length, deadline).decode('ascii'),
                           object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError()))
    except (ValueError, UnicodeError):
        raise ProtocolError() from None
    if type(value) is not dict or type(value.get('v')) is not int or value['v'] != VERSION:
        raise ProtocolError()
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError()
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ProtocolError()
    return value


def check_source(raw, mime_type):
    if type(raw) is not bytes or not raw or type(mime_type) is not str or mime_type not in MIMES:
        raise ProtocolError('invalid_input')
    if len(raw) > SOURCE_LIMIT:
        raise ProtocolError('too_large')


def receive_request(connection, deadline):
    value = receive_header(connection, deadline)
    if set(value) != {'v', 'mime', 'length', 'sha256'} or type(value['mime']) is not str or value['mime'] not in MIMES:
        raise ProtocolError('invalid_input')
    length = _integer(value['length'], 1, SOURCE_LIMIT)
    expected = _digest(value['sha256'])
    raw = _receive(connection, length, deadline)
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
        raise ProtocolError()
    return raw, value['mime']


def preview_header(value):
    return {'v': VERSION, 'ok': True, 'videoLength': len(value.data), 'sha256': value.sha256,
            'width': value.width, 'height': value.height, 'durationMs': value.duration_ms, 'hasAudio': value.has_audio,
            'posterLength': len(value.poster.data), 'posterSha256': value.poster.sha256,
            'posterWidth': value.poster.width, 'posterHeight': value.poster.height}


def _check_preview_header(value):
    if (set(value) != {'v', 'ok', 'videoLength', 'sha256', 'width', 'height', 'durationMs', 'hasAudio',
                      'posterLength', 'posterSha256', 'posterWidth', 'posterHeight'} or value['ok'] is not True
            or type(value['hasAudio']) is not bool):
        raise ProtocolError()
    _integer(value['videoLength'], 1, VIDEO_LIMIT)
    _integer(value['posterLength'], 1, POSTER_LIMIT)
    for key in ('width', 'height'):
        _integer(value[key], 2, 1280)
    for key in ('posterWidth', 'posterHeight'):
        _integer(value[key], 1, 1600)
    _integer(value['durationMs'], 1, 600250)
    _digest(value['sha256']); _digest(value['posterSha256'])


def send_preview(connection, value, deadline):
    header = preview_header(value)
    _check_preview_header(header)
    if value.content_type != 'video/mp4' or value.poster.content_type != 'image/jpeg':
        raise ProtocolError()
    send_header(connection, header, deadline)
    _send(connection, value.data, deadline)
    _send(connection, value.poster.data, deadline)


def exchange(connection, raw, mime_type, deadline):
    """Connected-stream protocol; production callers use the Unix-path API below."""
    check_source(raw, mime_type)
    send_header(connection, {'v': VERSION, 'mime': mime_type, 'length': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest()}, deadline)
    _send(connection, raw, deadline)
    value = receive_header(connection, deadline)
    if value.get('ok') is False:
        if set(value) != {'v', 'ok', 'code'} or type(value['code']) is not str or value['code'] not in CODES:
            raise ProtocolError()
        raise ProtocolError(value['code'])
    _check_preview_header(value)
    video = _receive(connection, value['videoLength'], deadline)
    poster = _receive(connection, value['posterLength'], deadline)
    connection.settimeout(remaining(deadline))
    if connection.recv(1):  # Success is accepted only after an exact, closed response.
        raise ProtocolError()
    if (not hmac.compare_digest(hashlib.sha256(video).hexdigest(), value['sha256'])
            or not hmac.compare_digest(hashlib.sha256(poster).hexdigest(), value['posterSha256'])
            or video[4:8] != b'ftyp' or not poster.startswith(b'\xff\xd8') or not poster.endswith(b'\xff\xd9')):
        raise ProtocolError()
    return VideoPreview(video, 'video/mp4', value['width'], value['height'], value['durationMs'], value['hasAudio'],
                        value['sha256'], Preview(poster, 'image/jpeg', value['posterWidth'], value['posterHeight'], value['posterSha256']))


def private_socket_path(value, *, existing):
    """Linux private directory and owned socket. Never unlink a stale path here."""
    if not sys.platform.startswith('linux') or not hasattr(socket, 'AF_UNIX'):
        raise ProtocolError('tools_unavailable')
    path = Path(value)
    if not path.is_absolute() or len(os.fsencode(path)) > 103 or '..' in path.parts:
        raise ProtocolError('tools_unavailable')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ProtocolError('tools_unavailable')
    directory = path.parent.stat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid() or stat.S_IMODE(directory.st_mode) != 0o700:
        raise ProtocolError('tools_unavailable')
    if existing:
        current = path.lstat()
        if not stat.S_ISSOCK(current.st_mode) or current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o600:
            raise ProtocolError('tools_unavailable')
    elif path.exists():
        raise ProtocolError('tools_unavailable')
    return path


def sanitize_remote_media_video(raw, mime_type, *, socket_path, timeout=900):
    """Return a complete verified VideoPreview, or a fixed public codec error."""
    code = 'invalid'
    try:
        deadline = deadline_after(timeout)
        check_source(raw, mime_type)
        path = private_socket_path(socket_path, existing=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining(deadline)); connection.connect(str(path))
            return exchange(connection, raw, mime_type, deadline)
    except ProtocolError as error:
        code = error.code
    except (TimeoutError, socket.timeout):
        code = 'timeout'
    except OSError:
        code = 'tools_unavailable'
    except (TypeError, ValueError):
        code = 'invalid_input'
    raise MediaVideoError(code) from None
