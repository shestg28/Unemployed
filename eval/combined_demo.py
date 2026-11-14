"""Experimental RetinaFace + HID ensemble viewer. Never grants access.

Run with --pipeline-root pointing to the HID checkout containing model assets.
Frames remain in memory; C runs the unchanged HID challenge, Q exits.
"""
import argparse
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline-root', required=True)
    parser.add_argument('--sample')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.pipeline_root).resolve()))
    import cv2
    from uniface import RetinaFace
    from pipeline.silentface import get
    from pipeline import challenge_check, warmup_challenge
    detector = RetinaFace()
    ensemble = get()
    print('Ensemble:', [m[0] for m in ensemble.models], flush=True)

    def score(frame):
        faces = detector.detect(frame)
        detected_at = time.perf_counter()*1000
        if len(faces) != 1:
            return None, 'Exactly one face required', detected_at
        x1, y1, x2, y2 = faces[0].bbox.astype(int)
        box = [int(x1), int(y1), int(x2-x1), int(y2-y1)]
        result = ensemble.predict(frame, box)
        return box, f"V2 + V1SE live score: {result['live_score']:.4f} (not a probability)", detected_at

    if args.sample:
        frame = cv2.imread(args.sample)
        if frame is None:
            raise ValueError('Cannot read sample')
        print(score(frame), flush=True)
        return
    if not warmup_challenge():
        raise RuntimeError('Challenge unavailable; refusing to start combined demo')
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError('Camera unavailable; close other camera apps')
    window = 'HID Combined - EXPERIMENTAL'
    result_text = 'Face detection starts a 2-second trial. Q quits.'
    frames, stamps, actions = [], [], []
    started = None
    pool = ThreadPoolExecutor(max_workers=2)
    score_job = None
    challenge_job = None
    armed = True
    box, message = None, 'Looking for one face'
    prompt_ts = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Camera stopped delivering frames')
            now = time.perf_counter() * 1000
            view = frame.copy()
            if score_job is not None and score_job.done():
                try:
                    box, message, detected_at = score_job.result()
                except Exception as exc:
                    box, message = None, 'UNAVAILABLE: ' + str(exc)[:60]
                score_job = None
                if box is not None and armed and started is None:
                    started = detected_at
                    actions = random.sample(['SMILE','OPEN_MOUTH','TURN_LEFT','TURN_RIGHT'], 2)
                    frames, stamps = [], []
                    prompt_ts = None
                    armed = False
            if score_job is None:
                score_job = pool.submit(score, frame.copy())
            if started is not None:
                # Model work stays off the display/capture thread.
                if not stamps or now-stamps[-1] >= 90:
                    frames.append(frame.copy())
                    stamps.append(now)
                elapsed = max(0, now-started)
                prompt = 'Hold neutral for baseline' if elapsed < 400 else ' THEN '.join(actions)
                result_text = f'{elapsed/1000:.1f}/2.0s: {prompt}'
                if elapsed >= 400 and prompt_ts is None:
                    prompt_ts = now
                if elapsed >= 1400 and challenge_job is None:
                    challenge_job = pool.submit(challenge_check, list(frames), list(stamps), prompt_ts, actions)
                if elapsed >= 2000:
                    result = {'status': 'UNCERTAIN', 'reason': 'DEADLINE'}
                    if challenge_job is not None and challenge_job.done():
                        try:
                            result = challenge_job.result()
                        except Exception:
                            result = {'status': 'UNCERTAIN', 'reason': 'UNAVAILABLE'}
                    outcome = 'LIVENESS PASS (identity/policy required)' if result['status'] == 'PASS' else 'REQUEST VERIFICATION'
                    if result['status'] == 'FAIL':
                        outcome = 'DENY: challenge failed'
                    result_text = f'{outcome} | {elapsed:.0f}ms | C to retry'
                    print({'outcome': outcome, 'elapsed_ms': round(elapsed, 1), 'challenge': result['status'],
                           'reason': result.get('reason'), 'late_result_can_change_decision': False}, flush=True)
                    frames, stamps = [], []
                    started = None
            if box:
                x,y,w,h = box
                cv2.rectangle(view,(x,y),(x+w,y+h),(255,180,0),2)
            cv2.putText(view, message, (12,30), 0, .48, (255,255,255), 1)
            cv2.putText(view, result_text, (12,65), 0, .48, (0,255,255), 1)
            cv2.putText(view, 'Experimental | challenge mandatory | identity + policy still required',
                        (12,view.shape[0]-18), 0, .43, (255,255,255), 1)
            cv2.imshow(window, view)
            key = cv2.waitKey(1) & 255
            if key == ord('q'):
                break
            if key == ord('c') and started is None:
                if challenge_job is None or challenge_job.done():
                    challenge_job = None
                    armed = True
                    result_text = 'Waiting for face detection'
    finally:
        cap.release()
        cv2.destroyAllWindows()
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
