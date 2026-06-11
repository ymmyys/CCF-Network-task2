# 赛题2：大模型推理算力资源动态负载感知调度 — 实施计划（PLAN）

> 配套文档：同目录 `赛题2-解析.md`（赛题拆解 + 评分映射 + 调研结论）

## Context（为什么做这件事）

赛题2 的内核是一个**带动态权重的 LLM 推理负载均衡器（Router）**，跑在华为昇腾 NPU（910/910B/910C）异构算力之上。要解决三件事：

1. **动态负载感知**：节点可用性受实例健康、瞬时负载、资源池隔离影响，是动态变化的，静态轮询无法适配，会造成热点过载 + 其他节点空闲。
2. **动态权重调度**：把实时负载折算成权重，按权重概率选节点，消除热点。
3. **平滑过渡（评分关键）**：节点 capacity 从 10 骤降到 1 时，新请求平滑迁走、**在途请求绝不强制中断**；恢复时平滑回升。

评分对齐（决定投入重点）：
- **算力网特性利用程度 40%** → 必须用昇腾 NPU 真实指标（npu-smi 利用率/显存、KV cache、队列、延迟）+ 多资源池/异构，做实做透。
- 创意新颖性 30% → 算法相对 SWRR/静态轮询有明确升级点。
- 方案可行性 30% → 可运行原型 + ≤5min 演示视频。

**已确认决策**：原型形态 = 独立 Router 服务（挡在多个 vLLM-Ascend / MindIE 实例前，不改引擎内核）；技术栈 = Python（FastAPI + asyncio）；昇腾卡已可用，做真机演示。

---

## 核心算法：LA-SWRR（Load-Aware Smooth WRR）

一句话：**SWRR 平滑骨架 + Power-of-Two 防羊群 + 实时负载折算 effective_weight + 衰减/slow-start 处理容量突变**。

### 1) 实时负载 → 有效权重
每节点周期上报指标，折算容量分：
```
load_i      = w1*queue_len + w2*npu_util + w3*kv_cache_used + w4*ewma_latency   # 各项归一化
capacity_i  = base_capacity_i * health_i          # health: 探活/错误率 [0,1]
target_w_i  = clamp(capacity_i * (1 - load_i), 0, base)
```
关键：`effective_weight` **不直接跳变**，每个 tick 向 `target_w` 缓动（`eff += sign*step`，仿 nginx `effective_weight++`），天然产生平滑。

### 2) 选节点：SWRR ⊕ Power-of-Two
- 主路径 SWRR：`current_weight += effective_weight` → 选 max → `current_weight -= total_weight`（参考 nginx 平滑加权轮询，保证按权重平滑分布、不爆发）。
- 叠加 P2C：在高权重候选里随机取两个，比 `active_requests / effective_weight`，选更空者，进一步消热点（参考 Ray Serve pow_2_router、SGLang power_of_two）。

### 3) capacity 10→1 平滑过渡（评分核心，必须可视化对比）
节点状态机：`active → draining → drained → recovering(slow-start) → active`
- **新请求**：`target_w` 设为 1，`effective_weight` 用衰减曲线在 N 个 tick 内从 10 滑到 1（不瞬跳，避免流量断崖与 SWRR 计数器 overshoot）。
- **在途请求**：Router 只管未来准入；已分配请求绝不强制断；draining 期间继续跑完存量（按 in-flight 计数判定 drained）。
- **恢复**：slow-start，权重逐步爬回，防止刚恢复就被打爆再抖动。
- **兜底**：错误率超阈值触发 outlier 式临时摘除，健康后自动归队（参考 Envoy outlier detection）。

---

## 原型架构（独立 Router）

```
client ──> [LA-SWRR Router (FastAPI/asyncio)] ──> 多个昇腾推理实例 (vLLM-Ascend / MindIE)
                  │  Scheduler(LA-SWRR + P2C + 状态机)
                  │  NodeState(EWMA 平滑指标) <── 各节点 /metrics (npu-smi/队列/KV/延迟)
                  └  /admin (注入 capacity 变更事件) + /stats (导出曲线数据)
```

