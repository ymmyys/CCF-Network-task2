# 实验计划

本计划对应当前真实 NPU 实验脚本。详细操作见 [`runbook.md`](runbook.md)，结果见 [`experiment-results.md`](experiment-results.md)。

## 目标

验证 `suan-router` 在真实 Ascend NPU 推理集群中的动态调度能力：

- 正常均衡场景下，动态调度没有明显额外开销；
- 对单个真实后端形成外部压力时，调度器能根据 vLLM `/metrics` 降低热点节点被选中概率；
- capacity 10->1->10 时，新请求平滑迁移，已分配请求不中断；
- 后端故障时自动摘除，恢复后 slow-start；
- 多资源池并发时隔离有效；
- smoothStep 参数选择有真实数据支撑。

## 测试环境

| 资源 | 配置 |
|---|---|
| 主机 | `kunlun-02-act` |
| Router 容器 | `yijq27-cann851` |
| 模型 | `Qwen/Qwen2.5-1.5B-Instruct` |
| 真实后端 | NPU 3/4/5/6/7 |
| Router 端口 | `8180` / `8181` |

正式数据目录：

```text
bench/results/formal/
```

## 实验列表

| 实验 | 脚本 | 目的 | 验收口径 |
|---|---|---|---|
| exp1 | `scripts/run_experiment1.sh` | 均衡场景开销 | `p2c_smooth_wrr` 与 `swrr` QPS/p99 接近，0 错误 |
| exp2 | `scripts/run_experiment2_real.sh` | 外部真实压力避热点 | SWRR 基线维持约 20%；P2C 组根据 `remote_utilization` 显著降低 NPU3 占比 |
| exp3 | `scripts/run_experiment3.sh` | capacity 平滑迁移 | 稳定降容占比接近 2.44%，0 错误 |
| exp4 | `scripts/run_experiment4.sh` | 真实故障恢复 | 只 stop/start `yijq27-vllm-qwen15b-5`，故障稳定期占比接近 0 |
| exp5 | `scripts/run_experiment5_noisy.sh` | 资源池隔离 | default 池在 isolated 高压下 0 错误 |
| exp6 | `scripts/run_experiment6.sh` | 综合剧本 | 作为演示，不替代分窗口核心实验 |
| exp7 | `scripts/run_smoothstep_experiment.sh` | smoothStep 参数 | 比较 0.1/0.25/0.5/1.0 的收敛和平滑性 |

## 指标

- 请求数 / 错误数 / 错误率；
- QPS；
- p50 / p95 / p99；
- 各后端请求占比；
- `/admin/state` 中的 phase、capacity、desired/effective weight、inflight；
- `/metrics` 中的 router 状态；
- vLLM `num_requests_running`、`num_requests_waiting`、GPU/KV cache usage；

## 复现命令

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

生成汇总：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

## 当前结果

- exp1：`p2c_smooth_wrr` 246.46 QPS，`swrr` 247.41 QPS，均 0 错误。
- exp2：NPU3 direct 压力下，SWRR 基线 NPU3 占比 19.96%；`p2c_smooth_wrr` 占比 0.00%；`balanced_p2c` 占比 3.94%。
- exp3：NPU3 稳定降容占比 2.37%，理论 2.44%，29,748 请求 0 错误。
- exp4：NPU5 故障稳定期占比 0.02%，恢复末段占比 19.80%，72,794 请求 3 错误。
- exp5：default 池 28,218 请求 0 错误，isolated 池 1,592 请求 0 错误。
- exp7：smoothStep=0.25 稳定降容占比 2.31%，误差 0.13pp。
