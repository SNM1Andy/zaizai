"""Development-only coupling to the unchanged original M5 action authority."""
from contextlib import closing
import os
import sqlite3
import time

import original_action as m5
from common import ROOT, MODE, canonical, digest, need, parse, sha, fields

M5 = ROOT / "run/m5-original.sqlite"
SCHEMA = """
CREATE TABLE r22_plan(
    original_id TEXT PRIMARY KEY REFERENCES action(original_id),
    body TEXT NOT NULL);
CREATE TABLE r22_receipt(
    original_id TEXT PRIMARY KEY REFERENCES action(original_id),
    bound TEXT NOT NULL, pending_claim TEXT, claim_sha256 TEXT NOT NULL,
    stdout BLOB NOT NULL, response TEXT NOT NULL, exit_code INTEGER NOT NULL CHECK(exit_code=0));
CREATE TABLE r22_history(seq INTEGER PRIMARY KEY, original_id TEXT NOT NULL,
    state TEXT NOT NULL, bound TEXT NOT NULL);
INSERT INTO r22_history SELECT 1,original_id,state,request_sha256 FROM action;
CREATE TRIGGER r22_transition AFTER UPDATE OF state ON action WHEN NEW.state != OLD.state
BEGIN
    INSERT INTO r22_history(original_id,state,bound)
        VALUES(NEW.original_id,NEW.state,NEW.request_sha256);
END;
CREATE TRIGGER r22_require_receipt BEFORE UPDATE OF state ON action WHEN NEW.state='COMPLETED'
BEGIN
    SELECT CASE WHEN NOT EXISTS(
        SELECT 1 FROM r22_receipt WHERE original_id=OLD.original_id
        AND bound=OLD.request_sha256 AND pending_claim=OLD.claim
        AND OLD.state='RESERVED' AND NEW.claim IS NULL)
        THEN RAISE(ABORT,'R22_RECEIPT_AND_CLAIM_REQUIRED') END;
END;
CREATE TRIGGER r22_consume AFTER UPDATE OF state ON action WHEN NEW.state='COMPLETED'
BEGIN
    UPDATE r22_receipt SET pending_claim=NULL WHERE original_id=NEW.original_id;
END;
"""


