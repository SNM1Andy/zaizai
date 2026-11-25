"""Run the unchanged 2.0 dialogue suite on a separate writable 3.0 install copy."""
import argparse
from contextlib import closing
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

LIVE=Path(r"D:\再再2.0").resolve()
CASES=("W02","W03","W04","W07","W10","W11","W13","W16")

def require(ok,reason):
    if not ok:
        raise ValueError(reason)

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def reader(path):
    db=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=3)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db

def detached(root):
    require(root!=LIVE and root.exists(),"验收需要独立的构建副本")
    for sub in ("state","evidence","tools","host"):
        directory=root/sub
        require(directory.resolve()==directory and directory.is_dir(),"验收目录须属于构建副本："+sub)
    for name in ("dashboard-split.sqlite","individual.pcgm","desktop-writer.lock"):
        staged=root/"state"/name;live=LIVE/"state"/name
        if name!="desktop-writer.lock":require(staged.is_file(),"缺少副本状态："+name)
        if staged.exists():
            require(staged.resolve()==staged and not (live.exists() and staged.samefile(live)),"状态文件与正式库共享："+name)
    sys.path.insert(0,str(root/"host"))
    import native
    import service
    import evolution3
    for module in (native,service,evolution3):
        require(Path(module.__file__).resolve().parent==root/"host","加载的宿主并非待验副本")
    require(native.ROOT==root and native.STATE==root/"state" and native.DB==root/"state/dashboard-split.sqlite"
            and native.SAVE==root/"state/individual.pcgm","候选宿主实际连接的存档并非待验副本")
    return native,evolution3

