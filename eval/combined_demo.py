"""Experimental RetinaFace + HID ensemble viewer. Never grants access.

Run with --pipeline-root pointing to the HID checkout containing model assets.
Frames remain in memory; C runs the unchanged HID challenge, Q exits.
"""
import argparse
import random
import sys
import time
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
        if len(faces) != 1:
            return None, 'Exactly one face required'
        x1, y1, x2, y2 = faces[0].bbox.astype(int)
        box = [int(x1), int(y1), int(x2-x1), int(y2-y1)]
        result = ensemble.predict(frame, box)
        return box, f"V2 + V1SE live score: {result['live_score']:.4f} (not a probability)"

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
    result_text = 'Press C for challenge; Q to quit. No access decision here.'
    frames, stamps, actions = [], [], []
    started = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Camera stopped delivering frames')
            now = time.perf_counter() * 1000
            view = frame.copy()
            if started is not None:
                # Capture without model inference so action timing is not distorted.
                if not stamps or now-stamps[-1] >= 90:
                    frames.append(frame.copy())
                    stamps.append(now)
                elapsed = now-started
                prompt = 'Hold neutral for baseline' if elapsed < 600 else ' THEN '.join(actions)
                result_text = prompt
                if elapsed >= 5600:
                    cv2.putText(view, 'Checking...', (12, 100), 0, .7, (0,255,255), 2)
                    cv2.imshow(window, view)
                    cv2.waitKey(1)
                    try:
                        result = challenge_check(frames, stamps, prompt_ts, actions)
                        result_text = 'Challenge: ' + result['status'] + ' - ' + str(result.get('reason', ''))
                        print(result_text, flush=True)
                    except Exception as exc:
                        result_text = 'UNAVAILABLE: ' + str(exc)[:70]
                    frames, stamps = [], []
                    started = None
                elif elapsed >= 600 and prompt_ts is None:
                    prompt_ts = now
            else:
                box, message = score(frame)
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
                actions = random.sample(['SMILE','OPEN_MOUTH','TURN_LEFT','TURN_RIGHT'], 2)
                frames, stamps = [], []
                started = time.perf_counter()*1000
                prompt_ts = None
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
