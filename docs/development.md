# 开发指南

本项目是面向 OpenAI-compatible vLLM-Ascend 后端的 Go HTTP router。当前 Kunlun-02 开发目标与真实 NPU 实验使用同一套拓扑。

## 当前远程目标

| 项目 | 值 |
|---|---|
| SSH 主机 | `kunlun-02-act` |
| Router 容器 | `yijq27-cann851` |
| 主机工作区 | `/home/yijq27/workspace/Track1_fuiglwgfnq_repos` |
| 容器工作区 | `/workspace/Track1_fuiglwgfnq_repos` |
| 模型 | `Qwen/Qwen2.5-1.5B-Instruct` |
| 模型目录 | `/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct` |
| 7B 泛化模型 | `Qwen/Qwen2.5-7B-Instruct` |
| 7B 模型目录 | `/home/yijq27/workspace/models/Qwen2.5-7B-Instruct` |
| vLLM 镜像 | `quay.io/ascend/vllm-ascend:v0.18.0rc1` |
| Router 数据/管理端口 | `8180` / `8181` |

## 后端拓扑

| 后端 ID | NPU | 端口 | 容器 |
|---|---:|---:|---|
| `qwen15b-npu3` | 3 | 9021 | `yijq27-vllm-qwen15b-3` |
| `qwen15b-npu4` | 4 | 9022 | `yijq27-vllm-qwen15b-4` |
| `qwen15b-npu5` | 5 | 9026 | `yijq27-vllm-qwen15b-5` |
| `qwen15b-npu6` | 6 | 9027 | `yijq27-vllm-qwen15b-6` |
| `qwen15b-npu7` | 7 | 9028 | `yijq27-vllm-qwen15b-7` |

exp8 泛化实验会临时使用 7B 后端：

| 后端 ID | NPU | 端口 | 容器 |
|---|---:|---:|---|
| `qwen7b-npu3` | 3 | 9121 | `yijq27-vllm-qwen7b-3` |
| `qwen7b-npu4` | 4 | 9122 | `yijq27-vllm-qwen7b-4` |
| `qwen7b-npu5` | 5 | 9126 | `yijq27-vllm-qwen7b-5` |
| `qwen7b-npu6` | 6 | 9127 | `yijq27-vllm-qwen7b-6` |
| `qwen7b-npu7` | 7 | 9128 | `yijq27-vllm-qwen7b-7` |

7B 容器只在 exp8 期间启动，结束后删除释放 NPU。

每个后端暴露：

- `/v1/chat/completions` OpenAI-compatible API；
- `/health` 健康检查；
- `/metrics` Prometheus 指标。

## 构建 Router

```bash
ssh kunlun-02-act
docker exec yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  go build -o /workspace/bin/mutt ./cmd/router
'
```

## 手动启动 Router

手动调试时，在 CANN 容器内运行 router：

```bash
docker exec -it yijq27-cann851 bash
cd /workspace/Track1_fuiglwgfnq_repos
/workspace/bin/mutt -config config/router.qwen15b-5backends-p2c.json
```

正式实验优先使用 `scripts/` 下的脚本；这些脚本会写 PID 文件，并且只清理自己启动的 router 进程。

## 验证

检查后端健康：

```bash
for p in 9021 9022 9026 9027 9028; do
  printf "%s " "$p"
  curl -fsS http://127.0.0.1:$p/health >/dev/null && echo ok || echo fail
done
```

检查 router 状态：

```bash
curl http://127.0.0.1:8181/admin/state
curl http://127.0.0.1:8181/metrics
```

发送一次聊天请求：

```bash
curl -i http://127.0.0.1:8180/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-1.5b-instruct",
    "messages": [{"role": "user", "content": "用一句话打个招呼。"}],
    "max_tokens": 32,
    "temperature": 0
  }'
```

响应头会包含 `X-Router-Backend`。

## 真实实验入口

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

单独运行 exp2 指标驱动热点实验：

```bash
RESULTS_DIR=bench/results/real-npu-metrics-exp2-$(date +%Y%m%d%H%M%S) \
EXP2_DURATION=60 \
EXP2_PRESSURE_CONCURRENCY=32 \
  scripts/run_experiment2_real.sh
```

单独运行 exp8 7B 泛化热点实验：

```bash
RESULTS_DIR=bench/results/real-npu-qwen7b-$(date +%Y%m%d%H%M%S) \
  scripts/run_experiment8_qwen7b_real.sh
```

## 运维注意事项

- router 和 vLLM 进程都应运行在 Kunlun-02 的容器内。
- 不要停止无关容器或进程。
- 故障实验只允许 stop/start `yijq27-vllm-qwen15b-5`。
- exp8 只允许创建/删除 `yijq27-vllm-qwen7b-3` 到 `yijq27-vllm-qwen7b-7`。
- `config/router.qwen15b-5backends-swrr.json` 是静态基线，故意不配置 `metrics_url`。
- `config/router.qwen15b-5backends-p2c.json` 和 `config/router.qwen15b-5backends-balanced.json` 会读取 vLLM `/metrics` 实现负载感知调度。
- `config/router.qwen7b-5backends-*.json` 是 exp8 使用的 7B 配置。
