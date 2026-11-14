"""Motion across a frame burst: simple pixel diff on small grayscale copies."""
import io

from PIL import Image, ImageChops, ImageStat

from .config import MOTION_SIZE


def _small_gray(frame: bytes) -> Image.Image:
    with Image.open(io.BytesIO(frame)) as img:
        return img.convert("L").resize(MOTION_SIZE)


def motion_score(frames: list[bytes]) -> float:
    """Mean absolute difference between consecutive frames, scaled to 0..1.

    Returns 0.0 for fewer than two frames or undecodable input.
    Frames are decoded in memory only and never written anywhere.
    """
    if len(frames) < 2:
        return 0.0
    try:
        grays = [_small_gray(f) for f in frames]
    except Exception:
        return 0.0
    diffs = [
        ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / 255.0
        for a, b in zip(grays, grays[1:])
    ]
    return round(sum(diffs) / len(diffs), 5)
