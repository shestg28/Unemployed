"""Report one evaluation session from the kiosk decision log."""

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

SCENARIOS = (
    "genuine", "impostor", "print", "phone", "replay",
    "mask_no_cutout", "mask_cutout", "bad_light",
)
ATTACKS = SCENARIOS[2:7]
OUTCOMES = ("ALLOW", "REQUEST", "DENY")
PHASES = ("first_pass", "challenge")
SESSIONS = ("A", "B")
ROOT = Path(__file__).resolve().parent.parent
LIMIT_MS = 2000
COLUMNS = ("scope", "metric", "value", "unit", "n", "numerator")


def read_attempts(path, session, untagged_session):
    grouped = {}
    seen_sessions = set()
    skipped = Counter()
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number}: expected a JSON object")
            tag = record.get("session")
            if tag is not None and tag not in SESSIONS:
                raise ValueError(f"line {line_number}: invalid session tag")
            if tag is None and untagged_session is None:
                skipped["untagged rows"] += 1
                continue
            tag = tag if tag is not None else untagged_session
            seen_sessions.add(tag)
            if tag != session:
                continue
            scenario = record.get("scenario")
            if scenario not in SCENARIOS:
                skipped["rows with missing or unknown scenario"] += 1
                continue
            if record.get("stubs"):
                raise ValueError(f"line {line_number}: selected session used a stub")
            attempt_id = record.get("attempt_id")
            phase = record.get("phase")
            decision = record.get("decision")
            if decision == "REQUEST_VERIFICATION":
                decision = "REQUEST"
            if not isinstance(attempt_id, str) or not attempt_id.strip():
                raise ValueError(f"line {line_number}: missing attempt_id")
            if phase not in PHASES or decision not in OUTCOMES:
                raise ValueError(f"line {line_number}: invalid phase or decision")
            attempt = grouped.setdefault(attempt_id, {"scenario": scenario})
            if scenario != attempt["scenario"] or phase in attempt:
                raise ValueError(f"line {line_number}: conflicting or duplicate decision")
            attempt[phase] = {"decision": decision, "record": record}

    if untagged_session and seen_sessions - {untagged_session}:
        raise ValueError("--untagged-session requires a log dedicated to that session")

    attempts = []
    for attempt_id, attempt in grouped.items():
        first = attempt.get("first_pass")
        challenge = attempt.get("challenge")
        if not first or (challenge and first["decision"] != "REQUEST"):
            raise ValueError(f"attempt {attempt_id}: inconsistent decision phases")
        last = challenge or first
        first_ms = read_time(first["record"], "first_pass_ms", attempt_id)
        total_ms = None
        if challenge or last["decision"] != "REQUEST":
            total_ms = read_time(last["record"], "total_ms", attempt_id)
        if first_ms is not None and total_ms is not None and total_ms < first_ms:
            raise ValueError(f"attempt {attempt_id}: total time precedes first decision")
        attempts.append({
            "scenario": attempt["scenario"],
            "first": first["decision"],
            "last": last["decision"],
            "allowed": any(phase["decision"] == "ALLOW" for phase in (first, last)),
            "first_ms": first_ms,
            "total_ms": total_ms,
        })
    return attempts, skipped


def read_time(record, field, attempt_id):
    value = record.get(field)
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"attempt {attempt_id}: invalid {field}")
    return value


