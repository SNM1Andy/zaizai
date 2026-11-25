"""Run the 1.0 decoder against relocated bytes, verifying hashes instead of guest path names."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
native = ROOT/"state/native/offline-six-module-r28-20261120"
bundle = native/"r14/bundle"
sys.path.insert(0,str(native))
from common import verify_release
pin=json.loads((ROOT/"state/native/joint-reopen.json").read_bytes())["candidate_release"]
plan=verify_release(pin)
sys.path.insert(0,str(bundle))
import base
from provenance import R14_PIN
pins=json.loads((bundle/"FREEZE.json").read_bytes())
assert base.sha(bundle/"FREEZE.json")==R14_PIN
assert base.sha(Path(sys.executable))==pins["python_sha256"] and sys.version==pins["python_version"]
assert all(base.sha(bundle/k)==v for k,v in pins["files"].items())
import sqlite3
import world_link
import cold
import offline, original_action
base.enable_numeric(pins)
closed=json.loads((native/"acceptance/closed.json").read_bytes())
assert all(base.sha(native/k)==v for k,v in closed.items())
_,response,_,_=cold.transcript("06-confirm")
with sqlite3.connect((native/"run/m5-original.sqlite").as_uri()+"?mode=ro",uri=True) as db:
    saved,=db.execute("select response from r22_receipt").fetchone()
    assert json.loads(saved)==response
    phases=[r[0] for r in db.execute("select state from r22_history order by seq")]
assert phases==["PLANNED","RESERVED","COMPLETED"]
world=world_link.cold_world(plan,pin,response)
anchor=json.loads((ROOT/"state/native/joint-reopen.json").read_bytes())
assert plan["identity"]==anchor["identity"] and response["receipt_ref"]==anchor["receipt"]
print(json.dumps(dict(identity=plan["identity"],generation=world["generation"],tick=world["core_tick"],receipt=response["receipt_ref"],process=os.getpid(),m5_states=phases,world=world),ensure_ascii=True))


