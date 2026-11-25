"""Install and verify the local 0.159 geometry interface without replacing an engine or save.

The command-line entry point holds the same locks as the desktop writer.
Only --install and --step can modify the supplied native save; replay uses disposable copies.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import msvcrt
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
MODULE_PIN = "b0f9ee140a90501461003427250c6723544fb7c2503e98234c871c8fb84c818a"
PROTOCOL_PIN = "f59263c63ccf31ecc9337e99a6a08c662bd7bf72c58e4ade947092720011f360"
INIT_EVENT = "field_v11_glyph64_s8"
ACTIONS = ("inspect", "work", "wait")
CONTEXTS = ("inflow", "quiet", "outflow")
# Host-side discrete event encoding for this adapter; neither rewards nor emotion labels.
CONTEXT_FROM_KIND = {"fetch":"inflow", "integration":"quiet"}
MARKER = "\n# module geometry\n"
NAMESPACE = re.compile(r"\bgeom_[A-Za-z0-9_]+")
SHA256 = re.compile("[0-9a-f]{64}")
PRIME = "primordial_set={creation,entropy_reduction,evolution,optimization,order} kind=unordered direction_only"

def fail_unless(test, reason):
    if not test:raise ValueError(reason)

def sha(data):return hashlib.sha256(data).hexdigest()

def packed(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)

@contextmanager
def host_lock(state):
    with (state.parent.parent/"writer.guard").open("a+b") as outer,(state.parent/"desktop-writer.lock").open("a+b") as inner:
        held=[]
        try:
            for stream in (outer,inner):
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1);held.append(stream)
            yield
        finally:
            for stream in reversed(held):
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def clone_native(source,root):
    parent=root/"state";parent.mkdir(parents=True)
    target=parent/source.name
    shutil.copyfile(source,target)
    for suffix in (".history",".episodes"):
        original=source.with_name(source.name+suffix)
        if original.is_dir():shutil.copytree(original,target.with_name(target.name+suffix))
    if (source.parent/"modules").is_dir():shutil.copytree(source.parent/"modules",parent/"modules")
    return target

def native(binary,args,commands=()):
    cmd=[str(binary),*map(str,args)]
    payload=("\n".join(commands)+"\n").encode() if commands else b""
    p=subprocess.run(cmd,input=payload,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    text=p.stdout.decode("utf8").splitlines()
    errors=[s for s in text if s.startswith("QUERY_ERROR")]
    if p.returncode or errors:raise RuntimeError(" | ".join(errors) or p.stderr.decode("utf8","replace")[:800] or f"exit {p.returncode}")
    return text

def finite_vector(text,count):
    vals=json.loads(text);fail_unless(isinstance(vals,list) and len(vals)==count and all(type(v) in (int,float) and math.isfinite(v) for v in vals),"invalid native field vector")
    return vals

def status_line(text):
    m=re.fullmatch(r"field_tick=(\d+) budget=(\d+) completed=(\d+) features=(\[.*\])",text)
    fail_unless(m,"missing native post-action/initial field status")
    return {"field_tick":int(m[1]),"budget":int(m[2]),"completed":int(m[3]),"features":finite_vector(m[4],6)}

def decision_line(line):
    m=re.fullmatch(r"geometry context=(\w+) field_bias=(\[.*?\]) (.+) selected=(\w+) baseline=(\w+)",line)
    fail_unless(m and m[1] in CONTEXTS,"invalid native geometry decision header")
    candidates={}
    parts=m[3].split()
    fail_unless(len(parts)==3,"missing geometry candidates")
    for part in parts:
        c=re.fullmatch(r"(\w+):truth=(POSITIVE|NEGATIVE|UNKNOWN|CONFLICT),eligible=([01]),base=([^,]+),score=(\S+)",part)
        fail_unless(c and c[1] in ACTIONS and c[1] not in candidates,"invalid native candidate")
        base,score=float(c[4]),float(c[5]);fail_unless(math.isfinite(base) and math.isfinite(score),"invalid candidate score")
        candidates[c[1]]={"truth":c[2],"eligible":c[3]=="1","base":base,"score":score,"bias_contribution":score-base}
    for picked in (m[4],m[5]):fail_unless(picked in candidates and candidates[picked]["eligible"],"engine chose an ineligible action")
    return {"context":m[1],"pre_choice_bias":finite_vector(m[2],3),"candidates":candidates,"selected":m[4],"baseline":m[5]}

class Geometry:
    def __init__(self,bin_dir,assets):
        self.bin=bin_dir.resolve(strict=True)
        self.module=(assets/"geometry.cl").read_bytes()
        protocol=(assets/"geometry31-protocol.json").read_bytes()
        fail_unless(sha(self.module)==MODULE_PIN and sha(protocol)==PROTOCOL_PIN,"module or frozen protocol differs")
        self.module_text=self.module.decode("utf8")
        self.tol=json.loads(protocol)["comparison"]
        self.engines={}
        for owner in ("alpha","beta"):
            path=self.bin/("pcgm-"+owner+".exe");caps=json.loads("\n".join(native(path,["--capabilities"])))
            fail_unless(caps.get("release")=="0.159","expected PCGM 0.159")
            self.engines[owner]=path
    def snapshot(self,path):
        snap=json.loads("\n".join(native(self.engines["alpha"],["--desktop-snapshot",path])))
        fail_unless(snap["owner"] in self.engines,"expected a managed, owned local save")
        return snap
    def execute(self,state,snap,commands):
        lines=native(self.engines[snap["owner"]],["--resume",state],commands)
        fail_unless(lines and lines[0].startswith("individual="+snap["individual"]+" "),"unexpected native identity")
        return lines[1:]
    def inspect(self,state):
        snap=self.snapshot(state);source=snap["source"]
        fail_unless(source.count(MARKER)<=1,"duplicate geometry module in active CL")
        installed=MARKER in source
        if installed:
            before,sep,after=source.partition(MARKER)
            fail_unless(after.startswith(self.module_text),"installed geometry module has different provenance; existing implementation preserved")
            outside=before+after[len(self.module_text):]
        else:outside=source
        fail_unless(not NAMESPACE.search(outside),"reserved geom_ namespace already contains foreign rules/observations")
        lines=self.execute(state,snap,[":history"])
        end=re.fullmatch(r"history_end event=(\d+)",lines[-1])
        fail_unless(end,"native history ended without a head")
        count=int(end[1]);installs=[];starts=[];ticks=[]
        for line in lines[:-1]:
            e=re.match(r"event=(\d+) (.+)",line);fail_unless(e,"invalid history row")
            index,body=int(e[1]),e[2]
            if body=="install geometry":installs.append(index)
            if body==INIT_EVENT:starts.append(index)
            if body.startswith("field_tick "):
                _,ctx,action=body.split()
                fail_unless(ctx in CONTEXTS and action in ACTIONS,"unexpected geometry history")
                ticks.append([index,ctx,action])
        fail_unless(installed==(len(installs)==1) and len(starts)<=1 and (not starts or (installed and installs[0]<starts[0])),"module and native history disagree")
        fail_unless(not ticks or (starts and starts[0]<ticks[0][0]),"native tick outside initialized history")
        current=None
        if starts:
            detail=self.execute(state,snap,[":field_status",":primordial"])
            fail_unless(len(detail)==2 and detail[1]==PRIME,"unexpected birth directions")
            current=status_line(detail[0])
            fail_unless(current["field_tick"]==len(ticks),"native replay tick count differs")
        return {"identity":snap["individual"],"owner":snap["owner"],"head":snap["head"],"native_event":count,"installed":installed,
                "module_sha256":MODULE_PIN if installed else None,"install_event":installs[0] if installed else None,
                "init_event":starts[0] if starts else None,"ticks":ticks,"status":current}
    def install(self,state,identity,expected_head=None):
        before=self.inspect(state);fail_unless(before["identity"]==identity,"wrong target identity")
        dest=state.parent/"modules"/"geometry.cl"
        if dest.exists():fail_unless(dest.read_bytes()==self.module,"existing different geometry.cl was preserved")
        if before["init_event"] and dest.is_file():return {"before":before,"after":before,"changed":False}
        if expected_head:fail_unless(expected_head==before["head"],"save changed before installation")
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            with tempfile.NamedTemporaryFile(dir=dest.parent,prefix="geometry-",suffix=".tmp",delete=False) as file:
                temp=Path(file.name);file.write(self.module);file.flush();os.fsync(file.fileno())
            try:temp.rename(dest)
            finally:temp.unlink(missing_ok=True)
        snap=self.snapshot(state)
        if not before["installed"]:
            reply=self.execute(state,snap,[":install geometry"])
            fail_unless(len(reply)==1 and reply[0].endswith("module_installed geometry"),"missing installation receipt")
        if not before["init_event"]:
            reply=self.execute(state,snap,[":field_start"])
            fail_unless(len(reply)==1 and status_line(reply[0])["field_tick"]==0,"missing native initialization")
        after=self.inspect(state)
        fail_unless(after["installed"] and after["init_event"] and after["identity"]==identity,"module activation failed")
        fail_unless(after["native_event"]-before["native_event"]==int(not before["installed"])+int(not before["init_event"]),"unrelated native events during install")
        return {"before":before,"after":after,"changed":True}
    def run_ticks(self,state,events,interval):
        snap=self.snapshot(state);records=[]
        for start in range(0,len(events),interval):
            part=events[start:start+interval]
            commands=[":field_tick "+v["context"] for v in part]
            lines=self.execute(state,snap,commands)
            fail_unless(len(lines)==2*len(part),"native tick receipts incomplete")
            for i,v in enumerate(part):
                decision=decision_line(lines[2*i]);post=status_line(lines[2*i+1])
                fail_unless(decision["context"]==v["context"],"evidence context changed")
                records.append({"source_event":v,"decision":decision,"post":post})
        return records
    def compare(self,a,b,path="result"):
        if isinstance(a,float) or isinstance(b,float):
            fail_unless(type(a) in (int,float) and type(b) in (int,float) and math.isclose(a,b,abs_tol=self.tol["absolute_tolerance"],rel_tol=self.tol["relative_tolerance"]),path+" differed")
        elif isinstance(a,dict):
            fail_unless(isinstance(b,dict) and a.keys()==b.keys(),path+" keys differed")
            for k in a:self.compare(a[k],b[k],path+"."+k)
        elif isinstance(a,list):
            fail_unless(isinstance(b,list) and len(a)==len(b),path+" length differed")
            for i,(x,y) in enumerate(zip(a,b)):self.compare(x,y,f"{path}[{i}]")
        else:fail_unless(a==b,path+" differed")
    def replay(self,state,events):
        before=self.inspect(state)
        with tempfile.TemporaryDirectory(prefix="zaizai-geometry-replay-") as td:
            base=Path(td)
            sa=clone_native(state,base/"continuous");sb=clone_native(state,base/"reopened")
            aa=self.install(sa,before["identity"])["after"];bb=self.install(sb,before["identity"])["after"]
            self.compare(aa,bb,"initial")
            cont=self.run_ticks(sa,events,len(events))
            reopened=self.run_ticks(sb,events,1)
            self.compare(cont,reopened,"continuous-versus-reopened")
            final_a=self.inspect(sa);final_b=self.inspect(sb)
            self.compare(final_a,final_b,"persisted")
            fail_unless(final_a["native_event"]==aa["native_event"]+len(events),"unexpected number of native events")
            fail_unless(final_a["status"]["field_tick"]==aa["status"]["field_tick"]+len(events),"field ticks missing or repeated")
            expected=[[aa["native_event"]+i+1,r["source_event"]["context"],r["decision"]["selected"]] for i,r in enumerate(cont)]
            fail_unless(final_a["ticks"][-len(events):]==expected,"event ordering or actions differ")
            self.compare(cont[-1]["post"],final_b["status"],"final-reopen")
        fail_unless(self.snapshot(state)["head"]==before["head"],"source save changed during replay")
        return {"passed":True,"protocol_sha256":PROTOCOL_PIN,"module_sha256":MODULE_PIN,"comparison":self.tol,"source_head":before["head"],
                "initialized":aa,"reopened":final_b,"lockstep_receipts":cont,"recorded_native_events":expected,"source_unchanged":True}

def input_events(path,db_path):
    events=json.loads(path.read_bytes())
    fail_unless(isinstance(events,list) and events,"a nonempty source-event list is required")
    seen=set();last=-1
    with closing(sqlite3.connect(db_path.resolve(strict=True).as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        for v in events:
            fail_unless(isinstance(v,dict) and set(v)=={"id","source","version","at","sha256","context"},"expected id,source,version,at,sha256,context")
            fail_unless(all(isinstance(x,str) and x for x in v.values()) and v["context"] in CONTEXTS and SHA256.fullmatch(v["sha256"]),"malformed experience record")
            when=datetime.fromisoformat(v["at"])
            fail_unless(when.utcoffset() is not None and when.timestamp()>=last and v["id"] not in seen,"experience replay order, timezone or id mismatch")
            last=when.timestamp();seen.add(v["id"])
            fail_unless(v["version"]=="local3-life3_events.detail/utf8@1","unsupported observation record version")
            row=db.execute("SELECT kind,created,detail FROM life3_events WHERE id=?",(v["id"],)).fetchone()
            fail_unless(row and sha(row[2].encode())==v["sha256"] and abs(row[1]-last)<.0011,"source observation, timestamp or digest mismatch")
            detail=json.loads(row[2])
            source=detail.get("source") or "local:life3/"+row[0]
            fail_unless(source==v["source"],"source locator differs from the recorded observation")
            fail_unless(CONTEXT_FROM_KIND.get(row[0])==v["context"],"source kind and frozen context encoding differ")
    return events

def step(g,state,identity,request,event):
    fail_unless(re.fullmatch(r"[\w.:@-]{1,160}",request),"invalid field operation id")
    dbpath=(state.parent/"dashboard-split.sqlite").resolve(strict=True)
    with closing(sqlite3.connect(dbpath.as_uri()+"?mode=rw",uri=True,timeout=8)) as db:
        db.row_factory=sqlite3.Row;db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS geo31_steps(request TEXT PRIMARY KEY,source_id TEXT UNIQUE NOT NULL,
              packet TEXT NOT NULL,identity TEXT NOT NULL,before_head TEXT NOT NULL,expected_head TEXT NOT NULL,
              phase TEXT NOT NULL CHECK(phase IN ('prepared','committed')),receipt TEXT NOT NULL,created REAL NOT NULL,committed REAL)""")
        current=g.inspect(state)
        fail_unless(current["identity"]==identity and current["init_event"],"target identity differs or geometry not initialized")
        old=db.execute("SELECT * FROM geo31_steps WHERE request=? OR source_id=?",(request,event["id"])).fetchall()
        if old:
            fail_unless(len(old)==1 and old[0]["identity"]==identity and old[0]["packet"]==packed(event) and old[0]["request"]==request,"event bound to another field request or request reused with different source")
            prior=old[0];receipt=json.loads(prior["receipt"])
            if prior["phase"]=="committed":
                fail_unless(receipt["event"] in current["ticks"],"committed field event missing in current save")
                return {"request":request,"outcome":"previously_committed","receipt":receipt}
        else:
            fail_unless(not db.execute("SELECT 1 FROM geo31_steps WHERE phase='prepared' LIMIT 1").fetchone(),"a prior field request is pending reconciliation")
            with tempfile.TemporaryDirectory(prefix="zaizai-field-plan-") as td:
                clone=clone_native(state,Path(td));planned=g.run_ticks(clone,[event],1)[0];post=g.inspect(clone)
                native_event=[current["native_event"]+1,event["context"],planned["decision"]["selected"]]
                fail_unless(post["ticks"][-1]==native_event and post["native_event"]==current["native_event"]+1,"native preflight did not commit exactly one event")
            receipt={"request":request,"identity":identity,"module_sha256":MODULE_PIN,"before_head":current["head"],
                     "after_head":post["head"],"event":native_event,"pre":current["status"],**planned}
            with db:db.execute("INSERT INTO geo31_steps VALUES(?,?,?,?,?,?,'prepared',?,?,NULL)",
                (request,event["id"],packed(event),identity,current["head"],post["head"],packed(receipt),time.time()))
        if current["head"]==receipt["after_head"]:
            origin="recovered_at_predicted_head"
            fail_unless(current["ticks"][-1:]==[receipt["event"]],"persisted field event differs")
            g.compare(current["status"],receipt["post"],"recovered_post")
        elif current["head"]==receipt["before_head"]:
            actual=g.run_ticks(state,[event],1)[0]
            g.compare(actual,{"source_event":event,"decision":receipt["decision"],"post":receipt["post"]},"native-versus-planned")
            after=g.inspect(state)
            fail_unless(after["head"]==receipt["after_head"] and after["ticks"][-1:]==[receipt["event"]],"native save head differs; original request retained for reconciliation")
            origin="native_commit"
        else:
            raise RuntimeError("field result uncertain after other native writes; retained the prepared request without dispatch")
        receipt["verification"]=origin
        with db:db.execute("UPDATE geo31_steps SET phase='committed',receipt=?,committed=? WHERE request=?",(packed(receipt),time.time(),request))
        return {"request":request,"outcome":origin,"receipt":receipt}

