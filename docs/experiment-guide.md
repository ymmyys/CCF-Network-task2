# 实验操作文档：大模型推理算力资源动态负载感知调度

## 一、实验环境

| 项目 | 说明 |
|------|------|
| 硬件 | 昇腾 910B NPU × 8，主机 kunlun-02-act |
| 模型 | Qwen2.5-1.5B-Instruct |
| 推理引擎 | vLLM-Ascend v0.18.0rc1 |
| Router | suan-router（Go），运行在 `yijq27-cann851` 容器 |
| 数据面 | `:8180` |
| 管理面 | `:8181` |
| 后端端口 | NPU3=9021, NPU4=9022, NPU5=9026, NPU6=9027, NPU7=9028 |
| 工具 | `bench/loadgen.py`（负载生成）、`bench/inject_capacity.py`（容量注入）、`bench/fake_backend.py`（模拟后端） |

## 二、实验前准备

### 2.1 登录远程机器
```bash
ssh kunlun-02-act
```

### 2.2 检查 NPU 占用
```bash
docker exec yijq27-cann851 bash -lc "npu-smi info"
```
确认 NPU 3~7 空闲或仅运行自己的 vLLM 容器。**禁止停止他人任务。**

### 2.3 同步代码
```bash
cd /Users/xiantianjian/Track1_fuiglwgfnq_repos
rsync -az --exclude .git ./ kunlun-02-act:/home/yijq27/workspace/Track1_fuiglwgfnq_repos/
```

### 2.4 编译 Router
```bash
docker exec yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && go build -o /workspace/bin/suan-router ./cmd/router"
```

### 2.5 启动 vLLM 后端（如未运行）
```bash
# 模型目录
MODEL_DIR=/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct
IMAGE=quay.io/ascend/vllm-ascend:v0.18.0rc1

# 启动 NPU3 后端
docker run -itd --name yijq27-vllm-qwen15b-3 --privileged --net=host --ipc=host \
  --device /dev/davinci3 --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
  -e ASCEND_RT_VISIBLE_DEVICES=3 -e HF_ENDPOINT=https://hf-mirror.com \
  -v "$MODEL_DIR":"$MODEL_DIR":ro \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  "$IMAGE" bash -lc "vllm serve $MODEL_DIR --host 0.0.0.0 --port 9021 --served-model-name qwen2.5-1.5b-instruct --tensor-parallel-size 1 --max-model-len 2048 --gpu-memory-utilization 0.75"

# 同理启动 NPU4/NPU5/NPU6/NPU7（修改 --device /dev/davinci{N} 和 ASCEND_RT_VISIBLE_DEVICES={N} 及 --port）
```

### 2.6 验证后端健康
```bash
curl http://127.0.0.1:9021/health
curl http://127.0.0.1:9022/health
# ... 对每个后端重复
```

---

## 三、实验设计与操作步骤

### 实验1：正常均衡场景（三组对照）

**思路**：对比 direct-to-vLLM（单后端基线）、router+swrr 和 router+p2c_smooth_wrr，证明动态调度无额外开销。

**操作**：
```bash
# A. direct-to-vLLM（直接访问 NPU3）
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
python3 bench/loadgen.py \
  --url http://127.0.0.1:9021/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp1-direct-vllm.csv

# B. router + swrr（2后端：npu3, npu4）
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router.qwen15b-static-swrr.example.json >>/workspace/logs/suan-router-swrr.log 2>&1"
sleep 3
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp1-router-swrr.csv

# C. router + p2c_smooth_wrr
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router.qwen15b-p2c.example.json >>/workspace/logs/suan-router-p2c.log 2>&1"
sleep 3
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp1-router-p2c.csv
```

**关键指标**：QPS、p50/p95/p99、后端分布

---

### 实验2：异构负载场景

**思路**：fast backend = 真实 vLLM（npu3），slow backend = fake_backend（真实 sleep 300ms）。预期 swrr 下 slow 节点占约 50%，p2c 能完全避开 slow 节点。

**操作**：
```bash
# 1. 启动 slow fake backend（sleep 300ms）
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
python3 bench/fake_backend.py --port 9023 --metrics-port 9123 \
  --id slow-fake --latency-ms 300 --utilization 90 --queue-depth 16 --kv-cache 0.8 &

# 2. swrr 基线
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router-het-swrr.json >>/workspace/logs/suan-router-het-swrr.log 2>&1"
sleep 3
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp2-het-swrr.csv

# 3. p2c_smooth_wrr
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router-het-p2c.json >>/workspace/logs/suan-router-het-p2c.log 2>&1"
sleep 3
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp2-het-p2c.csv

# 4. 清理
pkill -f fake_backend.py
```

**关键指标**：slow-fake 占比、p95/p99 延迟变化

---

### 实验3：动态降容场景（核心实验 ⭐）

