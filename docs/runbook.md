# Operation Runbook

本文档用于迁移和复现实验。正式实验必须在 Ascend 机器真实 NPU 上运行，主结论不使用 fake backend 数据。

## 1. 登录与目录

```bash
ssh kunlun-02-act
```

远端仓库：

```text
/home/yijq27/workspace/Track1_fuiglwgfnq_repos
```

CANN/router 容器内仓库：

```text
/workspace/Track1_fuiglwgfnq_repos
```

router 容器：

```text
yijq27-cann851
```

正式 vLLM 后端容器：

```text
yijq27-vllm-qwen15b-3  -> NPU 3, port 9021
yijq27-vllm-qwen15b-4  -> NPU 4, port 9022
yijq27-vllm-qwen15b-5  -> NPU 5, port 9026
yijq27-vllm-qwen15b-6  -> NPU 6, port 9027
yijq27-vllm-qwen15b-7  -> NPU 7, port 9028
```

## 2. 安全规则

- 先看 `npu-smi info`，确认 NPU 3-7 没有非本项目任务。
- 不要停止未知容器，不要杀未知进程。
- 正式故障实验只允许操作 `yijq27-vllm-qwen15b-5`。
- 实验 router 只通过 `scripts/lib_real_npu.sh` 里的 PID 文件清理自己启动的进程。
- 不要使用宽泛 `pkill`、`killall`、`docker rm -f $(...)`。

检查 NPU：

```bash
docker exec yijq27-cann851 bash -lc "npu-smi info"
```

检查实验端口：

```bash
ss -ltnp 2>/dev/null | grep -E ':(8180|8181)\b' || true
```

如果 `8180/8181` 被未知进程占用，不要强杀，先换端口或确认来源。

## 3. 同步代码

本地同步到远端建议不用 `--delete`，避免误删远端实验结果：

```bash
rsync -az --exclude .git ./ \
  kunlun-02-act:/home/yijq27/workspace/Track1_fuiglwgfnq_repos/
```

远端如需同步到容器，当前环境已经通过 `/workspace` 挂载；如果迁移机器没有挂载，需要重新创建 CANN 容器并挂载项目目录。

## 4. CANN 容器

创建 8 卡 CANN 容器参考：

```bash
docker run -itd \
  --name yijq27-cann851 \
  --privileged \
  --net=host \
  --ipc=host \
  --device /dev/davinci0 \
  --device /dev/davinci1 \
  --device /dev/davinci2 \
  --device /dev/davinci3 \
  --device /dev/davinci4 \
  --device /dev/davinci5 \
  --device /dev/davinci6 \
  --device /dev/davinci7 \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -v /home/yijq27/workspace/Track1_fuiglwgfnq_repos:/workspace/Track1_fuiglwgfnq_repos \
  -v /home/yijq27/workspace/bin:/workspace/bin \
  -v /home/yijq27/workspace/logs:/workspace/logs \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  swr.cn-south-1.myhuaweicloud.com/ascendhub/cann:8.5.1-910b-ubuntu22.04-py3.11 \
  /bin/bash
```

构建 router：

```bash
docker exec yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  go test ./... &&
  go build -o /workspace/bin/suan-router ./cmd/router
'
```

## 5. 模型

正式实验模型：

```text
Qwen/Qwen2.5-1.5B-Instruct
```

本机路径：

```text
/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct
```

下载示例：

```bash
docker run --rm --entrypoint bash \
  -e HF_HOME=/models/.cache \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -v /home/yijq27/workspace/models:/models \
  quay.io/ascend/vllm-ascend:v0.18.0rc1 \
  -lc 'hf download Qwen/Qwen2.5-1.5B-Instruct \
    --local-dir /models/Qwen2.5-1.5B-Instruct \
    --max-workers 4'
```

## 6. vLLM-Ascend 后端

已有容器时先检查，不要重复创建：

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep 'yijq27-vllm-qwen15b'
```

单卡启动模板：

```bash
MODEL_DIR=/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct
IMAGE=quay.io/ascend/vllm-ascend:v0.18.0rc1
NPU=3
PORT=9021

