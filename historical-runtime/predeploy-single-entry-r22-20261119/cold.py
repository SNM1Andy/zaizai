"""Reconstruct a completed action from both closed databases, messages and original source."""
from contextlib import closing
import copy
import os
from pathlib import Path
import sqlite3
import sys

from common import (COMMANDS, DB, MODE, PREVIEW, ROOT, TEST_SOURCE, canonical, db_open,
                    digest, need, parse, sha)
import bridge
import r20_routes as routes

RUN = ROOT/"run"


def artifact(name):
    return parse((RUN/name).read_bytes())


def transcript(label):
    start = artifact(label+".start.json")
    end = artifact(label+".exit.json")
    need(start["pid"] == end["pid"] and end["exit"] == 0 and start["start_ns"] <= end["exit_ns"]
         and not (RUN/(label+".err")).read_bytes(), "EXCHANGE_"+label)
    return artifact(label+".in"), artifact(label+".out"), start, end


def check_language(db, plan, label, command, snap):
    from al01 import core
    translated = command == PREVIEW
    w, result, *_ = transcript(label)
    p = result["proposal"]
    stored, = db.execute("SELECT * FROM proposals WHERE nonce=?", (w["nonce"],)).fetchall()
    proof = parse(stored["proof"])
    need(w == dict(op="propose", command=command, nonce=p["candidate_nonce"], state_sha256=digest(snap))
         and stored["body"] == canonical(p) and stored["slot"]==0
         and result["status"]=="CANDIDATE" and stored["sha"] == result["proposal_sha256"] == digest(p)
         and digest(proof)==p["proof_sha256"] and proof["envelope"]==p["envelope"]
         and p["state_sha256"]==digest(snap) and p["command"]==command and p["preflight_only"]==translated,
         "PROPOSAL_PROOF")
    item, = plan["items"]
    want = dict(format=routes.FORMAT,route="offline_translation" if translated else "native",**item["binding"])
    raw = (ROOT/("offline.txt" if translated else item["cl_file"])).read_bytes()
    need(sha(raw)==p["input_sha256"]==proof["input_sha256"],"INPUT")
    if translated:
        report = proof["translation"]
        c, = report["candidates"]
        valid, = report["validation"]
        need(report["text"] == raw.decode().strip() == COMMANDS[0] and valid["passed"] and not valid["errors"]
             and valid["checks"]["real_cl"] and valid["checks"]["effects_exact"]
             and valid["candidate_id"]==c["candidate_id"]==item["binding"]["request"]["request_id"]
             and c["request"]==item["binding"]["request"] and c["provenance"]["authority"]=="NONE"
             and digest({k:v for k,v in c.items() if k!="candidate_sha256"})==c["candidate_sha256"]
             and report["counters"]["external_api_calls"]==report["counters"]["receipt_calls"]==0, "OFFLINE_PROVENANCE")
        want["translation"] = dict(input_sha256=sha(raw), candidate_sha256=c["candidate_sha256"])
        cl = routes.emit_source(want)
    else:
        cl = raw.decode()
        need(cl == routes.emit_source(want)+"\n" and proof["translation"] is None,"NATIVE_INPUT")
    vm = core.CVM(["emit"])
    tx = routes.prepare(vm,cl)
    env = routes.verify_tx(vm,tx,item["binding"],want["route"],want.get("translation"))
    need(env==want==p["envelope"] and proof["transaction"]==core.transaction_payload(tx)
         and proof["cl_sha256"]==sha(cl.encode()),"TRANSACTION")
    return p


