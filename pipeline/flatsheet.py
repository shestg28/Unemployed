"""Pass 1: flat-sheet motion check (supporting signal, fully local, no model).

flat_sheet(frames, ts=None) -> {status: FLAT|NOT_FLAT|UNCERTAIN|NO_MOTION|UNAVAILABLE, ...}

Idea (team brief): a real face moves separately from the room; a held photo or
phone moves together with its own background. We track corner points inside the
face and in a ring around it across the burst, fit the face's own 2D motion
(affine, RANSAC), and ask how many ring points move the way the face does.

  ring points that follow the face model   -> part of the same sheet (paper, phone
                                              screen, bezel, hand holding it)
  ring points that stay put / move otherwise -> the room behind a real head

Statuses:
  FLAT       >= FS_FLAT_RATIO of ring points move with the face: spoof evidence
  NOT_FLAT   <= FS_NOT_FLAT_RATIO: the surroundings do not move with the face.
             This is NOT proof of liveness (pipeline doc 6D); it only means this
             check found no flat sheet. Never ALLOW on it alone.
  UNCERTAIN  in between
  NO_MOTION  the face barely moved: the signal is unavailable, NOT a spoof
  UNAVAILABLE no single tracked face, too few trackable points, or an error

Known limits: a phone held close enough that the ring is all screen, or a print
filling the frame, can look FLAT (correct) but a print whose border is cut off by the
frame edge leaves only room points in view of the ring and can look NOT_FLAT. Plain,
textureless walls give too few ring points (UNAVAILABLE). Thresholds are starting
values in config.py (FS_*), not measured.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from . import config as C
from .frames import decode, faces_for
from .silentface import get_detector

_MAX_SIDE = 480  # work on downscaled grey frames; motion is normalised by face width


def _masks(shape, box, ring_scale):
    h, w = shape
    x, y, bw, bh = box
    cx, cy = x + bw / 2, y + bh / 2
    face = np.zeros((h, w), np.uint8)
    # inner face (avoid hair / background at the box edge)
    fx0, fy0 = int(cx - bw * 0.35), int(cy - bh * 0.35)
    fx1, fy1 = int(cx + bw * 0.35), int(cy + bh * 0.4)
    face[max(fy0, 0):max(fy1, 0), max(fx0, 0):max(fx1, 0)] = 255
    ring = np.zeros((h, w), np.uint8)
    rx0, ry0 = int(cx - bw * ring_scale / 2), int(cy - bh * ring_scale / 2)
    rx1, ry1 = int(cx + bw * ring_scale / 2), int(cy + bh * ring_scale / 2)
    ring[max(ry0, 0):max(ry1, 0), max(rx0, 0):max(rx1, 0)] = 255
    ex0, ey0 = int(cx - bw * 0.6), int(cy - bh * 0.6)
    ex1, ey1 = int(cx + bw * 0.6), int(cy + bh * 0.6)
    ring[max(ey0, 0):max(ey1, 0), max(ex0, 0):max(ex1, 0)] = 0  # exclude face + margin
    return face, ring


def _features(gray, mask, n):
    pts = cv2.goodFeaturesToTrack(gray, maxCorners=n, qualityLevel=0.01, minDistance=5, mask=mask)
    return pts if pts is not None else np.zeros((0, 1, 2), np.float32)


def flat_sheet(frames: list, ts: list[float] | None = None) -> dict:
    t0 = time.perf_counter()

    def out(status, reason=None, **kw):
        return {"status": status, "reason": reason, **kw,
                "ms": int((time.perf_counter() - t0) * 1000)}

    if not frames or len(frames) < 2:
        return out("UNAVAILABLE", "NEED_2_FRAMES")
    if ts is not None and len(ts) == len(frames):
        order = sorted(range(len(frames)), key=lambda i: ts[i])
        frames = [frames[i] for i in order]
    try:
        det = get_detector()
        grays, boxes = [], []
        for f in frames:
            img = decode(f)
            if img is None:
                return out("UNAVAILABLE", "UNDECODABLE")
            faces = faces_for(f, img, det)
            if len(faces) != 1:
                return out("UNAVAILABLE", "NEED_SINGLE_FACE_EVERY_FRAME")
            s = min(1.0, _MAX_SIDE / max(img.shape[:2]))
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if s < 1.0:
                g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            grays.append(g)
            boxes.append([v * s for v in faces[0]["bbox"]])

        face_m, ring_m = _masks(grays[0].shape, boxes[0], C.FS_RING_SCALE)
        fp = _features(grays[0], face_m, 80)
        rp = _features(grays[0], ring_m, 150)
        if len(fp) < C.FS_MIN_POINTS or len(rp) < C.FS_MIN_POINTS:
            return out("UNAVAILABLE", "TOO_FEW_POINTS", face_points=len(fp), ring_points=len(rp))

        pts0 = np.concatenate([fp, rp]).astype(np.float32)
        n_face = len(fp)
        cur = pts0.copy()
        alive = np.ones(len(pts0), bool)
        lk = dict(winSize=(21, 21), maxLevel=3,
                  criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        for g0, g1 in zip(grays, grays[1:]):  # chain frame to frame (small steps track well)
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, cur, None, **lk)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, nxt, None, **lk)
            fb = np.linalg.norm((back - cur).reshape(-1, 2), axis=1)
            alive &= (st.ravel() == 1) & (st2.ravel() == 1) & (fb < 1.5)
            cur = nxt

        p0 = pts0.reshape(-1, 2)
        p1 = cur.reshape(-1, 2)
        fa = alive[:n_face]
        ra = alive[n_face:]
        f0, f1 = p0[:n_face][fa], p1[:n_face][fa]
        r0, r1 = p0[n_face:][ra], p1[n_face:][ra]
        if len(f0) < C.FS_MIN_POINTS or len(r0) < C.FS_MIN_POINTS:
            return out("UNAVAILABLE", "TRACKING_LOST_POINTS", face_points=int(len(f0)),
                       ring_points=int(len(r0)))

        face_w = float(boxes[0][2])
        face_disp = float(np.median(np.linalg.norm(f1 - f0, axis=1)))
        # also count scale change (walking closer) as face motion
        size_change = abs(boxes[-1][2] - boxes[0][2])
        face_motion_px = max(face_disp, size_change / 2)
        face_motion = face_motion_px / face_w
        if face_motion < C.FS_MIN_FACE_MOTION:
            return out("NO_MOTION", "FACE_DID_NOT_MOVE", face_motion=round(face_motion, 4))

        M, inl = cv2.estimateAffine2D(f0, f1, method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if M is None:
            return out("UNAVAILABLE", "NO_FACE_MOTION_MODEL")
        pred = r0 @ M[:, :2].T + M[:, 2]
        err = np.linalg.norm(r1 - pred, axis=1)
        attached = err < C.FS_ATTACH_TOL * face_motion_px
        ratio = float(attached.mean())
        info = dict(attached_ratio=round(ratio, 3), face_motion=round(face_motion, 4),
                    face_points=int(len(f0)), ring_points=int(len(r0)),
                    face_inliers=int(inl.sum()) if inl is not None else None)
        if ratio >= C.FS_FLAT_RATIO:
            return out("FLAT", "SURROUNDINGS_MOVE_WITH_FACE", **info)
        if ratio <= C.FS_NOT_FLAT_RATIO:
            return out("NOT_FLAT", "FACE_MOVES_INDEPENDENTLY", **info)
        return out("UNCERTAIN", "MIXED", **info)
    except Exception as e:
        return out("UNAVAILABLE", f"error: {e}"[:200])
