# Experiment Results

This document records the current real Ascend NPU validation run for Track 2.

## Environment

- Date: 2026-06-26
- Host: `kunlun-02-act`
- Router container: `yijq27-cann851`
- vLLM image: `quay.io/ascend/vllm-ascend:v0.18.0rc1`
- Model: `Qwen/Qwen2.5-1.5B-Instruct`
- Model path: `/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct`
- Experiment router data plane: `http://127.0.0.1:8180`
- Experiment router admin plane: `http://127.0.0.1:8181`

NPU usage during this run:

- `qwen15b-npu3`: NPU 3, vLLM port `9021`
- `qwen15b-npu4`: NPU 4, vLLM port `9022`
- NPU 2 was already occupied by another process and was not touched.

Both vLLM backends passed direct OpenAI-compatible API checks:

```text
9021 -> Pong
9022 -> Pong
```

## Balanced Load

Purpose: verify that dynamic load-aware scheduling has no significant overhead
when both backends are healthy and symmetric.

Load:

- duration: 45s
- concurrency: 16
- request: `/v1/chat/completions`
- `max_tokens`: 16

| Scheduler | Requests | Success Rate | p50 ms | p95 ms | p99 ms | Backend Distribution |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `swrr` | 5690 | 100% | 125.89 | 140.41 | 148.51 | npu3=2848, npu4=2842 |
| `p2c_smooth_wrr` | 5625 | 100% | 128.57 | 140.63 | 145.99 | npu3=2815, npu4=2810 |

Conclusion: under balanced backend conditions, `p2c_smooth_wrr` keeps the same
success rate and nearly the same latency as static smooth weighted round-robin,
so the dynamic scheduler does not introduce meaningful overhead in the normal
case.

## Dynamic Capacity Drop

Purpose: validate the required smooth transition when a backend capacity drops
from `10` to `1`, then recovers to `10`.

Events:

```text
t=15s: qwen15b-npu3 capacity 10 -> 1
t=40s: qwen15b-npu3 capacity 1 -> 10
```

Load:

- duration: 65s
- concurrency: 16
- request: `/v1/chat/completions`
- `max_tokens`: 16

Overall result:

| Metric | Value |
| --- | ---: |
| Requests | 7661 |
| Success Rate | 100% |
| p50 ms | 133.42 |
| p95 ms | 196.45 |
| p99 ms | 208.78 |
| Backend Distribution | npu3=2337, npu4=5324 |

Request distribution around the capacity drop:

| Second | npu3 Requests | npu4 Requests | Observation |
| ---: | ---: | ---: | --- |
| 10 | 64 | 63 | balanced before event |
| 14 | 64 | 62 | balanced before event |
| 15 | 47 | 76 | traffic starts moving away from npu3 |
| 18 | 27 | 93 | npu3 share keeps decreasing |
| 21 | 14 | 105 | npu3 mostly drained |
| 25 | 9 | 111 | near target reduced share |
| 30 | 10 | 105 | stable low-share period |

Request distribution around recovery:

| Second | npu3 Requests | npu4 Requests | Observation |
| ---: | ---: | ---: | --- |
| 40 | 10 | 76 | recovery event just happened |
| 45 | 14 | 100 | slow-start begins |
| 48 | 33 | 90 | npu3 share increases gradually |
| 51 | 45 | 77 | npu3 continues recovering |
| 54 | 55 | 70 | approaching balanced distribution |

Router state samples:

| Sample | Backend | Phase | Capacity | Desired Weight | Effective Weight | Inflight | Latency EWMA ms |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | qwen15b-npu3 | active | 10 | 9.948 | 9.948 | 0 | 129.5 |
| 0 | qwen15b-npu4 | active | 10 | 9.948 | 9.948 | 0 | 130.3 |
| 14 | qwen15b-npu3 | active | 10 | 9.701 | 9.707 | 8 | 128.3 |
| 14 | qwen15b-npu4 | active | 10 | 9.700 | 9.698 | 8 | 126.5 |
| 16 | qwen15b-npu3 | recovering | 1 | 0.066 | 4.249 | 4 | 117.7 |
| 16 | qwen15b-npu4 | active | 10 | 9.603 | 9.668 | 12 | 133.3 |
| 20 | qwen15b-npu3 | recovering | 1 | 0.330 | 1.518 | 2 | 109.7 |
| 30 | qwen15b-npu3 | active | 1 | 0.993 | 0.873 | 1 | 99.1 |
| 40 | qwen15b-npu3 | recovering | 10 | 0.833 | 0.655 | 1 | 97.1 |
| 45 | qwen15b-npu3 | recovering | 10 | 4.127 | 2.582 | 3 | 110.5 |
| 55 | qwen15b-npu3 | active | 10 | 9.733 | 8.744 | 7 | 122.0 |

Conclusion: the scheduler performs the required smooth transition. After
capacity drops, `desired_weight` changes quickly while `effective_weight`
decreases gradually from about `9.7` to `0.87`; traffic shifts away from the
reduced backend without request failures. After capacity recovers, the backend
enters `recovering` and gradually returns toward its original request share.

## Exploratory Hot-Backend Run

An exploratory run directly loaded `qwen15b-npu3` while measured traffic went
through the router. The request distribution remained close to 50/50:

```text
p2c_smooth_wrr hot run: npu3=2317, npu4=2336, success=100%
```

This result is useful as a limitation note: direct out-of-band traffic is not
always reflected strongly enough by the currently parsed vLLM metrics to steer
traffic away automatically. The capacity, health, inflight, and in-router
latency mechanisms are validated, but external-load sensitivity can be improved
by adding stronger vLLM metrics or an NPU exporter signal.

## Submission-Relevant Claims

These results support the following claims for the Track 2 submission:

- The system runs end-to-end on real Ascend 910B resources with vLLM Ascend.
- Under normal conditions, dynamic scheduling has no meaningful overhead versus
  static SWRR.
- Capacity changes such as `10 -> 1` are smoothed by `effective_weight`, so
  traffic migrates gradually.
- The backend is not abruptly removed; request success remained `100%` during
  the transition.
- The implementation avoids occupied NPU resources by explicitly selecting
  available NPU IDs and using separate experiment ports.

## 完整实验计划

为了验证动态负载感知调度器的核心能力，我们设计了完整的7组实验，详见 [full-experiment-plan.md](full-experiment-plan.md)。

实验设计覆盖以下维度：
1. **正常均衡场景**：证明动态调度无额外开销
2. **异构负载场景**：验证慢节点避让能力，并记录吞吐和延迟折中
3. **动态降容场景**：验证capacity平滑迁移
4. **故障恢复场景**：证明高可用性
5. **资源池隔离**：验证多租户隔离能力
6. **真实NPU端到端**：证明可落地性
7. **smoothStep参数敏感性**：验证降容迁移的收敛速度和平滑性折中

完整的实验脚本和配置文件见 `scripts/` 和 `config/` 目录。