def negative_tests(private, m5db, plan, pin, wire, cap, response):
    from backend_api import api
    cases = {}
    def reject(label, fn, reason):
        try:
            fn()
        except (ValueError,sqlite3.DatabaseError) as exc:
            need(str(exc)==reason, "WRONG_REJECTION_"+label+"_"+str(exc))
            cases[label]=reason
        else:
            raise AssertionError(label)
    with closing(sqlite3.connect(":memory:",isolation_level=None)) as mirror:
        mirror.row_factory = sqlite3.Row
        private.backup(mirror)
        bad = dict(wire, confirmation="确认 other")
        reject("confirmation", lambda:api(mirror,plan,bad,pin),"CONFIRMATION")
        bad = dict(wire,attempt={**wire["attempt"],"attempt_id":"other"})
        reject("attempt",lambda:api(mirror,plan,bad,pin),"ATTEMPT_BINDING")
        for state in ("CLAIMED","READING","UNKNOWN"):
            mirror.execute("UPDATE actions SET state=?,response=NULL", (state,))
            got = api(mirror,plan,wire,pin)
            need(got == dict(status="UNKNOWN",reason="CLAIM_ALREADY_COMMITTED",retry=False), "SPENT")
            cases[state]="UNKNOWN_NO_REPLAY"
    altered = copy.deepcopy(wire)
    altered["proposal"]["envelope"]["request"]["entry_ref"]="entry_"+"d"*32
    altered["proposal"]["envelope"]["request_sha256"]=digest(altered["proposal"]["envelope"]["request"])
    reject("rehashed_target",lambda:bridge.binding(plan,altered,pin),"M5_FULL_REQUEST")
    bad = {**cap,"file_before":{**cap["file_before"],"file_id":"0"}}
    reject("file_identity",lambda:bridge.validate_response(plan,wire,bad,response,cap["pid"],cap["ppid"]),
           "CAPTURE_FILE_BINDING")
    reject("receipt",lambda:bridge.validate_response(plan,wire,cap,{**response,"receipt_ref":"other"},
                                                     cap["pid"],cap["ppid"]), "RECEIPT_BINDING")
    reject("m5_already_spent",lambda:bridge.reserve(plan,wire,pin),"M5_NOT_FRESH")
    with closing(sqlite3.connect(":memory:",isolation_level=None)) as mirror:
        m5db.backup(mirror)
        mirror.execute("UPDATE action SET state='RESERVED',claim='synthetic-memory-claim'")
        finish = lambda:mirror.execute("UPDATE action SET state='COMPLETED',claim=NULL")
        mirror.execute("UPDATE r22_receipt SET pending_claim='other'")
        reject("wrong_m5_claim",finish,"R22_RECEIPT_AND_CLAIM_REQUIRED")
        mirror.execute("DELETE FROM r22_receipt")
        reject("no_m5_receipt",finish,"R22_RECEIPT_AND_CLAIM_REQUIRED")
    return cases


