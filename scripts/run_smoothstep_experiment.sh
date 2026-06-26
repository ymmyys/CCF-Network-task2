#!/bin/bash
# 实验7：真实 NPU smoothStep 参数敏感性。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP7_DURATION:-80}"
CONCURRENCY="${EXP7_CONCURRENCY:-32}"
SMOOTH_STEPS=(0.1 0.25 0.5 1.0)

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

echo "=== exp7: real smoothStep sensitivity ==="
echo "results: $RESULTS_DIR"
check_real_backends

for smooth_step in "${SMOOTH_STEPS[@]}"; do
  tag="exp7-ss${smooth_step}"
  config="config/router-ss5-${smooth_step}.json"
  echo "[exp7] smoothStep=${smooth_step}"

  start_router "$config" "$tag"
  snapshot_router "${tag}-start"

  run_short_load \
    http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
    "$DURATION" "$CONCURRENCY" \
    "$RESULTS_DIR/exp7-real-ss${smooth_step}.csv" &
  LOAD_PID=$!

  sleep 20
  curl -fsS -X POST http://127.0.0.1:${ROUTER_ADMIN_PORT}/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'
  snapshot_router "${tag}-after-down"

  sleep 30
  snapshot_router "${tag}-stable-down"
  curl -fsS -X POST http://127.0.0.1:${ROUTER_ADMIN_PORT}/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'
  snapshot_router "${tag}-after-up"

  wait "$LOAD_PID"
  snapshot_router "${tag}-end"
  plot_if_possible "$RESULTS_DIR/exp7-real-ss${smooth_step}.csv" "$RESULTS_DIR/plots/exp7-real-ss${smooth_step}.png"
  stop_tracked_router
done

echo "exp7 done"