**思路**：5 后端场景，第 30s 降容 npu3（10→1），第 80s 恢复（1→10）。目标是 29,905 请求 0 错误，npu3 占比从 20% 平滑降至 ~2.44%。

**操作**：
```bash
# 1. 启动 router（5后端 p2c）
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router.qwen15b-5backends-p2c.json >>/workspace/logs/suan-router-exp3.log 2>&1"
sleep 3

# 2. 开始负载测试（120s，后台）
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 120 --concurrency 32 --timeout 90 \
  --output bench/results/exp3-capacity-drop.csv &
LOAD_PID=$!

# 3. 第 30s 降容
sleep 30
curl -X POST http://127.0.0.1:8181/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'

# 4. 第 80s 恢复
sleep 50
curl -X POST http://127.0.0.1:8181/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'

# 5. 等待测试完成
wait $LOAD_PID
```

**时间线标准**：
```
0-30s：正常运行（基准期）
30s：注入降容事件（10→1）
30-80s：观察平滑迁移期
80s：注入恢复事件（1→10）
80-120s：观察 slow-start 恢复期
```

**关键指标**：
- 每秒 npu3 请求数及占比
- 每秒 effective_weight / desired_weight
- p50/p95/p99 延迟
- 降容收敛时间
- 恢复收敛时间
- 错误率
- 在途请求中断数

---

### 实验4：后端故障与恢复

**思路**：5 后端场景，第 30s 停止 npu5 容器，第 90s 恢复。目标是 2-3s 完成摘除，故障期错误率 < 0.1%。

**操作**：
```bash
# 1. 启动 router
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router.qwen15b-5backends-p2c.json >>/workspace/logs/suan-router-exp4.log 2>&1"
sleep 3

# 2. 开始负载测试（300s，后台）
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 300 --concurrency 32 --timeout 90 \
  --output bench/results/exp4-failure.csv &

# 3. 第 30s 停止 npu5
sleep 30
docker stop yijq27-vllm-qwen15b-5

# 4. 第 90s 恢复 npu5
sleep 60
docker start yijq27-vllm-qwen15b-5

# 5. 等待测试完成（~210s）
wait
```

**时间线标准**：
```
0-30s：正常运行
30s：停止 npu5 容器
30-90s：观察故障摘除
90s：启动 npu5 容器
90-300s：观察恢复（vLLM 需 ~160s 启动/编译）
```

**关键指标**：
- 故障检测时间（从 stop 到 npu5 占比降至 0）
- 故障期间错误率
- 恢复后 npu5 占比
- 恢复后错误率

---

### 实验5：资源池隔离

**思路**：default 池（真实 vLLM）正常负载，isolated 池（fake 后端）高压负载。验证 default 池不受 isolated 池影响。

**操作**：
```bash
# 1. 启动 fake 后端（isolated 池用）
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
python3 bench/fake_backend.py --port 9024 --metrics-port 9124 --id isolated-fake-1 --latency-ms 80 &
python3 bench/fake_backend.py --port 9025 --metrics-port 9125 --id isolated-fake-2 --latency-ms 80 &
sleep 2

# 2. 启动多池 router
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router.qwen15b-multi-pool.json >>/workspace/logs/suan-router-multi-pool.log 2>&1"
sleep 3

# 3. default 池正常负载（并发 32）
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:default' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 --concurrency 32 --timeout 90 \
  --output bench/results/exp5-pool-default.csv &

# 4. isolated 池高压负载（并发 128 + 长 prompt）
python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --header 'X-Resource-Pool:isolated' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Write a detailed essay about AI, ML and DL covering neural networks, transformers and LLMs."}],"max_tokens":256,"temperature":0}' \
  --duration 60 --concurrency 128 --timeout 90 \
  --output bench/results/exp5-pool-isolated.csv &

# 5. 等待完成
wait

# 6. 清理
pkill -f fake_backend.py
```

**关键指标**：
- default 池错误率
- default 池 p95/p99 是否受 isolated 池高压影响
- 两个池的后端分布（是否完全隔离）

---

### 实验6：综合剧本（待重跑）

**思路**：把降容、热点、故障、恢复放入一个端到端流程。

**时间线**：
```
0-30s：正常服务
30s：npu3 降容 10→1
60s：npu4 注入长 prompt 压力
90s：停止 npu5
120s：恢复 npu5
150s：npu3 恢复 10
180s：结束
```

**操作**：
```bash
# 综合事件注入（在运行 loadgen 的同时执行）
sleep 30 && curl -X POST :8181/admin/capacity -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}'
sleep 30 && for i in {1..5}; do curl -s :9022/v1/chat/completions -d '长prompt' & done
sleep 30 && docker stop yijq27-vllm-qwen15b-5
sleep 30 && docker start yijq27-vllm-qwen15b-5
sleep 30 && curl -X POST :8181/admin/capacity -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}'
```

