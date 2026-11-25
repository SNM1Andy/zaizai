"""Reinstall the sealed 2.0 desktop host over the same current state. No state restore."""
import argparse
from contextlib import ExitStack, closing, contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from uuid import uuid4
import zipfile

ROOT=Path(__file__).resolve().parents[1]
KNOWN_MANIFEST="e36b9ac807c98ab9b2fc52f2c03392c77280f0ae490a39fce0cc94c4f5a067cc"
KNOWN_INSTALL="80c6d095c6e70758c2fd2ef3af5aec491954fa14c7bc883a03d1ce4250e936a8"
KNOWN_SEAL="fb92d8e061a96b4f0cfb866905f1966dbe55f43de199f7d8b789767f642c3356"
MANIFEST="evidence/manifest-sha256.json"
SAVE_TOOL="tools/save_state.py"
IMAGE_FILES=("再再.exe","bin/cl.exe","bin/pcgm-alpha.exe","bin/pcgm-beta.exe","bin/cl_memory.dll","bin/cl_runtime.dll")

def require(ok,message):
    if not ok:
        raise ValueError(message)

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()

def hashed(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def local(base,rel):
    base=base.resolve(strict=True)
    path=base/rel
    require(path==path.resolve() and path!=base and path.is_relative_to(base),"路径越出登记目录或含联接点："+str(path))
    return path

def read(path):
    return json.loads(path.read_bytes())

def inventory(folder):
    require(folder.is_dir() and folder.resolve()==folder,"宿主目录异常")
    result={}
    for file in folder.rglob("*"):
        require(not file.is_symlink() and not file.is_junction() and file.resolve()==file,"宿主内含路径联接："+str(file))
        if file.is_file():result[file.relative_to(folder).as_posix()]=hashed(file)
    return result

def fingerprint(files):
    return hashlib.sha256(canonical(files)).hexdigest()

def copy_flushed(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    with src.open("rb") as r,dst.open("xb") as w:
        while chunk:=r.read(1024*1024):w.write(chunk)
        w.flush();os.fsync(w.fileno())

def move_checked(src,dst,allowed,replace=False):
    # Both absolute names must still be the originally intended names at the last moment.
    for p in (src,dst):
        require(p.is_absolute() and p==p.resolve() and p!=allowed and p.is_relative_to(allowed),"切换目标越过安装目录")
    require(src.exists() and (replace or not dst.exists()),"来源缺失或目标已存在："+str(dst))
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    fn=kernel.MoveFileExW
    fn.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD];fn.restype=wintypes.BOOL
    if not fn(str(src),str(dst),8|(1 if replace else 0)):raise ctypes.WinError(ctypes.get_last_error())

def publish(target,data,root):
    temp=target.with_name(target.name+".new-"+uuid4().hex)
    require(temp==temp.resolve() and temp.is_relative_to(root),"临时发布路径异常")
    with temp.open("xb") as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    move_checked(temp,target,root,replace=True)

def inspect_bundle(root,bundle):
    old=read(local(bundle,"INSTALL.json"))
    meta=read(local(root,"INSTALL.json"))
    install=hashed(bundle/"INSTALL.json"); manifest=hashed(local(bundle,MANIFEST))
    known=(manifest==KNOWN_MANIFEST and install==KNOWN_INSTALL)
    registered=(str(meta.get("v2_manifest_sha256","")).lower()==manifest and
                str(meta.get("v2_install_sha256","")).lower()==install and
                meta.get("v2_rollback_dir") and Path(meta["v2_rollback_dir"]).resolve()==bundle)
    require(known or registered,"2.0 输入不匹配已知哈希或本安装登记的完整发布包")
    require(old.get("release")=="2.0" and old["identity"]==meta.get("identity") and old["host"]=="host/desktop.py","发行版本或身份不符")
    source=read(bundle/MANIFEST)["files"]
    require(source["INSTALL.json"]==install,"2.0 清单的安装描述不一致")
    host={k[5:]:v for k,v in source.items() if k.startswith("host/")}
    require(host and inventory(local(bundle,"host"))==host,"封存的 2.0 宿主内容与发布清单不一致")
    for rel,expected in source.items():
        if rel.startswith("tools/"):
            require(hashed(local(bundle,rel))==expected,"封存的 2.0 工具与清单不符："+rel)
    for rel in IMAGE_FILES:
        require(hashed(root/rel)==source[rel],"固定入口或引擎已经改变，请先确认兼容版本："+rel)
    archive=local(bundle,"sealed-2.0.zip")
    seal=hashed(archive)
    if known:require(seal==KNOWN_SEAL,"本次 2.0 封存包摘要不符")
    with zipfile.ZipFile(archive) as z:
        summary=json.loads(z.read("manifest.json"))
        require(summary["format"]==1 and summary["state"]["identity"]==old["identity"],"封存包身份、格式不符")
    return {"host":host,"host_sha256":fingerprint(host),"manifest_sha256":manifest,"install_sha256":install,
            "save_tool_sha256":source[SAVE_TOOL],"seal_sha256":seal,"identity":old["identity"],
            "registered":bool(registered),"known":known}

def state_view(root,identity):
    state=local(root,"state")
    require(read(local(state,"native/joint-reopen.json"))["identity"]==identity,"当前存档的原始身份不符")
    sqlite=local(state,"dashboard-split.sqlite")
    with closing(sqlite3.connect(sqlite.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        require(not db.execute("SELECT 1 FROM turns WHERE identity IS NOT ? LIMIT 1",(identity,)).fetchone(),"当前历史存在其他身份")
        turns,seq=db.execute("SELECT COUNT(*),MAX(seq) FROM turns").fetchone()
        schema=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"turns":turns,"last_seq":seq,"tables":schema,"native_sha256":hashed(local(state,"individual.pcgm")),
            "database_sha256":hashed(sqlite),
            "wal_sha256":hashed(sqlite.with_name(sqlite.name+"-wal")) if sqlite.with_name(sqlite.name+"-wal").exists() else None}

def mutex_names(root):
    prefix="Local\\Zaizai3-"+hashlib.sha256(str(root).casefold().encode()).hexdigest()[:16]+"-"
    return ["Local\\ZaizaiDesktop20","Local\\ZaizaiDesktop20Check",prefix+"supervisor",prefix+"worker"]

def kernel_api():
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    k.OpenMutexW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR];k.OpenMutexW.restype=wintypes.HANDLE
    k.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];k.CreateMutexW.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    k.ReleaseMutex.argtypes=[wintypes.HANDLE]
    return k

