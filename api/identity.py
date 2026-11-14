"""Identity via Rekognition CompareFaces (region from AWS_DEFAULT_REGION).

- One boto3 client, shared with the pipeline (pipeline.liveness.get_client),
  created once at startup. Creds come from repo-root .env via pipeline.config
  (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN).
- Reference photos are read once at startup from data/enrolled/<user_id>.jpg,
  downscaled to <=640 px and held in memory server-side only. Probe frames
  over 640 px are downscaled too. warm_up() runs one throwaway call at startup.
- MATCH if similarity >= ID_MATCH. MISMATCH only if exactly one face was found,
  its quality is adequate and similarity < ID_MISMATCH. Everything else,
  including any exception or timeout, is UNKNOWN.
"""
import io
import logging
import re
import threading
import time

from PIL import Image

from pipeline import config as PC
from pipeline.liveness import get_client

from . import config

log = logging.getLogger("api.identity")

USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Full-size webcam JPEGs (~180 KB) took ~3.3 s to upload on the venue network
# and hit the socket timeout; <=640 px (~36 KB) round-trips in ~350 ms.
MAX_SIDE = 640
# Integrator fix 14 Nov: send only the face. MediaPipe box + 30 % margin per
# side, <= 400 px, JPEG q85 (in memory only).
FACE_MAX_SIDE = 400
FACE_MARGIN = 0.30
JPEG_Q = 85


def face_crop(img: bytes, max_side: int = FACE_MAX_SIDE) -> tuple[bytes, str]:
    """-> (jpeg bytes, note). Face + margin, <= max_side px. Falls back to the whole
    frame downscaled if no single face is found (Rekognition then decides)."""
    try:
        import cv2
        import numpy as np
        from pipeline.challenge import metrics_for
        arr = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return img, "undecodable"
        m = metrics_for(img, arr)
        note = "face"
        if m.get("n_faces") == 1 and m.get("bbox"):
            H, W = arr.shape[:2]
            x, y, w, h = m["bbox"]
            mx, my = int(w * FACE_MARGIN), int(h * FACE_MARGIN)
            x0, y0 = max(0, x - mx), max(0, y - my)
            x1, y1 = min(W, x + w + mx), min(H, y + h + my)
            arr = arr[y0:y1, x0:x1]
        else:
            note = f"no_single_face({m.get('n_faces')})"
        h, w = arr.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        if scale < 1.0:
            arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
        return (buf.tobytes(), note) if ok else (fit(img, max_side), "encode_failed")
    except Exception as e:
        return fit(img, max_side), f"crop_error:{type(e).__name__}"


def fit(img: bytes, max_side: int = MAX_SIDE) -> bytes:
    """Downscale to <= max_side px (JPEG q85), in memory. Unchanged if already small
    or undecodable (Rekognition then reports its own error -> UNKNOWN)."""
    try:
        with Image.open(io.BytesIO(img)) as im:
            if max(im.size) <= max_side:
                return img
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=85)
            return out.getvalue()
    except Exception:
        return img
_ENROLLED: dict[str, bytes] = {}
_enrolled_lock = threading.Lock()
_loaded = False
# Outcome of the most recent CompareFaces call (warm-up included): for /status.
_last_call_ok: bool | None = None


_last_call_mono = 0.0
KEEP_WARM_S = 15.0  # idle HTTPS connections were dropped: first attempt after idle took 2.7 s


def keep_warm_once() -> bool:
    """If no CompareFaces in the last KEEP_WARM_S, make one tiny call (reference vs
    itself) so the pooled TLS connection stays open. Never raises."""
    if time.monotonic() - _last_call_mono < KEEP_WARM_S:
        return False
    with _enrolled_lock:
        ref = next(iter(_ENROLLED.values()), None)
    if ref is None:
        return False
    try:
        get_client().compare_faces(SourceImage={"Bytes": ref}, TargetImage={"Bytes": ref},
                                   SimilarityThreshold=0)
        _record(True)
        return True
    except Exception as e:
        log.warning("keep-warm CompareFaces failed: %s", type(e).__name__)
        _record(False)
        return False


def service_ok() -> bool:
    return _last_call_ok is True


def _record(ok: bool) -> None:
    global _last_call_ok, _last_call_mono
    _last_call_ok = ok
    _last_call_mono = time.monotonic()


