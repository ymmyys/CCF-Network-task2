# exp2 Hotspot Load

Purpose: validate real-time load-aware scheduling under external pressure on `qwen15b-npu3`.

This directory uses the metrics-driven rerun after vLLM Prometheus parsing was fixed. The static SWRR baseline intentionally does not use `metrics_url`; `p2c_smooth_wrr` and `balanced_p2c` use vLLM `/metrics`.

Key files:

- `exp2-real-hotspot-swrr.csv`
- `exp2-real-hotspot-p2c.csv`
- `exp2-real-hotspot-balanced.csv`
- `exp2-real-hotspot-*-metrics.csv`
- `exp2-real-pressure-*.csv`
- `exp2-*.state.json` and `exp2-*.metrics.txt`

Formal result: SWRR sent 19.96% of measured traffic to NPU3, while `p2c_smooth_wrr` reduced NPU3 measured traffic to 0.00% after observing `remote_utilization=1.0`; `balanced_p2c` kept a 3.94% probe share.
