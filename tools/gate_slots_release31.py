"""Run split release gates on same-identity, private copies. Never bind slots in the live installation."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

LIVE=Path("D:/再再2.0").resolve()
def h(file):
    with file.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def read(p):return json.loads(p.read_text(encoding="utf-8-sig"))
def dump(p,v):
    tmp=p.with_name(p.name+".partial");tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf8");os.replace(tmp,p)
def need(value,message):
    if not value:raise ValueError(message)
def run(py,script,*args,timeout=200):
    cmd=[str(py),"-B","-X","utf8",str(script),*map(str,args)]
    result=subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        tail=(result.stderr or result.stdout).decode("utf8","replace")
        raise RuntimeError(script.name+" failed: "+tail[-2300:])
    return result.stdout.decode("utf8","replace")

def prefix(dbfile,archive):
    db=sqlite3.connect(dbfile.as_uri()+"?mode=ro",uri=True);db.execute("BEGIN")
    with closing(db),tempfile.TemporaryDirectory() as td,zipfile.ZipFile(archive) as z:
        old=Path(td)/"old.sqlite";old.write_bytes(z.read("state/dashboard-split.sqlite"))
        with closing(sqlite3.connect(old.as_uri()+"?mode=ro",uri=True)) as source:
            initial=source.execute("SELECT * FROM turns ORDER BY seq").fetchall()
            current=db.execute("SELECT * FROM turns WHERE seq<=? ORDER BY seq",(initial[-1][0],)).fetchall()
            need(current==initial,"升级前的完整历史前缀不一致")
            entries=source.execute("SELECT id,phase,seq,native_receipt,answer FROM requests ORDER BY id").fetchall()
            for o in entries:
                need(db.execute("SELECT id,phase,seq,native_receipt,answer FROM requests WHERE id=?",(o[0],)).fetchone()==o,"旧请求或已提交回执发生变化")
            return {"unchanged_turns":len(initial),"unchanged_requests":len(entries),
                    "semantics":"matched full original rows and original request phase, sequence, adapter receipt and response"}
def main(opts):
    root=opts.root.resolve(strict=True);empty=opts.empty_root.resolve(strict=True);py=LIVE/"runtime/python.exe";out=root/"evidence"
    for wd in (root,empty):
        need(wd!=LIVE and (wd/"host").resolve()==wd/"host" and (wd/"state").resolve()==wd/"state" and
            not (wd/"state/dashboard-split.sqlite").samefile(LIVE/"state/dashboard-split.sqlite"),"需要独立候选状态")
    need(not (empty/"bin").exists() and not (empty/"state/individual.pcgm").exists(),"独立组必须实际移除两槽二进制与认知私有状态")
    sys.path.insert(0,str(root/"host"))
    import service as s,slots31 as slots,evolution3
    base=evolution3.protected_hashes()
    for name,pin in base.items():need(h(empty/name)==pin,"两个待验宿主的代码版本不同："+name)
    all_groups={};report={"schema":"zaizai-host-slot-gate/1","cases":{},"latency_ok":False,"errors_ok":False,
        "protected_sha256":base,"slot_groups":all_groups,"details":{},"failures":{},"time":time.time()}
    report["prefix_before"]=prefix(root/"state/dashboard-split.sqlite",opts.archive)
    def test(name,fn):
        start=time.monotonic()
        try:
            val=fn();all_groups[name]=True;report["details"][name]={"passed":True,"wall_seconds":round(time.monotonic()-start,3),"result":val}
            print(name,"PASS",flush=True)
        except Exception as exc:
            all_groups[name]=False;report["failures"][name]=str(exc);print(name,"FAIL",str(exc)[:1200],flush=True)
    def named(script,folder,args,output):
        f=folder/"evidence"/output;start=time.time_ns()
        run(py,folder/"tools"/script,*args,"--out",f)
        need(f.is_file() and f.stat().st_mtime_ns>=start-2_000_000_000,"缺少本轮验收回执")
        return read(f)
    def independent():
        data=named("check_host_slots31.py",empty,["--root",empty],"slot-independent.json")
        need(data["passed"] and data["engine_files_present"]==[] and not data["native_save_present"] and len(data["interruptions"])==4,"宿主独立组核对失败")
        shutil.copyfile(empty/"evidence/slot-independent.json",out/"slot-independent.json")
        return {"cuts":data["interruptions"],"real_window":data["two_window_status"],"old_memory":data["memory_readback"]}
    test("host_independent",independent)
    def checkpoint():
        token=str(time.time_ns());save=empty/("checkpoint-"+token+".zip");dst=empty/("restore-"+token)
        before=json.loads(run(py,empty/"tools/save_state.py","backup",save));after=json.loads(run(py,empty/"tools/save_state.py","restore-to",save,dst))
        need(before==after and before.get("native_sha256") is None and all(x["id"]=="empty" for x in before["slot_manifests"].values()),
             "无槽备份还原未对齐")
        return {"matched":True,"turns":before["turns"],"slots":[x["id"] for x in before["slot_manifests"].values()],"archive_sha256":h(save)}
    test("checkpoint",checkpoint)
    def contracts():
        data=named("check_slots31.py",root,["--root",root,"--archive",opts.archive],"slot-contracts.json")
        need(len(data["legacy_ports"])==15 and len(data["external_fixture_ports"])==15 and data["previous_proof_reproduced"],"契约覆盖不足")
        return {"legacy_ports":data["legacy_ports"],"fixture_ports":data["external_fixture_ports"],"faults":data["isolated_failures"],"file":"slot-contracts.json"}
    test("port_contracts",contracts)
    def swap():
        data=named("check_slot_swap31.py",root,["--root",root,"--archive",opts.archive],"slot-swap.json")
        need(data.get("passed") is True,"实际宿主换槽未通过")
        return {"file":"slot-swap.json","passed":True}
    test("binding_rehearsal",swap)
    def sources():
        life=named("check_life_slots31.py",root,["--root",root],"slot-host-life.json")
        memory=named("check_slot_ownership31.py",root,["--root",root],"slot-memory-exam.json")
        need(memory["passed"] and life["empty_legacy_calls"]==0,"单一选择点或来源有误")
        return {"life":"slot-host-life.json","memory":"slot-memory-exam.json","prior_cards":life["preserved_mastery"]}
    test("provenance",sources)
    def legacy():
        s.setup()
        with closing(s.store()) as db,db:bindings=slots.bind(db,language="legacy-cl",cognition="legacy-pcgm")
        # Ordinary entry points, original 2.0 test programs, and all requests in the same frozen timing set.
        timed=out/"slot-benchmark.json"
        need(h(opts.bench)=="824bcea73ea3e143435d3c8c0a34a5d71c3498fab94da7e0280080bdb38534c6"
             and h(out/"baseline3.json")=="36a5263ed245df67e7fec51d3e46403aa4e1bfa3be7a8e04bdec752df84aa5f9",
             "基线工作量或基准回执已变化")
        run(py,opts.bench,root,timed)
        with closing(s.store()) as db:
            frames=db.execute("""SELECT h.frame_kind FROM requests r JOIN host31_commits h ON r.id=h.request_id
              WHERE r.session='frozen_bench' ORDER BY r.seq DESC LIMIT 32""").fetchall()
            need(len(frames)==32 and all(r[0]=="reply" for r in frames),"时延样本包含槽不可用状态帧")
        subset=out/"slot-legacy-gate.json"
        run(py,root/"tools/gate_local3.py","--root",root,"--baseline",out/"baseline3.json","--benchmark",timed,
            "--baseline-source",opts.v2_archive,"--out",subset)
        old=read(subset)
        need(old["passed"],"旧件冻结回归未通过")
        # Exercise the original proof-integrity statuses and the existing real advisor through the compatibility paths.
        run(py,root/"tools/check_proof.py");run(py,root/"tools/check_learning.py",timeout=125)
        proof=read(out/"proof-integrity.json");learn=read(out/"learning.json")
        need(set(proof)=={"both","alternate","withdraw_con","restore_con"} and len(learn["cycles"])==2,"W09/W12 原始回执不足")
        # Independently bind an L2 conflict proof and reproduce it via L5 at the same input pin.
        with closing(s.store()) as db,db:
            expr=": fact(sym).\n& pro fact(x).\n& con !fact(x).\n? fact(x).\n"
            v=hashlib.sha256(expr.encode()).hexdigest();obs=slots.dispatch(db,"L2",{"source":expr},input_version=v)
            need(obs["output"]["results"][0]["status"]==bindings["L"]["value_domain"]["conflict"],"L2 冲突混淆")
            repeat=slots.dispatch(db,"L5",{"source":expr,"receipt":obs},input_version=v)
            need(repeat["output"]["matches"],"L5 旧证明无法复验")
        report.update(cases=old["cases"],latency_ok=old["latency_ok"],errors_ok=old["errors_ok"],benchmark=old["benchmark"])
        return {"cases":dict(old["cases"],W09=True,W12=True),"active":[bindings[k]["id"] for k in ("L","C")],
                "receipt":"slot-legacy-gate.json","proof_pin":obs["output"]["proof_ref"]}
    test("legacy_dependent",legacy)
    report["prefix_after"]=prefix(root/"state/dashboard-split.sqlite",opts.archive)
    need(base==evolution3.protected_hashes(),"回归期间构建发生改变")
    report["passed"]=len(all_groups)==6 and all(all_groups.values()) and report["latency_ok"] and report["errors_ok"]
    dump(out/"slot-release-gate.json",report)
    print("PASS" if report["passed"] else "FAIL",out/"slot-release-gate.json");return int(not report["passed"])
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("root","empty-root","archive","v2-archive","bench"):p.add_argument("--"+k,type=Path,required=True)
    raise SystemExit(main(p.parse_args()))

