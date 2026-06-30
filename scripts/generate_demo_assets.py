#!/usr/bin/env python3
"""Generate local demo-page and draft-video assets for the prototype video."""

from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path
from typing import Iterable

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_CSV = ROOT / "bench/results/formal/analysis/real_npu_summary.csv"
DEMO_DIR = ROOT / "docs/demo/work"
HTML_OUT = DEMO_DIR / "prototype-demo.html"
VIDEO_OUT = DEMO_DIR / "prototype-demo-draft.mp4"


def load_rows() -> list[dict[str, str]]:
    with SUMMARY_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def row(rows: list[dict[str, str]], exp: str, scheduler: str, window: str = "all") -> dict[str, str]:
    for item in rows:
        if item["experiment_id"] == exp and item["scheduler"] == scheduler and item["window"] == window:
            return item
    raise KeyError((exp, scheduler, window))


def fmt(value: str, suffix: str = "", digits: int = 2) -> str:
    if value == "":
        return "-"
    number = float(value)
    if math.isclose(number, round(number), abs_tol=1e-9):
        text = str(int(round(number)))
    else:
        text = f"{number:.{digits}f}"
    return text + suffix


def metrics(rows: list[dict[str, str]]) -> dict[str, str]:
    exp2_swrr = row(rows, "exp2", "swrr")
    exp2_p2c = row(rows, "exp2", "p2c_smooth_wrr")
    exp2_bal = row(rows, "exp2", "balanced_p2c")
    exp3_down = row(rows, "exp3", "p2c_smooth_wrr", "stable_down_40_80")
    exp3_all = row(rows, "exp3", "p2c_smooth_wrr")
    exp4_fail = row(rows, "exp4", "p2c_smooth_wrr", "fail_stable_35_90")
    exp4_recover = row(rows, "exp4", "p2c_smooth_wrr", "recovery_end_240_300")
    exp4_all = row(rows, "exp4", "p2c_smooth_wrr")
    exp5_default = row(rows, "exp5", "p2c_smooth_wrr", "all")
    # exp5 has two all rows; pick by source file.
    for item in rows:
        if item["experiment_id"] == "exp5" and "exp5-real-default.csv" in item["source_file"]:
            exp5_default = item
        if item["experiment_id"] == "exp5" and "exp5-real-isolated.csv" in item["source_file"]:
            exp5_isolated = item
    exp8_swrr = row(rows, "exp8", "swrr")
    exp8_p2c = row(rows, "exp8", "p2c_smooth_wrr")
    exp8_bal = row(rows, "exp8", "balanced_p2c")
    return {
        "exp2_swrr_share": fmt(exp2_swrr["target_share_pct"], "%"),
        "exp2_p2c_share": fmt(exp2_p2c["target_share_pct"], "%"),
        "exp2_bal_share": fmt(exp2_bal["target_share_pct"], "%"),
        "exp2_p2c_p99": fmt(exp2_p2c["p99_ms"], "ms"),
        "exp2_swrr_p99": fmt(exp2_swrr["p99_ms"], "ms"),
        "exp3_share": fmt(exp3_down["target_share_pct"], "%"),
        "exp3_expected": fmt(exp3_down["expected_share_pct"], "%"),
        "exp3_error": fmt(exp3_all["total_errors"]),
        "exp3_requests": fmt(exp3_all["total_requests"]),
        "exp4_fail_share": fmt(exp4_fail["target_share_pct"], "%"),
        "exp4_recover_share": fmt(exp4_recover["target_share_pct"], "%"),
        "exp4_errors": fmt(exp4_all["total_errors"]),
        "exp4_requests": fmt(exp4_all["total_requests"]),
        "exp5_default_requests": fmt(exp5_default["total_requests"]),
        "exp5_default_errors": fmt(exp5_default["total_errors"]),
        "exp5_isolated_requests": fmt(exp5_isolated["total_requests"]),
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


def build_html(data: dict[str, str]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MUTT 原型展示</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --ink: #101217;
      --muted: #5b6472;
      --line: #d8dee8;
      --green: #0f8b6f;
      --cyan: #087ea4;
      --red: #c2413b;
      --yellow: #c88a08;
      --panel: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--ink);
      overflow: hidden;
    }}
    .deck {{ width: 100vw; height: 100vh; position: relative; }}
    .slide {{
      position: absolute;
      inset: 0;
      padding: 5vh 6vw 7vh;
      display: none;
    }}
    .slide.active {{ display: grid; grid-template-rows: auto 1fr auto; gap: 28px; }}
    .eyebrow {{ color: var(--cyan); font-size: 18px; font-weight: 700; letter-spacing: 0; }}
    h1 {{ margin: 10px 0 0; font-size: 56px; line-height: 1.04; letter-spacing: 0; }}
    h2 {{ margin: 0; font-size: 42px; line-height: 1.1; letter-spacing: 0; }}
    p {{ font-size: 21px; line-height: 1.55; color: var(--muted); margin: 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 28px; align-items: stretch; min-height: 0; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      min-width: 0;
    }}
    .panel h3 {{ margin: 0 0 18px; font-size: 25px; letter-spacing: 0; }}
    .bullets {{ display: grid; gap: 14px; }}
    .bullet {{ font-size: 23px; line-height: 1.42; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    .metric {{ border-left: 5px solid var(--green); padding: 12px 12px 12px 16px; background: #f4fbf8; border-radius: 6px; }}
    .metric.red {{ border-color: var(--red); background: #fff6f5; }}
    .metric.cyan {{ border-color: var(--cyan); background: #f2f9fc; }}
    .metric strong {{ display: block; font-size: 36px; line-height: 1; }}
    .metric span {{ color: var(--muted); font-size: 17px; }}
    .arch {{ display: grid; grid-template-columns: 1fr 1.25fr 1fr; gap: 18px; align-items: center; height: 100%; }}
    .node {{ border: 1px solid var(--line); border-radius: 8px; padding: 20px; background: #fff; text-align: center; font-size: 22px; font-weight: 700; }}
    .node.router {{ border-color: var(--cyan); box-shadow: inset 0 0 0 3px #d9f0f7; }}
    .backends {{ display: grid; gap: 10px; }}
    .backend {{ display: flex; justify-content: space-between; border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; background: #fff; font-size: 18px; }}
    .formula {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 27px; background: #101217; color: white; padding: 22px; border-radius: 8px; }}
    .bars {{ display: grid; gap: 16px; margin-top: 18px; }}
    .bar-row {{ display: grid; grid-template-columns: 170px 1fr 90px; gap: 12px; align-items: center; font-size: 18px; }}
    .track {{ height: 22px; background: #e8edf4; border-radius: 6px; overflow: hidden; }}
    .fill {{ height: 100%; background: var(--green); }}
    .fill.red {{ background: var(--red); }}
    .fill.cyan {{ background: var(--cyan); }}
    .footer {{ display: flex; justify-content: space-between; color: var(--muted); font-size: 16px; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #eef2f7; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <script>window.DEMO_DATA = {payload};</script>
  <main class="deck">
    <section class="slide active">
      <header>
        <div class="eyebrow">赛题2：大模型推理算力资源动态负载感知调度</div>
        <h1>MUTT<br>多信号闭环动态权重调度方案</h1>
      </header>
      <div class="grid">
        <div class="panel">
          <h3>要解决的问题</h3>
          <div class="bullets">
            <div class="bullet">静态轮询无法感知后端真实负载。</div>
            <div class="bullet">热点 NPU 会继续收到请求，造成尾延迟和错误扩散。</div>
            <div class="bullet">capacity 降低时，新请求需要平滑迁移，已分配请求不能中断。</div>
          </div>
        </div>
        <div class="panel">
          <h3>原型目标</h3>
          <div class="metric-grid">
            <div class="metric cyan"><strong>5</strong><span>真实 Ascend NPU</span></div>
            <div class="metric"><strong>0</strong><span>正式主结论 fake 数据</span></div>
            <div class="metric"><strong>8</strong><span>实验分组</span></div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>OpenAI-compatible router + vLLM-Ascend</span><span>1 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">系统架构</div><h2>Router 位于客户端和 vLLM-Ascend 后端之间</h2></header>
      <div class="panel">
        <div class="arch">
          <div class="node">OpenAI 客户端<br><span style="font-weight:500;color:var(--muted)">/v1/chat/completions</span></div>
          <div class="node router">MUTT<br><span style="font-weight:500;color:var(--muted)">8180 data / 8181 admin / metrics</span></div>
          <div class="backends">
            <div class="backend"><span>NPU3</span><span>vLLM</span></div>
            <div class="backend"><span>NPU4</span><span>vLLM</span></div>
            <div class="backend"><span>NPU5</span><span>vLLM</span></div>
            <div class="backend"><span>NPU6</span><span>vLLM</span></div>
            <div class="backend"><span>NPU7</span><span>vLLM</span></div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>资源池：<code>X-Resource-Pool</code>；指标：health + inflight + vLLM /metrics</span><span>2 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">核心算法</div><h2>多维负载评分 + 平滑有效权重</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>权重计算</h3>
          <div class="formula">desired_weight = capacity * headroom<br><br>effective_weight += (desired - effective) * smooth_step</div>
        </div>
        <div class="panel">
          <h3>负载信号</h3>
          <div class="bullets">
            <div class="bullet">vLLM running / waiting</div>
            <div class="bullet">KV cache usage</div>
            <div class="bullet">router 本地 inflight</div>
            <div class="bullet">延迟 EWMA + 健康状态机</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>调度器：SWRR / P2C smooth WRR / balanced P2C</span><span>3 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">exp2：真实热点避让</div><h2>有压力的 NPU3 不再继续接收主要流量</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>NPU3 测量流量占比</h3>
          <div class="bars">
            <div class="bar-row"><span>SWRR</span><div class="track"><div class="fill red" style="width:19.96%"></div></div><strong>{data["exp2_swrr_share"]}</strong></div>
            <div class="bar-row"><span>P2C</span><div class="track"><div class="fill" style="width:0%"></div></div><strong>{data["exp2_p2c_share"]}</strong></div>
            <div class="bar-row"><span>balanced</span><div class="track"><div class="fill cyan" style="width:3.94%"></div></div><strong>{data["exp2_bal_share"]}</strong></div>
          </div>
        </div>
        <div class="panel">
          <h3>解释</h3>
          <div class="bullets">
            <div class="bullet">SWRR 不配置 metrics，作为静态基线。</div>
            <div class="bullet">P2C 读到 <code>remote_utilization=1.0</code> 后避开热点。</div>
            <div class="bullet">p99 从 {data["exp2_swrr_p99"]} 降到 {data["exp2_p2c_p99"]}。</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>真实 NPU3 direct 长请求压力 + router 测量流量</span><span>4 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">exp3：capacity 10->1->10</div><h2>新请求平滑迁移，已分配请求不中断</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>稳定降容窗口</h3>
          <div class="metric-grid">
            <div class="metric"><strong>{data["exp3_share"]}</strong><span>实际 NPU3 占比</span></div>
            <div class="metric cyan"><strong>{data["exp3_expected"]}</strong><span>理论占比</span></div>
            <div class="metric"><strong>{data["exp3_error"]}</strong><span>错误数</span></div>
          </div>
        </div>
        <div class="panel">
          <h3>验收意义</h3>
          <div class="bullets">
            <div class="bullet">capacity 降低不等于强制中断。</div>
            <div class="bullet">29,748 请求，0 错误。</div>
            <div class="bullet">恢复后占比回到约 20%。</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>赛题核心要求：权重变化需要有平滑过渡机制</span><span>5 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">exp4 + exp5：高可用与资源池隔离</div><h2>故障摘除、恢复慢启动、noisy neighbor 隔离</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>故障恢复</h3>
          <div class="metric-grid">
            <div class="metric"><strong>{data["exp4_fail_share"]}</strong><span>故障稳定期 NPU5 占比</span></div>
            <div class="metric cyan"><strong>{data["exp4_recover_share"]}</strong><span>恢复末段占比</span></div>
            <div class="metric red"><strong>{data["exp4_errors"]}</strong><span>{data["exp4_requests"]} 请求中的错误</span></div>
          </div>
        </div>
        <div class="panel">
          <h3>资源池隔离</h3>
          <div class="bullets">
            <div class="bullet">default 池：{data["exp5_default_requests"]} 请求，{data["exp5_default_errors"]} 错误。</div>
            <div class="bullet">isolated 池：{data["exp5_isolated_requests"]} 长请求承压。</div>
            <div class="bullet">default 与 isolated 使用独立调度空间。</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>故障实验只操作指定项目容器</span><span>6 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">exp8：Qwen2.5-7B 泛化验证</div><h2>更大模型上仍能避开热点 NPU</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>NPU3 流量占比</h3>
          <div class="bars">
            <div class="bar-row"><span>SWRR</span><div class="track"><div class="fill red" style="width:19.81%"></div></div><strong>{data["exp8_swrr_share"]}</strong></div>
            <div class="bar-row"><span>P2C</span><div class="track"><div class="fill" style="width:0%"></div></div><strong>{data["exp8_p2c_share"]}</strong></div>
            <div class="bar-row"><span>balanced</span><div class="track"><div class="fill cyan" style="width:3.64%"></div></div><strong>{data["exp8_bal_share"]}</strong></div>
          </div>
        </div>
        <div class="panel">
          <h3>QPS / p99</h3>
          <div class="bullets">
            <div class="bullet">SWRR：{data["exp8_swrr_qps"]} QPS，p99 {data["exp8_swrr_p99"]}</div>
            <div class="bullet">P2C：{data["exp8_p2c_qps"]} QPS，p99 {data["exp8_p2c_p99"]}</div>
            <div class="bullet">balanced：{data["exp8_bal_qps"]} QPS，p99 {data["exp8_bal_p99"]}</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>7B 后端为临时容器，实验后删除释放 NPU</span><span>7 / 8</span></footer>
    </section>

    <section class="slide">
      <header><div class="eyebrow">交付与复现</div><h2>代码、操作手册和真实实验数据已入仓</h2></header>
      <div class="grid">
        <div class="panel">
          <h3>仓库证据</h3>
          <div class="bullets">
            <div class="bullet"><code>docs/final-report.md</code>：最终技术报告。</div>
            <div class="bullet"><code>docs/runbook.md</code>：容器内启动、测试、清理和迁移。</div>
            <div class="bullet"><code>bench/results/formal/</code>：真实 NPU 原始数据和快照。</div>
          </div>
        </div>
        <div class="panel">
          <h3>安全边界</h3>
          <div class="bullets">
            <div class="bullet">正式结论不使用 fake backend。</div>
            <div class="bullet">router 只清理自己记录的 PID。</div>
            <div class="bullet">不停止无关容器，不占用卡。</div>
          </div>
        </div>
      </div>
      <footer class="footer"><span>使用方向键切换页面</span><span>8 / 8</span></footer>
    </section>
  </main>
  <script>
    const slides = [...document.querySelectorAll('.slide')];
    let idx = 0;
    function show(next) {{
      idx = Math.max(0, Math.min(slides.length - 1, next));
      slides.forEach((s, i) => s.classList.toggle('active', i === idx));
    }}
    window.addEventListener('keydown', (event) => {{
      if (['ArrowRight', ' ', 'PageDown'].includes(event.key)) show(idx + 1);
      if (['ArrowLeft', 'PageUp'].includes(event.key)) show(idx - 1);
    }});
  </script>
</body>
</html>
"""


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


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        bbox = draw.textbbox((0, 0), trial, font=face)
        if bbox[2] - bbox[0] <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    face: ImageFont.ImageFont,
    fill: str,
    width: int,
    line_gap: int = 8,
) -> int:
    x, y = xy
    for line in wrap(draw, text, face, width):
        draw.text((x, y), line, font=face, fill=fill)
        y += face.size + line_gap
    return y


def slide_frames(data: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "title": "MUTT：面向昇腾 NPU 推理集群的多信号闭环动态权重调度方案",
            "subtitle": "赛题2：大模型推理算力资源动态负载感知调度",
            "bullets": ["真实 Ascend NPU 3-7", "OpenAI-compatible router", "健康、负载、capacity、资源池统一调度"],
            "duration": 18,
        },
        {
            "title": "系统架构",
            "subtitle": "Client -> Router -> 5 个 vLLM-Ascend 后端",
            "bullets": ["数据面 8180，管理面 8181", "读取 /health、/metrics、本地 inflight", "资源池通过 X-Resource-Pool 隔离"],
            "duration": 30,
        },
        {
            "title": "核心算法",
            "subtitle": "desired_weight = capacity * headroom",
            "bullets": ["headroom 来自 running、waiting、KV cache、inflight、延迟 EWMA", "effective_weight 通过 smooth_step 平滑追随", "P2C 在两个候选中选择负载更低的后端"],
            "duration": 34,
        },
        {
            "title": "exp2：真实热点避让",
            "subtitle": f"NPU3 流量：SWRR {data['exp2_swrr_share']} -> P2C {data['exp2_p2c_share']} -> balanced {data['exp2_bal_share']}",
            "bullets": ["NPU3 direct 长 prompt 背景压力", "P2C 读到 remote_utilization=1.0 后避开热点", f"p99 从 {data['exp2_swrr_p99']} 降到 {data['exp2_p2c_p99']}"],
            "duration": 48,
        },
        {
            "title": "exp3：capacity 10->1->10",
            "subtitle": f"稳定降容占比 {data['exp3_share']}，理论 {data['exp3_expected']}",
            "bullets": [f"{data['exp3_requests']} 请求，{data['exp3_error']} 错误", "新请求平滑迁移", "已分配请求不强制中断"],
            "duration": 42,
        },
        {
            "title": "exp4 + exp5：高可用与隔离",
            "subtitle": f"故障稳定期 NPU5 占比 {data['exp4_fail_share']}，恢复末段 {data['exp4_recover_share']}",
            "bullets": [f"故障实验 {data['exp4_requests']} 请求，{data['exp4_errors']} 错误", f"default 池 {data['exp5_default_requests']} 请求，{data['exp5_default_errors']} 错误", "isolated 池长请求压力不影响 default 池"],
            "duration": 42,
        },
        {
            "title": "exp8：Qwen2.5-7B 泛化验证",
            "subtitle": f"NPU3 流量：SWRR {data['exp8_swrr_share']} -> P2C {data['exp8_p2c_share']} -> balanced {data['exp8_bal_share']}",
            "bullets": [f"QPS：{data['exp8_swrr_qps']} -> {data['exp8_p2c_qps']} -> {data['exp8_bal_qps']}", f"p99：{data['exp8_swrr_p99']} -> {data['exp8_p2c_p99']} -> {data['exp8_bal_p99']}", "7B 临时容器已删除释放 NPU"],
            "duration": 34,
        },
        {
            "title": "交付与复现",
            "subtitle": "正式结论只引用真实 NPU 数据",
            "bullets": ["docs/final-report.md：最终报告", "docs/runbook.md：容器内运行、停止、迁移", "bench/results/formal/：原始 CSV、metrics、state 快照"],
            "duration": 24,
        },
    ]


def draw_slide(slide: dict[str, object], index: int, total: int) -> Image.Image:
    width, height = 1600, 896
    image = Image.new("RGB", (width, height), "#f7f8fb")
    draw = ImageDraw.Draw(image)
    title_font = font(58, True)
    subtitle_font = font(32)
    bullet_font = font(34)
    small_font = font(22)
    draw.rectangle((0, 0, width, 18), fill="#087ea4")
    draw.text((92, 70), "原型展示草稿", font=small_font, fill="#087ea4")
    y = draw_text_block(draw, (90, 120), str(slide["title"]), title_font, "#101217", 1160, 10)
    y = draw_text_block(draw, (90, y + 20), str(slide["subtitle"]), subtitle_font, "#5b6472", 1220, 10)
    panel_top = max(370, y + 35)
    draw.rounded_rectangle((90, panel_top, 1510, 780), radius=8, fill="#ffffff", outline="#d8dee8", width=2)
    bullet_y = panel_top + 52
    for item in slide["bullets"]:  # type: ignore[index]
        draw.ellipse((130, bullet_y + 12, 148, bullet_y + 30), fill="#0f8b6f")
        bullet_y = draw_text_block(draw, (172, bullet_y), str(item), bullet_font, "#101217", 1210, 8) + 22
    draw.text((90, 824), "MUTT / Ascend NPU 3-7 / vLLM-Ascend", font=small_font, fill="#5b6472")
    draw.text((1410, 824), f"{index + 1} / {total}", font=small_font, fill="#5b6472")
    return image


def write_video(data: dict[str, str]) -> None:
    slides = slide_frames(data)
    fps = 2
    frames: list[np.ndarray] = []
    for i, slide in enumerate(slides):
        image = draw_slide(slide, i, len(slides))
        frame = np.asarray(image)
        for _ in range(int(slide["duration"]) * fps):  # type: ignore[index]
            frames.append(frame)
    imageio.mimsave(VIDEO_OUT, frames, fps=fps, quality=8, macro_block_size=16)


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    data = metrics(load_rows())
    HTML_OUT.write_text(build_html(data), encoding="utf-8")
    write_video(data)
    print(f"wrote {HTML_OUT.relative_to(ROOT)}")
    print(f"wrote {VIDEO_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
