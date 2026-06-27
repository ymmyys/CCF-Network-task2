# exp1 Balanced Baseline

Purpose: compare direct-to-one-backend, static SWRR, `p2c_smooth_wrr`, and `balanced_p2c` on five healthy real Ascend NPU backends.

Key files:

- `exp1-real-direct-npu3.csv`
- `exp1-real-swrr.csv`
- `exp1-real-p2c.csv`
- `exp1-real-balanced.csv`
- `exp1-*.state.json` and `exp1-*.metrics.txt`

Formal result: `swrr` reached 247.41 QPS and `p2c_smooth_wrr` reached 246.46 QPS, both with 0 errors. This supports low scheduling overhead in the balanced case.
