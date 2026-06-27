# bench

This directory contains the load generator, metrics collector, plotting helpers, and summary generator used by the router experiments.

## Formal Real-NPU Flow

Run experiments from the remote host workspace:

```bash
cd /home/yijq27/workspace/Track1_fuiglwgfnq_repos
RESULTS_DIR=bench/results/real-npu-$(date +%Y%m%d%H%M%S) \
  scripts/run_real_npu_suite.sh
```

Generate summaries:

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/real-npu-20260627021640 \
  --output-dir bench/results/real-npu-20260627021640/analysis
```

The current metrics-driven exp2 rerun lives in:

```text
bench/results/real-npu-metrics-exp2-20260627203104/
```

## Important Scripts

| File | Purpose |
|---|---|
| `loadgen.py` | OpenAI-compatible load generator |
| `collect_metrics.py` | vLLM `/metrics` plus router `/admin/state` sampler |
| `generate_summary.py` | real NPU CSV summary and window statistics |
| `plot_results.py` | optional latency/QPS plots |
| `inject_capacity.py` | admin API capacity event injector |
| `fake_backend.py` | development fixture only, not formal evidence |

## Baseline Definition

For formal comparisons:

- baseline: `scheduler.mode=swrr` with `config/router.qwen15b-5backends-swrr.json`, intentionally without `metrics_url`;
- improved: `scheduler.mode=p2c_smooth_wrr` with vLLM `/metrics`;
- balanced improved: `p2c_smooth_wrr` plus `balanced_p2c=true`, also with vLLM `/metrics`.

Fake backends are useful for local deterministic tests, but formal report conclusions only use real Ascend NPU 3-7 data.
