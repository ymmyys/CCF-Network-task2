# 真实 NPU 结果数据

本目录记录项目文档引用的正式真实 Ascend NPU 实验数据。

## 正式目录结构

| 目录 | 实验 | 目的 |
|---|---|---|
| `formal/exp1-balanced-baseline/` | exp1 | 5 后端均衡基线和调度开销 |
| `formal/exp2-hotspot-load/` | exp2 | 指标驱动热点避让重跑 |
| `formal/exp3-dynamic-capacity/` | exp3 | capacity 10->1->10 平滑迁移 |
| `formal/exp4-failure-recovery/` | exp4 | NPU5 stop/start 故障恢复 |
| `formal/exp5-pool-isolation/` | exp5 | 多资源池 noisy-neighbor 隔离 |
| `formal/exp6-comprehensive/` | exp6 | 综合演示剧本 |
| `formal/exp7-smoothstep/` | exp7 | smoothStep 参数敏感性 |
| `formal/exp8-qwen7b-hotspot/` | exp8 | Qwen2.5-7B 热点避让泛化 |
| `formal/system/` | system | `npu-smi` 前后快照 |
| `formal/analysis/` | summary | 自动生成的综合汇总 |

旧的按运行批次目录已经从正式证据中移除。exp2 只保留指标修复后的正式热点压力重跑数据，不保留更早的未接入 metrics 的压力结果。

## 文件说明

- `analysis/real_npu_summary.csv` 和 `.md`：报告使用的自动汇总。
- `exp*-real-*.csv`：`bench/loadgen.py` 生成的原始 OpenAI-compatible 请求日志。
- `exp*-real-*.summary.csv`：按秒统计的延迟、QPS 和后端占比。
- `exp2-real-hotspot-*-metrics.csv`：正式热点实验中的 vLLM `/metrics` 与 router `/admin/state` 采样。
- `exp8-qwen7b-hotspot-*-metrics.csv`：Qwen2.5-7B 泛化热点实验中的 vLLM `/metrics` 与 router `/admin/state` 采样。
- `*.state.json` 和 `*.metrics.txt`：实验过程中采集的 router 状态和 Prometheus 快照。
- `npu-smi-before.txt` 和 `npu-smi-after.txt`：完整实验前后的设备状态快照。

## 重新生成汇总

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

后续临时实验结果目录默认仍被忽略。只有当某个新目录成为正式证据时，才应显式加入仓库。
