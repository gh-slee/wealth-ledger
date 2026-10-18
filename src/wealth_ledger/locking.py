"""Same-host advisory locks; process IDs never establish ownership."""
from contextlib import contextmanager
import os
from pathlib import Path


class LockBusy(ValueError):
    pass


@contextmanager
def file_lock(path, *, shared=False):
    """Lock a stable inode, shared by CLI and containers; never unlink this file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Lock paths cannot be symlinks")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+b") as handle:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK if shared else msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LockBusy("Another process holds the advisory lock") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockBusy("Another process holds the advisory lock") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