def run_case(root,script,extra,name,archive):
    path=root/script;artifact=root/"evidence"/name
    require(path.is_file() and path.resolve().is_relative_to(root),"验收程序应来自构建副本")
    if archive and script.startswith("tools/"):
        frozen=archive.parent/script
        if frozen.exists():require(digest(frozen)==digest(path),"原版验收断言被替换："+script)
    old=artifact.stat().st_mtime_ns if artifact.exists() else None
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", ZAIZAI_CPU_ONLY="1")
    p=subprocess.run([root/"runtime/python.exe","-X","utf8","-B",path,*extra],cwd=root,
                     env=env,capture_output=True,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:
        # These fixed test programs print request examples/receipt identifiers; expose only the final error line.
        last=(p.stderr or p.stdout).decode("utf8","replace").strip().splitlines()
        raise RuntimeError(f"{script} exit={p.returncode} {last[-1][:350] if last else ''}")
    require(artifact.is_file() and artifact.stat().st_mtime_ns!=old,"进程没有生成新的 "+name)
    return json.loads(artifact.read_bytes()),{"script":script,"arguments":extra,"exit":p.returncode,
        "test_sha256":digest(path),"receipt_file":name,"receipt_sha256":digest(artifact)}

def verify_prefix(root,archive):
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory(prefix="zaizai-history-gate-") as tmp:
        manifest=json.loads(z.read("manifest.json"))
        state=manifest["state"];member="dashboard-split.sqlite"
        original=Path(tmp)/member
        original.write_bytes(z.read("state/"+member))
        require(digest(original)==manifest["files"][member],"封存基线数据库摘要不符")
        with closing(reader(original)) as a,closing(reader(root/"state"/member)) as b:
            a.execute("BEGIN");b.execute("BEGIN")
            maxseq=state["last_seq"]
            old=a.execute("SELECT * FROM turns ORDER BY seq")
            new=b.execute("SELECT * FROM turns WHERE seq<=? ORDER BY seq",(maxseq,))
            require([r[0] for r in old.description]==[r[0] for r in new.description],"历史表字段不一致")
            count=0
            for x,y in itertools.zip_longest(old,new):
                require(x is not None and y is not None and tuple(x)==tuple(y),"历史前缀的某一行与 2.0 封存不一致")
                count+=1
            require(count==state["turns"] and count>=3,"2.0 前缀行数不符")
            receipts=0
            for row in a.execute("SELECT id,seq,digest,answer,native_receipt FROM requests WHERE phase='committed'"):
                n=b.execute("SELECT id,seq,digest,answer,native_receipt FROM requests WHERE id=? AND phase='committed'",(row[0],)).fetchone()
                require(n is not None and tuple(n)==tuple(row),"迁移后已提交回执不一致")
                receipts+=1
        return {"archive_sha256":digest(archive),"legacy_identity":state["identity"],"old_turns_equal":count,
                "committed_receipts_equal":receipts,"up_to_seq":maxseq}

def verify_window(n,root,raw,question):
    require(raw["ready"] and raw["window_mapped"] and raw["monitor_mapped"] and raw["message_displayed"]
            and raw["monitor_displayed"] and not raw["error"],"实际对话或监测窗口未显示同一事务")
    require(raw["identity"]==n.IDENTITY and raw["host_sha256"]==digest(root/"host/desktop.py"),"窗口身份或宿主摘要不一致")
    require(all(digest(root/f"bin/pcgm-{k}.exe")==v for k,v in raw["builds"].items()) and
            set(raw["builds"])=={"alpha","beta"},"窗口引擎与当前构建不一致")
    with closing(reader(n.DB)) as db:
        data=db.execute("""SELECT r.*,t.request AS turn_input,t.response AS turn_output,t.identity AS turn_identity
            FROM requests r JOIN turns t ON r.seq=t.seq WHERE r.id=?""",(raw["request"],)).fetchone()
        require(data and data["phase"]=="committed" and data["delivered"] is not None
                and data["session"]==raw["session"] and data["source"]=="desktop" and data["native_receipt"]
                and data["question"]==data["turn_input"] and data["answer"]==data["turn_output"]
                and data["turn_identity"]==raw["identity"],"SQLite 对话、原生回执或实际送达标记不一致")
    plan=json.loads(data["plan"]);frozen=plan["proof"]
    atom="ready_to_use(local_term)" if question else "identity_restored(zaizai)"
    require(data["question"]=="证明 "+atom and frozen["proof"]["engine"]=="cl","桌面查询缺少对应的独立 CL 证明")
    live=n.proof_for(atom)
    status="UNKNOWN" if question else "POSITIVE"
    require(frozen["source_sha256"]==live["source_sha256"] and frozen["proof"]==live["proof"]
            and frozen["proof"]["results"][0]["status"]==status,"重新运行独立 CL 后结果不同")
    if question:
        require(raw["questions"] and raw["questions"]==plan["questions"],"缺前提桌面回复没有关联原生问题")
        for item in raw["questions"]:
            q=n.readcmd("question "+item["id"])["results"][0]
            require(q["request_sha256"]==item["request_sha256"] and q["status"]==item["status"]=="open","桌面提问与原生题号版本不符")
    else:
        require("positive=CLEAN_WITNESS" in frozen["integrity"],"身份依据缺少可用证明")
    return {"request":raw["request"],"turn_seq":data["seq"],"delivered":data["delivered"],
            "source_sha256":frozen["source_sha256"],"pcgm_head":frozen["pcgm_head"],"cl_status":status,
            "dpi":raw["dpi"],"geometry":raw["geometry"],"questions":len(raw.get("questions",[]))}

def timing(path):
    data=json.loads(path.read_bytes());rows=data["rows"]
    require(isinstance(rows,list) and rows and len(rows)==data["n"],"工作量样本数不符")
    millis=sorted(float(r["ms"]) for r in rows)
    require(all(math.isfinite(t) and t>=0 for t in millis),"时延样本无效")
    result={"median_ms":statistics.median(millis),"p95_ms":millis[int(.95*(len(rows)-1))],"mean_ms":statistics.mean(millis)}
    require(all(math.isclose(data[k],v,rel_tol=1e-9,abs_tol=1e-7) for k,v in result.items()),"汇总统计与逐次实测时延不符")
    errors=sum(row["error"] is not None for row in rows)
    require(errors==data["errors"],"错误数与明细不符")
    result.update(n=len(rows),errors=errors,error_rate=errors/len(rows),file_sha256=digest(path))
    return result,[row["query"] for row in rows]

def main(args):
    root=args.root.resolve(strict=True)
    n,e=detached(root)
    initial=e.protected_hashes()
    if args.baseline_source:
        archive=args.baseline_source.resolve(strict=True)
    else:
        sealed=sorted((LIVE/"rollback").glob("local3-pre-*/sealed-2.0.zip"),
                      key=lambda p:p.stat().st_mtime_ns,reverse=True)
        archive=sealed[0] if sealed else None
        if archive is None and (LIVE/"INSTALL.json").is_file():
            previous=json.loads((LIVE/"INSTALL.json").read_bytes()).get("latest_verified_backup")
            if previous and Path(previous).is_file():
                archive=Path(previous).resolve()
    out=args.out.resolve()
    require(not out.is_relative_to(n.STATE) and not out.is_relative_to(LIVE/"state"),"回归报告不能写入正式存档或副本存档")
    log={"schema":"zaizai-dialogue-gate-v1","root":str(root),"identity":n.IDENTITY,
         "checked_at_unix":time.time(),"cases":dict.fromkeys(CASES,False),"checks":{},"protected_sha256":initial,
         "latency_ok":False,"errors_ok":False}
    def record(name,fn):
        start=time.monotonic()
        try:
            info=fn()
            log["checks"][name]={"passed":True,"details":info,"seconds":round(time.monotonic()-start,3)}
            print(name,"OK",flush=True)
            return True
        except Exception as exc:
            log["checks"][name]={"passed":False,"error":str(exc)[:550],"seconds":round(time.monotonic()-start,3)}
            print(name,"FAIL",str(exc)[:310],flush=True)
            return False
    def migration():
        raw,trace=run_case(root,"tools/migrate.py",[],"migration.json",archive)
        require(raw["identity"]==n.IDENTITY and raw["source_rows_equal_target"] and raw["original_seq"]==[1,2,3]
                and raw["migrated_turns"]==3 and len(raw["legacy_native_files"])==152,"1.0 迁移基线不符")
        return dict(trace,original_turns=raw["migrated_turns"],native_files=len(raw["legacy_native_files"]))
    migration_ok=record("old_1_0_migration",migration)
    history_ok=record("all_2_0_history",lambda:verify_prefix(root,archive)) if archive else False
    if not archive:
        log["checks"]["all_2_0_history"]={"passed":False,"error":"未提供 2.0 存档。仅能核对 1.0 三条历史。"}
    log["cases"]["W03"]=migration_ok and history_ok
    def continuity():
        raw,trace=run_case(root,"tools/check_continuity.py",[],"continuity.json",archive)
        require(raw["question"]["both"]["status"]=="conflicted" and raw["question"]["after_withdrawal"]["status"]=="open"
               and {"candidate","adoption","withdraw"}<=raw["lexicon"].keys()
               and {"a","b","lexicon","chosen","remembered","recovered"}<=raw["dialogue"].keys()
               and raw["dialogue"]["a"]!=raw["dialogue"]["b"],"原生问询、词条或多轮记忆的验证明细不足")
        return dict(trace,question=raw["question"]["id"],lexicon=raw["lexicon"],dialogue=raw["dialogue"])
    cont=record("dialogue_lexicon_question_memory",continuity)
    log["cases"]["W07"]=log["cases"]["W11"]=cont
    def crash():
        raw,trace=run_case(root,"tools/check_crash.py",[],"crash.json",archive)
        require(all(raw[k]["phase_at_kill"]==phase and raw[k]["native_events_added"]==1
                 and raw[k]["final"]=="committed" and raw[k]["identity"]==n.IDENTITY
                 for k,phase in {"before":"planned","native":"prepared","after":"committed"}.items()),"中断恢复阶段或提交次数不符")
        return dict(trace,requests={k:v["id"] for k,v in raw.items()})
    log["cases"]["W04"]=record("crash_replay",crash)
    def decisions():
        raw,trace=run_case(root,"tools/check_decisions.py",[],"decisions.json",archive)
        require(raw["identity"]==n.IDENTITY and raw["stay"][1]=="stay" and raw["last"][1]=="stay"
                and raw["rewrite"]==["committed","rewrite"] and raw["rollback"]==["committed","rollback"],
                "保留、改写、回档或恢复后取舍不符")
        return dict(trace,sequence=[raw["stay"],raw["rewrite"],raw["rollback"],raw["last"]])
    log["cases"]["W13"]=record("decisions",decisions)
    def window(question):
        args=["--verify-window"]
        if question:args.append("--verify-question")
        raw,trace=run_case(root,"host/desktop.py",args,"window-question.json" if question else "window.json",archive)
        return dict(trace,transaction=verify_window(n,root,raw,question))
    win=record("window_independent_proof",lambda:window(False))
    question=record("window_addressed_question",lambda:window(True))
    log["cases"]["W02"]=win
    log["cases"]["W16"]=win and question
    log["cases"]["W10"]=cont and question
    def benchmark():
        old,qa=timing(args.baseline);new,qb=timing(args.benchmark)
        require(qa==qb,"基线与候选的实际工作负载或顺序不同")
        metrics={k:new[k]<=old[k] for k in ("mean_ms","median_ms","p95_ms")}
        log["benchmark"]={"baseline":old,"candidate":new,"nonregression":metrics}
        log["latency_ok"]=all(metrics.values())
        log["errors_ok"]=new["error_rate"]<=old["error_rate"]
        require(log["latency_ok"] and log["errors_ok"],"时延或错误率高于 2.0 基线")
        return {"matched_samples":len(qa),"workload_sha256":hashlib.sha256(json.dumps(qa,ensure_ascii=False).encode()).hexdigest()}
    record("timings",benchmark)
    def verify_hashes():
        require(initial==e.protected_hashes(),"回归期间受保护构建发生变化")
        return {"files":len(initial)}
    stable=record("unchanged_build",verify_hashes)
    log["passed"]=all(log["cases"].values()) and log["latency_ok"] and log["errors_ok"] and stable
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",dir=out.parent,suffix=".tmp",encoding="utf8",delete=False) as f:
        json.dump(log,f,ensure_ascii=False,indent=2)
        f.flush();os.fsync(f.fileno())
        partial=Path(f.name)
    os.replace(partial,out)
    print("PASS" if log["passed"] else "FAIL",str(out),flush=True)
    return 0 if log["passed"] else 1

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for arg in ("root","baseline","benchmark","out"):
        parser.add_argument("--"+arg,required=True,type=Path)
    parser.add_argument("--baseline-source",type=Path)
    raise SystemExit(main(parser.parse_args()))
