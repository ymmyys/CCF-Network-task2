#!/usr/bin/env python3
import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, math.ceil(len(values) * pct) - 1))
    return values[index]


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def summarize(rows):
    if not rows:
        return []
    start = min(float(row["ts"]) for row in rows)
    buckets = defaultdict(list)
    backend_counts = defaultdict(Counter)
    for row in rows:
        bucket = int(float(row["ts"]) - start)
        latency = float(row["latency_ms"])
        buckets[bucket].append(latency)
        backend_counts[bucket][row.get("backend", "")] += 1

    summary = []
    for bucket in sorted(buckets):
        values = buckets[bucket]
        summary.append(
            {
                "second": bucket,
                "qps": len(values),
                "p50_ms": percentile(values, 0.50),
                "p95_ms": percentile(values, 0.95),
                "backends": json_like_counts(backend_counts[bucket]),
            }
        )
    return summary


def json_like_counts(counter):
    return ";".join(f"{key or 'none'}={value}" for key, value in sorted(counter.items()))


def write_summary(path, summary):
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["second", "qps", "p50_ms", "p95_ms", "backends"])
        writer.writeheader()
        writer.writerows(summary)


def plot(summary, output):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    seconds = [row["second"] for row in summary]
    qps = [row["qps"] for row in summary]
    p50 = [row["p50_ms"] for row in summary]
    p95 = [row["p95_ms"] for row in summary]

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(seconds, qps, label="QPS")
    axes[0].set_ylabel("QPS")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    axes[1].plot(seconds, p50, label="p50")
    axes[1].plot(seconds, p95, label="p95")
    axes[1].set_xlabel("second")
    axes[1].set_ylabel("latency ms")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(output, dpi=160)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="bench/results.png")
    args = parser.parse_args()

    rows = load_rows(args.input)
    summary = summarize(rows)
    summary_path = str(Path(args.input).with_suffix(".summary.csv"))
    write_summary(summary_path, summary)
    if plot(summary, args.output):
        print(f"wrote {args.output} and {summary_path}")
    else:
        print(f"matplotlib not installed; wrote {summary_path}")


if __name__ == "__main__":
    main()
