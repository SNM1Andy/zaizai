#!/usr/bin/env bash
# Run inside the patched SOURCE directory. Supply a new directory for raw logs.
set -euo pipefail
if [[ $# != 1 ]]; then echo "usage: bash handoff-checks/verify-core.sh NEW_LOG_DIRECTORY" >&2; exit 2; fi
mkdir -- "$1"
logs=$(cd -- "$1" && pwd)
cd -- "$(dirname -- "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
exec > >(tee "$logs/run.log") 2>&1
run() {
    local label=$1
    shift
    printf '%s  ' "$label"
    printf ' %q' "$@"
    printf '\n'
    if "$@" </dev/null >"$logs/$label.log" 2>&1; then
        echo "PASS $label"
    else
        local rc=$?
        tail -c 1600 "$logs/$label.log" >&2
        echo "FAIL $label rc=$rc" >&2
        exit "$rc"
    fi
}
outcomes() {
    local name=$1 binary=$2 cl=$3
    python3 handoff-checks/reasoned-outcome-check.py "$binary" "$cl" >"$logs/outcomes-$name.jsonl"
}
date -u
uname -srmo
"${CXX:-c++}" --version
python3 --version
run fixtures sha256sum -c handoff-checks/CORE-FIXTURE-SHA256SUMS
run build make -j"${JOBS:-2}" cl pcgm-alpha pcgm-beta projection-check-build cl-projection-two-worker
for name in alpha beta; do
    pcgm="./pcgm-$name"
    run "native-$name" python3 handoff-checks/native-check.py ./cl "$pcgm"
    run "anchored-$name" python3 handoff-checks/anchored-check.py "$pcgm"
    run "enroll-$name" python3 handoff-checks/enroll-check.py "$pcgm"
    run "resident-$name" python3 handoff-checks/resident-check.py "$pcgm" ./cl
    run "lost-ack-$name" python3 handoff-checks/resident-check.py "$pcgm" ./cl lost-ack
    run "frozen-answer-$name" python3 handoff-checks/frozen-answer-check.py "$pcgm" ./cl
    run "arithmetic-$name" python3 handoff-checks/arithmetic-check.py "$pcgm"
done
run frozen-admission python3 check-frozen-proof-admission.py
for name in alpha beta direct; do
    pcgm="./pcgm-$name"
    cl=./cl
    if [[ "$name" == direct ]]; then pcgm=./pcgm-projection-direct; cl=./cl-projection-direct; fi
    run "agenda-$name" python3 handoff-checks/work-agenda-check.py "$pcgm" "$cl"
    run "repair-$name" python3 handoff-checks/repair-check.py "$pcgm"
    run "outcome-$name" outcomes "$name" "$pcgm" "$cl"
done
for test in criteria-questions question-handoff choice-reassessment observation-replay-audit native-projection; do
    run "$test" python3 "check-$test.py"
done
sha256sum cl pcgm-alpha pcgm-beta cl-projection-direct pcgm-projection-direct projection-kernel-check cl-projection-two-worker
date -u
