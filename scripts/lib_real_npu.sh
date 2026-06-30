#!/bin/bash

ROUTER_CONTAINER="${ROUTER_CONTAINER:-yijq27-cann851}"
CONTAINER_REPO="${CONTAINER_REPO:-/workspace/Track1_fuiglwgfnq_repos}"
ROUTER_BIN="${ROUTER_BIN:-/workspace/bin/mutt}"
ROUTER_DATA_PORT="${ROUTER_DATA_PORT:-8180}"
ROUTER_ADMIN_PORT="${ROUTER_ADMIN_PORT:-8181}"
ROUTER_PID_FILE="${ROUTER_PID_FILE:-/tmp/mutt-real-experiment.pid}"
MODEL="${MODEL:-qwen2.5-1.5b-instruct}"

SHORT_BODY="${SHORT_BODY:-}"
LONG_BODY="${LONG_BODY:-}"

if [ -z "$SHORT_BODY" ]; then
  SHORT_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"
fi

if [ -z "$LONG_BODY" ]; then
  LONG_PROMPT="Write a detailed technical note about distributed inference scheduling. Cover dynamic capacity, health checks, queueing, tail latency control, KV cache pressure, slow-start recovery, passive ejection, and multi-pool isolation. Repeat the analysis with concrete examples, tradeoffs, and failure scenarios. Include a step-by-step reasoning section and a final operational checklist. "
  LONG_PROMPT="${LONG_PROMPT}${LONG_PROMPT}${LONG_PROMPT}${LONG_PROMPT}"
  LONG_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"${LONG_PROMPT}\"}],\"max_tokens\":512,\"temperature\":0}"
fi

ensure_results_dir() {
  mkdir -p "$RESULTS_DIR" "$RESULTS_DIR/plots" "$RESULTS_DIR/snapshots"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

require_experiment_tools() {
  require_cmd docker
  require_cmd curl
  require_cmd python3
}

stop_tracked_router() {
  docker exec "$ROUTER_CONTAINER" bash -lc "
    set +e
    pidfile='$ROUTER_PID_FILE'
    if [ -f \"\$pidfile\" ]; then
      pid=\$(cat \"\$pidfile\" 2>/dev/null || true)
      if [ -n \"\$pid\" ] && ps -p \"\$pid\" -o args= | grep -q '$ROUTER_BIN'; then
        kill \"\$pid\" 2>/dev/null || true
        for _ in \$(seq 1 20); do
          kill -0 \"\$pid\" 2>/dev/null || break
          sleep 0.5
        done
        kill -0 \"\$pid\" 2>/dev/null && kill -TERM \"\$pid\" 2>/dev/null || true
      fi
      rm -f \"\$pidfile\"
    fi
  " >/dev/null
}

assert_router_ports_free() {
  if ss -ltn 2>/dev/null | grep -E ":(8180|8181)\b" >/dev/null; then
    echo "router experiment ports 8180/8181 are busy; refusing to kill unknown processes" >&2
    ss -ltnp 2>/dev/null | grep -E ":(8180|8181)\b" >&2 || true
    exit 1
  fi
}

start_router() {
  local config="$1"
  local tag="$2"
  local log_path="/workspace/logs/mutt-${tag}.log"

  stop_tracked_router
  assert_router_ports_free

  docker exec "$ROUTER_CONTAINER" bash -lc "
    mkdir -p /workspace/logs
    cd '$CONTAINER_REPO'
    nohup '$ROUTER_BIN' -config '$config' >>'$log_path' 2>&1 &
    echo \$! > '$ROUTER_PID_FILE'
  "

  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${ROUTER_ADMIN_PORT}/healthz" >/dev/null 2>&1; then
      echo "router started: $config (log: $log_path)"
      return
    fi
    sleep 0.5
  done

  echo "router failed to become healthy: $config" >&2
  docker exec "$ROUTER_CONTAINER" bash -lc "tail -n 80 '$log_path' 2>/dev/null || true" >&2
  stop_tracked_router
  exit 1
}

snapshot_router() {
  local label="$1"
  curl -fsS "http://127.0.0.1:${ROUTER_ADMIN_PORT}/admin/state" > "$RESULTS_DIR/snapshots/${label}.state.json" || true
  curl -fsS "http://127.0.0.1:${ROUTER_ADMIN_PORT}/metrics" > "$RESULTS_DIR/snapshots/${label}.metrics.txt" || true
}

check_backend_health() {
  local name="$1"
  local url="$2"
  echo "checking $name: $url"
  curl -fsS "$url" >/dev/null
}

check_real_backends() {
  check_backend_health qwen15b-npu3 http://127.0.0.1:9021/health
  check_backend_health qwen15b-npu4 http://127.0.0.1:9022/health
  check_backend_health qwen15b-npu5 http://127.0.0.1:9026/health
  check_backend_health qwen15b-npu6 http://127.0.0.1:9027/health
  check_backend_health qwen15b-npu7 http://127.0.0.1:9028/health
}

run_short_load() {
  local url="$1"
  local duration="$2"
  local concurrency="$3"
  local output="$4"
  shift 4
  python3 bench/loadgen.py \
    --url "$url" \
    --header 'Content-Type:application/json' \
    "$@" \
    --body "$SHORT_BODY" \
    --duration "$duration" \
    --concurrency "$concurrency" \
    --timeout 90 \
    --output "$output"
}

run_long_load() {
  local url="$1"
  local duration="$2"
  local concurrency="$3"
  local output="$4"
  shift 4
  python3 bench/loadgen.py \
    --url "$url" \
    --header 'Content-Type:application/json' \
    "$@" \
    --body "$LONG_BODY" \
    --duration "$duration" \
    --concurrency "$concurrency" \
    --timeout 180 \
    --output "$output"
}

plot_if_possible() {
  local input="$1"
  local output="$2"
  python3 bench/plot_results.py --input "$input" --output "$output" || true
}

cleanup_router_on_exit() {
  stop_tracked_router || true
}
