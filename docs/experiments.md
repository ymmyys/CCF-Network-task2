# Experiment Plan

This document defines the validation plan for Track 2: dynamic load-aware
scheduling for large-model inference compute resources.

## Goal

Validate that `suan-router` improves request scheduling for Ascend NPU inference
clusters under dynamic backend health, load, and capacity changes.

The key claim is:

- static round-robin keeps sending traffic to hot or degraded backends;
- `p2c_smooth_wrr` uses backend health, queue depth, local inflight, KV cache,
  latency, and capacity to adjust effective weights dynamically;
- capacity decreases such as `10 -> 1` are smoothed, so new traffic migrates
  gradually and in-flight requests are not interrupted.

## Remote Testbed

- Host: `kunlun-02-act`
- Router container: `yijq27-cann851`
- vLLM image: `quay.io/ascend/vllm-ascend:v0.18.0rc1`
- Model for experiments: `Qwen/Qwen2.5-1.5B-Instruct`
- Model path: `/home/yijq27/workspace/models/Qwen2.5-1.5B-Instruct`
- Experiment router data plane: `http://127.0.0.1:8180`
- Experiment router admin plane: `http://127.0.0.1:8181`

NPU allocation must be checked before every run. Do not stop containers or
processes that are not owned by the current experiment. If another user's job is
visible in `npu-smi`, choose different NPU IDs.

The current experiment uses:

- `qwen15b-npu3`: NPU 3, vLLM port `9021`
- `qwen15b-npu4`: NPU 4, vLLM port `9022`

NPU 2 is intentionally avoided because it has an existing non-experiment
process.

## Compared Schedulers

### Static Baseline

Config: `config/router.qwen15b-static-swrr.example.json`

This uses smooth weighted round-robin with static startup capacity. It keeps
health checks, but omits backend metrics URLs, so it does not dynamically react
to vLLM queue, KV cache, or latency metrics.

### Load-Aware Router

Config: `config/router.qwen15b-p2c.example.json`

This uses `p2c_smooth_wrr` and reads vLLM `/metrics`. The scheduler combines
smooth effective weights with power-of-two choices and local/remote load
signals.

## Metrics

Collect these metrics for each run:

- total requests
- success rate
- throughput/QPS
- p50 latency
- p95 latency
- p99 latency
- backend request distribution from `X-Router-Backend`
- `/admin/state` snapshots: `phase`, `capacity`, `desired_weight`,
  `effective_weight`, `queue_depth`, `latency_ewma_ms`

## Experiment A: Balanced Backends

Purpose: show that load-aware scheduling has no significant overhead when both
backends are healthy and symmetric.

Run the same load against the static baseline and the load-aware router:

```bash
python3 bench/loadgen.py \
  --url http://127.0.0.1:8180/v1/chat/completions \
  --header 'Content-Type:application/json' \
  --body '{"model":"qwen2.5-1.5b-instruct","messages":[{"role":"user","content":"Reply with pong only."}],"max_tokens":16,"temperature":0}' \
  --duration 60 \
  --concurrency 16 \
  --timeout 90 \
  --output bench/results/qwen15b-balanced-p2c.csv
```

Expected result: both schedulers produce similar throughput and latency, and the
backend distribution is close to even.

## Experiment B: Dynamic Capacity Drop

Purpose: validate the required `capacity 10 -> 1` smooth transition.

Start load generation, then inject a capacity drop and recovery:

```bash
python3 bench/inject_capacity.py \
  --admin http://127.0.0.1:8181 \
  --event 20,default,qwen15b-npu3,1 \
  --event 50,default,qwen15b-npu3,10
```

Expected result:

- `qwen15b-npu3.desired_weight` drops quickly after the event;
- `qwen15b-npu3.effective_weight` decreases smoothly instead of jumping;
- request share shifts from `qwen15b-npu3` to `qwen15b-npu4`;
- existing requests finish normally;
- after recovery, the backend enters `recovering`/slow-start before becoming
  fully active.

## Experiment C: Hot Backend

Purpose: show that load-aware scheduling reduces hotspot effects.

Create direct background pressure on `qwen15b-npu3`, then send measured traffic
through the router. Compare static baseline and load-aware router.

Expected result:

- static SWRR keeps routing a large share to the hot backend;
- `p2c_smooth_wrr` lowers the hot backend selection probability;
- p95/p99 latency and timeout rate are lower with `p2c_smooth_wrr`.

## Analysis

Use `bench/plot_results.py` for second-level summaries and plots:

```bash
python3 bench/plot_results.py \
  --input bench/results/qwen15b-balanced-p2c.csv \
  --output bench/results/qwen15b-balanced-p2c.png
```

For the submission report, include:

- one table comparing baseline and load-aware runs;
- one timeline plot for dynamic capacity drop;
- one `/admin/state` snapshot before, during, and after capacity change;
- one command transcript showing real Ascend NPU vLLM backends and router
  responses with `X-Router-Backend`.
