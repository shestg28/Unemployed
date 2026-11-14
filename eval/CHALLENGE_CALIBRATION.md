# Anil’s live challenge calibration

Have Anil run the kiosk while Siddhant presents the approved props. Record the challenge result and final access outcome for every presentation. If the kiosk denies access before a challenge begins, record that outcome and mark challenge as “not reached.” Mark the cutout mask separately.

| Prop | Planned | Observed | Challenge PASS | FAIL | UNCERTAIN | Not reached | Access granted |
|---|---:|---:|---:|---:|---:|---:|---:|
| Printed photo | 3 | — | — | — | — | — | — |
| Phone photo | 3 | — | — | — | — | — | — |
| Replay video | 2 | — | — | — | — | — | — |
| Mask without cutouts | 1 | — | — | — | — | — | — |
| Cutout mask | 1 | — | — | — | — | — | — |
| **Total** | **10** | — | — | — | — | — | — |

Copy these counts to the calibration slide after Anil’s run. The earlier 30-frame camera test measured the passive model, while this run measures the live challenge path. Report each with its own denominator.

## Attempt record — due 14:30 IST

For spoof presentations, a challenge PASS means the spoof passed that check. Record the final access decision separately. Use FAIL, UNCERTAIN or not reached exactly as returned.

| Trial | Prop | Challenge result | Final access decision | Saved capture ID |
|---|---|---|---|---|
| 1 | Print | Pending | Pending | Pending |
| 2 | Print | Pending | Pending | Pending |
| 3 | Print | Pending | Pending | Pending |
| 4 | Phone photo | Pending | Pending | Pending |
| 5 | Phone photo | Pending | Pending | Pending |
| 6 | Phone photo | Pending | Pending | Pending |
| 7 | Replay video | Pending | Pending | Pending |
| 8 | Replay video | Pending | Pending | Pending |
| 9 | Cutout mask | Pending | Pending | Pending |
| 10 | Mask without cutouts | Pending | Pending | Pending |

Retain the approved capture stills under data/gate with their scenario labels. Keep each attempt's capture ID so multiple frames from one attempt are counted as one trial.

The retained-capture browser runner is `python eval/retain_challenge.py 8768`, run from the integrated checkout with its current pipeline and models. Open http://127.0.0.1:8768 on that laptop. Select the prop before each attempt. The runner saves JPEG frames in `data/gate/<scenario>/` and the returned challenge status in `data/gate/challenge_trials.jsonl`. Record the kiosk access decision separately. Only challenge outcomes are produced by this runner.
