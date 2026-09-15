"""Real child-process signals and SQLite commits; no cloud or production data.

POSIX cases send SIGTERM/SIGINT from the parent. The portable case asks a
controller inside the child to raise SIGINT through Python's signal machinery;
it never calls the worker's handler directly. Linux container/PID 1 acceptance
is separate from these process tests.
"""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SIGNALS = [
    pytest.param('external', 'SIGTERM', marks=pytest.mark.skipif(os.name == 'nt', reason='Windows cannot deliver POSIX SIGTERM')),
    pytest.param('external', 'SIGINT', marks=pytest.mark.skipif(os.name == 'nt', reason='Windows os.kill(SIGINT) is not POSIX delivery')),
    pytest.param('self', 'SIGINT'),
]


def child(root, mode, delivery, name, blocked_phase='task_publish', failure=False):
    """Run the unmodified worker main with bounded synthetic phase adapters."""
    root = Path(root)
    stop_controller = threading.Event()
    output_lock = threading.Lock()

    def record(event, **values):
        with output_lock, (root / 'events.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps({'event': event, **values}) + '\n')

    def gate():
        deadline = time.monotonic() + 12
        while not (root / 'release').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('Synthetic gate timeout')
            time.sleep(0.01)

    def controller():
        while not stop_controller.wait(0.01):
            if (root / 'signal').exists():
                signal.raise_signal(getattr(signal, name))
                (root / 'signal-raised').touch()
                return

    class Phase:
        def __init__(self, household, phase):
            self.household, self.phase = household, phase

        def tick(self):
            record('phase_start', household=self.household, phase=self.phase)
            if self.phase != blocked_phase:
                record('phase_done', household=self.household, phase=self.phase)
                return
            # An actual open transaction exists when the parent sends the signal.
            with closing(sqlite3.connect(root / (self.household + '.sqlite3'))) as con:
                con.execute('CREATE TABLE IF NOT EXISTS writes(value TEXT NOT NULL)')
                con.execute('BEGIN IMMEDIATE')
                con.execute("INSERT INTO writes VALUES('synthetic committed result')")
                (root / ('inflight-' + self.household)).touch()
                gate()
                if failure:
                    con.rollback()
                    record('phase_rollback', household=self.household, phase=self.phase)
                    raise RuntimeError('Synthetic provider failure')
                con.commit()
                record('phase_commit', household=self.household, phase=self.phase)

    class Platform:
        def households(self):
            (root / 'ready').touch()
            record('schedule')
            if mode == 'idle':
                return []
            if mode == 'listing':
                gate()
            return [{'id': item} for item in ('alpha', 'beta', 'gamma')]

        def child(self, household):
            record('household_load', household=household['id'])
            return SimpleNamespace(extensions={phase: Phase(household['id'], phase)
                for phase in ('task_publish', 'calendar_publish', 'cloud_accounts', 'household_routines')})

    def create_app():
        if mode == 'startup':
            (root / 'ready').touch()
            gate()
        return SimpleNamespace(extensions={'household_platform': Platform()})

    # Fail closed if a test accidentally reaches a real network adapter.
    def deny_network(*_args, **_kwargs):
        raise AssertionError('Network access is forbidden in worker signal tests')
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    fake_app = ModuleType('app')
    fake_app.create_app = create_app
    sys.modules['app'] = fake_app
    sys.path.insert(0, str(ROOT))
    import sync_worker
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    thread = threading.Thread(target=controller, daemon=True)
    if delivery == 'self':
        thread.start()
    try:
        sync_worker.main()
        assert all(signal.getsignal(sig) == handler for sig, handler in before.items())
        record('exited')
    finally:
        stop_controller.set()
        if thread.is_alive():
            thread.join(1)


@contextmanager
def worker(tmp_path, mode, delivery, name, blocked_phase='task_publish', failure=False):
    process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker-child',
        str(tmp_path), mode, delivery, name, blocked_phase, '1' if failure else '0'],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        yield process
    finally:
        if process.poll() is None:
            # Cleanup applies only to this test-owned child, after assertions.
            process.kill()
        process.communicate(timeout=5)


