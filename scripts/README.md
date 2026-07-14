# 实验脚本

本目录分为两类脚本：

- 正式真实 NPU 实验：使用 Ascend NPU 3-7，可进入报告主结论。
- 开发夹具：使用 fake backend 或临时端口，只用于调试调度逻辑，不进入正式主结论。

## 现场可视化

```bash
python3 scripts/serve_demo_dashboard.py --admin http://127.0.0.1:8181 --port 8787
```

打开 `http://127.0.0.1:8787/`。详细说明见 [`docs/demo/live-console.md`](../docs/demo/live-console.md)。

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
| exp2 真实热点压力 | `run_experiment2_real.sh` | `exp2-real-hotspot-*.csv`, `exp2-real-hotspot-*-metrics.csv` |
| exp3 动态 capacity | `run_experiment3.sh` | `exp3-real-capacity-p2c.csv` |
| exp4 真实故障恢复 | `run_experiment4.sh` | `exp4-real-failure-p2c.csv` |
| exp5 资源池隔离 | `run_experiment5_noisy.sh` | `exp5-real-default.csv`, `exp5-real-isolated.csv` |
| exp6 综合剧本 | `run_experiment6.sh` | `exp6-real-comprehensive.csv` |
| exp7 smoothStep | `run_smoothstep_experiment.sh` | `exp7-real-ss*.csv` |
| exp8 7B 泛化热点压力 | `run_experiment8_qwen7b_real.sh` | `exp8-qwen7b-hotspot-*.csv`, `exp8-qwen7b-hotspot-*-metrics.csv` |

所有正式脚本都会加载 `scripts/lib_real_npu.sh`：

- 启动 MUTT 时写入 `/tmp/mutt-real-experiment.pid`；
- 清理时只停止 PID 文件记录且命令行为 `/workspace/bin/mutt` 的进程；
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

8 卡现场演示额外使用 `yijq27-vllm-qwen15b-0/1/2`（端口 `9018/9019/9020`），Router 配置为 `config/router.qwen15b-8backends-p2c.json`。这些新增容器不属于既有正式实验脚本的默认资源集合。

exp8 会临时使用 Qwen2.5-7B 后端：

```text
yijq27-vllm-qwen7b-3 -> 9121
yijq27-vllm-qwen7b-4 -> 9122
yijq27-vllm-qwen7b-5 -> 9126
yijq27-vllm-qwen7b-6 -> 9127
yijq27-vllm-qwen7b-7 -> 9128
```

实验完成后应删除这些 `qwen7b` 容器释放 NPU。

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
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

输出：

```text
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
```

该汇总器只读取 `exp*-real-*.csv` 这类真实实验文件，不读取 fake backend 文件。

exp2 的 `*-metrics.csv` 会额外记录：

```text
num_requests_running
num_requests_waiting
kv_cache_usage
router_remote_utilization
router_queue_depth
router_kv_cache_usage
```

SWRR 配置故意不配置 `metrics_url`，作为静态基线；P2C 和 balanced P2C 配置 vLLM `/metrics`，用于验证实时负载感知。

exp8 使用 `config/router.qwen7b-5backends-*.json`，验证同一热点避让逻辑在 Qwen2.5-7B-Instruct 上是否仍成立。

## 原型录屏脚本

`recordrealrun.sh` 用于在 VS Code 已连接远程 Ascend CANN 容器时录制原型展示。它会真实构建并启动一个临时 router，再通过 router 发起 OpenAI-compatible 推理请求，因此可以直接展示项目架构、运行过程和指标证据。

推荐在远程容器终端中执行：

```bash
cd /workspace/Track1_fuiglwgfnq_repos
bash scripts/recordrealrun.sh
```

脚本展示内容：

- MUTT 架构：client -> router -> NPU 3-7 上的 5 个 vLLM-Ascend 后端；
- `cmd`、`internal/router`、`config` 代码入口和调度关键实现位置；
- 5 个真实后端 `/health` 与 `npu-smi info`；
- `go build` 当前 router，并生成临时 `18180/18181` 配置；
- 通过 `bench/loadgen.py` 发起真实推理请求；
- 请求数、错误数、p50/p95/p99、后端分布、`/admin/state` 与 `/metrics`；
- 退出时只清理自己启动的 router，不停止 vLLM 后端容器。

录制前需要确认这些后端容器已启动并健康：

```text
yijq27-vllm-qwen15b-3 -> 9021
yijq27-vllm-qwen15b-4 -> 9022
yijq27-vllm-qwen15b-5 -> 9026
yijq27-vllm-qwen15b-6 -> 9027
yijq27-vllm-qwen15b-7 -> 9028
```

录制结束后，外层流程应停止这些后端容器释放 NPU：

```bash
docker stop \
  yijq27-vllm-qwen15b-3 \
  yijq27-vllm-qwen15b-4 \
  yijq27-vllm-qwen15b-5 \
  yijq27-vllm-qwen15b-6 \
  yijq27-vllm-qwen15b-7
```

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
