# bench 实验工具

本目录包含 router 实验使用的负载发生器、指标采集器、绘图辅助工具和结果汇总脚本。

## 正式真实 NPU 流程

在远程主机工作区运行实验：

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

生成汇总：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

已入库的正式结果按实验编号整理在：

```text
bench/results/formal/
```

## 关键脚本

| 文件 | 用途 |
|---|---|
| `loadgen.py` | OpenAI-compatible 负载发生器 |
| `collect_metrics.py` | vLLM `/metrics` 与 router `/admin/state` 采样器 |
| `generate_summary.py` | 真实 NPU CSV 汇总和窗口统计 |
| `plot_results.py` | 可选的延迟/QPS 绘图脚本 |
| `inject_capacity.py` | 管理 API capacity 事件注入脚本 |
| `fake_backend.py` | 仅用于开发夹具，不作为正式证据 |

## 基线定义

正式对比中：

- 基线：`scheduler.mode=swrr`，使用 `config/router.qwen15b-5backends-swrr.json`，故意不配置 `metrics_url`；
- 改进组：`scheduler.mode=p2c_smooth_wrr`，配置 vLLM `/metrics`；
- 均衡改进组：`p2c_smooth_wrr` 加 `balanced_p2c=true`，同样配置 vLLM `/metrics`。

fake backend 仅用于本地确定性测试；正式报告结论只使用真实 Ascend NPU 3-7 数据。
