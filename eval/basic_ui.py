"""Local experimental voting UI. No images are saved or transmitted."""
import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from combined_demo import vote_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pipeline-root', required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.pipeline_root).resolve()))
    import cv2
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title('HID | Liveness demo')
    root.geometry('900x760')
    root.configure(bg='#f3f6fb')
    root.minsize(760, 680)
    ttk.Style().configure('TButton', font=('Segoe UI', 13), padding=10)
    tk.Label(root, text='HID  /  Liveness check', font=('Segoe UI', 25, 'bold'),
             bg='#f3f6fb', fg='#102442').pack(pady=(18, 5))
    tk.Label(root, text='Experimental demo • consenting teammates only • no images saved',
             bg='#f3f6fb', fg='#526078', font=('Segoe UI', 11)).pack()
    preview = tk.Label(root, bg='#102442', text='Preparing camera and models…', fg='white')
    preview.pack(pady=12)
    status = tk.StringVar(value='Loading models…')
    status_label = tk.Label(root, textvariable=status, font=('Segoe UI', 22, 'bold'),
                            bg='#f3f6fb', fg='#102442')
    status_label.pack()
    detail = tk.StringVar(value='The check starts when one face is detected.')
    tk.Label(root, textvariable=detail, font=('Segoe UI', 11), bg='#f3f6fb').pack(pady=5)
    scores_text = tk.StringVar(value='Six sampled scores will appear here')
    tk.Label(root, textvariable=scores_text, font=('Consolas', 12), bg='#f3f6fb').pack(pady=5)
    events = queue.Queue()
    latest = queue.Queue(maxsize=1)
    start = threading.Event()
    stop = threading.Event()
    button = ttk.Button(root, text='Run check', state='disabled', command=start.set)
    button.pack(pady=8)
    tk.Label(root, text='4 of 6 > 0.85: approve  |  4 of 6 < 0.75: reject  |  otherwise: request verification',
             bg='#f3f6fb', fg='#526078', font=('Segoe UI', 10)).pack()
    tk.Label(root, text='Scores are not probabilities. Demo approval does not authorize access.',
             bg='#f3f6fb', fg='#526078', font=('Segoe UI', 10)).pack(pady=4)

    def worker():
        cap = None
        try:
            from uniface import RetinaFace
            from pipeline.silentface import get
            detector, ensemble = RetinaFace(), get()
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                raise RuntimeError('Camera unavailable. Close other camera apps and reopen this window.')
            events.put(('ready', None))
            active = False
            began = None
            values = []
            requested = None
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Camera stopped. Reopen the demo to retry.')
                if start.is_set():
                    start.clear()
                    active, began, values = True, None, []
                    requested = time.perf_counter()
                    events.put(('running', None))
                if active:
                    faces = detector.detect(frame)
                    detected_at = time.perf_counter()
                    if len(faces) == 1:
                        if began is None:
                            began = detected_at
                        x1,y1,x2,y2 = faces[0].bbox.astype(int)
                        if detected_at-began < 2:
                            result = ensemble.predict(frame, [int(x1),int(y1),int(x2-x1),int(y2-y1)])
                            if time.perf_counter()-began <= 2:
                                values.append(result['live_score'])
                        cv2.rectangle(frame,(x1,y1),(x2,y2),(255,180,0),2)
                    elapsed = time.perf_counter()-began if began is not None else None
                    events.put(('progress', (elapsed, len(values))))
                    if elapsed is not None and elapsed >= 2:
                        outcome, sampled, high = vote_result(values)
                        events.put(('result', (outcome, sampled, high, elapsed, len(values))))
                        active = False
                    elif began is None and time.perf_counter()-requested > 15:
                        events.put(('result', ('REQUEST VERIFICATION', [], 0, None, 0)))
                        active = False
                rgb = cv2.cvtColor(cv2.resize(frame, (640, 360)), cv2.COLOR_BGR2RGB)
                try:
                    latest.get_nowait()
                except queue.Empty:
                    pass
                latest.put_nowait(rgb)
        except Exception as exc:
            events.put(('error', str(exc)))
        finally:
            if cap is not None:
                cap.release()

    def update():
        try:
            rgb = latest.get_nowait()
            preview.image = ImageTk.PhotoImage(Image.fromarray(rgb))
            preview.configure(image=preview.image, text='')
        except queue.Empty:
            pass
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'ready':
                status.set('Ready')
                button.configure(state='normal')
            elif kind == 'running':
                button.configure(state='disabled')
                status.set('Looking for one face…')
                status_label.configure(fg='#102442')
                scores_text.set('Collecting fresh frames…')
            elif kind == 'progress':
                elapsed, count = value
                if elapsed is not None:
                    status.set(f'Checking… {max(0, 2-elapsed):.1f}s')
                detail.set(f'{count} valid scores collected')
            elif kind == 'result':
                outcome, sampled, high, elapsed, count = value
                status.set(outcome)
                status_label.configure(fg={'APPROVED':'#087947','REJECTED':'#bd3030'}.get(outcome,'#986000'))
                timing = f'{elapsed:.3f}s measured' if elapsed is not None else 'No single face detected'
                detail.set(f'{timing} • {high}/{len(sampled)} above 0.85 • {count} scores available')
                scores_text.set('   '.join(f'{s:.4f}' for s in sampled) or 'Not enough valid frames')
                button.configure(state='normal', text='Run again')
            elif kind == 'error':
                status.set('Unable to run check')
                detail.set(value)
                button.configure(state='disabled')
        if not stop.is_set():
            root.after(30, update)

    def close():
        stop.set()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    threading.Thread(target=worker, daemon=True).start()
    update()
    root.mainloop()


if __name__ == '__main__':
    main()
