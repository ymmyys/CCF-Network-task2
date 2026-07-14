# MUTT

**MUTT**（Multi-signal Unified Traffic Tuner，多信号统一流量调优器）是面向赛题 2「大模型推理算力资源动态负载感知调度」的 OpenAI-compatible 推理网关。它部署在客户端与 vLLM-Ascend 后端之间，根据后端健康状态、capacity、本地 inflight、vLLM `/metrics`、可选 NPU exporter 指标和资源池策略动态选择目标 Ascend NPU。

## 项目目标

赛题要求在 Ascend NPU 推理集群中避免热点、支持动态 capacity 变化、节点故障摘除、多资源池隔离，并在 capacity 从 10 降到 1 时平滑迁移新请求而不中断已分配请求。MUTT 已实现：

- 资源池隔离：请求头 `X-Resource-Pool` 选择资源池，未指定时进入 `default`。
- 动态权重：`desired_weight = capacity * headroom`，`headroom` 来自 vLLM running/waiting、KV cache、本地 inflight、延迟 EWMA 和可选 HBM 指标。
- 平滑迁移：`effective_weight += (desired_weight - effective_weight) * smooth_step`。
- 负载感知调度：`swrr`、`p2c_smooth_wrr`，以及可选 `balanced_p2c`。
- 高可用闭环：健康检查、被动熔断、代理错误短暂 cooloff、recovering slow-start。
- 管理与观测：`/admin/state`、`/admin/capacity`、`/admin/health`、`/metrics`。

## 评审维度对齐

| 评审项 | MUTT 对应设计 | 证据 |
|---|---|---|
| 创意新颖性 30% | 多信号闭环权重控制、SWRR-P2C 双层调度、draining/recovering 平滑状态机、balanced P2C 探测流量 | 热点避让、动态降容、故障恢复均有独立实验 |
| 算力网特性利用程度 40% | 使用 Ascend 910B 真实 NPU、vLLM-Ascend `/metrics`、可选 NPU exporter/HBM、KV cache、running/waiting、资源池隔离、capacity 管理面和健康状态 | 正式实验只引用 NPU3-7 真实后端，不把 fake backend 写入主结论 |
| 方案可行性 30% | Go 标准库数据面、零外部运行依赖、Docker/Compose、可复现脚本、Prometheus 指标、PID 文件安全清理 | `go test ./...` 通过，`bench/results/formal/` 已入库真实实验结果 |

## 系统架构

```text
client
  |
  v
MUTT (:8180 data, :8181 admin)
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

## 快速启动

本地运行示例配置：

```bash
go run ./cmd/router -config config/router.example.json
```

容器化启动示例：

```bash
docker compose up --build
```

Compose 默认将容器内 `8080/8081` 映射到宿主机 `8180/8181`，便于和真实 NPU 实验脚本、Live Console 端口保持一致。

Kunlun-02 Ascend 实验环境中，在 CANN 容器内构建和运行 MUTT：

```bash
docker exec yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  go build -o /workspace/bin/mutt ./cmd/router
'
```

完整操作手册见 [`docs/runbook.md`](docs/runbook.md)，文档索引见 [`docs/README.md`](docs/README.md)。

## 现场可视化（Live Console）

兼容现有 `/admin/state` 等接口，同学启动 MUTT 后即可用：

```bash
# 方式 A：重编后直接打开 admin 内嵌页
go build -o mutt ./cmd/router
# http://127.0.0.1:8181/demo/

