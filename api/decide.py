"""Decision engine: a pure function from signals to (decision, reason, next_action).

The only path to ALLOW is an explicit whitelist at the end of each phase.
Anything missing, UNKNOWN, UNAVAILABLE, late or unrecognised falls through
to REQUEST_VERIFICATION. "Nothing bad found" is never a reason to ALLOW.
Pixel-difference motion and spoof labels are not inputs here at all.

signals = {
  "quality":   {"ok": bool|None, "fail_reason": str|None, "continuity_ok": bool|None} | None,
  "passive":   {"status": "LIVE"|"SPOOF"|"UNCERTAIN"|"UNAVAILABLE", "score": float|None} | None,
  "identity":  {"status": "MATCH"|"MISMATCH"|"UNKNOWN", "similarity": float|None} | None,
               # None = no result arrived before the deadline
  "challenge": None (first pass) |
               {"status": "PASS"|"FAIL"|"UNCERTAIN"|"UNAVAILABLE",
                "passive": {"status", "score"} | None, "timed_out": bool,
                "identity": {"status", "similarity"} | None},
               # challenge.identity = CompareFaces re-run on a good challenge
               # frame. In the challenge phase it REPLACES top-level identity.
  "passive_allow_enabled": bool,
  "schedule":  {"status": "PERMITTED"|"PROHIBITED"|"APPROVAL_REQUIRED"|"UNKNOWN",
                "policy_version": str|None} | None,   # evaluated at decision time
  "mode":      "ONLINE"|"OFFLINE",                     # anything else = OFFLINE
}

Order: SPOOF / ID_MISMATCH -> DENY; schedule PROHIBITED -> DENY (even with
perfect biometrics); OFFLINE -> STAFF_VERIFY (never an automatic ALLOW);
biometric result; a biometric ALLOW still needs schedule PERMITTED, else
APPROVAL_REQUIRED/UNKNOWN -> STAFF_VERIFY.
"""
from typing import Any

ALLOW, REQUEST, DENY = "ALLOW", "REQUEST_VERIFICATION", "DENY"

# quality.fail_reason (from pipeline.quality) -> (reason_code, next_action)
_QUALITY_FAIL = {
    "TOO_SMALL": ("QUALITY_TOO_SMALL", "MOVE_CLOSER"),
    "QUALITY_TOO_SMALL": ("QUALITY_TOO_SMALL", "MOVE_CLOSER"),
    "BLUR": ("QUALITY_BLUR", "HOLD_STILL"),
    "QUALITY_BLUR": ("QUALITY_BLUR", "HOLD_STILL"),
    "DARK": ("QUALITY_DARK", "IMPROVE_LIGHT"),
    "QUALITY_DARK": ("QUALITY_DARK", "IMPROVE_LIGHT"),
    "MULTI_FACE": ("MULTI_FACE", "RETRY"),
    "NO_FACE": ("NO_FACE", "MOVE_CLOSER"),
}

Decision = tuple[str, str, str]


def _status(sig: Any) -> str | None:
    return sig.get("status") if isinstance(sig, dict) else None


def _quality_ok(q: Any) -> bool:
    return isinstance(q, dict) and q.get("ok") is True


def _continuity_ok(q: Any) -> bool:
    return isinstance(q, dict) and q.get("continuity_ok") is True


def _quality_problem(q: Any) -> Decision | None:
    """A specific, user-fixable quality failure, or None if not one."""
    if not isinstance(q, dict):
        return None
    if q.get("ok") is False:
        reason, action = _QUALITY_FAIL.get(
            str(q.get("fail_reason") or "").upper(), ("QUALITY_BLUR", "RETRY"))
        return REQUEST, reason, action
    if q.get("ok") is True and q.get("continuity_ok") is False:
        return REQUEST, "TRACKING_LOST", "HOLD_STILL"
    return None


def _deny(signals: dict) -> Decision | None:
    """Hard negatives. Checked first in every phase; nothing overrides them."""
    if _status(signals.get("passive")) == "SPOOF":
        return DENY, "SPOOF_PASSIVE", "NONE"
    ch = signals.get("challenge")
    if isinstance(ch, dict) and _status(ch.get("passive")) == "SPOOF":
        return DENY, "SPOOF_PASSIVE", "NONE"
    # Identity in force: the challenge-frame result once a challenge ran.
    ident = ch.get("identity") if isinstance(ch, dict) else signals.get("identity")
    if _status(ident) == "MISMATCH" and _quality_ok(signals.get("quality")):
        return DENY, "ID_MISMATCH", "NONE"
    return None


