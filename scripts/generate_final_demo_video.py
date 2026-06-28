#!/usr/bin/env python3
"""Generate a polished 5-minute prototype demo video with narration.

The script is intentionally data-driven: it reads the formal real-NPU summary
CSV and renders the video from the checked-in experiment results. It does not
connect to the remote NPU host and does not start any router or backend.
"""

from __future__ import annotations

import csv
import math
import os
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
SUMMARY_CSV = ROOT / "bench/results/formal/analysis/real_npu_summary.csv"
DEMO_DIR = ROOT / "docs/demo/submission"
FINAL_VIDEO = DEMO_DIR / "prototype-demo-final.mp4"
NARRATION_TEXT = DEMO_DIR / "prototype-demo-final-narration.txt"
SRT_OUT = DEMO_DIR / "prototype-demo-final.srt"
COVER_OUT = DEMO_DIR / "prototype-demo-final-cover.png"

W, H = 1920, 1080
FPS = 12

COLORS = {
    "bg": "#f5f7fb",
    "ink": "#101820",
    "muted": "#5c6675",
    "line": "#d8e0ea",
    "panel": "#ffffff",
    "cyan": "#087ea4",
    "green": "#0f8b6f",
    "red": "#c2413b",
    "amber": "#c98311",
    "navy": "#192a3d",
    "soft_cyan": "#e8f6fb",
    "soft_green": "#e9f7f2",
    "soft_red": "#fff1f0",
    "soft_amber": "#fff7e6",
}


@dataclass
class Scene:
    key: str
    eyebrow: str
    title: str
    subtitle: str
    narration: str
    caption: str
    draw: Callable[[ImageDraw.ImageDraw, float, dict[str, str]], None]
    fallback_duration: float


def load_rows() -> list[dict[str, str]]:
    with SUMMARY_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick(rows: list[dict[str, str]], exp: str, scheduler: str, window: str = "all", source: str | None = None) -> dict[str, str]:
    for item in rows:
        if item["experiment_id"] != exp or item["scheduler"] != scheduler or item["window"] != window:
            continue
        if source is not None and source not in item["source_file"]:
            continue
        return item
    raise KeyError((exp, scheduler, window, source))


def fmt(value: str, suffix: str = "", digits: int = 2) -> str:
    if value == "":
        return "-"
    number = float(value)
    if math.isclose(number, round(number), abs_tol=1e-9):
        text = f"{int(round(number)):,}"
    else:
        text = f"{number:.{digits}f}"
    return text + suffix


