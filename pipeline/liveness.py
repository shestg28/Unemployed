"""Passive liveness + identity match -> ALLOW / REQUEST_VERIFICATION / DENY.

Three Rekognition calls run in parallel threads (CONTRACT.md hard rule):
  1. detect_labels on the full frame  -> screen / print spoof cues
  2. detect_faces (Attributes=ALL)    -> sharpness, brightness, pose
  3. compare_faces vs enrolled photo  -> identity, SimilarityThreshold=99
Motion across the burst is computed locally while those calls are in flight.

Nothing is persisted: frames live in memory for the duration of the call.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from . import config as C
from .motion import motion_score

_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 3 calls per request; headroom so concurrent requests (or a call still
# hanging past the deadline) never queue behind each other.
_EXECUTOR = ThreadPoolExecutor(max_workers=24, thread_name_prefix="rekognition")
_client = None
_client_lock = threading.Lock()


def get_client():
    """One shared Rekognition client (thread-safe; creating one costs ~100ms)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import boto3
                from botocore.config import Config

                _client = boto3.client(
                    "rekognition",
                    region_name=C.AWS_REGION,
                    config=Config(
                        connect_timeout=C.CONNECT_TIMEOUT_S,
                        read_timeout=C.READ_TIMEOUT_S,
                        retries={"max_attempts": 1, "mode": "standard"},
                        # Reuse warm HTTPS connections across calls/threads.
                        tcp_keepalive=True,
                        max_pool_connections=50,
                    ),
                )
    return _client


def load_enrolled(user_id: str) -> bytes | None:
    if not _USER_ID_RE.match(user_id or ""):
        return None
    for ext in (".jpg", ".jpeg", ".png"):
        path = C.ENROLL_DIR / f"{user_id}{ext}"
        if path.is_file():
            return path.read_bytes()
    return None


# --- The three Rekognition calls -------------------------------------------

def _call_labels(client, frame: bytes) -> list[dict]:
    resp = client.detect_labels(Image={"Bytes": frame}, MinConfidence=50)
    spoof = C.SCREEN_LABELS | C.PRINT_LABELS
    return [
        {"name": l["Name"], "confidence": round(l["Confidence"], 2)}
        for l in resp.get("Labels", [])
        if l["Name"] in spoof
    ]


def _call_faces(client, frame: bytes) -> list[dict]:
    resp = client.detect_faces(Image={"Bytes": frame}, Attributes=["ALL"])
    return resp.get("FaceDetails", [])


def _call_compare(client, frame: bytes, enrolled: bytes | None) -> float:
    if enrolled is None:
        return 0.0
    try:
        resp = client.compare_faces(
            SourceImage={"Bytes": enrolled},
            TargetImage={"Bytes": frame},
            SimilarityThreshold=C.SIMILARITY_THRESHOLD,
        )
    except client.exceptions.InvalidParameterException:
        return 0.0  # no face found in one of the images
    matches = resp.get("FaceMatches", [])
    return max((m["Similarity"] for m in matches), default=0.0)


# --- Signal helpers ---------------------------------------------------------

def _face_quality(faces: list[dict]) -> tuple[float, bool]:
    """-> (quality 0..1, is_ok). Exactly one usable face is required."""
    if len(faces) != 1:
        return 0.0, False
    f = faces[0]
    sharp = f.get("Quality", {}).get("Sharpness", 0.0)
    bright = f.get("Quality", {}).get("Brightness", 0.0)
    pose = f.get("Pose", {})
    pose_ok = (abs(pose.get("Yaw", 0.0)) <= C.MAX_POSE_DEG
               and abs(pose.get("Pitch", 0.0)) <= C.MAX_POSE_DEG)
    ok = (sharp >= C.MIN_SHARPNESS
          and C.MIN_BRIGHTNESS <= bright <= C.MAX_BRIGHTNESS
          and pose_ok)
    quality = (sharp + bright) / 200.0 * (1.0 if pose_ok else 0.5)
    return round(min(max(quality, 0.0), 1.0), 4), ok


def _spoof_reason(label: dict) -> str:
    return "SCREEN_DETECTED" if label["name"] in C.SCREEN_LABELS else "PRINT_DETECTED"


def fuse(labels: list[dict] | None, faces: list[dict] | None,
         similarity: float | None, motion: float) -> dict:
    """Pure decision logic. None for a signal means its call failed/timed out.

    Order: strong spoof -> DENY; anything missing, weak or low quality ->
    REQUEST_VERIFICATION; only a clean, live, matched face -> ALLOW.
    """
    quality, quality_ok = _face_quality(faces or [])
    sim = similarity or 0.0
    top = max(labels or [], key=lambda l: l["confidence"], default=None)

    def out(decision, reason, confidence):
        return {
            "decision": decision,
            "confidence": round(min(max(confidence, 0.0), 1.0), 4),
            "reason_code": reason,
            "signals": {
                "labels": [l["name"] for l in labels or []],
                "motion": float(motion),
                "quality": float(quality),
                "similarity": round(float(sim), 2),
            },
        }

    if top and top["confidence"] >= C.LABEL_STRONG_CONFIDENCE:
        return out("DENY", _spoof_reason(top), top["confidence"] / 100)
    # A failed call means we cannot rule out a spoof or confirm identity.
    if labels is None or faces is None or similarity is None:
        return out("REQUEST_VERIFICATION", "LOW_QUALITY", 0.5)
    if not quality_ok:
        return out("REQUEST_VERIFICATION", "LOW_QUALITY", 1 - quality)
    if top and top["confidence"] >= C.LABEL_MIN_CONFIDENCE:
        return out("REQUEST_VERIFICATION", _spoof_reason(top), top["confidence"] / 100)
    if motion < C.MIN_MOTION:
        return out("REQUEST_VERIFICATION", "NO_MOTION", 0.5)
    if sim < C.SIMILARITY_THRESHOLD:
        return out("REQUEST_VERIFICATION", "NO_MATCH", 1 - sim / 100)
    return out("ALLOW", "LIVE_MATCH", sim / 100)


# --- Entry point --------------------------------------------------------------

def verify(frames: list[bytes], user_id: str, client=None) -> dict[str, Any]:
    """Run the pipeline on a frame burst. Returns the CONTRACT.md response dict."""
    t0 = time.perf_counter()
    if not frames:
        raise ValueError("at least one frame is required")
    client = client or get_client()
    frame = frames[len(frames) // 2]  # middle of the burst goes to Rekognition
    enrolled = load_enrolled(user_id)

    futures = {
        "labels": _EXECUTOR.submit(_call_labels, client, frame),
        "faces": _EXECUTOR.submit(_call_faces, client, frame),
        "similarity": _EXECUTOR.submit(_call_compare, client, frame, enrolled),
    }
    motion = motion_score(frames)  # local work overlaps the network calls

    remaining = C.REKOGNITION_DEADLINE_S - (time.perf_counter() - t0)
    wait(futures.values(), timeout=max(remaining, 0.0))
    results: dict[str, Any] = {}
    for name, fut in futures.items():
        try:
            results[name] = fut.result(timeout=0) if fut.done() else None
        except Exception:
            results[name] = None  # failed call -> fused as missing signal

    response = fuse(results["labels"], results["faces"], results["similarity"], motion)
    decision_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "decision": response["decision"],
        "confidence": response["confidence"],
        "decision_ms": decision_ms,
        "reason_code": response["reason_code"],
        "signals": response["signals"],
    }
