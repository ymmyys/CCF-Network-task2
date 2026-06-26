#!/bin/bash
# 运行实验3：capacity动态下降
# 验证capacity从10降到1再恢复的平滑过渡

set -e

# 配置
ROUTER_CONFIG="config/router.qwen15b-p2c.example.json"
ROUTER_ADMIN_PORT=8181
ROUTER_DATA_PORT=8180
RESULTS_DIR="bench/results"
DURATION=120
CONCURRENCY=32
BACKEND_ID="qwen15b-npu3"
POOL="default"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验3：capacity动态下降 ==="

# 1. 启动p2c_smooth_wrr router
echo "1. 启动p2c_smooth_wrr调度器..."
# 停止现有router
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

# 启动router
docker exec -d yijq27-cann851 bash -lc "
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config $ROUTER_CONFIG \
    >>/workspace/logs/suan-router-capacity-drop.log 2>&1
"
sleep 3

# 2. 开始持续压测（后台运行）
echo "2. 开始持续压测 (${DURATION}s, 并发${CONCURRENCY})..."
python3 bench/loadgen.py \
  --url http://127.0.0.1:$ROUTER_DATA_PORT/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration $DURATION \
  --concurrency $CONCURRENCY \
  --timeout 90 \
  --output "$RESULTS_DIR/exp3-capacity-drop-p2c.csv" &
LOAD_PID=$!

# 3. 注入capacity变化
echo "3. 注入capacity变化..."
echo "  第30秒: capacity 10 -> 1"
echo "  第80秒: capacity 1 -> 10"
python3 bench/inject_capacity.py \
  --admin http://127.0.0.1:$ROUTER_ADMIN_PORT \
  --event 30,$POOL,$BACKEND_ID,1 \
  --event 80,$POOL,$BACKEND_ID,10 &
INJECT_PID=$!

# 4. 等待负载测试完成
echo "4. 等待负载测试完成..."
wait $LOAD_PID
wait $INJECT_PID

# 5. 生成图表
echo "5. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp3-capacity-drop-p2c.csv" \
  --output "$RESULTS_DIR/plots/exp3-capacity-drop-p2c.png"

# 6. 收集router状态快照
echo "6. 收集router状态快照..."
echo "=== 实验期间的状态快照 ===" > "$RESULTS_DIR/exp3-state-snapshots.txt"
echo "时间点: 实验开始前" >> "$RESULTS_DIR/exp3-state-snapshots.txt"
curl -s http://127.0.0.1:$ROUTER_ADMIN_PORT/admin/state >> "$RESULTS_DIR/exp3-state-snapshots.txt"
echo -e "\n\n" >> "$RESULTS_DIR/exp3-state-snapshots.txt"

# 7. 清理
echo "7. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== 实验3完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp3-capacity-drop-p2c.csv"
echo "  - $RESULTS_DIR/exp3-state-snapshots.txt"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp3-capacity-drop-p2c.png"