def metrics() -> dict[str, str]:
    rows = load_rows()
    exp1_swrr = pick(rows, "exp1", "swrr")
    exp1_p2c = pick(rows, "exp1", "p2c_smooth_wrr")
    exp2_swrr = pick(rows, "exp2", "swrr")
    exp2_p2c = pick(rows, "exp2", "p2c_smooth_wrr")
    exp2_bal = pick(rows, "exp2", "balanced_p2c")
    exp3_down = pick(rows, "exp3", "p2c_smooth_wrr", "stable_down_40_80")
    exp3_all = pick(rows, "exp3", "p2c_smooth_wrr")
    exp3_recover = pick(rows, "exp3", "p2c_smooth_wrr", "stable_up_100_120")
    exp4_fail = pick(rows, "exp4", "p2c_smooth_wrr", "fail_stable_35_90")
    exp4_recover = pick(rows, "exp4", "p2c_smooth_wrr", "recovery_end_240_300")
    exp4_all = pick(rows, "exp4", "p2c_smooth_wrr")
    exp5_default = pick(rows, "exp5", "p2c_smooth_wrr", source="exp5-real-default.csv")
    exp5_iso = pick(rows, "exp5", "p2c_smooth_wrr", source="exp5-real-isolated.csv")
    exp7_ss025 = pick(rows, "exp7", "smooth_step=0.25", "stable_down_30_50")
    exp8_swrr = pick(rows, "exp8", "swrr")
    exp8_p2c = pick(rows, "exp8", "p2c_smooth_wrr")
    exp8_bal = pick(rows, "exp8", "balanced_p2c")
    return {
        "exp1_swrr_qps": fmt(exp1_swrr["qps"]),
        "exp1_p2c_qps": fmt(exp1_p2c["qps"]),
        "exp1_delta": "-0.38%",
        "exp2_swrr_share": fmt(exp2_swrr["target_share_pct"], "%"),
        "exp2_p2c_share": fmt(exp2_p2c["target_share_pct"], "%"),
        "exp2_bal_share": fmt(exp2_bal["target_share_pct"], "%"),
        "exp2_swrr_p99": fmt(exp2_swrr["p99_ms"], "ms"),
        "exp2_p2c_p99": fmt(exp2_p2c["p99_ms"], "ms"),
        "exp2_bal_p99": fmt(exp2_bal["p99_ms"], "ms"),
        "exp2_remote": fmt(exp2_p2c["max_target_remote_utilization"], ""),
        "exp3_share": fmt(exp3_down["target_share_pct"], "%"),
        "exp3_expected": fmt(exp3_down["expected_share_pct"], "%"),
        "exp3_error": fmt(exp3_all["total_errors"]),
        "exp3_requests": fmt(exp3_all["total_requests"]),
        "exp3_recover": fmt(exp3_recover["target_share_pct"], "%"),
        "exp4_fail_share": fmt(exp4_fail["target_share_pct"], "%"),
        "exp4_recover_share": fmt(exp4_recover["target_share_pct"], "%"),
        "exp4_errors": fmt(exp4_all["total_errors"]),
        "exp4_requests": fmt(exp4_all["total_requests"]),
        "exp5_default_requests": fmt(exp5_default["total_requests"]),
        "exp5_default_errors": fmt(exp5_default["total_errors"]),
        "exp5_iso_requests": fmt(exp5_iso["total_requests"]),
        "exp7_ss025": fmt(exp7_ss025["target_share_pct"], "%"),
        "exp7_error": fmt(exp7_ss025["absolute_share_error_pct"], "pp"),
        "exp8_swrr_share": fmt(exp8_swrr["target_share_pct"], "%"),
        "exp8_p2c_share": fmt(exp8_p2c["target_share_pct"], "%"),
        "exp8_bal_share": fmt(exp8_bal["target_share_pct"], "%"),
        "exp8_swrr_qps": fmt(exp8_swrr["qps"]),
        "exp8_p2c_qps": fmt(exp8_p2c["qps"]),
        "exp8_bal_qps": fmt(exp8_bal["qps"]),
        "exp8_swrr_p99": fmt(exp8_swrr["p99_ms"], "ms"),
        "exp8_p2c_p99": fmt(exp8_p2c["p99_ms"], "ms"),
        "exp8_bal_p99": fmt(exp8_bal["p99_ms"], "ms"),
    }


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=1 if bold else 0)
        except Exception:
            continue
    return ImageFont.load_default()


F = {
    "eyebrow": font(26, True),
    "title": font(58, True),
    "subtitle": font(28),
    "body": font(29),
    "body_bold": font(31, True),
    "small": font(22),
    "mono": font(25),
    "kpi": font(52, True),
    "kpi_label": font(22),
    "caption": font(27, True),
}


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], s: str, face: ImageFont.ImageFont, fill: str) -> None:
    draw.text(xy, s, font=face, fill=fill)


def wrap(draw: ImageDraw.ImageDraw, s: str, face: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in s:
        trial = current + ch
        bbox = draw.textbbox((0, 0), trial, font=face)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def paragraph(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    s: str,
    face: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    for line in wrap(draw, s, face, max_width):
        text(draw, (x, y), line, face, fill)
        y += face.size + line_gap
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str = "", width: int = 1, radius: int = 16) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline or None, width=width)


