"""Run from SOURCE: python3 handoff-checks/repair-check.py ./pcgm-alpha"""
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory


binary = Path(sys.argv[1]).resolve(strict=True)
fixtures = Path(__file__).resolve().parents[1] / "fixtures"
policy = (fixtures / "repair-parcels.cl").read_text()
observations = (fixtures / "repair-parcels.observations").read_text().splitlines()


def run(*args, commands=()):
    proc = subprocess.run([binary, *args], input="".join(x + "\n" for x in commands),
                          text=True, capture_output=True, timeout=20)
    assert proc.returncode == 0 and not proc.stderr and "QUERY_ERROR " not in proc.stdout, (proc.args, proc.stdout, proc.stderr)
    return proc.stdout


def init(root, name, program, rows):
    path, source = root / name, root / (name + ".cl")
    source.write_text(program)
    run("--init-managed", source, path, commands=rows)
    return path


def split_state(path):
    head, source = path.read_bytes().split(b"\nsource\n", 1)
    magic, _, actor, *events = head.splitlines()
    assert magic == b"PCGM-STATE-1"
    return actor.decode(), events, source


def proof(path, prop):
    raw = run("--read-channel", path, commands=["a proof " + prop])
    return json.loads(raw)["payload"]["results"][0]["status"]


def ranked(receipt, kind, slot=0):
    return [o for o in receipt["decision"]["options"] if o["kind"] == kind][slot]


def selected(receipt):
    decision = receipt["decision"]
    idx = decision["selected"]
    return decision["options"][idx]["kind"] if idx is not None else None


def check_raw(label, path, command=":repair_compare"):
    raw = run("--resume", path, commands=[command])
    record, = [line for line in raw.splitlines() if line.startswith("{")]
    print(label, record, flush=True)
    return json.loads(record)


