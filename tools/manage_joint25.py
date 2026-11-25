"""Switch the host slot pair and transfer its single native writer without replacing its checkpoint.

Applications hold exactly the same file locks as service.writer. An interrupted switch is
resumed against the saved operation and the native prepare / handoff / claim receipts.
"""
from pathlib import Path
from contextlib import closing,contextmanager
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from uuid import uuid4

JOINT={"L":"joint25-cl","C":"joint25-pcgm"}
OLD={"L":"legacy-cl","C":"legacy-pcgm"}
EMPTY={"L":"empty","C":"empty"}
MOD="# module dialogue25\n"

def need(ok,why):
    if not ok:raise ValueError(why)
def digest_bytes(v):return hashlib.sha256(v).hexdigest()
def read(path):return json.loads(path.read_text(encoding="utf-8-sig"))
def atomic_bytes(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".partial-"+uuid4().hex)
    try:
        with tmp.open("xb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
def store_journal(path,data):atomic_bytes(path,(json.dumps(data,indent=2,ensure_ascii=False)+"\n").encode())
def has(db,name):return db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(name,)).fetchone() is not None
def pending(db):
    result={}
    if has(db,"requests"):
        normal=db.execute("SELECT id,phase FROM requests WHERE phase IN ('running','prepared') ORDER BY started").fetchall()
        result["inflight_requests"]=[list(v) for v in normal]
        result["unknown_with_pinned_route"]=[r[0] for r in db.execute("""SELECT r.id FROM requests r JOIN host31_request_routes x ON r.id=x.id
            WHERE r.phase='unknown' AND NOT EXISTS(SELECT 1 FROM host31_commits h WHERE h.request_id=r.id)""")]
        result["historical_unknown_count"]=db.execute("SELECT count(*) FROM requests WHERE phase='unknown'").fetchone()[0]
    for table,phase in (("joint25_source_requests","prepared"),("joint25_reviews","issued"),("geo31_steps","prepared")):
        if has(db,table):
            result[table]=db.execute("SELECT count(*) FROM "+table+" WHERE phase=?",(phase,)).fetchone()[0]
    return result
def files(root,path):
    need(path.resolve()==path and path.is_relative_to(root),"控制文件须位于本安装区且不可重定向")
def examine(n,root,state):
    groups={"joint":root/"releases/joint25/bin","legacy":root/"bin"}
    usable={};failed={}
    for name,folder in groups.items():
        try:
            snap=n.snapshot(n.exe(folder,"alpha"),state)
            status=n.read(n.exe(folder,"alpha"),state,"status")
            current=snap["owner"];history=n.history(n.exe(folder,current),state)
            usable[name]={"actor":snap["individual"],"owner":current,"head":snap["head"],
                          "event_count":len(history),"event_prefix":n.pin(history),
                          "pending":bool(status.get("handoff_pending")),"source_sha256":n.digest(snap["source"].encode())}
        except (RuntimeError,ValueError,OSError) as ex:
            failed[name]=str(ex)[:230]
    return usable,failed
def verify_assets(api,root,db,targets):
    for role,aid in targets.items():
        if aid=="empty":continue
        row=db.execute("SELECT manifest,pin FROM slot31_registry WHERE slot=? AND adapter_id=?",(role,aid)).fetchone()
        if row:manifest=json.loads(row["manifest"]);need(api.hash_json(manifest)==row["pin"],"槽件登记摘要不符")
        else:manifest=api.BUILTIN.get(aid)
        need(manifest and manifest["slot"]==role,"本安装缺少槽件 "+aid)
        why=api._checkfiles(manifest)
        need(not why,why or "槽件文件无法核对")
