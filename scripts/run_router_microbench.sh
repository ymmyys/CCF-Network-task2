#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=${ROOT_DIR:-/workspace/Track1_fuiglwgfnq_repos}
BEFORE_BIN=${BEFORE_BIN:-/tmp/mutt-before}
AFTER_BIN=${AFTER_BIN:-/tmp/mutt-after}
RESULT_DIR=${RESULT_DIR:-/tmp/mutt-microbench}

DATA_PORT=${DATA_PORT:-18180}
ADMIN_PORT=${ADMIN_PORT:-18181}
HOT_PORT=${HOT_PORT:-19031}
COOL_PORT=${COOL_PORT:-19032}
HOT_METRICS_PORT=${HOT_METRICS_PORT:-19131}
COOL_METRICS_PORT=${COOL_METRICS_PORT:-19132}

PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

require_free_port() {
  local port=$1
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}$"; then
    echo "port ${port} is already in use; aborting without killing any process" >&2
    exit 1
  fi
}

for port in "$DATA_PORT" "$ADMIN_PORT" "$HOT_PORT" "$COOL_PORT" "$HOT_METRICS_PORT" "$COOL_METRICS_PORT"; do
  require_free_port "$port"
done

if [[ ! -x "$BEFORE_BIN" ]]; then
  echo "missing BEFORE_BIN: $BEFORE_BIN" >&2
  exit 1
fi
if [[ ! -x "$AFTER_BIN" ]]; then
  echo "missing AFTER_BIN: $AFTER_BIN" >&2
  exit 1
fi

cd "$ROOT_DIR"
mkdir -p "$RESULT_DIR"

CONFIG_FILE="$RESULT_DIR/router-hot-cold.json"
cat >"$CONFIG_FILE" <<JSON
{
  "listen": ":${DATA_PORT}",
  "admin_listen": ":${ADMIN_PORT}",
  "default_pool": "default",
  "update_interval": "1s",
  "probe_timeout": "500ms",
  "smooth_step": 0.25,
  "failure_cooloff_duration": "1s",
  "scheduler": {"mode": "p2c_smooth_wrr"},
  "load": {
    "ewma_alpha": 0.35,
    "utilization_weight": 0.35,
    "queue_weight": 0.25,
    "inflight_weight": 0.2,
    "kv_cache_weight": 0.1,
    "latency_weight": 0.1,
    "queue_soft_limit": 16,
    "kv_cache_soft_limit": 1,
    "latency_slo_ms": 2500,
    "min_healthy_fraction": 0.03
  },
  "pools": [{
    "name": "default",
    "backends": [
      {
        "id": "hot",
        "url": "http://127.0.0.1:${HOT_PORT}",
        "capacity": 100,
        "max_inflight": 256,
        "health_url": "http://127.0.0.1:${HOT_PORT}/healthz",
        "metrics_url": "http://127.0.0.1:${HOT_METRICS_PORT}/metrics"
      },
      {
        "id": "cool",
        "url": "http://127.0.0.1:${COOL_PORT}",
        "capacity": 1,
        "max_inflight": 256,
        "health_url": "http://127.0.0.1:${COOL_PORT}/healthz",
        "metrics_url": "http://127.0.0.1:${COOL_METRICS_PORT}/metrics"
      }
    ]
  }]
}
JSON

python3 bench/fake_backend.py \
  --port "$HOT_PORT" \
  --metrics-port "$HOT_METRICS_PORT" \
  --id hot \
  --latency-ms 300 \
  --utilization 95 \
  --queue-depth 16 \
  --kv-cache 0.8 \
  >"$RESULT_DIR/hot.log" 2>&1 &
PIDS+=("$!")

python3 bench/fake_backend.py \
  --port "$COOL_PORT" \
  --metrics-port "$COOL_METRICS_PORT" \
  --id cool \
  --latency-ms 50 \
  --utilization 10 \
  --queue-depth 0 \
  --kv-cache 0.1 \
  >"$RESULT_DIR/cool.log" 2>&1 &
PIDS+=("$!")

sleep 1

run_case() {
  local label=$1
  local bin=$2
  local csv="$RESULT_DIR/${label}.csv"

  "$bin" -config "$CONFIG_FILE" >"$RESULT_DIR/router-${label}.log" 2>&1 &
  local router_pid=$!
  PIDS+=("$router_pid")
  sleep 2

  python3 bench/loadgen.py \
    --url "http://127.0.0.1:${DATA_PORT}/v1/chat/completions" \
    --header 'Content-Type:application/json' \
    --body '{"prompt":"hello"}' \
    --duration 12 \
    --concurrency 16 \
    --timeout 5 \
    --output "$csv" \
    >"$RESULT_DIR/load-${label}.log"

  kill "$router_pid" 2>/dev/null || true
  wait "$router_pid" 2>/dev/null || true
}

run_case before "$BEFORE_BIN"
run_case after "$AFTER_BIN"

python3 - "$RESULT_DIR" <<'PY'
import csv
import sys
from collections import Counter

result_dir = sys.argv[1]

def pct(values, q):
    if not values:
        return 0.0
    idx = min(len(values) - 1, int(len(values) * q))
    return values[idx]

for label in ("before", "after"):
    with open(f"{result_dir}/{label}.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    latencies = sorted(float(row["latency_ms"]) for row in rows)
    backends = Counter(row["backend"] for row in rows)
    ok = sum(1 for row in rows if 200 <= int(row["status"] or 0) < 500 and not row["error"])
    print(
        label,
        "total", len(rows),
        "ok", ok,
        "qps", round(len(rows) / 12, 2),
        "p50", round(pct(latencies, 0.50), 2),
        "p95", round(pct(latencies, 0.95), 2),
        "p99", round(pct(latencies, 0.99), 2),
        "backends", dict(backends),
    )
PY
