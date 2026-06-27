#!/bin/bash
# 实验8：Qwen2.5-7B 真实 NPU 热点压力补充验证。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-qwen7b-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP8_DURATION:-120}"
CONCURRENCY="${EXP8_CONCURRENCY:-12}"
PRESSURE_CONCURRENCY="${EXP8_PRESSURE_CONCURRENCY:-12}"
MODEL="${MODEL:-qwen2.5-7b-instruct}"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

check_qwen7b_backends() {
  check_backend_health qwen7b-npu3 http://127.0.0.1:9121/health
  check_backend_health qwen7b-npu4 http://127.0.0.1:9122/health
  check_backend_health qwen7b-npu5 http://127.0.0.1:9126/health
  check_backend_health qwen7b-npu6 http://127.0.0.1:9127/health
  check_backend_health qwen7b-npu7 http://127.0.0.1:9128/health
}

run_qwen7b_hotspot_case() {
  local scheduler="$1"
  local config="$2"
  local tag="exp8-qwen7b-${scheduler}"

  echo "[exp8] scheduler=$scheduler"
  start_router "$config" "$tag"
  snapshot_router "${tag}-start"

  python3 bench/collect_metrics.py \
    --vllm-urls "http://127.0.0.1:9121/metrics,http://127.0.0.1:9122/metrics,http://127.0.0.1:9126/metrics,http://127.0.0.1:9127/metrics,http://127.0.0.1:9128/metrics" \
    --backend-ids "qwen7b-npu3,qwen7b-npu4,qwen7b-npu5,qwen7b-npu6,qwen7b-npu7" \
    --admin-url http://127.0.0.1:${ROUTER_ADMIN_PORT} \
    --output "$RESULTS_DIR/exp8-qwen7b-hotspot-${scheduler}-metrics.csv" \
    --interval 1.0 \
    --duration "$DURATION" &
  local metrics_pid=$!

  run_long_load \
    http://127.0.0.1:9121/v1/chat/completions \
    "$DURATION" "$PRESSURE_CONCURRENCY" \
    "$RESULTS_DIR/exp8-qwen7b-pressure-${scheduler}.csv" &
  local pressure_pid=$!

  sleep 5
  run_short_load \
    http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
    "$DURATION" "$CONCURRENCY" \
    "$RESULTS_DIR/exp8-qwen7b-hotspot-${scheduler}.csv"

  wait "$pressure_pid"
  wait "$metrics_pid" || true
  snapshot_router "${tag}-end"
  plot_if_possible "$RESULTS_DIR/exp8-qwen7b-hotspot-${scheduler}.csv" "$RESULTS_DIR/plots/exp8-qwen7b-hotspot-${scheduler}.png"
  stop_tracked_router
}

echo "=== exp8: Qwen2.5-7B real hotspot pressure on qwen7b-npu3 ==="
echo "results: $RESULTS_DIR"
check_qwen7b_backends

run_qwen7b_hotspot_case swrr config/router.qwen7b-5backends-swrr.json
run_qwen7b_hotspot_case p2c config/router.qwen7b-5backends-p2c.json
run_qwen7b_hotspot_case balanced config/router.qwen7b-5backends-balanced.json

echo "exp8 done"
