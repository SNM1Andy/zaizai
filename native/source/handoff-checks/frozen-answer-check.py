from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

pc, cl = (Path(p).resolve(strict=True) for p in sys.argv[1:3])
def h(b): return sha256(b).hexdigest()
def run(*args, wire=b"", error=""):
    p = subprocess.run([pc, *args], input=wire, capture_output=True, timeout=40)
    if error:
        assert p.returncode != 0 and not p.stdout and error in p.stderr.decode(), (p.args,p.stderr,p.stdout)
    else:
        assert p.returncode == 0 and not p.stderr, (p.args,p.stderr)
    return p.stdout

with TemporaryDirectory(prefix="native-scoped-approval-") as tmp:
    root=Path(tmp); source=root/"engine.cl"; state=root/"actor"
    source.write_text(""": raw(sym).
: anchor(sym).
: examined(sym).
: ready(sym).
: irrelevant(sym).
anchor($x) <- raw($x).
ready($x) <- anchor($x) & examined($x).
!ready($x) <- !examined($x).
""")
    run("--init-managed",source,state,wire=b":observe seed raw(a)\n")
    def read(frame, at=state):
        before=at.read_bytes()
        ans=json.loads(run("--read-channel",at,wire=("p "+frame+"\n").encode()))
        assert ans["ok"] and at.read_bytes()==before
        return ans["payload"]
    actor=read("storage")["state"]["individual"]
    def rev(at=state):return read("storage",at)["logical_sha256"]
    def lookup():
        r=rev();data=read(f"anchored_obligation {r} anchor ready")
        assert data["eligible_count"]==1 and not data["writes_state"]
        exact=json.dumps(data,ensure_ascii=False,separators=(",",":")).encode()
        return r,h(exact)
    def approve(pair,who=actor):
        r,pin=pair
        return f"PCGM-LOCAL-OBLIGATION-APPROVAL-1\n{who}\n{r}\nanchor ready\n{pin}\n".encode()
    file=root/"permit"
    def enroll(raw, *, error="", digest=None, at=state):
        file.write_bytes(raw)
        result=run("--enroll-anchored-obligation",at,file,digest or h(raw),error=error)
        return json.loads(result) if result else None
    old=lookup()
    content=state.read_bytes()
    assert not read("question_feed 0 16")["results"]
    enroll(approve(old),digest="0"*64,error="approval pin mismatch")
    enroll(approve(old,"0"*32),error="requires active managed owner")
    enroll(approve((old[0],"0"*64)),error="does not match current grounded review")
    assert state.read_bytes()==content
    run("--resume",state,wire=b":observe unrelated irrelevant(a)\n")
    stable=state.read_bytes()
    enroll(approve(old),error="approval is stale")
    assert state.read_bytes()==stable
    fresh=approve(lookup())
    first=enroll(fresh); ticket=first["ticket"]
    assert first["status"]=="enrolled" and first["writes_state"] and first["head_sha256"]==rev()
    assert first["actor"]==actor and not first["asserts_fact"] and not first["outbound"]
    current=state.read_bytes()
    retry=enroll(fresh)
    assert retry["status"]=="already_enrolled" and not retry["writes_state"] and retry["ticket"]==ticket
    assert state.read_bytes()==current
    q,=read("question_feed 0 16")["results"]
    assert q["id"]==ticket and q["status"]=="open" and q["needed"]["predicate"]=="examined",q
    inbox=root/"incoming";inbox.mkdir()
    independent=root/"independent.cl"
    independent.write_text("module independent.\nexport examined.\n: examined(sym).\n")
    def cl_run(*args,wire=b""):
        p=subprocess.run([cl,*args],input=wire,capture_output=True,timeout=30)
        assert p.returncode==0 and not p.stderr,(p.args,p.stderr)
        return p.stdout
    lock,api,pkg,goals,journal=[root/p for p in ("lock","api","package","goals","journal")]
    lock.write_bytes(cl_run("lock",independent));api.write_bytes(cl_run("project-api",independent,lock))
    pkg.write_bytes(cl_run("project-pack",independent,lock,api))
    goals.write_text("examined(a)\n")
    pkg_pin=h(pkg.read_bytes())
    assert json.loads(cl_run("evidence-init",pkg,pkg_pin,goals,journal,
                             wire=b"x batch independent 0 ; observe revised examined(a)\n"))["ok"]
    snapshot=h(journal.read_bytes())
    frozen=inbox/"approval.clef";frozen.write_bytes(cl_run("evidence-freeze",pkg,pkg_pin,goals,journal,snapshot))
    frozen_pin=h(frozen.read_bytes())
    hold=state.read_bytes()
    proof=json.loads(run("--frozen-question-review",state,ticket,q["request_sha256"],frozen,frozen_pin,pkg_pin,snapshot))
    assert state.read_bytes()==hold
    frame=f":admit_frozen {ticket} {q['request_sha256']} approval {frozen_pin} {pkg_pin} {snapshot} {proof['proof_sha256']}\n".encode()
    delivered=run("--resume",state,wire=frame)
    row=next(x for x in delivered.decode().splitlines() if x.startswith("frozen_evidence_committed "))
    observation=row.split()[2]
    assert observation.startswith("bundle_"),row
    assert read("question "+ticket)["results"][0]["status"]=="answered"
    assert read("proof ready(a)")["results"][0]["status"]=="POSITIVE"
    answered=state.read_bytes()
    assert b"frozen_evidence_unchanged" in run("--resume",state,wire=frame) and state.read_bytes()==answered
    run("--resume",state,wire=f":withdraw {observation}\n".encode())
    assert read("question "+ticket)["results"][0]["status"]=="open"
    assert read("proof ready(a)")["results"][0]["status"]=="UNKNOWN"
    withdrawn=state.read_bytes()
    assert b"frozen_evidence_unchanged" in run("--resume",state,wire=frame) and state.read_bytes()==withdrawn
    again=enroll(fresh)
    assert again["ticket"]==ticket and again["status"]=="already_enrolled"
    archive,cold=root/"archive",root/"cold"
    run("--export-complete",state,archive)
    run("--restore-copy",archive,cold)
    assert read("storage",cold)["state"]["individual"]==actor
    assert read("question "+ticket,cold)["results"][0]["status"]=="open"
    before=cold.read_bytes()
    enroll(fresh,at=cold,error="requires active managed owner")
    assert cold.read_bytes()==before
print("PASS: native exact approved question, independently compiled frozen answer, withdrawal and no duplicate after restart")
