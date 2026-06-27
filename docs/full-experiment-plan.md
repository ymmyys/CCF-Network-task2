# Full Real-NPU Experiment Plan

本文件保留完整实验设计，但以当前真实 Ascend NPU 3-7 脚本为准。旧的 fake backend 设计只作为开发夹具，不进入正式主结论。

## 1. 赛题映射

| 赛题要求 | 实验覆盖 |
|---|---|
| 动态负载感知调度 | exp1、exp2、exp3、exp7 |
| capacity 大幅下降平滑过渡 | exp3、exp7 |
| 高可用与健康状态 | exp4、exp6 |
| 多资源池隔离 | exp5 |
| 可落地系统实现 | 全部实验运行在 vLLM-Ascend + Ascend 910B |

## 2. 实验拓扑

```text
router :8180/:8181
  |
  +-- qwen15b-npu3 -> 9021
  +-- qwen15b-npu4 -> 9022
  +-- qwen15b-npu5 -> 9026
  +-- qwen15b-npu6 -> 9027
  +-- qwen15b-npu7 -> 9028
```

模型：`Qwen/Qwen2.5-1.5B-Instruct`。

## 3. 实验矩阵

| ID | 名称 | 时长 | 并发 | 事件 |
|---|---|---:|---:|---|
| exp1 | 均衡基线 | 60s/组 | 32 | direct、swrr、p2c、balanced |
| exp2 | 外部热点压力 | 90s/组 | 32 + direct pressure 32 | NPU3 长 prompt 背景压力，采集 vLLM `/metrics` 与 router `/admin/state` |
| exp3 | 动态 capacity | 120s | 32 | 30s: 10->1；80s: 1->10 |
| exp4 | 故障恢复 | 300s | 32 | 30s stop NPU5；90s start NPU5 |
| exp5 | 资源池隔离 | 120s | default 32 / isolated 96 | 两个真实资源池并行 |
| exp6 | 综合剧本 | 210s | 32 | 降容、压力、故障、恢复 |
| exp7 | smoothStep | 80s/组 | 32 | 20s: 10->1；50s: 1->10 |

## 4. 验收标准

- 所有正式结果来自真实 NPU 3-7。
- 实验期间不停止非指定容器。
- router 只清理 PID 文件记录的本项目进程。
- exp3/exp7 的 stable down 使用分窗口统计，不混入 transition。
- exp2 baseline 使用静态 SWRR；P2C 组必须配置 vLLM `metrics_url`，并证明 NPU3 的 `remote_utilization` 上升后流量占比下降。

## 5. 当前实测结论

当前结果目录：

```text
bench/results/real-npu-20260627021640/
```

核心结论：

- 均衡开销低：`p2c_smooth_wrr` 相比 `swrr` QPS 只低约 0.38%。
- 实时负载避热点有效：exp2 中 SWRR baseline 给 NPU3 19.96%，`p2c_smooth_wrr` 降到 0.00%，`balanced_p2c` 降到 3.94%。
- capacity 迁移准确：exp3 stable down 2.37%，理论 2.44%，0 错误。
- 故障摘除有效：exp4 fail stable NPU5 占比 0.02%，全程错误率 0.0041%。
- 资源池隔离有效：default 池在 isolated 池长请求压力下 0 错误。
- smoothStep=0.25 是当前默认折中：stable down 2.31%，误差 0.13pp。

## 6. 下一步

- 接入更直接的 Ascend NPU utilization exporter，补充设备级压力信号。
- 增加 token-cost-aware inflight。
- 增加多模型轻量矩阵，覆盖更长 TTFT 和更高 KV cache 压力。
