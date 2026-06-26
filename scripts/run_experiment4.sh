#!/bin/bash
# 实验4：真实 NPU5 容器故障与恢复。只操作 yijq27-vllm-qwen15b-5。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP4_DURATION:-300}"
CONCURRENCY="${EXP4_CONCURRENCY:-32}"
BACKEND_CONTAINER="yijq27-vllm-qwen15b-5"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap 'docker start "$BACKEND_CONTAINER" >/dev/null 2>&1 || true; cleanup_router_on_exit' EXIT

echo "=== exp4: real failure and recovery on ${BACKEND_CONTAINER} ==="
echo "results: $RESULTS_DIR"
check_real_backends

start_router config/router.qwen15b-5backends-p2c.json exp4-failure
snapshot_router exp4-start

run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp4-real-failure-p2c.csv" &
LOAD_PID=$!

sleep 30
snapshot_router exp4-before-stop
echo "[exp4] docker stop ${BACKEND_CONTAINER}"
docker stop "$BACKEND_CONTAINER"
sleep 5
snapshot_router exp4-after-stop

sleep 55
snapshot_router exp4-stable-fail
echo "[exp4] docker start ${BACKEND_CONTAINER}"
docker start "$BACKEND_CONTAINER"
sleep 5
snapshot_router exp4-after-start

wait "$LOAD_PID"
snapshot_router exp4-end
plot_if_possible "$RESULTS_DIR/exp4-real-failure-p2c.csv" "$RESULTS_DIR/plots/exp4-real-failure-p2c.png"
stop_tracked_router

echo "exp4 done"
