# CONTRACT

## Problem
HID entry kiosk must decide ALLOW / REQUEST VERIFICATION / DENY
in <=2s, distinguishing a live person from a printed photo,
screen replay, or video replay.

## Demo sentence
Same face, three outcomes: in person -> ALLOW in under 2s.
On a phone -> DENY. In bad light -> REQUEST VERIFICATION.
And the kiosk keeps nothing.

## Features, in priority order (cut from the bottom)
1. Passive check + identity match -> 3 outcomes, timer on screen
2. Step-up path for REQUEST VERIFICATION
3. Results table: detection rate, FAR, FRR, mean decision time
4. Consent screen + "0 images retained" counter
5. One-line Bedrock explanation AFTER the decision (first to cut)

## The decision contract — nobody changes this without Akash
POST /verify   (multipart: frames[], user_id)

Response:
{
  "decision": "ALLOW" | "REQUEST_VERIFICATION" | "DENY",
  "confidence": 0.0-1.0,
  "decision_ms": int,
  "reason_code": "LIVE_MATCH" | "SCREEN_DETECTED" | "PRINT_DETECTED"
                 | "NO_MOTION" | "LOW_QUALITY" | "NO_MATCH",
  "signals": {
    "labels": [],
    "motion": float,
    "quality": float,
    "similarity": float
  }
}

## Hard rules
- Rekognition calls run IN PARALLEL. Never sequential. 2s budget.
- CompareFaces SimilarityThreshold = 99
- Bedrock is NEVER in the decision path. Explanation only, after.
- Credentials from .env only. Never committed.
- AWS region: ap-south-1. Sandbox via Workshop Studio.
- ML ranks; it never opens doors.

## Ownership — do not write outside your folder
| Path              | Owner                                    |
|-------------------|------------------------------------------|
| /pipeline, /api   | Siddanth Anil (Akash covers until he's in) |
| /web              | Shesh                                     |
| /tests, /data     | Siddhant Khurdiya                         |
| root, config      | Akash                                     |

## Roles
- Akash — integrator. Owns main, merges, scope calls. Covers the
  AI core until Siddanth Anil is on.
- Siddanth Anil — AI core: liveness pipeline + Rekognition fusion.
- Shesh — kiosk UI, webcam capture, the screen judges look at.
- Siddhant Khurdiya — test data, results table, demo script, slides.

## Open questions (answer before 10:30)
- [ ] Is Rekognition Face Liveness enabled in our sandbox?
- [ ] Does the 2s clock start at face-presented or capture-complete?

## Today's gates
- 10:15  Contract committed, everyone building
- 12:30  End-to-end connected with fake data, ugly is fine
- 15:30  Test results table exists with real numbers
- 17:00  CODE FREEZE. Recorded demo video on disk.
- 17:00-18:00  Three timed rehearsals

## v2 attempt API (added 14 Nov). /verify kept: same request/response shape, now routed through the decision engine.

Decisions: ALLOW | REQUEST_VERIFICATION | DENY
Reason codes: OK_LIVE_MATCH, SPOOF_PASSIVE, ID_MISMATCH, ID_UNAVAILABLE, LIVENESS_UNCERTAIN,
  LIVENESS_UNAVAILABLE, QUALITY_TOO_SMALL, QUALITY_BLUR, QUALITY_DARK, MULTI_FACE, NO_FACE,
  TRACKING_LOST, TIMEOUT, CHALLENGE_FAILED, MANUAL_REVIEW
next_action: NONE | MOVE_CLOSER | HOLD_STILL | IMPROVE_LIGHT | CHALLENGE | RETRY | RECEPTION

### Browser -> API
POST /attempt/start          json {user_id, consent:true}
  -> {attempt_id, server_t0_ms, deadline_ms}            # deadline = t0 + 1700
POST /attempt/{id}/identity  multipart: frame (jpeg <=640px), capture_ts_ms
  -> {identity: MATCH|MISMATCH|UNKNOWN, similarity|null, ms}
  # Browser fires this WITHOUT awaiting, as soon as it has the first frame.
POST /attempt/{id}/liveness  multipart: frames[] (~6 jpeg over ~1s), capture_ts_ms[], scenario (optional)
  -> {decision, reason_code, message, next_action, attempt_id,
      signals:{quality, passive:{status,score}, identity:{status,similarity}},
      stage_ms:{quality, passive, identity_wait, decide}, first_pass_server_ms}
  # Server waits for identity until deadline, then decides. First-pass decision is FINAL.
POST /attempt/{id}/challenge/start
  -> {challenge_id, actions:[2 of SMILE|OPEN_MOUTH|TURN_LEFT|TURN_RIGHT], baseline_ms:400, timeout_ms:5000}
POST /attempt/{id}/challenge multipart: frames[], capture_ts_ms[], prompt_ts_ms, challenge_id
  -> same shape as /liveness, plus total_ms. One challenge per attempt; unresolved -> RECEPTION.

### API -> pipeline (Python functions in /pipeline)
quality(frames) -> {per_frame:[{face_count, face_px, blur, brightness, ok, fail_reason}], ok, fail_reason, continuity_ok}
select_frames(frames, ts) -> indices   # by quality + time spacing ONLY, never by liveness score
passive_liveness(frames) -> {status: LIVE|SPOOF|UNCERTAIN|UNAVAILABLE, score, per_frame}
challenge_check(frames, ts, prompt_ts, actions) -> {status: PASS|FAIL|UNCERTAIN, per_action, passive}

### Rules
- Unknown attempt_id -> 404. Results for an old attempt never touch a new one.
- A missing, failed, late or UNAVAILABLE signal is NEVER a pass.
- Late results are logged and never change a decision.
- Stubs must return UNAVAILABLE and be labelled STUB; they can never produce ALLOW.
- Logs: logs/attempts.jsonl, one line per decision, no images.
- AWS creds (.env) and enroll/ photos stay server-side and gitignored. Never commit face images.

## v3 additions (14 Nov, surprise challenges). Existing v2 API unchanged. REQUEST_VERIFICATION is displayed as "STEP-UP VERIFICATION".
New reason codes: SCHEDULE_DENIED, SCHEDULE_APPROVAL_REQUIRED, SCHEDULE_UNKNOWN, OFFLINE_STAFF_REQUIRED, STAFF_VERIFIED, STAFF_REJECTED
New next_action: STAFF_VERIFY
Every decision response adds: schedule:{status: PERMITTED|PROHIBITED|APPROVAL_REQUIRED|UNKNOWN, policy_version}, mode: ONLINE|OFFLINE
GET  /status -> {mode, pending_sync, synced, policy_version, kiosk_time}
POST /attempt/{id}/staff_verify  json {operator_pin, id_checked:bool, reason, approve:bool}
  -> final decision (STAFF_VERIFIED -> ALLOW only if schedule not PROHIBITED and no SPOOF; else DENY/blocked)
POST /operator/clock  json {iso_time|null}   # demo-only clock override, null = real time; shown on screen as "DEMO CLOCK"
Schedule file: data/schedule.json (fictional demo data; Siddhant owns). Times are Asia/Kolkata.
Sync: minimal decision events queued in SQLite (logs/outbox.db), uploaded to S3 key events/<event_id>.json; never images, embeddings or credentials.
