# exp1 均衡基线

目的：在 5 个健康的真实 Ascend NPU 后端上，对比单后端直连、静态 SWRR、`p2c_smooth_wrr` 和 `balanced_p2c`。

关键文件：

- `exp1-real-direct-npu3.csv`
- `exp1-real-swrr.csv`
- `exp1-real-p2c.csv`
- `exp1-real-balanced.csv`
- `exp1-*.state.json` 和 `exp1-*.metrics.txt`

正式结果：`swrr` 达到 247.41 QPS，`p2c_smooth_wrr` 达到 246.46 QPS，二者均 0 错误。该结果说明均衡场景下动态调度开销很低。
