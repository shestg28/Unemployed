# HID kiosk evaluation protocol

Use only consenting teammates as presenters and as the subjects of test props. Explain the purpose, what the camera captures, what gets logged, and how to withdraw before obtaining consent. Use participant codes in the evaluation notes. Keep props and any enrollment references private and outside Git. The kiosk should retain no attempt images or video. Collect only the decision metadata needed for evaluation.

| Scenario tag | Presentation | Session A | Session B |
|---|---|---:|---:|
| genuine | Enrolled teammate claiming their own ID in normal light | 3 | 6 |
| impostor | Live teammate claiming a different consenting teammate's ID | 3 | 6 |
| print | Printed face photo | 3 | 6 |
| phone | Still face photo shown on a phone | 3 | 6 |
| replay | Recorded face video played on a screen | 3 | 6 |
| mask_no_cutout | Mask without cutouts | 3 | 6 |
| mask_cutout | Mask with cutouts | 3 | 6 |
| bad_light | Enrolled teammate claiming their own ID in dim light | 3 | 6 |
| **Total** | | **24** | **48** |

1. In **Session A**, use fresh attempt IDs and calibrate the thresholds. Record the code revision, configuration, camera, and test conditions. Freeze them before Session B.
2. In **Session B**, collect fresh trials with the frozen configuration. Interleave scenario order and rotate consenting teammates across trials where possible. Keep ordinary lighting and camera position consistent except in the intended lighting test. Keep the first valid outcome even when it is unexpected. Record any acquisition or logging failure and actual counts. A setup rehearsal belongs outside A and B. If settings change after B begins, preserve that run and start a fresh reporting run.
3. Start at the ID tap and record the first visible decision time for the live demo. The report uses server timings from attempt start. Label them as server timings and keep the kiosk timer separate unless the clocks are confirmed equivalent. For a challenge, keep the scenario, session and attempt ID from the original presentation. If the subject or presentation changes, start a new attempt. Measure the corrected-light retry separately from the low-light presentation.
4. Prefix each decision row's `scenario` with the session and a slash, for example `A/print` or `B/print`. Use the same tag on the first pass and follow-up for each attempt. The reporter skips rows without a slash and never infers a session.

Run from the repo root with Python 3.10+:

```text
python eval/results.py --session B
```

The default input is `logs/attempts.jsonl`. Outputs are `eval/results-B.md` and `eval/results-B.csv`. Add `--log PATH` to read a different log.

Counts use the last decision per attempt. Any ALLOW counts as entry for the security metrics. Attack scenarios are print, phone, replay and both mask variants. An attack with no ALLOW counts toward the requested attack detection rate (access prevented). Report the DENY-only rate independently. A REQUEST by itself establishes only that access was held. False accepts count attack and impostor attempts with any ALLOW. False rejects and step-ups use the first decision on normal-light genuine attempts, with final genuine DENY and REQUEST reported separately. Bad light has its own row. State every denominator and report median, nearest-rank p95, and mean first-pass time. Report total-time median and p95 separately. A REQUEST without a recorded follow-up has no measured total duration.

The poster's liveness decision target is **≤2 s**. Report the first-pass count meeting that target. Adopt the judge slide's names and any additional thresholds once Akash shares the photo. Session B estimates describe this setup and these trials. Repeated attempts by a small team provide limited evidence about other people or conditions.

## Schedule and offline demo cases

Run Session B from **15:00 to 16:00 IST**. Use the fictional [main gate schedule](../data/schedule.json). Window times are IST. Interpret start as inclusive and end as exclusive, so Siddanth's 12:00 cutoff resolves to DENY. Unmatched or expired policy windows grant no access. The policy expires at 23:59 IST on 14 November 2026. Use Siddhant or Akash for ordinary permitted-time testing during the trial window. Use Siddanth for prohibited time. For the same-person comparison, run Siddanth using two documented test-clock settings on the demo environment (11:55 and 12:05 IST). Restore the normal clock before offline and sync trials.

Run six observations per case. Cases 1 and 3 may cite the same Session B attempts used for the liveness table. Link their attempt IDs and avoid adding them to that table again. Use two print, two phone, and two replay observations for case 3. Use case 4 through case 8 as a sequence you repeat six times, with distinct staff-authorized events. Run the offline spoof before the staff verification in each cycle so any later approval is clearly from the staff badge check. For the online schedule approval example, show Shesh's **staff approval** status separately from the eight scenarios.

| # | Pass condition | Evidence to record |
|---|---|---|
| 1 | Genuine, permitted time. ALLOW only after the challenge | Final decision, challenge outcome, first-pass and total times |
| 2 | Same person at prohibited time. DENY with the prohibited-time reason | Person code, policy clock, reason, final decision |
| 3 | Print, phone or replay fails verification. No access granted | Prop class, challenge outcome or earlier DENY, and final decision |
| 4 | Wi-Fi off. No automatic ALLOW | Connection state and decision before staff action |
| 5 | Offline staff checks the badge and authorizes ALLOW. Event stays queued | Staff-authorized source, event ID and pending count |
| 6 | Wi-Fi on. Pending sync reaches 0 and the event arrives once | Queue before and after, acknowledged event ID |
| 7 | Restart the app. Events survive without duplication | Restart before sync to check queue persistence and after sync to check you still have one event per ID |
| 8 | Offline spoof attempt. No access | Prop class, offline state, decision and absence of an authorization event |

Log observed outcomes by case, including failures and missing observations. For schedule and offline cases, record separate evidence from the kiosk or event queue, including the observed policy version, connection state, reason, and event IDs. Report each case as passed/run/planned with planned n=6. Keep staff-authorized access separate from biometric ALLOW. Report the Session B liveness table and the schedule/offline checks by **16:00 IST**. Leave any unrun cases pending and report actual denominators. Do not use the earlier 30-frame passive gate to fill Session B.
