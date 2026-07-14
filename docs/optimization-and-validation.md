# 优化与验证记录

本文档记录当前版本的调度优化、真实 NPU 验证结果和后续优化方向。正式结论只引用真实 Ascend NPU 3-7 数据。

## 已实现优化

### P2C 同后端高负载重采样

当两次带放回采样命中同一个高负载后端时，router 会额外从其余候选中补抽一个后端，再按 `loadScore` 比较。这样保留权重语义，同时降低热点节点被重复确认的概率。

### 故障冷却

配置：

```json
"failure_cooloff_duration": "1s"
```

代理错误或 5xx 响应后，后端会短暂不可调度；成功响应或健康探测恢复会清除 cooloff。该机制降低健康检查窗口内继续打到坏节点的概率。

### 非法指标防护

Prometheus 中的 `NaN`、`+Inf`、`-Inf` 会被忽略。权重计算和候选过滤拒绝非有限值，防止异常指标污染调度状态。

### 均衡 P2C

配置：

```json
"scheduler": {
  "mode": "p2c_smooth_wrr",
  "balanced_p2c": true,
  "slow_backend_min_share": 0.10
}
```

真实 5 后端配置：

```text
config/router.qwen15b-5backends-balanced.json
```

balanced P2C 只对健康且可调度的慢后端保留受控流量；不健康、被动摘除、故障冷却、drained、capacity=0、max inflight 已满的后端仍不会被调度。

### 多路 metrics 与设备级 HBM 信号

每个 backend 现在支持 `metrics_urls`，可以同时读取 vLLM `/metrics` 和 NPU exporter：

```json
"metrics_urls": [
  "http://127.0.0.1:9021/metrics",
  "http://127.0.0.1:19021/metrics"
]
```

MUTT 会合并多路样本，取 running、waiting、KV cache、AI Core/NPU utilization、HBM usage、latency 的最大压力值进入 EWMA。新增配置项：

```json
"hbm_weight": 0.15,
"hbm_soft_limit": 1
```

`hbm_soft_limit=1` 适合 exporter 直接暴露百分比/比例；如果 exporter 暴露 used bytes/MB，可把 `hbm_soft_limit` 设置为设备 HBM 容量，用于归一化。模板见：

```text
config/router.qwen15b-5backends-npu-exporter.example.json
```

### 7B latency-aware 调度配置

针对 exp8 中 Qwen2.5-7B 出现的 p95 trade-off，新增一组专门配置：

```text
config/router.qwen7b-5backends-latency.json
```

该配置提高 `latency_weight`、收紧 `latency_slo_ms`，并用更快 EWMA 让本地延迟反馈更快进入 load score。`scripts/run_experiment8_qwen7b_real.sh` 会在原有 `swrr / p2c / balanced` 之后追加 `latency` 组，便于决赛前重跑对照。

## 真实 NPU 验证

最新结果：

```text
bench/results/formal/analysis/real_npu_summary.csv
```

| 能力 | 结果 |
|---|---|
| 均衡开销 | `swrr` 247.41 QPS；`p2c_smooth_wrr` 246.46 QPS；均 0 错误 |
| 真实热点避让 | SWRR 基线给 NPU3 19.96%；`p2c_smooth_wrr` 在 `remote_utilization=1.0` 时降到 0.00%；`balanced_p2c` 降到 3.94% |
| 动态降容 | NPU3 稳定降容占比 2.37%，理论 2.44%，29,748 请求 0 错误 |
| 故障恢复 | NPU5 故障稳定期占比 0.02%，恢复末段占比 19.80%，72,794 请求 3 错误 |
| 资源池隔离 | default 池 28,218 请求 0 错误；isolated 池 1,592 长请求 0 错误 |
| smoothStep | 0.25 稳定降容占比 2.31%，误差 0.13pp |
| 7B 泛化热点避让 | Qwen2.5-7B 下 SWRR 给 NPU3 19.81%；`p2c_smooth_wrr` 降到 0.00%；`balanced_p2c` 降到 3.64%；均 0 错误 |

## exp2 指标驱动热点验证

真实 exp2 对 NPU3 发 direct 长 prompt 压力，并通过 router 测量 5 后端分布。SWRR 基线不配置 `metrics_url`，只按静态 capacity 轮询；P2C 组配置 vLLM `/metrics`，router 解析 `vllm:num_requests_running`、`vllm:num_requests_waiting`、`vllm:gpu_cache_usage_perc`。

重跑结果目录：

```text
bench/results/formal/exp2-hotspot-load/
```

| 调度器 | NPU3 占比 | p95 | p99 | NPU3 max running | router max remote_utilization |
|---|---:|---:|---:|---:|---:|
| swrr 基线 | 19.96% | 154.65ms | 178.44ms | 38 | 0.0 |
| p2c_smooth_wrr | 0.00% | 148.74ms | 158.73ms | 32 | 1.0 |
| balanced_p2c | 3.94% | 149.97ms | 157.72ms | 35 | 1.0 |

结论：在 NPU3 真实外部压力被 vLLM `/metrics` 观测到后，动态调度会主动降低热点节点被选中概率。`p2c_smooth_wrr` 追求尾延迟和热点规避，把 NPU3 测量流量降到 0；`balanced_p2c` 保留少量探测流量，便于热点消退后恢复判断。

## exp8 7B 泛化验证

exp8 将后端模型换为 `Qwen/Qwen2.5-7B-Instruct`，仍对 NPU3 发送 direct 长 prompt 压力，并通过 router 测量 5 后端分布。该实验使用临时容器 `yijq27-vllm-qwen7b-3` 到 `yijq27-vllm-qwen7b-7`，实验结束后移除容器释放 NPU。

结果目录：

```text
bench/results/formal/exp8-qwen7b-hotspot/
```

| 调度器 | NPU3 占比 | QPS | p95 | p99 | router max remote_utilization |
|---|---:|---:|---:|---:|---:|
| swrr 基线 | 19.81% | 77.51 | 136.74ms | 279.10ms | 0.0 |
| p2c_smooth_wrr | 0.00% | 92.51 | 187.76ms | 222.68ms | 1.0 |
| balanced_p2c | 3.64% | 95.13 | 182.55ms | 214.18ms | 1.0 |

结论：7B 模型下，动态调度仍能根据真实 vLLM 指标把热点 NPU3 从正常 20% 份额降到 0% 或受控探测份额。该实验补充跨模型泛化证据；由于 p95 未优于 SWRR，不夸大为全面延迟优势。新增 `latency` 组用于决赛前补跑尾延迟优化对照。

## 开发夹具

以下内容仅用于开发验证，不进入正式主结论：

```text
bench/fake_backend.py
scripts/run_router_microbench.sh
scripts/run_experiment2.sh
config/router.qwen15b-heterogeneous-*.json
```

fake backend 对确定性复现很有价值，例如构造 300ms 延迟、固定 queue depth、非法指标值等；但赛题提交材料中的性能结论必须来自真实 NPU。

## 后续工作

| 项目 | 状态 | 说明 |
|---|---|---|
| NPU exporter 集成 | 已接入配置与解析 | 支持多路 `metrics_urls`、AI Core/NPU utilization、HBM usage；仍需在目标环境部署 exporter 后补跑对照 |
| token-cost-aware inflight | TODO | 根据 prompt/max_tokens 估计请求成本 |
| 恢复期回退 | TODO | recovering 阶段若出现高延迟/错误，降低回流速度 |
| 多模型矩阵 | 部分完成 | 已补 Qwen2.5-7B 热点避让；后续可扩展更长上下文和更多模型 |
