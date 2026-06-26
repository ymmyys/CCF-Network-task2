# Router Optimization and Validation Notes

本文档记录 2026-06-27 之后新增的调度优化、轻量验证结果，以及后续多模型实验设计。它用于补充 `final-report.md`，不替代真实昇腾 NPU 实验数据。

## 1. 新增优化

### 1.1 P2C 同后端高负载重采样

原实现已经修复为两次独立带放回采样，避免小规模候选池中 `exclude` 逻辑导致 P2C 退化。但带放回采样仍有一个边界场景：如果两次都采到同一个高权重、高负载后端，旧逻辑会直接选择它，留下尾延迟概率。

本轮新增逻辑：

- 如果两次采样命中同一后端；
- 且该后端 `p2cLoadScore >= 0.35`；
- 则额外从其余候选中补抽一个后端，再用 loadScore 比较。

这样保留了带放回采样的权重语义，也减少高权重热点节点在 P2C 中“自我确认”的概率。

### 1.2 上游错误短暂避让

新增配置：

```json
"failure_cooloff_duration": "1s"
```

默认值为 `1s`。当某个后端出现代理错误或 5xx 响应时，即使尚未达到被动熔断阈值，也会进入短暂 cooloff，在该窗口内不可调度。成功响应或健康探测恢复会清除 cooloff。

这个机制用于降低故障检测窗口内继续打到坏节点的概率，目标是进一步降低 exp4 中的错误请求数。

### 1.3 非法指标值防护

Prometheus 指标中如果出现 `NaN`、`+Inf` 或 `-Inf`，现在会在解析阶段忽略；权重计算阶段也会对非有限值兜底为 0。`schedulingState` 会拒绝非有限 `effective_weight`，避免非法指标污染后端权重并进入调度候选集。

### 1.4 balanced P2C

新增可选配置：

```json
"scheduler": {
  "mode": "p2c_smooth_wrr",
  "balanced_p2c": true,
  "slow_backend_min_share": 0.10
}
```

默认不启用，保持原 `p2c_smooth_wrr` 行为兼容。启用后，healthy slow backend 不会被 aggressive P2C 长期清零；当该 slow backend 已经积累 WRR 债务时，router 会按 `slow_backend_min_share` 控制少量流量回灌。以下后端仍然没有 floor，必须硬摘除或不可调度：

- unhealthy；
- passive ejected；
- failure cooling off；
- drained；
- capacity = 0；
- max inflight 已满。

配套配置文件：

```text
config/router.qwen15b-heterogeneous-balanced.json
```

当前状态：代码和单测已完成，真实 `exp2-balanced` 尚未重跑，不能把它写成已实测优于 aggressive P2C。

## 2. 轻量微基准

脚本：

```bash
./scripts/run_router_microbench.sh
```

该脚本只启动 fake backend 和临时 router，不占用 NPU，不停止未知进程。清理时只 kill 当前脚本捕获的 PID。如果端口已被占用，脚本会直接退出。

场景：

- `hot` 后端：capacity=100，但延迟 300ms，utilization=95%，queue_depth=16；
- `cool` 后端：capacity=1，延迟 50ms，utilization=10%，queue_depth=0；
- 对比优化前后 router 二进制。

结果：

| 版本 | 请求数 | QPS | p50 | p95 | p99 | 后端分布 |
|------|-------:|----:|----:|----:|----:|----------|
| before | 667 | 55.58 | 301.71ms | 303.43ms | 306.71ms | hot=638, cool=29 |
| after | 3,630 | 302.50 | 51.85ms | 53.21ms | 54.66ms | cool=3,630 |

结论：在确定性热点后端场景中，本轮优化显著降低了 hot 后端命中率和尾延迟。这是调度逻辑微基准，不作为真实 NPU 性能结论；真实提交材料仍以 exp1、exp3、exp4-fix、exp5、exp7-5b 为核心证据。

## 3. 真实 NPU 回归

### 3.1 exp3-current：5 后端动态降容

环境：

- 后端：真实 vLLM-Ascend，NPU 3/4/5/6/7；
- Router：当前分支构建的 `/tmp/suan-router-current`；
- 配置：`config/router.qwen15b-5backends-p2c.json`；
- 负载：80s，并发 16；
- 事件：20s 时 `qwen15b-npu3 capacity 10→1`，50s 时恢复 `1→10`。

结果：

