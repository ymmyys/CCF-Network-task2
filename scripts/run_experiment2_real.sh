#!/bin/bash
# 实验2：真实 NPU 热点压力。直接压 NPU3，同时通过 router 测量避热点能力。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP2_DURATION:-90}"
CONCURRENCY="${EXP2_CONCURRENCY:-32}"
PRESSURE_CONCURRENCY="${EXP2_PRESSURE_CONCURRENCY:-32}"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

echo "=== exp2: real hotspot pressure on qwen15b-npu3 ==="
echo "results: $RESULTS_DIR"
check_real_backends

run_hotspot_case() {
  local scheduler="$1"
  local config="$2"
  local tag="exp2-${scheduler}"

  echo "[exp2] scheduler=$scheduler"
  start_router "$config" "$tag"
  snapshot_router "${tag}-start"

  python3 bench/collect_metrics.py \
    --vllm-urls "http://127.0.0.1:9021/metrics,http://127.0.0.1:9022/metrics,http://127.0.0.1:9026/metrics,http://127.0.0.1:9027/metrics,http://127.0.0.1:9028/metrics" \
    --backend-ids "qwen15b-npu3,qwen15b-npu4,qwen15b-npu5,qwen15b-npu6,qwen15b-npu7" \
    --admin-url http://127.0.0.1:${ROUTER_ADMIN_PORT} \
    --output "$RESULTS_DIR/exp2-real-hotspot-${scheduler}-metrics.csv" \
    --interval 1.0 \
    --duration "$DURATION" &
  local metrics_pid=$!

  run_long_load \
    http://127.0.0.1:9021/v1/chat/completions \
    "$DURATION" "$PRESSURE_CONCURRENCY" \
    "$RESULTS_DIR/exp2-real-pressure-${scheduler}.csv" &
  local pressure_pid=$!

  sleep 3
  run_short_load \
    http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
    "$DURATION" "$CONCURRENCY" \
    "$RESULTS_DIR/exp2-real-hotspot-${scheduler}.csv"

  wait "$pressure_pid"
  wait "$metrics_pid" || true
  snapshot_router "${tag}-end"
  plot_if_possible "$RESULTS_DIR/exp2-real-hotspot-${scheduler}.csv" "$RESULTS_DIR/plots/exp2-real-hotspot-${scheduler}.png"
  stop_tracked_router
}

run_hotspot_case swrr config/router.qwen15b-5backends-swrr.json
run_hotspot_case p2c config/router.qwen15b-5backends-p2c.json
run_hotspot_case balanced config/router.qwen15b-5backends-balanced.json

echo "exp2 done"
