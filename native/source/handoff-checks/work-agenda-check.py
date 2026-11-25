"""Linux: python3 handoff-checks/work-agenda-check.py ./pcgm-alpha ./cl

Both CL fixtures were authored locally and frozen before the first run.
The answer lives in a separate native evidence journal/package.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


pcgm, cl = [Path(x).resolve(strict=True) for x in sys.argv[1:3]]
fixtures = Path(__file__).resolve().parents[1] / "fixtures"
source = fixtures / "agenda-discovery.cl"
independent = fixtures / "agenda-independent.cl"


def digest(data):
    return hashlib.sha256(data).hexdigest()


assert digest(source.read_bytes()) == "8bb5f9b3e235666cd12d34e9b01cbbad6383d0fd6fcce08b979fa58120f49dbc"
assert digest(independent.read_bytes()) == "d585551a4b7d2f04366c2bb3f89e0d98b5d530cbeb41a4e68fb43ae774786b1e"


def run(*args, wire=b"", refused=None):
    p = subprocess.run(args, input=wire, capture_output=True, timeout=90)
    if refused:
        assert p.returncode and refused.encode() in p.stderr, (p.args, p.stdout, p.stderr)
    else:
        assert p.returncode == 0 and not p.stderr, (p.args, p.stdout, p.stderr)
    return p.stdout


def read(state, frame, concurrent=False):
    old = state.read_bytes()
    raw = run(pcgm, "--read-channel", state, wire=f"id {frame}\n".encode())
    print("READ", frame, raw.decode().rstrip(), flush=True)
    result = json.loads(raw)
    assert result["ok"] and (concurrent or old == state.read_bytes()), result
    return result["payload"]


def update(state, text):
    output = run(pcgm, "--resume", state, wire=text.encode())
    assert b"error " not in output, output


def expect_agenda(state, reason, goal=None, argument=None):
    report = read(state, "agenda")
    assert report["reason"] == reason and not report["writes_state"], report
    proposed = report["proposed_review"]
    if goal:
        target = proposed["current"]["goal"]
        assert target["predicate"] == goal and target["arguments"][0]["value"] == argument, target
        assert any(n["origin"].startswith("obs:") for n in report["grounding"]["proof"]["nodes"])
        assert proposed["current"]["status"] == "UNKNOWN"
        assert [b["consequence"]["status"] for b in proposed["investigation"]["branches"]] == ["POSITIVE", "NEGATIVE"]
        assert digest(json.dumps(proposed, separators=(",", ":"), ensure_ascii=False).encode()) == report["review_sha256"]
    else:
        assert proposed is None and report["review_sha256"] is None
    return report


class Resident:
    def __init__(self, state):
        r, self.w = os.pipe()
        self.p = subprocess.Popen([pcgm, "--resume-agenda-local", state, str(r)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(r,), bufsize=0)
        os.close(r)
        self.start = self.receive()
        print("RESIDENT PID", self.p.pid, flush=True)
        assert self.start["schema"] == "pcgm-resident-agenda-v1", self.start

    def receive(self):
        assert select.select([self.p.stdout], [], [], 90)[0], "resident timed out"
        reply = self.p.stdout.readline()
        assert reply, self.p.stderr.read()
        print("RESIDENT OUT", reply.decode().rstrip(), flush=True)
        return json.loads(reply)

    def send(self, channel, frame, ok=True):
        data = (frame + "\n").encode()
        print("RESIDENT IN", channel, frame, flush=True)
        if channel == "read":
            self.p.stdin.write(data)
        else:
            os.write(self.w, data)
        reply = self.receive()
        assert reply["channel"] == channel and reply["ok"] == ok, reply
        return reply.get("payload")

    def close(self, kill=False):
        if kill:
            print("SIGKILL PID", self.p.pid, "without reading approval ACK", flush=True)
            self.p.kill()
        self.p.stdin.close()
        os.close(self.w)
        code = self.p.wait(timeout=90)
        if not kill:
            assert code == 0 and not self.p.stderr.read(), code


def permit(report, review=None):
    actor, head = report["actor"], report["revision_sha256"]
    review = review or report["review_sha256"]
    pin = digest(f"PCGM-LOCAL-AGENDA-APPROVAL-1\n{actor}\n{head}\n{review}\n".encode())
    return f"{actor} {head} {review} {pin}"


def frozen_answer(root, state, ticket, request):
    package, journal, lock, api, goals = [root / x for x in ("package", "journal", "lock", "api", "goals")]
    provider = root / "provider.cl"
    provider.write_bytes(independent.read_bytes())
    lock.write_bytes(run(cl, "lock", provider))
    api.write_bytes(run(cl, "project-api", provider, lock))
    package.write_bytes(run(cl, "project-pack", provider, lock, api))
    pkg = digest(package.read_bytes())
    goals.write_text("checked(17)\n")
    commit = json.loads(run(cl, "evidence-init", package, pkg, goals, journal,
                            wire=b"x batch inspection 0 ; observe independent_check checked(17)\n"))
    assert commit["ok"], commit
    snapshot = digest(journal.read_bytes())
    dest = root / "incoming" / "inspection.clef"
    dest.parent.mkdir()
    dest.write_bytes(run(cl, "evidence-freeze", package, pkg, goals, journal, snapshot))
    artifact = digest(dest.read_bytes())
    verified = json.loads(run(pcgm, "--frozen-question-review", state, ticket, request, dest, artifact, pkg, snapshot))
    return f"{artifact} {pkg} {snapshot} {verified['proof_sha256']}"


with TemporaryDirectory(prefix="pcgm-work-agenda-") as tmp:
    root = Path(tmp)
    state = root / "actor"
    run(pcgm, "--init-managed", source, state)
    expect_agenda(state, "insufficient_evidence")
    update(state, ":observe wrong_literal reading(other,17)\n:observe first reading(sensor,17)\n")
    selected = expect_agenda(state, "pending_approval", "ready", "17")
    update(state, ":observe parcel arrival(cargo)\n")
    tied = expect_agenda(state, "tied")
    assert tied["eligible_count"] == 2 and not read(state, "question_feed 0 16")["results"]
    update(state, ":observe dispute !reading(sensor,17)\n")
    expect_agenda(state, "pending_approval", "released", "cargo")
    update(state, ":withdraw parcel\n")
    expect_agenda(state, "contested_or_unverified_grounding")
    update(state, ":withdraw dispute\n")
    assert selected["revision_sha256"] != expect_agenda(state, "pending_approval", "ready", "17")["revision_sha256"]
    print("PASS discovery: empty, two distinct goals, typed variable projection, tied, contested, withdrawn")

    resident = Resident(state)
    auto = resident.start["agenda"]
    assert auto == read(state, "agenda") and not read(state, "question_feed 0 16")["results"]
    scope, actor = permit(auto), auto["actor"]
    resident.send("approval", "enroll_agenda " + permit(selected), ok=False)
    resident.send("approval", "enroll_agenda " + permit(auto, "0"*64), ok=False)
    resident.send("read", "enroll_agenda " + scope, ok=False)
    resident.send("approval", "agenda_receipt " + scope, ok=False)
    assert resident.send("read", "agenda_receipt " + scope)["status"] == "not_recorded"
    run(pcgm, "--resume", state, refused="state already has a writer")
    # Write an approval, observe the durable commit from a second reader, then
    # SIGKILL before reading the ACK. Reconcile the exact pin before any retry.
    os.write(resident.w, f"enroll_agenda {scope}\n".encode())
    deadline = time.monotonic() + 90
    while not read(state, "question_feed 0 16", concurrent=True)["results"]:
        assert time.monotonic() < deadline
        time.sleep(.03)
    resident.close(kill=True)
    resident = Resident(state)
    assert resident.start["agenda"]["reason"] == "already_ticketed"
    receipt = resident.send("read", "agenda_receipt " + scope)
    assert receipt["status"] == "recorded" and not receipt["writes_state"]
    saved = state.read_bytes()
    ticket = receipt["ticket"]
    again = resident.send("approval", "enroll_agenda " + scope)
    assert not again["writes_state"] and again["ticket"] == ticket and state.read_bytes() == saved
    q, = read(state, "question_feed 0 16")["results"]
    assert q["id"] == ticket and q["needed"]["predicate"] == "checked"
    request = q["request_sha256"]
    frozen = frozen_answer(root, state, ticket, request)
    resident.close()
    update(state, ":restore dispute\n")
    assert read(state, "question " + ticket)["results"][0]["status"] == "superseded"
    resident = Resident(state)
    before = state.read_bytes()
    resident.send("approval", f"answer {actor} {resident.start['head_sha256']} {ticket} {request} inspection {frozen}", ok=False)
    assert resident.send("read", "agenda_receipt " + scope)["ticket"] == ticket and before == state.read_bytes()
    resident.close()
    update(state, ":withdraw dispute\n")
    resumed = read(state, "question " + ticket)["results"][0]
    assert resumed["status"] == "open" and resumed["request_sha256"] == request
    resident = Resident(state)
    approved = f"answer {actor} {resident.start['head_sha256']} {ticket} {request} inspection {frozen}"
    answer = resident.send("approval", approved)
    assert answer["writes_state"] and answer["next_agenda"]["reason"] == "already_decided", answer
    key = f"answer_receipt {actor} {ticket} {request} {frozen}"
    assert resident.send("read", key)["status"] == "recorded"
    assert read(state, "proof ready(17)")["results"][0]["status"] == "POSITIVE"
    resident.close()
    update(state, ":observe contrary !checked(17)\n")
    both = read(state, "proof ready(17)")["results"][0]
    assert both["status"] == "CONFLICT" and both["negative"]["supported"] and both["positive"]["supported"]
    update(state, f":withdraw {answer['observation']}\n")
    assert read(state, "proof ready(17)")["results"][0]["status"] == "NEGATIVE"
    update(state, ":withdraw contrary\n")
    reopened, = read(state, "question_feed 0 16")["results"]
    assert reopened["id"] == ticket and reopened["status"] == "open"
    assert read(state, "proof ready(17)")["results"][0]["status"] == "UNKNOWN"
    resident = Resident(state)
    assert resident.start["actor"] == actor and resident.send("read", key)["status"] == "withdrawn"
    before = state.read_bytes()
    retry = resident.send("approval", f"answer {actor} {resident.start['head_sha256']} {ticket} {request} inspection {frozen}")
    assert not retry["writes_state"] and state.read_bytes() == before
    resident.close()
    print("PASS resident: unsolicited start, separate approval, lost enrollment ACK/SIGKILL, exact read-only recovery, one ticket")
    print("PASS evidence: independent native CL freeze, same-process answer, reschedule, four proof states, withdrawn replay")

    partial = root / "partial"
    run(pcgm, "--init-managed", source, partial, wire=b":observe calibration_seen calibration(alpha)\n")
    expect_agenda(partial, "no_distinguishing_gap")
    update(partial, ":observe permission allowed(alpha)\n")
    review = expect_agenda(partial, "pending_approval", "calibrated", "alpha")
    assert review["proposed_review"]["investigation"]["premise"]["predicate"] == "measured"
    resident = Resident(partial)
    enrolled = resident.send("approval", "enroll_agenda " + permit(review))
    assert enrolled["next_agenda"]["reason"] == "already_ticketed"
    resident.close()
    update(partial, ":observe doubt !allowed(alpha)\n")
    expect_agenda(partial, "contested_dependencies")
    assert read(partial, "question " + enrolled["ticket"])["results"][0]["status"] == "superseded"
    update(partial, ":withdraw doubt\n")
    update(partial, ":withdraw permission\n")
    expect_agenda(partial, "no_distinguishing_gap")
    assert read(partial, "question " + enrolled["ticket"])["results"][0]["status"] == "superseded"
    update(partial, ":restore permission\n")
    reusable, = read(partial, "question_feed 0 16")["results"]
    assert reusable["status"] == "open" and reusable["id"] == enrolled["ticket"]
    large = root / "many"
    run(pcgm, "--init-managed", source, large, wire="".join(f":observe a{i} arrival(item{i})\n" for i in range(17)).encode())
    limited = expect_agenda(large, "scan_truncated")
    assert not limited["search_complete"] and limited["eligible_count"] is None and limited["limit"] == "grounded_targets"
    assert not read(large, "question_feed 0 16")["results"]
    print("PASS partial support recomputes a distinguishing gap; withdrawal and bounded scan publish no approval")
