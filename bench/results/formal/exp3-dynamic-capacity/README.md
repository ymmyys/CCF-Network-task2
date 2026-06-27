# exp3 Dynamic Capacity

Purpose: validate smooth migration when `qwen15b-npu3` capacity changes from 10 to 1 and back to 10.

Key files:

- `exp3-real-capacity-p2c.csv`
- `exp3-real-capacity-p2c.summary.csv`
- `exp3-*.state.json` and `exp3-*.metrics.txt`

Formal result: stable-down NPU3 share was 2.37% versus the theoretical 2.44%, with 29,748 requests and 0 errors. This supports the required smooth transition without interrupting assigned requests.
