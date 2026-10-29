"""Shared execution slots for worker threads and direct remediation runners."""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

MAX_PARALLEL_REMEDIATIONS = 5
DEFAULT_PARALLEL_REMEDIATIONS = 2


def concurrency_limit(settings):
    try:
        value = int(settings.get('parallel_remediations', DEFAULT_PARALLEL_REMEDIATIONS))
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL_REMEDIATIONS
    return value if 1 <= value <= MAX_PARALLEL_REMEDIATIONS else DEFAULT_PARALLEL_REMEDIATIONS


def validate_concurrency(value):
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError('Choose between 1 and 5 simultaneous remediation runs.') from error
    if not 1 <= parsed <= MAX_PARALLEL_REMEDIATIONS:
        raise ValueError('Choose between 1 and 5 simultaneous remediation runs.')
    return str(parsed)


def _acquire(path):
    handle = path.open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


@contextmanager
def remediation_slot(run_id, limit, root=None):
    limit = int(validate_concurrency(limit))
    directory = Path(root or os.getenv('HARNESS_ROOT', '/data/harness')) / 'execution-slots'
    directory.mkdir(parents=True, exist_ok=True)
    run = _acquire(directory / ('run-' + str(int(run_id)) + '.lock'))
    slot = None
    try:
        if run is not None:
            with (directory / 'allocation.lock').open('a') as allocation:
                fcntl.flock(allocation, fcntl.LOCK_EX)
                free = [handle for index in range(MAX_PARALLEL_REMEDIATIONS)
                        if (handle := _acquire(directory / ('slot-' + str(index) + '.lock'))) is not None]
                occupied = MAX_PARALLEL_REMEDIATIONS - len(free)
                if occupied < limit:
                    slot = free.pop(0)
                for handle in free:
                    handle.close()
        yield slot is not None
    finally:
        if slot is not None:
            slot.close()
        if run is not None:
            run.close()
