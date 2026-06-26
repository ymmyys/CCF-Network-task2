# 动态降容实验标准化时间线

## 实验设置
- 总时长：120秒
- 并发数：32
- 后端：5个真实vLLM后端 (NPU 3-7)
- 模型：Qwen2.5-1.5B-Instruct

## 时间线
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

## 关键指标采集
每秒采集以下指标：
1. **per-backend request rate**：每个后端每秒请求数
2. **per-backend inflight**：每个后端在途请求数
3. **effective_weight / desired_weight**：权重变化
4. **p50/p95/p99 latency**：延迟分布
5. **TTFT**：首token延迟（从vLLM /metrics）
6. **TPOT**：每token延迟（从vLLM /metrics）
7. **queue time**：排队时间（从vLLM /metrics）
8. **error rate**：错误率

## 预期结论
- 降容收敛时间 < 10s
- 恢复收敛时间 < 15s
- 降容期间错误率 = 0%
- 降容期间p99抖动 < 20%
- 在途请求中断数 = 0