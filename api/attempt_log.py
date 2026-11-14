"""One JSONL line per decision -> logs/attempts.jsonl. Never images or bytes."""
import json
import logging
import threading
from pathlib import Path

from . import config
from .store import now_ms

log = logging.getLogger("api.attempts")
_lock = threading.Lock()


def write_decision(record: dict) -> None:
    line = {"ts_ms": now_ms(), **record}
    try:
        path = Path(config.ATTEMPT_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(line, default=str, separators=(",", ":"))
        with _lock, path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        log.exception("could not write attempt log")


def late_result(attempt_id: str, kind: str, result: dict) -> None:
    """Late results go to the process log, not attempts.jsonl (decisions only)."""
    log.warning("LATE %s for attempt %s ignored: %s", kind, attempt_id,
                {k: v for k, v in result.items() if k != "frame"})
