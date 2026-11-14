*** Begin Patch
*** Add File: work/hid-eval/eval/WHY_PASSIVE_FAILED.md
+# Why MiniFASNet failed the passive gate
+
+## Official sample sanity check
+
+Ran the pinned Silent-Face `test.py` and our `passive_liveness` on the same three files. The upstream score is for its winning class. Our score is for the live class, so the fake-row scores are different quantities.
+
+| Official sample | Upstream verdict and winning-class score | Our verdict | Our live score |
+|---|---|---|---:|
+| image_T1.jpg | Real, 0.99 | LIVE | 0.9936 |
+| image_F1.jpg | Fake, 0.73 | SPOOF | 0.0723 |
+| image_F2.jpg | Fake, 0.82 | SPOOF | 0.1813 |
+
+Verdicts matched **3/3**. The upstream pin was `b6d5f04ad78778917853b25c778acef6d5626d15`. The local wrapper had its default high/low cutoffs of 0.80/0.30. This sample check covers those three images only.
+
+## Local gate and ablations
+
+| Configuration | Genuine passed | Print passed | Phone passed | Score mean/min/max |
+|---|---:|---:|---:|---|
+| Original gate scorer, BGR ensemble at the recorded ≈0.9973 threshold | 6/10 | 4/10 | 3/10 | Unavailable |
+| Pipeline as-is | — | — | — | — |
+| Official detector + CropImage | — | — | — | — |
+| RGB input | — | — | — | — |
+| V2 alone | — | — | — | — |
+| V1SE alone | — | — | — | — |
+| Explicit ensemble | — | — | — | — |
+| Gamma 0.7 | — | — | — | — |
+| CLAHE luminance | — | — | — | — |
+
+The recorded gate caught **6/10 prints and 7/10 phone stills**. Source is the 13:24 IST local gate screenshot, with both props confirmed by the tester. Its winning threshold used the gate's maximin criterion. The requested threshold sweep instead maximizes genuine pass rate plus pooled spoof catch rate, and requires the individual scores.
+
+The browser gate saved the 30 captures only in a temporary directory and removed it after scoring. No saved `data/gate` batch was found on this PC. Dashes indicate ablations awaiting the original frames. The three-box comparison, widths, correlations, threshold sweep and histogram also require those frames.
+
+## What the numbers establish
+
+| Observed failure | Evidence |
+|---|---|
+| Genuine rejection | 4/10 genuine frames fell below the fitted threshold. Genuine pass rate was 30 percentage points below the 90% gate. |
+| Spoof acceptance | 7/20 spoof frames cleared the same threshold. Print and phone catch rates were 30 and 20 percentage points below the gate. |
+
+These counts establish the two failure modes. They cannot rank the causes among detector boxes, color order, model choice, brightness and face size. The two-model scorer passes the official sample check, and the aggregate counts show that its scores failed to separate the local cases at the gate’s selected threshold.
+
+Keep the mandatory challenge. If the original batch is recovered, run the script below before assigning causes. Re-check any apparent improvement on fresh frames before changing a threshold or flag.
+
+```text
+python eval/gate_ablation.py --gate PATH_TO_EXISTING_DATA_GATE
+```
+
+Run with the liveness checkout's `pipeline` available on `PYTHONPATH` and its pinned weights installed. The script checks the official samples first, then writes the configuration table, anonymous per-frame widths and scores, and histogram under `eval`. The baseline ablation uses the pipeline's existing high cutoff. The independently fitted cutoffs are diagnostic.
+
