"""Grab labelled webcam stills for the spoof gate.

    python -m pipeline.capture_gate --out data/gate [--cam 0]

Keys: r=real  p=print  f=phone(screen photo)  v=replay(video)  m=mask  q=quit
Each key saves the current raw frame (BGR, unmirrored, as cv2 reads it) to <out>/<class>/.
Images are face data: data/ must stay gitignored and they must not be committed.
"""
import argparse
import time
from pathlib import Path

import cv2

KEYS = {ord("r"): "real", ord("p"): "print", ord("f"): "phone", ord("v"): "replay", ord("m"): "mask"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/gate", type=Path)
    ap.add_argument("--cam", default=0, type=int)
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    counts = {c: len(list((a.out / c).glob("*.jpg"))) for c in KEYS.values()}
    while True:
        ok, frame = cap.read()
        if not ok:
            print("camera read failed")
            break
        view = cv2.flip(frame, 1)  # mirrored preview only; saved frame is raw
        cv2.putText(view, "r real p print f phone v replay m mask q quit", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
        cv2.putText(view, " ".join(f"{k}:{v}" for k, v in counts.items()), (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.imshow("capture_gate", view)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k in KEYS:
            c = KEYS[k]
            d = a.out / c
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{c}_{int(time.time() * 1000)}.jpg"
            cv2.imwrite(str(p), frame)
            counts[c] += 1
            print("saved", p)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
