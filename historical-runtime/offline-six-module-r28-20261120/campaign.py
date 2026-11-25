"""One isolated new identity, one real fixture request and one M5 action."""
from contextlib import closing
import os
import subprocess
import sys
import time
from uuid import uuid4
from common import (ROOT, DB, FIXTURES, NAMES, MODE, COMMANDS, PREVIEW, TEST_SOURCE, canonical, child,
                    db_open, digest, fingerprint, json_file, need, parse, put, regular, sha)
import bridge

RUN = ROOT / "run"


def birth(plan, pin, pins):
    import base
    from r12_birth import birth as create
    need(RUN.is_dir() and not (RUN/"world").exists(), "FRESH_WORLD")
    cfg = base.read(base.PACKAGE/"r12-protocol.json")
    np = base.enable_numeric(pins)
    life = create(RUN/"world",plan["identity"],cfg["slots"]["amber"],cfg,np)
    state = life.individual.state
    need(state["id"] == plan["identity"] and state["tick"] == 0 and life.phase == "READY"
         and not state["requested_actions"], "BIRTH_CHECKPOINT")
    return dict(identity=state["id"], tick=state["tick"], phase=life.phase, release=pin, pid=os.getpid(),
                joint_sha256=sha(life.path.read_bytes()), generation=life.generation,
                modules=base.project_origins(pins))


def exchange(role, label, wire, pin):
    raw = (canonical(wire)+"\n").encode()
    put(RUN/(label+".in"), raw)
    if role == "api":
        proc = child("backend_api.py",pin)
    else:
        need(role == "birth", "ROLE")
        proc = subprocess.Popen([sys.executable,"-X","utf8","-I","-S","-B",str(ROOT/"entry.py"),role,pin],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, cwd=ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW, env={"SystemRoot":os.environ["SystemRoot"]})
    json_file("run/"+label+".start.json",dict(pid=proc.pid,parent=os.getpid(),start_ns=time.monotonic_ns()))
    out, err = proc.communicate(raw, timeout=60)
    put(RUN/(label+".out"), out)
    put(RUN/(label+".err"), err)
    json_file("run/"+label+".exit.json",dict(pid=proc.pid,exit=proc.returncode,exit_ns=time.monotonic_ns()))
    need(proc.returncode == 0 and not err and 0<len(out)<=65536, "UNCERTAIN_"+label)
    return parse(out)


def verify_inventory(plan):
    item, = plan["items"]
    path = FIXTURES/item["name"]
    info = path.lstat()
    regular(info)
    need(str(FIXTURES.stat().st_ino) == plan["directory_id"] and [p.name for p in FIXTURES.iterdir()] == list(NAMES)
         and fingerprint(info) == item["object"] and path.resolve() == path, "FIXTURE_METADATA_CHANGED")
    return fingerprint(info)


def run(plan, pin, pins):
    from world_link import practice, apply_receipt
    from backend_api import reserve_local
    from cli_frozen import Shell
    RUN.mkdir(exist_ok=False)
    json_file("run/before.json",verify_inventory(plan))
    b = exchange("birth","00-birth",{},pin)
    json_file("run/birth.json",b)
    gate = practice(plan, pin, pins)
    json_file("run/decision.json",gate)
    class StateView:
        def snapshot(self):
            return exchange("api",self.label,dict(op="status"),pin)["snapshot"]
    view = StateView()
    shell = Shell(view)
    view.label = "01-status"
    snap = shell.handle("状态")["snapshot"]
    need(snap["identity"] == b["identity"] and snap["revision"] == 0 and not snap["receipts"]
         and snap["stage"] == "READY_SYNTHETIC_READ", "NOT_FRESH")
    def propose(label, cmd):
        nonce = uuid4().hex
        resp = exchange("api",label,dict(op="propose",command=cmd,state_sha256=digest(snap),nonce=nonce),pin)
        p = resp["proposal"]
        need(resp["status"] == "CANDIDATE" and resp["proposal_sha256"] == digest(p)
             and p["candidate_nonce"] == nonce and p["state_sha256"] == digest(snap)
             and p["identity"] == plan["identity"] and p["instance"] == plan["instance"]
             and p["envelope"]["request"] == plan["items"][0]["binding"]["request"], "PROPOSAL")
        return p
    preview = propose("03-translation",PREVIEW)
    need(preview["preflight_only"] and preview["envelope"]["route"]=="offline_translation", "M3_PREVIEW")
    p = propose("04-native",gate["command"])
    need(p["decision_sha256"] == digest(gate), "NATIVE_DECISION_BINDING")
    need(not p["preflight_only"] and p["envelope"]["route"] == "native", "NATIVE_ONLY")
    view.label = "05-proposed-state"
    need(shell.handle("状态")["snapshot"] == snap, "EARLY_STATE_CHANGE")
    base = dict(op="confirm",proposal=p,proposal_sha256=digest(p),confirmation="确认 "+p["proposal_id"],
                confirmation_source=TEST_SOURCE)
    with closing(db_open(pin)) as db:
        attempt = reserve_local(db,plan,base)
    wire = dict(**base, attempt=attempt)
    json_file("run/planned.json",bridge.enroll(plan,wire,pin))
    response = exchange("api","06-confirm",wire,pin)
    need(response.get("status")=="VERIFIED" and not response["readback_only"]
         and bridge.settled(plan,wire,pin)==response, "UNCONFIRMED_ACTION")
    view.label = "07-receipts"
    final = shell.handle("回执")
    need(final["snapshot"]["receipts"] == [response["receipt_ref"]] and final["snapshot"]["stage"]=="COMPLETE"
         and final["snapshot"]["revision"] == 1, "UI_RECEIPT_VIEW")
    apply_receipt(plan, pin, wire)
    json_file("run/after.json",verify_inventory(plan))
    return dict(status="COMPLETED_DEVELOPMENT_FIXTURE", pid=os.getpid(), release=pin, identity=b["identity"],
                original_id=p["envelope"]["request"]["request_id"], receipt_ref=response["receipt_ref"],
                host_admission="NOT_GRANTED", lastJobID=None)


def duplicate(plan,pin):
    from backend_api import api
    wire = parse((RUN/"06-confirm.in").read_bytes())
    expected = bridge.settled(plan,wire,pin)
    before = [sha(p.read_bytes()) for p in (DB,bridge.M5)]
    with closing(db_open(pin)) as db:
        result = api(db,plan,wire,pin)
    after = [sha(p.read_bytes()) for p in (DB,bridge.M5)]
    need(before == after and result == {**expected, "readback_only":True}, "DUPLICATE")
    return dict(pid=os.getpid(),release=pin,response=result,before=before,after=after)
