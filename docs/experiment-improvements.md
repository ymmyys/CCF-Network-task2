# Experiment Improvements

本文档记录相对早期实验设计的改进和当前状态。

## 已完成

- 统一真实 NPU 实验入口：`scripts/run_real_npu_suite.sh`。
- 增加安全运行库：`scripts/lib_real_npu.sh`，只清理 PID 文件记录的 router。
- 将资源池隔离从 fake isolated 后端升级为真实 NPU5/6/7。
- 将故障实验限定为只 stop/start `yijq27-vllm-qwen15b-5`。
- 增加 `bench/generate_summary.py`，按窗口输出真实 NPU 汇总。
- 增强 vLLM Prometheus 解析：`num_requests_running`、`num_requests_waiting`、`gpu_cache_usage_perc` 进入 router load score。
- exp2 增加并行 metrics 采集，输出 `exp2-real-hotspot-*-metrics.csv`，可追踪 vLLM 指标与 router `/admin/state`。
- 增加 `config/router.qwen15b-5backends-balanced.json` 和 `config/router.qwen15b-multi-pool-real.json`。

## 当前真实结果

| 能力 | 结果 |
|---|---|
| 均衡开销 | `swrr` 247.41 QPS，`p2c_smooth_wrr` 246.46 QPS |
| 实时负载避热点 | SWRR baseline NPU3 19.96%；`p2c_smooth_wrr` NPU3 0.00%；`balanced_p2c` NPU3 3.94% |
| 动态降容 | stable down 2.37%，理论 2.44%，0 错误 |
| 故障恢复 | fail stable NPU5 0.02%，recovery end 19.80% |
| 资源池隔离 | default 池 28,218 请求 0 错误 |
| smoothStep | 0.25 stable down 2.31%，误差 0.13pp |

## 修正的表述

旧表述中把 fake backend 异构实验作为慢节点避让证据。当前正式文档已修正：

- fake backend 只作为开发夹具；
- exp2 已改为真实 vLLM 指标驱动热点避让实验；
- 主优势结论来自 exp1、exp2、exp3、exp4、exp5、exp7。

## 后续改进

- 接入真实 NPU utilization exporter，补充设备级压力信号。
- 支持 token-cost-aware inflight。
- 在 recovering 阶段加入基于错误率/高延迟的回退。
- 增加多模型矩阵。
