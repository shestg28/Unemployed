"""Fetch third-party models into pipeline/third_party: Silent-Face (pinned commit)
and the MediaPipe face_landmarker.task.

    python -m pipeline.fetch_third_party

The clone (code + weights + detector) is gitignored; MODELS.md records the
commit and license.

Windows: upstream saved_logs/ contains a directory whose name ends in a space,
which Windows git refuses to check out (even with sparse checkout). So we make a
bare clone and export only what we need: each directory with
`git archive <commit>:<dir>` (extracted by Python's tarfile), each file with
`git cat-file -p <commit>:<file>`.
"""
import io
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing"
COMMIT = "b6d5f04ad78778917853b25c778acef6d5626d15"
THIRD = Path(__file__).resolve().parent / "third_party"
DEST = THIRD / "Silent-Face-Anti-Spoofing"
SRC_REPO = THIRD / "Silent-Face-Anti-Spoofing.git"
KEEP_DIRS = ["src", "resources", "images", "datasets"]
KEEP_FILES = ["LICENSE", "README.md", "README_EN.md", "requirements.txt", "test.py", "train.py"]
STAMP = DEST / ".pinned_commit"
LANDMARKER_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                  "face_landmarker/float16/1/face_landmarker.task")
LANDMARKER = THIRD / "face_landmarker.task"


def main() -> int:
    THIRD.mkdir(parents=True, exist_ok=True)
    if STAMP.is_file() and STAMP.read_text().strip() == COMMIT:
        print(f"Silent-Face already at {DEST} @ {COMMIT}")
    else:
        if not SRC_REPO.is_dir():
            subprocess.check_call(["git", "clone", "--bare", REPO, str(SRC_REPO)])
        git = ["git", "--git-dir", str(SRC_REPO)]
        for d in KEEP_DIRS:
            tar_bytes = subprocess.check_output(
                git + ["archive", "--format=tar", f"--prefix={d}/", f"{COMMIT}:{d}"])
            with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
                try:
                    tf.extractall(DEST, filter="data")
                except TypeError:  # Python without tarfile filters
                    tf.extractall(DEST)
        for f in KEEP_FILES:
            (DEST / f).write_bytes(subprocess.check_output(git + ["cat-file", "-p", f"{COMMIT}:{f}"]))
        STAMP.write_text(COMMIT + "\n")
        print(f"Silent-Face exported to {DEST} @ {COMMIT}")
    if not LANDMARKER.is_file():
        import urllib.request
        urllib.request.urlretrieve(LANDMARKER_URL, LANDMARKER)
    print(f"MediaPipe face landmarker at {LANDMARKER} ({LANDMARKER.stat().st_size} bytes)")
    ok = (DEST / "resources" / "anti_spoof_models" / "2.7_80x80_MiniFASNetV2.pth").is_file() and \
        (DEST / "resources" / "detection_model" / "deploy.prototxt").is_file()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
