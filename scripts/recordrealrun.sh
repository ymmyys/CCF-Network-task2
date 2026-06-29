#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/workspace/Track1_fuiglwgfnq_repos}"
WORK_DIR="${WORK_DIR:-/tmp/suan-router-arch-realrun}"
ROUTER_BIN="$WORK_DIR/suan-router"
ROUTER_CONFIG="$WORK_DIR/router.json"
ROUTER_LOG="$WORK_DIR/router.log"
ROUTER_PID_FILE="$WORK_DIR/router.pid"
RESULT_CSV="$WORK_DIR/realrun.csv"
STATE_BEFORE="$WORK_DIR/state-before.json"
STATE_AFTER="$WORK_DIR/state-after.json"
METRICS_AFTER="$WORK_DIR/metrics-after.txt"
DATA_PORT="${DATA_PORT:-18180}"
ADMIN_PORT="${ADMIN_PORT:-18181}"
DEMO_DURATION="${DEMO_DURATION:-16}"
DEMO_CONCURRENCY="${DEMO_CONCURRENCY:-8}"
MODEL="${MODEL:-qwen2.5-1.5b-instruct}"
PAUSE="${DEMO_PAUSE:-4}"

cd "$REPO_DIR"
mkdir -p "$WORK_DIR"

pause() {
  sleep "$PAUSE"
}

