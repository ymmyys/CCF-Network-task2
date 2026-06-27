# exp5 资源池隔离

目的：验证 noisy-neighbor 压力下的资源池隔离能力。

关键文件：

- `exp5-real-default.csv`
- `exp5-real-isolated.csv`
- `exp5-*.state.json` 和 `exp5-*.metrics.txt`

正式结果：isolated 池在真实 NPU5/6/7 上运行长请求压力时，default 池完成 28,218 请求且 0 错误。该结果支撑并发负载下的资源池隔离。
