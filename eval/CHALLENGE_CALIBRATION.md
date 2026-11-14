# Anil’s live challenge calibration

Have Anil run the kiosk while Siddhant presents the approved props. Record the challenge result and final access outcome for every presentation. If the kiosk denies access before a challenge begins, record that outcome and mark challenge as “not reached.” Mark the cutout mask separately.

| Prop | Planned | Observed | Challenge PASS | FAIL | UNCERTAIN | Not reached | Access granted |
|---|---:|---:|---:|---:|---:|---:|---:|
| Printed photo | 3 | 0 | — | — | — | — | — |
| Phone photo | 3 | 3 | 0 | 0 | 3 | 0 | Unreported |
| Replay video | 2 | 3 | 0 | 0 | 3 | 0 | Unreported |
| Mask without cutouts | 1 | 0 | — | — | — | — | — |
| Cutout mask | 1 | 0 | — | — | — | — | — | — |
| Genuine control | 3 | 5 | 5 | 0 | 0 | 0 | Unreported |
| **Total** | **13** | **11** | **5** | **0** | **6** | **0** | Unreported |

Counts supplied by the tester and sent to Sidhant and Sonu in [issue #3](https://github.com/shestg28/Unemployed/issues/3). Source logs, per-attempt IDs and final kiosk access decisions have not been supplied. Prints and both masks were not tested because the props were unavailable. Replay and genuine totals exceeded the original plan. Optional big-screen and improvised-prop trials have no results yet and must be labeled separately.

## Additional captured live-face trials

The tester confirmed these three captures used their live face after initially selecting bigscreen1. Their labels and 148 saved frames were corrected to real locally, with original metadata retained. These results are reported separately from the earlier counts because overlap with those reported totals is unknown.

| Attempt | Capture ID | Outcome | Validity |
|---|---|---|---|
| 1 | 7b6cb09eedc94202aff1f19eabf8e553 | PASS, 2/2 actions | Included |
| 2 | 15e8de5312af4ae78d1d8285902c5d3e | UNCERTAIN, TRACKING_LOST | Excluded because tester reported improper execution |
| 3 | 62c932467e104537859faf0efa66df69 | UNCERTAIN, TRACKING_LOST | Included |

Valid genuine attempts in this batch: 1/2 PASS and 1/2 UNCERTAIN. Big-screen spoof attempts in this batch: 0. All three original outcomes remain recorded.

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
