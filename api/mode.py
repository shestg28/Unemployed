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
from concurrent.futures import ThreadPoolExecutor

from pipeline import config as PC

CACHE_S = 5.0
CONNECT_TIMEOUT_S = 0.8

_lock = threading.Lock()
_state = {"mode": None, "checked": 0.0}
_operator_force_offline = False
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health")


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
    region = PC.AWS_REGION
    hosts = [f"rekognition.{region}.amazonaws.com", f"s3.{region}.amazonaws.com"]
    return all(_pool.map(_reachable, hosts))


def refresh() -> str:
    m = "OFFLINE" if _forced() or not health_ok() else "ONLINE"
    with _lock:
        _state.update(mode=m, checked=time.monotonic())
    return m


def current() -> str:
    if _forced():
        return "OFFLINE"
    with _lock:
        if _state["mode"] and time.monotonic() - _state["checked"] < CACHE_S:
            return _state["mode"]
    return refresh()
