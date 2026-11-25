import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

pc = Path(sys.argv[1]).resolve(strict=True)
def run(*args, wire=b""):
    p = subprocess.run([pc, *args], input=wire, capture_output=True, timeout=25)
    assert p.returncode == 0 and not p.stderr, (p.args, p.stderr)
    return p.stdout

with TemporaryDirectory(prefix="native-anchor-exact-") as location:
    d = Path(location)
    source = d / "model.cl"
    source.write_text(""": raw(sym).
: anchor(sym).
: examined(sym).
: ready(sym).
: unrelated(sym).
: diff_types(sym,i64).
anchor($x) <- raw($x).
ready($x) <- anchor($x) & examined($x).
!ready($x) <- !examined($x).
? ready(old).
""")
    state = d / "actor"
    run("--init-managed", source, state, wire=b":observe old raw(old)\n")
    def read(frame, at=state):
        s = at.read_bytes()
        result = json.loads(run("--read-channel", at, wire=("x " + frame + "\n").encode()))
        assert at.read_bytes() == s
        return result
    def current(at=state):
        return read("storage", at)["payload"]["logical_sha256"]
    def check(fromrel="anchor", torel="ready", at=state, expected=None):
        return read(f"anchored_obligation {expected or current(at)} {fromrel} {torel}", at)
    def emit(wire):
        run("--resume", state, wire=wire)
    def result(count, expected=None, at=state):
        found = check(at=at)["payload"]
        assert found["eligible_count"] == count, found
        assert not found["promotes_goal"] and not found["writes_state"] and not found["outbound"]
        if expected is None:
            assert found["proposed_review"] is None
        else:
            rec = found["proposed_review"]
            assert rec["current"]["status"] == "UNKNOWN"
            assert rec["current"]["goal"]["arguments"][0]["value"] == expected
            assert rec["investigation"]["premise"]["predicate"] == "examined"
            assert [b["consequence"]["status"] for b in rec["investigation"]["branches"]] == ["POSITIVE", "NEGATIVE"]
        return found
    result(0)
    assert not check("anchor", "unrelated")["ok"]
    assert not check("anchor", "diff_types")["ok"]
    assert not check(expected="*")["ok"]
    old = current()
    emit(b":observe a1 raw(a)\n")
    a = result(1, "a")
    assert not check(expected=old)["ok"]
    assert not read(f"obligation {current()} ready(a)")["ok"]
    emit(b":observe b1 raw(b)\n")
    result(2)
    emit(b":observe contradiction !anchor(b)\n")
    result(1, "a")
    emit(b":observe support examined(a)\n")
    result(0)
    emit(b":withdraw support\n")
    result(1, "a")
    archive, restored = d / "archive", d / "restored"
    run("--export-complete", state, archive)
    run("--restore-copy", archive, restored)
    assert result(1, "a", restored)["actor"] == a["actor"]
    assert not read("question_feed 0 8")["payload"]["results"]
    emit(b"".join(f":observe row{n} raw(other{n})\n".encode() for n in range(9)))
    assert not result(None)["search_complete"]
print("PASS: targetless grounded review, explicit type and native dependency, dispute, restore and bounded ambiguity")
