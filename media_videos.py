"""Bounded local MP4/MOV normalization. No account, network, storage or UI integration.

Trusted FFmpeg executables must be supplied by the deployment. This is a decoder
boundary, not an OS security sandbox or a guarantee against every codec defect.
"""
from dataclasses import dataclass, field
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import time

from media_images import Preview, sanitize_media_preview

MAX_INPUT_BYTES = 100 * 1024**2
MAX_OUTPUT_BYTES = 64 * 1024**2
MAX_DURATION_MS = 600_000
MAX_PIXELS = 20_000_000
MAX_EDGE = 1280
MAX_MEMORY_BYTES = 1536 * 1024**2
MAX_CPU_SECONDS = 600
TOTAL_TIMEOUT_SECONDS = 900
PROBE_TIMEOUT_SECONDS = 30
LOG_LIMIT = 256 * 1024
_LOCK = Lock()
_MESSAGES = {
    'invalid_input': '请提供视频字节和有效的媒体类型。',
    'too_large': '视频超过输入或展示副本的大小上限。',
    'too_long': '视频最长支持十分钟，未保存截断片段。',
    'unsupported': '此视频的格式、音轨或色彩模式暂不支持。',
    'invalid': '视频不完整或无法正常解码。',
    'timeout': '视频处理超时，请稍后重试。',
    'tools_unavailable': '视频处理工具或必要的资源限制不可用。',
}


class MediaVideoError(Exception):
    def __init__(self, code):
        self.code = code
        self.message = _MESSAGES[code]
        super().__init__(self.message)


class _Failure(Exception):
    def __init__(self, code):
        self.code = code


@dataclass(frozen=True, slots=True)
class VideoTools:
    """Server-owned executable paths; never accept these from a request."""
    ffmpeg: str
    ffprobe: str

    def paths(self):
        paths = []
        for value in (self.ffmpeg, self.ffprobe):
            if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
                raise _Failure('tools_unavailable')
            try:
                path = Path(value).resolve(strict=True)
            except OSError:
                raise _Failure('tools_unavailable') from None
            if not path.is_file() or (os.name == 'nt' and path.suffix.lower() != '.exe'):
                raise _Failure('tools_unavailable')
            paths.append(str(path))
        return paths


@dataclass(frozen=True, slots=True)
class VideoPreview:
    data: bytes = field(repr=False)
    content_type: str
    width: int
    height: int
    duration_ms: int
    has_audio: bool
    sha256: str
    poster: Preview


# The trusted wrapper waits for its parent to attach the Windows Job Object
# BEFORE it starts the decoder. POSIX applies rlimits before exec, avoiding
# preexec_fn inside a potentially multithreaded worker.
_CHILD = '''import os,sys
if sys.stdin.buffer.read(1)!=b'1': sys.exit(126)
if os.name=='posix':
 import resource
 resource.setrlimit(resource.RLIMIT_AS, (1610612736,1610612736))
 resource.setrlimit(resource.RLIMIT_CPU, (600,600))
 resource.setrlimit(resource.RLIMIT_FSIZE, (68157440,68157440))
 resource.setrlimit(resource.RLIMIT_NOFILE, (64,64))
if os.name=='nt':
 import subprocess
 sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL))
os.execv(sys.argv[1],sys.argv[1:])
'''


