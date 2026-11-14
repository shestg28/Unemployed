"""ONLINE / OFFLINE mode.

OFFLINE if FORCE_OFFLINE=1 (env, read live) or the operator flag is set, or if
the health check fails. Health check = TCP connect to the Rekognition and S3
endpoints for the configured region (parallel, short timeout). The result is
cached for 5 s; the background loop refreshes it so decisions rarely wait.
Network-level only: expired creds still show ONLINE, but then identity
returns UNKNOWN and sync stays pending, so nothing is ever auto-approved.
"""
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from pipeline import config as PC

CACHE_S = 5.0
CONNECT_TIMEOUT_S = 0.8
HEALTH_BUDGET_S = 1.0   # whole check incl. DNS (getaddrinfo ignores socket timeouts)
STALE_OK_S = 30.0       # decision path reuses a cached result up to this old

_lock = threading.Lock()
_state = {"mode": None, "checked": 0.0}
_operator_force_offline = False
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="health")
_refreshing = threading.Lock()


def _forced() -> bool:
    env = os.environ.get("FORCE_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}
    return env or _operator_force_offline


def set_operator_offline(flag: bool) -> None:
    global _operator_force_offline
    _operator_force_offline = bool(flag)


def _reachable(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


def health_ok() -> bool:
    """Both endpoints reachable within HEALTH_BUDGET_S total (a hung DNS lookup = down)."""
    region = PC.AWS_REGION
    hosts = [f"rekognition.{region}.amazonaws.com", f"s3.{region}.amazonaws.com"]
    futs = [_pool.submit(_reachable, h) for h in hosts]
    done, _ = wait(futs, timeout=HEALTH_BUDGET_S)
    return len(done) == len(futs) and all(f.result() for f in futs)


def refresh() -> str:
    m = "OFFLINE" if _forced() or not health_ok() else "ONLINE"
    with _lock:
        _state.update(mode=m, checked=time.monotonic())
    return m


def current() -> str:
    """Never blocks a decision on the network once a result exists: the background
    loop refreshes every 5 s; a result up to STALE_OK_S old is reused, and a stale
    one triggers a non-blocking refresh. Only the very first call checks inline."""
    if _forced():
        return "OFFLINE"
    with _lock:
        m, age = _state["mode"], time.monotonic() - _state["checked"]
    if m and age < CACHE_S:
        return m
    if m and age < STALE_OK_S:
        if _refreshing.acquire(blocking=False):
            def _bg():
                try:
                    refresh()
                finally:
                    _refreshing.release()
            _pool.submit(_bg)
        return m
    return refresh()  # no result yet, or too old to trust: check now (<= ~1 s)