def load_enrolled() -> int:
    """Read every data/enrolled/<user_id>.(jpg|jpeg|png) once. Returns count."""
    global _loaded
    refs: dict[str, bytes] = {}
    d = config.ENROLL_DIR
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and USER_ID_RE.match(p.stem):
                raw = p.read_bytes()
                crop, note = face_crop(raw)
                refs.setdefault(p.stem, crop)
                log.info("reference %s: %d KB -> %d KB (%s)", p.stem, len(raw) // 1024,
                         len(crop) // 1024, note)
    with _enrolled_lock:
        _ENROLLED.clear()
        _ENROLLED.update(refs)
        _loaded = True
    log.info("loaded %d enrolled reference(s) from %s", len(refs), d)
    return len(refs)


def enrolled_ids() -> list[str]:
    if not _loaded:
        load_enrolled()
    with _enrolled_lock:
        return sorted(_ENROLLED)


def reference_for(user_id: str) -> bytes | None:
    if not _loaded:
        load_enrolled()
    return _ENROLLED.get(user_id)


def init_client() -> bool:
    """Create the shared client once at startup. False if boto3/creds are missing."""
    try:
        get_client()
        return True
    except Exception as e:
        log.warning("Rekognition client not created: %s", type(e).__name__)
        return False


def warm_up() -> dict:
    """One throwaway CompareFaces (first reference vs itself) at startup so the
    first real attempt doesn't pay TLS/connection setup. Never raises."""
    with _enrolled_lock:
        uid, ref = next(iter(_ENROLLED.items()), (None, None))
    if ref is None:
        return {"ok": False, "ms": 0, "note": "no_enrolled_reference"}
    t0 = time.perf_counter()
    for attempt in (1, 2):  # retry once: the first TLS setup can fail on a slow network
        try:
            get_client().compare_faces(SourceImage={"Bytes": ref}, TargetImage={"Bytes": ref},
                                       SimilarityThreshold=0)
            note, ok = f"ok:{uid}" + (" (retry)" if attempt == 2 else ""), True
            _record(True)
            break
        except Exception as e:
            note, ok = f"error:{type(e).__name__}", False
            _record(False)
    ms = int((time.perf_counter() - t0) * 1000)
    # uvicorn.error is the logger uvicorn actually prints at INFO.
    startup_log = logging.getLogger("uvicorn.error")
    (startup_log.info if ok else startup_log.warning)("CompareFaces warm-up %s in %d ms", note, ms)
    return {"ok": ok, "ms": ms, "note": note}


def _face_quality_ok(face: dict) -> bool:
    q = face.get("Quality") or {}
    sharp, bright = q.get("Sharpness"), q.get("Brightness")
    if sharp is None or bright is None:
        return False
    return sharp >= PC.MIN_SHARPNESS and PC.MIN_BRIGHTNESS <= bright <= PC.MAX_BRIGHTNESS


def classify(resp: dict) -> tuple[str, float | None, str]:
    """CompareFaces response -> (status, similarity, note). Pure."""
    matches = resp.get("FaceMatches") or []
    unmatched = resp.get("UnmatchedFaces") or []
    n = len(matches) + len(unmatched)
    if n == 0:
        return "UNKNOWN", None, "no_face"
    if n > 1:
        return "UNKNOWN", None, "multi_face"
    if not matches:  # one face, but no similarity reported
        return "UNKNOWN", None, "no_similarity"
    m = matches[0]
    sim = m.get("Similarity")
    if sim is None:
        return "UNKNOWN", None, "no_similarity"
    sim = round(float(sim), 2)
    if sim >= config.ID_MATCH:
        return "MATCH", sim, "ok"
    if sim < config.ID_MISMATCH and _face_quality_ok(m.get("Face") or {}):
        return "MISMATCH", sim, "ok"
    return "UNKNOWN", sim, "grey_zone_or_low_quality"


def compare(user_id: str, frame: bytes) -> dict:
    """-> {identity, similarity, ms, note}. Never raises."""
    t0 = time.perf_counter()

    def out(status, sim, note):
        return {"identity": status, "similarity": sim,
                "ms": int((time.perf_counter() - t0) * 1000), "note": note}

    ref = reference_for(user_id)
    if ref is None:
        return out("UNKNOWN", None, "not_enrolled")
    target, _crop_note = face_crop(frame)
    if _crop_note.startswith("no_single_face"):
        log.warning("identity probe: %s", _crop_note)
    try:
        resp = get_client().compare_faces(
            SourceImage={"Bytes": ref},
            TargetImage={"Bytes": target},
            SimilarityThreshold=0,  # get the raw score; thresholds applied here
        )
        _record(True)
        return out(*classify(resp))
    except Exception as e:  # no creds, timeout, no face in source, throttling...
        _record(False)
        err = getattr(e, "response", None) or {}
        code = (err.get("Error") or {}).get("Code") or type(e).__name__
        msg = ((err.get("Error") or {}).get("Message") or str(e))[:200]
        log.warning("compare_faces failed: %s: %s (target %d B, %s)", code, msg, len(target),
                    _crop_note)
        return out("UNKNOWN", None, f"error:{code}: {msg}"[:240])