docker run -itd \
  --name yijq27-vllm-qwen15b-${NPU} \
  --restart unless-stopped \
  --privileged \
  --net=host \
  --ipc=host \
  --device /dev/davinci${NPU} \
  --device /dev/davinci_manager \
  --device /dev/devmm_svm \
  --device /dev/hisi_hdc \
  -e ASCEND_RT_VISIBLE_DEVICES=${NPU} \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -v "$MODEL_DIR":"$MODEL_DIR":ro \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  "$IMAGE" \
  bash -lc "vllm serve $MODEL_DIR \
    --host 0.0.0.0 \
    --port ${PORT} \
    --served-model-name qwen2.5-1.5b-instruct \
    --tensor-parallel-size 1 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.75"
```

端口映射：

```text
NPU 3 -> 9021
NPU 4 -> 9022
NPU 5 -> 9026
NPU 6 -> 9027
NPU 7 -> 9028
```

健康检查：

```bash
for p in 9021 9022 9026 9027 9028; do
  printf "%s " "$p"
  curl -fsS http://127.0.0.1:$p/health >/dev/null && echo ok || echo fail
done
```

模型名检查：

```bash
curl -fsS http://127.0.0.1:9021/v1/models
```

## 7. 运行正式实验

一键完整重跑：

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

单独重跑：

```bash
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment1.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment2_real.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment3.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment4.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment5_noisy.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment6.sh
RESULTS_DIR=bench/results/real-npu-manual scripts/run_smoothstep_experiment.sh
```

实验含义：

| 实验 | 脚本 | 真实资源 |
|---|---|---|
| exp1 | `run_experiment1.sh` | direct、5 后端 `swrr/p2c/balanced` |
| exp2 | `run_experiment2_real.sh` | NPU3 direct 长 prompt 压力 + 5 后端测量流量 + vLLM/router 指标采样 |
| exp3 | `run_experiment3.sh` | NPU3 capacity 10->1->10 |
| exp4 | `run_experiment4.sh` | 只 stop/start `yijq27-vllm-qwen15b-5` |
| exp5 | `run_experiment5_noisy.sh` | default=NPU3/4，isolated=NPU5/6/7 |
| exp6 | `run_experiment6.sh` | 综合剧本 |
| exp7 | `run_smoothstep_experiment.sh` | smoothStep 0.1/0.25/0.5/1.0 |

## 8. 结果文件

最新正式结果：

```text
bench/results/real-npu-20260627021640/
```

重点文件：

```text
analysis/real_npu_summary.csv
analysis/real_npu_summary.md
exp2-real-hotspot-*-metrics.csv
snapshots/*.state.json
snapshots/*.metrics.txt
npu-smi-before.txt
npu-smi-after.txt
```

重新生成汇总：

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-20260627021640 \
  --output-dir bench/results/real-npu-20260627021640/analysis
```

exp2 单独重跑后的指标驱动结果目录：

```text
bench/results/real-npu-metrics-exp2-20260627203104/
```

该实验的 baseline 是 `config/router.qwen15b-5backends-swrr.json`，不配置 `metrics_url`，只按静态 capacity 做 SWRR；`config/router.qwen15b-5backends-p2c.json` 和 `config/router.qwen15b-5backends-balanced.json` 配置 vLLM `/metrics`，用于验证 `num_requests_running` 等真实指标触发避热点。

## 9. 停止与清理

安全停止本项目实验 router：

```bash
docker exec yijq27-cann851 bash -lc '
  pidfile=/tmp/suan-router-real-experiment.pid
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile")
    if [ -n "$pid" ] && ps -p "$pid" -o args= | grep -q /workspace/bin/suan-router; then
      kill "$pid"
    fi
    rm -f "$pidfile"
  fi
'
```

确认端口清空：

```bash
ss -ltnp 2>/dev/null | grep -E ':(8180|8181)\b' || true
```

确认故障实验后 NPU5 已恢复：

```bash
docker start yijq27-vllm-qwen15b-5 >/dev/null 2>&1 || true
curl -fsS http://127.0.0.1:9026/health
```

## 10. 开发夹具

`bench/fake_backend.py` 和 `scripts/run_router_microbench.sh` 只用于开发期确定性验证，不写入正式赛题主结论。正式报告只引用真实 NPU 3-7 的实验数据。
