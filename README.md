# suan-router

大模型推理算力资源动态负载感知调度 router。数据面用 Go 实现，适合放在推理服务前面做流式反向代理和动态权重调度。

## 核心机制

- 资源池隔离：请求头 `X-Resource-Pool` 选择资源池，未指定时进入 `default`。
- P2C + 平滑加权轮询：默认 `p2c_smooth_wrr`，先按有效权重采样两个候选，再选择当前负载更低的 backend；需要做基线实验时可切换为 `swrr`。
- 动态目标权重：`capacity * headroom`，其中 `headroom` 来自 NPU 利用率、队列深度、本地 inflight、KV cache 占用和延迟 EWMA。
- 平滑降权：有效权重按 `effective += (desired - effective) * smooth_step` 逐步靠近目标权重。比如 capacity 从 10 降到 1 时，新请求概率会逐步下降，已分配请求不会被中断。
- 显式状态机：backend 状态包括 `active`、`draining`、`drained`、`recovering`。降容/摘除时进入 draining，恢复时通过 slow-start 从 recovering 回到 active。
- 健康与被动熔断：健康检查失败或连续代理错误会暂时摘除 backend，后续探活恢复。
- Prometheus 兼容：router 会读取 backend 的 Prometheus 指标，也会暴露自身 `/metrics`。

## 运行

```bash
go run ./cmd/router -config config/router.example.json
```

数据面默认监听 `:8080`，管理面默认监听 `:8081`。

Kunlun-02 上的多 vLLM Ascend 部署流程见
[`docs/development.md`](docs/development.md)，对应配置样例为
[`config/router.vllm-ascend.example.json`](config/router.vllm-ascend.example.json)。

## 动态降容演示

把 `ascend-910b-a` 的 capacity 从 10 调到 1：

```bash
curl -X POST http://127.0.0.1:8081/admin/capacity \
  -H 'Content-Type: application/json' \
  -d '{"pool":"default","backend":"ascend-910b-a","capacity":1}'
```

查看当前状态：

```bash
curl http://127.0.0.1:8081/admin/state
```

观察 `phase` 会进入 `draining`，`desired_weight` 会立即接近新 capacity 对应目标值，`effective_weight` 会按 `smooth_step` 平滑下降。

## 调度模式

默认配置：

```json
{
  "scheduler": {
    "mode": "p2c_smooth_wrr"
  }
}
```

对照实验可以改成：

```json
{
  "scheduler": {
    "mode": "swrr"
  }
}
```

## 指标约定

backend 的 `metrics_url` 可返回 JSON 或 Prometheus text format。router 会识别以下关键词：

- NPU 利用率：`npu_util`、`ai_core_util`、`aicore_util`、`device_util`
- 队列深度：`queue_depth`、`request_queue`、`waiting_requests`、`pending_requests`
- KV cache：`kv_cache`、`kvcache`、`cache_block`
- 延迟：`latency`、`duration`、`ttft`、`time_to_first_token`、`decode_time`、`prefill_time`
