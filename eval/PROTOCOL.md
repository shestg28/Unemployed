# HID kiosk evaluation protocol

Use only consenting teammates as presenters and as the subjects of test props. Explain the purpose, what the camera captures, what gets logged, and how to withdraw before obtaining consent. Use participant codes in the evaluation notes. Keep props and any enrollment references private and outside Git. The kiosk should retain no attempt images or video. Collect only the decision metadata needed for evaluation.

| Scenario tag | Presentation | Session A | Session B |
|---|---|---:|---:|
| genuine | Enrolled teammate claiming their own ID in normal light | 3 | 10 |
| impostor | Live teammate claiming a different consenting teammate's ID | 3 | 10 |
| print | Printed face photo | 3 | 10 |
| phone | Still face photo shown on a phone | 3 | 10 |
| replay | Recorded face video played on a screen | 3 | 10 |
| mask_no_cutout | Mask without cutouts | 3 | 10 |
| mask_cutout | Mask with cutouts | 3 | 10 |
| bad_light | Enrolled teammate claiming their own ID in dim light | 3 | 10 |
| **Total** | | **24** | **80** |

1. In **Session A**, use fresh attempt IDs and calibrate the thresholds. Record the code revision, configuration, camera, and test conditions. Freeze them before Session B.
2. In **Session B**, collect fresh trials with the frozen configuration. Interleave scenario order and rotate consenting teammates across trials where possible. Keep ordinary lighting and camera position consistent except in the intended lighting test. Keep the first valid outcome even when it is unexpected. Record any acquisition or logging failure and actual counts. A setup rehearsal belongs outside A and B. If settings change after B begins, preserve that run and start a fresh reporting run.
3. Start at the ID tap and record the first visible decision time for the live demo. The report uses server timings from attempt start. Label them as server timings and keep the kiosk timer separate unless the clocks are confirmed equivalent. For a challenge, keep the scenario, session and attempt ID from the original presentation. If the subject or presentation changes, start a new attempt. Measure the corrected-light retry separately from the low-light presentation.
4. Tag each decision row with `session: "A"` or `session: "B"`. The current logger on `akash/api-v2` records the scenario and phase but lacks a session field. Until the integration adds it, use a fresh log for each session and pass the known session explicitly, as below. Never infer the session of a mixed or previously used log.

Run from the repo root with Python 3.10+:

```text
python eval/results.py --session B
python eval/results.py --session B --untagged-session B
```

The second command is for a physically separate, clean B-only log. The default input is `logs/attempts.jsonl`. Outputs are `eval/results-B.md` and `eval/results-B.csv`. Add `--log PATH` for a session-specific snapshot.

Counts use the last decision per attempt. Any ALLOW counts as entry for the security metrics. Attack scenarios are print, phone, replay and both mask variants. An attack with no ALLOW counts toward the requested attack detection rate (access prevented). Report the DENY-only rate independently. A REQUEST by itself establishes only that access was held. False accepts count attack and impostor attempts with any ALLOW. False rejects and step-ups use the first decision on normal-light genuine attempts, with final genuine DENY and REQUEST reported separately. Bad light has its own row. State every denominator and report median, nearest-rank p95, and mean first-pass time. Report total-time median and p95 separately. A REQUEST without a recorded follow-up has no measured total duration.

The poster's liveness decision target is **≤2 s**. Report the first-pass count meeting that target. Adopt the judge slide's names and any additional thresholds once Akash shares the photo. Session B estimates describe this setup and these trials. Repeated attempts by a small team provide limited evidence about other people or conditions.
