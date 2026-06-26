#!/bin/bash
# 实验1：正常均衡场景 - 三组对照实验
# 证明动态调度的开销和性能

set -e

# 配置
RESULTS_DIR="bench/results"
DURATION=60
CONCURRENCY=32
MODEL="qwen2.5-1.5b-instruct"
REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验1：正常均衡场景 - 三组对照实验 ==="

# 1. 直接访问vLLM后端（不经过router）
echo "1. 测试 direct-to-vLLM (NPU 3)..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:9021/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp1-direct-vllm.csv" &

DIRECT_PID=$!

# 2. 测试 router + swrr
echo "2. 测试 router + swrr..."
# 启动swrr router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-static-swrr.example.json \
    >>/workspace/logs/suan-router-swrr.log 2>&1
"
sleep 3

python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp1-router-swrr.csv" &

SWRR_PID=$!

# 3. 测试 router + p2c_smooth_wrr
echo "3. 测试 router + p2c_smooth_wrr..."
# 等待上一个实验完成
wait $DIRECT_PID
wait $SWRR_PID

# 启动p2c router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-p2c.example.json \
    >>/workspace/logs/suan-router-p2c.log 2>&1
"
sleep 3

python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp1-router-p2c.csv"

# 4. 生成汇总图表
echo "4. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp1-direct-vllm.csv" \
  --output "$RESULTS_DIR/plots/exp1-direct-vllm.png"

python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp1-router-swrr.csv" \
  --output "$RESULTS_DIR/plots/exp1-router-swrr.png"

python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp1-router-p2c.csv" \
  --output "$RESULTS_DIR/plots/exp1-router-p2c.png"

# 5. 清理
echo "5. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== 实验1完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp1-direct-vllm.csv"
echo "  - $RESULTS_DIR/exp1-router-swrr.csv"
echo "  - $RESULTS_DIR/exp1-router-p2c.csv"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp1-direct-vllm.png"
echo "  - $RESULTS_DIR/plots/exp1-router-swrr.png"
echo "  - $RESULTS_DIR/plots/exp1-router-p2c.png"