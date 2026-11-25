"""Move one existing individual between signed managed Windows builds through native prepare/handoff/claim."""
import argparse
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import time

_deadline=ContextVar("joint25_native_deadline",default=None)
@contextmanager
def deadline_scope(seconds):
    limit=time.monotonic()+seconds
    active=_deadline.get()
    token=_deadline.set(min(limit,active) if active is not None else limit)
    try:yield
    finally:_deadline.reset(token)
def remaining(default=45):
    due=_deadline.get()
    if due is None:return default
    value=min(default,due-time.monotonic())
    if value<=0:raise TimeoutError("原生调用预算到期")
    return value

def digest(value):return hashlib.sha256(value).hexdigest()
def filehash(p):return digest(p.read_bytes())
def pin(v):return digest(json.dumps(v,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode())
def require(v,reason):
    if not v:raise ValueError(reason)
def write(p,obj):
    temp=p.with_name(p.name+".pending-save")
    with temp.open("w",encoding="utf8",newline="\n") as f:json.dump(obj,f,indent=2,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(temp,p)
def fields(s):return dict(re.findall(r"(\w+)=([^\s]+)",s))
def exe(folder,owner):
    require(owner in ("alpha","beta"),"unknown owner")
    return folder/("pcgm-"+owner+".exe")
def invoke(binary,args,data=b""):
    try:p=subprocess.run([binary,*args],input=data,capture_output=True,timeout=remaining(),creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:raise TimeoutError("原生操作期限已到；有写入意图时先查回执") from exc
    err=p.stderr.decode("utf8","replace")
    if p.returncode or err:raise RuntimeError(f"{binary.name} ({p.returncode}): {err[:230]}")
    result=p.stdout.decode("utf8")
    if any(l.startswith("QUERY_ERROR") for l in result.splitlines()):raise ValueError("native command was refused: "+[l for l in result.splitlines() if l.startswith("QUERY_ERROR")][0][:200])
    return result
def snapshot(binary,state):return json.loads(invoke(binary,["--desktop-snapshot",state]))
def read(binary,state,operation):
    require("\r" not in operation and "\n" not in operation,"one read frame required")
    r=json.loads(invoke(binary,["--read-channel",state],("host "+operation+"\n").encode()))
    require(r.get("id")=="host" and r.get("ok"),str(r.get("error","read failed")))
    return r["payload"]
def history(binary,state):
    lines=invoke(binary,["--resume",state],b":history\n").splitlines()
    require(lines and lines[0].startswith("individual=") and lines[-1].startswith("history_end event="),"invalid event stream")
    events=[v for v in lines[1:] if v.startswith("event=")]
    # The runtime may return summary lines in addition to its enumerated events.
    require(int(fields(lines[-1])["event"])==len(events),"history count differs")
    return events
@contextmanager
def guard(state):
    # Same acquisition order as host service.writer(), never nest with an already-held host lock.
    with (state.parent.parent/"writer.guard").open("a+b") as outer,(state.parent/"desktop-writer.lock").open("a+b") as inner:
        got=[]
        try:
            for f in (outer,inner):f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1);got.append(f)
            yield
        finally:
            for f in reversed(got):f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
def transfer(state,oldbin,newbin,actor,journal,apply=False,*,host_locked=False):
    state=state.resolve(strict=True);oldbin=oldbin.resolve(strict=True);newbin=newbin.resolve(strict=True)
    require(oldbin!=newbin and state.is_file(),"distinct release directories and existing state required")
    pair={str(p):filehash(p) for d in (oldbin,newbin) for p in [exe(d,"alpha"),exe(d,"beta")]}
    with (nullcontext() if host_locked else guard(state)):
        probe=exe(newbin,"alpha")
        # If the target cannot decode a newer format this fails before any write.
        current=snapshot(probe,state)
        require(current["individual"]==actor,"wrong individual")
        info=read(probe,state,"status")
        j=json.loads(journal.read_bytes()) if journal.is_file() else None
        if j:require(j["identity"]==actor and j["source_bin"]==str(oldbin) and j["target_bin"]==str(newbin) and j["pins"]==pair,"journal refers to other actor or release")
        active=info["owner"]
        if j and j.get("phase")=="complete" and active==j["to"] and not info["handoff_pending"]:
            verify=history(exe(newbin,active),state)
            require(len(verify)>=j["old_event_count"]+2 and pin(verify[:j["old_event_count"]])==j["old_event_prefix"],"receipt history differs")
            return dict(j,outcome="already_target")
        if not info["handoff_pending"]:
            # A switch might have been completed just before a previous caller lost acknowledgment.
            if j and active==j["to"]:
                hist=history(exe(newbin,active),state)
                require(len(hist)>=j["old_event_count"]+2 and pin(hist[:j["old_event_count"]])==j["old_event_prefix"],"post-claim history differs")
                if apply:
                    j.update(phase="complete",after_head=current["head"],after_event_count=len(hist));write(journal,j)
                return dict(j,outcome="verified_claim")
            source_exe=exe(oldbin,active);events=history(source_exe,state)
            target="beta" if active=="alpha" else "alpha"
            if j:require(active==j["from"] and current["head"]==j["before_head"],"recorded starting head has changed; no replay")
            else:j=dict(schema="zaizai-native-release-handoff/1",identity=actor,pins=pair,source_bin=str(oldbin),target_bin=str(newbin),
                        before_head=current["head"],old_event_count=len(events),old_event_prefix=pin(events),source_sha256=digest(current["source"].encode()),
                        inactive_sha256=pin(current["inactive"]),phase="checked",**{"from":active,"to":target})
            require(not info.get("restore_staged"),"staged restore is not a live actor")
            if not apply:return dict(j,outcome="eligible")
            journal.parent.mkdir(parents=True,exist_ok=True);write(journal,j)
            out=fields(invoke(exe(newbin,target),["--prepare",state]))
            require(out["binary_sha256"]==pair[str(exe(newbin,target))] and out["snapshot_sha256"]==current["head"] and out["individual"]==actor and out["build"]==target,"readiness mismatch")
            msg=f":handoff {target} {out['binary_sha256']} {current['head']}\n"
            ret=invoke(source_exe,["--resume",state],msg.encode()).splitlines()
            require(len(ret)==2 and ret[-1].startswith("handoff_prepared "),"writer did not confirm its handoff")
        else:
            require(j and j["phase"] in ("checked","prepared") and active==j["from"],"unrecognized pending transition; preserve it")
            if not apply:return dict(j,outcome="pending")
        target=j["to"]
        inspected=invoke(exe(oldbin,active),["--inspect",state])
        pending=re.search(r"pending_handoff to=(\w+) nonce=(\w+)",inspected)
        require(pending and pending[1]==target,"native pending target mismatch")
        if j.get("nonce"):require(j["nonce"]==pending[2],"pending nonce changed")
        j.update(phase="prepared",nonce=pending[2]);write(journal,j)
        # Native --claim validates the target binary against the hash sealed by the current owner.
        raw=invoke(exe(newbin,target),["--claim",state,j["nonce"]])
        require(raw.startswith("individual="+actor+" "),"claim returned different identity")
        after=snapshot(exe(newbin,target),state);events=history(exe(newbin,target),state)
        require(after["individual"]==actor and after["owner"]==target and digest(after["source"].encode())==j["source_sha256"] and pin(after["inactive"])==j["inactive_sha256"],"claim changed source, inactive evidence, or identity")
        require(len(events)==j["old_event_count"]+2 and pin(events[:-2])==j["old_event_prefix"],"handoff changed older events")
        j.update(phase="complete",after_head=after["head"],after_event_count=len(events),native_events_added=2,after_prefix_verified=True);write(journal,j)
        return dict(j,outcome="claimed")
def main():
    p=argparse.ArgumentParser();p.add_argument("--state",required=True,type=Path);p.add_argument("--source-bin",required=True,type=Path)
    p.add_argument("--target-bin",required=True,type=Path);p.add_argument("--identity",required=True);p.add_argument("--journal",required=True,type=Path)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument("--check",action="store_true");g.add_argument("--apply",action="store_true")
    a=p.parse_args();print(json.dumps(transfer(a.state,a.source_bin,a.target_bin,a.identity,a.journal,a.apply),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
