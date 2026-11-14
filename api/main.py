"""HTTP API: v2 attempt flow + v1 /verify, all decided by api.decide.decide().

Run from the repo root:  uvicorn api.main:app --port 8000

Nothing in the decision path calls pipeline.liveness.fuse() or motion.py.
"""
import logging
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import config, identity, mode, schedule, signals
from .attempt_log import late_result, write_decision
from .decide import decide, message_for
from .store import STORE, Attempt, identity_snapshot, now_ms

log = logging.getLogger("api")
_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="api")
CHALLENGE_UPLOAD_GRACE_MS = 2000
CHALLENGE_IDENTITY_TIMEOUT_S = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    identity.load_enrolled()   # reference bytes, once
    identity.init_client()     # shared boto3 client, once (keep-alive pool)
    identity.warm_up()         # throwaway CompareFaces: pay TLS setup now
    stubs = signals.stubs_in_use()
    if stubs:
        log.warning("STUB pipeline functions in use (never ALLOW): %s", stubs)
    yield


app = FastAPI(title="HID liveness", lifespan=lifespan)


# --- helpers ------------------------------------------------------------------

def _read_frames(files: list[UploadFile]) -> list[bytes]:
    if not 1 <= len(files) <= config.MAX_FRAMES:
        raise HTTPException(400, f"send 1-{config.MAX_FRAMES} frames")
    data = [f.file.read() for f in files]
    if any(not b or len(b) > config.MAX_FRAME_BYTES for b in data):
        raise HTTPException(400, "each frame must be a non-empty image under 5 MB")
    return data


def _parse_ts(values: list[str] | None, n: int) -> list[int]:
    """Accept repeated fields or one comma-separated field. Pads with 0s."""
    out: list[int] = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                try:
                    out.append(int(float(part)))
                except ValueError:
                    raise HTTPException(400, "capture_ts_ms must be integers")
    return (out + [0] * n)[:n]


def _get_attempt(attempt_id: str) -> Attempt:
    at = STORE.get(attempt_id)
    if at is None:
        raise HTTPException(404, "unknown attempt_id")
    return at


def _labels_future(frame: bytes):
    """Optional, flag-gated detect_labels. Logged only; never decides."""
    if not config.LABELS_SIGNAL_ENABLED:
        return None
    from pipeline.liveness import _call_labels, get_client
    return _EXECUTOR.submit(lambda: _call_labels(get_client(), frame))


def _labels_result(fut) -> list | None:
    if fut is None or not fut.done():
        return None
    try:
        return fut.result(timeout=0)
    except Exception:
        return None


def _quality_and_passive(frames: list[bytes], ts: list[int]) -> tuple[dict, dict, dict]:
    t = time.perf_counter()
    q = signals.quality(frames)
    t_q = time.perf_counter()
    idx = signals.select_frames(frames, ts)  # quality + spacing only
    p = signals.passive_liveness([frames[i] for i in idx])
    t_p = time.perf_counter()
    stage = {"quality": int((t_q - t) * 1000), "passive": int((t_p - t_q) * 1000)}
    return q, p, stage


def _quality_view(q: dict | None) -> dict:
    q = q or {}
    return {"ok": q.get("ok"), "fail_reason": q.get("fail_reason"),
            "continuity_ok": q.get("continuity_ok"),
            "per_frame": q.get("per_frame", []), "stub": bool(q.get("stub"))}


def _identity_view(ident: dict | None) -> dict:
    if ident is None:
        return {"status": "UNKNOWN", "similarity": None, "note": "not_received_by_deadline"}
    return {"status": ident.get("identity", "UNKNOWN"),
            "similarity": ident.get("similarity"), "note": ident.get("note")}


def _decision_signals(q, p, ident, challenge=None, *, user_id: str) -> dict:
    """Schedule and mode are evaluated NOW, at the moment of the decision."""
    return {
        "schedule": schedule.evaluate(user_id, config.KIOSK_ZONE),
        "mode": mode.current(),
        "quality": q if isinstance(q, dict) and isinstance(q.get("ok"), bool) else None,
        "passive": p,
        "identity": None if ident is None else
                    {"status": ident.get("identity"), "similarity": ident.get("similarity")},
        "challenge": challenge,
        "passive_allow_enabled": config.PASSIVE_ALLOW_ENABLED,
    }


def _schedule_view(sig: dict) -> dict:
    sc = sig.get("schedule") or {}
    return {"status": sc.get("status", "UNKNOWN"), "policy_version": sc.get("policy_version")}


