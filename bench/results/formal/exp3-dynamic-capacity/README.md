# exp3 动态 Capacity

目的：验证 `qwen15b-npu3` capacity 从 10 降到 1、再恢复到 10 时，新请求是否能平滑迁移。

关键文件：

- `exp3-real-capacity-p2c.csv`
- `exp3-real-capacity-p2c.summary.csv`
- `exp3-*.state.json` 和 `exp3-*.metrics.txt`

正式结果：稳定降容窗口内 NPU3 占比为 2.37%，理论值为 2.44%，全程 29,748 请求 0 错误。该结果支撑“不中断已分配请求的平滑过渡”要求。
