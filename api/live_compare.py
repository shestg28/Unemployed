"""Live CompareFaces check (needs .env creds). Not a pytest test.

    python -m api.live_compare [user_id] [probe_path] [n]
    python -m api.live_compare akash data/akash_probe.jpg 5

Prints similarity / status / round-trip ms per call, then median and max.
Never prints credentials or image bytes.
"""
import statistics
import sys
import time
from pathlib import Path

from pipeline.liveness import get_client

from . import config, identity


def main() -> int:
    user_id = sys.argv[1] if len(sys.argv) > 1 else "akash"
    probe = Path(sys.argv[2] if len(sys.argv) > 2 else config.REPO_ROOT / "data" / "akash_probe.jpg")
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    identity.load_enrolled()
    print(f"region={get_client().meta.region_name} user={user_id} probe={probe.name} "
          f"ID_MATCH={config.ID_MATCH} ID_MISMATCH={config.ID_MISMATCH}")
    w = identity.warm_up()
    print(f"warm-up: {w}")
    frame = probe.read_bytes()
    ms = []
    for i in range(n):
        t = time.perf_counter()
        r = identity.compare(user_id, frame)
        rt = (time.perf_counter() - t) * 1000
        ms.append(rt)
        print(f"call {i + 1}: identity={r['identity']} similarity={r['similarity']} "
              f"round_trip_ms={rt:.0f} note={r['note']}")
    print(f"median_ms={statistics.median(ms):.0f} max_ms={max(ms):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
