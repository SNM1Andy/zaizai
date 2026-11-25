"""R20 JSON wire backend scoped to a two-file R21 engineering experiment."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import os
import sqlite3

from common import (COMMANDS, MODE, PREVIEW, TEST_SOURCE, Refused, canonical, child, db_open, digest,
                    fields, need, nonce_ok, parse, sha, stdin_json, verify_release)


def snapshot(db, plan):
    rows = db.execute("SELECT state, response FROM actions ORDER BY slot").fetchall()
    need(len(rows) == 1, "LEDGER_SLOTS")
    receipts = [parse(r["response"])["receipt_ref"] for r in rows if r["state"] == "SETTLED"]
    held = any(r["state"] not in ("READY", "SETTLED") for r in rows)
    stage = "UNKNOWN_NO_REPLAY" if held else ("COMPLETE" if len(receipts) == 1 else "READY_SYNTHETIC_READ")
    return dict(identity=plan["identity"], instance=plan["instance"], revision=len(receipts), stage=stage,
                receipts=receipts, evidence_scope=MODE)


def propose(db, plan, wire, pin):
    from world_link import decision
    from language import bind
    fields(wire, "op command state_sha256 nonce")
    command = wire["command"]
    need(command in (*COMMANDS, PREVIEW) and nonce_ok(wire["nonce"]), "COMMAND_OR_NONCE")
    db.execute("BEGIN IMMEDIATE")
    snap = snapshot(db, plan)
    need(snap["stage"] != "UNKNOWN_NO_REPLAY" and wire["state_sha256"] == digest(snap), "STALE_OR_HELD")
    slot = 0 if command == PREVIEW else COMMANDS.index(command)
    row = db.execute("SELECT state FROM actions WHERE slot=?", (slot,)).fetchone()
    need(command == PREVIEW or row["state"] == "READY", "SPENT")
    existing = db.execute("SELECT body FROM proposals WHERE nonce=?", (wire["nonce"],)).fetchone()
    if existing:
        p = parse(existing[0])
        need(p["command"] == command and p["state_sha256"] == digest(snap), "NONCE_CONFLICT")
    else:
        gate = decision(plan, pin, live=True)
        need(command in (gate["command"], PREVIEW), "POLICY_COMMAND")
        proof = bind(plan, command)
        env = proof["envelope"]
        p = dict(command=command, operation=env["request"]["operation"], envelope=env,
                 decision_sha256=digest(gate), candidate_nonce=wire["nonce"], identity=snap["identity"], instance=snap["instance"],
                 evidence_scope=MODE, state_sha256=digest(snap), input_sha256=proof["input_sha256"],
                 proof_sha256=digest(proof), preflight_only=command == PREVIEW)
        p["proposal_id"] = "p_" + digest(p)[:32]
        db.execute("INSERT INTO proposals VALUES (?,?,?,?,?)",
                   (wire["nonce"], slot, digest(p), canonical(p), canonical(proof)))
    db.commit()
    return dict(status="CANDIDATE", proposal=p, proposal_sha256=digest(p))


def check_base(db, plan, base):
    fields(base, "op proposal proposal_sha256 confirmation confirmation_source")
    p = base["proposal"]
    need(base["op"] == "confirm" and type(p) is dict and digest(p) == base["proposal_sha256"], "PROPOSAL_DIGEST")
    row = db.execute("SELECT slot, body FROM proposals WHERE sha=?", (base["proposal_sha256"],)).fetchone()
    need(row is not None and canonical(p) == row["body"] and not p["preflight_only"], "ISSUED_ACTION_REQUIRED")
    need(base["confirmation"] == "确认 " + p["proposal_id"] and base["confirmation_source"] == TEST_SOURCE,
         "CONFIRMATION")
    item = plan["items"][row["slot"]]
    need(p["command"] == COMMANDS[row["slot"]] and p["envelope"]["route"] == "native" and
         all(p["envelope"][k] == v for k,v in item["binding"].items()), "SLOT_BINDING")
    return row["slot"]


def reserve_local(db, plan, base):
    """Local test client reservation. Never loads or claims a historical attempt."""
    from uuid import uuid4
    db.execute("BEGIN IMMEDIATE")
    slot = check_base(db, plan, base)
    snap = snapshot(db, plan)
    row = db.execute("SELECT * FROM actions WHERE slot=?", (slot,)).fetchone()
    need(row["state"] == "READY" and snap["stage"] == "READY_SYNTHETIC_READ"
         and digest(snap) == base["proposal"]["state_sha256"], "RESERVATION_HELD")
    if row["attempt"]:
        attempt = parse(row["attempt"])
        need(attempt["request_sha256"] == digest(base), "ALREADY_RESERVED")
    else:
        attempt = dict(attempt_id="r22_" + uuid4().hex, request_sha256=digest(base))
        db.execute("UPDATE actions SET attempt=? WHERE slot=?", (canonical(attempt), slot))
    db.commit()
    return attempt


def check_capture(proposal, attempt, item, capture, pid, ppid):
    from al01 import folder_contracts as fc
    req = proposal["envelope"]["request"]
    fields(capture, "pid ppid attempt proposal_sha256 file_before file_after result m5 read")
    need(capture["pid"] == pid and capture["ppid"] == ppid and pid != ppid and
         capture["attempt"] == attempt and capture["proposal_sha256"] == digest(proposal), "CAPTURE_PROCESS_BINDING")
    need(capture["file_before"] == capture["file_after"] == item["object"], "CAPTURE_FILE_BINDING")
    result = capture["result"]
    fc.validate_result(result, req)
    need(result["status"] == "OK" and result["payload"]["content_sha256"] == item["content_sha256"]
         and result["payload"]["utf8_bytes"] == item["object"]["size"], "CAPTURE_CONTENT_BINDING")


def confirm(db, plan, wire, pin):
    fields(wire, "op proposal proposal_sha256 confirmation confirmation_source attempt")
    base = {k:v for k,v in wire.items() if k != "attempt"}
    import bridge
    attempt = wire["attempt"]
    fields(attempt, "attempt_id request_sha256")
    db.execute("BEGIN IMMEDIATE")
    slot = check_base(db, plan, base)
    row = db.execute("SELECT * FROM actions WHERE slot=?", (slot,)).fetchone()
    need(row["attempt"] == canonical(attempt) and attempt["request_sha256"] == digest(base), "ATTEMPT_BINDING")
    if row["state"] != "READY":
        need(row["wire"] == canonical(wire), "CONFLICT")
        db.commit()
        if row["state"] == "SETTLED":
            stored = bridge.settled(plan, wire, pin)
            need(stored == parse(row["response"]), "M5_RECEIPT_DISAGREES")
            return {**stored, "readback_only": True}
        return dict(status="UNKNOWN", reason="CLAIM_ALREADY_COMMITTED", retry=False)
    p = base["proposal"]
    snap = snapshot(db, plan)
    need(snap["stage"] == "READY_SYNTHETIC_READ" and digest(snap) == p["state_sha256"], "STALE_OR_HELD")
    db.execute("UPDATE actions SET state='CLAIMED', wire=?, parent=? WHERE slot=?",
               (canonical(wire), os.getpid(), slot))
    db.commit()  # Every subsequent failure leaves this request spent, including process death.
    proc = None
    try:
        claim = bridge.reserve(plan, wire, pin)
        proc = child("m2_reader.py", pin)
        db.execute("UPDATE actions SET child=? WHERE slot=?", (proc.pid, slot))
        out, err = proc.communicate(canonical(dict(wire=wire, claim=claim)).encode("utf8"), timeout=20)
        db.execute("UPDATE actions SET stdout=?, stderr=?, exit_code=? WHERE slot=?", (out, err, proc.returncode, slot))
        need(proc.returncode == 0 and not err and len(out) <= 65536, "CHILD_TERMINAL")
        capture = parse(out)
        item = plan["items"][slot]
        check_capture(p, attempt, item, capture, proc.pid, os.getpid())
        response = dict(status="VERIFIED", evidence_scope=MODE, source="APPLICATION_BROKER_CAPTURE",
                        operation=p["operation"], identity=p["identity"], instance=p["instance"],
                        receipt_ref="r22_receipt_" + digest(capture), attempt_id=attempt["attempt_id"],
                        request_sha256=attempt["request_sha256"], proposal_sha256=digest(p),
                        folder_request_sha256=p["envelope"]["request_sha256"], entry_ref=capture["result"]["entry_ref"],
                        display=dict(kind="READ_TEXT", name=item["name"], text=capture["result"]["payload"]["text"]),
                        readback_only=False)
        bridge.finish(plan, wire, pin, claim, capture, response, out, proc.pid)
        changed = db.execute("UPDATE actions SET state='SETTLED',response=? WHERE slot=? AND state='READING'",
                             (canonical(response), slot)).rowcount
        need(changed == 1, "CHILD_DID_NOT_CLAIM")
        return response
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Refused) else type(exc).__name__
        db.execute("UPDATE actions SET state='UNKNOWN',error=? WHERE slot=? AND state!='SETTLED'", (reason, slot))
        return dict(status="UNKNOWN", reason=reason, retry=False)


def api(db, plan, wire, pin):
    need(type(wire) is dict, "WIRE_OBJECT")
    try:
        if wire.get("op") == "status":
            fields(wire, "op")
            return dict(status="OK", snapshot=snapshot(db, plan))
        if wire.get("op") == "propose":
            return propose(db, plan, wire, pin)
        if wire.get("op") == "confirm":
            return confirm(db, plan, wire, pin)
        raise Refused("OPERATION")
    finally:
        if db.in_transaction:
            db.rollback()

