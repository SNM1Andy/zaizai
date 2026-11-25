"""Usage: python3 integration/frozen-answer-to-repair.py SOURCE_DIR [alpha|beta]

Single managed actor. The local host approves requests. The independent CL
producer supplies one certified fact. The two repair ticks have no arguments.
Stdout contains native JSON records, stderr carries the final test result.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


source = Path(sys.argv[1]).resolve(strict=True)
build = sys.argv[2] if len(sys.argv) > 2 else "alpha"
assert build in ("alpha", "beta")
pcgm, cl = source / ("pcgm-" + build), source / "cl"
fixtures = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(binary, *args, wire=b"", pass_fds=()):
    p = subprocess.run([binary, *args], input=wire, capture_output=True, pass_fds=pass_fds, timeout=120)
    assert p.returncode == 0 and not p.stderr and b"QUERY_ERROR " not in p.stdout, (p.args, p.stdout, p.stderr)
    return p.stdout


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",",":")), flush=True)
    return value


def atom(a):
    return a["predicate"] + "(" + ",".join(x["value"] for x in a["arguments"]) + ")"


def selected(repair):
    decision = repair["decision"]
    return decision["options"][decision["selected"]]["kind"]


def scenario(root):
    state = root / "actor"
    run(pcgm, "--init-managed", fixtures/"parcel.cl", state, wire=b":pin initial\n")

    def resume(command):
        return run(pcgm, "--resume", state, wire=(command+"\n").encode())

    def read(command):
        before = state.read_bytes()
        result = json.loads(run(pcgm,"--read-channel",state,wire=("q "+command+"\n").encode()))
        assert result["ok"] and before == state.read_bytes(),result
        return result["payload"]

    def tick():
        result, = [json.loads(line) for line in resume(":repair_step").splitlines() if line.startswith(b"{")]
        return emit(result)

    def approval(command):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd,(command+"\n").encode())
        finally:
            os.close(write_fd)
        try:
            lines = run(pcgm, "--resume-agenda-local", state, str(read_fd), pass_fds=(read_fd,)).splitlines()
        finally:
            os.close(read_fd)
        startup, response = map(json.loads,lines)
        assert startup["actor"] == actor and response["channel"] == "approval" and response["ok"],response
        return emit(response["payload"])

    initial = state.read_bytes()
    first = tick()
    actor = first["actor"]
    assert selected(first) == "stay" and not first["writes_state"] and state.read_bytes() == initial
    assert any(o["kind"] == "rewrite" and "fewer than two" in o["blocked_reason"] for o in first["decision"]["options"])
    scan = emit(read("agenda"))
    assert scan["reason"] == "pending_approval" and scan["actor"] == actor and scan["eligible_count"] == 1
    review = scan["proposed_review"]
    gap = review["investigation"]
    assert atom(review["current"]["goal"]) == "eligible(blue)" and atom(gap["premise"]) == "certified(blue)"
    assert {b["consequence"]["status"] for b in gap["branches"]} == {"POSITIVE","NEGATIVE"}
    head, review_pin = scan["revision_sha256"],scan["review_sha256"]
    approved = sha(f"PCGM-LOCAL-AGENDA-APPROVAL-1\n{actor}\n{head}\n{review_pin}\n".encode())
    enrolled = approval(f"enroll_agenda {actor} {head} {review_pin} {approved}")
    ticket = enrolled["ticket"]
    question, = read("question "+ticket)["results"]
    request = question["request_sha256"]
    assert question["status"] == "open"

    provider = fixtures / "provider.cl"
    lock, api, package, goals, journal = [root / n for n in ("lock","api","package","goals","journal")]
    lock.write_bytes(run(cl,"lock",provider))
    api.write_bytes(run(cl,"project-api",provider,lock))
    package.write_bytes(run(cl,"project-pack",provider,lock,api))
    package_pin = sha(package.read_bytes())
    goals.write_text("certified(blue)\n")
    assert json.loads(run(cl,"evidence-init",package,package_pin,goals,journal,
                          wire=b"req batch inspector 0 ; observe verified certified(blue)\n"))["ok"]
    snapshot = sha(journal.read_bytes())
    (root/"incoming").mkdir()
    frozen = root/"incoming"/"inspector.clef"
    frozen.write_bytes(run(cl,"evidence-freeze",package,package_pin,goals,journal,snapshot))
    artifact = sha(frozen.read_bytes())
    reviewed = emit(json.loads(run(pcgm,"--frozen-question-review",state,ticket,request,frozen,artifact,package_pin,snapshot)))
    proof = reviewed["proof_sha256"]
    assert reviewed["individual"] == actor and not reviewed["observation_written"]
    answer = approval(f"answer {actor} {enrolled['head_sha256']} {ticket} {request} inspector {artifact} {package_pin} {snapshot} {proof}")
    observation = answer["observation"]
    assert answer["writes_state"] and answer["actor"] == actor

    def outcome(goal, pin):
        result = emit(read(f"reasoned_outcome parcel {goal} since {pin}"))
        assert result["source_id"] == actor
        return result

    eligible = outcome("eligible(blue)","initial")
    assert eligible["status"] == "POSITIVE" and eligible["question_ticket"] == ticket
    answer_ref, = eligible["questions"][0]["evidence"]
    assert answer_ref["observation"] == observation and answer_ref["cl_proof_sha256"] == proof and answer_ref["active"]
    assert outcome("release(blue)","initial")["status"] == "UNKNOWN"
    resume(":pin answered")
    commit = tick()
    assert commit["actor"] == actor and commit["writes_state"] and selected(commit) == "rewrite"
    rule, = [r for r in commit["rule_reviews"] if r["compiled_cl_slice_sha256"]]
    assert set(rule["stalled_cases"]) == {"release(amber)","release(blue)"}
    assert "obs:"+observation in rule["proof_origins"]
    joint = outcome("release(blue)","initial")
    assert joint["status"] == "POSITIVE"
    effect = joint["effect_receipt"]
    added, = effect["rules_added"]
    assert added["rule"] == "release($x) <- eligible($x)." and added["in_witness"]
    changed, = effect["observation_changes"]
    assert changed["observation_id"] == observation and changed["status_if_change_undone"] == "UNKNOWN"
    nodes = {atom(n["fact"]): n for n in joint["positive_proof"]["nodes"]}
    assert nodes["certified(blue)"]["origin"] == "obs:"+observation
    assert [atom(x) for x in nodes["release(blue)"]["premises"]] == ["eligible(blue)"]
    assert outcome("release(crushed)","initial")["status"] == "NEGATIVE"

    # A new writer reopens the same actor and retrieves the committed decision.
    recovered = emit(read("decision "+commit["decision_event"]))
    assert recovered == commit["decision"]
    saved = state.read_bytes()
    again = tick()
    assert again["actor"] == actor and selected(again) == "stay" and not again["writes_state"]
    assert saved == state.read_bytes() and len(read("question_feed 0 16")["results"]) == 1

    # A later input has its own gap. The actor must create a second ticket,
    # keep the first address readable, and reconcile a duplicate approval.
    resume(":observe green_scanner scanned(green)")
    fresh = emit(read("agenda"))
    assert fresh["reason"] == "pending_approval" and fresh["actor"] == actor
    assert atom(fresh["proposed_review"]["investigation"]["premise"]) == "certified(green)"
    new_head, new_review = fresh["revision_sha256"], fresh["review_sha256"]
    new_pin = sha(f"PCGM-LOCAL-AGENDA-APPROVAL-1\n{actor}\n{new_head}\n{new_review}\n".encode())
    frame = f"enroll_agenda {actor} {new_head} {new_review} {new_pin}"
    second_ticket = approval(frame)
    assert second_ticket["writes_state"] and second_ticket["ticket"] != ticket
    latest = state.read_bytes()
    duplicate = approval(frame)
    assert not duplicate["writes_state"] and duplicate["ticket"] == second_ticket["ticket"]
    questions = {q["id"]: q for q in read("question_feed 0 16")["results"]}
    assert set(questions) == {ticket, second_ticket["ticket"]}
    assert questions[ticket]["status"] == "answered" and questions[second_ticket["ticket"]]["status"] == "open"
    assert read("agenda")["reason"] == "already_ticketed" and latest == state.read_bytes()


with TemporaryDirectory(prefix="pcgm-answer-repair-") as folder:
    scenario(Path(folder))
print(f"PASS {build}: same actor; approved independent frozen evidence enables second repair witness; "
      "joint proof, negative control, durable decision and distinct idempotent tickets checked",file=sys.stderr)
