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
