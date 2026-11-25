"""Exercise the rollback journal only on an already detached, populated test host."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import argparse
import importlib.util
import json
import shutil
import sqlite3
import sys
import time
from zipfile import ZipFile
import rollback_slot_host31 as rb

def main():
 p=argparse.ArgumentParser();p.add_argument("--fixture",required=True,type=Path);p.add_argument("--bundle",required=True,type=Path);p.add_argument("--out",type=Path);args=p.parse_args()
 fixture=args.fixture.resolve(strict=True);bundle=args.bundle.resolve(strict=True)
 live=bundle.parent.parent
 assert fixture!=live and not (fixture/"state/dashboard-split.sqlite").samefile(live/"state/dashboard-split.sqlite")
 tmp_parent=Path(__file__).resolve().parents[1]
 with TemporaryDirectory(dir=tmp_parent,prefix="rollback-verification-") as td:
  root=Path(td);backup=root/"rollback"/bundle.name;backup.mkdir(parents=True)
  for area in ("host","tools"):
   shutil.copytree(bundle/area,backup/area)
   shutil.copytree(bundle/area,root/area)
  for mark in rb.PINS:shutil.copy2(bundle/mark,backup/mark)
  shutil.copytree(fixture/"host",root/"host",dirs_exist_ok=True,ignore=shutil.ignore_patterns("*.pyc","__pycache__"))
  for area in ("bin","state/native"):
   if area=="bin":shutil.copytree(live/area,root/area)
   else:
    (root/area).mkdir(parents=True)
    shutil.copy2(fixture/area/"joint-reopen.json",root/area/"joint-reopen.json")
  (root/"evidence").mkdir()
  with closing(sqlite3.connect((fixture/"state/dashboard-split.sqlite").as_uri()+"?mode=ro",uri=True)) as db,closing(sqlite3.connect(root/"state/dashboard-split.sqlite")) as cp:db.backup(cp)
  with ZipFile(bundle/"pre-slots.zip") as z:(root/"state/individual.pcgm").write_bytes(z.read("state/individual.pcgm"))
  old=rb.load(backup/"INSTALL.json");meta=dict(old,host_slots={"rollback_dir":str(backup)})
  newgate=rb.load(backup/"v3-gate.json")
  # A rollback-only fixture holds the candidate byte inventory. Its gate is not a production release receipt.
  newgate["protected_sha256"]={k:rb.hashed(root/k) for k in newgate["protected_sha256"]}
  (root/"evidence/v3-gate.json").write_text(json.dumps(newgate),encoding="utf8")
  meta["frozen_dialogue_gate_sha256"]=rb.hashed(root/"evidence/v3-gate.json")
  (root/"INSTALL.json").write_text(json.dumps(meta,ensure_ascii=False),encoding="utf8")
  manifest=rb.load(backup/"manifest-sha256.json")
  for folder in ("host","tools"):
   for f in (root/folder).rglob("*"):
    if f.is_file() and f.suffix!=".pyc" and "__pycache__" not in f.parts:manifest["files"][f.relative_to(root).as_posix()]=rb.hashed(f)
  manifest["files"]["INSTALL.json"]=rb.hashed(root/"INSTALL.json")
  (root/"evidence/manifest-sha256.json").write_text(json.dumps(manifest),encoding="utf8")
  original=rb.state_info(root);disk=rb.hashed(root/"state/dashboard-split.sqlite")
  assert original["stored_frame_types"].get("slot_status",0)>0
  cut=[]
  for trigger in ("host/service.py","evidence/v3-gate.json","INSTALL.json"):
   def interrupt(phase):
    if phase==trigger and phase not in cut:
     cut.append(phase)
     raise InterruptedError(phase)
   try:rb.apply_locked(root,backup,interrupt)
   except InterruptedError:pass
   else:raise AssertionError("missed boundary "+trigger)
  result=rb.apply_locked(root,backup)
  assert rb.apply_locked(root,backup)["already_restored"]
  assert rb.state_info(root)==original and rb.hashed(root/"state/dashboard-split.sqlite")==disk
  script="import sys;from pathlib import Path;r=Path(sys.argv[1]);sys.path.insert(0,str(r/'host'));import service as s;rows=s.history('host_cut');assert rows and '没有生成认知回复' in rows[-1][2];print(len(rows))"
  import subprocess
  run=subprocess.run([sys.executable,"-B","-X","utf8","-c",script,root],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
  if run.returncode and b"FileNotFoundError" in run.stderr:
   # Original host imports the folder reference decoder, whose constants do not require its historical payloads when reading conversations.
   raise AssertionError(run.stderr.decode("utf8","replace")[-450:])
  assert run.returncode==0,run.stderr.decode("utf8","replace")[-500:]
  result.update(interrupted_at=cut,db_file_sha256_unchanged=disk,old_host_read_empty_submission=True,readback=int(run.stdout.strip()),
                restore_rerun_idempotent=True,production_changed=False,archived_host_location="temporary test fixture")
  result.pop("former_host",None)
  if args.out:args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
  print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()
