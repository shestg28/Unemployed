"""Decision-event outbox: SQLite at logs/outbox.db, survives restarts.

One row per decision EVENT (automatic first pass, challenge, staff decision,
/verify are separate events). Rows hold only the minimal fields below:
no images, embeddings, similarity scores, raw user_id or credentials.
Rows are never edited after insert except the `synced` flag.
"""
import hashlib
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

COLUMNS = ("event_id", "attempt_id", "timestamp_utc", "pseudonymous_person_id", "kiosk_id",
           "decision", "reason_code", "policy_version", "verification_method", "operator_id",
           "synced")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  pseudonymous_person_id TEXT NOT NULL,
  kiosk_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  policy_version TEXT,
  verification_method TEXT NOT NULL,
  operator_id TEXT,
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_unsynced ON events(synced, timestamp_utc);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Outbox:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA)
        self._salt = os.environ.get("PSEUDONYM_SALT") or self._stored_salt()

    def _stored_salt(self) -> str:
        """Per-kiosk random salt, created once and kept in the DB (not in git)."""
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
            if row:
                return row["value"]
            salt = secrets.token_hex(16)
            self._db.execute("INSERT INTO meta(key, value) VALUES('salt', ?)", (salt,))
            return salt

    def pseudonym(self, user_id: str) -> str:
        return hashlib.sha256((user_id + self._salt).encode("utf-8")).hexdigest()

    def add(self, *, attempt_id: str, user_id: str, decision: str, reason_code: str,
            policy_version: str | None, verification_method: str,
            operator_id: str | None = None) -> str:
        event_id = str(uuid.uuid4())
        row = (event_id, attempt_id,
               datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
               self.pseudonym(user_id), config.KIOSK_ID, decision, reason_code,
               policy_version, verification_method, operator_id, 0)
        with self._lock:
            self._db.execute(f"INSERT INTO events({','.join(COLUMNS)}) "
                             f"VALUES({','.join('?' * len(COLUMNS))})", row)
        return event_id

    def unsynced(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM events WHERE synced=0 ORDER BY timestamp_utc LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_synced(self, event_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE events SET synced=1 WHERE event_id=?", (event_id,))

    def get(self, event_id: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return dict(r) if r else None

    def counts(self) -> tuple[int, int]:
        """-> (pending_sync, synced)"""
        with self._lock:
            r = self._db.execute(
                "SELECT COALESCE(SUM(synced=0),0) AS p, COALESCE(SUM(synced=1),0) AS s "
                "FROM events").fetchone()
        return int(r["p"]), int(r["s"])

    def close(self) -> None:
        with self._lock:
            self._db.close()


_outbox: Outbox | None = None
_outbox_lock = threading.Lock()


def get() -> Outbox:
    """Process-wide outbox for config.OUTBOX_PATH (reopened if the path changes)."""
    global _outbox
    with _outbox_lock:
        if _outbox is None or _outbox.path != str(config.OUTBOX_PATH):
            if _outbox is not None:
                _outbox.close()
            _outbox = Outbox(config.OUTBOX_PATH)
        return _outbox


def event_payload(row: dict) -> dict:
    """What leaves the kiosk: the row minus the local `synced` flag."""
    return {k: row[k] for k in COLUMNS if k != "synced"}
