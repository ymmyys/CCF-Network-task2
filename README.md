# suan-router

`suan-router` 是面向赛题 2「大模型推理算力资源动态负载感知调度」的 OpenAI-compatible 推理网关。它运行在 vLLM-Ascend 后端之前，根据后端健康状态、capacity、inflight、vLLM 指标和资源池策略动态选择目标 NPU。

## 项目目标

赛题要求在 Ascend NPU 推理集群中避免热点、支持动态 capacity 变化、节点故障摘除、多资源池隔离，并在 capacity 从 10 降到 1 时平滑迁移新请求而不中断已分配请求。本项目实现了：

- 资源池隔离：请求头 `X-Resource-Pool` 选择资源池，未指定时进入 `default`。
- 动态权重：`desired_weight = capacity * headroom`，`headroom` 来自 NPU/vLLM 指标和本地 inflight。
- 平滑迁移：`effective_weight += (desired_weight - effective_weight) * smooth_step`。
- 调度器：`swrr`、`p2c_smooth_wrr`，以及可选 `balanced_p2c`。
- 高可用：健康检查、被动熔断、代理错误短暂 cooloff、recovering slow-start。
- 管理面：`/admin/state`、`/admin/capacity`、`/admin/health`、`/metrics`。

## 系统架构

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

## 快速启动

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

完整操作手册见 [`docs/runbook.md`](docs/runbook.md)，文档索引见 [`docs/README.md`](docs/README.md)。

## 初赛材料

代码仓库提交时，文字材料已放在 README 与 `docs/` 中；原型展示材料放在 `docs/demo/`：

- 设计方案：[`docs/final-report.md`](docs/final-report.md)
- 技术路线图：[`docs/experiments.md`](docs/experiments.md)、[`docs/optimization-and-validation.md`](docs/optimization-and-validation.md)
- 原型展示材料：[`docs/demo/submission/`](docs/demo/submission/)
- 原型视频：[`docs/demo/submission/prototype-demo-final.mp4`](docs/demo/submission/prototype-demo-final.mp4)
- 视频证据说明：[`docs/demo/submission/prototype-evidence-video-guide.md`](docs/demo/submission/prototype-evidence-video-guide.md)
- 浅色讲解 PPT：[`docs/demo/submission/suan-router-preliminary-demo-deck.pptx`](docs/demo/submission/suan-router-preliminary-demo-deck.pptx)
- 逐页阐述文档：[`docs/demo/submission/slide-speaker-notes.md`](docs/demo/submission/slide-speaker-notes.md)

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

其中 exp2 目录只保留指标修复后的正式热点压力重跑数据；exp8 是 Qwen2.5-7B-Instruct 泛化验证，不替代 exp1-exp7 主套件。

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
- router 只通过 PID 文件清理自己启动的进程，不使用宽泛 `pkill`。

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

exp2 的基线是 `config/router.qwen15b-5backends-swrr.json`：它不配置 `metrics_url`，只按静态 capacity 做平滑加权轮询。改进组 `p2c_smooth_wrr` 与 `balanced_p2c` 配置 vLLM `/metrics`，将 `vllm:num_requests_running` 归一化为 `remote_utilization`，并把 `vllm:num_requests_waiting`、GPU/KV cache 指标纳入负载评分。这样可以直接验证赛题要求的“根据节点实时负载动态调整被选中概率”。

exp8 使用同样的热点避让方法，但把模型换成 `Qwen/Qwen2.5-7B-Instruct`，端口为 `9121/9122/9126/9127/9128`。该实验用于回应“单模型验证”的风险：在更大模型上，动态组仍能利用真实 vLLM 指标避开热点 NPU3，并保持 0 错误。

完整报告见 [`docs/final-report.md`](docs/final-report.md)，实验数据说明见 [`docs/experiment-results.md`](docs/experiment-results.md)。
