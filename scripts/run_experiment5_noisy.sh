#!/bin/bash
# 实验5：资源池隔离 - noisy-neighbor实验
# 证明资源池隔离能防止多租户干扰

set -e

# 配置
RESULTS_DIR="bench/results"
DURATION=120
MODEL="qwen2.5-1.5b-instruct"
REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"
LONG_REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a detailed essay about artificial intelligence, machine learning, and deep learning. Include examples and explanations of neural networks, transformers, and large language models. Discuss the impact of AI on society and future developments.\"}],\"max_tokens\":256,\"temperature\":0}"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验5：资源池隔离 - noisy-neighbor实验 ==="

# 1. 启动多池router
echo "1. 启动多池router..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-multi-pool.json \
    >>/workspace/logs/suan-router-multi-pool.log 2>&1
"
sleep 3

# 2. 启动default池正常负载（并发32）
echo "2. 启动default池正常负载 (并发32)..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:default' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency 32 \
  --timeout 90 \
  --output "$RESULTS_DIR/exp5-pool-default-normal.csv" &

DEFAULT_PID=$!

# 3. 启动isolated池高压负载（并发128 + 长prompt）
echo "3. 启动isolated池高压负载 (并发128 + 长prompt)..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:isolated' \
  --body "$LONG_REQUEST_BODY" \
  --duration $DURATION \
  --concurrency 128 \
  --timeout 90 \
  --output "$RESULTS_DIR/exp5-pool-isolated-highload.csv" &

ISOLATED_PID=$!

# 4. 等待测试完成
echo "4. 等待测试完成..."
wait $DEFAULT_PID
wait $ISOLATED_PID

# 5. 生成图表
echo "5. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp5-pool-default-normal.csv" \
  --output "$RESULTS_DIR/plots/exp5-pool-default-normal.png"

python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp5-pool-isolated-highload.csv" \
  --output "$RESULTS_DIR/plots/exp5-pool-isolated-highload.png"

# 6. 清理
echo "6. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== 实验5完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp5-pool-default-normal.csv"
echo "  - $RESULTS_DIR/exp5-pool-isolated-highload.csv"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp5-pool-default-normal.png"
echo "  - $RESULTS_DIR/plots/exp5-pool-isolated-highload.png"