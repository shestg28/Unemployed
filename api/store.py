"""In-memory attempt store. Nothing here is persisted; no images are kept.

Each attempt has its own lock. A result is only ever written to the attempt
whose id it was posted to; unknown or evicted ids are rejected (-> 404).
Decisions are write-once: set only while still None.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import config


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Attempt:
    attempt_id: str
    user_id: str
    server_t0_ms: int
    deadline_ms: int
    t0_mono: float
    deadline_mono: float
    scenario: str | None = None
    first_action: str | None = None     # quick 1-action challenge shown at the tap
    identity: dict | None = None        # accepted before deadline/decision
    identity_late: list = field(default_factory=list)  # logged, never used
    passive: dict | None = None
    quality: dict | None = None         # summary stats, no pixels
    continuity_ok: bool | None = None
    decision: dict | None = None        # first-pass response, write-once
    challenge: dict | None = None       # {challenge_id, actions, started_mono}
    challenge_decision: dict | None = None  # write-once
    challenge_passive: dict | None = None
    staff_decision: dict | None = None      # write-once
    pin_failures: int = 0
    stage_ms: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    identity_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def past_deadline(self) -> bool:
        return time.monotonic() > self.deadline_mono

    def set_decision(self, payload: dict) -> dict:
        """Write-once. Caller holds self.lock. Returns the decision that stands."""
        if self.decision is None:
            self.decision = payload
        return self.decision

    def set_challenge_decision(self, payload: dict) -> dict:
        if self.challenge_decision is None:
            self.challenge_decision = payload
        return self.challenge_decision


class AttemptStore:
    def __init__(self) -> None:
        self._attempts: dict[str, Attempt] = {}
        self._lock = threading.Lock()

    def _evict(self) -> None:
        cutoff = time.monotonic() - config.ATTEMPT_TTL_S
        for aid in [a for a, at in self._attempts.items() if at.t0_mono < cutoff]:
            del self._attempts[aid]

    def create(self, user_id: str, deadline_ms: int | None = None) -> Attempt:
        window = config.ATTEMPT_DEADLINE_MS if deadline_ms is None else deadline_ms
        t0, mono = now_ms(), time.monotonic()
        at = Attempt(
            attempt_id=str(uuid.uuid4()), user_id=user_id,
            server_t0_ms=t0, deadline_ms=t0 + window,
            t0_mono=mono, deadline_mono=mono + window / 1000.0,
        )
        with self._lock:
            self._evict()
            self._attempts[at.attempt_id] = at
        return at

    def get(self, attempt_id: str) -> Attempt | None:
        with self._lock:
            self._evict()
            return self._attempts.get(attempt_id)

    def record_identity(self, attempt_id: str, result: dict) -> str:
        """-> 'accepted' | 'late' | 'duplicate' | 'unknown_attempt'.

        Late = arrived after the deadline or after the first-pass decision.
        Late results are kept for the log only and never feed a decision.
        """
        at = self.get(attempt_id)
        if at is None:
            return "unknown_attempt"
        with at.lock:
            if at.decision is not None or at.past_deadline():
                at.identity_late.append(result)
                return "late"
            if at.identity is not None:
                return "duplicate"
            at.identity = result
            at.identity_event.set()
            return "accepted"

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._attempts)


STORE = AttemptStore()


def identity_snapshot(at: Attempt) -> dict[str, Any] | None:
    """Caller holds at.lock. Only the on-time identity result is visible."""
    return dict(at.identity) if at.identity is not None else None