def ro():
    need(M5.resolve() == M5 and M5.is_file(), "M5_PATH")
    db = sqlite3.connect(M5.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def binding(plan, wire, pin):
    from al01 import folder_contracts as fc
    p = wire["proposal"]
    req = p["envelope"]["request"]
    item, = plan["items"]
    fc.validate_request(req)
    need(req == item["binding"]["request"] and fc.request_sha256(req) ==
         p["envelope"]["request_sha256"] == item["binding"]["request_sha256"]
         and p["identity"] == plan["identity"] and p["instance"] == plan["instance"]
         and req["scope_ref"] == plan["scope_ref"] and req["operation"] == "READ_TEXT"
         and p["evidence_scope"] == plan["mode"] == MODE and not p["preflight_only"]
         and p["envelope"]["route"] == "native", "M5_FULL_REQUEST")
    birth = parse((ROOT / "run/birth.json").read_bytes())
    joint_sha = sha((ROOT / "run/world/joint.json").read_bytes())
    need(birth["identity"] == plan["identity"] and birth["release"] == pin
         and birth["tick"] == 0 and birth["phase"] == "READY"
         and birth["joint_sha256"] == joint_sha, "WORLD_BINDING")
    route = dict(job="fixture-read-1", campaign=plan["instance"], original_id=req["request_id"])
    return dict(mode=MODE, release=pin, route=route, wire=wire, item=item,
                birth_sha256=digest(birth), joint_sha256=joint_sha)


def row(db, body):
    route = body["route"]
    r = db.execute("""SELECT a.*, p.body FROM authority ns
        JOIN binding b ON b.campaign=ns.namespace JOIN action a USING(original_id)
        JOIN r22_plan p USING(original_id)
        WHERE ns.namespace=? AND b.job=? AND a.original_id=?""",
        (route["campaign"], route["job"], route["original_id"])).fetchone()
    need(r is not None and r["body"] == canonical(body) and
         r["request_sha256"] == digest(body), "M5_PLAN_MISMATCH")
    return r


def enroll(plan, wire, pin):
    body = binding(plan, wire, pin)
    route = body["route"]
    oid = route["original_id"]
    m5.enroll(M5, route["campaign"], [(oid, digest(body))], [(route["job"], route["campaign"], oid)])
    with m5.transaction(M5, route["campaign"]) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO r22_plan VALUES (?,?)", (oid, canonical(body)))
    with closing(ro()) as db:
        seen = row(db, body)
        need(seen["state"] == "PLANNED" and seen["claim"] is None, "NOT_PLANNED")
    return dict(original_id=oid, state="PLANNED", request_sha256=digest(body), pid=os.getpid(),
                observed_ns=time.monotonic_ns())


def reserve(plan, wire, pin):
    body = binding(plan, wire, pin)
    route = body["route"]
    with closing(ro()) as db:
        initial = row(db, body)
        need(initial["state"] == "PLANNED" and initial["claim"] is None, "M5_NOT_FRESH")
    d = m5.decide(M5, route["campaign"], route, digest(body), recovery=False)
    need(d["prior"] == "PLANNED" and d["granted"] and d["state"] == "RESERVED"
         and d["original_id"] == route["original_id"] and d["claim"], "NO_M5_GRANT")
    return d["claim"]


def reader_witness(plan, wire, pin, claim):
    body = binding(plan, wire, pin)
    with closing(ro()) as db:
        r = row(db, body)
        need(r["state"] == "RESERVED" and claim and r["claim"] == claim, "NO_LIVE_M5_CLAIM")
        return dict(original_id=r["original_id"], bound=r["request_sha256"],
                    state=r["state"], claim_sha256=digest(claim), observed_ns=time.monotonic_ns())


def validate_response(plan, wire, capture, response, child_pid, parent_pid):
    from backend_api import check_capture
    from al01 import folder_contracts as fc
    p = wire["proposal"]
    attempt = wire["attempt"]
    req = p["envelope"]["request"]
    item, = plan["items"]
    check_capture(p, attempt, item, capture, child_pid, parent_pid)
    read = capture["read"]
    fields(read, "open_start_ns closed_ns read_calls bytes_read open_flags calls opened_path")
    need(capture["m5"]["observed_ns"] <= read["open_start_ns"] <= read["closed_ns"] and
         read["calls"] == ["open","read","close"] and read["opened_path"] == os.path.join("fixtures",item["name"])
         and read["read_calls"] == 1 and read["bytes_read"] == item["object"]["size"]
         and read["open_flags"] == os.O_RDONLY | os.O_NOINHERIT | os.O_BINARY, "READ_WITNESS")
    text = capture["result"]["payload"]["text"]
    need(fc.text_payload(text.encode("utf8")) == capture["result"]["payload"], "TEXT_CONTENT")
    expected = dict(status="VERIFIED", evidence_scope=MODE, source="APPLICATION_BROKER_CAPTURE",
                    operation="READ_TEXT", identity=plan["identity"], instance=plan["instance"],
                    receipt_ref="r22_receipt_" + digest(capture), attempt_id=attempt["attempt_id"],
                    request_sha256=digest({k:v for k,v in wire.items() if k!="attempt"}),
                    proposal_sha256=digest(p), folder_request_sha256=digest(req), entry_ref=req["entry_ref"],
                    display=dict(kind="READ_TEXT", name=item["name"], text=text), readback_only=False)
    need(response == expected and response["request_sha256"] == attempt["request_sha256"], "RECEIPT_BINDING")


def finish(plan, wire, pin, claim, capture, response, stdout, child_pid):
    body = binding(plan, wire, pin)
    route = body["route"]
    oid = route["original_id"]
    w = capture["m5"]
    fields(w, "original_id bound state claim_sha256 observed_ns")
    need(w["original_id"] == oid and w["bound"] == digest(body) and w["state"] == "RESERVED"
         and w["claim_sha256"] == digest(claim) and parse(stdout) == capture, "CHILD_M5_BINDING")
    validate_response(plan, wire, capture, response, child_pid, os.getpid())
    with m5.transaction(M5, route["campaign"]) as db:
        db.row_factory = sqlite3.Row
        current = row(db, body)
        need(current["state"] == "RESERVED" and current["claim"] == claim, "STALE_M5_CLAIM")
        db.execute("INSERT INTO r22_receipt VALUES (?,?,?,?,?,?,0)",
                   (oid, digest(body), claim, digest(claim), stdout, canonical(response)))
    # A stop between the commits leaves RESERVED with the receipt; never dispatch again.
    m5.complete(M5, route["campaign"], oid, claim)
    need(settled(plan, wire, pin) == response, "M5_FINAL_READBACK")


def settled(plan, wire, pin):
    body = binding(plan, wire, pin)
    with closing(ro()) as db:
        r = row(db, body)
        need(r["state"] == "COMPLETED" and r["claim"] is None, "M5_NOT_COMPLETED")
        receipt = db.execute("SELECT * FROM r22_receipt WHERE original_id=?", (r["original_id"],)).fetchone()
        need(receipt is not None and receipt["pending_claim"] is None and receipt["bound"] == digest(body),
             "M5_RECEIPT_NOT_CLOSED")
        cap = parse(receipt["stdout"])
        w = cap["m5"]
        need(w["bound"] == digest(body) and w["original_id"] == r["original_id"] and
             w["claim_sha256"] == receipt["claim_sha256"] and w["state"] == "RESERVED", "RECEIPT_WITNESS")
        result = parse(receipt["response"])
        validate_response(plan, wire, cap, result, cap["pid"], cap["ppid"])
        return result
