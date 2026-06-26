# 昇腾NPU推理集群动态负载感知调度系统 — 实验验证与算法优化报告

## 一、项目背景

本项目的赛题是 **大模型推理算力资源动态负载感知调度**（Track 2）。要求设计并实现一个动态负载感知的调度器，用于优化昇腾NPU推理集群的请求分配，核心挑战包括后端负载不均、容量动态变化、节点故障和多租户隔离。

## 二、系统架构

```
客户端请求
    │
    ▼
┌─────────────────────────────────┐
│  suan-router (Go, :8180/:8181)  │
│  · P2C + 平滑加权轮询           │
│  · 动态目标权重 = capacity×headroom │
│  · 显式状态机 (active→draining→drained→recovering) │
│  · 健康检查 + 被动熔断           │
│  · 多资源池隔离                  │
└──────┬──────┬──────┬──────┬──────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
   vLLM-Ascend 后端 (NPU 3/4/5/6/7)
   模型: Qwen2.5-1.5B-Instruct
```

### 核心机制

1. **P2C + 平滑加权轮询**：每次从候选池中按有效权重独立采样两个后端，比较二者的 loadScore，选择负载更低的节点
2. **动态目标权重**：`desiredWeight = capacity × headroom`，其中 `headroom` 综合 NPU 利用率、队列深度、本地 inflight、KV Cache 占用和延迟 EWMA
3. **平滑降权**：`effectiveWeight += (desiredWeight - effectiveWeight) × smoothStep`，避免流量突变
4. **显式状态机**：`active → draining → drained → recovering → active`
5. **健康检查与被动熔断**：定期探测 `/health` 端点，连续失败 3 次触发被动熔断（10s）
6. **资源池隔离**：通过 `X-Resource-Pool` 请求头实现多租户隔离

### 关键数据结构

```go
type Backend struct {
    id              string
    capacity        float64        // 管理面意图
    desiredWeight   float64        // 目标权重 = capacity × headroom
    effectiveWeight float64        // 实际权重（平滑过渡）
    healthy         bool
    phase           BackendPhase   // active/draining/drained/recovering
    passiveUntil    time.Time      // 被动熔断到期时间
    remoteUtilization float64
    queueDepth      float64
    kvCacheUsage    float64
    latencyEWMA     float64
    inflight        int64
}
```

## 三、实验设计

### 实验环境

- **硬件**：昇腾 910B NPU × 8（主机 kunlun-02-act）
- **软件**：vLLM-Ascend v0.18.0rc1，容器化部署（每卡一容器）
- **模型**：Qwen2.5-1.5B-Instruct
- **Router**：suan-router（Go 实现，运行在 CANN 开发容器 `yijq27-cann851` 内）

### 七组实验

| 实验 | 目的 | 对比对象 | 关键指标 |
|------|------|----------|----------|
| exp1 | 证明动态调度无明显额外开销 | direct 单后端参考 / swrr / p2c | QPS, p50/p95/p99 |
| exp2 | 验证慢节点避让能力，并记录吞吐/延迟代价 | swrr vs p2c（慢后端300ms） | 慢节点占比, QPS, p50/p95/p99 |
| exp3 | 验证容量平滑迁移 | capacity 10→1→10 | effective_weight, 占比, 错误率 |
| exp4 | 证明故障自动摘除与恢复 | docker stop/start | 摘除时间, 错误率 |
| exp5 | 验证多租户隔离 | default vs isolated 池 | 池间影响 |
| exp6 | 综合剧本探索 | 降容+热点+故障+恢复 | 全过程稳定性 |
| exp7 | 验证参数选择的合理折中 | smoothStep=0.1/0.25/0.5/1.0 | 收敛速度, 平滑性 |

### 证据链与表述边界

