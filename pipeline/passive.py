"""Passive liveness over a few frames with Silent-Face (CONTRACT v2).

passive_liveness(frames) -> {status: LIVE|SPOOF|UNCERTAIN|UNAVAILABLE, score, per_frame, ...}

Conservative aggregation (thresholds in config, env-overridable):
  LIVE      every frame was scored AND min score >= PASSIVE_HIGH
  SPOOF     median score <= PASSIVE_LOW
  UNCERTAIN otherwise (including frames with no face)
  UNAVAILABLE model could not load or run; never treated as a pass.

Scores are Silent-Face live scores (see silentface.py). They are NOT
probabilities; never present them as "% secure".
"""
from __future__ import annotations

import statistics
import time

from . import config as C
from .frames import decode, faces_for
from .silentface import get


def passive_liveness(frames: list) -> dict:
    t0 = time.perf_counter()
    if not frames:
        return {"status": "UNCERTAIN", "score": None, "per_frame": [], "reason": "NO_FRAMES",
                "ms": 0}
    try:
        sf = get()
    except Exception as e:
        return {"status": "UNAVAILABLE", "score": None, "per_frame": [], "reason": str(e)[:200],
                "ms": int((time.perf_counter() - t0) * 1000)}

    per_frame = []
    try:
        for f in frames:
            img = decode(f)
            if img is None:
                per_frame.append({"score": None, "reason": "UNDECODABLE"})
                continue
            faces = faces_for(f, img, sf.detector)
            if not faces:
                per_frame.append({"score": None, "reason": "NO_FACE"})
                continue
            r = sf.predict(img, faces[0]["bbox"])
            per_frame.append({"score": round(r["live_score"], 4), "label": r["label"],
                              "bbox": r["bbox"]})
    except Exception as e:  # inference failure -> no signal, never a pass
        return {"status": "UNAVAILABLE", "score": None, "per_frame": per_frame,
                "reason": f"inference error: {e}"[:200],
                "ms": int((time.perf_counter() - t0) * 1000)}

    scores = [p["score"] for p in per_frame if p["score"] is not None]
    if not scores:
        status, score, med = "UNCERTAIN", None, None
    else:
        mn, med = min(scores), statistics.median(scores)
        if len(scores) == len(frames) and mn >= C.PASSIVE_HIGH:
            status = "LIVE"
        elif med <= C.PASSIVE_LOW:
            status = "SPOOF"
        else:
            status = "UNCERTAIN"
        score = mn
    return {
        "status": status,
        "score": score,              # min live score over scored frames (what LIVE is tested on)
        "median": med,
        "n_scored": len(scores),
        "thresholds": {"high": C.PASSIVE_HIGH, "low": C.PASSIVE_LOW},
        "per_frame": per_frame,
        "ms": int((time.perf_counter() - t0) * 1000),
    }


def warmup() -> bool:
    """Load the detector + models and run one dummy inference (first torch call is slow,
    ~1 s). Call once at API startup so the first attempt stays inside the 2 s budget.
    Returns False if Silent-Face is unavailable."""
    import numpy as np
    try:
        sf = get()
        sf.predict(np.full((640, 480, 3), 128, np.uint8), [140, 200, 200, 240])
        return True
    except Exception:
        return False
