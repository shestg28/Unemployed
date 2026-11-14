"""Run a local browser webcam challenge and retain labeled stills under data/gate."""
import base64
import json
import random
import sys
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import challenge_check, warmup, warmup_challenge

labels = {
    "SMILE": "Smile",
    "OPEN_MOUTH": "Open your mouth",
    "TURN_LEFT": "Turn to your left",
    "TURN_RIGHT": "Turn to your right",
}
TRIAL_LOCK = threading.Lock()
SCENARIOS = ('print', 'phone', 'replay', 'mask_cutout', 'mask_no_cutout', 'real')
GATE = Path(__file__).resolve().parent.parent / 'data' / 'gate'
page = Path(__file__).with_suffix(".html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def reply(self, data, kind="application/json"):
        if kind == "application/json":
            data = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.reply(page, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        if self.path == "/actions":
            self.server.completed = False
            self.server.actions = random.sample(list(labels), 2)
            self.reply([labels[action] for action in self.server.actions])
            return
        size = int(self.headers.get("Content-Length", 0))
        if self.path != "/check" or not 0 < size < 8_000_000 or not self.server.actions:
            self.send_error(400)
            return
        try:
            data = json.loads(self.rfile.read(size))
            frames = [base64.b64decode(frame, validate=True) for frame in data["frames"]]
            stamps = data["times"]
            prompt = data["prompt"]
            if len(frames) != len(stamps) or not 3 <= len(frames) <= 60:
                raise ValueError("invalid capture")
            scenario = data["scenario"]
            if scenario not in SCENARIOS:
                raise ValueError("unknown scenario")
            capture_id = uuid.uuid4().hex
            folder = GATE / scenario
            folder.mkdir(parents=True, exist_ok=True)
            for index, frame in enumerate(frames):
                with (folder / f"{capture_id}_{index:03}.jpg").open("xb") as saved:
                    saved.write(frame)
            result = challenge_check(frames, stamps, prompt, self.server.actions)
            summary = {
                "scenario": scenario, "capture_id": capture_id, "frames": len(frames),
                "baseline_frames": sum(t < prompt for t in stamps),
                "status": result["status"],
                "reason": result["reason"],
                "actions_completed": sum(bool(a["done"]) for a in result["per_action"]),
                "actions_prompted": len(self.server.actions),
                "tracking": result.get("tracking"),
                "passive_status": (result.get("passive") or {}).get("status"),
                "ms": result["ms"],
            }
            with TRIAL_LOCK:
                with (GATE / "challenge_trials.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(summary) + "\n")
            print(json.dumps(summary), flush=True)
            self.server.actions = []
            self.server.completed = False
            self.reply(summary)
        except (ValueError, TypeError, KeyError):
            self.send_error(400)


if __name__ == "__main__":
    warmup()
    warmup_challenge()
    with ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler) as server:
        server.timeout = 0.5
        server.actions = []
        server.completed = False
        print(f"READY http://127.0.0.1:{server.server_port}", flush=True)
        while not server.completed:
            server.handle_request()
