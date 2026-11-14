# HID Session B results

**Trial window:** 15:00–16:00 IST, 14 November 2026

**Status:** Awaiting the Session B attempt log and offline event evidence from the desktop HID folder.

## Biometric outcomes

| Scenario | Planned | Observed n | ALLOW | REQUEST | DENY |
|---|---:|---:|---:|---:|---:|
| Genuine | 6 | — | — | — | — |
| Impostor | 6 | — | — | — | — |
| Print | 6 | — | — | — | — |
| Phone | 6 | — | — | — | — |
| Replay | 6 | — | — | — | — |
| Mask without cutouts | 6 | — | — | — | — |
| Mask with cutouts | 6 | — | — | — | — |
| Bad light | 6 | — | — | — | — |
| **Total** | **48** | — | — | — | — |

Generate the measured counts, rates, and times with `python eval/results.py --session B --log PATH`. The reporter reads session prefixes from the scenario field, such as `B/print`, and skips rows without a slash. The 30-frame calibration run is separate.

## Schedule and offline outcomes

| Case | Planned | Observed n | Passed | Evidence |
|---|---:|---:|---:|---|
| Genuine at permitted time | 6 | — | — | Challenge and final outcome |
| Same person at prohibited time | 6 | — | — | Policy clock and denial reason |
| Print, phone or replay | 6 | — | — | Prop type and final outcome |
| Wi-Fi off | 6 | — | — | Offline mode and automatic outcome |
| Staff badge check offline | 6 | — | — | Staff authorization and queued event ID |
| Wi-Fi restored | 6 | — | — | Pending reaches zero and event is acknowledged |
| App restart | 6 | — | — | Queue persistence and one record per event ID |
| Offline spoof | 6 | — | — | No access and no authorization event |

Dashes indicate measurements pending. For each completed case, report actual counts even when fewer than six trials ran.
