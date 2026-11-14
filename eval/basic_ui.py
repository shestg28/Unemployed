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
    root.title('HID | Liveness studio')
    root.geometry('1080x670')
    root.minsize(1040, 640)
    bg, panel, muted = '#0b1224', '#16223b', '#a4b4cf'
    root.configure(bg=bg)
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('Accent.TButton', font=('Segoe UI', 13, 'bold'), padding=14,
                    background='#6366f1', foreground='white', borderwidth=0)
    style.map('Accent.TButton', background=[('active','#818cf8'),('disabled','#344260')])
    style.configure('Live.Horizontal.TProgressbar', troughcolor='#263550', background='#22d3ee', borderwidth=0)
    head = tk.Frame(root, bg=bg)
    head.pack(fill='x', padx=24, pady=(20,16))
    tk.Label(head, text='HID  /  Liveness studio', font=('Segoe UI',25,'bold'), bg=bg, fg='white').pack(side='left')
    tk.Label(head, text='  LOCAL DEMO  ', font=('Segoe UI',10,'bold'), bg='#29376b', fg='#c7d2fe', pady=8).pack(side='right')
    body = tk.Frame(root, bg=bg)
    body.pack(fill='both', expand=True, padx=24)
    left = tk.Frame(body, bg=panel, padx=12, pady=12)
    left.pack(side='left', fill='both')
    tk.Label(left, text='CAMERA PREVIEW', bg=panel, fg='#67e8f9', font=('Segoe UI',10,'bold')).pack(anchor='w', pady=(0,10))
    preview = tk.Label(left, bg='#080e1c', text='Preparing camera and models…', fg='white')
    preview.pack()
    tk.Label(left, text='Face the camera • Keep one face in view', bg=panel, fg='white', font=('Segoe UI',12)).pack(pady=(14,4))
    tk.Label(left, text='Consenting teammates only. Images stay in memory.', bg=panel, fg=muted, font=('Segoe UI',10)).pack()
    right = tk.Frame(body, bg=panel, padx=16, pady=16)
    right.pack(side='right', fill='both', expand=True, padx=(16,0))
    tk.Label(right, text='YOUR CHECK', bg=panel, fg='#a5b4fc', font=('Segoe UI',10,'bold')).pack(anchor='w')
    status = tk.StringVar(value='Getting ready…')
    status_label = tk.Label(right, textvariable=status, wraplength=280, justify='left', anchor='w',
                            font=('Segoe UI',21,'bold'), bg=panel, fg='white')
    status_label.pack(fill='x', pady=(10,8))
    progress = ttk.Progressbar(right, maximum=2, style='Live.Horizontal.TProgressbar')
    progress.pack(fill='x', pady=8)
    detail = tk.StringVar(value='The timer starts when one face is detected.')
    tk.Label(right, textvariable=detail, wraplength=280, justify='left', font=('Segoe UI',10), bg=panel, fg=muted).pack(fill='x', pady=8)
    tk.Label(right, text='SIX SAMPLED SCORES', bg=panel, fg='#a5b4fc', font=('Segoe UI',9,'bold')).pack(anchor='w', pady=(8,6))
    score_grid = tk.Frame(right, bg=panel)
    score_grid.pack(fill='x')
    cards = []
    for i in range(6):
        card = tk.Label(score_grid, text=f'{i+1}  —', font=('Consolas',12,'bold'), bg='#24324c', fg=muted, padx=8, pady=9)
        card.grid(row=i//2, column=i%2, padx=3, pady=3, sticky='ew')
        cards.append(card)
    score_grid.columnconfigure((0,1), weight=1)
    scores_text = tk.StringVar(value='Scores are not probabilities')
    tk.Label(right, textvariable=scores_text, wraplength=280, bg=panel, fg=muted, font=('Segoe UI',9)).pack(pady=6)
    events = queue.Queue()
    latest = queue.Queue(maxsize=1)
    start = threading.Event()
    stop = threading.Event()
    def run_check():
        if str(button['state']) != 'disabled':
            button.configure(state='disabled')
            start.set()
    button = ttk.Button(right, text='▶  Run check', style='Accent.TButton', state='disabled', command=run_check)
    button.pack(fill='x', pady=(6,0))
    root.bind('<space>', lambda event: run_check())
    tk.Label(right, text='Press Space to run again', bg=panel, fg=muted, font=('Segoe UI',9)).pack(pady=5)
    tk.Label(root, text='4/6 above 0.85: approve   •   4/6 below 0.75: reject   •   Otherwise: request verification',
             bg=bg, fg=muted, font=('Segoe UI',10)).pack(pady=(14,4))
    tk.Label(root, text='EXPERIMENTAL  /  Demo approval does not authorize access. Actual timing is shown after each check.',
             bg=bg, fg='#8292b1', font=('Segoe UI',9)).pack(pady=(0,12))

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
                status_label.configure(fg='#67e8f9')
                progress['value'] = 0
                for i, card in enumerate(cards):
                    card.configure(text=f'{i+1}  —', bg='#24324c', fg=muted)
                scores_text.set('Collecting fresh frames…')
            elif kind == 'progress':
                elapsed, count = value
                if elapsed is not None:
                    status.set(f'Checking… {max(0, 2-elapsed):.1f}s')
                    progress['value'] = min(elapsed, 2)
                detail.set(f'{count} valid scores collected')
            elif kind == 'result':
                outcome, sampled, high, elapsed, count = value
                status.set(outcome)
                status_label.configure(fg={'APPROVED':'#34d399','REJECTED':'#fb7185'}.get(outcome,'#fbbf24'))
                timing = f'{elapsed:.3f}s measured' if elapsed is not None else 'No single face detected'
                detail.set(f'{timing} • {high}/{len(sampled)} above 0.85 • {count} scores available')
                progress['value'] = 2
                for i, card in enumerate(cards):
                    if i < len(sampled):
                        value = sampled[i]
                        color = '#34d399' if value > .85 else '#fb7185' if value < .75 else '#fbbf24'
                        card.configure(text=f'{i+1}  {value:.4f}', fg=color)
                scores_text.set('Scores are not probabilities' if sampled else 'Not enough valid frames')
                button.configure(state='normal', text='↻  Run again')
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
