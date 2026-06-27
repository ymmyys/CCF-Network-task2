# Real NPU Experiment Summary

All rows are generated from real Ascend NPU experiment CSV files. Fake-backend fixture data is excluded.

| experiment | scheduler | window | requests | errors | qps | p50 | p95 | p99 | target share | conclusion |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| exp2 | swrr | all | 14179 | 0 | 236.45 | 133.7 | 154.65 | 178.44 | 19.96 | real hotspot pressure on qwen15b-npu3 |
| exp2 | p2c_smooth_wrr | all | 14447 | 0 | 240.81 | 132.3 | 148.74 | 158.73 | 0.0 | real hotspot pressure on qwen15b-npu3 |
| exp2 | balanced_p2c | all | 14429 | 0 | 240.42 | 132.5 | 149.97 | 157.72 | 3.94 | real hotspot pressure on qwen15b-npu3 |
