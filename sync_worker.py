"""One dedicated worker. Unselected accounts make no cloud requests."""
import logging
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from app import create_app

class StopRequest:
    def __init__(self):
        self.requested = False

    def signal(self, _number, _frame):
        # Python runs this in the main thread. Do not acquire an Event/logging
        # lock here: a signal can interrupt that same thread while it owns it.
        self.requested = True

    def wait(self, seconds):
        until = time.monotonic() + seconds
        while not self.requested:
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))


def sync_household(platform, household, stop=None):
    if stop is not None and stop.requested:
        return
    try:
        application = platform.child(household)
    except Exception as error:
        logging.error('Household load error type=%s', type(error).__name__)
        return
    for phase in ('task_reminders', 'task_publish', 'calendar_publish', 'cloud_accounts', 'household_routines'):
        if stop is not None and stop.requested:
            return
        try:
            # A tick already entered is allowed to finish with its existing
            # timeouts and persistence rules. Never interrupt its transaction.
            application.extensions[phase].tick()
        except Exception as error:
            # A malformed queued publication must not stop ordinary source sync.
            # Never log tokens, response payloads, event contents, or exception text.
            logging.error('Sync worker phase=%s error type=%s', phase, type(error).__name__)


def main():
    stop, handlers = StopRequest(), {}
    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            handlers[number] = signal.signal(number, stop.signal)
        app = create_app()
        platform = app.extensions['household_platform']
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
        active, last_run = {}, {}
        # The executor context waits for already-running ticks on shutdown.
        # Queued workers also check stop before loading a household or phase.
        with ThreadPoolExecutor(max_workers=2) as pool:
            while not stop.requested:
                try:
                    for uid, future in list(active.items()):
                        if future.done():
                            future.result()
                            last_run[uid] = time.monotonic()
                            del active[uid]
                    if stop.requested:
                        break
                    households = sorted(platform.households(), key=lambda h: last_run.get(h['id'], 0))
                    for household in households:
                        if stop.requested or len(active) >= 2:
                            break
                        uid = household['id']
                        if uid not in active and time.monotonic() - last_run.get(uid, 0) >= 3:
                            active[uid] = pool.submit(sync_household, platform, household, stop)
                except Exception as error:
                    logging.error('Sync scheduler error type=%s', type(error).__name__)
                stop.wait(1)
    finally:
        # Keep graceful handlers installed while the executor drains; repeated
        # stop signals must not turn into KeyboardInterrupt mid-shutdown.
        for number, handler in handlers.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    main()
