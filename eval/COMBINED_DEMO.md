# Experimental combined demo

## Basic button interface

Run `python eval/basic_ui.py --pipeline-root C:/path/to/HID-with-working-pipeline`
with the same environment/models described below. Python needs Tk support (included
in the standard Windows Python installer). Click Run check; a single detected face
starts the scoring window. Results show six randomly selected completed scores and
measured elapsed time. Run again starts a fresh trial. No challenge runs in this UI.
Four scores >0.85 approve, four <0.75 reject, otherwise request verification.
This is an experimental local display, not an integrated access controller. No
images are saved. Actual elapsed time can exceed two seconds due to inference and
camera latency; do not present the two-second target as a demonstrated guarantee.

## Optional passive voting experiment

Add `--mode vote` to run the requested passive-only experiment. Within the two-second
trial, collect completed scores from distinct webcam frames, then uniformly sample
six scores without replacement. Four or more strictly greater than 0.85 gives
APPROVED; four or more strictly below 0.75 gives REJECTED. Otherwise return
REQUEST VERIFICATION, including boundary scores of 0.75 and 0.85. Fewer than
six finite valid scores gives REQUEST VERIFICATION. Scores completed after the
deadline are excluded. Selected scores/counts and actual elapsed time print to the
console; frames stay in memory. This sampling is random among scored frames, not
all camera frames. Voting mode does not run a challenge. Standalone challenge mode
has a separate six-second budget and is not a two-second authentication. APPROVED is an
experimental passive vote, not a door authorization or validated spoof verdict.
The default challenge mode and production pipeline remain unchanged.

Entry point: `eval/combined_demo.py` on `siddhant/eval`.
Uses UniFace RetinaFace plus the existing HID MiniFASNet V2/V1SE ensemble;
does not count V2 twice. No face frames are saved. No production flags changed.

## Teammate setup

Use Python 3.11 in a separate environment. Install the HID pipeline's requirements
and its model assets as described in that checkout. Also install `uniface==4.3.0`
and `onnxruntime==1.32.0`. Use `opencv-contrib-python==4.14.0.94` (OpenCV 5 removed
the Caffe loader needed by HID). Avoid installing multiple OpenCV distributions
in the same environment. UniFace downloads its RetinaFace model on first use.

`--pipeline-root` must name a checkout containing the working `siddanth/liveness`
pipeline, its Silent-Face weights/detector and MediaPipe face_landmarker.task.
The eval branch alone may contain an older pipeline; do not substitute it silently.

```powershell
python eval/combined_demo.py --pipeline-root C:/path/to/HID-with-working-pipeline
```

Camera 0 is used. Close other camera apps. First detected single face starts the
trial; C rearms after a result, Q exits. No additional camera permission workaround
is required or provided.

## Timing and decision limitations

Experimental two-second deadline measured from detector completion, including
subsequent scoring time. Background scoring and challenge processing run in worker
threads while capture/display continue. First 400ms supplies a neutral baseline;
the two action prompts follow. A snapshot is submitted for checking at 1400ms.
At 2000ms the display loop finalizes the available result. Missing/late/error results
are REQUEST VERIFICATION and cannot subsequently change the result. A failed
challenge is DENY; PASS is liveness only, never access authorization.

The camera/display loop is not a real-time scheduler: actual elapsed time is
printed and can exceed 2000ms. Two actions may not fit this short window. This
prototype has NOT established under-two-second successful authentication or spoof
detection accuracy. A REQUEST is neither a detected spoof nor a genuine acceptance.
Record fresh genuine/spoof trials and latency counts before making any such claim.
Identity, schedules and offline authorization remain responsibilities of the kiosk.
