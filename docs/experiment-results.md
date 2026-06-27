# Real Ascend NPU Experiment Results

最新正式实验目录：

```text
bench/results/real-npu-20260627021640/
```

该目录由 `scripts/run_real_npu_suite.sh` 生成。后续针对实时负载感知短板，单独重跑了 exp2 指标驱动热点压力实验：

```text
bench/results/real-npu-metrics-exp2-20260627203104/
```

正式结果全部来自真实 Ascend NPU 3-7。

## Environment

| 项目 | 值 |
|---|---|
| Host | `kunlun-02-act` |
| Router container | `yijq27-cann851` |
| Backend containers | `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7` |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` |
| vLLM image | `quay.io/ascend/vllm-ascend:v0.18.0rc1` |
| Router ports | `8180` / `8181` |

## Summary

| 实验 | 关键结果 |
|---|---|
| exp1 | `swrr` 247.41 QPS，`p2c_smooth_wrr` 246.46 QPS，均 0 错误 |
| exp2 | NPU3 direct 强压力下，SWRR baseline 给 NPU3 19.96%；`p2c_smooth_wrr` 读到 `remote_utilization=1.0` 后降到 0.00%；`balanced_p2c` 降到 3.94% |
| exp3 | NPU3 capacity 10->1 后 stable down 占比 2.37%，理论 2.44%，0 错误 |
| exp4 | stop/start NPU5 容器，全程 72,794 请求 3 错误，fail stable NPU5 占比 0.02% |
| exp5 | default 池 28,218 请求 0 错误；isolated 池真实 NPU 长请求 1,592 请求 0 错误 |
| exp6 | 综合剧本 50,003 请求 7 错误，作为演示型结果 |
| exp7 | smoothStep=0.25 stable down 占比 2.31%，误差 0.13pp |

## Formal Evidence Boundary

- 进入正式主结论：exp1、exp2 指标驱动重跑、exp3、exp4、exp5、exp7。
- 辅助演示：exp6 为综合演示。
- 不进入主结论：fake backend 微基准和旧异构开发夹具。

## Generated Files

```text
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
exp2-real-hotspot-*-metrics.csv
snapshots/*.state.json
snapshots/*.metrics.txt
npu-smi-before.txt
npu-smi-after.txt
```

重新生成：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-20260627021640 \
  --output-dir bench/results/real-npu-20260627021640/analysis

python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-metrics-exp2-20260627203104 \
  --output-dir bench/results/real-npu-metrics-exp2-20260627203104/analysis
```

完整分析见 [`final-report.md`](final-report.md)。
