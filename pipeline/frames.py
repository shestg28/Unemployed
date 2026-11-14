"""Frame decoding + a small per-frame detection cache shared by quality and passive."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import cv2
import numpy as np


def decode(frame) -> np.ndarray | None:
    """bytes (jpeg/png) or BGR ndarray -> BGR uint8 ndarray, None if undecodable.

    Decoded in memory only; nothing is written to disk.
    """
    if isinstance(frame, np.ndarray):
        return frame
    try:
        buf = np.frombuffer(frame, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


_cache: "OrderedDict[str, list]" = OrderedDict()
_lock = threading.Lock()
_CACHE_MAX = 64


def faces_for(frame, img: np.ndarray, detector) -> list[dict]:
    """detector.detect_faces(img), memoised by frame bytes so quality() and
    passive_liveness() don't detect the same frame twice."""
    key = hashlib.sha1(frame).hexdigest() if isinstance(frame, (bytes, bytearray)) else None
    if key is not None:
        with _lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key]
    faces = detector.detect_faces(img)
    if key is not None:
        with _lock:
            _cache[key] = faces
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    return faces
