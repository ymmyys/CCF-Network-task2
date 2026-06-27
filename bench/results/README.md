# Real NPU Result Data

This directory records the formal real Ascend NPU experiment data used by the project documentation.

## Formal Layout

| Directory | Experiment | Purpose |
|---|---|---|
| `formal/exp1-balanced-baseline/` | exp1 | Balanced 5-backend baseline and scheduler overhead |
| `formal/exp2-hotspot-load/` | exp2 | Metrics-driven hotspot avoidance rerun |
| `formal/exp3-dynamic-capacity/` | exp3 | Capacity 10->1->10 smooth migration |
| `formal/exp4-failure-recovery/` | exp4 | Stop/start NPU5 failure recovery |
| `formal/exp5-pool-isolation/` | exp5 | Multi-pool noisy-neighbor isolation |
| `formal/exp6-comprehensive/` | exp6 | Combined demo scenario |
| `formal/exp7-smoothstep/` | exp7 | smoothStep sensitivity |
| `formal/system/` | system | `npu-smi` before/after snapshots |
| `formal/analysis/` | summary | Combined generated summaries |

The old run-batch directories were intentionally removed from tracked evidence. exp2 keeps the post-fix metrics-driven rerun, not the earlier pre-metrics pressure run.

## Included Files

- `analysis/real_npu_summary.csv` and `.md`: generated summaries used by the reports.
- `exp*-real-*.csv`: raw OpenAI-compatible request logs from `bench/loadgen.py`.
- `exp*-real-*.summary.csv`: per-second latency/QPS/backend-share summaries.
- `exp2-real-hotspot-*-metrics.csv`: vLLM `/metrics` plus router `/admin/state` samples for the formal hotspot experiment.
- `snapshots/*.state.json` and `snapshots/*.metrics.txt`: router state and Prometheus snapshots captured during experiments.
- `npu-smi-before.txt` and `npu-smi-after.txt`: device state snapshots for the full suite.

## Regenerate Summaries

```bash
python3 bench/generate_summary.py \
  --results-dir bench/results/formal \
  --output-dir bench/results/formal/analysis
```

Future ad-hoc result directories remain ignored by default. Add a new directory explicitly only when it becomes formal evidence.
