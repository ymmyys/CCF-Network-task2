# 昇腾 NPU 推理集群动态负载感知调度系统报告

## 1. 项目目标

本项目面向赛题 2「大模型推理算力资源动态负载感知调度」。目标是在 Ascend NPU 推理集群中实现一个可落地的 OpenAI-compatible router，使请求调度能感知：

- backend 健康状态；
- 管理面 capacity；
- 本地 inflight；
- vLLM Prometheus 指标中的 waiting、KV cache、延迟等信号；
- 多资源池隔离策略。

核心要求是当某节点 capacity 从 10 降到 1 时，已分配请求不中断，新请求按动态权重平滑迁移；当节点故障时快速摘除；多资源池并发时互不影响。

## 2. 系统架构

```text
client
  |
  v
suan-router
  |-- data plane  :8180
  |-- admin plane :8181
  |-- metrics     /metrics
  |
  +--> qwen15b-npu3  NPU3  port 9021
  +--> qwen15b-npu4  NPU4  port 9022
  +--> qwen15b-npu5  NPU5  port 9026
  +--> qwen15b-npu6  NPU6  port 9027
  +--> qwen15b-npu7  NPU7  port 9028
```

实现模块：

| 模块 | 作用 |
|---|---|
| `internal/router/router.go` | 反向代理、资源池选择、管理 API、metrics |
| `internal/router/scheduler.go` | `swrr`、`p2c_smooth_wrr`、`balanced_p2c` |
| `internal/router/backend.go` | 健康检查、状态机、指标解析、权重计算 |
| `bench/loadgen.py` | OpenAI-compatible 负载发生器 |
| `bench/generate_summary.py` | 真实 NPU 实验窗口汇总 |
| `scripts/lib_real_npu.sh` | 安全启动/停止 router、采集状态快照 |

## 3. 调度算法

### 3.1 动态目标权重

```text
desired_weight = capacity * headroom
headroom = 1 - weighted_load_score
```

`weighted_load_score` 综合：

- NPU/vLLM utilization；
- vLLM waiting/queue；
- router 本地 inflight；
- KV cache usage；
- 请求延迟 EWMA。

### 3.2 平滑有效权重

```text
effective_weight += (desired_weight - effective_weight) * smooth_step
```

`capacity` 或健康状态变化时，`desired_weight` 立即变化，`effective_weight` 分步追随，因此新请求逐渐迁移，已经转发给后端的请求不会被强制中断。

### 3.3 P2C + smooth WRR

`p2c_smooth_wrr` 会按有效权重采样两个候选，然后选择 load score 更低的后端。相比纯 SWRR，它能利用实时负载信号；相比硬切换，它保留权重平滑和状态机约束。

### 3.4 故障处理

backend 状态：

```text
active -> draining -> drained -> recovering -> active
```

代理错误或 5xx 会触发短暂 `failure_cooloff_duration`，连续失败会进入被动熔断。恢复时进入 `recovering`，通过 slow-start 逐渐回流。

## 4. 正式实验环境

| 项目 | 值 |
|---|---|
| 主机 | `kunlun-02-act` |
| 硬件 | Ascend 910B，正式实验使用 NPU 3-7 |
| Router 容器 | `yijq27-cann851` |
| vLLM 镜像 | `quay.io/ascend/vllm-ascend:v0.18.0rc1` |
| 模型 | `Qwen/Qwen2.5-1.5B-Instruct` |
| 结果目录 | `bench/results/real-npu-20260627021640/` |
| 汇总文件 | `analysis/real_npu_summary.csv` |

正式主结论只引用真实 NPU 数据。fake backend 只作为开发夹具，不进入本报告主证据链。

## 5. 实验结果

### exp1：均衡场景调度开销

| 组别 | 请求 | 错误 | QPS | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|
| direct npu3 | 7,991 | 0 | 133.22 | 244.85ms | 284.50ms | 303.80ms |
| router + swrr | 14,842 | 0 | 247.41 | 128.48ms | 148.08ms | 156.44ms |
| router + p2c_smooth_wrr | 14,788 | 0 | 246.46 | 129.57ms | 148.41ms | 156.53ms |
| router + balanced_p2c | 14,732 | 0 | 245.48 | 129.74ms | 149.72ms | 158.00ms |

结论：在 5 个真实后端均衡健康时，`p2c_smooth_wrr` 相比 `swrr` QPS 下降约 0.38%，p99 基本持平，说明动态调度开销很低。direct 是单后端参考，不与 5 后端 router 做横向吞吐比较。

### exp2：真实外部热点压力边界

设置：对 NPU3 直接发送长 prompt 背景压力，同时经 router 发送测量流量。

| 调度器 | 请求 | 错误 | QPS | p95 | p99 | NPU3 占比 |
|---|---:|---:|---:|---:|---:|---:|
| swrr | 21,713 | 0 | 241.16 | 157.86ms | 170.54ms | 19.93% |
| p2c_smooth_wrr | 21,669 | 0 | 240.76 | 155.94ms | 173.51ms | 19.91% |
| balanced_p2c | 21,607 | 0 | 240.01 | 157.19ms | 171.16ms | 19.93% |

结论边界：该真实外部压力没有让 vLLM 指标形成明显 waiting/KV 高水位，因此三种调度器都保持约 20% 分布。这个结果不能证明“外部直连压力自动避让”，但证明在该压力下 router 没有误判或引入错误。后续若要强化热点感知，需要接入更直接的 NPU exporter 或 vLLM engine queue 信号。

### exp3：动态 capacity 10->1->10