def summaries(attempts):
    rows = []

    def ratio(scope, name, numerator, n):
        percent = 100 * numerator / n if n else None
        rows.append((scope, name, percent, "%", n, numerator))

    for scope in (*SCENARIOS, "all"):
        subset = attempts if scope == "all" else [
            item for item in attempts if item["scenario"] == scope
        ]
        for phase, label in (("last", "Final"), ("first", "First pass")):
            counts = Counter(item[phase] for item in subset)
            for outcome in OUTCOMES:
                count = counts[outcome]
                rows.append((scope, f"{label} {outcome}", count, "count", len(subset), count))
        for field, label in (("first_ms", "First-pass time"), ("total_ms", "Total time")):
            times = sorted(item[field] for item in subset if item[field] is not None)
            n = len(times)
            median = statistics.median(times) if n else None
            p95 = times[math.ceil(0.95 * n) - 1] if n else None
            rows.append((scope, f"{label} median", median, "ms", n, None))
            rows.append((scope, f"{label} p95", p95, "ms", n, None))
            if field == "first_ms":
                mean = statistics.mean(times) if n else None
                rows.append((scope, f"{label} mean", mean, "ms", n, None))
                ratio(scope, "First-pass time ≤2 s", sum(t <= LIMIT_MS for t in times), n)

    for scope, cases in [(name, (name,)) for name in ATTACKS] + [("attacks", ATTACKS)]:
        subset = [item for item in attempts if item["scenario"] in cases]
        held = [item for item in subset if not item["allowed"]]
        ratio(scope, "Attack detection rate (access prevented)", len(held), len(subset))
        ratio(scope, "DENY-only rate", sum(item["last"] == "DENY" for item in held), len(subset))

    unauthorized = [item for item in attempts if item["scenario"] in (*ATTACKS, "impostor")]
    ratio("attacks + impostor", "False accept rate (FAR)",
          sum(item["allowed"] for item in unauthorized), len(unauthorized))
    genuine = [item for item in attempts if item["scenario"] == "genuine"]
    ratio("genuine", "False reject rate (FRR)",
          sum(item["first"] == "DENY" for item in genuine), len(genuine))
    ratio("genuine", "Genuine step-up rate",
          sum(item["first"] == "REQUEST" for item in genuine), len(genuine))
    ratio("genuine", "Final genuine DENY rate",
          sum(item["last"] == "DENY" for item in genuine), len(genuine))
    ratio("genuine", "Final genuine REQUEST rate",
          sum(item["last"] == "REQUEST" for item in genuine), len(genuine))
    return rows


def markdown(session, attempts, rows, skipped):
    purpose = "threshold setting" if session == "A" else "reported results"
    lines = [f"# HID evaluation · Session {session} ({purpose})", "",
             "## Final decision counts", "",
             "| Scenario | ALLOW | REQUEST | DENY | n |",
             "|---|---:|---:|---:|---:|"]
    for scope in (*SCENARIOS, "all"):
        final = [row for row in rows if row[0] == scope and row[1].startswith("Final ")
                 and row[3] == "count"]
        cells = [scope, *(str(row[2]) for row in final), str(final[0][4])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Rates and timing", "",
                  "| Scope | Metric | Value | Numerator | n |",
                  "|---|---|---:|---:|---:|"])
    for scope, name, value, unit, n, numerator in rows:
        if unit == "count":
            continue
        display = "—" if value is None else f"{value:.2f} {unit}"
        count = "—" if numerator is None else str(numerator)
        lines.append(f"| {scope} | {name} | {display} | {count} | {n} |")

    lines.extend(["", "First-pass and total durations are server timings. P95 is nearest rank.",
                  "REQUEST holds access. The attack detection rate measures how often access "
                  "was prevented. DENY-only measures final DENY with no ALLOW.",
                  "Total time excludes attempts with an open REQUEST and no measured follow-up."])
    if not attempts:
        lines.append(f"No eligible attempts were found for Session {session}.")
    for reason, count in sorted(skipped.items()):
        lines.append(f"Excluded {count} {reason}.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", choices=SESSIONS, required=True)
    parser.add_argument("--untagged-session", choices=SESSIONS,
                        help="Explicit session of an isolated, single-session source log")
    parser.add_argument("--log", type=Path, default=ROOT / "logs" / "attempts.jsonl")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "eval")
    args = parser.parse_args()
    if args.untagged_session and args.untagged_session != args.session:
        parser.error("--untagged-session must match --session")
    try:
        attempts, skipped = read_attempts(args.log, args.session, args.untagged_session)
        rows = summaries(attempts)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        basename = f"results-{args.session}"
        md_path = args.out_dir / f"{basename}.md"
        csv_path = args.out_dir / f"{basename}.csv"
        md_path.write_text(markdown(args.session, attempts, rows, skipped), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("session", *COLUMNS))
            writer.writerows((args.session, *row) for row in rows)
    except (OSError, ValueError) as error:
        print(f"results: {error}", file=sys.stderr)
        return 1
    print(f"{md_path}\n{csv_path}")
    if not attempts:
        print(f"No eligible Session {args.session} attempts.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
