"""Rerun delivered acceptance programs against this Windows build."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
R=Path(__file__).resolve().parent;S=R/"source";LOG=R/"evidence"/"native-tests";LOG.mkdir(exist_ok=True,parents=True)
p=argparse.ArgumentParser();p.add_argument("--phase",choices=("basic","reference","all"),default="all");p.add_argument("--only",default="");o=p.parse_args()
for folder in (R/"bin",R/"reference-bin"):
 if not folder.is_dir():continue
 for f in folder.glob("*.exe"):
  for name in (f.name,f.stem):
   t=S/name
   if t.exists() and t.samefile(f):continue
   if t.exists():raise ValueError("Unrecognised previous artifact: "+str(t))
   os.link(f,t)
def filehash(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for row in (S/"handoff-checks/CORE-FIXTURE-SHA256SUMS").read_text().splitlines():
 pin,name=row.split(maxsplit=1);assert pin==filehash(S/name.strip())
cases=[]
for slot in ["alpha","beta","direct"]:
 pcgm=R/"bin"/("pcgm-"+slot+".exe") if slot!="direct" else R/"reference-bin/pcgm-projection-direct.exe"
 cl=R/"bin/cl.exe" if slot!="direct" else R/"reference-bin/cl-projection-direct.exe"
 if slot!="direct" and o.phase!="reference":
  for label,script,args in [("native","native-check",[cl,pcgm]),("anchored","anchored-check",[pcgm]),("enroll","enroll-check",[pcgm]),("resident","resident-check",[pcgm,cl]),("lost-ack","resident-check",[pcgm,cl,"lost-ack"]),("frozen-answer","frozen-answer-check",[pcgm,cl]),("arithmetic","arithmetic-check",[pcgm])]:
   cases.append((label+"-"+slot,S/"handoff-checks"/(script+".py"),args))
  cases.append(("full-integration-"+slot,R/"codex/integration/frozen-answer-to-repair.py",[S,slot]))
 if (slot=="direct" and o.phase!="basic") or (slot!="direct" and o.phase!="reference"):
  for label,script,args in [("agenda","work-agenda-check",[pcgm,cl]),("repair","repair-check",[pcgm]),("outcomes","reasoned-outcome-check",[pcgm,cl])]:
   cases.append((label+"-"+slot,S/"handoff-checks"/(script+".py"),args))
if o.phase!="reference":cases+= [(n,S/("check-"+n+".py"),[]) for n in ("frozen-proof-admission","criteria-questions","question-handoff","choice-reassessment","observation-replay-audit")]
if o.phase!="basic":cases.append(("native-projection",S/"check-native-projection.py",[]))
def run(case):
 name,path,args=case;t=time.monotonic()
 try:
  p=subprocess.run([sys.executable,"-X","utf8","-B",R/"tools/windows_test.py",path,*args],cwd=S,stdin=subprocess.DEVNULL,capture_output=True,timeout=160,env=dict(os.environ,ZAIZAI_CPU_ONLY="1",PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1"),creationflags=subprocess.CREATE_NO_WINDOW)
  (LOG/(name+".log")).write_bytes(p.stdout);(LOG/(name+".stderr")).write_bytes(p.stderr);rc=p.returncode
  print(name,rc,("" if not rc else p.stderr.decode("utf8","replace")[-380:]),flush=True)
 except subprocess.TimeoutExpired as exc:
  rc=-999;(LOG/(name+".log")).write_bytes(exc.stdout or b"");(LOG/(name+".stderr")).write_bytes(exc.stderr or b"");print(name,"TIMEOUT",flush=True)
 return {"name":name,"exit":rc,"seconds":round(time.monotonic()-t,3),"source_sha256":filehash(path)}
if o.only:cases=[c for c in cases if c[0] in o.only.split(",")]
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,cases))
for row in results:(LOG/(row["name"]+".json")).write_text(json.dumps(row),encoding="utf8")
raise SystemExit(any(x["exit"]!=0 for x in results))
