# MUTT Live Console（现场可视化）

单页观测台，只读/调用现有 Admin API，**不改调度算法**。同学在真机上按原流程启动 MUTT 后，浏览器打开即可。

## 同学最快用法（推荐）

1. 按 `docs/runbook.md` 正常启动 MUTT（admin 默认 `:8181`）。
2. **任选一种打开方式：**

### 方式 A：嵌入式（需重新 `go build` 一次）

```bash
go build -o /workspace/bin/mutt ./cmd/router
# 启动后打开：
# http://127.0.0.1:8181/demo/
```

### 方式 B：Python 代理（无需重编二进制）

```bash
python3 scripts/serve_demo_dashboard.py --admin http://127.0.0.1:8181 --port 8787
# 打开 http://127.0.0.1:8787/
```

远程跳板机 / VS Code 端口转发时，把 `8181`（或 `8787`）转到本机即可。

## 页面能力

| 模式 | 作用 |
|---|---|
| **连接 Live** | 轮询 `GET /admin/state`，展示 phase / transition_reason / capacity / desired·effective weight / inflight / remote_utilization |
| **现场按钮** | `POST /admin/capacity`、`POST /admin/health`（平滑降容、持久人工摘除与恢复） |
| **离线演示** | 无 NPU 时也能预演热点 / 降容 / 故障 / 恢复场景 |

## 兼容性说明

- 数据协议与当前仓库 `internal/router` 的 JSON 字段一致。
- 「标记不健康」设置 `admin_disabled=true`，不会被后续成功健康探测自动覆盖；「标记健康」清除人工摘除，并按 slow-start 恢复流量。
- `observed_healthy` 表示真实探测结果，`healthy` 表示叠加管理员禁用后的最终可用状态；人工摘除期间即使 `effective_weight` 尚在平滑衰减，调度器也不会再分配新请求。
- `transition_reason` 区分 `capacity_downscale`、`capacity_upscale`、健康故障、人工摘除和被动失败；成功健康探测不会再把容量下降误判成恢复。
- 权重条采用集群统一绝对刻度：实心条是 `effective_weight`，白色竖线是 `desired_weight`，文字同时显示 `capacity` 与归一化 dispatch share。百分比只用于说明相对份额，不再单独承担权重可视化。
- 同一 origin 访问时无跨域问题；admin 面已加 CORS，便于调试。
- 可视化展示的是 **effective_weight 份额** 与 **remote_utilization**；P2C 选路还会比较 loadScore，实测请求占比可能更激进地避开热点——页面底部有说明，答辩时可主动讲清。

## 现场建议脚本（约 2 分钟）

1. 打开 Live，展示 5 个 NPU 均衡。
2. 对热点节点加压（原有 direct 压测），看 utilization 变红、权重份额下降。
3. 点 `capacity → 1`，看 effective weight 平滑下滑，inflight 请求自然结束。
4. 点「标记不健康」或停一个后端，看 draining / ejected。
5. 恢复后看 recovering slow-start。
