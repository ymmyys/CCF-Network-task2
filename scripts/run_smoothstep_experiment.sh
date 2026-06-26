#!/bin/bash
# smoothStep参数敏感性实验
# 测试不同smoothStep值对平滑性的影响

set -e

# 配置
RESULTS_DIR="bench/results"
DURATION=60
CONCURRENCY=32
MODEL="qwen2.5-1.5b-instruct"
REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== smoothStep参数敏感性实验 ==="

# smoothStep值列表
SMOOTH_STEPS=(0.1 0.25 0.5 1.0)

for smooth_step in "${SMOOTH_STEPS[@]}"; do
  echo "测试 smoothStep = ${smooth_step}..."
  
  # 创建临时配置文件
  CONFIG_FILE="config/router-smoothstep-${smooth_step}.json"
  cat > "$CONFIG_FILE" << EOF
{
  "listen": ":8180",
  "admin_listen": ":8181",
  "default_pool": "default",
  "pool_header": "X-Resource-Pool",
  "update_interval": "1s",
  "probe_timeout": "2s",
  "smooth_step": ${smooth_step},
  "slow_start_duration": "15s",
  "passive_failure_threshold": 3,
  "passive_eject_duration": "10s",
  "scheduler": {
    "mode": "p2c_smooth_wrr"
  },
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
  "pools": [
    {
      "name": "default",
      "backends": [
        {
          "id": "qwen15b-npu3",
          "url": "http://127.0.0.1:9021",
          "capacity": 10,
          "max_inflight": 64,
          "health_url": "http://127.0.0.1:9021/health",
          "metrics_url": "http://127.0.0.1:9021/metrics"
        },
        {
          "id": "qwen15b-npu4",
          "url": "http://127.0.0.1:9022",
          "capacity": 10,
          "max_inflight": 64,
          "health_url": "http://127.0.0.1:9022/health",
          "metrics_url": "http://127.0.0.1:9022/metrics"
        }
      ]
    }
  ]
}
EOF

  # 启动router
  docker exec yijq27-cann851 bash -lc \
    "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

  docker exec -d yijq27-cann851 bash -lc "
    cd /workspace/Track1_fuiglwgfnq_repos &&
    exec /workspace/bin/suan-router \
      -config ${CONFIG_FILE} \
      >>/workspace/logs/suan-router-smoothstep-${smooth_step}.log 2>&1
  "
  sleep 3

  # 开始负载测试
  python3 bench/loadgen.py \
    --url http://127.0.0.1:8180/v1/chat/completions \
    --header 'Content-Type:application/json' \
    --body "$REQUEST_BODY" \
    --duration $DURATION \
    --concurrency $CONCURRENCY \
    --timeout 90 \
    --output "$RESULTS_DIR/exp-smoothstep-${smooth_step}.csv" &

  LOAD_PID=$!

  # 第30秒注入降容
  sleep 30
  echo "  [30s] 降容 npu3: 10 → 1"
  curl -X POST http://127.0.0.1:8181/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'

  # 第50秒恢复
  sleep 20
  echo "  [50s] 恢复 npu3: 1 → 10"
  curl -X POST http://127.0.0.1:8181/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'

  # 等待测试完成
  wait $LOAD_PID

  # 生成图表
  python3 bench/plot_results.py \
    --input "$RESULTS_DIR/exp-smoothstep-${smooth_step}.csv" \
    --output "$RESULTS_DIR/plots/exp-smoothstep-${smooth_step}.png"

  # 清理临时配置文件
  rm -f "$CONFIG_FILE"
done

# 清理router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== smoothStep参数敏感性实验完成 ==="
echo "结果文件:"
for smooth_step in "${SMOOTH_STEPS[@]}"; do
  echo "  - $RESULTS_DIR/exp-smoothstep-${smooth_step}.csv"
done
echo "图表:"
for smooth_step in "${SMOOTH_STEPS[@]}"; do
  echo "  - $RESULTS_DIR/plots/exp-smoothstep-${smooth_step}.png"
done