#!/bin/bash
# 实验5：真实 NPU 资源池隔离。default=NPU3/4，isolated=NPU5/6/7。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP5_DURATION:-120}"
DEFAULT_CONCURRENCY="${EXP5_DEFAULT_CONCURRENCY:-32}"
ISOLATED_CONCURRENCY="${EXP5_ISOLATED_CONCURRENCY:-96}"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap cleanup_router_on_exit EXIT

echo "=== exp5: real resource-pool isolation ==="
echo "results: $RESULTS_DIR"
check_real_backends

start_router config/router.qwen15b-multi-pool-real.json exp5-multipool
snapshot_router exp5-start

run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$DEFAULT_CONCURRENCY" \
  "$RESULTS_DIR/exp5-real-default.csv" \
  --header 'X-Resource-Pool:default' &
DEFAULT_PID=$!

run_long_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$ISOLATED_CONCURRENCY" \
  "$RESULTS_DIR/exp5-real-isolated.csv" \
  --header 'X-Resource-Pool:isolated' &
ISOLATED_PID=$!

sleep 30 && snapshot_router exp5-running || true
wait "$DEFAULT_PID"
wait "$ISOLATED_PID"

snapshot_router exp5-end
plot_if_possible "$RESULTS_DIR/exp5-real-default.csv" "$RESULTS_DIR/plots/exp5-real-default.png"
plot_if_possible "$RESULTS_DIR/exp5-real-isolated.csv" "$RESULTS_DIR/plots/exp5-real-isolated.png"
stop_tracked_router

echo "exp5 done"
