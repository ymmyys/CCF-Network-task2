# exp5 Pool Isolation

Purpose: validate resource-pool isolation under noisy-neighbor pressure.

Key files:

- `exp5-real-default.csv`
- `exp5-real-isolated.csv`
- `exp5-*.state.json` and `exp5-*.metrics.txt`

Formal result: the default pool served 28,218 requests with 0 errors while the isolated pool ran long requests on real NPU5/6/7. This supports pool isolation under concurrent load.
