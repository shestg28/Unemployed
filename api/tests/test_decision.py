"""The three required safety tests for the v2 decision path."""
import itertools

import pytest
from fastapi.testclient import TestClient

import pipeline
from api import config, identity, signals
from api.decide import decide
from api.main import app
from api.store import STORE

GOOD_Q = {"ok": True, "fail_reason": None, "continuity_ok": True}
LIVE = {"status": "LIVE", "score": 0.97}
MATCH = {"status": "MATCH", "similarity": 98.0}
FRAME = b"\xff\xd8not-really-a-jpeg"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ATTEMPT_LOG_PATH", str(tmp_path / "attempts.jsonl"))
    monkeypatch.setattr(config, "ATTEMPT_DEADLINE_MS", 150)
    monkeypatch.setattr(config, "PASSIVE_ALLOW_ENABLED", True)
    # Pipeline reports a perfect, live face: so the ONLY thing that can
    # stop an ALLOW below is the identity result and its timing.
    monkeypatch.setattr(pipeline, "quality", lambda f: dict(GOOD_Q, per_frame=[]), raising=False)
    monkeypatch.setattr(pipeline, "passive_liveness", lambda f: dict(LIVE, per_frame=[]), raising=False)
    monkeypatch.setattr(identity, "compare", lambda uid, fr: {
        "identity": "MATCH", "similarity": 98.0, "ms": 5, "note": "fake"})
    STORE.clear()
    yield TestClient(app)
    STORE.clear()


def _start(c, user="u1"):
    r = c.post("/attempt/start", json={"user_id": user, "consent": True})
    assert r.status_code == 200
    return r.json()["attempt_id"]


def _liveness(c, aid):
    return c.post(f"/attempt/{aid}/liveness",
                  files=[("frames", ("f.jpg", FRAME, "image/jpeg"))] * 3)


def _identity(c, aid):
    return c.post(f"/attempt/{aid}/identity", files={"frame": ("f.jpg", FRAME, "image/jpeg")})


def test_a_missing_unknown_or_unavailable_signal_never_allows():
    qualities = [GOOD_Q, None, {"ok": None, "continuity_ok": None},
                 {"ok": False, "fail_reason": "BLUR", "continuity_ok": True},
                 {"ok": True, "continuity_ok": False}, {"ok": True, "continuity_ok": None}]
    passives = [LIVE, None, {"status": "UNAVAILABLE", "score": None},
                {"status": "UNCERTAIN", "score": 0.5}, {"status": "GARBAGE"}]
    identities = [MATCH, None, {"status": "UNKNOWN", "similarity": None},
                  {"status": "UNKNOWN", "similarity": 70.0}]
    flags = [True, False, None]
    combos = 0
    for q, p, i, flag in itertools.product(qualities, passives, identities, flags):
        d = decide({"quality": q, "passive": p, "identity": i, "challenge": None,
                    "passive_allow_enabled": flag})
        all_good = q is GOOD_Q and p is LIVE and i is MATCH and flag is True
        assert (d[0] == "ALLOW") == all_good, (q, p, i, flag, d)
        combos += 1
    assert combos == 6 * 5 * 4 * 3

    # Challenge phase: same rule.
    for ch_status, ch_passive in itertools.product(
            ["PASS", "FAIL", "UNCERTAIN", "UNAVAILABLE", None], [LIVE, None, {"status": "UNAVAILABLE"}]):
        d = decide({"quality": GOOD_Q, "passive": {"status": "UNCERTAIN"}, "identity": MATCH,
                    "challenge": {"status": ch_status, "passive": ch_passive, "timed_out": False,
                                  "identity": MATCH},
                    "passive_allow_enabled": True})
        assert (d[0] == "ALLOW") == (ch_status == "PASS" and ch_passive is LIVE), d

    # Challenge phase uses the challenge-frame identity, not the first-pass one
    # (which may have been late/missing): MATCH -> ALLOW, UNKNOWN/missing ->
    # RECEPTION, MISMATCH on good quality -> DENY.
    def _after(ch_ident):
        return decide({"quality": GOOD_Q, "passive": {"status": "UNCERTAIN"}, "identity": None,
                       "passive_allow_enabled": False,
                       "challenge": {"status": "PASS", "passive": LIVE, "timed_out": False,
                                     "identity": ch_ident}})
    assert [_after(i) for i in (MATCH, {"status": "UNKNOWN"}, None,
                                {"status": "MISMATCH", "similarity": 10.0})] == [
        ("ALLOW", "OK_LIVE_MATCH", "NONE"),
        ("REQUEST_VERIFICATION", "ID_UNAVAILABLE", "RECEPTION"),
        ("REQUEST_VERIFICATION", "ID_UNAVAILABLE", "RECEPTION"),
        ("DENY", "ID_MISMATCH", "NONE")]

    # The real STUBs (pipeline has no v2 functions yet) can never produce ALLOW.
    d = decide({"quality": signals._stub_quality([]), "passive": signals._stub_passive([]),
                "identity": MATCH, "challenge": None, "passive_allow_enabled": True})
    assert d[0] != "ALLOW"
    ch = signals._stub_challenge([], [], 0, [])
    d = decide({"quality": GOOD_Q, "passive": LIVE, "identity": MATCH,
                "challenge": {"status": ch["status"], "passive": ch["passive"], "timed_out": False,
                              "identity": MATCH},
                "passive_allow_enabled": True})
    assert d == ("REQUEST_VERIFICATION", "MANUAL_REVIEW", "RECEPTION")