- 核心支撑实验为 exp1、exp3、exp4-fix、exp5 和 exp7-5b，分别覆盖低调度开销、容量动态迁移、故障摘除、资源池隔离和 `smoothStep` 参数敏感性。
- exp2 证明 P2C 能识别并避让慢节点，但当前策略偏向激进避慢，会牺牲 QPS 和 p50；不能表述为 P2C 在所有指标上全面优于 SWRR。
- exp6 目前作为综合剧本探索，不作为核心证据使用；后续需要拆分 transition/stable 窗口后再纳入主结论。
- direct-to-vLLM 是单后端原始性能参考，用来帮助理解 vLLM 基准，不与多后端 router 结果做严格横向优劣比较。

## 四、工作历程

### 第一阶段：初始实验完成

完成了 exp1-exp7 的初始运行，但发现以下问题：

### 第二阶段：问题诊断与修复（核心工作）

#### 问题 1：exp4 故障摘除不彻底

**现象**：docker stop npu5 后，故障稳定期（35-90s）npu5 仍有 11.7% 的请求分配。

**根因分析**：

进入 `backend.go:219` 的 `schedulingState()` 方法：

```go
// 旧代码
func (b *Backend) schedulingState(now time.Time) (float64, bool) {
    ...
    if capacity <= 0 || phase == PhaseDrained {
        return 0, false
    }
    return weight, healthy && weight > 0  // ← 问题所在
}
```

当 `healthy = false` 时，`ok` 返回 `false`（正确，后端被跳过）。但当后端刚被 docker stop、健康检查尚未运行时，`healthy` 仍为 `true`，此时 `effectiveWeight` 从 10 平滑下降过程中仍大于 0，`ok` 返回 `true`，后端仍可被调度。

**修复**：

```go
// 新代码
func (b *Backend) schedulingState(now time.Time) (float64, bool) {
    ...
    if capacity <= 0 || phase == PhaseDrained {
        return 0, false
    }
    // 新增：健康检查失败或被动熔断中，立即不可调度
    if !healthy || now.Before(passiveUntil) {
        return 0, false
    }
    if weight <= 0 {
        return 0, false
    }
    return weight, true
}
```

**修复效果**：见章节五「实验结果」。

---

#### 问题 2：exp7 P2C 采样退化

**现象**：2 后端场景下，降容 npu3 10→1 后，npu3 实际占比约 33%，远高于理论目标 9.09%。

**根因分析**：

进入 `scheduler.go:92` 的 `pickP2CLocked()` 方法：

```go
// 旧代码
first := p.weightedCandidate(candidates, total, nil)
second := p.weightedCandidate(candidates, total-first.weight, first.slot)
//  ↑ total-first.weight 使第二次采样的总权重减小
if second.slot == nil {
    second = p.bestCurrentCandidate(candidates, first.slot)
}
// ↑ 2后端时 first.slot=唯一另一后端，exclude后 second 采不到，
//    fallback 到 bestCurrentCandidate，实际两个候选是同一个后端
//   P2C 退化为单采样
```

P2C 在只有 2 个后端时退化：第二次采样使用了 `total-first.weight` 并排除 first，导致只有 first 自己可被采样。当两个后端权重相同时，first 本身权重占一半，第二次采样总权重也只有一半，但排除 first 后采不到 second，fallback 到 `bestCurrentCandidate` 选到的还是同一个后端。P2C 完全退化，无法利用 effective_weight 差异消除热点。

**修复**：改为两次独立的带放回采样（weighted sample with replacement）：

```go
// 新代码
first := p.weightedCandidate(candidates, total, nil)
second := p.weightedCandidate(candidates, total, nil)
// ↑ 两次独立采样，total 不变，第二次不排除 first

// 选到同一个 → 直接使用
if first.slot == second.slot {
    return p.commitPick(first.slot, total), nil
}
// 两个不同 → 用 loadScore 比较选更优的
winner := p.betterP2CCandidate(first, second)
return p.commitPick(winner.slot, total), nil
```

同时移除不再使用的 `bestCurrentCandidate()` 方法。