def after_native_module(n,root,state,j,mark):
    folder=root/"releases/joint25/bin";snap=n.snapshot(n.exe(folder,"alpha"),state)
    active=n.exe(folder,snap["owner"])
    template=(root/"releases/joint25/assets/dialogue25.cl").read_bytes()
    needle=MOD+template.decode().strip()
    dest=state.parent/"modules/dialogue25.cl"
    files(root,dest)
    if MOD.strip() in snap["source"].splitlines():
        section=snap["source"].split(MOD,1)[1].split("\n# module ",1)[0]
        need(section.lstrip().startswith(template.decode().strip()) and dest.is_file() and dest.read_bytes()==template,
             "已安装的 dialogue25 模块内容或磁盘文件不一致，不能重复安装")
        return {"stored":True,"added_in_this_call":False,"module_sha256":digest_bytes(template)}
    need(not dest.exists() or dest.is_file() and dest.read_bytes()==template,"已存在不同的 dialogue25 模块")
    # Predict its exact post-state first; it consists solely of new signatures and the pinned rules.
    with tempfile.TemporaryDirectory(prefix="joint25-module-probe-") as td:
        stage=Path(td)/"state";stage.mkdir();sample=stage/state.name;shutil.copy2(state,sample)
        for suffix in (".history",".episodes"):
            part=state.with_name(state.name+suffix)
            if part.exists():shutil.copytree(part,stage/part.name)
        m=stage/"modules";m.mkdir();(m/dest.name).write_bytes(template)
        log=n.invoke(active,["--resume",sample],b":install dialogue25\n")
        expected=n.snapshot(active,sample)
        need(log.strip().endswith("module_installed dialogue25") and expected["source"].startswith(snap["source"])
             and expected["source"][len(snap["source"]):].strip()==needle and expected["inactive"]==snap["inactive"],"模块预演未通过")
    if j.get("module_before"):need(j["module_before"]==snap["head"] and j["module_after"]==expected["head"],"范围安装曾开始，当前头不明")
    mark("module_prepared",module_before=snap["head"],module_after=expected["head"])
    if not dest.exists():atomic_bytes(dest,template)
    raw=n.invoke(active,["--resume",state],b":install dialogue25\n")
    final=n.snapshot(active,state)
    need(raw.strip().endswith("module_installed dialogue25") and final["head"]==expected["head"],"实际模块提交与预演不符，请按日志核对")
    return {"stored":True,"added_in_this_call":True,"module_sha256":digest_bytes(template),"native_result":raw.splitlines()[-1]}
