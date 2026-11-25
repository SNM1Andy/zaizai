#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
sha256sum -c SOURCE-SHA256SUMS >/dev/null
make -j1 cl pcgm-alpha pcgm-beta
for name in alpha beta; do
    exe="./pcgm-$name"
    python3 handoff-checks/native-check.py ./cl "$exe"
    python3 handoff-checks/anchored-check.py "$exe"
    python3 handoff-checks/enroll-check.py "$exe"
    python3 handoff-checks/resident-check.py "$exe" ./cl
    python3 handoff-checks/resident-check.py "$exe" ./cl lost-ack
    python3 handoff-checks/frozen-answer-check.py "$exe" ./cl
    python3 handoff-checks/arithmetic-check.py "$exe"
done
python3 check-frozen-proof-admission.py
