"""Silent-Face-Anti-Spoofing (minivision) wrapper, reproducing its test.py.

Reproduces https://github.com/minivision-ai/Silent-Face-Anti-Spoofing test.py
exactly, except that both models are loaded ONCE (test.py reloads weights on
every predict call):

  1. image = BGR uint8 as returned by cv2.imread / cv2.imdecode (no RGB swap)
  2. bbox  = its RetinaFace caffe detector (Detection.get_bbox)
  3. for each model in resources/anti_spoof_models:
       crop with its CropImage at the model's scale (2.7 / 4.0) to 80x80,
       its own transform (src.data_io.transform.ToTensor: HWC->CHW float,
       NOT divided by 255 -- upstream "modify by zkx"), softmax
  4. prediction = sum of the per-model softmax vectors (shape 3)
  5. label = argmax(prediction); class index 1 == real face
     (test.py: `if label == 1: "Real Face"`). Classes 0 and 2 are spoof.

Live score used here = prediction[1] / n_models (in [0, 1]); this is the
same number test.py prints as "RealFace Score" when label == 1.
It is a model score, NOT a probability and NOT a "% secure".

Upstream code lives in pipeline/third_party/Silent-Face-Anti-Spoofing
(run `python -m pipeline.fetch_third_party`). See pipeline/MODELS.md.
"""
from __future__ import annotations

import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

SF_DIR = Path(os.environ.get(
    "SILENTFACE_DIR",
    Path(__file__).resolve().parent / "third_party" / "Silent-Face-Anti-Spoofing",
))
MODEL_DIR = SF_DIR / "resources" / "anti_spoof_models"
REAL_CLASS = 1  # verified from test.py, see module docstring and MODELS.md


class SilentFaceUnavailable(RuntimeError):
    pass


class FaceDetector:
    """Upstream RetinaFace caffe detector (needs only OpenCV 4.x, not torch)."""

    def __init__(self, sf_dir: Path = SF_DIR):
        det_dir = sf_dir / "resources" / "detection_model"
        if not (det_dir / "deploy.prototxt").is_file():
            raise SilentFaceUnavailable(
                f"detector not found at {det_dir}; run python -m pipeline.fetch_third_party")
        # same files and parameters as upstream Detection.__init__
        self._det = cv2.dnn.readNetFromCaffe(
            str(det_dir / "deploy.prototxt"), str(det_dir / "Widerface-RetinaFace.caffemodel"))
        self.detector_confidence = 0.6
        self._lock = threading.Lock()

    # -- detection ----------------------------------------------------------
    def _detect_raw(self, img: np.ndarray) -> np.ndarray:
        """Upstream get_bbox preprocessing; returns raw rows [_, _, conf, l, t, r, b] (normalised)."""
        height, width = img.shape[0], img.shape[1]
        aspect_ratio = width / height
        if img.shape[1] * img.shape[0] >= 192 * 192:
            img = cv2.resize(img, (int(192 * np.sqrt(aspect_ratio)), int(192 / np.sqrt(aspect_ratio))),
                             interpolation=cv2.INTER_LINEAR)
        blob = cv2.dnn.blobFromImage(img, 1, mean=(104, 117, 123))
        with self._lock:
            self._det.setInput(blob, "data")
            out = self._det.forward("detection_out")
        return out.reshape(-1, 7)

    def get_bbox(self, img: np.ndarray) -> list[int]:
        """Exactly upstream Detection.get_bbox: the highest-confidence box, no threshold."""
        out = self._detect_raw(img)
        h, w = img.shape[:2]
        i = int(np.argmax(out[:, 2]))
        l, t, r, b = out[i, 3] * w, out[i, 4] * h, out[i, 5] * w, out[i, 6] * h
        return [int(l), int(t), int(r - l + 1), int(b - t + 1)]

    def detect_faces(self, img: np.ndarray, min_conf: float | None = None) -> list[dict]:
        """All boxes >= min_conf (default upstream 0.6), sorted by confidence. For quality checks."""
        thr = self.detector_confidence if min_conf is None else min_conf
        out = self._detect_raw(img)
        h, w = img.shape[:2]
        faces = []
        for row in out[out[:, 2] >= thr]:
            l, t = max(0.0, row[3] * w), max(0.0, row[4] * h)
            r, b = min(w - 1.0, row[5] * w), min(h - 1.0, row[6] * h)
            if r - l < 2 or b - t < 2:
                continue
            faces.append({"bbox": [int(l), int(t), int(r - l + 1), int(b - t + 1)],
                          "conf": float(row[2])})
        faces.sort(key=lambda f: -f["conf"])
        return faces