with TemporaryDirectory(prefix="pcgm-repair-") as tmp:
    root = Path(tmp)
    first = init(root, "single", policy, observations[:2])
    original = first.read_bytes()
    single = check_raw("single_witness", first, ":repair_step")
    assert not single["writes_state"] and selected(single) == "stay"
    assert "fewer than two" in ranked(single, "rewrite")["blocked_reason"] and first.read_bytes() == original
    assert single["knowledge_review"]["premise"]["predicate"] == "packed"
    assert single["knowledge_review"]["ticket"] is None
    assert [x["status"] for x in single["knowledge_review"]["hypotheses"]] == ["POSITIVE", "UNKNOWN"]

    # Two new subjects occur only in incoming evidence. Fixed review cases
    # contain neither name and the host supplies no candidate rule or subject.
    fresh_rows = [":observe fault_v stalled(violet)", ":observe scan_v scanned(violet)",
                  ":observe fault_w stalled(white)", ":observe scan_w scanned(white)",
                  ":observe check_sample scanned(copper)"]
    unnamed = init(root, "novel", policy, fresh_rows)
    discovered = check_raw("unlisted_stall_subjects", unnamed, ":repair_step")
    assert discovered["writes_state"] and set(discovered["rule_reviews"][-1]["stalled_cases"]) == {
        "release(violet)", "release(white)"}
    assert proof(unnamed, "release(white)") == proof(unnamed, "release(copper)") == "POSITIVE"

    # Actually compile and evaluate the bad generalization. The negative
    # control becomes conflicted: the candidate cannot write even if wishes improve.
    incorrect = init(root, "unsafe", policy, observations + [":observe scan_veto scanned(crushed)"])
    original = incorrect.read_bytes()
    denied = check_raw("counterexample_rejection", incorrect, ":repair_step")
    trial = ranked(denied, "rewrite")
    assert trial["wishes"] == 3 and not trial["eligible"]
    assert denied["rule_reviews"][-1]["compiled_cl_slice_sha256"]
    assert any(x["expected"] == "NEGATIVE" and x["after"] == "CONFLICT" for x in trial["criteria"])
    assert not denied["writes_state"] and original == incorrect.read_bytes()

    # A currently dormant downstream rule would affect another predicate after
    # a future observation. The candidate must be refused before this happens.
    downstream = init(root, "outside", policy + "\n: future(sym).\nfuture($x) <- release($x) & note($x).\n", observations)
    guarded = check_raw("future_scope_guard", downstream, ":repair_step")
    assert not guarded["writes_state"] and "downstream" in ranked(guarded, "rewrite")["blocked_reason"]

    # The wrong scope is declared first so that the chooser cannot select the
    # first proposal by construction.
    second = (fixtures / "repair-second-scope.cl").read_text()
    additions = [":observe second_a delayed(green)", ":observe second_b delayed(gold)",
                 ":observe second_scan_a indexed(green)", ":observe second_scan_b indexed(gold)"]
    # The negative input is later withdrawn, which makes this initially wrong
    # candidate legal at exactly the same time as rolling back the first change.
    initial = observations + additions + [":observe bad_scan indexed(held)"]
    path = init(root, "managed", second + "\n" + policy, initial)
    identity, prefix, source_before = split_state(path)
    pid_before = None
    with subprocess.Popen([binary, "--resume", path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, bufsize=1) as writer:
        try:
            pid_before = writer.pid
            assert select.select([writer.stdout], [], [], 10)[0]
            assert "individual=" + identity in writer.stdout.readline()

            def command(line):
                writer.stdin.write(line + "\n:plans\n")
                writer.stdin.flush()
                rows = []
                # The engine flushes every insertion; Python's buffered reader
                # can already hold following lines after one descriptor wakeup.
                assert select.select([writer.stdout], [], [], 20)[0]
                for row in writer.stdout:
                    row = row.rstrip("\n")
                    assert not row.startswith("QUERY_ERROR"), row
                    if row.startswith("plans_end "):
                        return rows
                    rows.append(row)
                raise AssertionError("writer closed before command finished")

            def live(tag, operation):
                raw, = [x for x in command(operation) if x.startswith("{")]
                print(tag, raw, flush=True)
                return json.loads(raw)

            old = path.read_bytes()
            preview = live("comparison_before", ":repair_compare")
            assert selected(preview) == "rewrite" and not preview["writes_state"] and old == path.read_bytes()
            assert set(o["kind"] for o in preview["decision"]["options"]) == {"stay", "rollback", "rewrite", "knowledge"}
            assert not ranked(preview, "rewrite", 0)["eligible"] and ranked(preview, "rewrite", 1)["eligible"]
            evidence = preview["rule_reviews"][-1]
            assert set(evidence["stalled_cases"]) == {"release(amber)", "release(blue)"}
            assert set(evidence["proof_origins"]) == {"obs:stall_a", "obs:stall_b", "obs:scan_a", "obs:scan_b"}
            assert proof(path, "release(copper)") == "UNKNOWN"
            accepted = live("same_pid_rule_commit", ":repair_step")
            assert accepted["writes_state"] and accepted["actor"] == identity and selected(accepted) == "rewrite"
            assert accepted["basis_sha256"] == preview["basis_sha256"] == hashlib.sha256(old).hexdigest()
            assert proof(path, "release(copper)") == "POSITIVE" and proof(path, "release(crushed)") == "NEGATIVE"
            assert "release(copper)" in "\n".join(command(":explain release(copper)"))
            actor_after, events_after, source_after = split_state(path)
            assert actor_after == identity and events_after[:len(prefix)] == prefix
            proposal = bytes.fromhex(next(e for e in events_after[len(prefix):] if e.startswith(b"proposal ")).split()[-1].decode())
            assert source_after == source_before + b"\n" + proposal
            assert proposal.endswith(b"release($x) <- scanned($x).\n")
            competitor = subprocess.run([binary, "--resume", path], capture_output=True, timeout=10)
            assert competitor.returncode and b"already has a writer" in competitor.stderr

            saved = path.read_bytes()
            replay = live("unchanged_on_next_tick", ":repair_step")
            assert selected(replay) == "stay" and not replay["writes_state"] and saved == path.read_bytes()
            command(":withdraw bad_scan")
            peers = live("two_legal_alternatives", ":repair_compare")
            assert ranked(peers, "rollback")["eligible"] and ranked(peers, "rewrite", 0)["eligible"]
            assert selected(peers) == "rewrite" and not peers["writes_state"]
            # New experience after publication must survive the rollback.
            command(":observe later note(later)")
            command(":observe scanner_fault scanned(crushed)")
            assert proof(path, "release(crushed)") == "CONFLICT"
            _, old_events, old_source = split_state(path)
            rollback = live("same_pid_rollback", ":repair_step")
            assert rollback["writes_state"] and selected(rollback) == "rollback"
            assert rollback["actor"] == identity and writer.pid == pid_before and writer.poll() is None
            actor_final, events_final, source_final = split_state(path)
            assert actor_final == identity and events_final[:len(old_events)] == old_events
            assert source_final == source_before + old_source[len(source_after):]
            assert events_final[len(old_events)].startswith(b"revert ")
            assert proof(path, "note(later)") == "POSITIVE" and proof(path, "release(crushed)") == "NEGATIVE"
            assert proof(path, "release(copper)") == "UNKNOWN"
            print(json.dumps({"writer_pid": writer.pid, "actor": identity, "prior_events_retained": len(old_events),
                              "events_after_rollback": len(events_final), "post_update_observation": "later",
                              "original_rule_source_and_later_input_bytes_match": True}), flush=True)
        finally:
            writer.stdin.close()
            if writer.wait(timeout=15) or writer.stderr.read():
                raise AssertionError("managed writer failed")
    cold_bytes = path.read_bytes()
    assert "individual=" + identity in run("--inspect", path)
    saved = run("--resume", path, commands=[":decision_receipt " + accepted["decision_event"],
                                            ":decision_receipt " + rollback["decision_event"]])
    recorded = [json.loads(row) for row in saved.splitlines() if row.startswith("{")]
    assert recorded == [accepted["decision"], rollback["decision"]]
    assert path.read_bytes() == cold_bytes and proof(path, "note(later)") == "POSITIVE"
print("PASS: scoped native CL repair on repeated stalls; two signed controls, rejected candidate, "
      "four-way comparison, two legal alternatives, atomic live replacement and lossless rollback.")
