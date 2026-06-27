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
    "max_target_running",
    "max_target_waiting",
    "max_target_kv_cache_usage",
    "max_target_remote_utilization",
    "max_target_queue_depth",
    "max_target_router_kv_cache_usage",
    "backend_distribution",
    "main_conclusion",
    "notes",
]


def resolve_result_file(results_dir, filename):
    direct = results_dir / filename
    if direct.exists():
        return direct
    matches = sorted(path for path in results_dir.rglob(filename) if path.is_file())
    if matches:
        return matches[0]
    return direct


def display_path(results_dir, path, fallback):
    if path.exists():
        try:
            return str(path.relative_to(results_dir))
        except ValueError:
            return str(path)
    return fallback


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
    path = resolve_result_file(results_dir, filename)
    rows = load_rows(path)
    stats = window_stats(rows, start_sec, end_sec, target_backend, expected_share)
    row = {
        "experiment_id": experiment_id,
        "scheduler": scheduler,
        "source_file": display_path(results_dir, path, filename),
        "window": window,
        "target_backend": target_backend,
        "expected_share_pct": "" if expected_share is None else expected_share,
        "main_conclusion": conclusion,
        "notes": notes,
    }
    row.update(stats)
    return row


def metrics_signal_stats(results_dir, filename, backend_id):
    path = resolve_result_file(results_dir, filename)
    rows = load_rows(path)
    if not rows:
        return {}

    selected = [row for row in rows if row.get("backend_id") == backend_id]
    if not selected:
        return {}

    return {
        "max_target_running": max(safe_float(row.get("num_requests_running")) for row in selected),
        "max_target_waiting": max(safe_float(row.get("num_requests_waiting")) for row in selected),
        "max_target_kv_cache_usage": round(max(safe_float(row.get("kv_cache_usage")) for row in selected), 6),
        "max_target_remote_utilization": round(max(safe_float(row.get("router_remote_utilization")) for row in selected), 6),
        "max_target_queue_depth": round(max(safe_float(row.get("router_queue_depth")) for row in selected), 6),
        "max_target_router_kv_cache_usage": round(max(safe_float(row.get("router_kv_cache_usage")) for row in selected), 6),
    }


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
            "真实 NPU 均衡基线",
            "direct 是单后端参考；router 行使用五个真实后端",
        ))

    for scheduler, filename in [
        ("swrr", "exp2-real-hotspot-swrr.csv"),
        ("p2c_smooth_wrr", "exp2-real-hotspot-p2c.csv"),
        ("balanced_p2c", "exp2-real-hotspot-balanced.csv"),
    ]:
        row = make_row(
            results_dir, "exp2", scheduler, filename,
            "qwen15b-npu3 真实热点压力",
            "背景压力是直接打到 NPU3 的长 prompt 请求",
            target_backend="qwen15b-npu3",
        )
        metric_tag = scheduler
        if scheduler == "p2c_smooth_wrr":
            metric_tag = "p2c"
        if scheduler == "balanced_p2c":
            metric_tag = "balanced"
        row.update(metrics_signal_stats(results_dir, f"exp2-real-hotspot-{metric_tag}-metrics.csv", "qwen15b-npu3"))
        summaries.append(row)

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
            "capacity 10->1->10 平滑迁移",
            "目标后端 qwen15b-npu3",
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
            "NPU5 容器 stop/start 故障恢复",
            "只停止 yijq27-vllm-qwen15b-5 容器",
            window=window,
            start_sec=start,
            end_sec=end,
            target_backend="qwen15b-npu5",
            expected_share=expected,
        ))

    summaries.append(make_row(
        results_dir, "exp5", "p2c_smooth_wrr", "exp5-real-default.csv",
        "isolated 池承压时 default 池保持隔离",
        "default 池使用 NPU3/4",
    ))
    summaries.append(make_row(
        results_dir, "exp5", "p2c_smooth_wrr", "exp5-real-isolated.csv",
        "isolated 池 noisy-neighbor 负载运行在真实 NPU5/6/7",
        "isolated 池使用 NPU5/6/7",
    ))

    summaries.append(make_row(
        results_dir, "exp6", "p2c_smooth_wrr", "exp6-real-comprehensive.csv",
        "组合动态 capacity、热点、故障和恢复的综合场景",
        "演示场景；报告中使用时应结合分窗口 CSV 解读",
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
                "五个真实后端上的 smoothStep 敏感性",
                "目标后端 qwen15b-npu3",
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
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write("# 真实 NPU 实验汇总\n\n")
        file.write("所有行均由真实 Ascend NPU 实验 CSV 生成，不包含 fake backend 开发夹具数据。\n\n")
        file.write("| 实验 | 调度器 | 窗口 | 请求数 | 错误数 | QPS | p50 | p95 | p99 | 目标占比 | 结论 |\n")
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
