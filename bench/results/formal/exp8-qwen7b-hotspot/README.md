# exp8：Qwen2.5-7B 热点避让泛化实验

## 目的

验证 exp2 的真实负载感知热点避让能力在更大模型 `Qwen/Qwen2.5-7B-Instruct` 上仍然成立。实验对 NPU3 直接发送长 prompt 背景压力，同时通过 router 发送测量流量，对比静态 SWRR、`p2c_smooth_wrr` 和 `balanced_p2c`。

## 环境

| 项目 | 值 |
|---|---|
| 主机 | `kunlun-02-act` |
| 模型 | `Qwen/Qwen2.5-7B-Instruct` |
| 后端 | NPU 3/4/5/6/7 |
| 临时容器 | `yijq27-vllm-qwen7b-3` 到 `yijq27-vllm-qwen7b-7` |
| 端口 | `9121/9122/9126/9127/9128` |
| 脚本 | `scripts/run_experiment8_qwen7b_real.sh` |

实验完成后已删除上述 `qwen7b` 容器，避免继续占用 NPU。

## 结果

| 调度器 | 请求 | 错误 | QPS | p50 | p95 | p99 | NPU3 占比 | router max remote_utilization |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| swrr | 8,532 | 0 | 77.51 | 102.46ms | 136.74ms | 279.10ms | 19.81% | 0.0 |
| p2c_smooth_wrr | 11,100 | 0 | 92.51 | 130.15ms | 187.76ms | 222.68ms | 0.00% | 1.0 |
| balanced_p2c | 11,415 | 0 | 95.13 | 125.94ms | 182.55ms | 214.18ms | 3.64% | 1.0 |

结论：7B 模型下，静态 SWRR 仍给热点 NPU3 分配约 20% 流量；动态调度可以根据真实 vLLM 指标将 NPU3 流量降到 0% 或受控探测份额。三组均 0 错误。动态组在 QPS 和 p99 上优于基线，p95 未优于基线，因此该实验作为跨模型泛化补充证据。

## 文件

```text
exp8-qwen7b-hotspot-swrr.csv
exp8-qwen7b-hotspot-p2c.csv
exp8-qwen7b-hotspot-balanced.csv
exp8-qwen7b-hotspot-*-metrics.csv
exp8-qwen7b-pressure-*.csv
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
snapshots/*.state.json
snapshots/*.metrics.txt
```
