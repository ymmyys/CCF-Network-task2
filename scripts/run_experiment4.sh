#!/bin/bash
# 运行实验4：后端故障与恢复
# 证明高可用性：自动摘除异常后端，恢复后slow-start

set -e

# 配置
ROUTER_CONFIG="config/router.qwen15b-p2c.example.json"
ROUTER_ADMIN_PORT=8181
ROUTER_DATA_PORT=8180
RESULTS_DIR="bench/results"
DURATION=150
CONCURRENCY=32
BACKEND_CONTAINER="yijq27-vllm-qwen15b-3"

# 创建结果目录
mkdir -p "$RESULTS_DIR"

echo "=== 实验4：后端故障与恢复 ==="

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
    >>/workspace/logs/suan-router-failure-recovery.log 2>&1
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
  --output "$RESULTS_DIR/exp4-failure-recovery-p2c.csv" &
LOAD_PID=$!

# 3. 第30秒停止backend-0容器
echo "3. 第30秒停止backend-0容器..."
sleep 30
echo "停止容器: $BACKEND_CONTAINER"
docker stop $BACKEND_CONTAINER

# 4. 第90秒恢复backend-0容器
echo "4. 第90秒恢复backend-0容器..."
sleep 60
echo "启动容器: $BACKEND_CONTAINER"
docker start $BACKEND_CONTAINER

# 5. 等待负载测试完成
echo "5. 等待负载测试完成..."
wait $LOAD_PID

# 6. 生成图表
echo "6. 生成汇总图表..."
python3 bench/plot_results.py \
  --input "$RESULTS_DIR/exp4-failure-recovery-p2c.csv" \
  --output "$RESULTS_DIR/plots/exp4-failure-recovery-p2c.png"

# 7. 收集router状态快照
echo "7. 收集router状态快照..."
echo "=== 实验期间的状态快照 ===" > "$RESULTS_DIR/exp4-state-snapshots.txt"
echo "时间点: 实验结束后" >> "$RESULTS_DIR/exp4-state-snapshots.txt"
curl -s http://127.0.0.1:$ROUTER_ADMIN_PORT/admin/state >> "$RESULTS_DIR/exp4-state-snapshots.txt"
echo -e "\n\n" >> "$RESULTS_DIR/exp4-state-snapshots.txt"

# 8. 清理
echo "8. 清理..."
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill" 2>/dev/null || true

echo "=== 实验4完成 ==="
echo "结果文件:"
echo "  - $RESULTS_DIR/exp4-failure-recovery-p2c.csv"
echo "  - $RESULTS_DIR/exp4-state-snapshots.txt"
echo "图表:"
echo "  - $RESULTS_DIR/plots/exp4-failure-recovery-p2c.png"