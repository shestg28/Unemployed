# Request: face-only identification (1:N) — for Akash (/api owner)

The kiosk can verify **without an ID**: the person just looks at the camera and presses Verify.
That needs one backend change. The kiosk side is done on `shesh/kiosk` (`CONFIG.IDENTIFY_MODE`, **off by default**
until this lands; `?identify=1` turns it on, otherwise the kiosk uses the 1:1 flow with the ID field).

Today `/attempt/start` rejects a missing `user_id` (400 `invalid user_id`), so identify mode shows
"Additional Verification Required — the server does not support face-only identification yet" until this lands.
It never approves.

## What the kiosk sends (unchanged except `user_id`)

```
POST /attempt/start   json {consent: true, scenario}          # no user_id
POST /attempt/{id}/identity, /liveness, /challenge/start, /challenge   # exactly as today
```

## What the kiosk needs back

Only one new field: the matched enrolled id, wherever identity is reported.

```
/attempt/{id}/identity  -> {identity: MATCH|MISMATCH|UNKNOWN, user_id: "<matched id>"|null, similarity, ms}
/liveness, /challenge   -> signals.identity = {status, similarity, user_id}
```

The kiosk shows `user_id` **only on Access Approved**. It never shows who a rejected face resembled.

## Suggested server behaviour

- `StartBody.user_id` optional. Missing user_id = identify mode for that attempt.
- `identity.compare` in identify mode: run CompareFaces against **every** enrolled photo **in parallel**
  (same executor, same client; contract rule "Rekognition calls run in parallel"). Fine for a demo-sized
  enrolled set. For a large set, use a Rekognition collection + `SearchFacesByImage` (one call).
- Result rule (keeps "missing/unsure is never a pass"):
  - **MATCH**: exactly one enrolled person ≥ `ID_MATCH`. Return their `user_id`.
  - **MISMATCH**: one face, adequate quality, and every enrolled person < `ID_MISMATCH` → existing DENY `ID_MISMATCH`
    (face is not enrolled).
  - **UNKNOWN**: everything else: two people ≥ `ID_MATCH`, grey zone, no face, multi-face, errors, timeouts.
- The challenge-phase identity re-check should compare against the **same matched user_id** from the first pass,
  so the challenge can't switch identities mid-attempt.
- Log the matched `user_id` in `attempts.jsonl` as today.
- Latency: the parallel calls must still fit the 1.7 s identity deadline; late = missing, as today.

This changes the decision contract ("nobody changes this without Akash"), so it's your call.
