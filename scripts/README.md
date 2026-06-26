# 实验运行指南

本指南说明如何运行完整的7组实验，验证动态负载感知调度器的性能。

## 前置条件

1. 确保kunlun-02-act机器可访问
2. 确保vLLM后端容器运行（NPU 3和4；5后端实验需要NPU 3-7）
3. 确保router容器运行
4. 确保Python环境有必要的依赖

## 实验概览

| 实验 | 脚本 | 配置文件 | 结果文件 |
|------|------|----------|----------|
| 1. 正常均衡 | 手动运行 | router.qwen15b-p2c.example.json | exp1-balanced-*.csv |
| 2. 异构负载 | run_experiment2.sh | router.qwen15b-heterogeneous-*.json | exp2-heterogeneous-*.csv |
| 3. 动态降容 | run_experiment3.sh | router.qwen15b-p2c.example.json | exp3-capacity-drop-p2c.csv |
| 4. 故障恢复 | run_experiment4.sh | router.qwen15b-p2c.example.json | exp4-failure-recovery-p2c.csv |
| 5. 资源池隔离 | 手动运行 | router.qwen15b-multi-pool.json | exp5-pool-*.csv |
| 6. 真实NPU端到端 | 手动运行 | router.qwen15b-p2c.example.json | exp6-real-npu-p2c.csv |
| 7. smoothStep参数敏感性 | run_smoothstep_experiment.sh | router-ss5-*.json | exp7-5b-ss*.csv |

## 详细步骤

### 实验1：正常均衡场景

```bash
# 1. 启动p2c_smooth_wrr router
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-p2c.example.json \
    >>/workspace/logs/suan-router-qwen15b-p2c.log 2>&1
'

# 2. 在不同并发级别下运行负载测试
for concurrency in 16 32 64 128; do
  python3 bench/loadgen.py \
    --url http://127.0.0.1:8180/v1/chat/completions \
    --header 'Content-Type:application/json' \
    --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
    --duration 60 --concurrency $concurrency --timeout 90 \
    --output bench/results/exp1-balanced-p2c-c${concurrency}.csv
done

# 3. 切换到静态基线
docker exec yijq27-cann851 bash -lc \
  "ps -eo pid=,args= | awk '/\\/workspace\\/bin\\/suan-router -config config\\/router\\.qwen15b/ && !/awk/ {print \$1}' | xargs -r kill"

docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-static-swrr.example.json \
    >>/workspace/logs/suan-router-qwen15b-swrr.log 2>&1
'

# 4. 重复负载测试
for concurrency in 16 32 64 128; do
  python3 bench/loadgen.py \
    --url http://127.0.0.1:8180/v1/chat/completions \
    --header 'Content-Type:application/json' \
    --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
    --duration 60 --concurrency $concurrency --timeout 90 \
    --output bench/results/exp1-balanced-swrr-c${concurrency}.csv
done

# 5. 生成比较图表
python3 bench/plot_results.py \
  --input bench/results/exp1-balanced-p2c-c16.csv \
  --output bench/results/plots/exp1-balanced-p2c-c16.png
```

### 实验2：异构负载场景

```bash
# 运行实验2脚本
chmod +x scripts/run_experiment2.sh
./scripts/run_experiment2.sh
```

### 实验3：capacity动态下降

```bash
# 运行实验3脚本
chmod +x scripts/run_experiment3.sh
./scripts/run_experiment3.sh
```

### 实验4：后端故障与恢复

```bash
# 运行实验4脚本
chmod +x scripts/run_experiment4.sh
./scripts/run_experiment4.sh
```

### 实验5：资源池隔离

```bash
# 1. 启动fake后端（用于isolated池）
python3 bench/fake_backend.py --port 9024 --metrics-port 9124 --id isolated-fake-1 --latency-ms 80 &
python3 bench/fake_backend.py --port 9025 --metrics-port 9125 --id isolated-fake-2 --latency-ms 80 &

# 2. 启动多池router
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-multi-pool.json \
    >>/workspace/logs/suan-router-multi-pool.log 2>&1
'

# 3. 测试default池
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:default' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 16 --timeout 90 \
  --output bench/results/exp5-pool-default.csv

# 4. 测试isolated池
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:isolated' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 16 --timeout 90 \
  --output bench/results/exp5-pool-isolated.csv

# 5. 清理fake后端
pkill -f "fake_backend.py" || true
```

### 实验6：真实昇腾NPU端到端实验

```bash
# 1. 启动router
docker exec -d yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  exec /workspace/bin/suan-router \
    -config config/router.qwen15b-p2c.example.json \
    >>/workspace/logs/suan-router-qwen15b-p2c.log 2>&1
'

# 2. 验证后端健康
curl http://127.0.0.1:9021/health
curl http://127.0.0.1:9022/health

# 3. 测试router转发
curl -i http://127.0.0.1:8180/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Hello"}],"max_tokens":16,"temperature":0}'

# 4. 运行综合负载测试
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 120 --concurrency 64 --timeout 90 \
  --output bench/results/exp6-real-npu-p2c.csv

# 5. 生成汇总报告
python3 bench/plot_results.py \
  --input bench/results/exp6-real-npu-p2c.csv \
  --output bench/results/plots/exp6-real-npu-p2c.png

# 6. 查看最终状态
curl http://127.0.0.1:8181/admin/state
```

### 实验7：smoothStep参数敏感性

该实验需要 5 个后端（默认 NPU 3-7），用于比较 `smoothStep=0.1/0.25/0.5/1.0` 在降容 `10→1` 后的收敛速度和平滑性。

```bash
chmod +x scripts/run_smoothstep_experiment.sh
./scripts/run_smoothstep_experiment.sh
```

收口结论使用 `stable_down` 窗口，不使用包含 transition 的混合窗口。当前实验中 `smoothStep=0.25` 是较优默认折中，不表述为所有场景下绝对最优。

## 结果分析

所有实验结果保存在 `bench/results/` 目录，图表保存在 `bench/results/plots/` 目录。

### 调度优化微基准

该基准只使用 fake backend 和临时端口，不占用 NPU。脚本只清理自己启动的 PID；如果端口已被占用会直接退出。

```bash
go build -o /tmp/suan-router-after ./cmd/router
BEFORE_BIN=/tmp/suan-router-before AFTER_BIN=/tmp/suan-router-after \
  ./scripts/run_router_microbench.sh
```

用于验证 P2C 同后端高负载重采样和 `failure_cooloff_duration` 的调度效果。正式提交结论仍以真实 NPU 实验为准。

使用以下命令生成比较图表：

```bash
# 比较不同调度器的性能
python3 bench/plot_results.py \
  --input bench/results/exp1-balanced-p2c-c16.csv \
  --output bench/results/plots/exp1-balanced-p2c-c16.png

# 查看状态快照
cat bench/results/exp3-state-snapshots.txt
cat bench/results/exp4-state-snapshots.txt
```

## 注意事项

1. 实验前检查NPU占用，避免影响其他用户
2. 使用独立端口（8180/8181, 9021/9022等）
3. 每次实验后清理容器和进程
4. 记录完整的实验日志和状态快照
5. 对比实验使用相同的负载参数
