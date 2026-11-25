"""Single-use reader for the new synthetic fixture only. stdin never supplies a path."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (FIXTURES, NAMES, ROOT, canonical, db_open, digest, fingerprint,
                    need, regular, stdin_json, verify_release)


def read_once(pin):
    plan = verify_release(pin)
    from al01 import folder_contracts as fc
    import bridge
    import time
    dispatch = stdin_json()
    wire = dispatch["wire"]
    p = wire["proposal"]
    req = p["envelope"]["request"]
    fc.validate_request(req)
    with db_open(pin) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM actions WHERE parent=? AND child=? AND state='CLAIMED'",
                         (os.getppid(), os.getpid())).fetchone()
        need(row is not None and row["wire"] == canonical(wire) and row["attempt"] == canonical(wire["attempt"]),
             "NO_CURRENT_CLAIM")
        slot = row["slot"]
        item = plan["items"][slot]
        need(req == item["binding"]["request"] and fc.request_sha256(req) == p["envelope"]["request_sha256"]
             and p["envelope"]["route"] == "native" and req["operation"] == "READ_TEXT"
             and not p["preflight_only"] and item["name"] == NAMES[slot], "REQUEST_TARGET")
        witness = bridge.reader_witness(plan, wire, pin, dispatch["claim"])
        db.execute("UPDATE actions SET state='READING' WHERE slot=?", (slot,))
        db.commit()
    path = FIXTURES / NAMES[slot]
    need(FIXTURES.resolve() == FIXTURES and not FIXTURES.is_junction() and path.resolve() == path
         and FIXTURES.parent == ROOT and str(FIXTURES.stat().st_ino) == plan["directory_id"], "FIXTURE_ROOT")
    regular(path.lstat())
    started = time.monotonic_ns()
    fd = os.open(path, os.O_BINARY | os.O_RDONLY | os.O_NOINHERIT)
    try:
        opened = os.fstat(fd)
        regular(opened)
        before = fingerprint(opened)
        need(before == item["object"] and 0 < opened.st_size <= fc.MAX_TEXT_BYTES, "OPEN_OBJECT_MISMATCH")
        raw = os.read(fd, opened.st_size)
        after = fingerprint(os.fstat(fd))
        payload = fc.text_payload(raw)
        need(before == after and len(raw) == opened.st_size and payload["content_sha256"] == item["content_sha256"],
             "READ_MISMATCH")
        result = fc.make_result(req, "OK", payload=payload)
    finally:
        os.close(fd)
    read = dict(open_start_ns=started, closed_ns=time.monotonic_ns(), read_calls=1,
                bytes_read=len(raw), open_flags=os.O_BINARY | os.O_RDONLY | os.O_NOINHERIT)
    return dict(m5=witness, read=read, pid=os.getpid(), ppid=os.getppid(), attempt=wire["attempt"], proposal_sha256=digest(p),
                file_before=before, file_after=after, result=result)