def holders(root):
    k=kernel_api();active=[]
    for name in mutex_names(root):
        h=k.OpenMutexW(0x100000,False,name)
        if h:
            k.CloseHandle(h);active.append(name)
        elif ctypes.get_last_error()!=2:
            raise ctypes.WinError(ctypes.get_last_error())
    return active

def host_processes(root):
    # Read only relevant interpreter commands; never print full command lines.
    cmd=("$ErrorActionPreference='Stop';$p=@(Get-CimInstance Win32_Process -Filter "
         "\"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object {$_.CommandLine -and "
         "$_.CommandLine.Replace('/','\\').IndexOf($env:ZAIZAI_ROLLBACK_HOST,[StringComparison]::OrdinalIgnoreCase) -ge 0} "
         "| Select-Object ProcessId,CommandLine);"
         "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);ConvertTo-Json -Compress -InputObject $p")
    r=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",cmd],capture_output=True,
                     encoding="utf8",timeout=12,creationflags=subprocess.CREATE_NO_WINDOW,check=True,
                     env=dict(os.environ,ZAIZAI_ROLLBACK_HOST=str(root/"host")+"\\"))
    active=[]
    watch=[str(root/name).casefold() for name in ("host/desktop.py","host/life3_worker.py","host/watchdog3.py")]
    for p in json.loads(r.stdout):
        line=(p.get("CommandLine") or "").replace("/","\\").casefold()
        if any(named in line for named in watch):active.append(p["ProcessId"])
    return active