def header(draw: ImageDraw.ImageDraw, scene: Scene, index: int, total: int) -> None:
    draw.rectangle((0, 0, W, 16), fill=COLORS["cyan"])
    text(draw, (96, 68), scene.eyebrow, F["eyebrow"], COLORS["cyan"])
    paragraph(draw, (96, 112), scene.title, F["title"], COLORS["ink"], 1700, 8)
    paragraph(draw, (96, 252), scene.subtitle, F["subtitle"], COLORS["muted"], 1420, 8)
    draw.line((96, 315, 1824, 315), fill=COLORS["line"], width=2)
    progress_w = int(1728 * (index + 1) / total)
    draw.rounded_rectangle((96, 1018, 1824, 1028), radius=5, fill="#dde5ee")
    draw.rounded_rectangle((96, 1018, 96 + progress_w, 1028), radius=5, fill=COLORS["cyan"])
    text(draw, (96, 978), "suan-router / Ascend NPU 3-7 / vLLM-Ascend", F["small"], COLORS["muted"])
    text(draw, (1740, 978), f"{index + 1} / {total}", F["small"], COLORS["muted"])


def caption(draw: ImageDraw.ImageDraw, s: str) -> None:
    rounded(draw, (240, 900, 1680, 960), "#101820", radius=14)
    bbox = draw.textbbox((0, 0), s, font=F["caption"])
    text(draw, ((W - (bbox[2] - bbox[0])) // 2, 914), s, F["caption"], "#ffffff")


def kpi(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, value: str, label: str, color: str, sub: str = "") -> None:
    rounded(draw, (x, y, x + w, y + 150), COLORS["panel"], COLORS["line"], width=2, radius=18)
    draw.rectangle((x, y, x + 10, y + 150), fill=color)
    text(draw, (x + 32, y + 28), value, F["kpi"], color)
    text(draw, (x + 34, y + 92), label, F["kpi_label"], COLORS["ink"])
    if sub:
        text(draw, (x + 34, y + 120), sub, F["small"], COLORS["muted"])


def bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, value: float, max_value: float, value_text: str, color: str, p: float) -> None:
    text(draw, (x, y - 2), label, F["body_bold"], COLORS["ink"])
    track_x = x + 250
    track_w = w - 420
    rounded(draw, (track_x, y + 8, track_x + track_w, y + 42), "#e7edf5", radius=8)
    fill_w = int(track_w * (value / max_value) * p)
    rounded(draw, (track_x, y + 8, track_x + fill_w, y + 42), color, radius=8)
    text(draw, (track_x + track_w + 36, y), value_text, F["body_bold"], color)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str, width: int = 5) -> None:
    draw.line((start, end), fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 18
    pts = [
        (x2, y2),
        (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45)),
        (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45)),
    ]
    draw.polygon(pts, fill=color)


