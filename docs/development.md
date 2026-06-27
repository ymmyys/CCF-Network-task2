# Development Guide

This project is a Go HTTP router for OpenAI-compatible vLLM-Ascend backends. The current Kunlun-02 development target is the same topology used by the real NPU experiments.

## Current Remote Target

| Item | Value |
|---|---|
| SSH host | `kunlun-02-act` |
| Router container | `yijq27-cann851` |
| Host workspace | `/home/yijq27/workspace/Track1_fuiglwgfnq_repos` |
| Container workspace | `/workspace/Track1_fuiglwgfnq_repos` |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` |
| Model directory | `/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct` |
| vLLM image | `quay.io/ascend/vllm-ascend:v0.18.0rc1` |
| Router data/admin ports | `8180` / `8181` |

## Backend Topology

| Backend ID | NPU | Port | Container |
|---|---:|---:|---|
| `qwen15b-npu3` | 3 | 9021 | `yijq27-vllm-qwen15b-3` |
| `qwen15b-npu4` | 4 | 9022 | `yijq27-vllm-qwen15b-4` |
| `qwen15b-npu5` | 5 | 9026 | `yijq27-vllm-qwen15b-5` |
| `qwen15b-npu6` | 6 | 9027 | `yijq27-vllm-qwen15b-6` |
| `qwen15b-npu7` | 7 | 9028 | `yijq27-vllm-qwen15b-7` |

Each backend exposes:

- OpenAI-compatible API on `/v1/chat/completions`;
- health probe on `/health`;
- Prometheus metrics on `/metrics`.

## Build Router

```bash
ssh kunlun-02-act
docker exec yijq27-cann851 bash -lc '
  cd /workspace/Track1_fuiglwgfnq_repos &&
  go build -o /workspace/bin/suan-router ./cmd/router
'
```

## Start Router Manually

For manual debugging, run the router inside the CANN container:

```bash
docker exec -it yijq27-cann851 bash
cd /workspace/Track1_fuiglwgfnq_repos
/workspace/bin/suan-router -config config/router.qwen15b-5backends-p2c.json
```

For experiment runs, prefer the scripts in `scripts/`; they write a PID file and only clean up the router process they started.

## Validate

Check backend health:

```bash
for p in 9021 9022 9026 9027 9028; do
  printf "%s " "$p"
  curl -fsS http://127.0.0.1:$p/health >/dev/null && echo ok || echo fail
done
```

Check router state:

```bash
curl http://127.0.0.1:8181/admin/state
curl http://127.0.0.1:8181/metrics
```

Send a chat request:

```bash
curl -i http://127.0.0.1:8180/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-1.5b-instruct",
    "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
    "max_tokens": 32,
    "temperature": 0
  }'
```

The response headers include `X-Router-Backend`.

## Real Experiment Entry

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

Single exp2 metrics-driven hotspot run:

```bash
RESULTS_DIR=bench/results/real-npu-metrics-exp2-$(date +%Y%m%d%H%M%S) \
EXP2_DURATION=60 \
EXP2_PRESSURE_CONCURRENCY=32 \
  scripts/run_experiment2_real.sh
```

## Operational Notes

- Keep router and vLLM processes inside containers on Kunlun-02.
- Do not stop unrelated containers or processes.
- Fault experiments may only stop/start `yijq27-vllm-qwen15b-5`.
- `config/router.qwen15b-5backends-swrr.json` is the static baseline and intentionally has no `metrics_url`.
- `config/router.qwen15b-5backends-p2c.json` and `config/router.qwen15b-5backends-balanced.json` read vLLM `/metrics` for load-aware scheduling.