### 建议目录结构（待创建，全部放当前文件夹）
```
e:\大四上\CCF-cpt\
  router/
    app.py              # FastAPI 入口：转发请求 + admin/stats 端点
    scheduler.py        # LA-SWRR + P2C 选节点核心
    node_state.py       # NodeState、EWMA、target_w 计算、状态机
    metrics.py          # 采集/解析 npu-smi、队列、KV、延迟
    config.py           # 权重系数 w1..w4、step、slow-start 参数
  bench/
    load_gen.py         # 变长 LLM 请求负载发生器
    inject_events.py    # 注入 capacity 10→1 事件
    plot.py             # 出对比图（方差 / P99 / 中断数）
  docs/
    design.md           # 设计方案
    roadmap.md          # 技术路线图
  README.md
```

---

## 分步执行计划

**阶段 0 — 环境与骨架**
- OpenI 启智社区起多个昇腾推理实例（vLLM-Ascend 或 MindIE），确认每节点能暴露指标。
- 搭 FastAPI 转发骨架 + 静态轮询基线（作为对比对照组）。

**阶段 1 — 指标采集层**（`metrics.py` + `node_state.py`）
- 各节点暴露：队列长度、npu-smi 利用率/显存、KV cache 占用、推理延迟。
- Router 侧 EWMA 平滑，统一成 `NodeState`；实现 `target_w` 折算。

**阶段 2 — 调度核心**（`scheduler.py`）
- 实现 SWRR 计数器 + `effective_weight` 向 `target_w` 缓动 + P2C 叠加。
- 单元测试：权重分布正确性、P2C 选择、缓动收敛。

**阶段 3 — 平滑过渡 + 兜底**（`node_state.py` 状态机）
- in-flight 计数与 drain 逻辑；衰减/slow-start 曲线；outlier 摘除/自愈。
- `/admin` 注入 capacity 变更事件。

**阶段 4 — 评测与演示**（`bench/`）
- 负载发生器打变长请求；注入 capacity 10→1 事件。
- 出对比图：静态轮询 vs LA-SWRR 的 **负载方差 / P99 延迟 / 被中断请求数**。目标：零中断 + 方差显著下降。
- 录 ≤5min 视频：讲算法 → 放对比曲线 → 强调零中断与热点消除。
- 写 `docs/design.md` + `roadmap.md` + README，显式对齐三项评分（重点写满 40% 的算力网/昇腾特性）。

---

## 复用的现成实现/理论（避免重造轮子）

- **nginx 平滑加权轮询（SWRR）**：`current_weight += effective_weight` → max → `-= total`；`effective_weight` 故障降、恢复 `++` 回升 —— 直接作为平滑骨架与回升机制。
- **Power-of-Two**：[Ray Serve pow_2_router.py](https://github.com/ray-project/ray/blob/c33b6074/python/ray/serve/_private/request_router/pow_2_router.py)、[SGLang power_of_two.rs](https://github.com/sgl-project/sglang/blob/4a50cd78/sgl-model-gateway/src/policies/power_of_two.rs)。
- **LLM 路由立论**：[Modular: 为什么 LLM 推理需要新型 Router](https://www.modular.com/blog/why-llm-inference-needs-a-new-kind-of-router-part-1)、[vLLM Router](https://blog.vllm.ai/2025/12/13/vllm-router-release.html)、[KV Cache Aware Routing](https://docs.vllm.ai/projects/production-stack/en/vllm-stack-0.1.8/use_cases/kv-cache-aware-routing.html)、[llm-d](https://llm-d.ai/blog/kvcache-wins-you-can-see)。
- **论文（新颖性来源）**：[SkyLB](https://arxiv.org/html/2505.24095v1)、[Lodestar 在线学习路由](https://arxiv.org/html/2606.00946)、[Data-Parallel LB Bottleneck](https://arxiv.org/html/2605.06113v2)、[Power of Two Choices 综述](https://www.eecs.harvard.edu/~michaelm/postscripts/handbook2001.pdf)。
- **平滑/兜底范式**：[Envoy LB](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers)、[Envoy outlier](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/outlier)、[K8s readiness/drain](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)。

---

## 验证方法（端到端）

1. **算法单测**：给定固定权重，验证 SWRR 输出序列与权重比例一致、状态返回零点循环；验证 P2C 选择更空节点；验证 `effective_weight` 缓动收敛到 `target_w`。
2. **平滑过渡测试**：注入 capacity 10→1，断言 **in-flight 请求被中断数 = 0**，effective_weight 按曲线下降而非瞬跳。
3. **真机对比实验**（昇腾多实例）：同一负载下跑静态轮询基线 vs LA-SWRR，采集各节点负载方差、P99 延迟、中断数，出对比图。
4. **演示**：跑 `bench/load_gen.py` + `inject_events.py`，实时看 `/stats` 曲线，录制视频。