| 窗口 | 请求 | 错误 | QPS | p50 | p95 | p99 | npu3 占比 |
|------|-----:|-----:|----:|----:|----:|----:|----------:|
| pre_0_20 | 2,584 | 0 | 129.20 | 123.65ms | 140.90ms | 149.99ms | 20.01% |
| transition_down_20_30 | 1,287 | 0 | 128.70 | 123.33ms | 141.80ms | 149.48ms | 5.36% |
| stable_down_30_50 | 2,595 | 0 | 129.75 | 122.92ms | 138.96ms | 144.03ms | 2.20% |
| transition_up_50_65 | 1,944 | 0 | 129.60 | 123.03ms | 139.53ms | 145.54ms | 7.72% |
| stable_up_65_80 | 1,929 | 0 | 128.60 | 123.57ms | 142.55ms | 150.31ms | 19.28% |
| all | 10,339 | 0 | 129.24 | 123.29ms | 140.51ms | 147.79ms | 11.27% |

结论：

- 当前优化没有破坏真实 NPU 动态降容能力；
- 降容稳定期 npu3 占比 2.20%，接近理论目标 2.44%；
- 恢复稳定期 npu3 占比回到 19.28%，接近 5 后端均衡 20%；
- 全程 10,339 请求 0 错误。

原始结果保存在远端临时目录：

```text
/tmp/suan-router-real-exp3-20260626175313/
```

## 4. 实验充分性判断

当前实验已经覆盖赛题核心能力：

- 正常均衡下的低调度开销；
- 动态 capacity 下降时的平滑迁移；
- 故障摘除与恢复；
- 多资源池隔离；
- smoothStep 参数敏感性；
- 昇腾 910B + vLLM-Ascend 真实环境端到端运行。

不足之处：

- exp2 证明了慢节点避让能力，但策略偏激进，QPS/p50 存在代价；
- balanced P2C 已实现为可选策略，但还没有完成真实 exp2-balanced 数据；
- exp6 综合剧本尚未按 transition/stable 窗口重算，不作为核心证据；
- 当前主实验模型集中在 Qwen2.5-1.5B-Instruct，跨模型泛化证据还不强。

## 5. 是否需要更多模型

建议增加，但不建议把“模型数量”作为主线。赛题关注的是算力资源动态调度，模型只是负载形态来源。更合理的设计是用 2-3 个模型覆盖不同推理压力：

| 模型层级 | 目的 | 是否必须 |
|----------|------|----------|
| 小模型（如 Qwen2.5-0.5B-Instruct） | 快速 smoke test，验证迁移机器、容器、健康检查、router 逻辑 | 建议保留 |
| 主模型（当前 Qwen2.5-1.5B-Instruct） | 作为正式实验主线，完成 exp1/3/4/5/7 | 必须 |
| 更大模型或 TP 模型 | 增强决赛说服力，验证长 TTFT/高 KV cache 压力下调度仍有效 | 可选，取决于 NPU 3-7 空闲情况 |

决赛前建议补一个“多模型轻量矩阵”，不必重跑所有实验：

| 模型 | 实验 | 重点指标 |
|------|------|----------|
| 小模型 | exp1 + exp3 | 调度开销、capacity 迁移是否仍稳定 |
| 主模型 | exp1 + exp3 + exp4 + exp5 + exp7 | 作为完整证据链 |
| 大模型/TP 模型 | exp1 + exp2 或 exp3 | 验证高延迟、高 KV cache 场景下的尾延迟和迁移能力 |

## 6. 下一步真实 NPU 验证优先级

在不影响他人任务的前提下，只使用 NPU 3-7：

1. 先跑 `npu-smi info`，确认 NPU 3-7 空闲或只包含本项目容器；
2. 重跑 exp4-fix，观察错误数是否从 7 进一步下降；
3. 重跑 exp2，确认慢节点避让仍成立，并记录 QPS/p50 是否改善；
4. 选择一个小模型做 exp1/exp3 快速复验；
5. 如果资源允许，再用更大模型做 exp1/exp3 轻量复验。

不要使用无条件 `pkill` 或 `docker rm -f $(...)`。所有清理命令必须限定到本项目容器名、当前脚本 PID 或明确端口。

## 7. 未实现项

| 项目 | 状态 | 说明 |
|------|------|------|
| token-cost-aware inflight | NOT_IMPLEMENTED | 已有设计方向，但尚未在请求路径中解析 prompt/max_tokens 并维护 weighted inflight。 |
| recovering slow-start 回退增强 | NOT_IMPLEMENTED | 当前已有 slow-start，尚未实现基于恢复期错误率/高延迟的回退和 stableFor 判断。 |
| TTFT/TPOT 正式采集 | NOT_RUN | `bench/collect_metrics.py` 已存在，但尚未作为 exp2/exp8 的同步采集结果进入核心报告。 |
| exp6 窗口重算 | NOT_RUN | 需要拆分 pre/transition/stable 窗口后再使用。 |
