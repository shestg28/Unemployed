"""ONLINE / OFFLINE mode. Part B: FORCE_OFFLINE only; health check added in Part C."""
import os


def current() -> str:
    if os.environ.get("FORCE_OFFLINE", "").strip() in {"1", "true", "yes", "on"}:
        return "OFFLINE"
    return "ONLINE"
