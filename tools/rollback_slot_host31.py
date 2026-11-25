"""Restore the frozen Windows host without rolling its life database or slot-private state back."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

PINS={"INSTALL.json":"0782a036cfae4396d9af0d4a10c18d0e6282c430121dac4ce06ce13880b92009",
      "manifest-sha256.json":"9b330ed5cbd68c2d2ea65d90df195d5fdd9a52f9206a5e8087d106d5e477cc35",
      "v3-gate.json":"85af6d4dad0a7fbb3b1869a6405feb9da3eb339dd292341a048add8ef2d0d099"}
MARKERS=("evidence/v3-gate.json","INSTALL.json","evidence/manifest-sha256.json")
JOURNAL="rollback/slot-host-selection.json"
SELF="tools/rollback_slot_host31.py"

def need(value,detail):
    if not value:raise ValueError(detail)

def hashed(file):
    with file.open("rb") as fp:return hashlib.file_digest(fp,"sha256").hexdigest()

def local(root,rel):
    p=root/rel
    need(p!=root and p==p.resolve() and p.is_relative_to(root),"路径不是指定安装目录下的独立项目："+str(rel))
    return p

def load(p):return json.loads(p.read_bytes())

def view(root,bundle):
    need(root.is_absolute() and bundle.parent==root/"rollback" and bundle.name=="hostslots-20261124-093053","需使用该安装的宿主留空改造前封存目录")
    for name,pin in PINS.items():need(hashed(local(bundle,name))==pin,"封存标记被修改："+name)
    meta=load(bundle/"INSTALL.json");gate=load(bundle/"v3-gate.json");pins=load(bundle/"manifest-sha256.json")["files"]
    need(meta["frozen_dialogue_gate_sha256"]==PINS["v3-gate.json"] and gate["passed"] and meta["release"]=="3.0",
         "宿主对应的原3.0几何增量门不符")
    for rel,pin in pins.items():
        if rel.startswith(("host/","tools/")):
            need(hashed(local(bundle,rel))==pin,"封存宿主/工具摘要不符："+rel)
    # The stop-and-lock facility itself must match this separately frozen source.
    helper=local(bundle,"tools/rollback_local3.py")
    sp=importlib.util.spec_from_file_location("_slot_rollback_os",helper)
    ops=importlib.util.module_from_spec(sp);sp.loader.exec_module(ops)
    return meta,pins,gate,ops

def state_info(root):
    dbfile=local(root,"state/dashboard-split.sqlite")
    with closing(sqlite3.connect(dbfile.as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        identity=load(local(root,"state/native/joint-reopen.json"))["identity"]
        need(db.execute("SELECT 1 FROM turns WHERE identity IS NOT ? LIMIT 1",(identity,)).fetchone() is None,
             "存档含不同身份")
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts={name:db.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
        stamps=db.execute("SELECT count(*),coalesce(max(seq),0) FROM turns").fetchone()
        frames=(dict(db.execute("SELECT frame_kind,COUNT(*) FROM host31_commits GROUP BY frame_kind")) if "host31_commits" in tables else {})
    native=local(root,"state/individual.pcgm")
    return {"identity":identity,"turns":stamps[0],"latest_seq":stamps[1],"table_counts":counts,"stored_frame_types":frames,
            "legacy_native_sha256":hashed(native) if native.is_file() else None}

def old_ready(root,gate):
    return (all((root/rel).is_file() and hashed(local(root,rel))==PINS[Path(rel).name] for rel in MARKERS)
            and all((root/rel).is_file() and hashed(local(root,rel))==pin for rel,pin in gate["protected_sha256"].items())
            and not (root/"host/slots31.py").exists())

def active_journal(root):
    p=local(root,JOURNAL)
    if not p.exists():return None
    j=load(p);need(j["schema"]=="slot-host-rollback/1" and re.fullmatch(r"slot-host-former-[a-f0-9]{32}",j["folder"]),"回退日志不符合格式")
    return j if j["phase"]!="complete" else None

def incoming(root,bundle,meta,pins):
    installed=load(local(root,"INSTALL.json"))
    need(installed["identity"]==meta["identity"] and Path(installed.get("host_slots",{}).get("rollback_dir","")).resolve()==bundle,
         "当前宿主没有登记指定的槽留空改造前封存")
    now=load(local(root,MARKERS[2]))["files"];candidate_gate=load(local(root,MARKERS[0]))
    need(now.get("INSTALL.json")==hashed(local(root,"INSTALL.json")) and candidate_gate["passed"],"本次宿主标记或验收门异常")
    need(installed.get("frozen_dialogue_gate_sha256")==hashed(local(root,MARKERS[0])),"当前验收门摘要与发布信息不同")
    for rel,pin in candidate_gate.get("protected_sha256",{}).items():
        need(hashed(local(root,rel))==pin,"在位受保护文件已被其他更新替换："+rel)
    changes={}
    # Restore every previously tracked tool which changed. Archive new host modules/tooling with the outgoing release.
    for rel in sorted(set(now)|set(pins)):
        if not rel.startswith(("host/","tools/")) or rel==SELF:continue
        previous=pins.get(rel);latest=now.get(rel)
        if latest:need(hashed(local(root,rel))==latest,"在位程序摘要不符："+rel)
        if previous!=latest:changes[rel]=[latest,previous]
    for rel in MARKERS:changes[rel]=[hashed(local(root,rel)),PINS[Path(rel).name]]
    return changes

def check(root,bundle):
    meta,pins,gate,ops=view(root,bundle)
    pending=active_journal(root)
    state="resume_pending" if pending else ("already_restored" if old_ready(root,gate) else "eligible")
    if state=="eligible":incoming(root,bundle,meta,pins)
    used=ops.holders(root);processes=ops.host_processes(root);current=state_info(root)
    need(current["identity"]==meta["identity"],"身份不一致")
    return dict(version=state,read_only=True,ready_to_apply=not used and not processes,
        occupied_mutexes=used,occupied_processes=processes,**current,
        old_window_behavior="旧窗口统一使用旧对话标签；槽状态仍以原文字保留，精确帧类型和宿主回执留在 host31_commits。")

def apply_locked(root,bundle,checkpoint=None):
    meta,pins,gate,ops=view(root,bundle)
    j=active_journal(root)
    if not j and old_ready(root,gate):return {"already_restored":True,"identity":meta["identity"]}
    before=state_info(root);need(before["identity"]==meta["identity"],"恢复目标身份不符")
    if not j:
        changes=incoming(root,bundle,meta,pins);folder=local(root,"rollback/slot-host-former-"+uuid4().hex);folder.mkdir()
        for rel,(latest,previous) in changes.items():
            if latest:
                dst=local(folder,"former/"+rel);dst.parent.mkdir(parents=True,exist_ok=True)
                ops.copy_flushed(local(root,rel),dst);need(hashed(dst)==latest,"当前文件归档校验失败："+rel)
            if previous:
                expected=local(bundle,Path(rel).name if rel in MARKERS else rel)
                dst=local(folder,"restore/"+rel);dst.parent.mkdir(parents=True,exist_ok=True)
                ops.copy_flushed(expected,dst);need(hashed(dst)==previous,"原文件暂存校验失败："+rel)
        j={"schema":"slot-host-rollback/1","folder":folder.name,"bundle":str(bundle),"changes":changes,
           "started":time.time(),"phase":"prepared","before":before}
        ops.publish(local(root,JOURNAL),ops.canonical(j),root)
    need(j["bundle"]==str(bundle),"有另一项未结束的回退")
    folder=local(root,"rollback/"+j["folder"])
    def mark(phase):
        j["phase"]=phase;ops.publish(local(root,JOURNAL),ops.canonical(j),root)
        if checkpoint:checkpoint(phase)
    changes=j["changes"]
    for rel in [k for k in changes if k not in MARKERS]+list(MARKERS):
        recent,previous=changes[rel];dest=local(root,rel)
        if recent:need(hashed(local(folder,"former/"+rel))==recent,"留档版本被更改")
        if previous:
            target=local(folder,"restore/"+rel)
            need(hashed(target)==previous and (previous==pins.get(rel) or (rel in MARKERS and previous==PINS[Path(rel).name])),
                 "旧文件摘要不符："+rel)
        current=hashed(dest) if dest.is_file() else None
        need(current in {recent,previous},"切换期间出现新内容："+rel)
        if current!=previous:
            if previous:
                dest.parent.mkdir(parents=True,exist_ok=True);ops.publish(dest,target.read_bytes(),root)
            else:
                archived=local(folder,"removed/"+rel);archived.parent.mkdir(parents=True,exist_ok=True)
                need(not archived.exists(),"准备移动的文件留档位置冲突")
                ops.move_checked(dest,archived,root)
        mark(rel)
    need(old_ready(root,gate),"3.0 几何增量宿主或冻结门未还原")
    evo=local(root,"host/evolution3.py")
    spec=importlib.util.spec_from_file_location("_old_slot_host_gate",evo);restored=importlib.util.module_from_spec(spec);spec.loader.exec_module(restored)
    need(restored.gate_status()[0],"恢复后的原版宿主实际无法通过冻结门")
    after=state_info(root);need(after==before,"宿主切换期间数据状态有变化")
    mark("complete")
    return {"installed":meta["release"],"increment":meta["local_increment"]["name"],"former_host":str(folder),
            "original_gate":True,"all_table_counts_kept":True,"legacy_native_sha256":after["legacy_native_sha256"],
            "retained_host_receipts":after["stored_frame_types"],"identity":meta["identity"]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup",type=Path,required=True)
    modes=parser.add_mutually_exclusive_group(required=True);modes.add_argument("--check",action="store_true");modes.add_argument("--apply",action="store_true")
    args=parser.parse_args();root=args.root.resolve(strict=True);backup=args.backup.resolve(strict=True)
    if args.check:result=check(root,backup)
    else:
        meta,pins,gate,ops=view(root,backup)
        with ops.closed(root):result=apply_locked(root,backup)
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=="__main__":main()