| 窗口 | 请求 | 错误 | QPS | p50 | p95 | p99 | NPU3 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pre 0-30s | 7,374 | 0 | 245.80 | 129.68ms | 150.01ms | 158.49ms | 19.96% |
| transition down 30-40s | 2,485 | 0 | 248.50 | 128.02ms | 147.90ms | 155.19ms | 6.08% |
| stable down 40-80s | 9,956 | 0 | 248.90 | 127.25ms | 147.52ms | 154.63ms | 2.37% |
| transition up 80-100s | 4,973 | 0 | 248.65 | 127.97ms | 145.46ms | 154.23ms | 10.22% |
| stable up 100-120s | 4,956 | 0 | 247.80 | 128.41ms | 147.67ms | 153.75ms | 19.83% |

理论降容占比为：

```text
1 / (1 + 10 + 10 + 10 + 10) = 2.44%
```

结论：stable down 中 NPU3 实际占比 2.37%，误差 0.07pp；全程 29,748 请求 0 错误；恢复后回到 19.83%。这直接支撑赛题要求的动态 capacity 平滑迁移。

### exp4：真实故障摘除与恢复

设置：第 30 秒停止 `yijq27-vllm-qwen15b-5`，第 90 秒启动，观察 300 秒。

| 窗口 | 请求 | 错误 | QPS | NPU5 占比 | 说明 |
|---|---:|---:|---:|---:|---|
| pre fail 0-30s | 7,392 | 1 | 246.40 | 20.06% | 正常均衡 |
| fail detect 30-35s | 1,125 | 0 | 225.00 | 0.00% | 故障检测窗口 |
| fail stable 35-90s | 13,213 | 2 | 240.24 | 0.02% | 已摘除 |
| recovery wait 90-240s | 36,219 | 0 | 241.46 | 0.65% | vLLM 重启/编译/探活 |
| recovery end 240-300s | 14,840 | 0 | 247.33 | 19.80% | 恢复均衡 |
| all | 72,794 | 3 | 242.64 | 6.40% | 全过程 |

结论：真实容器故障后，NPU5 在故障稳定期占比 0.02%，恢复末段回到 19.80%。全程错误率 0.0041%。该实验只操作指定项目容器，没有停止其他任务。

### exp5：真实资源池隔离

| 资源池 | 后端 | 请求 | 错误 | QPS | p50 | p95 | p99 |
|---|---|---:|---:|---:|---:|---:|---:|
| default | NPU3/4 | 28,218 | 0 | 235.14 | 134.02ms | 162.67ms | 192.95ms |
| isolated | NPU5/6/7 | 1,592 | 0 | 13.41 | 7,386.15ms | 9,365.28ms | 11,692.68ms |

结论：isolated 池承受长 prompt 高压时，default 池仍 0 错误，说明请求头资源池隔离有效。两个池都使用真实 NPU，不再使用 fake backend。

### exp6：综合剧本

综合剧本包含 capacity 降低、NPU4 背景压力、NPU5 stop/start、capacity 恢复。全程 50,003 请求，7 错误，QPS 238.10，p99 159.28ms。该实验用于演示多事件连续发生时系统仍可运行；核心定量结论以 exp3/exp4/exp5 的分窗口实验为准。

### exp7：smoothStep 参数敏感性

| smoothStep | pre 占比 | stable down 占比 | 理论值 | 误差 | stable up 占比 | 错误 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.10 | 20.01% | 4.70% | 2.44% | 2.26pp | 16.02% | 0 |
| 0.25 | 19.96% | 2.31% | 2.44% | 0.13pp | 19.18% | 0 |
| 0.50 | 19.97% | 2.31% | 2.44% | 0.13pp | 19.84% | 0 |
| 1.00 | 19.89% | 2.49% | 2.44% | 0.05pp | 19.93% | 0 |

结论：`smooth_step=0.25` 在本项目中是较稳妥默认值，stable down 误差仅 0.13pp，同时比 0.5/1.0 更平滑。`1.0` 收敛最快，但更接近硬切换。

## 6. 可支撑结论

1. 动态调度开销低：均衡场景中 `p2c_smooth_wrr` 与 `swrr` QPS/p99 基本持平。
2. capacity 动态变化可平滑迁移：10->1 后稳定占比 2.37%，接近理论 2.44%，0 错误。
3. 故障恢复可落地：真实停止 NPU5 容器后稳定期占比 0.02%，恢复末段回到 19.80%。
4. 多资源池隔离有效：default 池在 isolated 真实长请求高压下 28,218 请求 0 错误。
5. smoothStep 参数有实测依据：0.25 是当前 5 后端拓扑下的默认折中。

## 7. 不能夸大的内容

- exp2 没有证明外部直连压力自动避让；它证明的是当前 vLLM 指标下该压力未被 router 观测为热点。
- fake backend 微基准不进入正式主结论。
- exp6 是演示型综合剧本，不替代 exp3/exp4/exp5 的分窗口结果。
- 当前模型集中在 Qwen2.5-1.5B-Instruct，跨模型泛化仍需补充。

## 8. 代码与脚本更新

- 新增 `scripts/lib_real_npu.sh`，用 PID 文件安全管理实验 router。
- 新增 `scripts/run_real_npu_suite.sh`，完整重跑真实 NPU 实验。
- 新增 `config/router.qwen15b-5backends-balanced.json`。
- 新增 `config/router.qwen15b-multi-pool-real.json`。
- `bench/generate_summary.py` 改为真实实验窗口汇总，排除 fake backend 文件。
- `bench/collect_metrics.py` 修正 `/metrics` URL 到 backend URL 的映射。

## 9. 复现命令

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

详见 [`docs/runbook.md`](runbook.md)。
