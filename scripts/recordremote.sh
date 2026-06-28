#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/workspace/Track1_fuiglwgfnq_repos}"
SUMMARY_DIR="${SUMMARY_DIR:-/tmp/suan-recording-summary}"
PAUSE="${DEMO_PAUSE:-2}"

cd "$REPO_DIR"

run() {
  printf '\n$ %s\n' "$*"
  "$@"
}

pause() {
  sleep "$PAUSE"
}

section() {
  clear 2>/dev/null || true
  printf '============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

section "1/7 VS Code 已连接远程 Ascend 容器"
run pwd
run hostname
run whoami
run bash -lc "sed -n '1,6p' /etc/os-release"
printf '\n左下角状态栏可见：容器 yijq27-cann851 @ kunlun-02-act\n'
pause

section "2/7 真实 NPU 与模型环境"
if command -v npu-smi >/dev/null 2>&1; then
  run bash -lc "npu-smi info | sed -n '1,42p'"
else
  printf 'npu-smi 不在 PATH 中，跳过设备快照。\n'
fi
printf '\n模型目录：\n'
run bash -lc "find /workspace/models -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort || true"
pause

section "3/7 仓库代码与运行入口"
run bash -lc "git rev-parse --abbrev-ref HEAD 2>/dev/null || true"
run bash -lc "git log -1 --oneline 2>/dev/null || true"
printf '\n核心运行入口：\n'
run bash -lc "find cmd internal config -maxdepth 3 -type f | sort | sed -n '1,32p'"
printf '\n调度器关键逻辑位置：\n'
run bash -lc "grep -R -n -E 'weightedLoadScore|desiredWeight|smooth|P2C|Resource-Pool' internal/router | sed -n '1,28p'"
pause

section "4/7 正式实验数据按实验入库"
run bash -lc "find bench/results/formal -maxdepth 2 -type f | wc -l"
run bash -lc "find bench/results/formal -maxdepth 1 -type d | sort"
printf '\n真实 NPU 汇总结论：\n'
run bash -lc "sed -n '1,24p' bench/results/formal/analysis/real_npu_summary.md"
pause

section "5/7 脚本与配置静态检查"
run bash -lc "bash -n scripts/run_real_npu_suite.sh scripts/run_experiment2_real.sh scripts/run_experiment3.sh scripts/run_experiment4.sh scripts/run_experiment5_noisy.sh scripts/run_smoothstep_experiment.sh scripts/run_experiment8_qwen7b_real.sh"
run bash -lc "python3 -m py_compile bench/generate_summary.py bench/collect_metrics.py bench/loadgen.py scripts/generate_final_demo_video.py"
printf '\n检查通过：正式实验脚本和汇总脚本可执行。\n'
pause

section "6/7 从真实结果重新生成汇总"
run bash -lc "rm -rf '$SUMMARY_DIR' && python3 bench/generate_summary.py --results-dir bench/results/formal --output-dir '$SUMMARY_DIR'"
run bash -lc "sed -n '1,26p' '$SUMMARY_DIR/real_npu_summary.md'"
pause

section "7/7 热点避让与 vLLM 指标证据"
python3 - <<'PY'
import json
from pathlib import Path

root = Path("bench/results/formal")
state_file = root / "exp2-hotspot-load" / "exp2-p2c-end.state.json"
if not state_file.exists():
    print(f"缺少状态快照: {state_file}")
else:
    state = json.loads(state_file.read_text())
    pools = state.get("pools", {})
    if isinstance(pools, dict):
        backends = pools.get("default", {}).get("backends", [])
    else:
        default_pool = next((p for p in pools if p.get("name") == "default"), {})
        backends = default_pool.get("backends", [])
    print("exp2-p2c-end.state.json / default pool:")
    for item in backends:
        print(
            f"  {item.get('id')}: "
            f"remote_util={item.get('remote_utilization')}, "
            f"queue={item.get('queue_depth')}, "
            f"effective_weight={item.get('effective_weight')}, "
            f"desired_weight={item.get('desired_weight')}, "
            f"healthy={item.get('healthy')}"
        )

summary_file = root / "exp2-hotspot-load" / "summary.json"
if summary_file.exists():
    summary = json.loads(summary_file.read_text())
    print("\nexp2 请求分布摘要:")
    for key, value in summary.items():
        if isinstance(value, dict) and ("backend_share" in value or "backend_counts" in value):
            print(f"  {key}:")
            shares = value.get("backend_share") or value.get("backend_counts") or {}
            for backend, share in sorted(shares.items()):
                print(f"    {backend}: {share}")
PY
printf '\n完整重跑命令（会占用 NPU，本视频不执行）：\n'
printf 'RESULTS_DIR=bench/results/real-npu-$(date +%%Y%%m%%d%%H%%M%%S) scripts/run_real_npu_suite.sh\n'
printf '\n演示结束：本次录制展示的是远程容器中的真实代码与真实 NPU 实验结果。\n'
