"""Frozen local scheduling comparisons with real CL wall time and an independent watchdog."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import evolution3 as e

# Defined before observing any outcomes. The unchanged work uses one CL invocation per lane.
# The two contrasts validate both useful work and an expensive successful alternative.
SCENARIOS=(("single_compile_each",1,1),("independent_rejected_prerequisites",8,1),("independent_positive_proofs",1,8))
LANES=("blocked_compilation","independent_compilation")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def commit_report(path,report):
    if path:
        temp=path.with_name(path.name+"."+str(os.getpid())+".tmp")
        with temp.open("w",encoding="utf8",newline="\n") as f:
            json.dump(report,f,indent=2,ensure_ascii=False,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(temp,path)


def make_inputs(directory,errors,proofs):
    paths={key:[] for key in LANES}
    for i in range(errors):
        # Each separate document is a different unresolved prerequisite of this lane's operation.
        path=directory/f"missing_{i}.cl"
        lines=[f"& e{j} valid(v{j})." for j in range(1300)]
        path.write_bytes((": valid(sym).\n"+"\n".join(lines)+f"\n? valid{i}(.\n").encode())
        paths[LANES[0]].append(path)
    for i in range(proofs):
        path=directory/f"available_{i}.cl"
        path.write_bytes(f": valid(sym).\n& local_{i} valid(g{i}).\n? valid(g{i}).\n".encode())
        paths[LANES[1]].append(path)
    return paths


def policy_criteria(db,raw):
    rows=list(db.execute("""SELECT a.arm,e.event_id,e.progress,e.failed,e.duration_ms FROM evo3_assignments a
        JOIN evo3_events e ON a.event_id=e.event_id AND e.lane=a.chosen
        WHERE a.trial=1 AND a.arm IN ('reference','canary') ORDER BY e.seq"""))
    for arm in ("canary","reference"):
        sample=[r for r in rows if r[0]==arm];stats=raw[arm]
        values=sorted(r[4] for r in sample)
        assert len(values)==stats["count"] and [r[1] for r in sample]==stats["events"]
        assert stats["median_ms"]==values[len(values)//2]
        assert stats["progress_rate"]==sum(r[2]>0 and not r[3] for r in sample)/len(sample)
        assert stats["fail_rate"]==sum(r[3] for r in sample)/len(sample)
    canary,reference=raw["canary"],raw["reference"]
    return {"more_progress":canary["progress_rate"]>reference["progress_rate"],
            "no_more_failures":canary["fail_rate"]<=reference["fail_rate"],
            "within_frozen_latency":canary["median_ms"]<=max(5.0,reference["median_ms"]*1.25),
            "dialogue_gate_open":e.gate_status()[0]}


def run_comparison(db,directory,name,errors,proofs,live_gate,group):
    paths=make_inputs(directory,errors,proofs)
    group["inputs_sha256"]={p.name:sha(p.read_bytes()) for entries in paths.values() for p in entries}
    group["steps"]=[]
    env=dict(os.environ,ZAIZAI_CPU_ONLY="1")
    def step():
        ident=name+"_"+str(len(group["steps"])+1)
        with db:
            lane=e.select_lane(db,ident,LANES)
            assert e.select_lane(db,ident,LANES)==lane
        started_at=time.time_ns();start=time.perf_counter_ns()
        results=[]
        for path in paths[lane]:
            p=subprocess.run([ROOT/"bin/cl.exe","json",path],capture_output=True,env=env,
                             timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            if lane==LANES[0]:
                assert p.returncode!=0 and b"identifier" in p.stderr.lower(),p.stderr
            else:
                assert p.returncode==0 and json.loads(p.stdout)["results"][0]["status"]=="POSITIVE"
            results.append({"input":path.name,"exit":p.returncode,"output_sha256":sha(p.stderr if p.returncode else p.stdout)})
        elapsed=(time.perf_counter_ns()-start)/1_000_000
        ok=all(r["exit"]==0 for r in results)
        data={"topic":name,"status":"verified" if ok else "rejected","progress":int(ok),"category":"rule",
              "duration_ms":elapsed,"summary":"all inputs proved" if ok else "unresolved prerequisites","executed_lane":lane}
        with db:
            e.observe(db,ident,lane,data);e.observe(db,ident,lane,data)
        arm,revision=db.execute("SELECT arm,revision FROM evo3_assignments WHERE event_id=?",(ident,)).fetchone()
        group["steps"].append({"event":ident,"lane":lane,"arm":arm,"revision":revision,"duration_ms":elapsed,
                               "started_ns":started_at,"result":"proved" if ok else "rejected","runs":results})

    with db:e.setup(db)
    for _ in range(3):step()
    with db:opened=e.advance(db)
    assert opened["kind"]=="evolution_demand"
    with db:shadow=e.advance(db)
    assert shadow["kind"]=="evolution_shadow"
    group["shadow"]=json.loads(db.execute("SELECT shadow FROM evo3_demands WHERE id=1").fetchone()[0])
    actual=e.GATE_FILE
    try:
        e.GATE_FILE=directory/"gate.json"
        with db:blocked=e.advance(db)
        assert blocked["kind"]=="evolution_gate" and e.policy(db)["revision"]==1
        group["missing_gate_refused"]=True
        if live_gate:
            e.GATE_FILE=actual
            assert e.gate_status()[0],e.gate_status()
        else:
            fixed=e.protected_hashes()
            gate={"passed":True,"latency_ok":True,"errors_ok":True,"cases":dict.fromkeys(e.CASE_IDS,True),"protected_sha256":dict(fixed)}
            gate["protected_sha256"]["host/evolution3.py"]="0"*64
            e.GATE_FILE.write_text(json.dumps(gate),encoding="utf8");assert not e.gate_status()[0]
            gate["protected_sha256"]=fixed
            e.GATE_FILE.write_text(json.dumps(gate),encoding="utf8")
        with db:canary=e.advance(db)
        assert canary and canary["kind"]=="evolution_canary",canary
        for _ in range(400):
            step()
            with db:decision=e.advance(db)
            if decision:
                assert decision["kind"] in ("evolution_applied","evolution_stay"),decision
                break
        else:raise RuntimeError("实际差异派工样本不足")
        group["actual_canary"]=json.loads(db.execute("SELECT evaluation FROM evo3_demands WHERE id=1").fetchone()[0])
        group["decision"]=decision["kind"]
        criteria=policy_criteria(db,group["actual_canary"])
        group["criteria"]=criteria
        applied=all(criteria.values())
        assert applied==(decision["kind"]=="evolution_applied"),(decision,criteria)
        revision=e.policy(db)["revision"]
        assert (revision!=1)==applied
        if applied:
            db.execute("BEGIN IMMEDIATE")
            e.rollback(db,"test interruption");db.rollback()
            assert e.policy(db)["revision"]==revision
            with db:
                e.observe(db,"later","knowledge",{"topic":"later","status":"verified","progress":1});e.rollback(db,"verified restore")
            assert e.policy(db)["revision"]==1
            assert db.execute("SELECT 1 FROM evo3_events WHERE event_id='later'").fetchone()
            group["rollback"]={"baseline":1,"promoted":revision,"restored":1,"later_evidence_preserved":True,
                               "interrupted_rollback_preserved_revision":True}
        else:
            changes=db.execute("SELECT count(*) FROM evo3_transitions WHERE reason='promoted'").fetchone()[0]
            assert changes==0 and revision==1
            group["stay"]={"revision":revision,"promotions":changes,"failed_criteria":[k for k,v in criteria.items() if not v]}
        count,unique=db.execute("SELECT count(*),count(distinct event_id) FROM evo3_events").fetchone()
        assert count==unique==len(group["steps"])+int(applied)
        group["actual_cl_runs"]=sum(len(row["runs"]) for row in group["steps"])
    finally:e.GATE_FILE=actual


def check_watchdog(directory):
    dbfile=directory/"watch.sqlite"
    with closing(sqlite3.connect(dbfile)) as db:
        db.execute("CREATE TABLE life3_meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("CREATE TABLE turns(identity TEXT)")
        db.execute("INSERT INTO turns VALUES('same-local-id')")
        with subprocess.Popen([sys.executable,"-c","import time; time.sleep(20)"],creationflags=subprocess.CREATE_NO_WINDOW) as worker:
            with db:
                db.executemany("INSERT INTO life3_meta VALUES(?,?)",[
                    ("pid",str(worker.pid)),("heartbeat",str(time.time())),("paused","0"),("mode","test")])
            log=directory/"observer.jsonl"
            args=[sys.executable,"-B",ROOT/"host/watchdog3.py","--database",dbfile,"--log",log,"--parent",str(worker.pid),
                  "--identity","same-local-id","--interval",".05","--stale-after","1.5"]
            p=subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(150):
                    if log.exists() and "worker_stale" in log.read_text(encoding="utf8"):break
                    time.sleep(.05)
                worker.terminate();worker.wait(timeout=4);p.wait(timeout=4)
            finally:
                if p.poll() is None:p.kill();p.wait()
                if worker.poll() is None:worker.kill();worker.wait()
            states=[row["state"] for row in map(json.loads,log.read_text(encoding="utf8").splitlines())]
            assert states==["healthy","worker_stale","worker_exit"],states
            snapshot=sha(dbfile.read_bytes())
            args[args.index(str(worker.pid))]=str(os.getpid())
            one=subprocess.run(args+["--once"],capture_output=True,timeout=4)
            assert one.returncode==2 and sha(dbfile.read_bytes())==snapshot
            return {"states":states,"read_only_database":True}


def run(require_gate,output,previous_stay):
    prior=[]
    if output and output.exists():
        raw=output.read_bytes();old=json.loads(raw);prior=old.pop("prior_runs",[])
        prior.append({"artifact_sha256":sha(raw),"report":old})
    report={"schema":"zaizai-local-iteration-workloads-v2","prior_runs":prior,"passed":False,
            "specification":[{"name":n,"blocked_inputs":b,"proved_inputs":g} for n,b,g in SCENARIOS],
            "clock":"time.perf_counter_ns / 1e6, elapsed per actual work unit",
            "dialogue_gate":"actual deployment regression receipt" if require_gate else "gate fixture on private ledger",
            "frozen_spec_sha256":sha(Path(__file__).read_bytes()),"started_ns":time.time_ns(),"scenarios":[]}
    if previous_stay:
        report["earlier_unrecorded_run"]={"outcome":"evolution_stay","source":"previous harness assertion observed by release operator",
            "latencies":None,"note":"previous harness raised before persisting temporary ledger or measured latency"}
    if require_gate:
        assert e.gate_status()[0],e.gate_status()
        report["gate_sha256"]=sha(e.GATE_FILE.read_bytes())
    # Even when a comparison fails, preserve every completed step and run the other predeclared contrasts.
    with tempfile.TemporaryDirectory(prefix="zaizai-iteration-") as temp:
        root=Path(temp).resolve()
        for name,errors,proofs in SCENARIOS:
            d=root/name;d.mkdir()
            group={"name":name};report["scenarios"].append(group)
            try:
                with closing(sqlite3.connect(d/"ledger.sqlite")) as db:
                    db.row_factory=sqlite3.Row
                    run_comparison(db,d,name,errors,proofs,require_gate,group)
                group["passed"]=True
            except Exception as exc:
                group["passed"]=False;group["error"]=f"{type(exc).__name__}: {exc}"
            commit_report(output,report)
        try:report["watchdog"]=check_watchdog(root)
        except Exception as exc:report["watchdog"]={"error":repr(exc)}
    indexed={row["name"]:row for row in report["scenarios"]}
    promotion=indexed[SCENARIOS[1][0]]
    if promotion.get("rollback"):
        report["real_shadow"]=promotion["shadow"]
        report["actual_canary"]=promotion["actual_canary"]
        report["rollback"]=dict(promotion["rollback"],actual_cl_runs=promotion["actual_cl_runs"],scenario=promotion["name"])
    report["coverage"]={"expensive_blocked_lane_promoted_and_rolled_back":bool(indexed[SCENARIOS[1][0]].get("rollback")),
        "expensive_positive_lane_retained_due_to_latency":
            "within_frozen_latency" in indexed[SCENARIOS[2][0]].get("stay",{}).get("failed_criteria",[])}
    report["passed"]=all(r["passed"] for r in report["scenarios"]) and "error" not in report["watchdog"] and all(report["coverage"].values())
    report["finished_ns"]=time.time_ns()
    commit_report(output,report)
    print(json.dumps({"passed":report["passed"],"coverage":report["coverage"],"watchdog":report["watchdog"],
        "scenarios":[{"name":r["name"],"decision":r.get("decision"),"runs":r.get("actual_cl_runs"),
                      "error":r.get("error"),"summary":r.get("actual_canary")} for r in report["scenarios"]]},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--require-live-gate",action="store_true")
    parser.add_argument("--prior-observed-stay",action="store_true",help="记录旧版在写出结果前已观察到的一次不改决定")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    raise SystemExit(run(args.require_live_gate,args.output,args.prior_observed_stay))
