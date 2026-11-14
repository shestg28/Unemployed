"""HTTP wrapper around the liveness pipeline.

Run from the repo root:  uvicorn api.main:app --port 8000
"""
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from pipeline import verify as run_verify

MAX_FRAMES = 10
MAX_FRAME_BYTES = 5 * 1024 * 1024  # Rekognition's limit for image bytes

app = FastAPI(title="HID liveness")


@app.post("/verify")
def verify(frames: list[UploadFile] = File(...), user_id: str = Form(...)) -> dict:
    # Sync endpoint: FastAPI runs it in a worker thread, so the blocking
    # Rekognition calls don't stall the event loop.
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise HTTPException(400, f"send 1-{MAX_FRAMES} frames")
    data = [f.file.read() for f in frames]
    if any(not b or len(b) > MAX_FRAME_BYTES for b in data):
        raise HTTPException(400, "each frame must be a non-empty image under 5 MB")
    try:
        return run_verify(data, user_id)
    finally:
        data.clear()  # kiosk keeps nothing
