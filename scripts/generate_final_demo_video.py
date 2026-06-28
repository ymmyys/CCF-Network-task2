#!/usr/bin/env python3
"""Generate the final evidence-first prototype demo video.

The video is built from checked-in real Ascend NPU experiment artifacts:
summary CSV, router /admin/state snapshots, router /metrics snapshots and
npu-smi text captures. It does not connect to the remote host, start containers
or occupy NPU cards.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "bench/results/formal"
SUMMARY_CSV = FORMAL / "analysis/real_npu_summary.csv"
DEMO_DIR = ROOT / "docs/demo/submission"
FINAL_VIDEO = DEMO_DIR / "prototype-demo-final.mp4"
NARRATION_TEXT = DEMO_DIR / "prototype-demo-final-narration.txt"
SRT_OUT = DEMO_DIR / "prototype-demo-final.srt"
COVER_OUT = DEMO_DIR / "prototype-demo-final-cover.png"

W, H = 1920, 1080
FPS = 12

C = {
    "bg": "#f6f8fb",
    "panel": "#ffffff",
    "ink": "#0f172a",
    "muted": "#5f6b7a",
    "line": "#d8e0ea",
    "terminal": "#111827",
    "terminal2": "#0b1220",
    "cyan": "#0786a6",
    "blue": "#2563eb",
    "green": "#0f8b6f",
    "amber": "#c47a00",
    "red": "#c2413b",
    "soft_cyan": "#e8f7fb",
    "soft_green": "#e8f7f1",
    "soft_amber": "#fff5df",
    "soft_red": "#fff0ee",
}


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []
    if mono:
        candidates = [
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    elif bold:
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for item in candidates:
        p = Path(item)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size, index=1 if bold and p.suffix == ".ttc" else 0)
            except OSError:
                continue
    return ImageFont.load_default()


F = {
    "eyebrow": font(24, True),
    "title": font(56, True),
    "subtitle": font(28),
    "h2": font(34, True),
    "body": font(25),
    "body_bold": font(25, True),
    "small": font(19),
    "tiny": font(16),
    "mono": font(19, mono=True),
    "mono_small": font(15, mono=True),
}


@dataclass
class Scene:
    key: str
    eyebrow: str
    title: str
    subtitle: str
    narration: str
    caption: str
    draw: Callable[[ImageDraw.ImageDraw, float, dict[str, object]], None]
    fallback_duration: float


def load_rows() -> list[dict[str, str]]:
    with SUMMARY_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick(rows: list[dict[str, str]], exp: str, scheduler: str, window: str = "all", source: str | None = None) -> dict[str, str]:
    for item in rows:
        if item["experiment_id"] != exp or item["scheduler"] != scheduler or item["window"] != window:
            continue
        if source and source not in item["source_file"]:
            continue
        return item
    raise KeyError((exp, scheduler, window, source))


def fmt(value: str | float, suffix: str = "", digits: int = 2) -> str:
    if value == "":
        return "-"
    number = float(value)
    if math.isclose(number, round(number), abs_tol=1e-9):
        text = f"{int(round(number)):,}"
    else:
        text = f"{number:.{digits}f}"
    return f"{text}{suffix}"


def state_rows(path: Path, fields: tuple[str, ...] = ("id", "phase", "capacity", "effective_weight", "remote_utilization", "healthy")) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, object]] = []
    for pool in data.get("pools", []):
        for backend in pool.get("backends", []):
            row = {"pool": pool.get("name", "")}
            for field in fields:
                row[field] = backend.get(field)
            out.append(row)
    return out


def short_state_lines(path: str, limit: int = 7) -> list[str]:
    rows = state_rows(ROOT / path)
    lines = [f"$ jq backend-summary {path}"]
    for row in rows[:limit]:
        eff = row.get("effective_weight")
        remote = row.get("remote_utilization")
        lines.append(
            f"{row['id']:<17} phase={row['phase']:<8} cap={row['capacity']:<4} "
            f"eff={float(eff or 0):>5.2f} remote={float(remote or 0):>4.2f} healthy={str(row['healthy']).lower()}"
        )
    return lines


def npu_smi_excerpt() -> list[str]:
    text = (FORMAL / "system/npu-smi-before.txt").read_text(encoding="utf-8").splitlines()
    lines = ["$ npu-smi info  # formal/system/npu-smi-before.txt", "NPU  Health  Power  Temp  HBM-Usage(MB)  Process memory"]
    npu_lines: list[str] = []
    for i, line in enumerate(text):
        m = re.match(r"\| ([3-7])\s+910B3\s+\|\s+(OK)\s+\|\s+([0-9.]+)\s+([0-9]+)", line)
        if not m:
            continue
        npu, health, power, temp = m.groups()
        hbm = "?"
        if i + 1 < len(text):
            h = re.search(r"([0-9]+)\s*/\s*65536", text[i + 1])
            if h:
                hbm = h.group(1)
        npu_lines.append(f"NPU{npu:<2} {health:<6} power={power:>5}W temp={temp:>2}C hbm={hbm:>5}/65536")
    proc_lines = []
    for line in text:
        m = re.match(r"\| ([3-7])\s+0\s+\|\s+([0-9]+)\s+\|\s+\s*\|\s+([0-9]+)", line)
        if m:
            proc_lines.append(f"NPU{m.group(1)} pid={m.group(2)} mem={m.group(3)}MB")
    lines.extend(npu_lines)
    lines.extend(proc_lines[:5])
    return lines


def metrics_excerpt(path: str, backend: str, keys: tuple[str, ...]) -> list[str]:
    lines = [f"$ grep {backend} {Path(path).name} | grep metrics"]
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        if backend not in line:
            continue
        if any(key in line for key in keys):
            lines.append(line[:118])
    return lines[:9]


def summary() -> dict[str, object]:
    rows = load_rows()
    exp2_swrr = pick(rows, "exp2", "swrr")
    exp2_p2c = pick(rows, "exp2", "p2c_smooth_wrr")
    exp2_bal = pick(rows, "exp2", "balanced_p2c")
    exp3_down = pick(rows, "exp3", "p2c_smooth_wrr", "stable_down_40_80")
    exp3_all = pick(rows, "exp3", "p2c_smooth_wrr")
    exp3_up = pick(rows, "exp3", "p2c_smooth_wrr", "stable_up_100_120")
    exp4_fail = pick(rows, "exp4", "p2c_smooth_wrr", "fail_stable_35_90")
    exp4_up = pick(rows, "exp4", "p2c_smooth_wrr", "recovery_end_240_300")
    exp4_all = pick(rows, "exp4", "p2c_smooth_wrr")
    exp5_def = pick(rows, "exp5", "p2c_smooth_wrr", source="exp5-real-default.csv")
    exp5_iso = pick(rows, "exp5", "p2c_smooth_wrr", source="exp5-real-isolated.csv")
    exp8_swrr = pick(rows, "exp8", "swrr")
    exp8_p2c = pick(rows, "exp8", "p2c_smooth_wrr")
    exp8_bal = pick(rows, "exp8", "balanced_p2c")
    return {
        "exp2": {
            "swrr_share": float(exp2_swrr["target_share_pct"]),
            "p2c_share": float(exp2_p2c["target_share_pct"]),
            "bal_share": float(exp2_bal["target_share_pct"]),
            "swrr_p99": float(exp2_swrr["p99_ms"]),
            "p2c_p99": float(exp2_p2c["p99_ms"]),
            "bal_p99": float(exp2_bal["p99_ms"]),
            "remote": float(exp2_p2c["max_target_remote_utilization"]),
            "p2c_req": int(exp2_p2c["total_requests"]),
        },
        "exp3": {
            "series": [19.96, 6.08, float(exp3_down["target_share_pct"]), 10.22, float(exp3_up["target_share_pct"])],
            "expected": float(exp3_down["expected_share_pct"]),
            "errors": int(exp3_all["total_errors"]),
            "requests": int(exp3_all["total_requests"]),
            "share": float(exp3_down["target_share_pct"]),
        },
        "exp4": {
            "series": [20.06, float(exp4_fail["target_share_pct"]), float(exp4_up["target_share_pct"])],
            "errors": int(exp4_all["total_errors"]),
            "requests": int(exp4_all["total_requests"]),
        },
        "exp5": {
            "default_req": int(exp5_def["total_requests"]),
            "default_err": int(exp5_def["total_errors"]),
            "iso_req": int(exp5_iso["total_requests"]),
            "iso_p95": float(exp5_iso["p95_ms"]),
        },
        "exp8": {
            "swrr_share": float(exp8_swrr["target_share_pct"]),
            "p2c_share": float(exp8_p2c["target_share_pct"]),
            "bal_share": float(exp8_bal["target_share_pct"]),
            "swrr_qps": float(exp8_swrr["qps"]),
            "p2c_qps": float(exp8_p2c["qps"]),
            "bal_qps": float(exp8_bal["qps"]),
            "swrr_p99": float(exp8_swrr["p99_ms"]),
            "p2c_p99": float(exp8_p2c["p99_ms"]),
            "bal_p99": float(exp8_bal["p99_ms"]),
        },
        "npu": npu_smi_excerpt(),
        "exp2_state": short_state_lines("bench/results/formal/exp2-hotspot-load/exp2-p2c-end.state.json"),
        "exp3_state": short_state_lines("bench/results/formal/exp3-dynamic-capacity/exp3-stable-down.state.json"),
        "exp4_state": short_state_lines("bench/results/formal/exp4-failure-recovery/exp4-stable-fail.state.json"),
        "exp5_state": short_state_lines("bench/results/formal/exp5-pool-isolation/exp5-running.state.json", limit=6),
        "exp8_state": short_state_lines("bench/results/formal/exp8-qwen7b-hotspot/snapshots/exp8-qwen7b-p2c-end.state.json"),
        "exp2_metrics": metrics_excerpt(
            "bench/results/formal/exp2-hotspot-load/exp2-p2c-end.metrics.txt",
            "qwen15b-npu3",
            ("remote_utilization", "desired_weight", "effective_weight"),
        ),
        "exp4_metrics": metrics_excerpt(
            "bench/results/formal/exp4-failure-recovery/exp4-stable-fail.metrics.txt",
            "qwen15b-npu5",
            ("phase", "healthy", "effective_weight", "latency_ewma_ms"),
        ),
    }


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fnt: ImageFont.FreeTypeFont, fill: str = C["ink"], anchor: str | None = None) -> None:
    draw.text(xy, value, font=fnt, fill=fill, anchor=anchor)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, radius: int = 22, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap_text(value: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    buf = ""
    for ch in value:
        test = buf + ch
        if draw_measure(test, fnt) <= max_width or not buf:
            buf = test
        else:
            lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    return lines


def draw_measure(value: str, fnt: ImageFont.FreeTypeFont) -> int:
    box = fnt.getbbox(value)
    return box[2] - box[0]


def paragraph(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fnt: ImageFont.FreeTypeFont, fill: str, width: int, line_gap: int = 8) -> int:
    x, y = xy
    for line in wrap_text(value, fnt, width):
        text(draw, (x, y), line, fnt, fill)
        y += fnt.size + line_gap
    return y


def header(draw: ImageDraw.ImageDraw, scene: Scene, idx: int, total: int) -> None:
    text(draw, (86, 52), scene.eyebrow, F["eyebrow"], C["cyan"])
    text(draw, (86, 92), scene.title, F["title"], C["ink"])
    paragraph(draw, (88, 168), scene.subtitle, F["subtitle"], C["muted"], 1320, 8)
    draw.line((86, 238, 1834, 238), fill=C["line"], width=2)
    text(draw, (86, 1018), "suan-router / real Ascend NPU evidence video", F["tiny"], C["muted"])
    text(draw, (1834, 1018), f"{idx + 1:02d}/{total:02d}", F["tiny"], C["muted"], anchor="ra")


def terminal(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, lines: list[str], highlight: tuple[str, ...] = ()) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, C["terminal"], "#253044", radius=18, width=2)
    draw.rounded_rectangle((x1, y1, x2, y1 + 48), radius=18, fill=C["terminal2"])
    draw.rectangle((x1, y1 + 26, x2, y1 + 50), fill=C["terminal2"])
    for i, color in enumerate(("#ff5f57", "#ffbd2e", "#28c840")):
        draw.ellipse((x1 + 20 + i * 28, y1 + 18, x1 + 34 + i * 28, y1 + 32), fill=color)
    text(draw, (x1 + 118, y1 + 15), title, F["mono_small"], "#cbd5e1")
    y = y1 + 70
    max_chars = max(35, int((x2 - x1 - 42) / 10.5))
    for raw in lines:
        chunks = [raw[i:i + max_chars] for i in range(0, len(raw), max_chars)] or [""]
        for line in chunks:
            if y > y2 - 28:
                text(draw, (x1 + 22, y), "...", F["mono_small"], "#94a3b8")
                return
            color = "#e5e7eb"
            if line.startswith("$"):
                color = "#7dd3fc"
            if any(key in line for key in highlight):
                color = "#86efac"
            if "0.000000" in line or "drained" in line or "healthy=false" in line or "connection refused" in line:
                color = "#fca5a5"
            text(draw, (x1 + 22, y), line, F["mono_small"], color)
            y += 23


def kpi(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], value: str, label: str, color: str, sub: str = "") -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, C["panel"], C["line"], radius=18)
    draw.rectangle((x1, y1, x1 + 9, y2), fill=color)
    text(draw, (x1 + 28, y1 + 24), value, font(42, True), color)
    text(draw, (x1 + 30, y1 + 82), label, F["small"], C["ink"])
    if sub:
        text(draw, (x1 + 30, y1 + 112), sub, F["tiny"], C["muted"])


def bar_chart(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, rows: list[tuple[str, float, str, str]], max_value: float, title: str) -> None:
    text(draw, (x, y), title, F["h2"], C["ink"])
    y += 70
    for label, value, value_text, color in rows:
        text(draw, (x, y + 5), label, F["body_bold"], C["ink"])
        rounded(draw, (x + 175, y, x + width - 90, y + 32), "#e7edf5", None, radius=16, width=0)
        fill_w = max(5, int((width - 265) * min(value, max_value) / max_value))
        rounded(draw, (x + 175, y, x + 175 + fill_w, y + 32), color, None, radius=16, width=0)
        text(draw, (x + width - 55, y + 3), value_text, F["body_bold"], color, anchor="ra")
        y += 78


def line_chart(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], values: list[float], labels: list[str], title: str, color: str) -> None:
    x1, y1, x2, y2 = box
    text(draw, (x1, y1 - 54), title, F["h2"], C["ink"])
    plot = (x1 + 74, y1 + 20, x2 - 30, y2 - 54)
    px1, py1, px2, py2 = plot
    for val in (0, 10, 20):
        yy = py2 - (py2 - py1) * val / 22
        draw.line((px1, yy, px2, yy), fill="#e6edf5", width=2)
        text(draw, (px1 - 18, int(yy) - 10), f"{val}%", F["tiny"], C["muted"], anchor="ra")
    pts = []
    for i, val in enumerate(values):
        xx = px1 + (px2 - px1) * i / (len(values) - 1)
        yy = py2 - (py2 - py1) * val / 22
        pts.append((xx, yy))
    for a, b in zip(pts, pts[1:]):
        draw.line((*a, *b), fill=color, width=5)
    for (xx, yy), label, val in zip(pts, labels, values):
        draw.ellipse((xx - 7, yy - 7, xx + 7, yy + 7), fill=color)
        text(draw, (int(xx), py2 + 20), label, F["tiny"], C["muted"], anchor="ma")
        text(draw, (int(xx), int(yy) - 28), f"{val:.2f}%", F["tiny"], color, anchor="ma")


def draw_cover(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    terminal(draw, (88, 302, 1130, 820), "real evidence files", [
        "$ find bench/results/formal -name '*.state.json' | wc -l",
        "60+ router /admin/state snapshots",
        "$ ls bench/results/formal/system/npu-smi-*.txt",
        "npu-smi-before.txt  npu-smi-after.txt",
        "$ sed -n '1,12p' bench/results/formal/analysis/real_npu_summary.md",
        "all rows come from real Ascend NPU CSV; fake backend excluded",
        "$ find docs/demo/submission -maxdepth 1 -type f",
        "prototype-demo-final.mp4  prototype-demo-final.srt",
    ], ("真实", "state", "npu-smi"))
    kpi(draw, (1200, 316, 1720, 448), "5", "真实 Ascend NPU", C["cyan"], "NPU 3-7")
    kpi(draw, (1200, 484, 1720, 616), "60+", "/admin/state 快照", C["green"], "随实验入仓")
    kpi(draw, (1200, 652, 1720, 784), "0", "fake 主结论", C["red"], "只作开发夹具")


def draw_problem(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    terminal(draw, (86, 292, 1055, 835), "npu-smi snapshot", d["npu"], ("NPU3", "NPU4", "NPU5", "NPU6", "NPU7"))
    bar_chart(draw, 1130, 326, 610, [
        ("静态份额", 20.0, "20%", C["red"]),
        ("真实热点", 100.0, "100%", C["amber"]),
        ("空闲节点", 20.0, "仍等 20%", C["green"]),
    ], 120, "问题：静态轮询看不到热点")
    paragraph(draw, (1130, 650), "NPU 状态和 vLLM 队列会动态变化。静态轮询只知道节点列表，不知道哪个后端已经被外部长请求压住。", F["body"], C["muted"], 650)


def draw_router(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    terminal(draw, (86, 302, 1005, 812), "router inputs", [
        "$ curl http://127.0.0.1:8181/admin/state",
        "pool=default backends=qwen15b-npu3..npu7",
        "$ curl http://127.0.0.1:8181/metrics | grep router_backend",
        "signals: health capacity inflight remote_utilization queue_depth kv_cache latency_ewma",
        "$ curl -H 'X-Resource-Pool: isolated' /v1/chat/completions",
        "resource-pool isolation is selected by request header",
    ], ("signals", "resource-pool"))
    x = 1100
    rounded(draw, (x, 306, 1750, 785), C["panel"], C["line"])
    text(draw, (x + 44, 350), "调度闭环", F["h2"], C["ink"])
    steps = [
        ("观测", "health / metrics / inflight", C["cyan"]),
        ("计算", "desired = capacity × headroom", C["green"]),
        ("平滑", "effective += delta × smoothStep", C["amber"]),
        ("保护", "cooloff / drain / slow-start", C["red"]),
    ]
    for i, (name, desc, color) in enumerate(steps):
        y = 430 + i * 78
        draw.ellipse((x + 48, y, x + 84, y + 36), fill=color)
        text(draw, (x + 110, y - 2), name, F["body_bold"], color)
        text(draw, (x + 220, y), desc, F["small"], C["muted"])


def draw_exp2(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    e = d["exp2"]
    terminal(draw, (86, 300, 980, 825), "exp2 metrics evidence", d["exp2_metrics"], ("remote_utilization", "effective_weight"))
    bar_chart(draw, 1050, 314, 700, [
        ("SWRR", e["swrr_share"], f"{e['swrr_share']:.2f}%", C["red"]),
        ("P2C", e["p2c_share"], f"{e['p2c_share']:.2f}%", C["green"]),
        ("balanced", e["bal_share"], f"{e['bal_share']:.2f}%", C["cyan"]),
    ], 25, "NPU3 测量流量占比")
    kpi(draw, (1050, 690, 1378, 820), f"{e['remote']:.0f}", "max remote_utilization", C["amber"], "summary CSV")
    kpi(draw, (1415, 690, 1745, 820), f"{e['p2c_p99']:.2f}ms", "P2C p99", C["green"], f"SWRR {e['swrr_p99']:.2f}ms")


def draw_exp2_state(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    terminal(draw, (86, 292, 1110, 840), "exp2 /admin/state evidence", d["exp2_state"], ("qwen15b-npu3", "remote=0.65"))
    rounded(draw, (1185, 330, 1745, 790), C["panel"], C["line"])
    text(draw, (1228, 374), "解释这张状态快照", F["h2"], C["ink"])
    bullets = [
        ("NPU3", "remote utilization 明显高于其他节点", C["amber"]),
        ("desired/effective", "目标权重下降，实际权重平滑跟随", C["green"]),
        ("结果", "测量流量没有继续压到热点后端", C["cyan"]),
    ]
    y = 455
    for title, body, color in bullets:
        draw.ellipse((1228, y + 7, 1244, y + 23), fill=color)
        text(draw, (1264, y), title, F["body_bold"], color)
        text(draw, (1375, y + 2), body, F["small"], C["muted"])
        y += 82


def draw_exp3(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    e = d["exp3"]
    line_chart(draw, (96, 360, 1050, 800), e["series"], ["0s", "降容", "稳定", "恢复", "末段"], "capacity 10 -> 1 -> 10：目标节点占比", C["green"])
    terminal(draw, (1110, 306, 1780, 640), "exp3 stable-down state", d["exp3_state"][:5], ("cap=1", "eff= 0.96"))
    kpi(draw, (1110, 680, 1410, 812), f"{e['share']:.2f}%", "稳定降容占比", C["green"], f"理论 {e['expected']:.2f}%")
    kpi(draw, (1450, 680, 1780, 812), f"{e['errors']}", f"{e['requests']:,} 请求", C["cyan"], "错误数")


def draw_exp4(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    e = d["exp4"]
    terminal(draw, (86, 298, 1030, 835), "exp4 failure state + metrics", d["exp4_state"][:6] + d["exp4_metrics"][:5], ("qwen15b-npu5", "drained", "healthy=false"))
    line_chart(draw, (1100, 402, 1740, 718), e["series"], ["故障前", "故障期", "恢复末段"], "NPU5 流量占比", C["red"])
    kpi(draw, (1120, 745, 1430, 875), f"{e['errors']}", f"{e['requests']:,} 请求", C["red"], "全程错误数")
    kpi(draw, (1470, 745, 1778, 875), "0.02%", "故障稳定期", C["green"], "NPU5 已摘除")


def draw_exp5(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    e = d["exp5"]
    terminal(draw, (86, 300, 1050, 830), "exp5 resource-pool state", d["exp5_state"], ("pool", "default", "isolated"))
    rounded(draw, (1120, 330, 1760, 790), C["panel"], C["line"])
    text(draw, (1160, 376), "资源池隔离证据", F["h2"], C["ink"])
    kpi(draw, (1160, 455, 1710, 585), f"{e['default_req']:,}", "default 池请求", C["cyan"], f"{e['default_err']} 错误")
    kpi(draw, (1160, 625, 1710, 755), f"{e['iso_req']:,}", "isolated 池长请求承压", C["amber"], f"p95 {e['iso_p95']:.0f}ms")


def draw_exp8(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    e = d["exp8"]
    terminal(draw, (86, 302, 945, 825), "exp8 Qwen2.5-7B /admin/state", d["exp8_state"][:7], ("qwen7b-npu3", "remote=1.00"))
    bar_chart(draw, 1010, 314, 750, [
        ("SWRR", e["swrr_share"], f"{e['swrr_share']:.2f}%", C["red"]),
        ("P2C", e["p2c_share"], f"{e['p2c_share']:.2f}%", C["green"]),
        ("balanced", e["bal_share"], f"{e['bal_share']:.2f}%", C["cyan"]),
    ], 25, "7B 热点节点占比")
    text(draw, (1020, 650), f"QPS: SWRR {e['swrr_qps']:.2f} / P2C {e['p2c_qps']:.2f} / balanced {e['bal_qps']:.2f}", F["body"], C["ink"])
    text(draw, (1020, 705), f"p99: SWRR {e['swrr_p99']:.2f}ms / P2C {e['p2c_p99']:.2f}ms / balanced {e['bal_p99']:.2f}ms", F["body"], C["muted"])


def draw_close(draw: ImageDraw.ImageDraw, p: float, d: dict[str, object]) -> None:
    terminal(draw, (86, 302, 1100, 820), "submission evidence index", [
        "$ tree docs/demo/submission",
        "prototype-demo-final.mp4",
        "prototype-demo-final.srt",
        "prototype-demo-final-narration.txt",
        "prototype-evidence-video-guide.md",
        "suan-router-preliminary-demo-deck.pptx  # auxiliary, not the video body",
        "$ ls bench/results/formal/analysis",
        "real_npu_summary.csv  real_npu_summary.md",
        "$ find bench/results/formal -name '*.state.json' | wc -l",
        "real router state snapshots retained with the repo",
    ], ("prototype", "real_npu_summary", "state"))
    rounded(draw, (1180, 330, 1748, 790), C["panel"], C["line"])
    text(draw, (1224, 380), "最终结论", F["h2"], C["ink"])
    paragraph(draw, (1224, 448), "这个原型演示不是 PPT 朗读，而是直接展示真实运行证据：NPU 状态、router 状态、metrics、实验 CSV 和对比图表。", F["body"], C["muted"], 455)
    paragraph(draw, (1224, 610), "主线保持为：问题 -> 方案 -> 真实证据。所有正式结论来自 Ascend NPU 3-7。", F["body_bold"], C["green"], 455)


def scenes() -> list[Scene]:
    return [
        Scene(
            "cover",
            "真实原型演示",
            "不用 PPT 讲故事，直接展示运行证据",
            "视频画面来自 npu-smi、router /admin/state、/metrics 和真实实验 CSV。",
            "这版原型演示不再用 PPT 做主体，而是直接展示真实运行数据。画面来自仓库里的 npu-smi 截图文本、router 状态快照、metrics 快照和真实实验 CSV。讲解顺序是问题、方案、证据。",
            "证据来源：npu-smi、/admin/state、/metrics、real_npu_summary.csv",
            draw_cover,
            20,
        ),
        Scene(
            "problem",
            "问题现场",
            "真实 NPU 集群状态会动态变化",
            "静态轮询只知道节点列表，看不到哪个 NPU 正在被外部推理压力占用。",
            "首先看真实 NPU 状态。实验环境使用的是 Ascend 910B，NPU 三到七都有推理进程和显存占用。大模型推理中，长 prompt、KV cache 和队列都会让后端能力变化。静态轮询仍然给每个节点固定份额，热点节点就会继续被打中。",
            "问题：静态轮询看不到真实热点，空闲 NPU 无法及时承接流量。",
            draw_problem,
            25,
        ),
        Scene(
            "router",
            "方案入口",
            "suan-router 把可观测信号变成调度权重",
            "router 位于 OpenAI 客户端和 vLLM-Ascend 后端之间，读取 health、capacity、inflight 和 vLLM 指标。",
            "我们的方案是在客户端和 vLLM Ascend 后端之间加一个 OpenAI 兼容的 router。它读取健康状态、capacity、本地 inflight，以及 vLLM metrics 中的 running、waiting、KV cache 和延迟信号，再把这些信号转换成动态权重。",
            "方案：观测 -> 动态权重 -> smoothStep -> 故障保护。",
            draw_router,
            24,
        ),
        Scene(
            "exp2",
            "证据一：热点避让",
            "真实背景压力下，P2C 自动避开 NPU3",
            "SWRR 是静态基线；P2C 读取 vLLM 指标后把热点节点测量流量降到 0%。",
            "第一组证据是热点避让。我们直接对 NPU 三发送长请求作为背景压力，同时通过 router 发送测量请求。静态 SWRR 仍给 NPU 三百分之十九点九六流量；P2C 读取到 remote utilization 后降到零；balanced P2C 保留少量探测流量。",
            "exp2：热点 NPU3 流量 19.96% -> 0.00%，并保留 metrics 证据。",
            draw_exp2,
            29,
        ),
        Scene(
            "exp2-state",
            "证据一补充",
            "router 状态快照显示权重被真实负载压低",
            "同一实验的 /admin/state 快照展示 remote_utilization、desired_weight 和 effective_weight。",
            "这里展示的不是手写结果，而是实验结束时的 router 状态快照。可以看到热点后端的 remote utilization 明显高于其他节点，目标权重下降，有效权重平滑跟随。最终测量流量没有继续压到热点后端。",
            "/admin/state 证明：调度决策来自真实负载信号。",
            draw_exp2_state,
            24,
        ),
        Scene(
            "exp3",
            "证据二：平滑降容",
            "capacity 10 -> 1 -> 10，新请求平滑迁移",
            "稳定降容窗口目标节点占比 2.37%，理论值 2.44%，全程 0 错误。",
            "第二组证据对应赛题明确要求的 capacity 大幅下降。我们把目标节点 capacity 从十降到一，再恢复到十。稳定降容窗口中，目标节点实际占比是百分之二点三七，接近理论值百分之二点四四，全程二万九千七百四十八个请求零错误。",
            "exp3：capacity 降到 1 后占比接近理论值，且没有强制中断请求。",
            draw_exp3,
            29,
        ),
        Scene(
            "exp4",
            "证据三：故障摘除与恢复",
            "只停止指定容器，router 自动摘除并慢启动恢复",
            "NPU5 故障稳定期流量 0.02%，恢复末段回到 19.80%。",
            "第三组证据是故障恢复。实验只停止我们自己的 qwen15b NPU 五容器。状态快照显示 NPU 五进入 drained，healthy 变为 false，连接被拒绝。故障稳定期它的流量降到百分之零点零二，恢复末段回到百分之十九点八。",
            "exp4：故障后 NPU5 被摘除，恢复后按 slow-start 回归。",
            draw_exp4,
            31,
        ),
        Scene(
            "exp5",
            "证据四：资源池隔离",
            "isolated 池承压，不影响 default 池",
            "default 池完成 28,218 请求 0 错误，isolated 池独立承受长请求压力。",
            "第四组证据是资源池隔离。我们让 isolated 池承受长请求压力，同时 default 池继续服务正常请求。状态快照里两个 pool 是分开的。结果 default 池完成两万八千二百一十八个请求，零错误；isolated 池独立承压。",
            "exp5：noisy neighbor 被限制在 isolated 池内。",
            draw_exp5,
            24,
        ),
        Scene(
            "exp8",
            "证据五：7B 泛化",
            "Qwen2.5-7B 上热点避让仍然成立",
            "同样的热点实验换成 7B 后，P2C 仍把 NPU3 流量降到 0%。",
            "为了避免只验证小模型，我们补充了 Qwen 二点五七 B 实验。实验逻辑和热点避让一致，只是后端模型变成七 B。静态 SWRR 仍给热点 NPU 三百分之十九点八一流量；P2C 降到零；balanced P2C 保留百分之三点六四探测流量。",
            "exp8：更大模型上，真实负载感知仍然有效。",
            draw_exp8,
            28,
        ),
        Scene(
            "close",
            "提交材料",
            "视频、字幕、证据说明和实验数据已集中归档",
            "正式视频展示真实运行证据；PPT 只作为辅助讲解材料保留。",
            "最后看提交目录。正式视频、字幕、旁白文本和证据型视频说明都在 submission 目录下。PPT 只是辅助材料，不再是视频主体。评委可以沿着这些路径检查每个结论对应的真实数据文件。",
            "最终材料：问题 -> 方案 -> 真实证据，全部可追溯到仓库文件。",
            draw_close,
            23,
        ),
    ]


def render_scene(scene: Scene, idx: int, total: int, frame_idx: int, frame_count: int, data: dict[str, object]) -> Image.Image:
    image = Image.new("RGB", (W, H), C["bg"])
    draw = ImageDraw.Draw(image)
    header(draw, scene, idx, total)
    p = frame_idx / max(1, frame_count - 1)
    scene.draw(draw, p, data)
    return image


def render_video(scene_list: list[Scene], durations: list[float], data: dict[str, object], out: Path) -> None:
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=8, macro_block_size=8)
    try:
        for idx, (scene, duration) in enumerate(zip(scene_list, durations)):
            frame_count = max(1, int(round(duration * FPS)))
            for frame_idx in range(frame_count):
                writer.append_data(np.asarray(render_scene(scene, idx, len(scene_list), frame_idx, frame_count, data)))
    finally:
        writer.close()


def write_text_assets(scene_list: list[Scene]) -> None:
    NARRATION_TEXT.write_text("\n\n".join(s.narration for s in scene_list), encoding="utf-8")


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)


def audio_duration(path: Path) -> float:
    proc = run(["afinfo", str(path)])
    match = re.search(r"estimated duration: ([0-9.]+) sec", proc.stdout)
    if not match:
        raise RuntimeError(f"cannot parse audio duration for {path}")
    return float(match.group(1))


def generate_audio(scene_list: list[Scene], tmp: Path) -> tuple[Path | None, list[float]]:
    if shutil.which("say") is None:
        return None, [s.fallback_duration for s in scene_list]
    files: list[Path] = []
    durations: list[float] = []
    for idx, scene in enumerate(scene_list, 1):
        out = tmp / f"scene-{idx:02d}.aiff"
        subprocess.run(["say", "-v", "Tingting", "-r", "185", "-o", str(out), scene.narration], check=True)
        files.append(out)
        durations.append(audio_duration(out) + 0.35)
    concat = tmp / "audio-list.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in files), encoding="utf-8")
    narration = tmp / "narration.m4a"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:a", "aac", "-b:a", "128k", str(narration)])
    return narration, durations


def mux_audio(video: Path, audio: Path, out: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    run([ffmpeg, "-y", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)])


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(scene_list: list[Scene], durations: list[float]) -> None:
    current = 0.0
    blocks = []
    for idx, (scene, duration) in enumerate(zip(scene_list, durations), 1):
        start = current
        end = current + duration
        blocks.append(f"{idx}\n{srt_time(start)} --> {srt_time(end)}\n{scene.caption}\n")
        current = end
    SRT_OUT.write_text("\n".join(blocks), encoding="utf-8")


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    data = summary()
    scene_list = scenes()
    write_text_assets(scene_list)
    render_scene(scene_list[0], 0, len(scene_list), 0, 1, data).save(COVER_OUT)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        audio, durations = generate_audio(scene_list, tmp)
        silent = tmp / "silent.mp4"
        render_video(scene_list, durations, data, silent)
        write_srt(scene_list, durations)
        if audio is None:
            shutil.copyfile(silent, FINAL_VIDEO)
        else:
            mux_audio(silent, audio, FINAL_VIDEO)
    print(f"wrote {FINAL_VIDEO.relative_to(ROOT)} ({sum(durations):.1f}s)")
    print(f"wrote {SRT_OUT.relative_to(ROOT)}")
    print(f"wrote {NARRATION_TEXT.relative_to(ROOT)}")
    print(f"wrote {COVER_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
