# HID kiosk demo

## Three minutes

| Time | Say or do |
|---|---|
| 0:00–0:15 | **Slide 1.** “A wrong ALLOW is a breach, a wrong DENY is an inconvenience, so doubt never resolves to ALLOW.” |
| 0:15–0:35 | **Slide 2.** Read the 30-frame camera test and the 90% target. “We measured the off-the-shelf model, it failed our bar, so it never approves anyone on its own.” |
| 0:35–0:50 | **Slide 3.** Explain the two speeds. The kiosk gives a first decision, then a mandatory challenge precedes every online biometric ALLOW. Access also requires an identity match and schedule permission. |
| 0:50–1:30 | **Slide 4, live.** Run permitted-time genuine verification and show REQUEST → challenge → ALLOW. Read the first-pass timer and total separately. Show the same person's prohibited-time DENY. Use the recorded run if a demo clock change is impractical. Show bad light with its targeted fix and one spoof live if time allows. Use rehearsed captures for the remaining print, phone, replay and mask cases. Say “none gets in” only when the shown outcomes support it. |
| 1:30–2:20 | **Slide 5.** “Offline, the kiosk can still say no on its own, but only a person with a badge check can say yes.” Show the offline screen and the no-access spoof outcome. Show staff checking a badge, authorizing access, and the queued event. Reconnect and show pending sync at zero. Use a short recorded sequence for the restart and event-ID checks. Show Shesh's online staff-approval status if time allows. |
| 2:20–2:45 | **Slide 6.** Show Session B counts, false accepts with the denominator, and first-pass median and p95 with the sample size. Read the schedule/offline pass counts from the rehearsal record. Label any pending cases. |
| 2:45–3:00 | **Slide 7.** “One tap selects the record to check, like a badge. The kiosk makes a one-to-one comparison. It never searches a gallery, stores no attempt images, and sends no faces to Bedrock.” Verify those behaviors in the demo build before presenting them as implemented. |

## Eight checks to rehearse

| Case | Show the audience |
|---|---|
| Genuine at permitted time | Tap the claimed ID, complete the challenge, and show ALLOW. |
| Same person at prohibited time | Show the test-clock setting and the prohibited-time DENY. |
| Print, phone or replay | Show verification fail or an earlier DENY. The door stays closed. |
| Wi-Fi off | Show the offline state and confirm there is no automatic ALLOW. |
| Offline staff verification | Staff checks the badge, explicitly authorizes access, and shows the pending event. |
| Wi-Fi restored | Show pending sync drop to zero and the same event appear once on the server. |
| App restart | Show the queued event survive a restart before reconnecting. After sync, restart again and verify one record per event ID. |
| Offline spoof | Present an approved test prop while offline and show that no access was granted. |

## Judge Q&A

- **What would OTP tell you?** “OTP proves you hold a phone, not that you're present.” A phone check cannot substitute for face liveness or identity evidence at the kiosk.
- **Is a score of 0.96 a 96% chance?** No. Scores are model signals. We set decision thresholds with Session A and evaluate them on fresh Session B attempts.
- **How much can we infer from this test?** Read the numerator and denominator. The attempts are from a small consenting team, with repeated participants on one setup. A zero in the false accepts column describes the observed attempts only.
- **Is REQUEST a detected spoof?** REQUEST holds the door closed while more evidence is needed. The DENY-only rate tells you how often attack attempts received a DENY without any ALLOW.
- **Where is the two-second clock measured?** The results table reports server first-pass time from attempt start. The live timer shows the person’s experience. A requested follow-up has a separate end-to-end time.
- **What happens to the face images?** State the verified retention for attempt frames and the separate policy for enrollment references. The contract allows server-side enrollment photos. Only say “no images stored” if the deployed build supports that claim across the stated scope. Bedrock explanation, if enabled, receives no face images and runs after the decision.
