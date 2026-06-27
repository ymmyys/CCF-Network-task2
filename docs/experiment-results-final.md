# Final Experiment Results

本文件是提交材料中的实验结果索引。详细报告见 [`final-report.md`](final-report.md)，操作复现见 [`runbook.md`](runbook.md)。

## Result Directory

```text
bench/results/real-npu-20260627021640/
bench/results/real-npu-metrics-exp2-20260627203104/
```

正式实验只引用真实 Ascend NPU 3-7 数据。旧 fake backend 结果已经从主文档移除。

## Key Numbers

| Capability | Evidence |
|---|---|
| 低调度开销 | `swrr` 247.41 QPS vs `p2c_smooth_wrr` 246.46 QPS，均 0 错误 |
| 实时负载避热点 | NPU3 direct 压力下，SWRR baseline NPU3 share 19.96%；`p2c_smooth_wrr` share 0.00%；`balanced_p2c` share 3.94% |
| 动态降容 | capacity 10->1 后 NPU3 stable share 2.37%，理论 2.44% |
| 平滑恢复 | capacity 1->10 后 NPU3 stable share 19.83% |
| 故障摘除 | NPU5 stop 后 fail stable share 0.02% |
| 故障恢复 | recovery end NPU5 share 19.80%，全程错误率 0.0041% |
| 资源池隔离 | default 池 28,218 请求 0 错误，isolated 池真实 NPU 高压 0 错误 |
| 参数选择 | smoothStep=0.25 stable down share 2.31%，误差 0.13pp |

## Caveats

- exp2 证明的是 vLLM `/metrics` 可观测 engine-level 压力下的动态避让；硬件级 NPU exporter 仍可作为增强。
- exp6 是演示型综合剧本，核心量化结论以 exp3/exp4/exp5/exp7 为准。
- fake backend 只保留为开发夹具。