section() {
  clear 2>/dev/null || true
  printf '============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

run() {
  printf '\n$ %s\n' "$*"
  "$@"
}

cleanup_router() {
  if [ -f "$ROUTER_PID_FILE" ]; then
    local pid
    pid="$(cat "$ROUTER_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && ps -p "$pid" -o args= 2>/dev/null | grep -q "$ROUTER_BIN"; then
      printf '\n清理：只停止本脚本启动的 router pid=%s\n' "$pid"
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.2
      done
    fi
    rm -f "$ROUTER_PID_FILE"
  fi
}
trap cleanup_router EXIT

print_backend_state() {
  local file="$1"
  python3 - "$file" <<'PY'
import json
import sys

path = sys.argv[1]
state = json.load(open(path, encoding="utf-8"))
pools = state.get("pools", [])
if isinstance(pools, dict):
    pools = [{"name": name, **value} for name, value in pools.items()]
for pool in pools:
    print(f"pool={pool.get('name', 'default')}")
    for item in pool.get("backends", []):
        print(
            f"  {item.get('id')}: phase={item.get('phase')} "
            f"healthy={item.get('healthy')} "
            f"effective={float(item.get('effective_weight', 0)):.2f} "
            f"desired={float(item.get('desired_weight', 0)):.2f} "
            f"remote_util={float(item.get('remote_utilization', 0)):.3f} "
            f"kv={float(item.get('kv_cache_usage', 0)):.3f} "
            f"inflight={item.get('inflight')}"
        )
PY
}

summarize_csv() {
  python3 - "$RESULT_CSV" <<'PY'
import csv
import statistics
import sys
from collections import Counter

path = sys.argv[1]
rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
lat = sorted(float(row["latency_ms"]) for row in rows if row.get("latency_ms"))
codes = Counter(row.get("status", "") for row in rows)
backends = Counter(row.get("backend", "") or "missing" for row in rows)
errors = sum(1 for row in rows if row.get("error"))

def pct(values, q):
    if not values:
        return 0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[idx]

print(f"requests={len(rows)} errors={errors} status={dict(codes)}")
print(f"latency_ms p50={pct(lat, 0.50):.2f} p95={pct(lat, 0.95):.2f} p99={pct(lat, 0.99):.2f}")
print("backend distribution:")
for backend, count in sorted(backends.items()):
    share = count / max(len(rows), 1) * 100
    print(f"  {backend}: {count} ({share:.2f}%)")
PY
}

section "1/8 项目架构：动态负载感知推理调度"
cat <<'EOF'
OpenAI 客户端
  |
  |  /v1/chat/completions
  v
suan-router 数据面 :18180
  |-- 管理面 /admin/state :18181
  |-- Prometheus /metrics :18181
  |-- 调度：P2C + smooth weighted round robin
  |-- 权重：capacity * headroom(load score)
  |
  +--> vLLM-Ascend qwen15b-npu3  :9021  NPU 3
  +--> vLLM-Ascend qwen15b-npu4  :9022  NPU 4
  +--> vLLM-Ascend qwen15b-npu5  :9026  NPU 5
  +--> vLLM-Ascend qwen15b-npu6  :9027  NPU 6
  +--> vLLM-Ascend qwen15b-npu7  :9028  NPU 7

router 周期性读取 vLLM /metrics，将 running、waiting、KV cache、
本地 inflight 和延迟 EWMA 合成为 load score，再平滑调整 effective weight。
EOF
pause

section "2/8 代码结构：入口、调度器、后端状态机"
run bash -lc "find cmd internal config -maxdepth 3 -type f | sort | sed -n '1,34p'"
printf '\n关键实现位置：\n'
run bash -lc "grep -R -n -E 'weightedLoadScore|desiredWeight|effective_weight|smooth|P2C|Resource-Pool|metrics_url' internal/router config/router.qwen15b-5backends-p2c.json | sed -n '1,38p'"
pause

section "3/8 真实后端健康检查与 NPU 快照"
run bash -lc "for p in 9021 9022 9026 9027 9028; do printf '%s ' \"\$p\"; curl -fsS --max-time 2 \"http://127.0.0.1:\${p}/health\" >/dev/null && echo ok || echo fail; done"
if command -v npu-smi >/dev/null 2>&1; then
  run bash -lc "npu-smi info | sed -n '1,38p'"
fi
pause

section "4/8 构建当前 router 并生成临时配置"
run go build -o "$ROUTER_BIN" ./cmd/router
python3 - "$ROUTER_CONFIG" "$DATA_PORT" "$ADMIN_PORT" <<'PY'
import json
import sys
from pathlib import Path

out, data_port, admin_port = sys.argv[1:4]
cfg = json.loads(Path("config/router.qwen15b-5backends-p2c.json").read_text())
cfg["listen"] = f":{data_port}"
cfg["admin_listen"] = f":{admin_port}"
Path(out).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
print(out)
PY
run bash -lc "sed -n '1,32p' '$ROUTER_CONFIG'"
pause

section "5/8 启动真实 router，并读取初始 admin state"
if ss -ltn 2>/dev/null | grep -E ":(${DATA_PORT}|${ADMIN_PORT})\\b" >/dev/null; then
  echo "临时端口 ${DATA_PORT}/${ADMIN_PORT} 被占用，拒绝杀未知进程。"
  exit 1
fi
"$ROUTER_BIN" -config "$ROUTER_CONFIG" >"$ROUTER_LOG" 2>&1 &
echo $! > "$ROUTER_PID_FILE"
for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null 2>&1 && break
  sleep 0.25
done
run bash -lc "curl -fsS http://127.0.0.1:${ADMIN_PORT}/healthz"
run bash -lc "curl -fsS http://127.0.0.1:${ADMIN_PORT}/admin/state > '$STATE_BEFORE'"
print_backend_state "$STATE_BEFORE"
pause

section "6/8 真实实验：通过 router 发起 OpenAI-compatible 请求"
BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"
printf 'duration=%ss concurrency=%s model=%s\n' "$DEMO_DURATION" "$DEMO_CONCURRENCY" "$MODEL"
run python3 bench/loadgen.py \
  --url "http://127.0.0.1:${DATA_PORT}/v1/chat/completions" \
  --header "Content-Type:application/json" \
  --body "$BODY" \
  --duration "$DEMO_DURATION" \
  --concurrency "$DEMO_CONCURRENCY" \
  --timeout 90 \
  --output "$RESULT_CSV"
summarize_csv
pause

section "7/8 实验后状态：权重、实时负载与 metrics"
run bash -lc "curl -fsS http://127.0.0.1:${ADMIN_PORT}/admin/state > '$STATE_AFTER'"
print_backend_state "$STATE_AFTER"
run bash -lc "curl -fsS http://127.0.0.1:${ADMIN_PORT}/metrics > '$METRICS_AFTER'"
run bash -lc "grep -E 'backend|request|remote|weight|inflight|kv' '$METRICS_AFTER' | sed -n '1,42p'"
pause

section "8/8 结果位置与安全清理"
printf '临时实验结果：%s\n' "$WORK_DIR"
run bash -lc "ls -lh '$WORK_DIR'"
printf '\n本脚本退出时只清理自己启动的 router，不停止 vLLM 后端容器。\n'
printf '后端容器由外层录制流程统一停止释放 NPU。\n'