class _WindowsJob:
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('processTime', c.c_longlong), ('jobTime', c.c_longlong),
                ('flags', w.DWORD), ('minWorking', c.c_size_t), ('maxWorking', c.c_size_t),
                ('active', w.DWORD), ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(n, c.c_ulonglong) for n in ('readOps', 'writeOps', 'otherOps', 'readBytes', 'writeBytes', 'otherBytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('processMemory', c.c_size_t),
                ('jobMemory', c.c_size_t), ('peakProcess', c.c_size_t), ('peakJob', c.c_size_t)]
        self.kernel = k = c.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]; k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]; k.SetInformationJobObject.restype = w.BOOL
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]; k.AssignProcessToJobObject.restype = w.BOOL
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]; k.TerminateJobObject.restype = w.BOOL
        k.CloseHandle.argtypes = [w.HANDLE]; k.CloseHandle.restype = w.BOOL
        k.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        k.QueryInformationJobObject.restype = w.BOOL
        self.handle = k.CreateJobObjectW(None, None)
        info = Extended()
        # Job CPU, active-process count, total committed memory, kill on close.
        info.basic.flags = 0x4 | 0x8 | 0x200 | 0x2000
        info.basic.jobTime = MAX_CPU_SECONDS * 10_000_000
        info.basic.active = 4  # Python launcher/wrapper plus the real executable.
        info.jobMemory = MAX_MEMORY_BYTES
        if (not self.handle or not k.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info))
                or not k.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle)))):
            self.close()
            raise _Failure('tools_unavailable')

    def close(self):
        if self.handle:
            import ctypes as c
            self.kernel.TerminateJobObject(self.handle, 1)
            # Termination is asynchronous; wait for descendant file handles to
            # close before TemporaryDirectory removes potentially private data.
            deadline = time.monotonic() + 5
            accounting = c.create_string_buffer(48)
            while time.monotonic() < deadline:
                if (not self.kernel.QueryInformationJobObject(self.handle, 1, accounting, 48, None)
                        or int.from_bytes(accounting.raw[40:44], 'little') == 0):
                    break
                time.sleep(.01)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _run(args, directory, deadline, *, watched=(), probe=False):
    """No shell, bounded on-disk diagnostics, minimal environment, whole-tree kill."""
    limit = min(deadline, time.monotonic() + (PROBE_TIMEOUT_SECONDS if probe else TOTAL_TIMEOUT_SECONDS))
    out, err = directory / 'stdout', directory / 'stderr'
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR') if k in os.environ}
    env.update(PATH=os.defpath, TMP=str(directory), TEMP=str(directory), TMPDIR=str(directory), AV_LOG_FORCE_NOCOLOR='1')
    process = job = None
    try:
        with out.open('wb') as stdout, err.open('wb') as stderr:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-c', _CHILD, *args],
                stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, cwd=directory, env=env,
                start_new_session=os.name == 'posix',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if os.name == 'nt':
                job = _WindowsJob(process)
            elif os.name != 'posix':
                raise _Failure('tools_unavailable')
            process.stdin.write(b'1'); process.stdin.close()
            while True:
                if time.monotonic() >= limit:
                    raise _Failure('timeout')
                if out.stat().st_size > LOG_LIMIT or err.stat().st_size > LOG_LIMIT:
                    raise _Failure('invalid')
                if any(path.exists() and path.stat().st_size > size for path, size in watched):
                    raise _Failure('too_large')
                if process.poll() is not None:
                    break
                time.sleep(.02)
            if process.returncode != 0:
                # Only fixed diagnostics are inspected, never surfaced or logged.
                with err.open('rb') as stream:
                    raw = stream.read(LOG_LIMIT)
                missing = (b'Unknown encoder', b'No such filter', b'Option not found', b'Unrecognized option')
                raise _Failure('tools_unavailable' if any(text in raw for text in missing) else 'invalid')
        if any(path.exists() and path.stat().st_size > size for path, size in watched):
            raise _Failure('too_large')
        with out.open('rb') as stream:
            result = stream.read(LOG_LIMIT+1)
        if len(result) > LOG_LIMIT:
            raise _Failure('invalid')
        return result
    except (FileNotFoundError, PermissionError):
        raise _Failure('tools_unavailable') from None
    finally:
        if job:
            job.close()
        elif process and os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()


def _container(raw):
    """Bound top-level ISO-BMFF boxes; never let a playlist choose a demuxer."""
    position, boxes, count = 0, set(), 0
    while position < len(raw):
        if len(raw) - position < 8 or count >= 10000:
            raise _Failure('invalid')
        size = int.from_bytes(raw[position:position+4], 'big'); kind = raw[position+4:position+8]
        header = 8
        if size == 1:
            if len(raw) - position < 16:
                raise _Failure('invalid')
            size = int.from_bytes(raw[position+8:position+16], 'big'); header = 16
        elif size == 0:
            size = len(raw) - position
        if size < header or position + size > len(raw):
            raise _Failure('invalid')
        if not position and kind != b'ftyp':
            raise _Failure('unsupported')
        if kind == b'moov':
            _references(raw, position+header, position+size)
        boxes.add(kind); count += 1; position += size
    if not {b'ftyp', b'moov', b'mdat'} <= boxes:
        raise _Failure('invalid')


