"""Run MiniFASNet preprocessing ablations on a saved, labeled calibration set."""
import argparse
import contextlib
import csv
from pathlib import Path

import cv2
import numpy as np

from pipeline import passive_liveness
from pipeline.frames import decode
from pipeline.silentface import REAL_CLASS, SF_DIR, get

from passive_sanity import compare

CLASSES = ("real", "print", "phone")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CONFIGS = (
    "Pipeline as-is", "Original gate scorer", "Official detector + CropImage",
    "RGB input", "V2 alone", "V1SE alone", "Explicit ensemble",
    "Gamma 0.7", "CLAHE luminance",
)


def load_inputs(root):
    images = {}
    for label in CLASSES:
        images[label] = sorted(
            path for path in (root / label).glob("*")
            if path.is_file() and path.suffix.lower() in EXTENSIONS
        )
        if not images[label]:
            raise ValueError(f"no gate images in {root / label}")
    return images


def official_detector():
    from src.anti_spoof_predict import Detection

    with contextlib.chdir(SF_DIR):
        return Detection()


def score_models(sf, image, box, cropper):
    scores = {}
    for name, model, height, width, scale in sf.models:
        patch = cropper.crop(image, box, scale, width, height, crop=scale is not None)
        with sf._torch.inference_mode():
            logits = model(sf._transform(patch).unsqueeze(0))
            scores["V1SE alone" if "V1SE" in name else "V2 alone"] = float(
                sf._F.softmax(logits, dim=1)[0, REAL_CLASS]
            )
    return {**scores, "Explicit ensemble": float(np.mean(list(scores.values())))}


def score_frame(sf, upstream, cropper, clahe, lookup, image, data):
    native = passive_liveness([data])
    if native["status"] == "UNAVAILABLE":
        raise RuntimeError(native.get("reason", "passive pipeline unavailable"))
    gate = sf.predict(image)
    official_box = upstream.get_bbox(image)
    scores = dict.fromkeys(CONFIGS)
    scores.update({
        "Pipeline as-is": native["score"],
        "Original gate scorer": gate["live_score"],
        "Official detector + CropImage":
            score_models(sf, image, official_box, cropper)["Explicit ensemble"],
    })
    box = native["per_frame"][0].get("bbox")
    if box is not None:
        scores.update(score_models(sf, image, box, cropper))
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        variants = {
            "RGB input": cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
            "Gamma 0.7": cv2.LUT(image, lookup),
            "CLAHE luminance": cv2.cvtColor(lab, cv2.COLOR_LAB2BGR),
        }
        for name, adjusted in variants.items():
            scores[name] = sf.predict(adjusted, box)["live_score"]
    return box, official_box, scores


def split_counts(records, config, threshold):
    return {
        label: (
            sum(r[config] is not None and r[config] >= threshold for r in records
                if r["class"] == label),
            sum(r["class"] == label for r in records),
        )
        for label in CLASSES
    }


def threshold_summary(records, config):
    # Fit only on scored frames. Missing scores cannot support separation.
    scored = [r for r in records if r[config] is not None]
    levels = sorted({r[config] for r in scored})
    if not levels or set(r["class"] for r in scored) != set(CLASSES):
        return None
    thresholds = [0.0, *((a + b) / 2 for a, b in zip(levels, levels[1:])),
                  float(np.nextafter(levels[-1], np.inf))]
    choices = []
    for cutoff in thresholds:
        counts = split_counts(scored, config, cutoff)
        real, print_, phone = (counts[label] for label in CLASSES)
        genuine_pass = real[0] / real[1]
        spoof_catch = 1 - (print_[0] + phone[0]) / (print_[1] + phone[1])
        worst = min(genuine_pass, 1 - print_[0] / print_[1], 1 - phone[0] / phone[1])
        choices.append((genuine_pass + spoof_catch, worst, cutoff, counts))
    return max(choices, key=lambda choice: choice[:3])


def box_iou(first, second):
    if first is None:
        return "NA"
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    overlap = (
        max(0, min(ax + aw, bx + bw) - max(ax, bx))
        * max(0, min(ay + ah, by + bh) - max(ay, by))
    )
    return f"{overlap / (aw * ah + bw * bh - overlap):.4f}"


def stat_cell(records, config, label, counts):
    values = [r[config] for r in records if r["class"] == label and r[config] is not None]
    passed, n = counts[label]
    summary = f"{np.mean(values):.4f}/{min(values):.4f}/{max(values):.4f}" if values else "NA"
    return f"{passed}/{n}; {summary}; scored {len(values)}"


def correlation(rows, config):
    pairs = [(r["width_px"], r[config]) for r in rows
             if r["width_px"] is not None and r[config] is not None]
    if len(pairs) < 3:
        return f"NA (n={len(pairs)})"
    widths, scores = np.asarray(pairs).T
    if not np.ptp(widths) or not np.ptp(scores):
        return f"NA (n={len(pairs)})"
    return f"{np.corrcoef(widths, scores)[0, 1]:+.3f} (n={len(pairs)})"


