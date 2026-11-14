# HID kiosk demo

## Three minutes

| Time | Say or do |
|---|---|
| 0:00–0:20 | **Slide 1.** “A wrong ALLOW is a breach, a wrong DENY is an inconvenience, so doubt never resolves to ALLOW.” Explain that the kiosk checks whether a live person matches the identity they claim. |
| 0:20–0:45 | **Slide 2.** Follow the two-speed diagram. The first decision checks presence and the claimed identity. Uncertainty keeps the door closed and asks for a specific fix or a short follow-up check. Access requires affirmative evidence of both presence and identity. |
| 0:45–1:05 | **Slide 3, live.** Siddhant taps his identity and presents his face. Point to the actual ALLOW and timer if it appears under 2 seconds. Read the actual outcome and time if it differs. |
| 1:05–1:45 | **Live.** Run a print, phone still, replay and mask against the same claimed identity. Read each decision aloud. Say “none gets in” only if all four were held through the end of their shown attempts. A REQUEST keeps access closed. Report an unexpected ALLOW plainly. |
| 1:45–2:05 | **Live.** Use dim light. Show the reason on screen, then point to the targeted instruction, such as “Move into better light.” Show the corrected-light retry if the clock allows. |
| 2:05–2:35 | **Slide 4.** Show Session B counts. Read the false accept count and denominator, the separate DENY-only figure and the first-pass median and p95 with sample size. If collection is pending, say so and keep the live demonstration separate. |
| 2:35–3:00 | **Slide 5.** “One tap selects the record to check, like a badge. The kiosk makes a one-to-one comparison. It never searches a gallery, stores no attempt images, and sends no faces to Bedrock.” Verify those behaviors in the demo build before presenting them as implemented. |

## Judge Q&A

- **What would OTP tell you?** “OTP proves you hold a phone, not that you're present.” A phone check cannot substitute for face liveness or identity evidence at the kiosk.
- **Is a score of 0.96 a 96% chance?** No. Scores are model signals. We set decision thresholds with Session A and evaluate them on fresh Session B attempts.
- **How much can we infer from this test?** Read the numerator and denominator. The attempts are from a small consenting team, with repeated participants on one setup. A zero in the false accepts column describes the observed attempts only.
- **Is REQUEST a detected spoof?** REQUEST holds the door closed while more evidence is needed. The DENY-only rate tells you how often attack attempts received a DENY without any ALLOW.
- **Where is the two-second clock measured?** The results table reports server first-pass time from attempt start. The live timer shows the person’s experience. A requested follow-up has a separate end-to-end time.
- **What happens to the face images?** State the verified retention for attempt frames and the separate policy for enrollment references. The contract allows server-side enrollment photos. Only say “no images stored” if the deployed build supports that claim across the stated scope. Bedrock explanation, if enabled, receives no face images and runs after the decision.
