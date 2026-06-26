# Experiment 3 Timeline

实验：真实 Ascend NPU 3-7，`qwen15b-npu3` capacity 10->1->10。

结果文件：

```text
bench/results/real-npu-20260627021640/exp3-real-capacity-p2c.csv
```

## Timeline

```text
0-30s   正常运行，5 后端 capacity=10
30s     qwen15b-npu3 capacity 10 -> 1
30-40s  transition down
40-80s  stable down
80s     qwen15b-npu3 capacity 1 -> 10
80-100s transition up
100-120s stable up
```

## Window Results

| 窗口 | 请求 | 错误 | QPS | p50 | p95 | p99 | NPU3 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pre 0-30s | 7,374 | 0 | 245.80 | 129.68ms | 150.01ms | 158.49ms | 19.96% |
| transition down 30-40s | 2,485 | 0 | 248.50 | 128.02ms | 147.90ms | 155.19ms | 6.08% |
| stable down 40-80s | 9,956 | 0 | 248.90 | 127.25ms | 147.52ms | 154.63ms | 2.37% |
| transition up 80-100s | 4,973 | 0 | 248.65 | 127.97ms | 145.46ms | 154.23ms | 10.22% |
| stable up 100-120s | 4,956 | 0 | 247.80 | 128.41ms | 147.67ms | 153.75ms | 19.83% |

## Interpretation

理论 stable down 占比：

```text
1 / (1 + 10 + 10 + 10 + 10) = 2.44%
```

实测 stable down 为 2.37%，误差 0.07pp。全程 29,748 请求 0 错误，说明 capacity 下降不会中断已分配请求，且新请求能平滑迁移到其他后端。