def run(args):
    state=args.state.resolve(strict=True)
    fail_unless(state.is_file() and state.parent.name=="state","supply an explicit native save located in its state/ directory")
    g=Geometry(args.bin_dir,args.assets.resolve(strict=True))
    with host_lock(state):
        if args.inspect:return g.inspect(state)
        if args.install:
            fail_unless(args.identity,"--install needs the original identity")
            return g.install(state,args.identity,args.expected_head)
        fail_unless(args.events,"supply actual dated experiences through --events")
        events=input_events(args.events,args.source_db or (state.parent/"dashboard-split.sqlite"))
        if args.replay:return g.replay(state,events)
        fail_unless(args.identity and args.request and len(events)==1,"--step needs --identity, --request and one experience")
        return step(g,state,args.identity,args.request,events[0])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    op=p.add_mutually_exclusive_group(required=True)
    for name in ("inspect","install","replay","step"):op.add_argument("--"+name,action="store_true")
    p.add_argument("--state",type=Path,required=True);p.add_argument("--bin-dir",type=Path,default=Path("D:/再再2.0/bin"))
    p.add_argument("--assets",type=Path,default=HERE);p.add_argument("--identity");p.add_argument("--expected-head")
    p.add_argument("--events",type=Path);p.add_argument("--source-db",type=Path);p.add_argument("--request");p.add_argument("--out",type=Path)
    args=p.parse_args();result=run(args)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf8",dir=args.out.parent,delete=False) as f:
            temp=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
        try:os.replace(temp,args.out)
        finally:temp.unlink(missing_ok=True)
    print(payload)

if __name__=="__main__":main()