**对 exp7 的影响**：原 2 后端场景被迫改为 5 后端（因为 2 端时 P2C 采样到同一后端的概率为 50%，两个不同后端比较时 effective_weight 差异被正确利用，但 same 分支直接使用无比较）。5 后端时 same 概率为 `sum(p_i²)` ≈ 20%，comparison 分支能有效利用 loadScore。

---

#### 问题 3：smoothStep 实验统计口径混乱

**现象**：原 exp7 混用了降容后整个阶段（含 transition 和 stable 窗口），导致降容后占比虚高（33% vs 理论 9.09%）。

**修复**：
1. 统一使用 5 后端场景（理论目标明确：`1/(1+10×4) = 2.44%`）
2. 拆分统计窗口：`pre_window(0-29s)` → `transition_down(30-34s)` → `stable_down(35-60s)`
3. 仅用 `stable_down` 计算降容后稳定占比

---

## 五、实验结果

### exp1：正常均衡场景（三组对照）

| 组别 | 请求 | QPS | p50 | p95 | p99 | 错误 |
|------|------|-----|-----|-----|-----|------|
| direct-to-vLLM (1后端) | 8,081 | 134.68 | 238.80ms | 285.49ms | 308.49ms | 0 |
| router + swrr (2后端) | 14,057 | 234.28 | 134.87ms | 151.23ms | 195.68ms | 0 |
| router + p2c_smooth_wrr | 14,038 | 233.97 | 134.80ms | 153.24ms | 199.06ms | 0 |

**结论**：p2c_smooth_wrr 相比 swrr，QPS 基本持平，p50 几乎一致，p95 增加约 2ms，p99 差约 3.4ms（约 1.7%），说明动态调度在均衡场景下无明显额外开销。direct-to-vLLM 是单后端参考，不与 2 后端 router 结果直接比较。

---

### exp2：异构负载场景（重跑 ✅）

**设置**：fast backend = vLLM npu3（真实），slow backend = fake_backend（真实 sleep 300ms，利用率 90%）

| 调度器 | 请求 | fast-npu3 | slow-fake | p50 | p95 | p99 |
|--------|------|-----------|-----------|-----|-----|-----|
| swrr | 8,826 | 51.1% | **48.9%** | 150.4ms | **303.7ms** | **304.8ms** |
| p2c_smooth_wrr | 7,725 | **100%** | **0%** | 251.4ms | 285.2ms | 300.4ms |

**结论**：P2C 通过 loadScore 比较（inflight/latencyEWMA/queueDepth），将慢后端流量从 48.9% 降到 0%，证明慢节点避让能力成立。但该策略在本实验中较激进，QPS 从 147 降到 129，p50 从 150.4ms 升到 251.4ms；因此 exp2 不证明 P2C 全面优于 SWRR，而是说明后续可加入 `p2c_balanced` 一类策略，在慢节点保留少量受控流量以改善吞吐和中位延迟折中。

---

### exp3：动态降容场景（核心实验 ⭐）

**设置**：5 后端，第 30s 降容 npu3 10→1，第 80s 恢复

| 指标 | 数值 |
|------|------|
| 总请求 | 29,905 |
| 总错误 | **0** |
| 降容前 npu3 占比 | 20.0% |
| 降容后 npu3 占比 | 2.9%（理论目标 2.44%） |
| 绝对误差 | 0.45pp |
| 降容收敛时间 | ~8s |
| 在途请求中断数 | **0** |

**关键时间点**：

```
秒30  降容事件: npu3=50 (20%)
秒34  npu3=32  ← 开始下降
秒37  npu3=14  ← 快速下降
秒49  npu3=5   ← 稳定低流量
秒80  恢复事件: npu3=5
秒107 npu3=39  ← slow-start
秒117 npu3=50  ← 完全恢复均衡
```

---

### exp4：故障恢复（修复后重跑 ✅）

**设置**：5 后端，第 30s `docker stop npu5`，第 90s `docker start npu5`

