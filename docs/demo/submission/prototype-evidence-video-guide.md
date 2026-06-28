# 证据型原型演示视频说明

适用文件：`prototype-demo-final.mp4`

这版视频的定位是“真实运行证据演示”，不是 PPT 朗读。画面直接展示终端输出风格的真实实验文件、router 状态快照、metrics 快照、NPU 状态文本和实验对比图表，并配旁白讲清楚“问题 -> 方案 -> 证据”。

## 视频主线

1. 问题：真实 NPU 集群状态会动态变化，静态轮询看不到热点。
2. 方案：suan-router 从 health、capacity、inflight、vLLM metrics 和资源池信息计算动态权重。
3. 证据：用真实 Ascend NPU 3-7 的实验文件证明热点避让、平滑降容、故障恢复、资源池隔离和 7B 泛化。
4. 交付：视频、字幕、旁白文本、PPT 辅助材料和真实实验数据均已归档。

## 镜头与数据源

| 镜头 | 展示内容 | 真实数据源 |
|---|---|---|
| 1 | 证据文件清单、state 快照数量、npu-smi 文件 | `bench/results/formal/`、`docs/demo/submission/` |
| 2 | NPU3-7 的 npu-smi 状态和热点问题 | `bench/results/formal/system/npu-smi-before.txt` |
| 3 | router 输入信号和调度闭环 | router 管理面设计、`/admin/state`、`/metrics` |
| 4 | exp2 热点避让 metrics 与图表 | `exp2-hotspot-load/exp2-p2c-end.metrics.txt`、`real_npu_summary.csv` |
| 5 | exp2 router 状态快照 | `exp2-hotspot-load/exp2-p2c-end.state.json` |
| 6 | exp3 capacity 10->1->10 平滑迁移 | `exp3-dynamic-capacity/exp3-stable-down.state.json`、`real_npu_summary.csv` |
| 7 | exp4 故障摘除和恢复 | `exp4-failure-recovery/exp4-stable-fail.state.json`、`exp4-stable-fail.metrics.txt` |
| 8 | exp5 资源池隔离 | `exp5-pool-isolation/exp5-running.state.json`、`real_npu_summary.csv` |
| 9 | exp8 Qwen2.5-7B 泛化 | `exp8-qwen7b-hotspot/snapshots/exp8-qwen7b-p2c-end.state.json`、`real_npu_summary.csv` |
| 10 | 提交材料索引 | `docs/demo/submission/`、`bench/results/formal/analysis/` |

## 重新生成

```bash
python3 scripts/generate_final_demo_video.py
```

生成过程只读取本地真实实验文件，不连接远程机器，不启动 router，不创建容器，不占用 NPU。

输出文件：

- `prototype-demo-final.mp4`：最终证据型原型演示视频
- `prototype-demo-final.srt`：字幕
- `prototype-demo-final-narration.txt`：旁白文本
- `prototype-demo-final-cover.png`：封面

## 录制与讲解要求

- 不要录完整实验重跑过程，时间太长。
- 不要展示密码、令牌、远程登录凭据或其他用户任务。
- 如果需要现场补充终端，只展示安全命令，例如 `cat bench/results/formal/analysis/real_npu_summary.md`、`jq` 查看已归档 state 快照、`grep` 查看 metrics 快照。
- PPT 只作为辅助讲解材料，不作为视频主体。
