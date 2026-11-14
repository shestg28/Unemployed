"""Settings and tunable thresholds for the liveness pipeline.

Credentials come from the environment / repo-root .env only (CONTRACT.md).
Nothing here is a secret.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, never overrides real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


_load_dotenv(REPO_ROOT / ".env")

# Region comes from the environment / .env (sandbox is us-east-1).
# ap-south-1 is only a last-resort fallback when nothing is set.
AWS_REGION = (os.environ.get("AWS_DEFAULT_REGION")
              or os.environ.get("AWS_REGION")
              or "ap-south-1")

# Enrolled reference photos: <ENROLL_DIR>/<user_id>.jpg|.jpeg|.png
ENROLL_DIR = Path(os.environ.get("ENROLL_DIR", REPO_ROOT / "data" / "enrolled"))

# --- Timing -----------------------------------------------------------------
BUDGET_MS = 2000
# How long we wait for the parallel Rekognition calls before giving up.
REKOGNITION_DEADLINE_S = 1.7
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 1.6

# --- Contract-fixed ---------------------------------------------------------
SIMILARITY_THRESHOLD = 99  # CONTRACT.md hard rule

# --- Spoof labels (detect_labels on the full frame) -------------------------
SCREEN_LABELS = {"Mobile Phone", "Screen", "Electronics"}
PRINT_LABELS = {"Paper", "Picture", "Poster"}
LABEL_MIN_CONFIDENCE = 70.0     # at/above: weak spoof signal -> step-up
LABEL_STRONG_CONFIDENCE = 90.0  # at/above: strong spoof signal -> DENY

# --- Face quality (detect_faces, Attributes=ALL) ----------------------------
MIN_SHARPNESS = 20.0
MIN_BRIGHTNESS = 30.0
MAX_BRIGHTNESS = 95.0
MAX_POSE_DEG = 30.0  # |yaw| and |pitch|

# --- Motion (mean abs pixel diff across the burst, 0..1) --------------------
MOTION_SIZE = (64, 64)
MIN_MOTION = 0.004  # ~1 grey level; calibrate on real kiosk captures
