"""Provision the sole new synthetic target. No business operation runs here."""
from pathlib import Path
import os
import sqlite3
import sys
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (COMMANDS, DB, FIXTURES, MODE, NAMES, PYTHON_SHA, ROOT,
                    fingerprint, json_file, need, put, regular, sha)
from provenance import R14_PIN, R22_PIN


def provision():
    need(ROOT.name == "offline-six-module-r28-20261120" and os.name == "nt"
         and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and not sys.flags.optimize
         and sha(Path(sys.executable).read_bytes()) == PYTHON_SHA, "FIXED_DEVELOPMENT_BUILD")
    sources = {"provenance.py","world_link.py","prepare.py","entry.py","bridge.py","backend_api.py","common.py","language.py",
               "m2_reader.py","r20_routes.py","cold.py","campaign.py","acceptance.py","parent-sources.json"}
    need({p.name for p in ROOT.iterdir()} == sources | {"r14"}, "EXCLUSIVE_PROVISION")
    sys.path.insert(0, str(ROOT / "r14/bundle/lib"))
    sys.path.insert(0, str(ROOT / "r14/bundle"))
    import base
    base.verified(R14_PIN)
    from al01 import folder_contracts as fc
    from zhcl import vocab
    import r20_routes as routes
    FIXTURES.mkdir(exist_ok=False)
    name, = NAMES
    raw = b'{"object_id":"object_0001","outcome":"cooperate"}\n'
    path = FIXTURES / name
    put(path, raw)
    info = path.lstat()
    regular(info)
    uid = uuid4().hex
    scope = "scope_" + uid
    ref = "entry_" + uuid4().hex
    req = fc.make_request("READ_TEXT", scope, request_id=vocab.message_id("READ_TEXT", scope, entry_ref=ref),
                          entry_ref=ref)
    binding = dict(request=req, request_sha256=fc.request_sha256(req))
    item = dict(name=name, cl_file="direct.cl", object=fingerprint(info), binding=binding, content_sha256=sha(raw))
    put(ROOT/"direct.cl", (routes.emit_source(dict(format=routes.FORMAT, route="native", **binding))+"\n").encode())
    put(ROOT/"offline.txt", (COMMANDS[0]+"\n").encode())
    json_file("plan.json", dict(mode=MODE, identity="TEST-R28-"+uid, run_id=uid, route_target="object_0001", instance="TEST-"+uid+"-amber", scope_ref=scope,
        items=[item], directory_id=str(FIXTURES.stat().st_ino), actual_read_budget=1, translation_read_budget=0,
        host_admission="NOT_GRANTED", retry=False, lastJobID=None))
    members = sources | {"direct.cl", "offline.txt", "plan.json"}
    members.update(p.relative_to(ROOT).as_posix() for p in (ROOT/"r14").rglob("*") if p.is_file())
    release = dict(mode=MODE, r14=R14_PIN, parent_r22=R22_PIN, python_sha256=PYTHON_SHA,
                   files={n:sha((ROOT/n).read_bytes()) for n in sorted(members)})
    json_file("release.json", release)
    pin = sha((ROOT/"release.json").read_bytes())
    put(DB,b"")
    with sqlite3.connect(DB) as db:
        db.executescript("""
            CREATE TABLE campaign(release_sha TEXT PRIMARY KEY);
            CREATE TABLE proposals(nonce TEXT PRIMARY KEY,slot INTEGER NOT NULL CHECK(slot=0),sha TEXT UNIQUE NOT NULL,
                                   body TEXT NOT NULL,proof TEXT NOT NULL);
            CREATE TABLE actions(slot INTEGER PRIMARY KEY CHECK(slot=0),state TEXT NOT NULL,
                attempt TEXT UNIQUE,wire TEXT,parent INTEGER,child INTEGER,stdout BLOB,stderr BLOB,
                exit_code INTEGER,response TEXT,error TEXT);
            INSERT INTO actions(slot,state) VALUES (0,'READY');
        """)
        db.execute("INSERT INTO campaign VALUES (?)",(pin,))
    print(pin)


if __name__ == "__main__":
    provision()
