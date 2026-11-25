"""Coordinated backup and verified restore of the native state and desktop ledger."""
import argparse
from contextlib import closing, contextmanager, ExitStack
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import native as n
import service

TRANSIENT = {"desktop-writer.lock", "individual.pcgm.lock", "gpu-admission.tick",
             "startup.json", "window-check-start.json", "dashboard-split.sqlite-journal",
             "dashboard-split.sqlite-wal", "dashboard-split.sqlite-shm"}

def check(condition, message):
    if not condition:
        raise ValueError(message)

def describe(folder, database_copy=None, *, immutable_snapshot=False):
    save = folder / n.SAVE.name
    # Slot-private files are opaque. A host checkpoint also works with no engines installed.
    anchor = json.loads((folder/"native/joint-reopen.json").read_bytes())
    check(anchor["identity"]==n.IDENTITY,"宿主身份与原存档锚不符")
    dbpath = (database_copy or (folder / n.DB.name)).as_uri() + "?mode=ro"
    if immutable_snapshot and not any((folder/(n.DB.name+suffix)).exists() for suffix in ("-wal","-shm","-journal")):
        # restore() has verified each archive entry in a private freshly created staging folder.
        # A backed-up SQLite database has no uncheckpointed WAL/SHM to consult or create.
        dbpath += "&immutable=1"
    with closing(sqlite3.connect(dbpath, uri=True)) as db:
        db.execute("BEGIN")
        check(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "SQLite 完整性检查失败")
        check(db.execute("SELECT COUNT(*) FROM turns WHERE identity IS NOT ?",(n.IDENTITY,)).fetchone()[0] == 0, "历史存在其他身份")
        turns, seq = db.execute("SELECT COUNT(*),MAX(seq) FROM turns").fetchone()
        phases = dict(db.execute("SELECT phase,COUNT(*) FROM requests GROUP BY phase"))
        check(db.execute("SELECT COUNT(*) FROM requests r LEFT JOIN turns t ON t.seq=r.seq WHERE r.phase='committed' AND (t.seq IS NULL OR r.answer IS NOT t.response OR r.question IS NOT t.request)").fetchone()[0]==0, "对话与提交回执不一致")
        local={}
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='life3_meta'").fetchone():
            check(db.execute("SELECT value FROM life3_meta WHERE key='identity'").fetchone()==(n.IDENTITY,),"生命循环身份不符")
            for table in ("life3_events","inner3_events","study3_card","study3_observation","evo3_events","life3_questions"):
                local[table]=db.execute("SELECT count(*) FROM "+table).fetchone()[0]
            check(not db.execute("""SELECT 1 FROM requests r JOIN turns t ON t.seq=r.seq LEFT JOIN life3_events e ON e.id=r.id
                WHERE t.build LIKE '3.0 /%' AND r.phase='committed' AND e.id IS NULL LIMIT 1""").fetchone(),"3.0 回执缺少内在状态审计")
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        binding={}
        if "slot31_bindings" in names:
            import slots31
            db.row_factory=sqlite3.Row
            binding=slots31.checkpoint(db)
            check(not db.execute("""SELECT 1 FROM host31_commits h JOIN requests r ON r.id=h.request_id
                WHERE r.phase='committed' AND (h.content_sha256!=r.digest OR h.frame_kind NOT IN ('slot_status','host_data','reply')) LIMIT 1""").fetchone(),
                "宿主提交与请求摘要或输出类别不一致")
        for name in sorted(names):
            if name.startswith(("slot31_","host31_","round31_","life31_")):
                local[name]=db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
    fingerprint=n.sha(save.read_bytes()) if save.is_file() else None
    return {"identity":n.IDENTITY, "native_sha256":fingerprint,
            "turns":turns,"last_seq":seq,"phases":phases,"m5":anchor["receipt"],
            **({"local3":local} if local else {}),**({"slot_manifests":binding} if binding else {})}

def backup(archive):
    archive.parent.mkdir(parents=True,exist_ok=True)
    check(not archive.exists() and not archive.is_relative_to(n.STATE), "请指定存档区外的全新备份文件")
    with tempfile.TemporaryDirectory(dir=archive.parent) as tmp, service.writer():
        stage = Path(tmp)
        with closing(service.store()) as source, closing(sqlite3.connect(stage/n.DB.name)) as dest:
            if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='slot31_bindings'").fetchone():
                import slots31
                with source:slots31.capture_private(source)
            source.backup(dest)
        summary = describe(n.STATE,stage/n.DB.name)
        partial = stage/"save.zip"
        hashes = {}
        with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            for p in sorted(n.STATE.rglob("*")):
                rel = p.relative_to(n.STATE).as_posix()
                if not p.is_file() or rel in TRANSIENT or (p.parent==n.STATE and p.suffix==".tmp"):
                    continue
                data = (stage/n.DB.name if p==n.DB else p).read_bytes()
                hashes[rel] = n.sha(data)
                bundle.writestr("state/"+rel, data)
            check(summary["native_sha256"]==(n.sha(n.SAVE.read_bytes()) if n.SAVE.is_file() else None), "备份时原生状态改变，请重试")
            bundle.writestr("manifest.json", n.canonical({"format":2,"state":summary,"files":hashes}))
        os.rename(partial,archive)
    return summary

