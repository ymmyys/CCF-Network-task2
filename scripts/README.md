# Experiment Scripts

本目录分为两类脚本：

- 正式真实 NPU 实验：使用 Ascend NPU 3-7，可进入报告主结论。
- 开发夹具：使用 fake backend 或临时端口，只用于调试调度逻辑，不进入正式主结论。

## 正式入口

完整重跑：

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

单独实验：

| 实验 | 脚本 | 输出 |
|---|---|---|
| exp1 均衡基线 | `run_experiment1.sh` | `exp1-real-*.csv` |
| exp2 真实热点压力 | `run_experiment2_real.sh` | `exp2-real-hotspot-*.csv` |
| exp3 动态 capacity | `run_experiment3.sh` | `exp3-real-capacity-p2c.csv` |
| exp4 真实故障恢复 | `run_experiment4.sh` | `exp4-real-failure-p2c.csv` |
| exp5 资源池隔离 | `run_experiment5_noisy.sh` | `exp5-real-default.csv`, `exp5-real-isolated.csv` |
| exp6 综合剧本 | `run_experiment6.sh` | `exp6-real-comprehensive.csv` |
| exp7 smoothStep | `run_smoothstep_experiment.sh` | `exp7-real-ss*.csv` |

所有正式脚本都会 source `scripts/lib_real_npu.sh`：

- 启动 router 时写入 `/tmp/suan-router-real-experiment.pid`；
- 清理时只停止 PID 文件记录且命令行为 `/workspace/bin/suan-router` 的进程；
- 如果 `8180/8181` 被未知进程占用，脚本直接退出；
- 故障实验只停止/启动 `yijq27-vllm-qwen15b-5`。

## 真实环境

正式实验要求这些容器健康：

```text
yijq27-vllm-qwen15b-3 -> 9021
yijq27-vllm-qwen15b-4 -> 9022
yijq27-vllm-qwen15b-5 -> 9026
yijq27-vllm-qwen15b-6 -> 9027
yijq27-vllm-qwen15b-7 -> 9028
```

检查：

```bash
for p in 9021 9022 9026 9027 9028; do
  printf "%s " "$p"
  curl -fsS http://127.0.0.1:$p/health >/dev/null && echo ok || echo fail
done
```

## 结果汇总

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-20260627021640 \
  --output-dir bench/results/real-npu-20260627021640/analysis
```

输出：

```text
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
```

该汇总器只读取 `exp*-real-*.csv` 这类真实实验文件，不读取 fake backend 文件。

## 开发夹具

以下脚本/文件保留用于本地开发，不作为正式赛题主证据：

```text
bench/fake_backend.py
scripts/run_experiment2.sh
scripts/run_router_microbench.sh
config/router.qwen15b-heterogeneous-balanced.json
config/router.qwen15b-heterogeneous-p2c.json
config/router.qwen15b-heterogeneous-swrr.json
```

开发夹具可以验证调度逻辑边界，例如高延迟假后端、确定性 queue depth、非法指标值等。正式报告只引用真实 NPU 3-7 数据。
