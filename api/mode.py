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
# Integrator fix 14 Nov: on the venue hotspot a single slow DNS/connect (>0.8 s) flipped
# the kiosk OFFLINE mid-demo (identity "offline" -> no ALLOW). Checks run in the
# background, so a longer timeout never delays a decision; and ONLINE -> OFFLINE needs
# FAILS_TO_OFFLINE consecutive failed checks (~5 s apart). OFFLINE -> ONLINE is immediate.
CONNECT_TIMEOUT_S = 1.5
HEALTH_BUDGET_S = 2.0   # whole check incl. DNS (getaddrinfo ignores socket timeouts)
FAILS_TO_OFFLINE = 2
STALE_OK_S = 30.0       # decision path reuses a cached result up to this old

_lock = threading.Lock()
_state = {"mode": None, "checked": 0.0, "fails": 0}
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
    if _forced():
        m = "OFFLINE"
        with _lock:
            _state.update(mode=m, checked=time.monotonic())
        return m
    ok = health_ok()
    with _lock:
        fails = 0 if ok else _state["fails"] + 1
        if ok:
            m = "ONLINE"
        elif _state["mode"] == "ONLINE" and fails < FAILS_TO_OFFLINE:
            m = "ONLINE"  # one blip on a slow network is not an outage
        else:
            m = "OFFLINE"
        _state.update(mode=m, checked=time.monotonic(), fails=fails)
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