class SilentFace:
    """Loads detector + both anti-spoof models once. Thread-safe predict."""

    def __init__(self, sf_dir: Path = SF_DIR):
        if not (sf_dir / "src" / "anti_spoof_predict.py").is_file():
            raise SilentFaceUnavailable(
                f"Silent-Face not found at {sf_dir}; run python -m pipeline.fetch_third_party")
        if str(sf_dir) not in sys.path:
            sys.path.insert(0, str(sf_dir))
        import torch
        import torch.nn.functional as F
        from src.anti_spoof_predict import MODEL_MAPPING  # upstream
        from src.data_io import transform as trans  # upstream
        from src.generate_patches import CropImage  # upstream
        from src.utility import get_kernel, parse_model_name  # upstream

        self._torch, self._F = torch, F
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        self._transform = trans.Compose([trans.ToTensor()])
        self._cropper = CropImage()
        self._lock = threading.Lock()

        self.detector = get_detector()

        self.models = []  # (name, model, h, w, scale)
        model_dir = sf_dir / "resources" / "anti_spoof_models"
        for name in sorted(os.listdir(model_dir)):  # upstream uses os.listdir order; sum is order-free
            h, w, model_type, scale = parse_model_name(name)
            model = MODEL_MAPPING[model_type](conv6_kernel=get_kernel(h, w))
            state = torch.load(model_dir / name, map_location="cpu")
            first = next(iter(state))
            if first.find("module.") >= 0:  # same key fix-up as upstream _load_model
                state = OrderedDict((k[7:], v) for k, v in state.items())
            model.load_state_dict(state)
            model.eval()
            self.models.append((name, model, h, w, scale))
        if not self.models:
            raise SilentFaceUnavailable(f"no models in {model_dir}")

    def get_bbox(self, img: np.ndarray) -> list[int]:
        return self.detector.get_bbox(img)

    def detect_faces(self, img: np.ndarray, min_conf: float | None = None) -> list[dict]:
        return self.detector.detect_faces(img, min_conf)

    # -- anti-spoof -----------------------------------------------------------
    def predict(self, img: np.ndarray, bbox: list[int] | None = None) -> dict:
        """-> {live_score, label, prediction(sum of softmax), bbox}. img is BGR uint8."""
        if bbox is None:
            bbox = self.get_bbox(img)
        prediction = np.zeros((1, 3))
        for _name, model, h, w, scale in self.models:
            param = {"org_img": img, "bbox": bbox, "scale": scale,
                     "out_w": w, "out_h": h, "crop": True}
            if scale is None:
                param["crop"] = False
            patch = self._cropper.crop(**param)
            x = self._transform(patch).unsqueeze(0)
            with self._torch.no_grad():
                prediction += self._F.softmax(model.forward(x), dim=1).cpu().numpy()
        label = int(np.argmax(prediction))
        return {
            "live_score": float(prediction[0][REAL_CLASS] / len(self.models)),
            "label": label,
            "is_real_label": label == REAL_CLASS,
            "prediction": prediction[0].tolist(),
            "bbox": bbox,
        }


_instance: SilentFace | None = None
_instance_err: Exception | None = None
_init_lock = threading.RLock()  # get() -> SilentFace() -> get_detector() re-enters


def get() -> SilentFace:
    """Process-wide singleton; raises SilentFaceUnavailable if it cannot load."""
    global _instance, _instance_err
    if _instance is None and _instance_err is None:
        with _init_lock:
            if _instance is None and _instance_err is None:
                try:
                    _instance = SilentFace()
                except Exception as e:  # missing clone, torch, weights...
                    _instance_err = e
    if _instance is None:
        raise SilentFaceUnavailable(str(_instance_err))
    return _instance


_detector: FaceDetector | None = None
_detector_err: Exception | None = None


def get_detector() -> FaceDetector:
    """Process-wide detector singleton; raises SilentFaceUnavailable if it cannot load."""
    global _detector, _detector_err
    if _detector is None and _detector_err is None:
        with _init_lock:
            if _detector is None and _detector_err is None:
                try:
                    _detector = FaceDetector()
                except Exception as e:
                    _detector_err = e
    if _detector is None:
        raise SilentFaceUnavailable(str(_detector_err))
    return _detector
