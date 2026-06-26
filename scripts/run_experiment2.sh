#!/bin/bash
# 运行实验2：异构负载场景
# 使用fake_backend模拟慢后端

set -e

# 配置
ROUTER_CONFIG_P2C="config/router.qwen15b-heterogeneous-p2c.json"
ROUTER_CONFIG_SWRR="config/router.qwen15b-heterogeneous-swrr.json"
FAKE_BACKEND_PORT=9023
FAKE_METRICS_PORT=9123
ROUTER_ADMIN_PORT=8181
ROUTER_DATA_PORT=8180
RESULTS_DIR="bench/results"
DURATION=120
CONCURRENCY=32

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验2：异构负载场景 ==="

# 1. 启动fake后端（慢后端）
echo "1. 启动fake慢后端 (延迟300ms)..."
python3 bench/fake_backend.py \
  --port $FAKE_BACKEND_PORT \
  --metrics-port $FAKE_METRICS_PORT \
  --id slow-backend \
  --latency-ms 300 \
  --utilization 90 \
  --queue-depth 16 \
  --kv-cache 0.8 &
FAKE_PID=$!
sleep 2

# 2. 运行p2c_smooth_wrr实验
echo "2. 运行p2c_smooth_wrr调度器..."
# 停止现有router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

# 启动p2c router
docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config $ROUTER_CONFIG_P2C \
    >>/workspace/logs/suan-router-heterogeneous-p2c.log 2>&1
"
sleep 3

# 运行负载测试
echo "运行负载测试 (${DURATION}s, 并发${CONCURRENCY})..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:$ROUTER_DATA_PORT/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp2-heterogeneous-p2c.csv"

# 3. 运行swrr基线实验
echo "3. 运行swrr基线调度器..."
# 停止现有router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

# 启动swrr router
docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config $ROUTER_CONFIG_SWRR \
    >>/workspace/logs/suan-router-heterogeneous-swrr.log 2>&1
"
sleep 3

# 运行负载测试
echo "运行负载测试 (${DURATION}s, 并发${CONCURRENCY})..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:$ROUTER_DATA_PORT/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp2-heterogeneous-swrr.csv"

# 4. 生成图表
echo "4. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp2-heterogeneous-p2c.csv" \
  --output "$RESULTS_DIR/plots/exp2-heterogeneous-p2c.png"

python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp2-heterogeneous-swrr.csv" \
  --output "$RESULTS_DIR/plots/exp2-heterogeneous-swrr.png"

# 5. 清理
echo "5. 清理..."
kill $FAKE_PID 2>/dev/null || true
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== 实验2完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp2-heterogeneous-p2c.csv"
echo "  - $RESULTS_DIR/exp2-heterogeneous-swrr.csv"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp2-heterogeneous-p2c.png"
echo "  - $RESULTS_DIR/plots/exp2-heterogeneous-swrr.png"