def _log(at_id, user_id, scenario, phase, d, q, p, ident, stage, first_ms, total_ms,
         challenge=None, labels=None, sig=None):
    sig = sig or {}
    write_decision({
        "attempt_id": at_id, "user_id": user_id, "scenario": scenario, "phase": phase,
        "decision": d[0], "reason": d[1], "next_action": d[2],
        "schedule": {**_schedule_view(sig), "note": (sig.get("schedule") or {}).get("note")},
        "mode": sig.get("mode"), "demo_clock": schedule.override_active(),
        "scores": {
            "quality_ok": (q or {}).get("ok"),
            "continuity_ok": (q or {}).get("continuity_ok"),
            "passive_status": (p or {}).get("status"),
            "passive_score": (p or {}).get("score"),
            "identity_status": _identity_view(ident)["status"],
            "identity_similarity": _identity_view(ident)["similarity"],
            "challenge_status": (challenge or {}).get("status"),
            "labels": labels,
        },
        "stubs": signals.stubs_in_use(),
        "stage_ms": stage, "first_pass_ms": first_ms, "total_ms": total_ms,
    })


# --- v2: attempt flow -------------------------------------------------------------

class StartBody(BaseModel):
    user_id: str
    consent: bool


@app.post("/attempt/start")
def attempt_start(body: StartBody) -> dict:
    if body.consent is not True:
        raise HTTPException(400, "consent required")
    if not identity.USER_ID_RE.match(body.user_id or ""):
        raise HTTPException(400, "invalid user_id")
    at = STORE.create(body.user_id)
    return {"attempt_id": at.attempt_id, "server_t0_ms": at.server_t0_ms,
            "deadline_ms": at.deadline_ms}


@app.post("/attempt/{attempt_id}/identity")
def attempt_identity(attempt_id: str, frame: UploadFile = File(...),
                     capture_ts_ms: str | None = Form(None)) -> dict:
    at = _get_attempt(attempt_id)
    data = _read_frames([frame])
    try:
        res = identity.compare(at.user_id, data[0])
    finally:
        data.clear()
    outcome = STORE.record_identity(attempt_id, res)
    if outcome == "unknown_attempt":
        raise HTTPException(404, "unknown attempt_id")
    if outcome == "late":
        late_result(attempt_id, "identity", res)
    return {"identity": res["identity"], "similarity": res["similarity"], "ms": res["ms"]}


def _first_pass_response(at: Attempt, d, q, p, ident, stage, first_ms, sig) -> dict:
    return {
        "decision": d[0], "reason_code": d[1], "message": message_for(d[1], d[2]),
        "next_action": d[2], "attempt_id": at.attempt_id,
        "schedule": _schedule_view(sig), "mode": sig["mode"],
        "signals": {"quality": _quality_view(q),
                    "passive": {"status": (p or {}).get("status", "UNAVAILABLE"),
                                "score": (p or {}).get("score")},
                    "identity": _identity_view(ident)},
        "stage_ms": stage, "first_pass_server_ms": first_ms,
    }