@contextmanager
def closed(root):
    k=kernel_api()
    with ExitStack() as stack:
        for name in mutex_names(root):
            ctypes.set_last_error(0)
            handle=k.CreateMutexW(None,True,name);existed=ctypes.get_last_error()==183
            if not handle:raise ctypes.WinError(ctypes.get_last_error())
            stack.callback(k.CloseHandle,handle)
            require(not existed,"请先正常关闭再再桌面和生命循环后台进程，然后再应用回退。占用互斥量 "+name)
            stack.callback(k.ReleaseMutex,handle)
        active=host_processes(root)
        require(not active,"后台或桌面仍在运行，进程号 "+str(active))
        with local(root,"writer.guard").open("a+b") as guard:
            guard.seek(0)
            try:msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise RuntimeError("有未结束的正式写事务") from exc
            try:yield
            finally:
                guard.seek(0);msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)

def journal_path(root):
    return local(root,"rollback/host-selection-journal.json")

def saved_open(root):
    path=journal_path(root)
    if not path.exists():return None
    data=read(path)
    require(data.get("schema")=="zaizai-host-selection-1" and re.fullmatch(r"host-switch-[a-f0-9]{32}",data.get("tx","")),
            "本地主机切换日志格式不正确")
    return data if data["phase"]!="complete" else None

def create_switch(root,bundle,source):
    tx="host-switch-"+uuid4().hex
    directory=local(root,"rollback/"+tx)
    directory.mkdir()
    incoming=local(directory,"incoming-host");incoming.mkdir()
    for name in source["host"]:
        copy_flushed(local(bundle,"host/"+name),local(incoming,name))
    require(inventory(incoming)==source["host"],"准备的宿主副本校验失败")
    for rel,label in (("INSTALL.json","install"),(MANIFEST,"manifest")):
        copy_flushed(local(bundle,rel),local(directory,"target-"+label+".json"))
        current=local(root,rel)
        if current.exists():copy_flushed(current,local(directory,"former-"+label+".json"))
    old=fingerprint(inventory(local(root,"host")))
    status={"schema":"zaizai-host-selection-1","tx":tx,"phase":"prepared","bundle":str(bundle),
            "source_manifest":source["manifest_sha256"],"source_install":source["install_sha256"],
            "old_host":old,"new_host":source["host_sha256"],"started":time.time()}
    publish(journal_path(root),canonical(status),root)
    return status

def stage_save_tool(root,bundle,source,folder,state):
    # Earlier journal versions staged only the host and release markers.
    # Capture both tool versions before making any change, including on resume.
    former=local(folder,"former-save_state.py")
    target=local(folder,"target-save_state.py")
    if "previous_save_tool" not in state:
        live_tool=local(root,SAVE_TOOL)
        old_pin=hashed(live_tool)
        if not former.exists():publish(former,live_tool.read_bytes(),root)
        require(hashed(former)==old_pin,"切换开始前存档工具发生变化，拒绝覆盖未归档版本")
        if not target.exists():publish(target,local(bundle,SAVE_TOOL).read_bytes(),root)
        require(hashed(target)==source["save_tool_sha256"],"暂存的存档工具与 2.0 清单不符")
        state["previous_save_tool"]=old_pin
        state["target_save_tool"]=source["save_tool_sha256"]
        publish(journal_path(root),canonical(state),root)
    require(hashed(former)==state["previous_save_tool"] and
            hashed(target)==state["target_save_tool"]==source["save_tool_sha256"],"留档的存档工具版本无法核对")
    return former,target

