"""Huey SQLite notifications contain only validated IDs, using JSON instead of pickle."""
from contextlib import closing
import json
import uuid

from huey import SqliteHuey
from huey.registry import Message

from .storage import ID, contained

TASK_NAME = "wealth_ledger.web.queue.dispatch"


class NotificationSerializer:
    def serialize(self, message):
        if (message.name != TASK_NAME or len(message.args) != 1 or not ID.fullmatch(message.args[0])
                or message.kwargs or message.on_complete or message.on_error or message.eta is not None):
            raise ValueError("Only internal job notifications can be queued")
        return json.dumps({"v": 1, "notification": message.id, "job": message.args[0]}).encode()

    def deserialize(self, raw):
        if len(raw) > 512:
            raise ValueError("Notification is too large")
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {"v", "notification", "job"} or value["v"] != 1
                or not isinstance(value["job"], str) or not ID.fullmatch(value["job"])
                or not isinstance(value["notification"], str) or str(uuid.UUID(value["notification"])) != value["notification"]):
            raise ValueError("Invalid notification")
        return Message(value["notification"], TASK_NAME, None, 0, 0, None, (value["job"],), {},
                       None, None, None, None, None, None, 1)


def make_queue(store):
    queue = SqliteHuey("wealth-ledger-v1", filename=str(contained(store.root, "admin/queue.sqlite3")),
                      serializer=NotificationSerializer(), results=False, store_none=False,
                      immediate=False, fsync=True)
    for suffix in ("", "-wal", "-shm"):
        path = contained(store.root, "admin/queue.sqlite3" + suffix)
        if path.exists():
            path.chmod(0o600)
    @queue.task(retries=0)
    def dispatch(job_id):
        from .worker import execute_isolated
        execute_isolated(store.settings, job_id)
    return queue, dispatch


def notify_pending(store, dispatch, *, force=False):
    with closing(store.connect()) as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE status='queued' AND (? OR enqueued_at IS NULL OR enqueued_at<?) ORDER BY created_at,id LIMIT 20",
                            (force, store.clock() - 30)).fetchall()
    for row in rows:
        # Notification may duplicate or be lost across these transactions. Claim,
        # operation linkage and recovery, not queue delivery, prevent double import.
        dispatch(row["id"])
        with store.transaction() as conn:
            conn.execute("UPDATE jobs SET enqueued_at=? WHERE id=? AND status='queued'", (store.clock(), row["id"]))
