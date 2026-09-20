"""Linux decoder-only Unix service. No Flask, database, account or cloud access."""
import argparse
from contextlib import contextmanager, nullcontext
import os
from pathlib import Path
import queue
import select
import signal
import socket
import stat
import sys
import threading
import time

from media_videos import MediaVideoError, VideoTools, sanitize_media_video
from media_video_transport import (CODES, ProtocolError, deadline_after, private_socket_path,
                                   receive_request, remaining, send_header, send_preview)


class _Cancelled(BaseException):
    pass


class _Stopping(BaseException):
    pass


def process_connection(connection, *, tools, temp_root, deadline, decode_guard=nullcontext):
    """One complete byte protocol; production serve adds Linux cancellation guard."""
    started_reply = False
    code = None
    try:
        raw, mime = receive_request(connection, deadline)
        if select.select([connection], [], [], 0)[0]:
            raise ProtocolError()  # No extra frames or client write-half-close.
        with decode_guard():
            remaining(deadline)
            value = sanitize_media_video(raw, mime, tools=tools, temp_root=temp_root)
            remaining(deadline)
        if select.select([connection], [], [], 0)[0]:
            raise ProtocolError()
        del raw
        started_reply = True
        send_preview(connection, value, deadline)
    except (MediaVideoError, ProtocolError) as error:
        code = error.code if error.code in CODES else 'invalid'
    except (TimeoutError, socket.timeout):
        code = 'timeout'
    except Exception:
        code = 'invalid'
    if code and not started_reply:
        try:
            send_header(connection, {'v': 1, 'ok': False, 'code': code}, deadline)
        except (Exception, _Cancelled):
            pass
    # The caller closes the connection. Partial responses are never retried or
    # followed by a second frame; the client requires complete lengths and EOF.


@contextmanager
def _request_guard(connection, deadline):
    """Main-thread signals interrupt codec finally, which kills its process tree."""
    if not sys.platform.startswith('linux') or threading.current_thread() is not threading.main_thread():
        raise ProtocolError('tools_unavailable')
    done = threading.Event()
    decoding = threading.Event()
    cancelling = False

    def cancel(_number, _frame):
        nonlocal cancelling
        if done.is_set() or cancelling:
            return
        cancelling = True
        raise _Cancelled()

    def disconnected():
        while not done.wait(.05):
            if not decoding.is_set():
                continue
            try:
                readable, _, _ = select.select([connection], [], [], 0)
                if not readable:
                    continue
                # There is no pipelining or half-close in v1. EOF or trailing
                # bytes during decode cancels this request, not the next one.
                connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            except BlockingIOError:
                continue
            except OSError:
                pass
            if not done.is_set() and decoding.is_set():
                os.kill(os.getpid(), signal.SIGUSR1)
                return

    @contextmanager
    def during_decode():
        decoding.set()
        try:
            yield
        finally:
            decoding.clear()

    old_alarm = signal.signal(signal.SIGALRM, cancel)
    old_cancel = signal.signal(signal.SIGUSR1, cancel)
    monitor = threading.Thread(target=disconnected, name='decoder-peer-watch', daemon=True)
    try:
        signal.setitimer(signal.ITIMER_REAL, remaining(deadline))
        monitor.start()
        yield during_decode
    finally:
        done.set(); signal.setitimer(signal.ITIMER_REAL, 0)
        if monitor.ident is not None:
            monitor.join(timeout=1)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGUSR1, old_cancel)


def serve(socket_path, *, tools, temp_root, timeout=900):
    """One in-flight decode; excess accepted peers receive fixed timeout/busy."""
    if not sys.platform.startswith('linux') or threading.current_thread() is not threading.main_thread():
        raise ProtocolError('tools_unavailable')
    deadline_after(timeout)
    path = private_socket_path(socket_path, existing=False)
    temporary = Path(temp_root)
    if not temporary.is_absolute() or temporary.is_symlink():
        raise ProtocolError('tools_unavailable')
    for parent in temporary.parents:
        if parent.is_symlink():
            raise ProtocolError('tools_unavailable')
    info = temporary.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProtocolError('tools_unavailable')
    # Validate executable configuration once; paths never come from IPC.
    tools.paths()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    owned = None
    stopped = threading.Event()
    slot = threading.Lock()
    incoming = queue.Queue(maxsize=1)

    def accept():
        while not stopped.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not slot.acquire(blocking=False):
                with connection:
                    try:
                        send_header(connection, {'v': 1, 'ok': False, 'code': 'timeout'}, deadline_after(1))
                    except Exception:
                        pass
                continue
            incoming.put_nowait((connection, deadline_after(timeout)))

    def stop(_number, _frame):
        stopped.set()
        raise _Stopping()

    old_term = signal.signal(signal.SIGTERM, stop)
    old_int = signal.signal(signal.SIGINT, stop)
    accepter = None
    try:
        listener.bind(str(path))
        owned = path.lstat()
        path.chmod(0o600)
        listener.listen(1); listener.settimeout(.2)
        accepter = threading.Thread(target=accept, name='decoder-accept', daemon=True)
        accepter.start()
        while not stopped.is_set():
            try:
                connection, deadline = incoming.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                with connection, _request_guard(connection, deadline) as decode_guard:
                    process_connection(connection, tools=tools, temp_root=temporary,
                                       deadline=deadline, decode_guard=decode_guard)
            except (_Cancelled, ProtocolError):
                pass
            finally:
                slot.release()
    except _Stopping:
        pass
    finally:
        stopped.set(); listener.close()
        if accepter:
            accepter.join(timeout=2)
        while not incoming.empty():
            pending, _ = incoming.get_nowait(); pending.close()
        # Never delete a replacement, regular file, symlink, or stale socket.
        if owned is not None:
            try:
                current = path.lstat()
                if stat.S_ISSOCK(current.st_mode) and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--temp-root', required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--ffprobe', required=True)
    args = parser.parse_args()
    try:
        serve(args.socket, tools=VideoTools(args.ffmpeg, args.ffprobe), temp_root=args.temp_root)
    except Exception:
        # No source bytes, path, decoder diagnostics or exception chain in logs.
        print('Video decoder service unavailable.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
