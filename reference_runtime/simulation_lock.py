"""Serialize runtime signal-actor replacement with the bridge's sensor/tick loop.

The bridge remains the only clock owner. This reduces concurrent scene mutation
during PhysX ray queries; it is not an engine-level memory-safety fix.
"""
import contextlib
import fcntl
import threading

_mutex = threading.RLock()
_local = threading.local()
_path = '/results/tmp/scene_tick.lock'

@contextlib.contextmanager
def scene_transaction():
    with _mutex:
        depth = getattr(_local, 'depth', 0)
        if depth == 0:
            _local.file = open(_path, 'a')
            fcntl.flock(_local.file, fcntl.LOCK_EX)
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth -= 1
            if _local.depth == 0:
                fcntl.flock(_local.file, fcntl.LOCK_UN)
                _local.file.close()
