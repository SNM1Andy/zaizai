from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

cl, pc = (Path(p).resolve(strict=True) for p in sys.argv[1:3])

def run(binary, *args, wire=b""):
    p = subprocess.run([binary, *args], input=wire, capture_output=True, timeout=30)
    assert p.returncode == 0 and not p.stderr, (p.args, p.stderr)
    return p.stdout

with TemporaryDirectory(prefix="isolated-goal-review-") as tmp:
    w = Path(tmp)
    rules = """: noticed(sym).
: safe(sym).
: alternative(sym).
: result(sym).
: mixed(sym).
: unknown_target(sym).
: connected(sym,sym).
: another(sym).
: undetermined(sym).
: insufficient(sym).
undetermined($x) <- noticed($x) & connected($who,$x).
undetermined($x) <- noticed($x) & safe($x).
insufficient($x) <- noticed($x) & safe($x) & another($x).
result($x) <- noticed($x) & safe($x).
!result($x) <- !safe($x).
mixed($x) <- noticed($x) & safe($x).
mixed($x) <- noticed($x) & alternative($x).
"""
    model = w / "rules.cl"
    state = w / "state"
    model.write_text(rules + "? result(item).\n? mixed(item).\n? undetermined(item).\n? insufficient(item).\n")
    run(pc, "--init-managed", model, state, wire=b":observe initial noticed(item)\n")

    def ask(frame, at=state):
        before = at.read_bytes()
        answer = json.loads(run(pc, "--read-channel", at, wire=("s " + frame + "\n").encode()))
        assert at.read_bytes() == before
        return answer

    def current(at=state):
        return ask("storage", at)["payload"]["logical_sha256"]

    def preview(goal="result(item)", head=None, at=state):
        return ask(f"obligation {head or current(at)} {goal}", at)

    checked = preview()["payload"]
    assert checked["current"]["status"] == "UNKNOWN" and checked["candidate_count"] == 1, checked
    assert checked["investigation"]["premise"]["predicate"] == "safe"
    branches = [row["consequence"]["status"] for row in checked["investigation"]["branches"]]
    assert branches == ["POSITIVE", "NEGATIVE"] and checked["scan_complete"]
    assert checked["investigation"]["distinguishes_consequence"]
    assert checked["hypotheses_are_not_facts"] and not any(checked[k] for k in ("authorizes_action", "writes_state", "outbound"))
    assert ask("question_feed 0 8")["payload"]["results"] == []
    mixed = preview("mixed(item)")["payload"]
    assert mixed["scan_complete"] and mixed["candidate_count"] == 2 and mixed["investigation"] is None
    uncertain = preview("undetermined(item)")["payload"]
    assert uncertain["current"]["status"] == "UNKNOWN" and not uncertain["scan_complete"], uncertain
    assert uncertain["candidate_count"] is None and uncertain["investigation"] is None
    insufficient = preview("insufficient(item)")["payload"]
    assert insufficient["scan_complete"] and insufficient["candidate_count"] == 1, insufficient
    trial = insufficient["investigation"]
    assert trial and not trial["distinguishes_consequence"]
    assert all(b["consequence"]["status"] == "UNKNOWN" for b in trial["branches"])
    assert not preview("unknown_target(item)")["ok"]
    assert not preview(head="*")["ok"]
    assert not preview("!result(item)")["ok"]
    assert not preview("result($x)")["ok"]
    formal = w / "reference.cl"
    formal.write_text("module reference.\ninput noticed.\ninput safe.\nexport result.\n" + rules)
    lock, api, data, package, goal = [w / p for p in ("lock", "api", "data.cl", "pkg", "goals")]
    lock.write_bytes(run(cl, "lock", formal))
    api.write_bytes(run(cl, "project-api", formal, lock))
    goal.write_text("result(item)\n")
    def oracle(extra):
        data.write_text("& initial noticed(item).\n" + extra)
        package.write_bytes(run(cl, "project-pack", formal, lock, api, data))
        return json.loads(run(cl, "package-prove", package, sha256(package.read_bytes()).hexdigest(), goal))["results"][0]["status"]
    assert [oracle("& trial safe(item).\n"), oracle("& trial !safe(item).\n")] == branches
    previous = current()
    for evidence, status, extra in [
        (b":observe yes safe(item)\n", "POSITIVE", "& yes safe(item).\n"),
        (b":observe no !safe(item)\n", "CONFLICT", "& yes safe(item).\n& no !safe(item).\n"),
        (b":withdraw yes\n", "NEGATIVE", "& no !safe(item).\n"),
        (b":withdraw no\n", "UNKNOWN", ""),
    ]:
        run(pc, "--resume", state, wire=evidence)
        result = preview()["payload"]
        assert result["current"]["status"] == oracle(extra) == status
        assert (result["investigation"] is None) == (status != "UNKNOWN")
        assert not preview(head=previous)["ok"]
        previous = current()
    archive, cold = w / "archive", w / "cold"
    run(pc, "--export-complete", state, archive)
    run(pc, "--restore-copy", archive, cold)
    fresh = preview(at=cold)["payload"]
    assert fresh["actor"] == checked["actor"] and fresh["current"]["status"] == "UNKNOWN"
    assert [row["consequence"]["status"] for row in fresh["investigation"]["branches"]] == branches
print("PASS: complete, ambiguous, incomplete and insufficient branches; independent CL and cold identity")
