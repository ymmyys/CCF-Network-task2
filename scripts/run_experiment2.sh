#!/bin/bash
# Deprecated fake-backend experiment entry.

set -euo pipefail

cat >&2 <<'EOF'
scripts/run_experiment2.sh is deprecated.

Use one of these instead:
  - Formal real-NPU experiment:
      RESULTS_DIR=bench/results/real-npu-manual scripts/run_experiment2_real.sh
  - Development-only deterministic fixture:
      scripts/run_router_microbench.sh

The formal report uses only real Ascend NPU data and does not use this legacy
fake-backend experiment as evidence.
EOF

exit 1
