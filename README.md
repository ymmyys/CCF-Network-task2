# suan-router

`suan-router` 是面向赛题 2「大模型推理算力资源动态负载感知调度」的 OpenAI-compatible 推理网关。它运行在 vLLM-Ascend 后端之前，根据后端健康状态、capacity、inflight、vLLM 指标和资源池策略动态选择目标 NPU。

## Purpose

赛题要求在 Ascend NPU 推理集群中避免热点、支持动态 capacity 变化、节点故障摘除、多资源池隔离，并在 capacity 从 10 降到 1 时平滑迁移新请求而不中断已分配请求。本项目实现了：

- 资源池隔离：请求头 `X-Resource-Pool` 选择资源池，未指定时进入 `default`。
- 动态权重：`desired_weight = capacity * headroom`，`headroom` 来自 NPU/vLLM 指标和本地 inflight。
- 平滑迁移：`effective_weight += (desired_weight - effective_weight) * smooth_step`。
- 调度器：`swrr`、`p2c_smooth_wrr`，以及可选 `balanced_p2c`。
- 高可用：健康检查、被动熔断、代理错误短暂 cooloff、recovering slow-start。
- 管理面：`/admin/state`、`/admin/capacity`、`/admin/health`、`/metrics`。

## Architecture

```text
client
  |
  v
suan-router (:8180 data, :8181 admin)
  |-- pool=default  -> qwen15b-npu3/4/5/6/7
  |-- pool=isolated -> configured isolated real NPU pool
  |
  v
vLLM-Ascend containers on Ascend 910B
```

核心代码：

- `cmd/router/main.go`：启动入口。
- `internal/router/router.go`：HTTP 代理、管理 API、metrics。
- `internal/router/scheduler.go`：SWRR、P2C、balanced P2C。
- `internal/router/backend.go`：状态机、健康检查、指标解析、权重计算。

## Quick Start

本地运行一个示例配置：

```bash
go run ./cmd/router -config config/router.example.json
```

Kunlun-02 Ascend 实验环境中，router 在 CANN 容器内构建和运行：

```bash
docker exec yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  go build -o /workspace/bin/suan-router ./cmd/router
'
```

完整操作手册见 [`docs/runbook.md`](docs/runbook.md)。

## Real NPU Experiments

最新正式实验只使用真实 Ascend NPU 3-7，不把 fake backend 数据写入主结论。实验结果目录：

```text
bench/results/real-npu-20260627021640/
```

统一汇总：

```text
bench/results/real-npu-20260627021640/analysis/real_npu_summary.csv
bench/results/real-npu-20260627021640/analysis/real_npu_summary.md
```

一键重跑：

```bash
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

安全边界：

- 只使用 `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7`。
- 只有故障实验会停止/启动 `yijq27-vllm-qwen15b-5`。
- router 只通过 PID 文件清理自己启动的进程，不使用宽泛 `pkill`。

## Current Real Results

| 能力 | 真实 NPU 结果 |
|---|---|
| 均衡开销 | `swrr` 247.41 QPS，`p2c_smooth_wrr` 246.46 QPS，二者 0 错误 |
| 动态降容 | `qwen15b-npu3` capacity 10->1 后稳定占比 2.37%，理论 2.44%，29,748 请求 0 错误 |
| 故障恢复 | 停止 `yijq27-vllm-qwen15b-5` 后 `fail_stable` 占比 0.02%，全程 72,794 请求 3 错误 |
| 资源池隔离 | default 池 28,218 请求 0 错误；isolated 池真实长请求 1,592 请求 0 错误 |
| smoothStep | `0.25` 稳定降容占比 2.31%，误差 0.13pp；`0.5/1.0` 收敛更快但更接近硬切换 |

真实热点压力 exp2 使用 direct long-prompt 负载压 NPU3，但 vLLM 指标没有形成可观测 waiting/KV 高水位，三种调度器目标占比都约 20%。因此它作为边界说明，不作为“外部压力自动避让”的优势证明。

完整报告见 [`docs/final-report.md`](docs/final-report.md)，实验数据说明见 [`docs/experiment-results.md`](docs/experiment-results.md)。
