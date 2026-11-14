"""Bridge from the API to the pipeline functions named in CONTRACT v2.

If /pipeline exports quality / select_frames / passive_liveness /
challenge_check, they are used. Otherwise a STUB runs that returns
UNAVAILABLE (and `stub: True`), so it can never lead to ALLOW.
Any exception or malformed output from a real function is also UNAVAILABLE.
"""
import logging

import pipeline

log = logging.getLogger("api.signals")

PASSIVE_STATUSES = {"LIVE", "SPOOF", "UNCERTAIN", "UNAVAILABLE"}
CHALLENGE_STATUSES = {"PASS", "FAIL", "UNCERTAIN", "UNAVAILABLE"}


def _impl(name: str):
    fn = getattr(pipeline, name, None)
    return fn if callable(fn) else None


def stubs_in_use() -> list[str]:
    return [n for n in ("quality", "select_frames", "passive_liveness", "challenge_check")
            if _impl(n) is None]


# --- STUBS (labelled; never a pass) -------------------------------------------

def _stub_quality(frames):
    return {"per_frame": [], "ok": None, "fail_reason": None,
            "continuity_ok": None, "status": "UNAVAILABLE", "stub": True}


def _stub_select_frames(frames, ts):
    return list(range(len(frames)))  # STUB: no selection, all frames


def _stub_passive(frames):
    return {"status": "UNAVAILABLE", "score": None, "per_frame": [], "stub": True}


def _stub_challenge(frames, ts, prompt_ts, actions):
    return {"status": "UNAVAILABLE", "per_action": {}, "stub": True,
            "passive": {"status": "UNAVAILABLE", "score": None, "stub": True}}


# --- Safe wrappers --------------------------------------------------------------

def quality(frames: list[bytes]) -> dict:
    fn = _impl("quality")
    if fn is None:
        log.warning("STUB quality() in use -> UNAVAILABLE")
        return _stub_quality(frames)
    try:
        out = fn(frames)
        if not isinstance(out, dict) or not isinstance(out.get("ok"), bool):
            raise ValueError("quality() must return a dict with bool 'ok'")
        return out
    except Exception as e:
        log.exception("quality() failed")
        return {**_stub_quality(frames), "stub": False, "error": type(e).__name__}


def select_frames(frames: list[bytes], ts: list[int]) -> list[int]:
    fn = _impl("select_frames")
    if fn is None:
        return _stub_select_frames(frames, ts)
    try:
        idx = [int(i) for i in fn(frames, ts) if 0 <= int(i) < len(frames)]
        return idx or list(range(len(frames)))
    except Exception:
        log.exception("select_frames() failed; using all frames")
        return list(range(len(frames)))


def passive_liveness(frames: list[bytes]) -> dict:
    fn = _impl("passive_liveness")
    if fn is None:
        log.warning("STUB passive_liveness() in use -> UNAVAILABLE")
        return _stub_passive(frames)
    try:
        out = fn(frames)
        if not isinstance(out, dict) or out.get("status") not in PASSIVE_STATUSES:
            raise ValueError("passive_liveness() returned an unknown status")
        return out
    except Exception as e:
        log.exception("passive_liveness() failed")
        return {**_stub_passive(frames), "stub": False, "error": type(e).__name__}


def challenge_check(frames, ts, prompt_ts, actions) -> dict:
    fn = _impl("challenge_check")
    if fn is None:
        log.warning("STUB challenge_check() in use -> UNAVAILABLE")
        return _stub_challenge(frames, ts, prompt_ts, actions)
    try:
        out = fn(frames, ts, prompt_ts, actions)
        if not isinstance(out, dict) or out.get("status") not in CHALLENGE_STATUSES:
            raise ValueError("challenge_check() returned an unknown status")
        return out
    except Exception as e:
        log.exception("challenge_check() failed")
        return {**_stub_challenge(frames, ts, prompt_ts, actions),
                "stub": False, "error": type(e).__name__}
