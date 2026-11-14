"""Local frame-quality gate and quality-only frame selection (CONTRACT v2).

quality(frames)          -> per-frame {face_count, face_px, blur, brightness, ok, fail_reason}
                            + burst summary + continuity
select_frames(frames,ts) -> indices of up to SELECT_MAX usable, time-spaced frames,
                            chosen by QUALITY ONLY (never by liveness score)

Frames are JPEG/PNG bytes (or BGR ndarrays). Decoded in memory only.

Face box / count / continuity come from the MediaPipe FaceLandmarker (same model
the challenge uses). The Silent-Face RetinaFace detector scored our kiosk webcam
faces at 0.15-0.23 (< 0.6) -> NO_FACE on clearly visible faces, so it is now used
only for the MiniFASNet crop inside passive_liveness (log-only). [integrator fix 14 Nov]
fail_reason values are CONTRACT reason codes:
  NO_FACE, MULTI_FACE, QUALITY_TOO_SMALL, QUALITY_DARK, QUALITY_BLUR, TRACKING_LOST
"""
from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from . import config as C
from .challenge import landmarker_ok, metrics_for
from .frames import decode

_BLUR_SIZE = (160, 160)  # face crop is resized before Laplacian so blur is scale-independent


def _iou(a: list[int], b: list[int]) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _mp_box(m: dict, img) -> list[int] | None:
    """MediaPipe landmark box clamped to the frame."""
    if not m.get("bbox"):
        return None
    H, W = img.shape[:2]
    x, y, w, h = m["bbox"]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return [x0, y0, x1 - x0, y1 - y0] if x1 - x0 > 2 and y1 - y0 > 2 else None


def _frame_quality(frame) -> dict:
    img = decode(frame)
    if img is None:
        return {"face_count": 0, "face_px": 0, "blur": 0.0, "brightness": 0.0,
                "bbox": None, "ok": False, "fail_reason": "NO_FACE"}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = metrics_for(frame, img)
    box = _mp_box(m, img)
    rec = {"face_count": int(m.get("n_faces") or 0), "face_px": 0, "blur": 0.0,
           "brightness": round(float(gray.mean()), 1), "bbox": None}
    if box:
        x, y, w, h = box
        crop = gray[y:y + h, x:x + w]
        if crop.size:
            rec["bbox"] = [x, y, w, h]
            rec["face_px"] = int(min(w, h))
            rec["brightness"] = round(float(crop.mean()), 1)
            small = cv2.resize(crop, _BLUR_SIZE, interpolation=cv2.INTER_AREA)
            rec["blur"] = round(float(cv2.Laplacian(small, cv2.CV_64F).var()), 1)

    # first failing check wins; darkness is reported even when the face can't be found
    if rec["brightness"] < C.Q_MIN_BRIGHTNESS:
        reason = "QUALITY_DARK"
    elif rec["face_count"] == 0 or rec["bbox"] is None:
        reason = "NO_FACE"
    elif rec["face_count"] > 1:
        reason = "MULTI_FACE"
    elif rec["face_px"] < C.Q_MIN_FACE_PX:
        reason = "QUALITY_TOO_SMALL"
    elif rec["blur"] < C.Q_MIN_BLUR:
        reason = "QUALITY_BLUR"
    else:
        reason = None
    rec["ok"] = reason is None
    rec["fail_reason"] = reason
    return rec


def quality(frames: list) -> dict:
    """Quality of a burst.

    Returns {per_frame, ok, fail_reason, continuity_ok, summary}.
    ok requires >= Q_MIN_USABLE usable frames AND continuity (exactly one face in
    every frame, consecutive face-box IoU >= Q_MIN_IOU, i.e. the same face throughout).
    """
    if not landmarker_ok():
        return {"per_frame": [], "ok": False, "fail_reason": "LIVENESS_UNAVAILABLE",
                "continuity_ok": False, "summary": {"n_frames": len(frames), "n_usable": 0,
                                                    "detector": "UNAVAILABLE"}}
    per = [_frame_quality(f) for f in frames]

    single = all(p["face_count"] == 1 and p["bbox"] for p in per)
    ious = [round(_iou(a["bbox"], b["bbox"]), 3) for a, b in zip(per, per[1:])
            if a["bbox"] and b["bbox"]]
    continuity_ok = bool(per) and single and all(i >= C.Q_MIN_IOU for i in ious)

    usable = [i for i, p in enumerate(per) if p["ok"]]
    if len(usable) < C.Q_MIN_USABLE:
        reasons = Counter(p["fail_reason"] for p in per if p["fail_reason"])
        fail = reasons.most_common(1)[0][0] if reasons else "NO_FACE"
    elif not continuity_ok:
        fail = "MULTI_FACE" if any(p["face_count"] > 1 for p in per) else "TRACKING_LOST"
    else:
        fail = None

    def med(key):
        vals = [p[key] for p in per if p["bbox"]]
        return round(float(np.median(vals)), 1) if vals else 0.0

    return {
        "per_frame": per,
        "ok": fail is None,
        "fail_reason": fail,
        "continuity_ok": continuity_ok,
        "summary": {
            "n_frames": len(per), "n_usable": len(usable), "usable": usable,
            "median_face_px": med("face_px"), "median_blur": med("blur"),
            "median_brightness": med("brightness"), "min_iou": min(ious) if ious else None,
        },
    }


def _quality_rank(p: dict) -> float:
    """Higher is better: sharpness, then face size. Liveness never enters here."""
    return p["blur"] / max(C.Q_MIN_BLUR, 1.0) + p["face_px"] / max(C.Q_MIN_FACE_PX, 1.0)


def select_frames(frames: list, ts: list[float], q: dict | None = None) -> list[int]:
    """Up to SELECT_MAX usable frames spread over the burst's time span.

    The span [min ts, max ts] is split into SELECT_MAX equal bins; from each bin
    the usable frame with the best QUALITY rank is taken. Pass q (a quality()
    result for the same frames) to avoid recomputing it.
    """
    if not frames:
        return []
    q = q or quality(frames)
    per = q["per_frame"]
    usable = [i for i, p in enumerate(per) if p["ok"]]
    if not usable:
        return []
    ts = list(ts) if ts is not None and len(ts) == len(frames) else list(range(len(frames)))
    k = max(1, C.SELECT_MAX)
    if len(usable) <= k:
        return usable
    t0, t1 = min(ts[i] for i in usable), max(ts[i] for i in usable)
    span = (t1 - t0) or 1.0
    bins: dict[int, int] = {}
    for i in usable:
        b = min(k - 1, int((ts[i] - t0) / span * k))
        if b not in bins or _quality_rank(per[i]) > _quality_rank(per[bins[b]]):
            bins[b] = i
    picked = set(bins.values())
    # an empty bin (frames bunched in time): top up with best remaining by quality
    for i in sorted(usable, key=lambda i: -_quality_rank(per[i])):
        if len(picked) >= k:
            break
        picked.add(i)
    return sorted(picked)
