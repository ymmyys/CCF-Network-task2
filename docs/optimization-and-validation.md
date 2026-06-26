# Optimization and Validation Notes

本文档记录当前版本的调度优化、真实 NPU 验证结果和后续优化方向。正式结论只引用真实 Ascend NPU 3-7 数据。

## Implemented Optimizations

### P2C 同后端高负载重采样

当两次带放回采样命中同一个高负载后端时，router 会额外从其余候选中补抽一个后端，再按 `loadScore` 比较。这样保留权重语义，同时降低热点节点被重复确认的概率。

### failure cooloff

配置：

```json
"failure_cooloff_duration": "1s"
```

代理错误或 5xx 响应后，后端会短暂不可调度；成功响应或健康探测恢复会清除 cooloff。该机制降低健康检查窗口内继续打到坏节点的概率。

### 非法指标防护

Prometheus 中的 `NaN`、`+Inf`、`-Inf` 会被忽略。权重计算和候选过滤拒绝非有限值，防止异常指标污染调度状态。

### balanced P2C

配置：

```json
"scheduler": {
  "mode": "p2c_smooth_wrr",
  "balanced_p2c": true,
  "slow_backend_min_share": 0.10
}
```

真实 5 后端配置：

```text
config/router.qwen15b-5backends-balanced.json
```

balanced P2C 只对 healthy 且 schedulable 的慢后端保留受控流量；unhealthy、passive ejected、failure cooling off、drained、capacity=0、max inflight 已满的后端仍不会被调度。

## Real NPU Validation

最新结果：

```text
bench/results/real-npu-20260627021640/analysis/real_npu_summary.csv
```

| 能力 | 结果 |
|---|---|
| 均衡开销 | `swrr` 247.41 QPS；`p2c_smooth_wrr` 246.46 QPS；均 0 错误 |
| 动态降容 | NPU3 stable down 2.37%，理论 2.44%，29,748 请求 0 错误 |
| 故障恢复 | NPU5 fail stable 0.02%，recovery end 19.80%，72,794 请求 3 错误 |
| 资源池隔离 | default 池 28,218 请求 0 错误；isolated 池 1,592 长请求 0 错误 |
| smoothStep | 0.25 stable down 2.31%，误差 0.13pp |

## Exp2 Boundary

真实 exp2 对 NPU3 发 direct long-prompt 压力，并通过 router 测量 5 后端分布。强压力重跑后：

| 调度器 | NPU3 占比 | p95 | p99 |
|---|---:|---:|---:|
| swrr | 19.93% | 157.86ms | 170.54ms |
| p2c_smooth_wrr | 19.91% | 155.94ms | 173.51ms |
| balanced_p2c | 19.93% | 157.19ms | 171.16ms |

结论：该外部压力没有通过当前 vLLM Prometheus 指标形成明显 waiting/KV 高水位，因此 router 不应强行迁移流量。这个结果是边界说明，不作为优势证明。下一步若要强化外部热点感知，应接入更直接的 NPU 利用率 exporter 或 vLLM engine queue 信号。

## Development Fixtures

以下内容仅用于开发验证，不进入正式主结论：

```text
bench/fake_backend.py
scripts/run_router_microbench.sh
scripts/run_experiment2.sh
config/router.qwen15b-heterogeneous-*.json
```

fake backend 对确定性复现很有价值，例如构造 300ms 延迟、固定 queue depth、非法指标值等；但赛题提交材料中的性能结论必须来自真实 NPU。

## Remaining Work

| 项目 | 状态 | 说明 |
|---|---|---|
| NPU exporter 集成 | TODO | 用真实硬件利用率增强外部热点感知 |
| token-cost-aware inflight | TODO | 根据 prompt/max_tokens 估计请求成本 |
| 恢复期回退 | TODO | recovering 阶段若出现高延迟/错误，降低回流速度 |
| 多模型矩阵 | TODO | 用小模型和更大模型补充泛化证据 |