| 指标 | 数值 |
|------|------|
| 总请求 | 72,887 |
| 总错误 | 7（0.01%） |
| 故障前 npu5 占比 | 20.0% |
| 故障检测时间 | **2-3s** |
| fail_stable(35-90s) npu5 占比 | **0.03%**（最后少量 in-flight） |
| 恢复后 npu5 占比 | 20.0%（sec 250 起） |

**关键时间点**：

```
sec 30: docker stop npu5
sec 31: npu5 = 55/248 (22.2%)
sec 32: npu5 = 3/220 (1.4%) ← 3 errors (in-flight)
sec 33-89: npu5 = 0  ← 完全摘除
sec 90: docker start npu5
sec 90-249: npu5 = 0  ← vLLM 启动/编译中
sec 250: npu5 = 50/246 (20.3%)  ← 恢复上线
sec 299: npu5 = 50/251 (19.9%)  ← 稳定
```

**说明**：修复前 exp4 中 npu5 故障后仍有 11.7% 流量（因 `schedulingState` 未严格检查 `healthy`）。修复后 sec 33 起完全摘除。

---

### exp5：资源池隔离

| 资源池 | 请求 | 错误 | p50 | p95 | p99 |
|--------|------|------|-----|-----|-----|
| default（正常负载） | 14,109 | **0** | 134.9ms | 159.6ms | 192.4ms |
| isolated（高压负载） | 65,038 | 20,340 | 137.3ms | 180.4ms | 203.7ms |

**结论**：default 池 14,109 请求 0 错误，完全不受 isolated 池高压（128 并发 + 长 prompt）影响。

---

### exp7：smoothStep 参数敏感性（重做 ✅）

**设置**：5 后端，降容 npu3 10→1，理论目标 2.44%

| smoothStep | QPS | 降容前 | 降容后 | 误差 | 抖动 | 评价 |
|------------|-----|--------|--------|------|------|------|
| 0.10 | 247.0 | 20.0% | 5.5% | +3.1pp | 2.5pp | 收敛过慢 |
| **0.25** | **246.3** | **20.0%** | **2.4%** | **-0.04pp** | **2.0pp** | **较优折中** |
| 0.50 | 246.2 | 19.9% | 2.1% | -0.34pp | 1.7pp | 轻微 undershoot |
| 1.00 | 246.6 | 19.9% | 2.5% | +0.06pp | 1.7pp | 近似硬切换 |

**结论**：smoothStep = 0.25 在该 5 后端降容实验中是较优默认折中：降容后实际占比 2.4% 与理论值 2.44% 误差仅 0.04pp，同时保持较平滑的迁移过程。该结论不表述为所有场景下的绝对最优。

---

## 六、代码修改清单

| 文件 | 行数 | 修改内容 |
|------|------|----------|
| `internal/router/scheduler.go` | 92-110 | P2C 采样逻辑：`weightedSampleExcept` → `weightedSampleWithReplacement`，两次独立采样 |
| `internal/router/scheduler.go` | 149-160 | 移除不再使用的 `bestCurrentCandidate()` |
| `internal/router/backend.go` | 219-236 | `schedulingState`：新增 unhealthy/passive 被熔断时立即返回 `(0, false)` |
| `internal/router/scheduler_test.go` | 106-119 | 适配新 P2C 行为：40 次采样中 cool wins > 20 |

**此次会话未修改的部分**：
- 核心 router 算法（p2cLoadScore、recomputeWeight、desiredWeightLocked 等）
- 实验启动脚本（loadgen.py、inject_capacity.py 等）
- 配置文件（除新增 `router-het-*.json`、`router-ss5-*.json` 外）

## 七、数据路径

