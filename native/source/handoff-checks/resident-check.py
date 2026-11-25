"""Exercise separate host pipes and the managed writer boundary with native PCGM."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from tempfile import TemporaryDirectory

binary, cl = [Path(p).resolve(strict=True) for p in sys.argv[1:3]]
lost_ack = len(sys.argv)==4 and sys.argv[3]=="lost-ack"
def digest(data):
    return hashlib.sha256(data).hexdigest()
def call(*args, wire=b"", expect=None):
    p = subprocess.run([binary,*args], input=wire, capture_output=True, timeout=10)
    if expect:
        assert p.returncode and expect in p.stderr.decode(), (p.args,p.stdout,p.stderr)
    else:
        assert p.returncode == 0 and not p.stderr, (p.args,p.stdout,p.stderr)
    return p.stdout

with TemporaryDirectory() as folder:
    root = Path(folder)
    state = root/"actor"
    source = root/"engine.cl"
    source.write_text(""": raw(sym).
: anchor(sym).
: examined(sym).
: ready(sym).
: irrelevant(sym).
anchor($x) <- raw($x).
ready($x) <- anchor($x) & examined($x).
!ready($x) <- !examined($x).
""")
    call("--init-managed",source,state,wire=b":observe only raw(a)\n")
    def inspect(frame):
        before=state.read_bytes()
        obj=json.loads(call("--read-channel",state,wire=("x "+frame+"\n").encode()))
        assert obj["ok"] and before==state.read_bytes()
        return obj["payload"]
    def start(r,w):
        p=subprocess.Popen([binary,"--resume-obligation-local",state,str(r)],stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(r,),bufsize=0)
        os.close(r)
        def receive():
            assert select.select([p.stdout],[],[],12)[0], "no framed response"
            line=p.stdout.readline()
            assert line, (p.poll(),p.stderr.read() if p.poll() is not None else "")
            return json.loads(line)
        def send(channel,frame):
            data=frame.encode()+b"\n"
            if channel=="read": p.stdin.write(data)
            else: os.write(w,data)
            reply=receive()
            assert reply["channel"]==channel, reply
            return reply
        return p,send,receive
    def permit(startup, review, *, head=None, pin=None):
        actor=startup["actor"]
        head=head or startup["head_sha256"]
        proof=digest(json.dumps(review,ensure_ascii=False,separators=(",",":")).encode())
        body=f"PCGM-LOCAL-OBLIGATION-APPROVAL-1\n{actor}\n{head}\nanchor ready\n{proof}\n".encode()
        return f"enroll {actor} {head} anchor ready {proof} {pin or digest(body)}"
    r,w=os.pipe()
    q=subprocess.Popen([binary,"--resume-obligation-local",state,str(r)],stdin=r,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(r,))
    try:
        assert "independent pipes" in q.communicate(timeout=10)[1].decode() and q.returncode
    finally:
        os.close(r)
        os.close(w)
    r,w=os.pipe()
    p,send,receive=start(r,w)
    try:
        boot=receive();initial=state.read_bytes()
        assert boot["schema"]=="pcgm-resident-obligation-v2"
        read=send("read","review anchor ready")
        assert read["ok"] and read["payload"]["eligible_count"]==1
        frame=permit(boot,read["payload"])
        assert not send("read",frame)["ok"]
        assert not send("read",":observe spoof examined(a)")["ok"]
        assert not send("approval",":observe spoof examined(a)")["ok"]
        assert not send("approval","review anchor ready")["ok"]
        assert not send("approval",permit(boot,read["payload"],head="0"*64))["ok"]
        assert not send("approval",permit(boot,read["payload"],pin="0"*64))["ok"]
        assert not send("approval","not_a_frame"*100)["ok"]
        call("--resume",state,expect="state already has a writer")
        assert state.read_bytes()==initial and not inspect("question_feed 0 16")["results"]
        res=send("approval",frame)
        assert res["ok"] and res["payload"]["status"]=="enrolled",res
        ticket=res["payload"]["ticket"]
        committed=state.read_bytes()
        assert send("approval",frame)["payload"]["status"]=="already_enrolled"
        assert state.read_bytes()==committed and p.poll() is None
        q,=inspect("question_feed 0 16")["results"]
        assert q["id"]==ticket and q["status"]=="open"
        assert inspect("proof ready(a)")["results"][0]["status"]=="UNKNOWN"
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
        pkg_pin=digest(pkg.read_bytes())
        assert json.loads(cl_run("evidence-init",pkg,pkg_pin,goals,journal,
                                 wire=b"x batch independent 0 ; observe revised examined(a)\n"))["ok"]
        snapshot=digest(journal.read_bytes())
        frozen=inbox/"approval.clef";frozen.write_bytes(cl_run("evidence-freeze",pkg,pkg_pin,goals,journal,snapshot))
        frozen_bytes=frozen.read_bytes();frozen_pin=digest(frozen_bytes)
        hold=state.read_bytes()
        proof=json.loads(call("--frozen-question-review",state,ticket,q["request_sha256"],frozen,frozen_pin,pkg_pin,snapshot))
        assert state.read_bytes()==hold
        pid=p.pid
        answer_head=res["payload"]["head_sha256"]
        def answer_frame(head,proof_sha=None,who=boot["actor"]):
            reviewed=proof_sha or proof["proof_sha256"]
            return f"answer {who} {head} {ticket} {q['request_sha256']} approval {frozen_pin} {pkg_pin} {snapshot} {reviewed}"
        req=answer_frame(answer_head)
        def receipt_frame(who=boot["actor"],proof_sha=proof["proof_sha256"]):
            return f"answer_receipt {who} {ticket} {q['request_sha256']} {frozen_pin} {pkg_pin} {snapshot} {proof_sha}"
        def receipt(status):
            res=send("read",receipt_frame())
            assert res["ok"] and res["payload"]["status"]==status and not res["payload"]["writes_state"],res
            return res["payload"]
        missing=receipt("not_recorded")
        assert missing["observation"] is None and missing["head_sha256"]==answer_head
        assert not send("read",receipt_frame(who="0"*32))["ok"]
        assert not send("approval",receipt_frame())["ok"]
        assert state.read_bytes()==committed
        assert not send("read",req)["ok"] and state.read_bytes()==committed
        assert not send("approval",answer_frame(answer_head,who="0"*32))["ok"]
        assert not send("approval",answer_frame(answer_head,"0"*64))["ok"]
        frozen.write_bytes(b"changed")
        assert not send("approval",req)["ok"] and state.read_bytes()==committed
        frozen.unlink()
        frozen.write_bytes(frozen_bytes)
        if lost_ack:
            os.write(w,req.encode()+b"\n")
            limit=time.monotonic()+8
            while time.monotonic()<limit:
                if inspect("proof ready(a)")["results"][0]["status"]=="POSITIVE": break
                time.sleep(.03)
            else: raise AssertionError("answer was not durable before process exit")
            p.kill();p.wait(timeout=10)
            # Intentionally never consume the original responder's ACK.
            os.close(w);w=-1
            r,w=os.pipe();p,send,receive=start(r,w)
            assert receive()["actor"]==boot["actor"]
            durable=receipt("recorded")
            assert durable["observation"].startswith("bundle_") and not durable["writes_state"]
            persisted=state.read_bytes()
            assert not send("approval",req)["ok"]
            assert state.read_bytes()==persisted
            p.stdin.close();os.close(w);w=-1
            assert p.wait(timeout=10)==0 and not p.stderr.read()
            print("PASS: committed answer with undelivered ACK recovered read-only after native writer is killed")
            sys.exit(0)
        admitted=send("approval",req)
        assert admitted["ok"] and admitted["payload"]["writes_state"],admitted
        answer=admitted["payload"]
        observation=answer["observation"]
        assert receipt("recorded")["observation"]==observation
        other=send("read",receipt_frame(proof_sha="0"*64))
        assert other["ok"] and other["payload"]["status"]=="not_recorded"
        assert observation.startswith("bundle_") and not answer["outbound"]
        assert p.poll() is None and p.pid==pid
        committed=state.read_bytes()
        assert not send("approval",req)["ok"]
        retry=send("approval",answer_frame(answer["head_sha256"]))
        assert retry["ok"] and not retry["payload"]["writes_state"] and retry["payload"]["observation"]==observation
        assert inspect("question "+ticket)["results"][0]["status"]=="answered"
        assert inspect("proof ready(a)")["results"][0]["status"]=="POSITIVE"
        # Missing newline makes this incomplete even if otherwise authorized.
        os.write(w,answer_frame(answer["head_sha256"]).encode())
        os.close(w);w=-1
        assert receive()["error"]=="unterminated resident frame"
        p.stdin.close()
        assert p.wait(timeout=10)==0 and not p.stderr.read() and state.read_bytes()==committed
    finally:
        if w>=0: os.close(w)
        if p.poll() is None: p.kill();p.wait()
    call("--resume",state,wire=f":withdraw {observation}\n".encode())
    assert inspect("question "+ticket)["results"][0]["status"]=="open"
    assert inspect("proof ready(a)")["results"][0]["status"]=="UNKNOWN"
    committed=state.read_bytes()
    r,w=os.pipe()
    p,send,receive=start(r,w)
    try:
        assert receive()["actor"]==boot["actor"]
        res=send("approval",frame)
        assert res["ok"] and res["payload"]["ticket"]==ticket and not res["payload"]["writes_state"]
        assert state.read_bytes()==committed
        assert receipt("withdrawn")["observation"]==observation
        retry=send("approval",answer_frame(res["payload"]["head_sha256"]))
        assert retry["ok"] and not retry["payload"]["writes_state"]
        assert inspect("proof ready(a)")["results"][0]["status"]=="UNKNOWN" and state.read_bytes()==committed
        p.stdin.close()
        os.close(w);w=-1
        assert p.wait(timeout=10)==0 and not p.stderr.read()
    finally:
        if w>=0: os.close(w)
        if p.poll() is None: p.kill();p.wait()
print("PASS: same-PID scoped enrollment and independently proven answer, stale/wrong-source/tamper denial, replay after withdrawal cannot reassert")
