# 完整实验计划：大模型推理算力资源动态负载感知调度

## 1. 赛题回顾
**Track 2：大模型推理算力资源动态负载感知调度**
- 核心目标：设计动态负载感知调度器，优化昇腾NPU推理集群的请求调度
- 关键挑战：后端健康状况、负载和容量动态变化，静态轮询导致热点和资源利用率不均
- 评分维度：技术完整性、性能优化效果、实用性

## 2. 实现思路概述
项目实现Go语言HTTP路由器 `suan-router`，核心机制：
- **P2C + 平滑加权轮询**：采样两个候选后端，选择负载更低的节点
- **动态目标权重**：`capacity × headroom`，headroom综合NPU利用率、队列深度、inflight、KV cache、延迟EWMA
- **平滑降权**：`effective += (desired - effective) × smooth_step`，避免流量突变
- **显式状态机**：active → draining → drained → recovering → active
- **健康检查与被动熔断**：自动摘除异常后端，探活恢复
- **资源池隔离**：通过 `X-Resource-Pool` 请求头实现多租户隔离

## 3. 实验设计总览
| 实验 | 对比对象 | 证明点 | 关键指标 |
|------|----------|--------|----------|
| 1. 正常均衡 | direct-vLLM vs router+swrr vs router+p2c | 无明显额外开销 | QPS, p50/p95/p99, TTFT, TPOT |
| 2. 异构负载 | swrr vs p2c_smooth_wrr | 验证慢节点避让能力，并记录吞吐/延迟折中 | 慢节点命中率, QPS, p50/p95/p99 |
| 3. 动态降容 | swrr vs smooth weight | capacity 10→1 平滑迁移 | effective_weight变化, 请求迁移, 错误率 |
| 4. 故障恢复 | 静态调度 vs 健康感知 | 自动摘除与slow-start | 故障检测时间, 恢复过程, 错误率 |
| 5. 资源池隔离 | 无隔离 vs header pool | 多租户隔离 | 池间请求分布, 故障隔离效果 |
| 6. 真实NPU端到端 | 910B vLLM Ascend | 可落地性 | 全链路验证 |
| 7. 参数敏感性 | 不同smoothStep值 | 参数选择合理 | 收敛速度, 平滑性 |

## 4. 实验1：正常均衡场景（三组对照）
### 4.1 目的
证明动态调度在对称后端下无显著额外开销。

### 4.2 对照组设计
```text
A. direct-to-vLLM：不经过router，测单后端原始性能，只作为参考
B. router + swrr：证明router基础转发开销
C. router + p2c_smooth_wrr：证明动态调度额外开销
```

### 4.3 负载设置
```text
短请求：输入32 tokens，输出64 tokens
中请求：输入512 tokens，输出128 tokens
长请求：输入2048 tokens，输出256 tokens
```

### 4.4 关键指标
- QPS / throughput
- p50 / p95 / p99 latency
- TTFT (Time to First Token)
- TPOT (Time Per Output Token)
- queue time
- per-backend request share

### 4.5 预期结论
在均衡场景下，p2c_smooth_wrr相比swrr的QPS、p95、p99基本持平，说明动态调度机制不会在正常场景引入明显性能损失。

## 5. 实验2：异构负载场景（真实NPU压力）
### 5.1 目的
验证动态调度能主动避开慢节点，并量化这种策略对 QPS、p50、p95/p99 的影响。

### 5.2 实验设置
```text
A. swrr：静态轮询
B. p2c_smooth_wrr：使用完整headroom指标
C. 真实NPU压力：对某个后端施加长prompt请求，制造KV Cache压力
```

### 5.3 压力制造方式
```bash
# 长prompt请求，制造KV Cache压力
curl http://127.0.0.1:9021/v1/chat/completions \
  -d '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Write a detailed essay..."}],"max_tokens":256}'
```

### 5.4 重点展示
- 慢节点请求占比下降
- p95/p99、QPS 和 p50 的变化
- 热点后端queue depth下降
- 快节点利用率提升

### 5.5 预期结论
p2c_smooth_wrr 在后端负载不均时能主动避开慢节点；若策略过于激进，可能以 QPS 和 p50 为代价换取慢节点流量下降，因此需要同时展示收益和折中。

## 6. 实验3：动态降容场景（标准化时间线）
### 6.1 目的
验证"capacity从10降到1时平滑过渡，不中断已有请求"。

### 6.2 标准化时间线
```
0-30s：正常运行（基准期）
      - 所有后端 capacity=10
      - 观察均衡分布

30s：注入降容事件
      - qwen15b-npu3 capacity 10 → 1
      - desired_weight 立即下降

30-80s：观察平滑迁移期
      - effective_weight 平滑下降
      - 请求逐步从npu3迁移到其他节点
      - 记录：降容收敛时间

80s：注入恢复事件
      - qwen15b-npu3 capacity 1 → 10
      - 进入 recovering 状态

80-120s：观察slow-start恢复期
      - effective_weight 平滑上升
      - 请求逐步回流到npu3
      - 记录：恢复收敛时间
```

### 6.3 关键指标
每秒采集以下指标：
1. **per-backend request rate**：每个后端每秒请求数
2. **per-backend inflight**：每个后端在途请求数
3. **effective_weight / desired_weight**：权重变化
4. **p50/p95/p99 latency**：延迟分布
5. **TTFT**：首token延迟（从vLLM /metrics）
6. **TPOT**：每token延迟（从vLLM /metrics）
7. **queue time**：排队时间（从vLLM /metrics）
8. **error rate**：错误率

### 6.4 预期结论
- 降容收敛时间 < 10s
- 恢复收敛时间 < 15s
- 降容期间错误率 = 0%
- 降容期间p99抖动 < 20%
- 在途请求中断数 = 0

