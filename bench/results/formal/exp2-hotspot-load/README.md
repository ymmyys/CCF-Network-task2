# exp2 热点负载

目的：在 `qwen15b-npu3` 承受外部压力时，验证实时负载感知调度是否能避让热点。

本目录使用修复 vLLM Prometheus 解析后的指标驱动重跑结果。静态 SWRR 基线故意不配置 `metrics_url`；`p2c_smooth_wrr` 和 `balanced_p2c` 使用 vLLM `/metrics`。

关键文件：

- `exp2-real-hotspot-swrr.csv`
- `exp2-real-hotspot-p2c.csv`
- `exp2-real-hotspot-balanced.csv`
- `exp2-real-hotspot-*-metrics.csv`
- `exp2-real-pressure-*.csv`
- `exp2-*.state.json` 和 `exp2-*.metrics.txt`

正式结果：SWRR 将 19.96% 的测量流量发送到 NPU3；`p2c_smooth_wrr` 观测到 `remote_utilization=1.0` 后，将 NPU3 测量流量降到 0.00%；`balanced_p2c` 保留 3.94% 探测流量。
