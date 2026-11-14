"""Fetch third-party models into pipeline/third_party: Silent-Face (pinned commit)
and the MediaPipe face_landmarker.task.

    python -m pipeline.fetch_third_party

The clone (code + weights + detector) is gitignored; MODELS.md records the
commit and license.
"""
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing"
COMMIT = "b6d5f04ad78778917853b25c778acef6d5626d15"
DEST = Path(__file__).resolve().parent / "third_party" / "Silent-Face-Anti-Spoofing"
LANDMARKER_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                  "face_landmarker/float16/1/face_landmarker.task")
LANDMARKER = Path(__file__).resolve().parent / "third_party" / "face_landmarker.task"


def main() -> int:
    if not (DEST / ".git").is_dir():
        DEST.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(["git", "clone", REPO, str(DEST)])
    subprocess.check_call(["git", "-C", str(DEST), "checkout", "-q", COMMIT])
    head = subprocess.check_output(["git", "-C", str(DEST), "rev-parse", "HEAD"], text=True).strip()
    print(f"Silent-Face at {DEST} @ {head}")
    if not LANDMARKER.is_file():
        import urllib.request
        urllib.request.urlretrieve(LANDMARKER_URL, LANDMARKER)
    print(f"MediaPipe face landmarker at {LANDMARKER} ({LANDMARKER.stat().st_size} bytes)")
    return 0 if head == COMMIT else 1


if __name__ == "__main__":
    sys.exit(main())
