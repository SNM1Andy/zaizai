"""Run from SOURCE: python3 handoff-checks/reasoned-outcome-check.py ./pcgm-alpha ./cl

Stdout is a JSONL transcript of the native outcome payloads. The preclassified
source and language records are interface fixtures, supplied independently of
the core under test. No external service or parser is simulated by this driver.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory


pcgm, cl = (Path(arg).resolve(strict=True) for arg in sys.argv[1:3])
fixtures = Path(__file__).resolve().parents[1] / "fixtures"
inputs = fixtures / "outcome"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(binary, *args, wire=""):
    p = subprocess.run([binary, *args], input=wire.encode(), capture_output=True, timeout=120)
    assert p.returncode == 0 and not p.stderr, (p.args, p.stdout, p.stderr)
    return p.stdout


def rows(name):
    return [json.loads(line) for line in (inputs / name).read_text(encoding="utf-8").splitlines()]


def proof_lines(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.startswith(b'{"schema":')]


def proof_atom(atom):
    return atom["predicate"] + "(" + ",".join(arg["value"] for arg in atom["arguments"]) + ")"


@contextmanager
def resident(state):
    rfd,wfd = os.pipe()
    try:
        p = subprocess.Popen([pcgm, "--resume-agenda-local", state, str(rfd)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(rfd,), bufsize=0)
    except BaseException:
        os.close(wfd)
        raise
    finally:
        os.close(rfd)

    def receive():
        assert select.select([p.stdout], [], [], 120)[0], "resident timed out"
        line = p.stdout.readline()
        assert line, "resident exited before returning a frame"
        return json.loads(line)

    def approve(frame):
        os.write(wfd, (frame+"\n").encode())
        reply = receive()
        assert reply["ok"] and reply["channel"] == "approval", reply
        return reply["payload"]

    try:
        yield receive(), approve
    finally:
        p.stdin.close()
        os.close(wfd)
        try:
            assert p.wait(timeout=120) == 0 and not p.stderr.read()
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            p.stderr.close()


def reviewed_answer(root, state, ticket, request, claim):
    lock, api, pkg, goals, journal = [root / n for n in ("lock", "api", "pkg", "goals", "journal")]
    source = inputs / "provider.cl"
    lock.write_bytes(run(cl, "lock", source))
    api.write_bytes(run(cl, "project-api", source, lock))
    pkg.write_bytes(run(cl, "project-pack", source, lock, api))
    package = sha(pkg.read_bytes())
    fact = proof_atom(claim)
    goals.write_text(fact+"\n")
    init = json.loads(run(cl, "evidence-init", pkg, package, goals, journal,
                          wire=f"y batch desk 0 ; observe independent {fact}\n"))
    assert init["ok"], init
    snapshot = sha(journal.read_bytes())
    inbox = root / "incoming"
    inbox.mkdir()
    frozen = inbox / "desk.clef"
    frozen.write_bytes(run(cl, "evidence-freeze", pkg, package, goals, journal, snapshot))
    artifact = sha(frozen.read_bytes())
    proof = json.loads(run(pcgm, "--frozen-question-review", state, ticket, request, frozen,
                           artifact, package, snapshot))
    return artifact, package, snapshot, proof["proof_sha256"]


def scenario(root):
    for line in (inputs/"SHA256SUMS").read_text(encoding="ascii").splitlines():
        expected, name = line.split()
        assert sha((inputs/name).read_bytes()) == expected,name
    case = "bluepass"
    sentence, = rows("dialogue-candidate.jsonl")
    senses = {s["sense_id"]: s for s in rows("lexicon-senses.jsonl")}
    spans = sentence["input_spans"]
    raw = sentence["utterance"].encode()
    assert all(raw[s["start"]:s["end"]].decode() == s["surface"] for s in spans)
    goals = []
    for candidate in sentence["alternatives"]:
        goal = candidate["goal"]
        assert goal["predicate"] == senses[candidate["sense_id"]]["predicate_signature"]["predicate"]
        goals.append(proof_atom(goal))
    cargo, funds = goals
    original, replica, independent = rows("source-observations.jsonl")
    assert all(sha(r["excerpt"].encode()) == r["digest"] for r in (original, replica, independent))
    assert original["lineage_refs"] == replica["lineage_refs"] != independent["lineage_refs"]
    assert all(r["case_id"] == case for r in [sentence, original, replica, independent, *senses.values()])
    state = root / "actor"

    def read(frame, ok=True):
        before = state.read_bytes()
        result = json.loads(run(pcgm, "--read-channel", state, wire="req "+frame+"\n"))
        assert state.read_bytes() == before and result["ok"] == ok, result
        return result.get("payload") if ok else result["error"]

    def resume(command):
        return run(pcgm, "--resume", state, wire=command+"\n")

    def outcome(goal, expected, basis="", emit=True):
        value = read(f"reasoned_outcome {case} {goal}"+(f" since {basis}" if basis else ""))
        assert value["schema"] == "pcgm-reasoned-outcome-v1" and value["case_id"] == case
        assert value["baseline_version"] == sentence["baseline_version"] and proof_atom(value["goal"]) == goal
        assert value["status"] == expected and value["state_revision"] == read("storage")["logical_sha256"]
        assert value["positive_proof"]["supported"] == (expected in ("POSITIVE","CONFLICT"))
        assert value["negative_proof"]["supported"] == (expected in ("NEGATIVE","CONFLICT"))
        if basis:
            effect = value["effect_receipt"]
            assert effect["state_revision"] == value["state_revision"] and not effect["writes_state"]
            assert effect["after_status"] == expected and proof_atom(effect["effect_point"]) == goal
        else:
            assert value["effect_receipt"] is None
        if emit:
            print(json.dumps(value, ensure_ascii=False, separators=(",",":")), flush=True)
        return value

    def fixture_observation(row):
        # The source line owns lineage verification. Here its frozen family
        # binding and typed claim are the precondition for core-level replay.
        return f":observe {row['fixture_admission_id']} {proof_atom(row['claim'])}"

    run(pcgm, "--init-managed", inputs/"routes.cl", state, wire=fixture_observation(original)+"\n")
    before = state.read_bytes()
    assert b"observation_unchanged" in resume(fixture_observation(replica)) and state.read_bytes() == before
    assert not read("question_feed 0 16")["results"]
    unknown = outcome(cargo, "UNKNOWN")
    assert [proof_atom(g) for g in unknown["missing"]] == ["dock_context(blue)"]
    assert unknown["question_ticket"] is None and not unknown["positive_proof"]["nodes"]
    outcome(funds, "UNKNOWN")

    with resident(state) as (startup,approve):
        scan = startup["agenda"]
        review = scan["proposed_review"]
        assert scan["eligible_count"] == 1 and proof_atom(review["current"]["goal"]) == cargo
        assert review["investigation"]["distinguishes_consequence"]
        assert {b["consequence"]["status"] for b in review["investigation"]["branches"]} == {"POSITIVE","NEGATIVE"}
        assert proof_atom(review["investigation"]["premise"]) == proof_atom(independent["claim"])
        actor, head, reviewed = startup["actor"], startup["head_sha256"], scan["review_sha256"]
        approval = sha(f"PCGM-LOCAL-AGENDA-APPROVAL-1\n{actor}\n{head}\n{reviewed}\n".encode())
        enrollment = approve(f"enroll_agenda {actor} {head} {reviewed} {approval}")
        ticket = enrollment["ticket"]
        waiting = outcome(cargo, "UNKNOWN")
        question, = waiting["questions"]
        assert waiting["question_ticket"] == ticket and question["status"] == "open"
        req = question["request_sha256"]
        pins = reviewed_answer(root, state, ticket, req, independent["claim"])

    # Persist focus and an exact baseline before reopening the approval pipe.
    assert b"chat_committed" in resume(f":chat {case} t0 focus {cargo}")
    resume(":pin waiting")
    with resident(state) as (startup,approve):
        assert startup["actor"] == actor
        artifact, package, snapshot, proof = pins
        frame = f"answer {actor} {startup['head_sha256']} {ticket} {req} desk {artifact} {package} {snapshot} {proof}"
        answer = approve(frame)
        assert answer["writes_state"]
        observed = answer["observation"]

    positive = outcome(cargo,"POSITIVE","waiting")
    neg = outcome(funds,"NEGATIVE","waiting")
    evidence, = positive["questions"][0]["evidence"]
    assert evidence["active"] and evidence["observation"] == observed and evidence["cl_proof_sha256"] == proof
    change, = positive["effect_receipt"]["observation_changes"]
    assert change["observation_id"] == observed and change["in_after_witness"] and change["before"] is None
    assert change["status_if_change_undone"] == "UNKNOWN" and not positive["effect_receipt"]["rules_added"]
    assert neg["effect_receipt"]["conclusion_changed"]
    # Chat receives exactly what the read-only caller saw at the pre-turn head.
    dialogue = resume(f":chat {case} t1 outcome since waiting")
    same, = proof_lines(dialogue)
    assert same == positive
    resume(":pin answered")
    resume(":observe challenger !dock_context(blue)")
    conflict = outcome(cargo,"CONFLICT","answered")
    outcome(funds,"CONFLICT","answered")
    change, = conflict["effect_receipt"]["observation_changes"]
    assert change["observation_id"] == "challenger" and change["status_if_change_undone"] == "POSITIVE"
    resume(":pin contested")
    resume(":withdraw "+observed)
    negative = outcome(cargo,"NEGATIVE","contested")
    outcome(funds,"POSITIVE","contested")
    removed, = negative["effect_receipt"]["observation_changes"]
    assert removed["observation_id"] == observed and removed["after"] is None
    assert removed["in_before_witness"] and removed["status_if_change_undone"] == "CONFLICT"
    assert negative["question_ticket"] == ticket and not negative["questions"][0]["evidence"][0]["active"]
    resume(":withdraw challenger")
    final = outcome(cargo,"UNKNOWN","waiting")
    assert final["question_ticket"] == ticket and final["questions"][0]["status"] == "open"
    assert not final["effect_receipt"]["conclusion_changed"] and not final["effect_receipt"]["proof_changed"]
    before = state.read_bytes()
    replay = resume(f":chat {case} t1 outcome since waiting")
    assert b"chat_replayed" in replay and proof_lines(replay) == [positive] and state.read_bytes() == before
    assert "unknown outcome comparison pin" in read(f"reasoned_outcome {case} {cargo} since absent",ok=False)
    assert final["source_id"] == actor and len(read("question_feed 0 16")["results"]) == 1


def check_rule_switch(root):
    state = root / "repair_actor"
    wire = (fixtures/"repair-parcels.observations").read_text(encoding="utf-8")
    run(pcgm, "--init-managed", fixtures/"repair-parcels.cl", state, wire=wire+"\n:pin prior\n")
    response, = proof_lines(run(pcgm, "--resume", state, wire=":repair_step\n"))
    assert response["writes_state"],response

    def result(pin):
        before=state.read_bytes()
        row=json.loads(run(pcgm,"--read-channel",state,wire=f"q reasoned_outcome parcel release(copper) since {pin}\n"))
        assert row["ok"] and before==state.read_bytes(),row
        print(json.dumps(row["payload"],ensure_ascii=False,separators=(",",":")),flush=True)
        return row["payload"]["effect_receipt"]

    effect = result("prior")
    added, = effect["rules_added"]
    assert effect["before_status"]=="UNKNOWN" and effect["after_status"]=="POSITIVE"
    assert added["in_witness"] and added["rule"]=="release($x) <- scanned($x)."
    assert not effect["observation_changes"] and not effect["rules_removed"]
    plans = run(pcgm, "--resume",state,wire=":pin hot\n:plans\n")
    applied, = [row.split()[1].decode() for row in plans.splitlines() if row.startswith(b"plan ") and b" applied " in row]
    assert b"revision_reverted" in run(pcgm, "--resume",state,wire=f":rollback {applied}\n")
    rolled = result("hot")
    assert rolled["rules_removed"] == [added] and not rolled["rules_added"]
    assert rolled["before_status"]=="POSITIVE" and rolled["after_status"]=="UNKNOWN"


with TemporaryDirectory(prefix="pcgm-outcomes-") as tmp:
    root = Path(tmp)
    scenario(root)
    check_rule_switch(root)
print("PASS: four values; case, proofs, open ticket, exact frozen evidence and withdrawal; dialogue replay; applied and rolled-back rule attribution",file=sys.stderr)
