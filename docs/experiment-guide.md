# Legacy Experiment Guide

本文件只保留为历史入口。当前正式操作手册已经迁移到 [`runbook.md`](runbook.md)，实验计划见 [`experiments.md`](experiments.md)，最终报告见 [`final-report.md`](final-report.md)。

旧版实验指南包含 fake backend、宽泛进程清理命令、两后端示例和早期端口配置，不再作为赛题提交或远程复现实验依据。正式实验必须使用：

- 真实 Ascend NPU 3-7；
- 容器 `yijq27-cann851` 内的 `/workspace/Track1_fuiglwgfnq_repos`；
- vLLM 后端 `yijq27-vllm-qwen15b-3` 到 `yijq27-vllm-qwen15b-7`；
- router 端口 `8180`、管理端口 `8181`；
- `scripts/run_real_npu_suite.sh` 或单项 `scripts/run_experiment*.sh`；
- `scripts/lib_real_npu.sh` 的 PID 安全清理逻辑。

常用入口：

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

单独验证实时负载感知热点避让：

```bash
RESULTS_DIR=bench/results/real-npu-metrics-exp2-$(date +%Y%m%d%H%M%S) \
EXP2_DURATION=60 \
EXP2_PRESSURE_CONCURRENCY=32 \
  scripts/run_experiment2_real.sh

python3 bench/generate_summary.py \
  --results-dir "$RESULTS_DIR" \
  --output-dir "$RESULTS_DIR/analysis"
```

注意：不要使用宽泛 `pkill` 或停止非本项目容器。故障实验只允许操作 `yijq27-vllm-qwen15b-5`。
