#!/usr/bin/env python3
"""Generate real-NPU experiment summaries.

The formal report consumes only CSV files produced by real Ascend NPU scripts.
Fake-backend fixtures are intentionally not part of this summary.
"""

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


FIELDS = [
    "experiment_id",
    "scheduler",
    "source_file",
    "window",
    "total_requests",
    "total_errors",
    "error_rate_pct",
    "qps",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "target_backend",
    "target_share_pct",
    "expected_share_pct",
    "absolute_share_error_pct",
    "backend_distribution",
    "main_conclusion",
    "notes",
]


def load_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_success(row):
    status = str(row.get("status", "0"))
    error = row.get("error", "")
    return status.isdigit() and 200 <= int(status) < 300 and not error


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, math.ceil(len(values) * pct) - 1))
    return round(values[index], 2)


def per_second(rows):
    if not rows:
        return {}
    start = min(safe_float(row.get("ts")) for row in rows)
    buckets = defaultdict(lambda: {"rows": [], "backends": Counter(), "errors": 0})
    for row in rows:
        second = int(safe_float(row.get("ts")) - start)
        backend = row.get("backend", "")
        buckets[second]["rows"].append(row)
        buckets[second]["backends"][backend] += 1
        if not is_success(row):
            buckets[second]["errors"] += 1
    return buckets


def window_stats(rows, start_sec=None, end_sec=None, target_backend="", expected_share=None):
    if not rows:
        return {
            "total_requests": 0,
            "total_errors": 0,
            "error_rate_pct": 0.0,
            "qps": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "target_share_pct": "",
            "backend_distribution": "",
            "absolute_share_error_pct": "",
        }

    selected = rows
    elapsed = max(safe_float(rows[-1].get("ts")) - safe_float(rows[0].get("ts")), 0.001)
    if start_sec is not None and end_sec is not None:
        origin = safe_float(rows[0].get("ts"))
        selected = [
            row
            for row in rows
            if start_sec <= safe_float(row.get("ts")) - origin < end_sec
        ]
        elapsed = max(end_sec - start_sec, 1)

    latencies = [safe_float(row.get("latency_ms")) for row in selected if is_success(row)]
    errors = sum(1 for row in selected if not is_success(row))
    backend_counts = Counter(row.get("backend", "") for row in selected)
    total = len(selected)
    target_share = ""
    abs_error = ""
    if target_backend:
        target_share = round(backend_counts.get(target_backend, 0) / total * 100, 2) if total else 0.0
        if expected_share is not None:
            abs_error = round(abs(target_share - expected_share), 2)

    distribution = ";".join(
        f"{backend or 'none'}={count}({round(count / total * 100, 2) if total else 0}%)"
        for backend, count in sorted(backend_counts.items())
    )

    return {
        "total_requests": total,
        "total_errors": errors,
        "error_rate_pct": round(errors / total * 100, 4) if total else 0.0,
        "qps": round(total / elapsed, 2),
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "target_share_pct": target_share,
        "backend_distribution": distribution,
        "absolute_share_error_pct": abs_error,
    }


def make_row(results_dir, experiment_id, scheduler, filename, conclusion, notes="", window="all",
             start_sec=None, end_sec=None, target_backend="", expected_share=None):
    path = results_dir / filename
    rows = load_rows(path)
    stats = window_stats(rows, start_sec, end_sec, target_backend, expected_share)
    row = {
        "experiment_id": experiment_id,
        "scheduler": scheduler,
        "source_file": filename,
        "window": window,
        "target_backend": target_backend,
        "expected_share_pct": "" if expected_share is None else expected_share,
        "main_conclusion": conclusion,
        "notes": notes,
    }
    row.update(stats)
    return row