```
远程主机：kunlun-02-act

原始数据：
  /home/yijq27/workspace/Track1_fuiglwgfnq_repos/bench/results/
  ├── exp1-direct-vllm.csv                8,081 行
  ├── exp1-router-swrr.csv               14,057 行
  ├── exp1-router-p2c.csv                14,038 行
  ├── exp2-het-swrr.csv                   8,826 行（重跑）
  ├── exp2-het-p2c.csv                    7,725 行（重跑）
  ├── exp3-capacity-drop.csv             29,905 行
  ├── exp4-fix.csv                       72,887 行（修复后重跑，300s）
  ├── exp5-pool-default-normal.csv       14,109 行
  ├── exp5-pool-isolated-highload.csv    65,038 行
  ├── exp7-5b-ss0.1.csv                 22,228 行（重做，5后端）
  ├── exp7-5b-ss0.25.csv                22,169 行
  ├── exp7-5b-ss0.5.csv                 22,156 行
  └── exp7-5b-ss1.0.csv                 22,198 行

分析输出：
  analysis-output/all_summary.csv

配置文件：
  config/router-het-p2c.json             异构负载 p2c 配置
  config/router-het-swrr.json            异构负载 swrr 配置
  config/router-ss5-0.1.json             smoothStep 5后端配置
  config/router-ss5-0.25.json
  config/router-ss5-0.5.json
  config/router-ss5-1.0.json

分析脚本：
  bench/analysis_framework.py            标准化分析框架
  bench/generate_summary.py              汇总生成器
  bench/collect_metrics.py               指标采集器
```

## 八、异常与未完成项

| 项目 | 状态 | 说明 |
|------|------|------|
| exp6 综合剧本 | ❌ 未重跑 | 统计窗口需拆分为 pre/transition_down/stable_down/transition_up/stable_up |
| exp2 QPS 下降 | ⚠️ 已知限制 | 本实验中 P2C 将 slow-fake 流量降为 0% 后只剩 1 个 fast 后端，QPS 下降是预期行为。优化方向：p2c_balanced 策略给 slow 后端少量受控流量 |
| exp2 TTFT/TPOT | ❌ 未采集 | vLLM 的 `collect_metrics.py` 已就绪但未与 exp2 同步运行 |
| exp7 原 2 后端数据 | ❌ 废弃 | 因 P2C 退化导致数据不可信，已改用 5 后端重做 |

## 九、可支撑结论

1. ✅ **p2c_smooth_wrr 相比 swrr 无明显额外开销**（exp1: p99 差约 3.4ms，约 1.7%）
2. ✅ **P2C 具备慢节点避让能力**（exp2: slow-fake 从 48.9% 降至 0%，但 QPS/p50 存在折中）
3. ✅ **动态降容平滑迁移零错误**（exp3: 29,905 请求，0 错误，占比从 20% 平滑降至 2.9%）
4. ✅ **故障 2-3s 完成摘除**（exp4-fix: fail_stable npu5 占比 0.03%，72,887 请求仅 7 个错误）
5. ✅ **资源池隔离有效**（exp5: default 池 14,109 请求 0 错误）
6. ✅ **smoothStep = 0.25 是较优默认折中**（exp7: 降容后 2.4% vs 理论 2.44%，误差仅 0.04pp）

## 十、后续深度优化补充

本轮新增两个调度层优化：

- **P2C 同后端高负载重采样**：两次带放回采样命中同一高负载后端时，额外补抽一个候选并按 loadScore 比较，减少高权重热点节点被重复确认的概率。
- **上游错误短暂避让**：新增 `failure_cooloff_duration`，默认 1s。代理错误或 5xx 响应后，后端即使尚未达到被动熔断阈值，也会短暂不可调度，降低故障窗口内继续打坏节点的概率。

微基准使用 fake backend 验证：hot 后端 capacity=100 但延迟 300ms、队列和利用率高；cool 后端 capacity=1 且延迟 50ms。优化前 p99 约 306.71ms，hot 命中 638/667；优化后 p99 约 54.66ms，cool 命中 3,630/3,630。该结果证明调度逻辑优化有效，但不替代真实 NPU 实验。

多模型验证建议：当前 Qwen2.5-1.5B-Instruct 已能支撑主证据链；决赛前建议增加小模型 smoke test 和一个更大模型/TP 模型的轻量 exp1+exp3 复验，用来证明调度能力不依赖单一模型。详细计划见 `docs/optimization-and-validation.md`。
