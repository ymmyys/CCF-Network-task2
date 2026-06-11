# suan-router

大模型推理算力资源动态负载感知调度 router 第一版。数据面用 Go 实现，适合放在推理服务前面做流式反向代理和动态权重调度。

## 核心机制

- 资源池隔离：请求头 `X-Resource-Pool` 选择资源池，未指定时进入 `default`。
- 平滑加权轮询：每个 backend 使用 smooth weighted round robin，权重高的 NPU 节点获得更高请求概率。
- 动态目标权重：`capacity * headroom`，其中 `headroom` 来自 NPU 利用率、队列深度和本地 inflight 请求数。
- 平滑降权：有效权重按 `effective += (desired - effective) * smooth_step` 逐步靠近目标权重。比如 capacity 从 10 降到 1 时，新请求概率会逐步下降，已分配请求不会被中断。
- 健康与被动熔断：健康检查失败或连续代理错误会暂时摘除 backend，后续探活恢复。
- Prometheus 兼容：router 会读取 backend 的 Prometheus 指标，也会暴露自身 `/metrics`。

## 运行

```bash
go run ./cmd/router -config config/router.example.json
```

数据面默认监听 `:8080`，管理面默认监听 `:8081`。

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

观察 `desired_weight` 会立即接近新 capacity 对应目标值，`effective_weight` 会按 `smooth_step` 平滑下降。