def test_b_late_result_is_ignored_and_attempts_are_isolated(client):
    a, b = _start(client), _start(client)

    # A: identity arrives on time -> ALLOW. B gets nothing from A's result.
    assert _identity(client, a).json()["identity"] == "MATCH"
    assert STORE.get(a).identity is not None
    assert STORE.get(b).identity is None

    ra = _liveness(client, a).json()
    assert ra["decision"] == "ALLOW" and ra["attempt_id"] == a

    # B: no identity before the deadline -> not ALLOW, even though quality,
    # passive and (A's) identity were all good.
    rb = _liveness(client, b).json()
    assert (rb["decision"], rb["reason_code"]) == ("REQUEST_VERIFICATION", "TIMEOUT")
    assert rb["attempt_id"] == b

    # A MATCH for B that arrives late is logged, stored aside, never used.
    assert _identity(client, b).status_code == 200
    assert STORE.get(b).identity is None and len(STORE.get(b).identity_late) == 1
    again = _liveness(client, b).json()
    assert again == rb  # first-pass decision is FINAL

    # A's decision is untouched by anything that happened to B.
    assert STORE.get(a).decision == ra

    # Unknown attempt ids are rejected outright.
    assert _identity(client, "does-not-exist").status_code == 404
    assert _liveness(client, "does-not-exist").status_code == 404

    # Exactly one log line per decision (A, B), none for the replay/late result.
    lines = open(config.ATTEMPT_LOG_PATH, encoding="utf-8").read().splitlines()
    assert len(lines) == 2


def test_c_passive_spoof_then_passed_challenge_is_deny(client, monkeypatch):
    d = decide({"quality": GOOD_Q, "passive": {"status": "SPOOF", "score": 0.99},
                "identity": MATCH, "passive_allow_enabled": True,
                "challenge": {"status": "PASS", "passive": LIVE, "timed_out": False}})
    assert d == ("DENY", "SPOOF_PASSIVE", "NONE")

    # Through the API: a SPOOF first pass is final and cannot be stepped up.
    monkeypatch.setattr(pipeline, "passive_liveness",
                        lambda f: {"status": "SPOOF", "score": 0.99, "per_frame": []}, raising=False)
    aid = _start(client)
    _identity(client, aid)
    assert _liveness(client, aid).json()["decision"] == "DENY"
    assert client.post(f"/attempt/{aid}/challenge/start").status_code == 409
