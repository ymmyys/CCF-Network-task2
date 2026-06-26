# 实验设计改进总结

## 一、主要改进点

### 1. 统一实验时间线
- 修正了实验3的时间线不一致问题
- 标准化为：0-30s正常 → 30s降容 → 30-80s观察 → 80s恢复 → 80-120s观察
- 明确了每秒窗口请求数、滑动窗口请求数等指标定义

### 2. 增强指标采集
创建了 `bench/collect_metrics.py`，采集以下关键指标：
- **TTFT** (Time to First Token)：首token延迟
- **TPOT** (Time Per Output Token)：每token延迟
- **queue time**：排队时间
- **inference time**：推理时间
- **prefill time**：预填充时间
- **decode time**：解码时间
- **per-backend request rate**：每个后端每秒请求数
- **per-backend inflight**：每个后端在途请求数
- **effective_weight / desired_weight**：权重变化
- **phase**：后端状态

### 3. 三组对照实验（实验1）
```text
A. direct-to-vLLM：不经过router，测单后端原始性能，只作为参考
B. router + swrr：证明router基础转发开销
C. router + p2c_smooth_wrr：证明动态调度额外开销
```

### 4. 真实NPU异构负载实验（实验2）
- 使用真实长prompt请求制造KV Cache压力
- 对某个后端施加背景压力，模拟真实热点
- 补充了fake backend实验，便于确定性复现

### 5. 综合剧本实验（实验6）
把降容、热点、故障、恢复放到一个真实端到端流程里展示：
```
0-30s：5个真实vLLM-Ascend后端正常服务
30s：对npu3降容 10 → 1
60s：向npu4注入长prompt压力，制造热点
90s：停止npu5后端，模拟故障
120s：恢复npu5
150s：恢复npu3 capacity 1 → 10
180s：结束
```

### 6. smoothStep参数敏感性实验（实验7）
测试不同smoothStep值：
```text
smoothStep = 0.1 / 0.25 / 0.5 / 1.0
```
证明0.25是平滑性和收敛速度的合理折中。

### 7. 资源池隔离noisy-neighbor实验（实验5）
- default池：正常请求，稳定并发32
- isolated池：高压请求，并发128 + 长prompt
- 证明资源池隔离能防止多租户干扰

## 二、新增实验脚本

### 实验1：三组对照
```bash
./scripts/run_experiment1.sh
```

### 实验2：真实NPU压力
```bash
./scripts/run_experiment2_real.sh
```

### 实验5：noisy-neighbor
```bash
./scripts/run_experiment5_noisy.sh
```

### 实验6：综合剧本
```bash
./scripts/run_experiment6.sh
```

### 实验7：参数敏感性
```bash
./scripts/run_smoothstep_experiment.sh
```

## 三、算法优化建议

### 1. loadScore拆分
```go
// 区分routing_score和desired_weight
routingScore = a * normalizedInflight + b * normalizedQueueDepth + c * latencyEWMA + d * kvCacheUsage
```

### 2. effective_weight上下限
```go
if !healthy || phase == drained || capacity == 0 {
    desiredWeight = 0
} else if phase == active || phase == recovering {
    desiredWeight = capacity * max(minHeadroom, headroom)
}
```

### 3. smoothStep自适应
根据负载变化幅度动态调整smoothStep。

### 4. P2C带放回采样
两次候选采样使用独立带放回抽样，避免小规模候选池中因排除逻辑导致 P2C 退化。

### 5. 增加hysteresis
避免状态抖动：
```text
连续N次健康才recovering
连续M次失败才unhealthy
恢复后最短观察窗口
权重变化最小阈值
```

## 四、预期结论表达

### 原表达
> 这个系统完整实现了赛题要求。

### 改进后表达
```text
实验表明，suan-router在正常均衡场景下相比SWRR没有明显额外开销；在异构负载场景下，P2C + 多维headroom能显著降低慢节点流量占比，但需要同时报告QPS和p50折中；在动态降容场景中，capacity从10降至1后，desired_weight立即响应，effective_weight平滑收敛，新请求逐步迁移，在途请求不中断，错误率保持0；在故障恢复场景中，主动健康检查与被动熔断能完成故障摘除，恢复阶段通过slow-start避免流量尖峰；资源池实验验证了多租户请求隔离。整体系统在昇腾910B + vLLM-Ascend真实环境中完成端到端验证，具备工程落地性。
```

## 五、关键验证点

1. **降容收敛时间** < 10s
2. **恢复收敛时间** < 15s
3. **降容期间错误率** = 0%
4. **降容期间p99抖动** < 20%
5. **在途请求中断数** = 0
6. **故障检测时间** < 5s
7. **恢复后slow-start时间** > 10s

## 六、实验优先级

按重要程度排序：
1. ✅ 统一动态降容实验时间线
2. ✅ 补p95/p99/TTFT/TPOT/queue time指标
3. ✅ 补direct-to-vLLM/router+swrr/router+p2c三组对照
4. ✅ 把fake backend异构实验升级为真实NPU压力实验
5. ✅ 资源池隔离增加noisy-neighbor测试
6. ✅ 增加smoothStep参数敏感性实验
7. ✅ 增加综合剧本实验

## 七、下一步行动

1. 运行所有实验，收集数据
2. 生成对比图表
3. 撰写实验报告
4. 准备答辩材料