def verify(plan,pin,pins):
    import base
    import original_action
    from al01 import core
    from campaign import verify_inventory
    from backend_api import snapshot, check_base
    need(Path(original_action.__file__).resolve()==ROOT/"r14/bundle/lib/original_action.py" and
         base.sha(Path(original_action.__file__))==pins["files"]["lib/original_action.py"], "ORIGINAL_M5_SOURCE")
    need(verify_inventory(plan)==artifact("before.json")==artifact("after.json"), "FIXTURE_METADATA")
    for path in (DB,bridge.M5):
        need(not any(path.with_name(path.name+ext).exists() for ext in ("-journal","-shm","-wal")), "OPEN_SIDECAR")
    _, birth, bs, be = transcript("00-birth")
    status_in, status, _, _ = transcript("01-status")
    snap = status["snapshot"]
    need(status_in=={"op":"status"} and snap["stage"]=="READY_SYNTHETIC_READ" and snap["revision"]==0
         and snap["receipts"]==[] and snap["identity"]==birth["identity"]==plan["identity"]
         and snap["instance"]==plan["instance"] and birth==artifact("birth.json")
         and bs["pid"]==birth["pid"] and birth["release"]==pin, "FRESH_STATE")
    planned = artifact("planned.json")
    with closing(db_open(pin,readonly=True)) as private, closing(bridge.ro()) as db:
        for d in (private,db):
            need(d.execute("PRAGMA integrity_check").fetchone()[0]=="ok" and not d.execute(
                "PRAGMA foreign_key_check").fetchall(), "SQLITE_INTEGRITY")
        with closing(sqlite3.connect(":memory:")) as ref:
            ref.executescript((ROOT/"r14/bundle/components/m5.sql").read_text(encoding="utf8"))
            sql = "SELECT type,name,sql FROM sqlite_master WHERE tbl_name IN ('action','authority','binding') AND type IN ('table','index') ORDER BY type,name"
            need(ref.execute(sql).fetchall()==[tuple(row) for row in db.execute(sql)], "ORIGINAL_SCHEMA")
        need(private.execute("SELECT count(*) FROM proposals").fetchone()[0]==2, "PROPOSAL_COUNT")
        check_language(private,plan,"03-translation",PREVIEW,snap)
        p = check_language(private,plan,"04-native",COMMANDS[0],snap)
        need(transcript("05-proposed-state")[1]==status, "PRE_EFFECT_SNAPSHOT")
        wire,response,start,end = transcript("06-confirm")
        req = p["envelope"]["request"]
        oid = req["request_id"]
        confirm = {k:v for k,v in wire.items() if k!="attempt"}
        expected_base = dict(op="confirm",proposal=p,proposal_sha256=digest(p),confirmation="确认 "+p["proposal_id"],
                             confirmation_source=TEST_SOURCE)
        need(confirm==expected_base and check_base(private,plan,confirm)==0 and
             wire["attempt"]["request_sha256"]==digest(confirm), "CONFIRMED_BINDING")
        side, = private.execute("SELECT * FROM actions").fetchall()
        need(side["wire"]==canonical(wire) and side["attempt"]==canonical(wire["attempt"]) and
             side["state"]=="SETTLED" and side["response"]==canonical(response) and side["error"] is None
             and not side["stderr"] and side["exit_code"]==0 and side["parent"]==start["pid"], "PRIVATE_CAPTURE")
        cap = parse(side["stdout"])
        bridge.validate_response(plan,wire,cap,response,side["child"],start["pid"])
        body = bridge.binding(plan,wire,pin)
        bound = digest(body)
        need([tuple(r) for r in db.execute("SELECT * FROM authority")]==[(plan["instance"],)]
             and [tuple(r) for r in db.execute("SELECT * FROM binding")]==[("fixture-read-1",plan["instance"],oid)]
             and [tuple(r) for r in db.execute("SELECT * FROM action")]==[(oid,bound,"COMPLETED",None)]
             and [tuple(r) for r in db.execute("SELECT * FROM r22_plan")]==[(oid,canonical(body))],
             "M5_ORIGINAL_ROWS")
        records = [tuple(r) for r in db.execute("SELECT * FROM r22_history ORDER BY seq")]
        states=["PLANNED","RESERVED","COMPLETED"]
        need(records==[(i,oid,s,bound) for i,s in enumerate(states,1)], "M5_ORDER")
        rec, = db.execute("SELECT * FROM r22_receipt").fetchall()
        need(rec["original_id"]==oid and rec["bound"]==bound and rec["stdout"]==side["stdout"] and
             rec["response"]==canonical(response) and rec["pending_claim"] is None and rec["exit_code"]==0
             and rec["claim_sha256"]==cap["m5"]["claim_sha256"] and bridge.settled(plan,wire,pin)==response,
             "M5_RECEIPT")
        need(planned["state"]=="PLANNED" and planned["original_id"]==oid and planned["request_sha256"]==bound
             and planned["pid"]==start["parent"] and be["exit_ns"]<=planned["observed_ns"]<=start["start_ns"]
             <=cap["m5"]["observed_ns"]<=cap["read"]["open_start_ns"]<=cap["read"]["closed_ns"]<=end["exit_ns"]
             and os.getpid() not in (start["pid"],side["child"],start["parent"],birth["pid"]), "COLD_TIMELINE")
        final=transcript("07-receipts")[1]["snapshot"]
        need(final==snapshot(private,plan) and final["receipts"]==[response["receipt_ref"]] and final["stage"]=="COMPLETE",
             "FINAL_SNAPSHOT")
        cases=negative_tests(private,db,plan,pin,wire,cap,response)
    # Load the original joint decoder without the writable constructor's temporary lock.
    base.enable_numeric(pins)
    from al01.integrated import IntegratedLife
    raw=(RUN/"world/joint.json").read_bytes()
    wrap=parse(raw)
    need(sha(raw)==birth["joint_sha256"] and core.digest(wrap["data"])==wrap["sha256"], "JOINT_BYTES")
    individual, _, _ = IntegratedLife._decode(wrap["data"])
    need(individual.state["id"]==plan["identity"] and individual.state["tick"]==birth["tick"]==0
         and wrap["data"]["core_joint"]["phase"]==birth["phase"]=="READY", "R14_COLD_DECODE")
    return dict(status="VERIFIED_R22_DEV_M5_FIXTURE", mode=MODE, release=pin, identity=plan["identity"],
        original_id=oid, request_sha256=digest(req), m5_binding_sha256=bound, m5_states=states,
        claim_sha256=cap["m5"]["claim_sha256"], claim_final=None, receipt_ref=response["receipt_ref"],
        file_id=cap["file_before"]["file_id"], bytes_read=cap["read"]["bytes_read"], read_calls=cap["read"]["read_calls"],
        pids=dict(writer=start["parent"],api=start["pid"],reader=cap["pid"],cold=os.getpid(),birth=birth["pid"]),
        original_action_sha256=base.sha(Path(original_action.__file__)), r14_tick=0, negative_cases=cases,
        host_admission="NOT_GRANTED", independent_os_observer="NOT_RUN", lastJobID=None)
