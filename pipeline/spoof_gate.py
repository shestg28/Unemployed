"""Step 1 go/no-go gate for the Silent-Face passive anti-spoof models.

    python -m pipeline.spoof_gate --dir data/gate

<dir> has subfolders real/ print/ phone/ replay/ mask/ (missing ones are skipped).
Prints per-image live score, per-class min/mean/max, the single threshold that
best separates real vs print+phone, counts at that threshold, ms/frame, and a
GO / PARTIAL / NO-GO verdict:

  GO      a threshold passes >=90% real AND fails >=90% print AND >=90% phone
  PARTIAL only print separates (>=90% real pass, >=90% print fail)
  NO-GO   otherwise

Only one threshold is chosen here; do not iterate on these images.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from .silentface import REAL_CLASS, SilentFace

CLASSES = ["real", "print", "phone", "replay", "mask"]
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
RATE = 0.9  # ">= 9/10"


def rates(scores: dict[str, list[float]], t: float) -> dict[str, float]:
    """real: fraction passing (score >= t); spoof classes: fraction failing (score < t)."""
    out = {}
    for c, s in scores.items():
        if not s:
            continue
        out[c] = (sum(x >= t for x in s) if c == "real" else sum(x < t for x in s)) / len(s)
    return out


def best_threshold(scores: dict[str, list[float]], spoof: list[str]) -> tuple[float, dict]:
    """Threshold maximising the worst of (real pass, each spoof class fail); ties -> widest gap."""
    allv = sorted({x for c in ["real", *spoof] for x in scores.get(c, [])})
    cands = [0.0] + [(a + b) / 2 for a, b in zip(allv, allv[1:])] + [1.0 + 1e-9]
    best = None
    for t in cands:
        r = rates({c: scores.get(c, []) for c in ["real", *spoof]}, t)
        worst = min(r.values()) if r else 0.0
        # margin = distance from t to the nearest score (prefer thresholds in the middle of a gap)
        margin = min((abs(x - t) for x in allv), default=0.0)
        key = (worst, margin)
        if best is None or key > best[0]:
            best = (key, t, r)
    return best[1], best[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path)
    args = ap.parse_args(argv)

    t_load = time.perf_counter()
    sf = SilentFace()
    print(f"Loaded detector + {len(sf.models)} models once in {(time.perf_counter() - t_load) * 1000:.0f} ms: "
          f"{[m[0] for m in sf.models]}; real class index = {REAL_CLASS}")

    files = {c: sorted(p for p in (args.dir / c).glob("*") if p.suffix.lower() in EXTS)
             for c in CLASSES if (args.dir / c).is_dir()}
    if not any(files.values()):
        print(f"No images under {args.dir}/{{{','.join(CLASSES)}}}")
        return 2

    # warm-up (first torch call is slow) on the first image found
    first = next(p for fs in files.values() for p in fs)
    warm = cv2.imread(str(first))
    if warm is not None:
        sf.predict(warm)

    scores: dict[str, list[float]] = {c: [] for c in files}
    total_ms, model_ms = [], []
    print(f"\n{'class':7} {'live':>6} {'label':>5} {'ms':>6}  file")
    for c, fs in files.items():
        for p in fs:
            img = cv2.imread(str(p))  # BGR, exactly as upstream test.py
            if img is None:
                print(f"{c:7} {'-':>6} {'-':>5} {'-':>6}  {p.name}  (unreadable, skipped)")
                continue
            note = ""
            h, w = img.shape[:2]
            if w / h != 3 / 4:
                note = "  (not 3:4; upstream test.py would refuse it, scored anyway)"
            t0 = time.perf_counter()
            bbox = sf.get_bbox(img)
            t1 = time.perf_counter()
            r = sf.predict(img, bbox)
            t2 = time.perf_counter()
            total_ms.append((t2 - t0) * 1000)
            model_ms.append((t2 - t1) * 1000)
            scores[c].append(r["live_score"])
            print(f"{c:7} {r['live_score']:6.3f} {r['label']:>5} {total_ms[-1]:6.1f}  {p.name}{note}")

    print(f"\n{'class':7} {'n':>3} {'min':>6} {'mean':>6} {'max':>6}")
    for c, s in scores.items():
        if s:
            print(f"{c:7} {len(s):3d} {min(s):6.3f} {statistics.mean(s):6.3f} {max(s):6.3f}")

    spoof = [c for c in ("print", "phone") if scores.get(c)]
    if not scores.get("real") or not spoof:
        print("\nNeed real/ and at least one of print/ phone/ to choose a threshold.")
        return 2
    t, r = best_threshold(scores, spoof)
    allr = rates(scores, t)
    print(f"\nBest threshold real vs {'+'.join(spoof)}: live_score >= {t:.4f} passes")
    for c, s in scores.items():
        if not s:
            continue
        k = sum(x >= t for x in s) if c == "real" else sum(x < t for x in s)
        verb = "pass" if c == "real" else "fail (caught)"
        print(f"  {c:7} {k}/{len(s)} {verb}  ({allr[c]:.0%})")

    print(f"\nms/frame on this CPU (detector + {len(sf.models)} models), n={len(total_ms)}: "
          f"mean {statistics.mean(total_ms):.1f}, median {statistics.median(total_ms):.1f}, "
          f"p95 {float(np.percentile(total_ms, 95)):.1f}; models only mean {statistics.mean(model_ms):.1f}")

    go = scores.get("phone") and r.get("real", 0) >= RATE and r.get("print", 0) >= RATE and r.get("phone", 0) >= RATE
    # PARTIAL: does any threshold separate real vs print alone?
    tp, rp = best_threshold(scores, ["print"]) if scores.get("print") else (None, {})
    partial = bool(rp) and rp.get("real", 0) >= RATE and rp.get("print", 0) >= RATE
    if go:
        verdict = "GO"
    elif partial:
        verdict = f"PARTIAL (prints separate at {tp:.4f}; phone does not)"
    else:
        verdict = "NO-GO"
    if not scores.get("phone"):
        verdict += "  [no phone/ images, GO impossible]"
    print(f"\nVERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