def operate(root,op,gate_file=None,checkpoint=None):
    root=root.resolve(strict=True)
    sys.path.insert(0,str(root/"host"));import service,slots31 as api
    helpers=root/"releases/joint25/tools";sys.path.insert(0,str(helpers))
    import joint25_handoff as n
    need(service.n.ROOT==root and api.ROOT==root and Path(n.__file__).resolve().parent==helpers.resolve(),"错误的宿主或所有权模块根路径")
    state=root/"state/individual.pcgm";dbfile=root/"state/dashboard-split.sqlite"
    identity=json.loads((root/"state/native/joint-reopen.json").read_bytes())["identity"]
    management=state.parent/"joint25-management";active=management/"active.json";files(root,active)
    oldbin=root/"bin";newbin=root/"releases/joint25/bin"
    target={"activate":JOINT,"detach":EMPTY,"restore-legacy":OLD}.get(op)
    if gate_file:
        gate=read(gate_file)
        need(gate.get("passed") is True,"发布验收未通过")
        pins=gate.get("protected_sha256")
        need(isinstance(pins,dict) and pins,"发布验收缺少受保护文件摘要")
        for rel,pin in pins.items():
            path=root/rel
            need(path.resolve().is_relative_to(root.resolve()) or path.parent in (oldbin,),"不受支持的发布清单路径")
            need(digest_bytes(path.read_bytes())==pin,"发布后文件改变："+rel)
    with n.guard(state),closing(sqlite3.connect(dbfile.as_uri()+("?mode=ro" if op=="check" else "?mode=rw"),uri=True,timeout=15)) as db:
        db.row_factory=sqlite3.Row
        if op!="check":
            db.execute("PRAGMA synchronous=FULL")
            with db:api.setup(db)
        before={k:v["id"] for k,v in api.checkpoint(db).items()}
        snapshot_pin=n.filehash(state)
        alive,why=examine(n,root,state)
        need(n.filehash(state)==snapshot_pin,"只读检查期间原生文件变化，请核对在途动作")
        need(all(v["actor"]==identity for v in alive.values()),"原生所有者与原身份不符")
        j=read(active) if active.is_file() else None
        need(not j or j["identity"]==identity,"上次操作属于其他个体")
        awaiting=pending(db)
        held=any(v for k,v in awaiting.items() if k!="historical_unknown_count")
        if op=="check":
            return {"identity":identity,"bindings":before,"matching_native_writers":alive,"unavailable_builds":why,
                    "inflight":awaiting,"management_phase":j["phase"] if j else None,"read_only":True}
        need(not held,"存在待核对的进行中请求："+json.dumps(awaiting,ensure_ascii=False))
        unfinished=j and j["phase"]!="complete"
        if unfinished:need(j["operation"]==op,"存在另一项未完成的切换，请先继续原操作")
        verify_assets(api,root,db,target)
        names={"activate":"joint","restore-legacy":"legacy"};want=names.get(op)
        native_ok=op=="detach" or want in alive and not alive[want]["pending"]
        if before==JOINT and op=="activate" and native_ok:
            actual_module=state.parent/"modules/dialogue25.cl";expected=root/"releases/joint25/assets/dialogue25.cl"
            snap=n.snapshot(n.exe(newbin,"alpha"),state)
            native_ok=(actual_module.is_file() and digest_bytes(actual_module.read_bytes())==digest_bytes(expected.read_bytes())
                       and MOD.strip() in snap["source"].splitlines() and MOD+expected.read_text(encoding="utf8").strip() in snap["source"])
        if before==target and native_ok and not unfinished:
            ok=api.snapshot(db)
            if all(v["state"] in ("ready","empty") for v in ok.values()):
                return {"outcome":"already_bound","identity":identity,"bindings":before,"native":alive.get(want),"writes_state":False}
        src_name="legacy" if want=="joint" else "joint"
        if want and not unfinished and want not in alive:
            need(src_name in alive and not alive[src_name]["pending"],"没有可安全移交的已知原生写者；保持现有存档")
            destination=newbin if want=="joint" else oldbin
            # Old readers can reject a newer format or larger dialogue table before we disconnect anything.
            check=n.transfer(state,oldbin if want=="joint" else newbin,destination,identity,management/"unused-check.json",False,host_locked=True)
            need(check["outcome"]=="eligible","原生目标不能核对当前存档")
        if not unfinished:
            management.mkdir(exist_ok=True)
            j={"protocol":"zaizai-joint-manager/1","id":uuid4().hex,"identity":identity,"operation":op,
               "phase":"intent","before_bindings":before,"target_bindings":target,"original_writer":next(iter(alive),None),
               "initial_native":alive,"initial_state_file_sha256":n.filehash(state),"created":time.time()}
            store_journal(active,j)
        def mark(phase,**extra):
            j.update(phase=phase,**extra);store_journal(active,j)
            if checkpoint:checkpoint(phase)
        if j["phase"]=="intent":
            if before!=EMPTY:
                with db:api.bind(db,language="empty",cognition="empty")
            mark("detached")
        if j["phase"] in ("detached","moving") and want:
            frombin=oldbin if want=="joint" else newbin;tobin=newbin if want=="joint" else oldbin
            handoff=management/(j["id"]+"-native.json")
            # If a previous caller died during native ownership transfer, continue the same native journal.
            if handoff.exists() or want not in alive:
                if not handoff.exists():
                    prereq=j["initial_native"].get(src_name)
                    need(prereq and src_name in alive and prereq["head"]==alive[src_name]["head"],
                         "切换前所封存的起始状态已经改变，不能重发旧交接")
                mark("moving");move=n.transfer(state,frombin,tobin,identity,handoff,True,host_locked=True)
            else:move={"outcome":"already_owned","owner":alive[want]["owner"],"head":alive[want]["head"]}
            mark("native_ready",handoff=move)
        elif j["phase"]=="detached" and not want:
            mark("native_ready",handoff={"outcome":"writer_preserved","native_sha256":n.filehash(state)})
        if j["phase"] in ("native_ready","module_prepared") and op=="activate":
            module=after_native_module(n,root,state,j,mark);mark("module_ready",module=module)
        if j["phase"] in ("native_ready","module_ready"):
            if want:
                active_bin=newbin if want=="joint" else oldbin
                snap=n.snapshot(n.exe(active_bin,"alpha"),state)
                hist=n.history(n.exe(active_bin,snap["owner"]),state)
                prior=next(iter(j["initial_native"].values()),None)
                if prior:need(n.pin(hist[:prior["event_count"]])==prior["event_prefix"],"状态变更破坏了先前历史前缀")
            with db:api.bind(db,language=target["L"],cognition=target["C"])
            mark("bound")
        need(j["phase"]=="bound","无法确认切换阶段；保持存档与日志")
        actual=api.snapshot(db)
        need(all(actual[k]["id"]==target[k] and actual[k]["state"] in ("ready","empty") for k in ("L","C")),"切换后槽状态核对失败")
        final,errors=examine(n,root,state)
        need(not want or want in final and final[want]["actor"]==identity,"切换后没有相匹配的单个写入者")
        if op=="detach":need(n.filehash(state)==j["initial_state_file_sha256"],"拔空期间原生文件发生变动，保留日志待核对")
        j.update(phase="complete",finished=time.time(),final_bindings=target,final_native=final,final_state_file_sha256=n.filehash(state))
        store_journal(management/(j["id"]+"-complete.json"),j);store_journal(active,j)
        return {"outcome":"complete","identity":identity,"bindings":target,"operation":op,"journal":str(active),
                "native":final.get(want,final),"module":j.get("module"),"handoff":j.get("handoff")}

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument("--root",type=Path,required=True);cli.add_argument("--gate",type=Path)
    group=cli.add_mutually_exclusive_group(required=True)
    for command in ("activate","detach","restore-legacy","check"):group.add_argument("--"+command,action="store_const",dest="operation",const=command)
    args=cli.parse_args()
    print(json.dumps(operate(args.root,args.operation,args.gate),ensure_ascii=False,indent=2))

