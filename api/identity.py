"""Identity via Rekognition CompareFaces (region from AWS_DEFAULT_REGION).

- One boto3 client, shared with the pipeline (pipeline.liveness.get_client),
  created once at startup. Creds come from repo-root .env via pipeline.config
  (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN).
- Reference photos are read once at startup from data/enrolled/<user_id>.jpg
  and held in memory server-side only.
- MATCH if similarity >= ID_MATCH. MISMATCH only if exactly one face was found,
  its quality is adequate and similarity < ID_MISMATCH. Everything else,
  including any exception or timeout, is UNKNOWN.
"""
import logging
import re
import threading
import time

from pipeline import config as PC
from pipeline.liveness import get_client

from . import config

log = logging.getLogger("api.identity")

USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ENROLLED: dict[str, bytes] = {}
_enrolled_lock = threading.Lock()
_loaded = False


def load_enrolled() -> int:
    """Read every data/enrolled/<user_id>.(jpg|jpeg|png) once. Returns count."""
    global _loaded
    refs: dict[str, bytes] = {}
    d = config.ENROLL_DIR
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and USER_ID_RE.match(p.stem):
                refs.setdefault(p.stem, p.read_bytes())
    with _enrolled_lock:
        _ENROLLED.clear()
        _ENROLLED.update(refs)
        _loaded = True
    log.info("loaded %d enrolled reference(s) from %s", len(refs), d)
    return len(refs)


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
    try:
        resp = get_client().compare_faces(
            SourceImage={"Bytes": ref},
            TargetImage={"Bytes": frame},
            SimilarityThreshold=0,  # get the raw score; thresholds applied here
        )
        return out(*classify(resp))
    except Exception as e:  # no creds, timeout, no face in source, throttling...
        log.warning("compare_faces failed: %s", type(e).__name__)
        return out("UNKNOWN", None, f"error:{type(e).__name__}")
