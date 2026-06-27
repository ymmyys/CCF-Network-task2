# 真实 Ascend NPU 实验结果

最新正式实验数据已经记录到仓库，并按实验编号整理：

```text
bench/results/formal/exp1-balanced-baseline/
bench/results/formal/exp2-hotspot-load/
bench/results/formal/exp3-dynamic-capacity/
bench/results/formal/exp4-failure-recovery/
bench/results/formal/exp5-pool-isolation/
bench/results/formal/exp6-comprehensive/
bench/results/formal/exp7-smoothstep/
```

exp1、exp3、exp4、exp5、exp6、exp7 来自完整真实 NPU suite；exp2 来自指标修复后的热点压力重跑。

正式结果全部来自真实 Ascend NPU 3-7。

## 环境

| 项目 | 值 |
|---|---|
| 主机 | `kunlun-02-act` |
| Router 容器 | `yijq27-cann851` |
| 后端容器 | `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7` |
| 模型 | `Qwen/Qwen2.5-1.5B-Instruct` |
| vLLM 镜像 | `quay.io/ascend/vllm-ascend:v0.18.0rc1` |
| Router 端口 | `8180` / `8181` |

## 汇总

| 实验 | 关键结果 |
|---|---|
| exp1 | `swrr` 247.41 QPS，`p2c_smooth_wrr` 246.46 QPS，均 0 错误 |
| exp2 | NPU3 direct 强压力下，SWRR 基线给 NPU3 19.96%；`p2c_smooth_wrr` 读到 `remote_utilization=1.0` 后降到 0.00%；`balanced_p2c` 降到 3.94% |
| exp3 | NPU3 capacity 10->1 后稳定降容占比 2.37%，理论 2.44%，0 错误 |
| exp4 | stop/start NPU5 容器，全程 72,794 请求 3 错误，故障稳定期 NPU5 占比 0.02% |
| exp5 | default 池 28,218 请求 0 错误；isolated 池真实 NPU 长请求 1,592 请求 0 错误 |
| exp6 | 综合剧本 50,003 请求 7 错误，作为演示型结果 |
| exp7 | smoothStep=0.25 稳定降容占比 2.31%，误差 0.13pp |

## 正式证据边界

- 进入正式主结论：exp1、exp2 指标驱动重跑、exp3、exp4、exp5、exp7。
- 辅助演示：exp6 为综合演示。
- 不进入主结论：fake backend 微基准和旧异构开发夹具。

## 生成文件

这些文件已随仓库提交，评审可以直接查看或重新生成汇总。

```text
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
exp2-real-hotspot-*-metrics.csv
exp*/README.md
exp*/*.state.json
exp*/*.metrics.txt
npu-smi-before.txt
npu-smi-after.txt
```

重新生成：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

完整分析见 [`final-report.md`](final-report.md)。