def draw_title(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    kpi(draw, 96, 370, 360, "5", "真实 Ascend NPU", COLORS["cyan"], "real NPU 3-7")
    kpi(draw, 496, 370, 360, "8", "正式实验分组", COLORS["green"], "exp1-exp8")
    kpi(draw, 896, 370, 360, "0", "fake 进入主结论", COLORS["red"], "只作开发夹具")
    kpi(draw, 1296, 370, 360, "7B", "跨模型补充", COLORS["amber"], "Qwen2.5-7B")
    y = 610
    rounded(draw, (96, y, 1824, y + 230), COLORS["panel"], COLORS["line"], width=2)
    paragraph(draw, (140, y + 42), "目标：在高并发、多资源池、后端健康和负载持续变化的场景下，让推理请求自动避开热点，并在 capacity 变化时平滑迁移。", F["body"], COLORS["ink"], 1660, 12)


def draw_problem(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    labels = ["NPU3 热点", "NPU4 空闲", "NPU5 空闲", "NPU6 空闲", "NPU7 空闲"]
    loads = [1.0, 0.22, 0.18, 0.2, 0.19]
    shares = [0.2, 0.2, 0.2, 0.2, 0.2]
    x0, y0 = 110, 380
    for i, (label, load, share) in enumerate(zip(labels, loads, shares)):
        x = x0 + i * 350
        rounded(draw, (x, y0, x + 270, y0 + 360), COLORS["panel"], COLORS["line"], width=2)
        color = COLORS["red"] if i == 0 else COLORS["green"]
        text(draw, (x + 28, y0 + 28), label, F["body_bold"], color)
        rounded(draw, (x + 52, y0 + 95, x + 218, y0 + 300), "#e8edf4", radius=12)
        fill_h = int(205 * load * p)
        rounded(draw, (x + 52, y0 + 300 - fill_h, x + 218, y0 + 300), color, radius=12)
        text(draw, (x + 46, y0 + 315), f"静态份额 {share * 100:.0f}%", F["small"], COLORS["muted"])
    caption(draw, "静态轮询看不到热点：NPU3 已经满载，仍继续分到约 20% 请求")


def draw_arch(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    client = (120, 455, 420, 610)
    router = (760, 410, 1160, 660)
    rounded(draw, client, COLORS["panel"], COLORS["line"], width=2)
    rounded(draw, router, "#eef9fc", COLORS["cyan"], width=3)
    text(draw, (180, 485), "Client", F["body_bold"], COLORS["ink"])
    text(draw, (150, 535), "OpenAI API", F["small"], COLORS["muted"])
    text(draw, (825, 455), "suan-router", F["body_bold"], COLORS["cyan"])
    text(draw, (812, 510), "data :8180", F["small"], COLORS["muted"])
    text(draw, (812, 545), "admin :8181", F["small"], COLORS["muted"])
    text(draw, (812, 580), "/metrics", F["small"], COLORS["muted"])
    if p > 0.2:
        arrow(draw, (420, 535), (760, 535), COLORS["cyan"])
    backend_x = 1350
    for i, npu in enumerate(["NPU3", "NPU4", "NPU5", "NPU6", "NPU7"]):
        y = 350 + i * 96
        rounded(draw, (backend_x, y, backend_x + 350, y + 72), COLORS["panel"], COLORS["line"], width=2)
        text(draw, (backend_x + 28, y + 18), npu, F["body_bold"], COLORS["ink"])
        text(draw, (backend_x + 140, y + 21), "vLLM-Ascend", F["small"], COLORS["muted"])
        if p > 0.45:
            arrow(draw, (1160, 535), (backend_x, y + 36), COLORS["green"], width=3)
    rounded(draw, (120, 710, 1700, 825), COLORS["panel"], COLORS["line"], width=2)
    paragraph(draw, (160, 738), "Router 同时读取 /health、vLLM /metrics、本地 inflight 和管理面 capacity；资源池通过 X-Resource-Pool 隔离。", F["body"], COLORS["ink"], 1500, 8)


def draw_algorithm(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    rounded(draw, (110, 360, 900, 760), "#101820", radius=18)
    formula = [
        "load_score = f(util, queue, inflight, KV, latency)",
        "headroom = 1 - load_score",
        "desired_weight = capacity * headroom",
        "effective += (desired - effective) * smooth_step",
    ]
    y = 410
    for line in formula:
        text(draw, (160, y), line, F["mono"], "#ffffff")
        y += 76
    rounded(draw, (1020, 360, 1780, 760), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (1060, 405), "状态机", F["body_bold"], COLORS["ink"])
    states = ["active", "draining", "drained", "recovering", "active"]
    xs = [1080, 1245, 1415, 1585, 1735]
    for i, st in enumerate(states):
        x = xs[i]
        rounded(draw, (x - 75, 500, x + 75, 570), "#e8f6fb" if i != 2 else "#fff7e6", COLORS["line"], width=2)
        bbox = draw.textbbox((0, 0), st, font=F["small"])
        text(draw, (x - (bbox[2] - bbox[0]) // 2, 522), st, F["small"], COLORS["ink"])
        if i < len(states) - 1 and p > 0.25 + i * 0.12:
            arrow(draw, (x + 78, 535), (xs[i + 1] - 82, 535), COLORS["cyan"], width=3)
    paragraph(draw, (1060, 620), "capacity 或健康状态变化只影响新请求选择；已转发请求由后端自然完成。", F["body"], COLORS["muted"], 640, 8)


def draw_exp2(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    rounded(draw, (96, 350, 1824, 785), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (140, 390), "热点 NPU3 测量流量占比", F["body_bold"], COLORS["ink"])
    bar(draw, 150, 475, 1500, "SWRR 静态基线", 19.96, 25, d["exp2_swrr_share"], COLORS["red"], p)
    bar(draw, 150, 565, 1500, "P2C smooth WRR", 0.0, 25, d["exp2_p2c_share"], COLORS["green"], p)
    bar(draw, 150, 655, 1500, "balanced P2C", 3.94, 25, d["exp2_bal_share"], COLORS["cyan"], p)
    kpi(draw, 1180, 392, 260, d["exp2_remote"], "remote_utilization", COLORS["amber"], "P2C 读到满载")
    kpi(draw, 1480, 392, 260, d["exp2_p2c_p99"], "P2C p99", COLORS["green"], f"SWRR {d['exp2_swrr_p99']}")


def draw_exp3(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    rounded(draw, (120, 375, 1800, 780), COLORS["panel"], COLORS["line"], width=2)
    points = [(0, 19.96), (30, 19.96), (40, 6.08), (80, 2.37), (100, 10.22), (120, 19.83)]
    x0, y0, w, h = 190, 455, 1040, 240
    draw.line((x0, y0 + h, x0 + w, y0 + h), fill=COLORS["line"], width=2)
    draw.line((x0, y0, x0, y0 + h), fill=COLORS["line"], width=2)
    for pct in [0, 5, 10, 20]:
        y = y0 + h - int(h * pct / 22)
        draw.line((x0 - 8, y, x0 + w, y), fill="#edf1f6", width=1)
        text(draw, (x0 - 70, y - 12), f"{pct}%", F["small"], COLORS["muted"])
    scaled: list[tuple[int, int]] = []
    max_t = 120
    for t, pct in points:
        x = x0 + int(w * t / max_t)
        y = y0 + h - int(h * pct / 22)
        scaled.append((x, y))
    visible = max(2, int(2 + (len(scaled) - 1) * p))
    draw.line(scaled[:visible], fill=COLORS["green"], width=6, joint="curve")
    for x, y in scaled[:visible]:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=COLORS["green"])
    kpi(draw, 1320, 435, 320, d["exp3_share"], "稳定降容占比", COLORS["green"], f"理论 {d['exp3_expected']}")
    kpi(draw, 1320, 610, 320, d["exp3_error"], f"{d['exp3_requests']} 请求", COLORS["cyan"], "错误数")
    text(draw, (185, 715), "0s        30s 降容        80s 恢复        120s", F["small"], COLORS["muted"])


def draw_exp4_exp5(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    rounded(draw, (110, 360, 900, 795), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (150, 400), "真实故障恢复", F["body_bold"], COLORS["ink"])
    phases = [("故障前", "20.06%"), ("稳定摘除", d["exp4_fail_share"]), ("恢复末段", d["exp4_recover_share"])]
    for i, (label, val) in enumerate(phases):
        x = 170 + i * 230
        color = COLORS["red"] if i == 1 else COLORS["green"]
        rounded(draw, (x, 500, x + 180, 630), "#fff1f0" if i == 1 else "#e9f7f2", radius=18)
        text(draw, (x + 24, 525), val, F["kpi"], color)
        text(draw, (x + 28, 590), label, F["small"], COLORS["ink"])
        if i < 2 and p > 0.25 + i * 0.2:
            arrow(draw, (x + 184, 565), (x + 225, 565), COLORS["cyan"], width=4)
    paragraph(draw, (150, 685), f"全程 {d['exp4_requests']} 请求，{d['exp4_errors']} 错误；只操作指定 NPU5 容器。", F["body"], COLORS["muted"], 680)
    rounded(draw, (1020, 360, 1810, 795), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (1060, 400), "资源池隔离", F["body_bold"], COLORS["ink"])
    rounded(draw, (1080, 495, 1750, 590), COLORS["soft_cyan"], radius=18)
    rounded(draw, (1080, 630, 1750, 725), COLORS["soft_amber"], radius=18)
    text(draw, (1120, 525), f"default 池：{d['exp5_default_requests']} 请求，{d['exp5_default_errors']} 错误", F["body_bold"], COLORS["cyan"])
    text(draw, (1120, 660), f"isolated 池：{d['exp5_iso_requests']} 长请求承压", F["body_bold"], COLORS["amber"])


def draw_exp8(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    rounded(draw, (96, 350, 930, 800), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (140, 392), "7B 热点避让：NPU3 流量占比", F["body_bold"], COLORS["ink"])
    bar(draw, 145, 475, 720, "SWRR", 19.81, 25, d["exp8_swrr_share"], COLORS["red"], p)
    bar(draw, 145, 565, 720, "P2C", 0.0, 25, d["exp8_p2c_share"], COLORS["green"], p)
    bar(draw, 145, 655, 720, "balanced", 3.64, 25, d["exp8_bal_share"], COLORS["cyan"], p)
    rounded(draw, (1010, 350, 1824, 800), COLORS["panel"], COLORS["line"], width=2)
    text(draw, (1055, 392), "QPS / p99", F["body_bold"], COLORS["ink"])
    rows = [
        ("SWRR", d["exp8_swrr_qps"], d["exp8_swrr_p99"], COLORS["red"]),
        ("P2C", d["exp8_p2c_qps"], d["exp8_p2c_p99"], COLORS["green"]),
        ("balanced", d["exp8_bal_qps"], d["exp8_bal_p99"], COLORS["cyan"]),
    ]
    for i, (name, qps, p99, color) in enumerate(rows):
        y = 485 + i * 95
        text(draw, (1070, y), name, F["body_bold"], COLORS["ink"])
        text(draw, (1260, y), f"{qps} QPS", F["body_bold"], color)
        text(draw, (1500, y), f"p99 {p99}", F["body_bold"], COLORS["muted"])
    paragraph(draw, (1060, 735), "动态组吞吐和 p99 优于基线；p95 未夸大，报告中如实说明。", F["small"], COLORS["muted"], 690)


def draw_submission(draw: ImageDraw.ImageDraw, p: float, d: dict[str, str]) -> None:
    p = ease(p)
    items = [
        ("设计方案", "docs/final-report.md", COLORS["cyan"]),
        ("技术路线图", "docs/experiments.md + docs/optimization-and-validation.md", COLORS["green"]),
        ("原型视频", "docs/demo/submission/prototype-demo-final.mp4", COLORS["amber"]),
        ("真实数据", "bench/results/formal/", COLORS["red"]),
    ]
    for i, (name, path, color) in enumerate(items):
        y = 370 + i * 112
        rounded(draw, (160, y, 1760, y + 86), COLORS["panel"], COLORS["line"], width=2)
        draw.rectangle((160, y, 176, y + 86), fill=color)
        text(draw, (205, y + 20), name, F["body_bold"], color)
        text(draw, (520, y + 23), path, F["body"], COLORS["ink"])
    rounded(draw, (160, 850, 1760, 915), "#101820", radius=14)
    text(draw, (210, 867), "安全边界：不杀无关任务；只清理自己启动的 router PID；7B 临时容器实验后删除释放 NPU。", F["caption"], "#ffffff")


def scenes(d: dict[str, str]) -> list[Scene]:
    return [
        Scene(
            "title",
            "赛题2 原型展示",
            "动态负载感知调度系统：suan-router",
            "面向昇腾 NPU 推理集群，解决热点、降容、故障和资源池隔离问题。",
            "我们展示的是面向赛题二的大模型推理算力资源动态负载感知调度系统，项目名是 suan-router。它位于客户端和 vLLM Ascend 后端之间，目标是在真实 NPU 集群中消除热点，支持 capacity 平滑变化，并保证故障恢复和资源池隔离。",
            "真实 NPU、动态调度、可复现数据，是这版原型的核心。",
            draw_title,
            28,
        ),
        Scene(
            "problem",
            "问题场景",
            "静态轮询无法适应动态算力环境",
            "某个后端已被外部任务压满，静态轮询仍继续给它分配请求。",
            "赛题的核心矛盾是，后端算力不是静态的。某个 NPU 可能正在承受外部压力，也可能进入故障或恢复阶段。如果仍然按静态轮询分配请求，热点节点会继续收到流量，尾延迟和错误都会扩散。",
            "静态轮询看不到热点，因此会把请求继续打到高负载 NPU。",
            draw_problem,
            30,
        ),
        Scene(
            "arch",
            "系统设计",
            "OpenAI-compatible Router + 5 个 vLLM-Ascend 后端",
            "数据面、管理面和 metrics 分离，资源池通过请求头隔离。",
            "系统架构上，router 对外提供 OpenAI 兼容接口，后端是五个真实 Ascend 九一零 B NPU 上的 vLLM Ascend 实例。router 同时读取健康检查、管理面 capacity、本地 inflight，以及 vLLM Prometheus 指标。资源池通过 X Resource Pool 请求头隔离。",
            "Router 汇聚健康、capacity、inflight 和 vLLM 指标，再做动态选择。",
            draw_arch,
            36,
        ),
        Scene(
            "algorithm",
            "调度算法",
            "多维负载评分 + smoothStep 平滑权重",
            "目标权重立即响应负载，有效权重平滑追随，避免硬切换。",
            "调度算法分两层。第一层根据 utilization，queue，inflight，KV cache 和延迟计算负载分数，再得到目标权重。第二层用 smooth step 让有效权重逐步追随目标权重。这样 capacity 从十降到一时，新请求逐步迁移，已经分配的请求不会被中断。",
            "desired weight 响应真实负载，effective weight 负责平滑迁移。",
            draw_algorithm,
            40,
        ),
        Scene(
            "exp2",
            "实验一：热点避让",
            "真实 NPU3 外部压力下，动态调度自动避开热点",
            "SWRR 是静态基线；P2C 和 balanced P2C 读取 vLLM /metrics。",
            f"第一个关键实验是热点避让。我们对 NPU 三直接发送长 prompt 背景压力，同时通过 router 发送测量流量。静态 SWRR 不读取指标，所以仍然给 NPU 三 {d['exp2_swrr_share']} 的流量。P2C 读到 remote utilization 等于一后，把 NPU 三的测量流量降到 {d['exp2_p2c_share']}。balanced P2C 保留 {d['exp2_bal_share']} 的受控探测流量。",
            "真实热点压力下，P2C 将 NPU3 流量从约 20% 降到 0%。",
            draw_exp2,
            44,
        ),
        Scene(
            "exp3",
            "实验二：capacity 平滑迁移",
            "capacity 10 -> 1 -> 10，新请求迁移但不强制中断",
            "稳定降容窗口中，目标节点占比接近理论值。",
            f"第二个实验验证赛题要求的 capacity 平滑变化。目标节点从十降到一后，理论流量占比是 {d['exp3_expected']}，真实稳定窗口是 {d['exp3_share']}，误差很小。整个实验 {d['exp3_requests']} 个请求，错误数是 {d['exp3_error']}。恢复后占比回到 {d['exp3_recover']}，说明平滑迁移和恢复都成立。",
            "capacity 降到 1 后，稳定占比 2.37%，接近理论 2.44%。",
            draw_exp3,
            42,
        ),
        Scene(
            "exp4_exp5",
            "实验三：高可用与资源池隔离",
            "故障摘除、恢复慢启动、noisy neighbor 隔离",
            "只操作指定项目容器，不影响其他任务。",
            f"第三组实验验证可用性和隔离。故障实验只停止我们自己的 NPU 五容器。故障稳定期，NPU 五流量占比降到 {d['exp4_fail_share']}，恢复末段回到 {d['exp4_recover_share']}。资源池隔离实验中，isolated 池承受长请求压力时，default 池仍完成 {d['exp5_default_requests']} 个请求，错误数为 {d['exp5_default_errors']}。",
            "故障节点被摘除，恢复后慢启动；资源池之间互不干扰。",
            draw_exp4_exp5,
            42,
        ),
        Scene(
            "exp8",
            "补充实验：7B 泛化",
            "Qwen2.5-7B 单卡后端上，热点避让仍然成立",
            "这是对“只验证小模型”的风险补充。",
            f"为了补充跨模型泛化证据，我们又运行了 Qwen 二点五 7B Instruct。静态 SWRR 仍给热点 NPU 三 {d['exp8_swrr_share']} 的流量，P2C 降到 {d['exp8_p2c_share']}，balanced P2C 保留 {d['exp8_bal_share']}。三组都是零错误，动态组在吞吐和 p 九十九上优于基线。",
            "7B 模型下，动态组仍能把热点 NPU3 流量降到 0% 或受控探测份额。",
            draw_exp8,
            34,
        ),
        Scene(
            "submission",
            "初赛提交材料",
            "设计方案、技术路线图、原型视频和真实实验数据已整理",
            "文字材料放在 README 与 docs，视频上传到项目数据集。",
            "最后，初赛需要的设计方案，技术路线图和五分钟以内原型视频都已经整理在仓库里。正式结论只引用真实 Ascend NPU 三到七的数据，不使用 fake backend。实验脚本只清理自己启动的进程，不杀无关任务，七 B 临时容器也在实验后释放。",
            "提交材料已经对应赛题要求整理完毕，可直接用于仓库或 ZIP 提交。",
            draw_submission,
            30,
        ),
    ]


def render_scene_frame(scene: Scene, index: int, total: int, frame_idx: int, frame_count: int, d: dict[str, str]) -> Image.Image:
    p = frame_idx / max(1, frame_count - 1)
    image = Image.new("RGB", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    header(draw, scene, index, total)
    scene.draw(draw, p, d)
    caption(draw, scene.caption)
    return image


def render_video(scene_list: list[Scene], durations: list[float], d: dict[str, str], out: Path) -> None:
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=8, macro_block_size=8)
    try:
        for idx, (scene, duration) in enumerate(zip(scene_list, durations)):
            frame_count = max(1, int(round(duration * FPS)))
            for frame_idx in range(frame_count):
                image = render_scene_frame(scene, idx, len(scene_list), frame_idx, frame_count, d)
                writer.append_data(np.asarray(image))
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
    audio_files: list[Path] = []
    durations: list[float] = []
    for i, scene in enumerate(scene_list, 1):
        out = tmp / f"scene-{i:02d}.aiff"
        subprocess.run(["say", "-v", "Tingting", "-r", "185", "-o", str(out), scene.narration], check=True)
        dur = audio_duration(out) + 0.45
        durations.append(dur)
        audio_files.append(out)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    concat_file = tmp / "audio-list.txt"
    concat_file.write_text("".join(f"file '{p}'\n" for p in audio_files), encoding="utf-8")
    narration = tmp / "narration.m4a"
    run([
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(narration),
    ])
    return narration, durations


def mux_audio(video: Path, audio: Path, out: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    run([
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ])


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(scene_list: list[Scene], durations: list[float]) -> None:
    current = 0.0
    blocks: list[str] = []
    for idx, (scene, duration) in enumerate(zip(scene_list, durations), 1):
        start = current
        end = current + duration
        blocks.append(f"{idx}\n{srt_time(start)} --> {srt_time(end)}\n{scene.caption}\n")
        current = end
    SRT_OUT.write_text("\n".join(blocks), encoding="utf-8")


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    data = metrics()
    scene_list = scenes(data)
    write_text_assets(scene_list)
    render_scene_frame(scene_list[0], 0, len(scene_list), 0, 1, data).save(COVER_OUT)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        audio, durations = generate_audio(scene_list, tmp)
        silent = tmp / "silent.mp4"
        render_video(scene_list, durations, data, silent)
        write_srt(scene_list, durations)
        if audio is not None:
            mux_audio(silent, audio, FINAL_VIDEO)
        else:
            shutil.copyfile(silent, FINAL_VIDEO)
    total = sum(durations)
    print(f"wrote {FINAL_VIDEO.relative_to(ROOT)} ({total:.1f}s)")
    print(f"wrote {SRT_OUT.relative_to(ROOT)}")
    print(f"wrote {NARRATION_TEXT.relative_to(ROOT)}")
    print(f"wrote {COVER_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