def publish_restored_directory(stage, dest):
    """Do not overwrite any destination, including one created during a sharing-violation retry."""
    source=stage.resolve(strict=True)
    if source!=stage or source.is_junction() or source.is_symlink():
        raise ValueError("还原暂存目录异常")
    if dest.parent.resolve()!=source.parent.parent or source==dest:
        raise ValueError("还原发布必须在同卷的指定父目录内")
    for attempt in range(8):
        if dest.exists() or dest.is_symlink() or dest.is_junction():
            raise FileExistsError("还原目标已存在："+str(dest))
        try:
            os.rename(source,dest)
            return
        except PermissionError as error:
            if (os.name!="nt" or getattr(error,"winerror",None) not in {5,32,33}
                or attempt==7 or not source.is_dir() or dest.exists()):
                raise
            time.sleep(min(.05*2**attempt,.5))


def restore(archive,dest):
    check(not dest.exists() and dest.parent.is_dir() and not dest.is_relative_to(n.STATE), "还原目标须为存档区外、尚不存在的目录")
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp, zipfile.ZipFile(archive) as bundle:
        stage = Path(tmp)/"restored"
        stage.mkdir()
        manifest = json.loads(bundle.read("manifest.json"))
        check(manifest["format"] in (1,2) and manifest["state"]["identity"]==n.IDENTITY, "备份格式或身份不符")
        hashes = manifest["files"]
        expected = {"state/"+key for key in hashes} | {"manifest.json"}
        check(set(bundle.namelist())==expected and len(bundle.namelist())==len(expected), "封装清单不符")
        for rel, expected_hash in hashes.items():
            path = PurePosixPath(rel)
            check(not path.is_absolute() and str(path)==rel and ".." not in path.parts and "\\" not in rel and ":" not in rel, "路径格式无效")
            target = (stage / path).resolve()
            check(target.is_relative_to(stage) and not target.exists(), "还原路径冲突")
            data = bundle.read("state/"+rel)
            check(n.sha(data)==expected_hash, "摘要不符："+rel)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        (stage/"incoming").mkdir(exist_ok=True)
        result = describe(stage, immutable_snapshot=True)
        # Version-1 archives include a legacy tool's event and owner readback.
        # The verified archive's file hash locks those opaque bytes; an empty host never runs that adapter.
        archived=manifest["state"]
        if manifest["format"]==1:
            check(all(result.get("local3",{}).get(k)==v for k,v in archived.get("local3",{}).items()),"旧宿主表快照不符")
            archived={k:v for k,v in archived.items() if k not in ("owner","event","local3")}
        check(all(result.get(k)==v for k,v in archived.items()), "还原后的身份、历史或回执不符")
        publish_restored_directory(stage,dest)
    return result

@contextmanager
def desktop_closed():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None,False,"Local\\ZaizaiDesktop20")
    existed = ctypes.get_last_error()==183
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        check(not existed, "请先正常关闭再再两窗后再切换存档")
        yield
    finally:
        kernel.CloseHandle(handle)

def restore_live(archive):
    from life3_worker import latch
    fixed = ROOT.resolve()/"state"
    check(fixed==n.STATE.resolve() and fixed.parent==ROOT and not fixed.is_junction(), "正式存档目录异常")
    with desktop_closed(), ExitStack() as locks, service.maintenance_lock():
        for label in ("supervisor","worker"):
            if not locks.enter_context(latch(label,True)):
                raise RuntimeError("请先在对话中输入「关闭后台」，等生命循环退出并关闭窗口后再恢复正式存档")
        tag = str(time.time_ns())
        staged = ROOT/("verified-state-"+tag)
        previous = (ROOT/"rollback"/("state-"+tag)).resolve()
        check(previous.parent==(ROOT/"rollback").resolve() and previous.parent.parent==ROOT and not previous.exists(), "回退目录异常")
        summary = restore(archive,staged)
        c=summary.get("slot_manifests",{}).get("C",{})
        if c.get("provider_type")=="external":
            with closing(sqlite3.connect(staged/n.DB.name)) as db,db:
                row=db.execute("SELECT state_sha256 FROM slot31_private_state WHERE adapter_id=? AND manifest_sha256=?",(c["id"],c["manifest_sha256"])).fetchone()
                check(row,"还原材料缺少该认知槽的可复验序列化状态")
                db.execute("CREATE TABLE IF NOT EXISTS slot31_private_restore_due(adapter_id TEXT PRIMARY KEY,manifest_pin TEXT NOT NULL,state_sha256 TEXT NOT NULL)")
                db.execute("INSERT OR REPLACE INTO slot31_private_restore_due VALUES(?,?,?)",(c["id"],c["manifest_sha256"],row[0]))
        os.rename(fixed,previous)
        try:
            os.rename(staged,fixed)
        except BaseException:
            os.rename(previous,fixed)
            raise
        return {"restored":summary,"previous":str(previous)}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="再再完整存档备份与校验还原")
    subs=parser.add_subparsers(dest="op",required=True)
    for name in ("backup","restore-to","restore-live"):
        sub=subs.add_parser(name)
        sub.add_argument("archive",type=Path)
        if name=="restore-to":
            sub.add_argument("destination",type=Path)
    args=parser.parse_args()
    path=args.archive.resolve()
    if args.op=="backup":
        result=backup(path)
    elif args.op=="restore-to":
        result=restore(path,args.destination.resolve())
    else:
        result=restore_live(path)
    print(json.dumps(result,ensure_ascii=False,indent=2))
