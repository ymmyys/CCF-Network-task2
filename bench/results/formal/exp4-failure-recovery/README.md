# exp4 故障恢复

目的：只 stop/start `yijq27-vllm-qwen15b-5`，验证真实后端故障摘除和恢复能力。

关键文件：

- `exp4-real-failure-p2c.csv`
- `exp4-real-failure-p2c.summary.csv`
- `exp4-*.state.json` 和 `exp4-*.metrics.txt`

正式结果：故障稳定窗口内 NPU5 占比降到 0.02%；恢复末段回到 19.80%。全程 72,794 请求，3 错误。