@app.post("/attempt/{attempt_id}/liveness")
def attempt_liveness(attempt_id: str, frames: list[UploadFile] = File(...),
                     capture_ts_ms: list[str] | None = Form(None),
                     scenario: str | None = Form(None)) -> dict:
    at = _get_attempt(attempt_id)
    if at.decision is not None:  # first pass is FINAL
        return at.decision
    data = _read_frames(frames)
    try:
        ts = _parse_ts(capture_ts_ms, len(data))
        labels_fut = _labels_future(data[len(data) // 2])
        q, p, stage = _quality_and_passive(data, ts)
    finally:
        data.clear()  # kiosk keeps nothing

    t_wait = time.perf_counter()
    at.identity_event.wait(timeout=max(at.deadline_mono - time.monotonic(), 0.0))
    stage["identity_wait"] = int((time.perf_counter() - t_wait) * 1000)

    with at.lock:
        if at.decision is not None:  # a concurrent request decided first
            return at.decision
        t_dec = time.perf_counter()
        ident = identity_snapshot(at)  # on-time result only
        sig = _decision_signals(q, p, ident, user_id=at.user_id)
        d = decide(sig)
        stage["decide"] = int((time.perf_counter() - t_dec) * 1000)
        first_ms = now_ms() - at.server_t0_ms
        at.scenario, at.passive, at.quality = scenario, p, _quality_view(q)
        at.continuity_ok = (q or {}).get("continuity_ok")
        at.stage_ms = dict(stage)
        mine = _first_pass_response(at, d, q, p, ident, stage, first_ms, sig)
        resp = at.set_decision(mine)
    if resp is mine:  # only the request that actually decided logs it
        _log(at.attempt_id, at.user_id, scenario, "first_pass", d, q, p, ident, stage,
             first_ms, first_ms, labels=_labels_result(labels_fut), sig=sig)
    return resp


@app.post("/attempt/{attempt_id}/challenge/start")
def challenge_start(attempt_id: str) -> dict:
    at = _get_attempt(attempt_id)
    with at.lock:
        if at.decision is None or at.decision["decision"] != "REQUEST_VERIFICATION":
            raise HTTPException(409, "challenge only after a REQUEST_VERIFICATION first pass")
        if at.challenge is not None:
            raise HTTPException(409, "one challenge per attempt")
        at.challenge = {"challenge_id": str(uuid.uuid4()),
                        "actions": random.sample(config.CHALLENGE_ACTIONS, 2),
                        "started_mono": time.monotonic()}
        ch = at.challenge
    return {"challenge_id": ch["challenge_id"], "actions": ch["actions"],
            "baseline_ms": config.CHALLENGE_BASELINE_MS,
            "timeout_ms": config.CHALLENGE_TIMEOUT_MS}


def _good_tracked_frame(q: dict | None, n: int) -> int | None:
    """Index of the best good frame, only if quality vouches it's one tracked face."""
    if not (isinstance(q, dict) and q.get("ok") is True and q.get("continuity_ok") is True):
        return None
    per = q.get("per_frame") or []
    good = [(f.get("face_px") or 0, i) for i, f in enumerate(per[:n])
            if isinstance(f, dict) and f.get("ok") is True and f.get("face_count") in (None, 1)]
    return max(good)[1] if good else None


def _challenge_identity(fut) -> dict:
    if fut is None:
        return {"identity": "UNKNOWN", "similarity": None, "ms": 0,
                "note": "no_good_tracked_frame"}
    try:
        return fut.result(timeout=CHALLENGE_IDENTITY_TIMEOUT_S)
    except Exception as e:  # timeout or failure -> never a pass
        return {"identity": "UNKNOWN", "similarity": None, "ms": None,
                "note": f"error:{type(e).__name__}"}


@app.post("/attempt/{attempt_id}/challenge")
def challenge_submit(attempt_id: str, frames: list[UploadFile] = File(...),
                     capture_ts_ms: list[str] | None = Form(None),
                     prompt_ts_ms: str | None = Form(None),
                     challenge_id: str = Form(...)) -> dict:
    at = _get_attempt(attempt_id)
    if at.challenge is None or at.challenge["challenge_id"] != challenge_id:
        raise HTTPException(409, "no such challenge for this attempt")
    if at.challenge_decision is not None:
        return at.challenge_decision
    elapsed_ms = (time.monotonic() - at.challenge["started_mono"]) * 1000
    timed_out = elapsed_ms > config.CHALLENGE_TIMEOUT_MS + CHALLENGE_UPLOAD_GRACE_MS
    data = _read_frames(frames)
    try:
        ts = _parse_ts(capture_ts_ms, len(data))
        prompt_ts = _parse_ts([prompt_ts_ms] if prompt_ts_ms else [], 1)[0]
        t = time.perf_counter()
        q = signals.quality(data)
        t_q = time.perf_counter()
        # Re-run identity on one good frame of the same tracked face, in
        # parallel with the challenge check. No such frame -> no call -> UNKNOWN.
        good = _good_tracked_frame(q, len(data))
        id_fut = (_EXECUTOR.submit(identity.compare, at.user_id, data[good])
                  if good is not None else None)
        ch = signals.challenge_check(data, ts, prompt_ts, at.challenge["actions"])
        t_c = time.perf_counter()
    finally:
        data.clear()
    ch_ident = _challenge_identity(id_fut)
    t_id = time.perf_counter()
    challenge = {"status": ch.get("status"), "passive": ch.get("passive"),
                 "timed_out": timed_out,
                 "identity": {"status": ch_ident["identity"],
                              "similarity": ch_ident["similarity"]}}
    with at.lock:
        if at.challenge_decision is not None:
            return at.challenge_decision
        ident = ch_ident  # challenge-frame identity replaces the first-pass one
        t_dec = time.perf_counter()
        sig = _decision_signals(q, at.passive, None, challenge, user_id=at.user_id)
        d = decide(sig)
        stage = {"quality": int((t_q - t) * 1000), "passive": int((t_c - t_q) * 1000),
                 "identity_wait": int((t_id - t_c) * 1000),
                 "decide": int((time.perf_counter() - t_dec) * 1000)}
        first_ms = at.decision["first_pass_server_ms"]
        total_ms = now_ms() - at.server_t0_ms
        resp = _first_pass_response(at, d, q, (ch.get("passive") or {}), ident, stage,
                                    first_ms, sig)
        resp["total_ms"] = total_ms
        mine = resp
        resp = at.set_challenge_decision(mine)
    if resp is mine:
        _log(at.attempt_id, at.user_id, at.scenario, "challenge", d, q, ch.get("passive"),
             ident, stage, first_ms, total_ms, challenge=challenge, sig=sig)
    return resp


# --- v3: operator demo clock ---------------------------------------------------------

class ClockBody(BaseModel):
    iso_time: str | None = None


@app.post("/operator/clock")
def operator_clock(body: ClockBody) -> dict:
    """Demo-only clock override (Asia/Kolkata if no offset). null = real time."""
    if not config.DEMO_CLOCK_ENABLED:
        raise HTTPException(403, "demo clock disabled")
    try:
        schedule.set_override(body.iso_time)
    except ValueError:
        raise HTTPException(400, "iso_time must be ISO 8601, e.g. 2026-11-14T10:30:00")
    log.warning("DEMO CLOCK %s", "set to " + body.iso_time if body.iso_time else "cleared")
    return {"kiosk_time": schedule.now().isoformat(timespec="seconds"),
            "demo_clock": schedule.override_active()}


# --- v1: /verify (shape unchanged, routed through decide()) ----------------------

_V1_REASON = {
    "OK_LIVE_MATCH": "LIVE_MATCH",
    "SPOOF_PASSIVE": "SCREEN_DETECTED",
    "ID_MISMATCH": "NO_MATCH",
    "ID_UNAVAILABLE": "NO_MATCH",
    "TIMEOUT": "NO_MATCH",
    "LIVENESS_UNCERTAIN": "NO_MOTION",
    "LIVENESS_UNAVAILABLE": "NO_MOTION",
}


def _v1_confidence(d, p, sim) -> float:
    if d[0] == "ALLOW":
        c = min(sim / 100 if sim is not None else 0.0, (p or {}).get("score") or 0.0)
    elif d[1] == "SPOOF_PASSIVE":
        c = (p or {}).get("score") or 0.5
    elif d[1] == "ID_MISMATCH":
        c = 1 - (sim or 0.0) / 100
    else:
        c = 0.5
    return round(min(max(float(c), 0.0), 1.0), 4)


@app.post("/verify")
def verify(frames: list[UploadFile] = File(...), user_id: str = Form(...)) -> dict:
    # Sync endpoint: FastAPI runs it in a worker thread, so the blocking
    # Rekognition calls don't stall the event loop.
    t0 = time.perf_counter()
    data = _read_frames(frames)
    attempt_id = str(uuid.uuid4())
    try:
        mid = data[len(data) // 2]
        id_fut = _EXECUTOR.submit(identity.compare, user_id, mid)
        labels_fut = _labels_future(mid)
        q, p, stage = _quality_and_passive(data, [0] * len(data))
        t_wait = time.perf_counter()
        remaining = config.ATTEMPT_DEADLINE_MS / 1000 - (t_wait - t0)
        wait([id_fut], timeout=max(remaining, 0.0))
        stage["identity_wait"] = int((time.perf_counter() - t_wait) * 1000)
        ident = id_fut.result(timeout=0) if id_fut.done() else None  # late -> missing
    finally:
        data.clear()  # kiosk keeps nothing
    t_dec = time.perf_counter()
    sig = _decision_signals(q, p, ident, user_id=user_id)
    d = decide(sig)
    stage["decide"] = int((time.perf_counter() - t_dec) * 1000)
    decision_ms = int((time.perf_counter() - t0) * 1000)
    sim = (ident or {}).get("similarity")
    q_ok = [f for f in (q or {}).get("per_frame", []) if isinstance(f, dict)]
    labels = _labels_result(labels_fut)
    _log(attempt_id, user_id, "verify_v1", "first_pass", d, q, p, ident, stage,
         decision_ms, decision_ms, labels=labels, sig=sig)
    return {
        "decision": d[0],
        "confidence": _v1_confidence(d, p, sim),
        "decision_ms": decision_ms,
        "reason_code": _V1_REASON.get(d[1], "LOW_QUALITY"),
        "signals": {
            "labels": [l["name"] for l in labels or []],
            "motion": 0.0,
            "quality": round(sum(1 for f in q_ok if f.get("ok")) / len(q_ok), 4) if q_ok else 0.0,
            "similarity": round(float(sim or 0.0), 2),
        },
        # v3 additive fields (v1 keys above unchanged)
        "schedule": _schedule_view(sig), "mode": sig["mode"], "reason_detail": d[1],
    }