def wait_marker(process, path, timeout=8):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert process.poll() is None, 'Worker exited before synthetic readiness'
        assert time.monotonic() < deadline, 'Worker did not reach synthetic readiness'
        time.sleep(0.01)


def send_stop(process, root, delivery, name):
    if delivery == 'external':
        process.send_signal(getattr(signal, name))
    else:
        (root / 'signal').touch()
        wait_marker(process, root / 'signal-raised')


def events(root):
    path = root / 'events.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def successful_exit(process):
    output, error = process.communicate(timeout=3)
    assert process.returncode == 0, (process.returncode, output, error)


@pytest.mark.parametrize('delivery,name', SIGNALS)
def test_idle_worker_exits_promptly_on_real_signal(tmp_path, delivery, name):
    with worker(tmp_path, 'idle', delivery, name) as process:
        wait_marker(process, tmp_path / 'ready')
        started = time.monotonic()
        send_stop(process, tmp_path, delivery, name)
        successful_exit(process)
        assert time.monotonic() - started < 2
    assert all(row['event'] != 'household_load' for row in events(tmp_path))
    assert events(tmp_path)[-1]['event'] == 'exited'


@pytest.mark.parametrize('delivery,name', SIGNALS)
@pytest.mark.parametrize('blocked_phase,failure', [('task_publish', False), ('calendar_publish', False), ('task_publish', True), ('cloud_accounts', False), ('household_routines', False), ('household_routines', True)])
def test_inflight_work_finishes_without_new_phase_or_household(tmp_path, delivery, name, blocked_phase, failure):
    with worker(tmp_path, 'inflight', delivery, name, blocked_phase, failure) as process:
        for household in ('alpha', 'beta'):
            wait_marker(process, tmp_path / ('inflight-' + household))
        send_stop(process, tmp_path, delivery, name)
        time.sleep(0.25)
        assert process.poll() is None, 'Stopping discarded an in-flight transaction'
        before = events(tmp_path)
        (tmp_path / 'release').touch()
        successful_exit(process)
    after = events(tmp_path)
    assert [row for row in after if row['event'] == 'household_load'] == [row for row in before if row['event'] == 'household_load']
    assert {row['household'] for row in after if row['event'] == 'household_load'} == {'alpha', 'beta'}
    assert [row for row in after if row['event'] == 'phase_start'] == [row for row in before if row['event'] == 'phase_start']
    order = ('task_publish', 'calendar_publish', 'cloud_accounts', 'household_routines')
    assert all(order.index(row['phase']) <= order.index(blocked_phase) for row in after if row['event'] == 'phase_start')
    for household in ('alpha', 'beta'):
        with closing(sqlite3.connect(tmp_path / (household + '.sqlite3'))) as con:
            assert con.execute('SELECT count(*) FROM writes').fetchone()[0] == (0 if failure else 1)
    assert sum(row['event'] == ('phase_rollback' if failure else 'phase_commit') for row in after) == 2
    assert after[-1]['event'] == 'exited'


@pytest.mark.parametrize('delivery,name', SIGNALS)
@pytest.mark.parametrize('mode', ['startup', 'listing'])
def test_stop_during_startup_or_listing_does_not_schedule_returned_households(tmp_path, delivery, name, mode):
    with worker(tmp_path, mode, delivery, name) as process:
        wait_marker(process, tmp_path / 'ready')
        send_stop(process, tmp_path, delivery, name)
        time.sleep(0.15)
        assert process.poll() is None
        (tmp_path / 'release').touch()
        successful_exit(process)
    rows = events(tmp_path)
    assert not any(row['event'] in ('household_load', 'phase_start') for row in rows)
    assert rows[-1]['event'] == 'exited'


if __name__ == '__main__' and len(sys.argv) == 8 and sys.argv[1] == '--worker-child':
    child(*sys.argv[2:7], failure=sys.argv[7] == '1')