def collect_summaries(results_dir):
    summaries = []

    for scheduler, filename in [
        ("direct-npu3", "exp1-real-direct-npu3.csv"),
        ("swrr", "exp1-real-swrr.csv"),
        ("p2c_smooth_wrr", "exp1-real-p2c.csv"),
        ("balanced_p2c", "exp1-real-balanced.csv"),
    ]:
        summaries.append(make_row(
            results_dir, "exp1", scheduler, filename,
            "real NPU balanced baseline",
            "direct is a single-backend reference; router rows use five real backends",
        ))

    for scheduler, filename in [
        ("swrr", "exp2-real-hotspot-swrr.csv"),
        ("p2c_smooth_wrr", "exp2-real-hotspot-p2c.csv"),
        ("balanced_p2c", "exp2-real-hotspot-balanced.csv"),
    ]:
        summaries.append(make_row(
            results_dir, "exp2", scheduler, filename,
            "real hotspot pressure on qwen15b-npu3",
            "background pressure is direct long-prompt load against NPU3",
            target_backend="qwen15b-npu3",
        ))

    exp3_windows = [
        ("pre_0_30", 0, 30, None),
        ("transition_down_30_40", 30, 40, 2.44),
        ("stable_down_40_80", 40, 80, 2.44),
        ("transition_up_80_100", 80, 100, None),
        ("stable_up_100_120", 100, 120, 20.0),
        ("all", None, None, None),
    ]
    for window, start, end, expected in exp3_windows:
        summaries.append(make_row(
            results_dir, "exp3", "p2c_smooth_wrr", "exp3-real-capacity-p2c.csv",
            "capacity 10->1->10 smooth migration",
            "target backend qwen15b-npu3",
            window=window,
            start_sec=start,
            end_sec=end,
            target_backend="qwen15b-npu3",
            expected_share=expected,
        ))

    exp4_windows = [
        ("pre_fail_0_30", 0, 30, 20.0),
        ("fail_detect_30_35", 30, 35, 0.0),
        ("fail_stable_35_90", 35, 90, 0.0),
        ("recovery_wait_90_240", 90, 240, 0.0),
        ("recovery_end_240_300", 240, 300, 20.0),
        ("all", None, None, None),
    ]
    for window, start, end, expected in exp4_windows:
        summaries.append(make_row(
            results_dir, "exp4", "p2c_smooth_wrr", "exp4-real-failure-p2c.csv",
            "npu5 container stop/start fault recovery",
            "only container yijq27-vllm-qwen15b-5 is stopped",
            window=window,
            start_sec=start,
            end_sec=end,
            target_backend="qwen15b-npu5",
            expected_share=expected,
        ))

    summaries.append(make_row(
        results_dir, "exp5", "p2c_smooth_wrr", "exp5-real-default.csv",
        "default pool remains isolated while isolated pool is under pressure",
        "default pool uses NPU3/4",
    ))
    summaries.append(make_row(
        results_dir, "exp5", "p2c_smooth_wrr", "exp5-real-isolated.csv",
        "isolated pool noisy-neighbor load runs on real NPU5/6/7",
        "isolated pool uses NPU5/6/7",
    ))

    summaries.append(make_row(
        results_dir, "exp6", "p2c_smooth_wrr", "exp6-real-comprehensive.csv",
        "combined dynamic capacity, hotspot, fault, and recovery scenario",
        "demo scenario; interpret with windowed CSV if used in report",
    ))

    for step in ["0.1", "0.25", "0.5", "1.0"]:
        for window, start, end, expected in [
            ("pre_0_20", 0, 20, 20.0),
            ("transition_down_20_30", 20, 30, 2.44),
            ("stable_down_30_50", 30, 50, 2.44),
            ("transition_up_50_65", 50, 65, None),
            ("stable_up_65_80", 65, 80, 20.0),
            ("all", None, None, None),
        ]:
            summaries.append(make_row(
                results_dir, "exp7", f"smooth_step={step}", f"exp7-real-ss{step}.csv",
                "smoothStep sensitivity on five real backends",
                "target backend qwen15b-npu3",
                window=window,
                start_sec=start,
                end_sec=end,
                target_backend="qwen15b-npu3",
                expected_share=expected,
            ))

    return [row for row in summaries if row["total_requests"]]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write("# Real NPU Experiment Summary\n\n")
        file.write("All rows are generated from real Ascend NPU experiment CSV files. Fake-backend fixture data is excluded.\n\n")
        file.write("| experiment | scheduler | window | requests | errors | qps | p50 | p95 | p99 | target share | conclusion |\n")
        file.write("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for row in rows:
            target_share = row["target_share_pct"] if row["target_share_pct"] != "" else "-"
            file.write(
                f"| {row['experiment_id']} | {row['scheduler']} | {row['window']} | "
                f"{row['total_requests']} | {row['total_errors']} | {row['qps']} | "
                f"{row['p50_ms']} | {row['p95_ms']} | {row['p99_ms']} | "
                f"{target_share} | {row['main_conclusion']} |\n"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="bench/results")
    parser.add_argument("--output-dir", default="analysis-output")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)
    rows = collect_summaries(results_dir)
    write_csv(output_dir / "real_npu_summary.csv", rows)
    write_markdown(output_dir / "real_npu_summary.md", rows)
    print(f"written {output_dir / 'real_npu_summary.csv'} with {len(rows)} rows")
    print(f"written {output_dir / 'real_npu_summary.md'}")


if __name__ == "__main__":
    main()