## 7. 实验4：后端故障与恢复
### 7.1 目的
证明高可用性：自动摘除异常后端，恢复后slow-start。

### 7.2 故障场景
```text
1. docker stop：硬故障
2. 后端返回500：应用层故障
3. 后端超时：慢故障 / 半死不活
```

### 7.3 关键指标
- 故障检测时间
- 摘除时间
- 故障期间错误请求数
- 故障期间p99峰值
- 恢复后slow-start时间
- 恢复后是否出现流量尖峰

### 7.4 预期结论
router能快速摘除异常后端，避免持续把请求打到坏节点。恢复后不是瞬间打满，而是slow-start逐步恢复流量。

## 8. 实验5：资源池隔离（noisy-neighbor测试）
### 8.1 目的
验证多租户隔离能力，防止noisy-neighbor干扰。

### 8.2 实验设置
```text
default池：正常请求，稳定并发32
isolated池：高压请求，并发128 + 长prompt
```

### 8.3 关键指标
- default池的p95/p99是否受影响
- 不同池的请求分布
- 池间资源利用率差异

### 8.4 预期结论
资源池隔离不仅是路由隔离，而且能降低多租户noisy-neighbor对延迟的影响。

## 9. 实验6：综合剧本实验
### 9.1 目的
把降容、热点、故障、恢复放到一个真实端到端流程里展示。

### 9.2 时间线
```
0-30s：5个真实vLLM-Ascend后端正常服务
30s：对npu3降容 10 → 1
60s：向npu4注入长prompt压力，制造热点
90s：停止npu5后端，模拟故障
120s：恢复npu5
150s：恢复npu3 capacity 1 → 10
180s：结束
```

### 9.3 关键指标
- 全过程成功率
- p95/p99时间序列
- 每个后端请求占比
- 每个后端effective_weight
- 每个后端phase
- 每个后端vLLM metrics

### 9.4 预期结论
系统在复杂场景下仍能保持稳定，动态调度、故障恢复、资源隔离等机制协同工作。

## 10. 实验7：smoothStep参数敏感性实验
### 10.1 目的
证明smoothStep参数选择合理。

### 10.2 实验设置
```text
smoothStep = 0.1 / 0.25 / 0.5 / 1.0
```

### 10.3 关键指标
- 收敛速度
- 平滑性
- 稳定性

### 10.4 预期结论
| smoothStep | 现象 |
|------------|------|
| 0.1 | 很平滑，但收敛慢 |
| 0.25 | 平滑和收敛折中 |
| 0.5 | 收敛快，但可能抖动 |
| 1.0 | 直接跳变，退化成硬切流 |

## 11. 算法优化建议
### 11.1 loadScore拆分
```go
// 区分routing_score和desired_weight
routingScore = a * normalizedInflight + b * normalizedQueueDepth + c * latencyEWMA + d * kvCacheUsage
```

### 11.2 effective_weight上下限
```go
if !healthy || phase == drained || capacity == 0 {
    desiredWeight = 0
} else if phase == active || phase == recovering {
    desiredWeight = capacity * max(minHeadroom, headroom)
}
```

### 11.3 smoothStep自适应
根据负载变化幅度动态调整smoothStep。

### 11.4 P2C带放回采样
两次候选采样使用独立带放回抽样，避免 2 后端或小规模候选池中因排除逻辑导致 P2C 退化。若两次采到同一后端，直接使用该后端；采到不同后端时再按 loadScore 比较。

### 11.5 增加hysteresis
避免状态抖动：
```text
连续N次健康才recovering
连续M次失败才unhealthy
恢复后最短观察窗口
权重变化最小阈值
```

## 12. 预期结论与评分对齐
### 12.1 技术完整性
- 实现完整的状态机（active → draining → drained → recovering）
- 支持多资源池隔离
- 健康检查与被动熔断机制

### 12.2 性能优化效果
- 实验1：无明显额外开销
- 实验2：降低热点和尾延迟
- 实验3：capacity变化时平滑迁移
- 实验4：故障自动摘除与slow-start恢复

### 12.3 实用性
- 实验5：多租户隔离支持
- 实验6：真实昇腾NPU验证
- 实验7：参数选择合理

### 12.4 最终展示结论
```text
实验表明，suan-router在正常均衡场景下相比SWRR没有明显额外开销；在异构负载场景下，P2C + 多维headroom能显著降低慢节点流量占比，但需要同时报告QPS和p50折中；在动态降容场景中，capacity从10降至1后，desired_weight立即响应，effective_weight平滑收敛，新请求逐步迁移，在途请求不中断，错误率保持0；在故障恢复场景中，主动健康检查与被动熔断能完成故障摘除，恢复阶段通过slow-start避免流量尖峰；资源池实验验证了多租户请求隔离。整体系统在昇腾910B + vLLM-Ascend真实环境中完成端到端验证，具备工程落地性。
```

## 13. 实验脚本清单
```
scripts/
├── run_experiment1.sh          # 实验1：三组对照
├── run_experiment2_real.sh     # 实验2：真实NPU压力
├── run_experiment3.sh          # 实验3：动态降容
├── run_experiment4.sh          # 实验4：故障恢复
├── run_experiment5_noisy.sh    # 实验5：noisy-neighbor
├── run_experiment6.sh          # 实验6：综合剧本
├── run_smoothstep_experiment.sh # 实验7：参数敏感性
└── README.md                   # 实验运行指南
```

## 14. 指标采集工具
```
bench/
├── collect_metrics.py          # 增强版指标采集器
├── loadgen.py                  # 负载生成器
├── plot_results.py             # 结果绘图器
├── inject_capacity.py          # 容量注入器
└── fake_backend.py             # 模拟后端
```