def _references(raw, start, end, depth=0):
    """Reject external track declarations even when FFmpeg ignores a dref."""
    if depth > 8:
        raise _Failure('invalid')
    pos, count = start, 0
    while pos < end:
        if end-pos < 8 or count >= 10000:
            raise _Failure('invalid')
        size = int.from_bytes(raw[pos:pos+4], 'big'); kind = raw[pos+4:pos+8]
        if size < 8 or pos+size > end:
            raise _Failure('invalid')
        if kind in (b'trak', b'mdia', b'minf', b'dinf'):
            _references(raw, pos+8, pos+size, depth+1)
        elif kind == b'dref':
            if size < 16:
                raise _Failure('invalid')
            entries = int.from_bytes(raw[pos+12:pos+16], 'big'); cursor = pos+16
            if not 1 <= entries <= 8:
                raise _Failure('invalid')
            for _ in range(entries):
                # A self-contained url has exactly version/flags=1 and no URL.
                if raw[cursor:cursor+12] != b'\x00\x00\x00\x0curl \x00\x00\x00\x01':
                    raise _Failure('invalid')
                cursor += 12
            if cursor != pos+size:
                raise _Failure('invalid')
        count += 1; pos += size


@contextmanager
def _temporary(root):
    value = TemporaryDirectory(prefix='media-video-', dir=root)
    try:
        yield value.name
    finally:
        # Windows may briefly retain closed executable/antivirus handles after
        # Job termination. Bounded retry removes plaintext, never ignore errors.
        deadline = time.monotonic()+5
        while True:
            try:
                value.cleanup()
                break
            except PermissionError:
                if os.name != 'nt' or time.monotonic() >= deadline:
                    raise
                time.sleep(.05)


def _input(path):
    # mov only; no network protocols, external relative tracks or absolute drefs.
    return ['-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
            '-use_absolute_path', '0', '-i', str(path)]