**统计窗口拆分**：
```
pre_window:        0-30s
transition_down:  30-50s
stable_down:      50-80s
transition_up:    80-110s
stable_up:       110-180s
```
仅用 `stable_down` 判断降容收敛。

---

### 实验7：smoothStep 参数敏感性

**思路**：5 后端场景，降容 npu3 10→1，理论目标 2.44%。对比 smoothStep=0.1/0.25/0.5/1.0 的收敛效果。

**操作**：
```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos

for SS in 0.1 0.25 0.5 1.0; do
  echo "=== smoothStep=${SS} ==="

  # 启动 router
  docker exec yijq27-cann851 bash -lc 'pkill -f suan-router' 2>/dev/null; sleep 1
  docker exec -d yijq27-cann851 bash -lc "cd /workspace/Track1_fuiglwgfnq_repos && exec /workspace/bin/suan-router -config config/router-ss5-${SS}.json >>/workspace/logs/suan-router-ss5-${SS}.log 2>&1"
  sleep 3

  # 负载测试（90s）
  python3 bench/loadgen.py --url http://127.0.0.1:8180/v1/chat/completions \
    --header 'Content-Type:application/json' \
    --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
    --duration 90 --concurrency 32 --timeout 90 \
    --output bench/results/exp7-5b-ss${SS}.csv &
  LPID=$!

  # 第 30s 降容
  sleep 30
  curl -s -X POST http://127.0.0.1:8181/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":1}' > /dev/null

  # 第 60s 恢复
  sleep 30
  curl -s -X POST http://127.0.0.1:8181/admin/capacity \
    -H 'Content-Type: application/json' \
    -d '{"pool":"default","backend":"qwen15b-npu3","capacity":10}' > /dev/null

  wait $LPID
  echo "smoothStep=${SS} done"
done
```

**统计窗口**：
```
pre_window:        0-29s
stable_down:      35-60s（仅用此窗口判断降容后稳定占比）
```

**关键指标**：
- 降容后 stable_down 窗口的 npu3 占比（vs 理论值 2.44%）
- 收敛速度
- 抖动（jitter）= max(占比) - min(占比)
- 错误率

---

## 四、数据分析方法

### 4.1 汇总脚本
```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
python3 bench/generate_summary.py
```
输出：`analysis-output/all_summary.csv`

### 4.2 分析框架
```python
from bench.analysis_framework import *

# 加载数据
rows = load_csv('bench/results/exp3-capacity-drop.csv')

# 按秒聚合
ps = per_second_aggregation(rows)

# 提取窗口统计
pre = window_stats(ps, 0, 30, backend_id='qwen15b-npu3')
post = window_stats(ps, 35, 80, backend_id='qwen15b-npu3')

# 计算收敛时间
conv = calc_convergence_time(ps, 30, 'qwen15b-npu3', 2.44, tolerance_pct=1.0)

# 生成时间序列 CSV
generate_timeseries(ps, ['qwen15b-npu3', 'qwen15b-npu4', ...], 'exp3_timeseries.csv')
```

### 4.3 关键公式

**理论降容占比**（n 个后端，第 k 个从 10→1）：
```
target_share = 1 / (1 + 10×(n-1))
```
例：5 后端 → `1 / (1 + 40) = 2.44%`

**降容后占比误差**：
```
error = |actual_share - target_share|
```

**抖动**（jitter）：
```
jitter = max(share[stable_window]) - min(share[stable_window])
```

---

## 五、实验后清理

```bash
# 停止 router
docker exec yijq27-cann851 bash -lc 'pkill -f suan-router'

# 停止 fake 后端
pkill -f fake_backend.py

# 确保 vLLM 容器运行（不要停止长期服务）
docker start yijq27-vllm-qwen15b-3 yijq27-vllm-qwen15b-4 \
  yijq27-vllm-qwen15b-5 yijq27-vllm-qwen15b-6 yijq27-vllm-qwen15b-7
```

---

## 六、配置文件清单

| 配置文件 | 用途 |
|----------|------|
| `router.qwen15b-p2c.example.json` | exp1-C: p2c, 2后端(npu3,4) |
| `router.qwen15b-static-swrr.example.json` | exp1-B: swrr, 2后端(npu3,4) |
| `router-het-p2c.json` | exp2: p2c异构(fast=vLLM, slow=fake 300ms) |
| `router-het-swrr.json` | exp2: swrr异构(fast=vLLM, slow=fake 300ms) |
| `router.qwen15b-5backends-p2c.json` | exp3/4/6: p2c, 5后端(npu3-7) |
| `router.qwen15b-multi-pool.json` | exp5: 多池(default+isolated) |
| `router-ss5-{0.1,0.25,0.5,1.0}.json` | exp7: smoothStep 参数实验 |

---

## 七、输出结果路径

```
原始数据: bench/results/
分析输出: analysis-output/
实验报告: docs/experiment-results-final.md
完整报告: docs/final-report.md
Router日志: /workspace/logs/
```
