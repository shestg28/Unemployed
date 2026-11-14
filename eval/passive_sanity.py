"""Compare the passive wrapper with the pinned Silent-Face sample runner."""
import argparse
import contextlib
import io
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import cv2
from pipeline import passive_liveness
from pipeline.silentface import SF_DIR

SAMPLES = {
    "image_T1.jpg": ("Real", "LIVE"),
    "image_F1.jpg": ("Fake", "SPOOF"),
    "image_F2.jpg": ("Fake", "SPOOF"),
}


def compare():
    original = Path.cwd()
    try:
        os.chdir(SF_DIR)
        for name, (official_label, passive_label) in SAMPLES.items():
            result = passive_liveness([Path("images/sample", name).read_bytes()])
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(cv2, "imwrite", return_value=True):
                runpy.run_path("test.py")["test"](name, "./resources/anti_spoof_models", 0)
            official = next(line for line in output.getvalue().splitlines() if "Face. Score:" in line)
            matched = f"is {official_label} Face." in official and result["status"] == passive_label
            yield name, official, result, matched
    finally:
        os.chdir(original)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    all_matched = True
    for name, official, result, matched in compare():
        print(name, official, result, "MATCH" if matched else "DIFFERENT")
        all_matched &= matched
    return 0 if all_matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