def _probe(path, executable, directory, deadline):
    raw = _run([executable, '-v', 'error', '-max_alloc', '268435456', *_input(path),
        '-show_entries', 'format=duration:format_tags:stream=index,codec_type,codec_name,width,height,duration,start_time,channels,sample_rate,pix_fmt,color_transfer:stream_tags:stream_disposition:stream_side_data',
        '-of', 'json'], directory, deadline, probe=True)
    try:
        value = json.loads(raw)
        streams = value['streams']
        if not isinstance(streams, list) or not 1 <= len(streams) <= 8:
            raise ValueError()
        videos = [s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
        audios = [s for s in streams if s.get('codec_type') == 'audio']
        if len(videos) != 1 or len(audios) > 1:
            raise _Failure('unsupported')
        video = videos[0]
        width, height = video['width'], video['height']
        if type(width) is not int or type(height) is not int or min(width, height) < 2 or width * height > MAX_PIXELS:
            raise _Failure('unsupported')
        if video['codec_name'] not in ('h264', 'hevc') or video.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
            raise _Failure('unsupported')
        duration = Decimal(str(value['format']['duration']))
        if not duration.is_finite() or duration <= 0:
            raise ValueError()
        # Include selected audio/video durations instead of trusting only mvhd.
        durations = [duration]
        for stream in [video, *audios]:
            if 'duration' in stream:
                item = Decimal(str(stream['duration']))
                if not item.is_finite() or item <= 0:
                    raise ValueError()
                durations.append(item)
        return value, video, audios, int(max(durations) * 1000 + Decimal('.5'))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise _Failure('invalid') from None


def _sanitize(raw, mime_type, tools, temp_root):
    if type(raw) is not bytes or not raw or type(mime_type) is not str:
        raise _Failure('invalid_input')
    if len(raw) > MAX_INPUT_BYTES:
        raise _Failure('too_large')
    if mime_type not in ('video/mp4', 'video/quicktime'):
        raise _Failure('unsupported')
    if not isinstance(tools, VideoTools):
        raise _Failure('tools_unavailable')
    ffmpeg, ffprobe = tools.paths()
    _container(raw)
    with _temporary(temp_root) as temporary:
        directory = Path(temporary); source = directory / 'input.mp4'; target = directory / 'display.mp4'; poster = directory / 'poster.jpg'
        source.write_bytes(raw)
        deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        _, video, audio, duration = _probe(source, ffprobe, directory, deadline)
        if duration > MAX_DURATION_MS:
            raise _Failure('too_long')
        # 85% of the output budget, including AAC, gives a complete ten-minute
        # clip room for muxing overhead/VBV bursts. Never use -t/-fs/-shortest.
        bitrate = min(2_000_000, int(MAX_OUTPUT_BYTES * 8 * .85 / (duration / 1000)) - (96_000 if audio else 0))
        common = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-max_alloc', '268435456',
            '-xerror', '-err_detect', 'explode', '-threads', '2', '-filter_threads', '1']
        args = [*common, *_input(source), '-map', '0:'+str(video['index'])]
        if audio:
            args += ['-map', '0:'+str(audio[0]['index'])]
        args += ['-map_metadata', '-1', '-map_metadata:s', '-1', '-map_chapters', '-1',
            '-vf', "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
            '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-b:v', str(bitrate), '-maxrate', str(bitrate), '-bufsize', str(bitrate*2), '-threads:v', '2',
            '-bsf:v', 'filter_units=remove_types=6', '-metadata:s:v:0', 'rotate=0',
            '-c:a', 'aac', '-b:a', '96000', '-ar', '48000', '-ac', '2',
            '-fflags', '+bitexact', '-flags:v', '+bitexact', '-flags:a', '+bitexact',
            '-movflags', '+faststart', '-f', 'mp4', str(target)]
        _run(args, directory, deadline, watched=[(target, MAX_OUTPUT_BYTES)])
        _, result, tracks, actual = _probe(target, ffprobe, directory, deadline)
        if (result['codec_name'] != 'h264' or result.get('pix_fmt') != 'yuv420p'
                or max(result['width'], result['height']) > MAX_EDGE
                or bool(tracks) != bool(audio) or any(s.get('codec_name') != 'aac' for s in tracks)
                or abs(actual-duration) > 250):
            raise _Failure('invalid')
        # Independently decode every output packet. No source stream is copied.
        _run([*common, *_input(target), '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], directory, deadline)
        _run([*common, *_input(target), '-map', '0:v:0', '-frames:v', '1', '-an', '-q:v', '2',
            '-threads:v', '1', '-f', 'image2', str(poster)], directory, deadline, watched=[(poster, 8*1024**2)])
        data = target.read_bytes()
        if not data or len(data) > MAX_OUTPUT_BYTES:
            raise _Failure('too_large')
        image = sanitize_media_preview(poster.read_bytes(), 'image/jpeg')
        return VideoPreview(data, 'video/mp4', result['width'], result['height'], actual, bool(tracks), sha256(data).hexdigest(), image)


def sanitize_media_video(raw: bytes, mime_type: str, *, tools: VideoTools, temp_root=None) -> VideoPreview:
    """Normalize a complete selected video. Caller owns authorization and quota.

    temp_root and tools are server configuration. No filenames/URLs from media
    metadata are used. Fixed errors have no decoder text or exception chain.
    """
    code = None
    acquired = _LOCK.acquire(timeout=1)
    if not acquired:
        raise MediaVideoError('timeout')
    try:
        try:
            return _sanitize(raw, mime_type, tools, temp_root)
        except _Failure as error:
            code = error.code
        except Exception:
            code = 'invalid'
    finally:
        _LOCK.release()
    raise MediaVideoError(code)
