"""One supervisor launch. Preserve original streams and compare evidence across reviewers."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import DB, ROOT, MODE, PYTHON_SHA, canonical, json_file, need, parse, put, sha

LOG = ROOT/"acceptance"
RUN = ROOT/"run"


def closed_files():
    members = [DB] + [p for p in RUN.rglob("*") if p.is_file()]
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(members)}


def call(role,pin):
    args = [sys.executable,"-X","utf8","-I","-S","-B",str(ROOT/"entry.py"),role,pin]
    with (LOG/(role+".stdout")).open("xb") as out, (LOG/(role+".stderr")).open("xb") as err:
        started=datetime.now(timezone.utc).isoformat()
        proc=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
            env={"SystemRoot":os.environ["SystemRoot"]},creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
        rc=proc.wait(timeout=180)
    json_file("acceptance/"+role+".exit.json",dict(pid=proc.pid, parent=os.getpid(),argv=args,exit=rc,
              started=started,ended=datetime.now(timezone.utc).isoformat()))
    need(rc==0 and not (LOG/(role+".stderr")).stat().st_size,"STOP_"+role)
    data=parse((LOG/(role+".stdout")).read_bytes())
    return data,proc.pid


def collect(pin):
    need(sha((ROOT/"release.json").read_bytes())==pin and sha(Path(sys.executable).read_bytes())==PYTHON_SHA
         and not RUN.exists(), "EXCLUSIVE_CANDIDATE")
    LOG.mkdir(exist_ok=False)
    info,_=call("check",pin)
    need(info["status"]=="PACKAGE_VERIFIED" and all(not g["executed"] for g in info["r14_original_gates"]),
         "CHECK")
    result,writer=call("run",pin)
    need(result["status"]=="COMPLETED_DEVELOPMENT_FIXTURE" and result["pid"]==writer,"RUN_STATUS")
    before=closed_files()
    json_file("acceptance/closed.json",before)
    duplicate,repeat_pid=call("duplicate",pin)
    need(duplicate["pid"]==repeat_pid and duplicate["response"]["readback_only"] and
         duplicate["response"]["receipt_ref"]==result["receipt_ref"] and before==closed_files(),"DUPLICATE_CHANGED")
    cold,cold_pid=call("cold",pin)
    need(cold["status"]=="VERIFIED_R22_DEV_M5_FIXTURE" and cold["pids"]["cold"]==cold_pid
         and cold["pids"]["writer"]==writer and cold["receipt_ref"]==result["receipt_ref"]
         and repeat_pid not in cold["pids"].values() and before==closed_files(),"COLD_CHANGED")
    json_file("RESULT.json",dict(cold,supervisor_pid=os.getpid(),duplicate_pid=repeat_pid,
        duplicate_status="STORED_RECEIPT_ONLY",checked_closed_files=len(before),
        closed_manifest_sha256=sha((LOG/"closed.json").read_bytes()),closed_files_unchanged=True,
        r14_original_gates=info["r14_original_gates"],business_attempts=1,automatic_retries=0))
    return dict(status=cold["status"], result_sha256=sha((ROOT/"RESULT.json").read_bytes()))


if __name__=="__main__":
    print(canonical(collect(sys.argv[1])))