# 方式 B：不重编二进制，Python 代理打开
python3 scripts/serve_demo_dashboard.py --admin http://127.0.0.1:8181 --port 8787
# http://127.0.0.1:8787/
```

说明见 [`docs/demo/live-console.md`](docs/demo/live-console.md)。无 NPU 时可点页面「离线演示」预演答辩。

## 初赛材料

代码仓库提交时，文字材料已放在 README 与 `docs/` 中；原型展示材料放在 `docs/demo/`：

- 设计方案：[`docs/final-report.md`](docs/final-report.md)
- 技术路线图：[`docs/GPU Scale-Out Hybrid-2026-06-29-132825.png`](docs/GPU%20Scale-Out%20Hybrid-2026-06-29-132825.png)
- 架构图：[`docs/arch.png`](docs/arch.png)
- NPU exporter 配置模板：[`config/router.qwen15b-5backends-npu-exporter.example.json`](config/router.qwen15b-5backends-npu-exporter.example.json)
- 7B latency-aware 配置：[`config/router.qwen7b-5backends-latency.json`](config/router.qwen7b-5backends-latency.json)
- 实验设计：[`docs/experiments.md`](docs/experiments.md)、[`docs/optimization-and-validation.md`](docs/optimization-and-validation.md)
- 原型展示材料：[`docs/demo/submission/`](docs/demo/submission/)
- 原型视频：[`docs/demo/submission/prototype-architecture-realrun-subtitled.mp4`](docs/demo/submission/prototype-architecture-realrun-subtitled.mp4)
- 视频字幕：[`docs/demo/submission/prototype-architecture-realrun.srt`](docs/demo/submission/prototype-architecture-realrun.srt)

## 真实 NPU 实验

最新正式实验只使用真实 Ascend NPU 3-7，不把 fake backend 数据写入主结论。实验数据已按实验编号整理：

```text
bench/results/formal/
bench/results/formal/exp1-balanced-baseline/
bench/results/formal/exp2-hotspot-load/
bench/results/formal/exp3-dynamic-capacity/
bench/results/formal/exp4-failure-recovery/
bench/results/formal/exp5-pool-isolation/
bench/results/formal/exp6-comprehensive/
bench/results/formal/exp7-smoothstep/
bench/results/formal/exp8-qwen7b-hotspot/
```

统一汇总：

```text
bench/results/formal/analysis/real_npu_summary.csv
bench/results/formal/analysis/real_npu_summary.md
```

一键重跑：

```bash
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

安全边界：

- exp1-exp7 只使用 `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7`。
- exp8 只临时使用 `yijq27-vllm-qwen7b-3` 到 `yijq27-vllm-qwen7b-7`，完成后删除释放 NPU。
- 只有故障实验会停止/启动 `yijq27-vllm-qwen15b-5`。
- MUTT 实验进程只通过 PID 文件清理自己启动的进程，不使用宽泛 `pkill`。

## 当前真实实验结果

| 能力 | 真实 NPU 结果 |
|---|---|
| 均衡开销 | `swrr` 247.41 QPS，`p2c_smooth_wrr` 246.46 QPS，二者 0 错误 |
| 实时负载避热点 | NPU3 direct 长请求压力下，SWRR 仍给 NPU3 19.96% 流量；`p2c_smooth_wrr` 读到 `remote_utilization=1.0` 后降到 0.00%；`balanced_p2c` 保留 3.94% 探测流量 |
| 动态降容 | `qwen15b-npu3` capacity 10->1 后稳定占比 2.37%，理论 2.44%，29,748 请求 0 错误 |
| 故障恢复 | 停止 `yijq27-vllm-qwen15b-5` 后 `fail_stable` 占比 0.02%，全程 72,794 请求 3 错误 |
| 资源池隔离 | default 池 28,218 请求 0 错误；isolated 池真实长请求 1,592 请求 0 错误 |
| smoothStep | `0.25` 稳定降容占比 2.31%，误差 0.13pp；`0.5/1.0` 收敛更快但更接近硬切换 |
| 7B 泛化热点避让 | Qwen2.5-7B 真实热点压力下，SWRR 给 NPU3 19.81% 流量；`p2c_smooth_wrr` 降到 0.00%；`balanced_p2c` 保留 3.64% 探测流量；三组均 0 错误 |

完整设计方案见 [`docs/final-report.md`](docs/final-report.md)，实验数据说明见 [`docs/experiment-results.md`](docs/experiment-results.md)。
