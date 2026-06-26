#!/bin/bash
# 实验3：真实 NPU capacity 10 -> 1 -> 10 平滑迁移。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP3_DURATION:-120}"
CONCURRENCY="${EXP3_CONCURRENCY:-32}"
POOL="${EXP3_POOL:-default}"
BACKEND_ID="${EXP3_BACKEND:-qwen15b-npu3}"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

echo "=== exp3: real capacity transition ==="
echo "results: $RESULTS_DIR"
check_real_backends

start_router config/router.qwen15b-5backends-p2c.json exp3-capacity
snapshot_router exp3-start

run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp3-real-capacity-p2c.csv" &
LOAD_PID=$!

python3 bench/inject_capacity.py \
  --admin http://127.0.0.1:${ROUTER_ADMIN_PORT} \
  --event 30,${POOL},${BACKEND_ID},1 \
  --event 80,${POOL},${BACKEND_ID},10 &
INJECT_PID=$!

sleep 29 && snapshot_router exp3-before-down || true
sleep 4 && snapshot_router exp3-transition-down || true
sleep 17 && snapshot_router exp3-stable-down || true
sleep 30 && snapshot_router exp3-after-up || true

wait "$LOAD_PID"
wait "$INJECT_PID"
snapshot_router exp3-end
plot_if_possible "$RESULTS_DIR/exp3-real-capacity-p2c.csv" "$RESULTS_DIR/plots/exp3-real-capacity-p2c.png"
stop_tracked_router

echo "exp3 done"
