"""Campus schedule policy: data/schedule.json -> PERMITTED | PROHIBITED |
APPROVAL_REQUIRED | UNKNOWN, evaluated in Asia/Kolkata on the backend clock
(or the demo operator override).

Expected file shape (Siddhant owns the data; fictional demo users only):
{
  "policy_version": "2026-11-14.1",
  "expires_utc": "2026-11-15T00:00:00Z",
  "users": {
    "akash": {"zone": "LAB-1",
              "windows": [{"days": ["MON","TUE","WED","THU","FRI"],
                           "start": "09:00", "end": "18:00", "effect": "allow"},
                          {"days": ["SAT"], "start": "10:00", "end": "13:00",
                           "effect": "approval"}]}
  }
}
`users` may also be a list of {"user_id": ..., ...}. policy_version and
expires_utc may be set per user (overrides top level).

Rules:
- Missing file, unparseable JSON, unknown user, missing/invalid/past
  expires_utc, or any malformed window -> UNKNOWN (never a pass).
- Kiosk zone set and different from the user's zone -> UNKNOWN (staff decides).
- Windows are [start, end) local time; end < start wraps past midnight
  (counted on the day it starts). Several matching windows: deny > approval > allow.
- A valid policy with no matching window -> PROHIBITED (default deny).
"""
import json
import logging
import threading
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

from . import config

log = logging.getLogger("api.schedule")

# Asia/Kolkata is UTC+05:30 with no DST; a fixed offset avoids needing tzdata
# on Windows (no new dependency).
IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
_DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_EFFECT = {"allow": "PERMITTED", "approval": "APPROVAL_REQUIRED", "deny": "PROHIBITED"}
_RANK = {"PROHIBITED": 3, "APPROVAL_REQUIRED": 2, "PERMITTED": 1}

# --- clock (real time, or demo operator override) ----------------------------

_clock_lock = threading.Lock()
_override_offset: timedelta | None = None  # override = real now + offset (keeps ticking)


def now() -> datetime:
    real = datetime.now(timezone.utc)
    with _clock_lock:
        off = _override_offset
    return (real + off if off is not None else real).astimezone(IST)


def set_override(iso_time: str | None) -> None:
    """None -> real time. Naive ISO times are read as Asia/Kolkata."""
    global _override_offset
    if iso_time is None:
        with _clock_lock:
            _override_offset = None
        return
    t = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=IST)
    with _clock_lock:
        _override_offset = t - datetime.now(timezone.utc)


def override_active() -> bool:
    with _clock_lock:
        return _override_offset is not None


# --- policy file ---------------------------------------------------------------

_cache: dict = {"key": None, "data": None}
_cache_lock = threading.Lock()


def _load() -> dict | None:
    """Parsed JSON, re-read when the file changes. None if missing/unparseable."""
    path = Path(config.SCHEDULE_PATH)
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except Exception as e:
        log.warning("schedule unparseable (%s) -> UNKNOWN", type(e).__name__)
        data = None
    with _cache_lock:
        _cache.update(key=key, data=data)
    return data


def _user_entry(data: dict, user_id: str) -> dict | None:
    users = data.get("users")
    if isinstance(users, dict):
        u = users.get(user_id)
    elif isinstance(users, list):
        u = next((x for x in users if isinstance(x, dict) and x.get("user_id") == user_id), None)
    else:
        u = None
    return u if isinstance(u, dict) else None


def policy_version() -> str | None:
    data = _load()
    return data.get("policy_version") if data else None


def _parse_hhmm(s) -> dtime:
    h, m = str(s).split(":")
    return dtime(int(h), int(m))


def _window_hits(w: dict, local: datetime) -> bool:
    days = w["days"]
    if not isinstance(days, list) or not days:
        raise ValueError("days")
    day_nums = {_DAYS[str(d).upper()[:3]] for d in days}
    start, end = _parse_hhmm(w["start"]), _parse_hhmm(w["end"])
    t, wd = local.time(), local.weekday()
    if start < end:
        return wd in day_nums and start <= t < end
    if start == end:
        raise ValueError("empty window")
    # Overnight: [start, 24:00) on a listed day, or [00:00, end) the day after.
    return (wd in day_nums and t >= start) or (((wd - 1) % 7) in day_nums and t < end)


def evaluate(user_id: str, zone: str | None, at: datetime | None = None) -> dict:
    """-> {"status": PERMITTED|PROHIBITED|APPROVAL_REQUIRED|UNKNOWN,
           "policy_version": str|None, "note": str}. Never raises."""
    def out(status, version, note):
        return {"status": status, "policy_version": version, "note": note}

    data = _load()
    if data is None:
        return out("UNKNOWN", None, "no_policy")
    top_version = data.get("policy_version")
    user = _user_entry(data, user_id)
    if user is None:
        return out("UNKNOWN", top_version, "user_not_in_policy")
    version = user.get("policy_version", top_version)
    local = (at or now()).astimezone(IST)
    try:
        exp = datetime.fromisoformat(
            str(user.get("expires_utc", data.get("expires_utc"))).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:
        return out("UNKNOWN", version, "bad_or_missing_expiry")
    if local >= exp:
        return out("UNKNOWN", version, "policy_expired")
    if zone and user.get("zone") != zone:
        return out("UNKNOWN", version, "zone_mismatch")
    windows = user.get("windows")
    if not isinstance(windows, list):
        return out("UNKNOWN", version, "bad_windows")
    best = None
    try:
        for w in windows:
            status = _EFFECT[str(w["effect"]).lower()]
            if _window_hits(w, local) and (best is None or _RANK[status] > _RANK[best]):
                best = status
    except Exception:
        return out("UNKNOWN", version, "bad_window")
    if best is None:
        return out("PROHIBITED", version, "outside_all_windows")
    return out(best, version, "window_match")
