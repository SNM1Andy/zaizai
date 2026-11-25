"""Revert the November 2026 geometry host increment; retain the actual native field and subsequent memories."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

OLD_PINS={"INSTALL.json":"2be210a32d61b0095fd732f9140694f19291acffc3135e36072f6655cfda5c91",
          "manifest-sha256.json":"7e94e648718864589174845461034abae88006838517126efc0e1b94f990d399",
          "v3-gate.json":"be8b3ae1abefabbe352d28489e62694e2252cdfb6fd064b5edacdf567b768690"}
MOD="b0f9ee140a90501461003427250c6723544fb7c2503e98234c871c8fb84c818a"
INCREMENT="3.1 几何接入与逐轮读回"
CHANGED=("host/life3.py","host/life3_worker.py","host/service.py","host/evolution3.py")
ADDED=("host/round31.py","host/field31_status.py")
MARKERS=("evidence/v3-gate.json","INSTALL.json","evidence/manifest-sha256.json")
TRIGGERS=("round31_legacy_dialogue","round31_request_receipt")
JOURNAL="rollback/geometry31-host-rollback-journal.json"

def need(ok,message):
    if not ok:raise ValueError(message)

def hashed(file):
    with file.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()

def load(file):return json.loads(file.read_bytes())
def encoded(data):return (json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+"\n").encode()

def local(root,rel):
    path=root/rel
    need(root==root.resolve() and path==path.resolve() and path.is_relative_to(root) and path!=root,
         "不允许在登记位置以外切换："+str(path))
    return path

def bundle_view(root,backup):
    need(backup.parent==root/"rollback" and backup.name=="geometry31-20261123-193556","本工具仅接受此次已封存的 3.0 几何增量前备份")
    for name,pin in OLD_PINS.items():need(hashed(local(backup,name))==pin,"旧版本凭据不符："+name)
    manifest=load(backup/"manifest-sha256.json")["files"]
    gate=load(backup/"v3-gate.json")
    old=load(backup/"INSTALL.json")
    need(old["release"]=="3.0" and gate["passed"] and old["frozen_dialogue_gate_sha256"]==OLD_PINS["v3-gate.json"] and manifest["INSTALL.json"]==OLD_PINS["INSTALL.json"],"旧发布描述不符")
    for rel in CHANGED:need(hashed(local(backup,rel))==manifest[rel]==gate["protected_sha256"][rel],"封存的宿主字节不符："+rel)
    for rel,pin in gate["protected_sha256"].items():
        if rel not in CHANGED:need(hashed(local(root,rel))==pin,"固定引擎或 3.0 公共功能已变化："+rel)
    # The existing release utility holds all four Win32 instance mutexes and writer.guard.
    file=local(root,"tools/rollback_local3.py")
    need(hashed(file)==manifest["tools/rollback_local3.py"],"宿主停机锁工具已变化")
    spec=importlib.util.spec_from_file_location("_zaizai_geom31_rollback_os",file)
    ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)
    return old,gate,ops

def old_file(backup,rel):return local(backup,Path(rel).name if rel in MARKERS else rel)

def check_anchors(root,backup,old,gate):
    meta=load(local(root,"INSTALL.json"))
    g=load(local(root,MARKERS[0]));m=load(local(root,MARKERS[2]))["files"]
    if all(hashed(local(root,rel))==OLD_PINS[Path(rel).name] for rel in MARKERS) and not any(local(root,k).exists() for k in ADDED):
        need(all(hashed(local(root,k))==gate["protected_sha256"][k] for k in CHANGED),"原发布标记与宿主矛盾")
        return "already_3.0"
    inc=meta.get("local_increment") or {}
    need(meta.get("release") in ("3.0","3.1") and meta.get("identity")==old["identity"] and inc.get("name")==INCREMENT
         and inc.get("module_sha256")==MOD and Path(inc.get("host_rollback_dir","")).resolve()==backup,
         "未知宿主版本或回退绑定不匹配")
    need(g["passed"] and all(g["cases"].values()) and g["protected_sha256"].get("tools/geometry.cl")==MOD,
         "3.1 对话门或几何模块来源不匹配")
    for rel,pin in g["protected_sha256"].items():
        need(hashed(local(root,rel))==pin,"实际在位宿主已变化："+rel)
    for rel in CHANGED+ADDED:need(hashed(local(root,rel))==m[rel]==g["protected_sha256"][rel],"静态清单与在位版本不符："+rel)
    need(hashed(local(root,"INSTALL.json"))==m["INSTALL.json"],"当前发布描述摘要不符")
    return "eligible"

def tracks(root,db):
    identity=load(local(root,"state/native/joint-reopen.json"))["identity"]
    need(not db.execute("SELECT 1 FROM turns WHERE identity IS NOT ? LIMIT 1",(identity,)).fetchone(),"会话身份不符")
    result={}
    names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for name in names:
        q='"'+name.replace('"','""')+'"'
        # No user content is written to disk or returned by this check.
        result[name]=db.execute("SELECT count(*) FROM "+q).fetchone()[0]
    sql={r[0]:r[1] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'round31_%'")}
    need(set(sql)<=set(TRIGGERS),"发现其他版本的轮次触发器，不能盲目停用")
    return {"identity":identity,"counts":result,"native_sha256":hashed(local(root,"state/individual.pcgm"))},sql

def current_journal(root):
    p=local(root,JOURNAL)
    if not p.exists():return None
    data=load(p);need(data.get("schema")=="geometry31-host-rollback/1","未知回退日志")
    return data if data["phase"]!="complete" else None

def verify_old(root,old_gate):
    for rel,pin in old_gate["protected_sha256"].items():need(hashed(local(root,rel))==pin,"原 3.0 门未复位："+rel)
    need(not any(local(root,r).exists() for r in ADDED),"额外受保护源码仍在宿主内")
    evo=local(root,"host/evolution3.py")
    spec=importlib.util.spec_from_file_location("_geom31_restored_immutable_gate",evo)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    need(mod.gate_status()[0],"原 3.0 冻结回归门未打开")

def check(root,backup):
    old,gate,ops=bundle_view(root,backup)
    state=current_journal(root)
    version="resume_pending" if state else check_anchors(root,backup,old,gate)
    busy=ops.holders(root);procs=ops.host_processes(root)
    with closing(sqlite3.connect(local(root,"state/dashboard-split.sqlite").as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN");data,triggers=tracks(root,db)
    need(data["identity"]==old["identity"],"存档与封存原身份不同")
    return {"version":version,"ready_to_apply":not busy and not procs,"occupied_mutexes":busy,"occupied_processes":procs,
        "turns":data["counts"]["turns"],"table_count":len(data["counts"]),"native_sha256":data["native_sha256"],
        "installed_compatibility_triggers":sorted(triggers),"previous_gate":OLD_PINS["v3-gate.json"],"read_only":True}

def apply_locked(root,backup,old,gate,ops,checkpoint=None):
    state=current_journal(root)
    dbfile=local(root,"state/dashboard-split.sqlite")
    with closing(sqlite3.connect(dbfile.as_uri()+"?mode=rw",uri=True,timeout=8)) as db:
        db.execute("PRAGMA synchronous=FULL");db.execute("BEGIN IMMEDIATE")
        before,trigger_sql=tracks(root,db);need(before["identity"]==old["identity"],"当前个体不匹配")
        if not state:
            v=check_anchors(root,backup,old,gate)
            if v=="already_3.0":
                need(not trigger_sql,"发现 3.1 触发器与 3.0 标记不符")
                verify_old(root,gate);return {"already_restored":True,"identity":old["identity"]}
            folder=local(root,"rollback/geometry31-removed-"+uuid.uuid4().hex);folder.mkdir()
            names=CHANGED+ADDED+MARKERS
            old_files={}
            for rel in names:
                src=local(root,rel);dst=local(folder,rel)
                dst.parent.mkdir(parents=True,exist_ok=True);ops.copy_flushed(src,dst)
                old_files[rel]=hashed(dst)
                need(hashed(src)==old_files[rel],"归档时源码改变")
            state={"schema":"geometry31-host-rollback/1","phase":"prepared","folder":folder.name,"bundle":str(backup),
                   "before_files":old_files,"original_native_sha256":before["native_sha256"],"before_counts":before["counts"],
                   "disabled_triggers":trigger_sql,"began":time.time()}
            ops.publish(local(root,JOURNAL),encoded(state),root)
        need(state["bundle"]==str(backup) and re.fullmatch("geometry31-removed-[0-9a-f]{32}",state["folder"]),"回退日志引用异常")
        folder=local(root,"rollback/"+state["folder"])
        need(set(state["before_files"])==set(CHANGED+ADDED+MARKERS),"回退范围异常")
        for rel,pin in state["before_files"].items():need(hashed(local(folder,rel))==pin,"归档被改写："+rel)
        def mark(phase):
            state["phase"]=phase;ops.publish(local(root,JOURNAL),encoded(state),root)
            if checkpoint:checkpoint(phase)
        for rel in CHANGED+ADDED+MARKERS:
            path=local(root,rel);old_pin=state["before_files"][rel]
            if rel in ADDED:
                retired=local(folder,"retired-"+path.name)
                if path.exists():
                    need(hashed(path)==old_pin and not retired.exists(),"未登记的活跃新增模块："+rel)
                    ops.move_checked(path,retired,root);mark(rel)
                else:need(retired.is_file() and hashed(retired)==old_pin,"不能复核移出的文件："+rel)
            else:
                src=old_file(backup,rel);pin=hashed(src);current=hashed(path)
                need(current in (pin,old_pin),"当前不是本切换登记的版本："+rel)
                if current!=pin:
                    ops.publish(path,src.read_bytes(),root);need(hashed(path)==pin,"回退后文件摘要不同："+rel);mark(rel)
        verify_old(root,gate)
        for name,sql in trigger_sql.items():
            need(sql==state["disabled_triggers"].get(name),"待停用触发器不再是已归档版本："+name)
            db.execute("DROP TRIGGER "+name)
        after,left=tracks(root,db);need(before==after and not left,"当前表记录数、身份或原生存档在回退中变化")
        db.commit()
        mark("triggers_disabled")
        state["finished"]=time.time();state["retained_at_completion"]=after;mark("complete")
        ops.publish(local(folder,"completed.json"),encoded(state),root)
        return {"release":"3.0","restored_frozen_gate":True,"preserved_native_sha256":after["native_sha256"],
                "retained_tables":len(after["counts"]),"retained_turns":after["counts"]["turns"],
                "removed_host_files":list(ADDED),"removed_triggers":list(state["disabled_triggers"]),"archive":str(folder)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,required=True);p.add_argument("--backup",type=Path,required=True)
    opt=p.add_mutually_exclusive_group(required=True);opt.add_argument("--check",action="store_true");opt.add_argument("--apply",action="store_true")
    args=p.parse_args();root=args.root.resolve(strict=True);backup=args.backup.resolve(strict=True)
    if args.check:result=check(root,backup)
    else:
        old,gate,ops=bundle_view(root,backup)
        with ops.closed(root):result=apply_locked(root,backup,old,gate,ops)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