def write_report(out, records, high):
    lines = [
        "# Gate ablation results", "",
        f"Fixed pass rule for all rows: score ≥ {high:g}. Each cell is passed/total, "
        "mean/min/max, then the number scored. Spoof passes are errors. "
        "Unscored images cannot pass and do not enter score statistics or threshold fitting.",
        "",
        "| Configuration | Real | Print | Phone | Fitted threshold | Genuine pass + spoof catch |",
        "|---|---|---|---|---:|---:|",
    ]
    fits = {}
    for config in CONFIGS:
        fixed = split_counts(records, config, high)
        cells = [stat_cell(records, config, label, fixed) for label in CLASSES]
        fit = threshold_summary(records, config)
        if fit is not None:
            fits[config] = fit
        fit_cells = [f"{fit[2]:.9g}", f"{fit[0]:.4f}"] if fit else ["NA", "NA"]
        lines.append("| " + " | ".join([config, *cells, *fit_cells]) + " |")
    lines += ["", "## Detector comparison", "",
              "| Frame | Pipeline (x, y, w, h) | Upstream (x, y, w, h) | IoU |",
              "|---|---|---|---:|"]
    for label in CLASSES:
        row = next(r for r in records if r["class"] == label)
        lines.append(f"| {row['frame']} | {row['box']} | {row['official_box']} | "
                     f"{box_iou(row['box'], row['official_box'])} |")
    lines += ["", "## Face width and score", "", "| Class | Pearson r |", "|---|---|"]
    for label in (*CLASSES, "all"):
        rows = records if label == "all" else [r for r in records if r["class"] == label]
        lines.append(f"| {label} | {correlation(rows, 'Pipeline as-is')} |")
    if fits:
        best = max(fits, key=lambda config: fits[config][:2])
        score, worst, cutoff, counts = fits[best]
        lines += ["", "## Best fit on this batch", "",
                  f"{best}, cutoff {cutoff:.9g}, objective {score:.4f}/2 and "
                  f"worst class correct rate {worst:.1%} among scored frames.",
                  "Passes among scored frames: " + ", ".join(
                      f"{label} {k}/{n}" for label, (k, n) in counts.items()) + ".",
                  "Thresholds maximize the sum of the genuine pass rate and pooled spoof catch "
                  "rate. Ties prefer the better worst-class rate, then the higher threshold.",
                  "Calibration only. Re-check on independent frames before changing any flag."]
        plot(out, records, best, cutoff)
    (out / "gate_ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (out / "gate_scores.csv").open("w", encoding="utf-8", newline="") as file:
        columns = ["frame", "class", "width_px", "box", "official_box", *CONFIGS]
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def plot(out, records, best, cutoff):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    scores = [r[best] for r in records if r[best] is not None]
    low, high = min(scores), max(scores)
    bins = np.linspace(max(0, low - 0.005), min(1, high + 0.005), 26)
    for axis, label, color in zip(axes, CLASSES, ("#16745a", "#b34926", "#385c9e")):
        values = [r[best] for r in records if r["class"] == label and r[best] is not None]
        axis.hist(values, bins=bins, color=color)
        axis.axvline(cutoff, color="#262626", linestyle="--")
        axis.set_title(f"{label} · n={len(values)}", loc="left")
        axis.set_ylabel("Frames")
    axes[-1].set_xlabel("MiniFASNet live score")
    fig.suptitle(f"{best} · fitted threshold {cutoff:.5f} · calibration only")
    fig.tight_layout()
    fig.savefig(out / "gate_scores.png", dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    for name, official, result, matched in compare():
        print(f"{name}: {official} Passive {result['status']} {result['score']}.")
        if not matched:
            parser.exit(1, f"Stopped at sample mismatch: {result}\n")
    try:
        sources = load_inputs(args.gate)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    sf = get()
    from src.generate_patches import CropImage
    from pipeline.config import PASSIVE_HIGH

    upstream = official_detector()
    cropper = CropImage()
    lookup = np.rint(255 * (np.arange(256) / 255) ** 0.7).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    records = []
    for label, paths in sources.items():
        for number, path in enumerate(paths, 1):
            data = path.read_bytes()
            image = decode(data)
            if image is None:
                parser.exit(2, f"Unreadable image {label}/{number}\n")
            box, official_box, scores = score_frame(sf, upstream, cropper, clahe, lookup, image, data)
            records.append({"frame": f"{label}/{number:02}", "class": label,
                            "width_px": box[2] if box is not None else None,
                            "box": box, "official_box": official_box, **scores})
    args.out.mkdir(parents=True, exist_ok=True)
    write_report(args.out, records, PASSIVE_HIGH)


if __name__ == "__main__":
    main()
