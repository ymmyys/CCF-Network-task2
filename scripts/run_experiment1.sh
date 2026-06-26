#!/bin/bash
# 实验1：真实 NPU 正常均衡场景。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP1_DURATION:-60}"
CONCURRENCY="${EXP1_CONCURRENCY:-32}"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

echo "=== exp1: real balanced baseline ==="
echo "results: $RESULTS_DIR"
check_real_backends

echo "[exp1] direct single-backend reference: npu3"
run_short_load \
  http://127.0.0.1:9021/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp1-real-direct-npu3.csv"
plot_if_possible "$RESULTS_DIR/exp1-real-direct-npu3.csv" "$RESULTS_DIR/plots/exp1-real-direct-npu3.png"

echo "[exp1] router + swrr, five real backends"
start_router config/router.qwen15b-5backends-swrr.json exp1-swrr
snapshot_router exp1-swrr-start
run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp1-real-swrr.csv"
snapshot_router exp1-swrr-end
plot_if_possible "$RESULTS_DIR/exp1-real-swrr.csv" "$RESULTS_DIR/plots/exp1-real-swrr.png"
stop_tracked_router

echo "[exp1] router + p2c_smooth_wrr, five real backends"
start_router config/router.qwen15b-5backends-p2c.json exp1-p2c
snapshot_router exp1-p2c-start
run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp1-real-p2c.csv"
snapshot_router exp1-p2c-end
plot_if_possible "$RESULTS_DIR/exp1-real-p2c.csv" "$RESULTS_DIR/plots/exp1-real-p2c.png"
stop_tracked_router

echo "[exp1] router + balanced_p2c, five real backends"
start_router config/router.qwen15b-5backends-balanced.json exp1-balanced
snapshot_router exp1-balanced-start
run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp1-real-balanced.csv"
snapshot_router exp1-balanced-end
plot_if_possible "$RESULTS_DIR/exp1-real-balanced.csv" "$RESULTS_DIR/plots/exp1-real-balanced.png"
stop_tracked_router

echo "exp1 done"