def _first_pass(signals: dict) -> Decision:
    q = signals.get("quality")
    ident = signals.get("identity")
    passive = _status(signals.get("passive"))

    problem = _quality_problem(q)
    if problem:
        return problem
    if ident is None:
        return REQUEST, "TIMEOUT", "RETRY"
    if _status(ident) != "MATCH":
        return REQUEST, "ID_UNAVAILABLE", "RETRY"
    if passive == "UNCERTAIN":
        return REQUEST, "LIVENESS_UNCERTAIN", "CHALLENGE"
    if passive != "LIVE":  # UNAVAILABLE, missing, or unrecognised
        return REQUEST, "LIVENESS_UNAVAILABLE", "RETRY"
    if not (_quality_ok(q) and _continuity_ok(q)):  # quality UNAVAILABLE
        return REQUEST, "MANUAL_REVIEW", "RETRY"
    if signals.get("passive_allow_enabled") is not True:
        return REQUEST, "LIVENESS_UNCERTAIN", "CHALLENGE"
    # Whitelist: quality OK, continuity OK, MATCH, LIVE, flag on.
    return ALLOW, "OK_LIVE_MATCH", "NONE"


def _after_challenge(signals: dict) -> Decision:
    """One challenge per attempt: anything short of a clean pass -> RECEPTION."""
    ch = signals["challenge"]
    q = signals.get("quality")
    if ch.get("timed_out") is True:
        return REQUEST, "TIMEOUT", "RECEPTION"
    if _status(ch) == "FAIL":
        return REQUEST, "CHALLENGE_FAILED", "RECEPTION"
    if _status(ch.get("identity")) != "MATCH":  # UNKNOWN / missing
        return REQUEST, "ID_UNAVAILABLE", "RECEPTION"
    if (_status(ch) == "PASS"
            and _status(ch.get("passive")) == "LIVE"
            and _quality_ok(q) and _continuity_ok(q)):
        return ALLOW, "OK_LIVE_MATCH", "NONE"
    return REQUEST, "MANUAL_REVIEW", "RECEPTION"


def decide(signals: dict) -> Decision:
    """Pure: no I/O, no clock, no config reads. Same input -> same output."""
    if not isinstance(signals, dict):
        return REQUEST, "MANUAL_REVIEW", "RETRY"
    denied = _deny(signals)
    if denied:
        return denied
    sched = _status(signals.get("schedule"))
    if sched == "PROHIBITED":
        return DENY, "SCHEDULE_DENIED", "NONE"
    if signals.get("mode") != "ONLINE":
        return REQUEST, "OFFLINE_STAFF_REQUIRED", "STAFF_VERIFY"
    if signals.get("challenge") is not None:
        if not isinstance(signals["challenge"], dict):
            return REQUEST, "MANUAL_REVIEW", "RECEPTION"
        bio = _after_challenge(signals)
    else:
        bio = _first_pass(signals)
    if bio[0] != ALLOW:
        return bio
    if sched == "PERMITTED":
        return bio
    if sched == "APPROVAL_REQUIRED":
        return REQUEST, "SCHEDULE_APPROVAL_REQUIRED", "STAFF_VERIFY"
    return REQUEST, "SCHEDULE_UNKNOWN", "STAFF_VERIFY"


MESSAGES = {
    "OK_LIVE_MATCH": "Welcome.",
    "SPOOF_PASSIVE": "Entry denied.",
    "ID_MISMATCH": "Entry denied.",
    "ID_UNAVAILABLE": "We couldn't confirm who you are. Please try again.",
    "LIVENESS_UNCERTAIN": "One more quick check, please.",
    "LIVENESS_UNAVAILABLE": "Liveness check unavailable. Please try again.",
    "QUALITY_TOO_SMALL": "Please move closer.",
    "QUALITY_BLUR": "Please hold still.",
    "QUALITY_DARK": "Please find better light.",
    "MULTI_FACE": "Only one person in frame, please.",
    "NO_FACE": "We can't see your face. Please look at the camera.",
    "TRACKING_LOST": "Please stay in frame and hold still.",
    "TIMEOUT": "That took too long. Please try again.",
    "CHALLENGE_FAILED": "Please see reception.",
    "MANUAL_REVIEW": "Please see reception.",
    "SCHEDULE_DENIED": "Entry not permitted at this time.",
    "SCHEDULE_APPROVAL_REQUIRED": "Staff approval needed for this time.",
    "SCHEDULE_UNKNOWN": "Staff will verify your access.",
    "OFFLINE_STAFF_REQUIRED": "Kiosk offline. Staff will verify your ID.",
    "STAFF_VERIFIED": "Welcome. Verified by staff.",
    "STAFF_REJECTED": "Entry denied by staff.",
}


def message_for(reason: str, next_action: str) -> str:
    if next_action == "RECEPTION":
        return "Please see reception."
    if next_action == "STAFF_VERIFY" and reason not in MESSAGES:
        return "Please wait for staff to verify your ID."
    return MESSAGES.get(reason, "Please try again.")
