# Experiment Plan

本计划对应当前真实 NPU 实验脚本。详细操作见 [`runbook.md`](runbook.md)，结果见 [`experiment-results.md`](experiment-results.md)。

## Goal

验证 `suan-router` 在真实 Ascend NPU 推理集群中的动态调度能力：

- 正常均衡场景下，动态调度没有明显额外开销；
- capacity 10->1->10 时，新请求平滑迁移，已分配请求不中断；
- backend 故障时自动摘除，恢复后 slow-start；
- 多资源池并发时隔离有效；
- smoothStep 参数选择有真实数据支撑。

## Testbed

| 资源 | 配置 |
|---|---|
| Host | `kunlun-02-act` |
| Router container | `yijq27-cann851` |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` |
| Real backends | NPU 3/4/5/6/7 |
| Router ports | `8180` / `8181` |

正式数据目录：

```text
bench/results/real-npu-20260627021640/
```

## Experiments

| 实验 | 脚本 | 目的 | 验收口径 |
|---|---|---|---|
| exp1 | `scripts/run_experiment1.sh` | 均衡场景开销 | `p2c_smooth_wrr` 与 `swrr` QPS/p99 接近，0 错误 |
| exp2 | `scripts/run_experiment2_real.sh` | 外部真实压力边界 | 记录 NPU3 占比；若 vLLM 指标未形成热点，不宣称避让优势 |
| exp3 | `scripts/run_experiment3.sh` | capacity 平滑迁移 | stable down 占比接近 2.44%，0 错误 |
| exp4 | `scripts/run_experiment4.sh` | 真实故障恢复 | 只 stop/start `yijq27-vllm-qwen15b-5`，fail stable 占比接近 0 |
| exp5 | `scripts/run_experiment5_noisy.sh` | 资源池隔离 | default 池在 isolated 高压下 0 错误 |
| exp6 | `scripts/run_experiment6.sh` | 综合剧本 | 作为演示，不替代分窗口核心实验 |
| exp7 | `scripts/run_smoothstep_experiment.sh` | smoothStep 参数 | 比较 0.1/0.25/0.5/1.0 的收敛和平滑性 |

## Metrics

- requests / errors / error rate；
- QPS；
- p50 / p95 / p99；
- per-backend request share；
- `/admin/state` 中的 phase、capacity、desired/effective weight、inflight；
- `/metrics` 中的 router 状态；
- vLLM metrics 采样用于综合剧本辅助分析。

## Reproduction

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

生成汇总：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-20260627021640 \
  --output-dir bench/results/real-npu-20260627021640/analysis
```

## Current Outcome

- exp1：`p2c_smooth_wrr` 246.46 QPS，`swrr` 247.41 QPS，均 0 错误。
- exp3：NPU3 stable down 2.37%，理论 2.44%，29,748 请求 0 错误。
- exp4：NPU5 fail stable 0.02%，recovery end 19.80%，72,794 请求 3 错误。
- exp5：default 池 28,218 请求 0 错误，isolated 池 1,592 请求 0 错误。
- exp7：smoothStep=0.25 stable down 2.31%，误差 0.13pp。

exp2 当前结论是边界：真实 external direct pressure 没有在 vLLM 指标中形成明显热点，所以不能把它写成优势证明。
