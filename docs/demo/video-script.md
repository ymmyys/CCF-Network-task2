# 原型展示视频讲稿

目标时长：4 分 30 秒到 5 分钟。最终自动成片使用 `docs/demo/prototype-demo-final-narration.txt` 作为旁白文本，并已生成 `docs/demo/prototype-demo-final.mp4`。如果需要真人配音或重新录屏，可以屏幕录制 `docs/demo/prototype-demo.html`，并按下面讲稿配音。视频中不需要展示密码、远程登录信息或长时间实验过程。

## 0:00-0:25 开场

画面：标题页和赛题关键词。

旁白：

> 我们的作品面向赛题 2：大模型推理算力资源动态负载感知调度。问题是，在真实推理集群里，后端 NPU 的可用能力不是静态的。某个节点可能正在承受外部压力，也可能正在恢复、降容或故障。如果仍然使用静态轮询，请求会继续打到热点节点，造成尾延迟和错误扩散。

## 0:25-1:05 系统架构

画面：Client、suan-router、5 个 vLLM-Ascend 后端、admin/metrics。

旁白：

> 我们实现了一个 OpenAI-compatible router，部署在客户端和 vLLM-Ascend 后端之间。数据面监听 8180，管理面监听 8181。后端是 5 个真实 Ascend 910B NPU，分别运行 vLLM-Ascend。router 会读取健康检查、管理面 capacity、本地 inflight，以及 vLLM 的 Prometheus 指标，包括 running、waiting、KV cache 和延迟信号。请求头 X-Resource-Pool 用于多资源池隔离。

## 1:05-1:45 核心算法

画面：权重计算公式和状态机。

旁白：

> 核心算法分两层。第一层是目标权重：desired weight 等于 capacity 乘以 headroom，headroom 来自多维负载评分。第二层是平滑有效权重：effective weight 逐步追随 desired weight。这样当某个节点 capacity 从 10 降到 1 时，新请求会平滑迁移，而已经分配给后端的请求不会被强制中断。调度器支持静态 smooth WRR、P2C smooth WRR 和 balanced P2C。后端还有 active、draining、drained、recovering 的状态机，以及故障冷却和 slow-start。

## 1:45-2:35 实验一：真实热点避让

画面：exp2 柱状图。

旁白：

> 第一个关键实验是热点避让。我们对 NPU3 直接发送长 prompt 背景压力，同时通过 router 发送测量流量。静态 SWRR 不读取 metrics，所以仍然给 NPU3 约 19.96% 的流量。P2C smooth WRR 读取到 NPU3 的 remote utilization 为 1.0 后，把 NPU3 的测量流量降到 0%。balanced P2C 保留 3.94% 的受控探测流量。三组都是 0 错误，动态组的 p95 和 p99 也优于静态基线。

## 2:35-3:25 实验二：capacity 平滑迁移

画面：exp3 时间窗口和理论占比。

旁白：

> 第二个实验对应赛题要求的 capacity 10 到 1 再恢复到 10。理论上，目标节点降容后占比应当接近 1 除以 41，也就是 2.44%。实际稳定降容窗口中，NPU3 占比是 2.37%，误差只有 0.07 个百分点。整个实验 29,748 个请求，0 错误。这个结果说明权重变化是平滑的，并且没有中断已分配请求。

## 3:25-4:05 实验三：故障恢复和资源池隔离

画面：exp4 和 exp5 汇总。

旁白：

> 第三个能力是高可用和隔离。故障实验只停止我们自己的 yijq27-vllm-qwen15b-5 容器。故障稳定期，NPU5 的流量占比降到 0.02%，恢复末段回到 19.80%。资源池隔离实验中，isolated 池承受长请求压力时，default 池仍然完成 28,218 个请求，0 错误。这说明 noisy neighbor 不会跨资源池影响正常业务。

## 4:05-4:35 7B 泛化验证

画面：exp8 7B 结果。

旁白：

> 为了避免只验证小模型，我们补充了 Qwen2.5-7B-Instruct 的热点避让实验。7B 单卡 vLLM 后端运行在 NPU3 到 NPU7。静态 SWRR 仍然给热点 NPU3 19.81% 流量；P2C smooth WRR 降到 0%；balanced P2C 保留 3.64%。三组 0 错误，动态组在吞吐和 p99 上优于基线。这个实验作为跨模型泛化证据。

## 4:35-4:55 收尾

画面：复现路径和安全边界。

旁白：

> 所有正式结论都来自真实 Ascend NPU 3 到 7，不使用 fake backend。实验脚本只清理自己启动的 router PID；故障实验只操作指定容器；7B 临时容器在实验后删除释放卡。完整代码、操作手册、实验数据和最终报告都已经在仓库中。

## 录制建议

- 不要录完整实验重跑过程，时间太长。录演示页、状态快照和结果表即可。
- 如果需要展示终端，只展示 `curl /admin/state`、`/metrics` 和结果汇总，不展示密码。
- 讲稿按自然语速约 4 分 40 秒；如果超时，删掉 exp7 smoothStep，只保留一句“参数有真实实验依据”。
