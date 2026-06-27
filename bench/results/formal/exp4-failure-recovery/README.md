# exp4 Failure Recovery

Purpose: validate real backend failure ejection and recovery by stopping and starting only `yijq27-vllm-qwen15b-5`.

Key files:

- `exp4-real-failure-p2c.csv`
- `exp4-real-failure-p2c.summary.csv`
- `exp4-*.state.json` and `exp4-*.metrics.txt`

Formal result: during the fail-stable window, NPU5 share dropped to 0.02%; during the recovery-end window, it returned to 19.80%. The full run had 72,794 requests and 3 errors.
