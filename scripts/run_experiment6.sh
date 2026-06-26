#!/bin/bash
# 实验6：综合剧本实验
# 把降容、热点、故障、恢复放到一个真实端到端流程里展示

set -e

# 配置
RESULTS_DIR="bench/results"
DURATION=180
CONCURRENCY=32
MODEL="qwen2.5-1.5b-instruct"
REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with pong only.\"}],\"max_tokens\":16,\"temperature\":0}"
LONG_REQUEST_BODY="{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a detailed essay about artificial intelligence, machine learning, and deep learning. Include examples and explanations of neural networks, transformers, and large language models. Discuss the impact of AI on society and future developments.\"}],\"max_tokens\":256,\"temperature\":0}"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验6：综合剧本实验 ==="
echo "时间线:"
echo "0-30s：5个真实vLLM-Ascend后端正常服务"
echo "30s：对npu3降容 10 → 1"
echo "60s：向npu4注入长prompt压力，制造热点"
echo "90s：停止npu5后端，模拟故障"
echo "120s：恢复npu5"
echo "150s：恢复npu3 capacity 1 → 10"
echo "180s：结束"

# 1. 启动p2c_smooth_wrr router
echo "1. 启动p2c_smooth_wrr调度器..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-5backends-p2c.json \
    >>/workspace/logs/suan-router-comprehensive.log 2>&1
"
sleep 3

# 2. 开始主负载测试
echo "2. 开始主负载测试 (${DURATION}s, 并发${CONCURRENCY})..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body "$REQUEST_BODY" \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp6-comprehensive.csv" &

MAIN_PID=$!

# 3. 开始指标采集
echo "3. 开始指标采集..."
python3 bench/collect_metrics.py \
  --vllm-urls "http://127.0.0.1:9021/metrics,http://127.0.0.1:9022/metrics,http://127.0.0.1:9026/metrics,http://127.0.0.1:9027/metrics,http://127.0.0.1:9028/metrics" \
  --admin-url http://127.0.0.1:8181 \
  --output "$RESULTS_DIR/exp6-comprehensive-metrics.csv" \
  --interval 1.0 \
  --duration $DURATION &

METRICS_PID=$!

# 4. 执行剧本事件
echo "4. 执行剧本事件..."

# 第30秒：降容 npu3 10 → 1
sleep 30
echo "  [30s] 降容 npu3: 10 → 1"
curl -X POST http://127.0.0.1:8181/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'

# 第60秒：向npu4注入长prompt压力
sleep 30
echo "  [60s] 向npu4注入长prompt压力..."
for i in {1..5}; do
  curl -s http://127.0.0.1:9022/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d "$LONG_REQUEST_BODY" > /dev/null &
done

# 第90秒：停止npu5后端
sleep 30
echo "  [90s] 停止npu5后端..."
docker stop yijq27-vllm-qwen15b-5

# 第120秒：恢复npu5后端
sleep 30
echo "  [120s] 恢复npu5后端..."
docker start yijq27-vllm-qwen15b-5

# 第150秒：恢复npu3 capacity
sleep 30
echo "  [150s] 恢复npu3 capacity: 1 → 10"
curl -X POST http://127.0.0.1:8181/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'

# 5. 等待测试完成
echo "5. 等待测试完成..."
wait $MAIN_PID
wait $METRICS_PID

# 6. 生成图表
echo "6. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp6-comprehensive.csv" \
  --output "$RESULTS_DIR/plots/exp6-comprehensive.png"

# 7. 收集最终状态
echo "7. 收集最终状态..."
curl -s http://127.0.0.1:8181/admin/state > "$RESULTS_DIR/exp6-final-state.json"

# 8. 清理
echo "8. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

# 确保npu5容器运行
docker start yijq27-vllm-qwen15b-5 2>/dev/null || true

echo "=== 实验6完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp6-comprehensive.csv"
echo "  - $RESULTS_DIR/exp6-comprehensive-metrics.csv"
echo "  - $RESULTS_DIR/exp6-final-state.json"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp6-comprehensive.png"