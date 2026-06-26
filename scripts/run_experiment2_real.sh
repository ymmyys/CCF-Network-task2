#!/bin/bash
# 实验2：异构负载场景 - 真实NPU压力实验
# 通过背景请求制造真实热点

set -e

# 配置
RESULTS_DIR="bench/results"
DURATION=120
CONCURRENCY=32
MODEL="qwen2.5-1.5b-instruct"
REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"
# 长prompt请求，用于制造KV Cache压力
LONG_REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a detailed essay about artificial intelligence, machine learning, and deep learning. Include examples and explanations of neural networks, transformers, and large language models. Discuss the impact of AI on society and future developments.\"}],\"max_tokens\":256,\"temperature\":0}"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验2：异构负载场景 - 真实NPU压力实验 ==="

# 1. 启动p2c_smooth_wrr router
echo "1. 启动p2c_smooth_wrr调度器..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-p2c.example.json \
    >>/workspace/logs/suan-router-heterogeneous.log 2>&1
"
sleep 3

# 2. 启动背景压力（直接向NPU3发送长prompt请求）
echo "2. 启动背景压力 (NPU 3)..."
# 后台发送长prompt请求，制造KV Cache压力
for i in {1..10}; do
  curl -s http://127.0.0.1:9021/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d "$LONG_REQUEST_BODY" > /dev/null &
done

# 3. 运行主负载测试
echo "3. 运行主负载测试 (${DURATION}s, 并发${CONCURRENCY})..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp2-heterogeneous-real-p2c.csv" &

MAIN_PID=$!

# 4. 持续制造背景压力
echo "4. 持续制造背景压力..."
for round in {1..5}; do
  sleep 20
  echo "  第${round}轮背景压力..."
  for i in {1..5}; do
    curl -s http://127.0.0.1:9021/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d "$LONG_REQUEST_BODY" > /dev/null &
  done
done

# 5. 等待主测试完成
echo "5. 等待主测试完成..."
wait $MAIN_PID

# 6. 生成图表
echo "6. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp2-heterogeneous-real-p2c.csv" \
  --output "$RESULTS_DIR/plots/exp2-heterogeneous-real-p2c.png"

# 7. 清理
echo "7. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

# 杀死所有背景curl进程
pkill -f "curl.*9021" 2>/dev/null || true

echo "=== 实验2完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp2-heterogeneous-real-p2c.csv"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp2-heterogeneous-real-p2c.png"