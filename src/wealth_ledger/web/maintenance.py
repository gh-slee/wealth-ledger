"""Cross-process maintenance barriers shared by HTTP, workers and portfolio CLI writes."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import time
import uuid

from ..locking import LockBusy, file_lock
from .storage import contained, private_write

_HELD = ContextVar("web_instance_activity", default=frozenset())


@contextmanager
def instance_activity(root):
    root = Path(root).resolve()
    if root in _HELD.get():
        yield
        return
    marker = contained(root, "admin/maintenance.json")
    if marker.exists():
        raise LockBusy("Instance maintenance is in progress")
    with file_lock(contained(root, "admin/maintenance.guard"), shared=True):
        if marker.exists():
            raise LockBusy("Instance maintenance is in progress")
        token = _HELD.set(_HELD.get() | {root})
        try:
            yield
        finally:
            _HELD.reset(token)


@contextmanager
def workspace_activity(project):
    project = Path(project).resolve()
    root = project.parent.parent
    if project.parent.name == "portfolios" and (root / "admin/instance.json").is_file():
        with instance_activity(root):
            yield
    else:
        yield


@contextmanager
def maintenance(root, *, timeout=30):
    """Block new entrants, drain existing readers/writers, then hold the barrier."""
    if not 0 <= timeout <= 300:
        raise ValueError("Maintenance timeout must be between 0 and 300 seconds")
    root = Path(root)
    marker = contained(root, "admin/maintenance.json")
    with file_lock(contained(root, "admin/maintenance-control.guard")):
        if marker.exists():
            raise ValueError("Interrupted maintenance needs the trusted maintenance-clear command")
        token = uuid.uuid4().hex
        private_write(marker, json.dumps({"token": token, "purpose": "backup"}).encode())
        try:
            deadline = time.monotonic() + timeout
            while True:
                guard = file_lock(contained(root, "admin/maintenance.guard"))
                try:
                    guard.__enter__()
                    break
                except LockBusy:
                    if time.monotonic() >= deadline:
                        raise LockBusy("Active work did not drain before the maintenance timeout")
                    time.sleep(0.05)
            try:
                yield
            finally:
                guard.__exit__(None, None, None)
        finally:
            if marker.exists() and json.loads(marker.read_text()).get("token") == token:
                marker.unlink()


def clear_maintenance(root):
    """Only an offline host may clear a crashed coordinator, never an active one."""
    root = Path(root)
    with file_lock(contained(root, "admin/maintenance-control.guard")), \
            file_lock(contained(root, "admin/maintenance.guard")):
        contained(root, "admin/maintenance.json").unlink(missing_ok=True)