def apply(root,bundle,snapshot=None):
    source=inspect_bundle(root,bundle)
    with closed(root):
        before=state_view(root,source["identity"])
        state=saved_open(root)
        if not state:
            if (fingerprint(inventory(local(root,"host")))==source["host_sha256"] and
                    hashed(local(root,"INSTALL.json"))==source["install_sha256"] and
                    hashed(local(root,MANIFEST))==source["manifest_sha256"] and
                    hashed(local(root,SAVE_TOOL))==source["save_tool_sha256"]):
                return {"already_restored":True,"release":"2.0","current_turns":before["turns"]}
            state=create_switch(root,bundle,source)
        require(Path(state["bundle"]).resolve()==bundle and state["source_manifest"]==source["manifest_sha256"]
                and state["source_install"]==source["install_sha256"] and state["new_host"]==source["host_sha256"],
                "有未完成的切换，请使用原指定的 2.0 包恢复")
        folder=local(root,"rollback/"+state["tx"]);old=local(folder,"former-host")
        host=local(root,"host");incoming=local(folder,"incoming-host")
        former_tool,target_tool=stage_save_tool(root,bundle,source,folder,state)
        def mark(phase):
            state["phase"]=phase
            publish(journal_path(root),canonical(state),root)
            if snapshot:snapshot(phase)
        if not old.exists():
            require(fingerprint(inventory(host))==state["old_host"],"切换前新版本内容发生改变")
            require(fingerprint(inventory(incoming))==state["new_host"],"暂存的 2.0 内容发生改变")
            move_checked(host,old,root)
            mark("former_host_archived")
        require(fingerprint(inventory(old))==state["old_host"],"保留的前一版宿主校验失败")
        if not host.exists():
            require(fingerprint(inventory(incoming))==state["new_host"],"暂存的 2.0 内容无法复核")
            move_checked(incoming,host,root)
            mark("target_host_installed")
        require(fingerprint(inventory(host))==state["new_host"],"安装位置出现未登记的宿主")
        live_tool=local(root,SAVE_TOOL)
        current_tool=hashed(live_tool)
        require(current_tool in (state["previous_save_tool"],state["target_save_tool"]),"存档工具是未归档的其他版本")
        if current_tool!=state["target_save_tool"]:
            publish(live_tool,target_tool.read_bytes(),root)
            require(hashed(live_tool)==source["save_tool_sha256"],"发布后的存档工具摘要不符")
            mark("save_tool_installed")
        for rel,label,pin in ((MANIFEST,"manifest",source["manifest_sha256"]),
                               ("INSTALL.json","install",source["install_sha256"])):
            target=local(root,rel);incoming_file=local(folder,"target-"+label+".json")
            require(hashed(incoming_file)==pin,"暂存的发布标记校验失败")
            if not target.exists() or hashed(target)!=pin:
                publish(target,incoming_file.read_bytes(),root)
                mark(label+"_installed")
        after=state_view(root,source["identity"])
        require(before==after,"切换期间有其他写入发生，存档未被回退，请核对写入来源")
        state["finished"]=time.time()
        state["state_unchanged"]=True
        state["current_turns"]=after["turns"]
        mark("complete")
        publish(local(folder,"completed.json"),canonical(state),root)
        return {"release":"2.0","former_host":str(old),"former_release_marker":str(folder/"former-install.json"),
                "former_save_tool":str(former_tool),"save_tool_sha256":state["target_save_tool"],
                "journal":str(journal_path(root)),"identity":source["identity"],"current_turns":after["turns"],
                "preserved_tables":len(after["tables"]),"state_bytes_unchanged":True}

def check(root,bundle):
    source=inspect_bundle(root,bundle)
    status=state_view(root,source["identity"])
    busy=holders(root);procs=host_processes(root)
    active=saved_open(root)
    return {"verified_bundle":str(bundle),"manifest_sha256":source["manifest_sha256"],"host_files":len(source["host"]),
            "verified_fixed_images":list(IMAGE_FILES),"save_tool_sha256":source["save_tool_sha256"],
            "installed_save_tool_sha256":hashed(local(root,SAVE_TOOL)),"identity":source["identity"],"live_turns":status["turns"],
            "table_count":len(status["tables"]),"release":read(root/"INSTALL.json")["release"],
            "ready_to_apply":not busy and not procs,"occupied_mutexes":busy,"occupied_processes":procs,
            "pending_switch":active["tx"] if active else None,
            "action":"check only; no state, release file or process changed"}

if __name__=="__main__":
    p=argparse.ArgumentParser(description="原地回退 2.0 本地宿主，保留当前存档与所有新增数据")
    p.add_argument("--bundle",required=True,type=Path)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument("--check",action="store_true")
    mode.add_argument("--apply",action="store_true")
    args=p.parse_args()
    result=(check if args.check else apply)(ROOT,args.bundle.resolve(strict=True))
    print(json.dumps(result,ensure_ascii=False,indent=2))
