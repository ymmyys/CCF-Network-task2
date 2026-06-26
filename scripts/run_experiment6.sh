#!/bin/bash
# 实验6：真实 NPU 综合剧本。包含降容、热点压力、npu5 故障、恢复。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

RESULTS_DIR="${RESULTS_DIR:-bench/results/real-npu-$(date +%Y%m%d%H%M%S)}"
DURATION="${EXP6_DURATION:-210}"
CONCURRENCY="${EXP6_CONCURRENCY:-32}"
PRESSURE_CONCURRENCY="${EXP6_PRESSURE_CONCURRENCY:-6}"
BACKEND_CONTAINER="yijq27-vllm-qwen15b-5"

source "$SCRIPT_DIR/lib_real_npu.sh"
require_experiment_tools
ensure_results_dir
trap 'docker start "$BACKEND_CONTAINER" >/dev/null 2>&1 || true; cleanup_router_on_exit' EXIT

echo "=== exp6: real comprehensive scenario ==="
echo "results: $RESULTS_DIR"
check_real_backends

start_router config/router.qwen15b-5backends-p2c.json exp6-comprehensive
snapshot_router exp6-start

run_short_load \
  http://127.0.0.1:${ROUTER_DATA_PORT}/v1/chat/completions \
  "$DURATION" "$CONCURRENCY" \
  "$RESULTS_DIR/exp6-real-comprehensive.csv" &
MAIN_PID=$!

python3 bench/collect_metrics.py \
  --vllm-urls "http://127.0.0.1:9021/metrics,http://127.0.0.1:9022/metrics,http://127.0.0.1:9026/metrics,http://127.0.0.1:9027/metrics,http://127.0.0.1:9028/metrics" \
  --backend-ids "qwen15b-npu3,qwen15b-npu4,qwen15b-npu5,qwen15b-npu6,qwen15b-npu7" \
  --admin-url http://127.0.0.1:${ROUTER_ADMIN_PORT} \
  --output "$RESULTS_DIR/exp6-real-comprehensive-metrics.csv" \
  --interval 1.0 \
  --duration "$DURATION" &
METRICS_PID=$!

sleep 30
echo "[exp6] npu3 capacity 10 -> 1"
curl -fsS -X POST http://127.0.0.1:${ROUTER_ADMIN_PORT}/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'
snapshot_router exp6-after-down

sleep 30
echo "[exp6] background pressure on npu4"
run_long_load \
  http://127.0.0.1:9022/v1/chat/completions \
  60 "$PRESSURE_CONCURRENCY" \
  "$RESULTS_DIR/exp6-real-npu4-pressure.csv" &
PRESSURE_PID=$!
snapshot_router exp6-pressure-start

sleep 30
echo "[exp6] docker stop ${BACKEND_CONTAINER}"
docker stop "$BACKEND_CONTAINER"
snapshot_router exp6-after-stop

sleep 30
echo "[exp6] docker start ${BACKEND_CONTAINER}"
docker start "$BACKEND_CONTAINER"
snapshot_router exp6-after-start

sleep 30
echo "[exp6] npu3 capacity 1 -> 10"
curl -fsS -X POST http://127.0.0.1:${ROUTER_ADMIN_PORT}/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'
snapshot_router exp6-after-up

wait "$PRESSURE_PID" || true
wait "$MAIN_PID"
wait "$METRICS_PID" || true

snapshot_router exp6-end
plot_if_possible "$RESULTS_DIR/exp6-real-comprehensive.csv" "$RESULTS_DIR/plots/exp6-real-comprehensive.png"
stop_tracked_router

echo "exp6 done"
