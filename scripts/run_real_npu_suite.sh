#!/bin/bash
# 完整真实 Ascend NPU 实验套件。只使用 NPU 3-7 和指定项目容器。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

export RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
mkdir -p "$RESULTS_DIR"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools

echo "=== real NPU suite ==="
echo "repo: $REPO_DIR"
echo "results: $RESULTS_DIR"

echo "[suite] npu-smi snapshot"
docker exec "$ROUTER_CONTAINER" bash -lc "npu-smi info" > "$RESULTS_DIR/npu-smi-before.txt" || true

echo "[suite] build router in CANN container"
docker exec "$ROUTER_CONTAINER" bash -lc "cd '$CONTAINER_REPO' && go build -o '$ROUTER_BIN' ./cmd/router"

check_real_backends

"$SCRIPT_DIR/run_experiment1.sh"
"$SCRIPT_DIR/run_experiment2_real.sh"
"$SCRIPT_DIR/run_experiment3.sh"
"$SCRIPT_DIR/run_experiment4.sh"

echo "[suite] waiting for npu5 health after fault experiment"
for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:9026/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
check_real_backends

"$SCRIPT_DIR/run_experiment5_noisy.sh"
"$SCRIPT_DIR/run_experiment6.sh"

echo "[suite] waiting for npu5 health after comprehensive experiment"
for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:9026/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
check_real_backends

"$SCRIPT_DIR/run_smoothstep_experiment.sh"

python3 bench/generate_summary.py --results-dir "$RESULTS_DIR" --output-dir "$RESULTS_DIR/analysis"
docker exec "$ROUTER_CONTAINER" bash -lc "npu-smi info" > "$RESULTS_DIR/npu-smi-after.txt" || true

echo "real NPU suite done: $RESULTS_DIR"
