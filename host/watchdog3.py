"""Independent Windows observer. Only its own JSONL log is opened for writing."""
import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sqlite3
import time


class ProcessHandle:
    def __init__(self,pid):
        self.kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        self.kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype=wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes=(wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD))
        self.kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
        self.handle=self.kernel.OpenProcess(0x100000|0x1000,False,pid)
        if not self.handle and ctypes.get_last_error()!=87:
            raise ctypes.WinError(ctypes.get_last_error())

    def exit_code(self):
        if not self.handle:
            return -1
        result=self.kernel.WaitForSingleObject(self.handle,0)
        if result==258:
            return None
        if result!=0:
            raise ctypes.WinError(ctypes.get_last_error())
        code=wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


def sample(database,pid,stale_after,verify=False,identity=None):
    with closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True,timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        if verify and db.execute("PRAGMA quick_check(1)").fetchone()[0]!="ok":
            return "database_corrupt",{}
        if verify and identity:
            wrong=db.execute("SELECT 1 FROM turns WHERE identity IS NOT ? LIMIT 1",(identity,)).fetchone()
            if wrong:
                return "identity_mismatch",{}
        meta=dict(db.execute("""SELECT key,value FROM life3_meta
                             WHERE key IN ('pid','heartbeat','mode','paused')"""))
        if not meta.get("heartbeat") or not meta.get("pid"):
            return "worker_starting",{}
        if int(meta["pid"])!=pid:
            return "worker_pid_mismatch",{"registered":meta["pid"]}
        age=time.time()-float(meta["heartbeat"])
        info={"heartbeat_age_s":round(age,2),"mode":meta.get("mode"),"paused":meta.get("paused")=="1"}
        if age< -5 or age>stale_after:
            return "invalid_heartbeat" if age<0 else "worker_stale",info
        return "healthy",info


def log_event(path,kind,**details):
    row={"time":time.time(),"state":kind,**details}
    with path.open("a",encoding="utf8",newline="\n") as stream:
        stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
        stream.flush()


def monitor(database,log,pid,interval,stale,identity=None,once=False):
    if database==log or database.with_suffix(database.suffix+"-wal")==log:
        raise ValueError("看门狗日志须与存档分开")
    log.parent.mkdir(parents=True,exist_ok=True)
    try:
        handle=ProcessHandle(pid)
    except OSError as exc:
        log_event(log,"process_unobservable",pid=pid,error=str(exc))
        return 2
    last=None
    audit_due=0
    try:
        while True:
            exitcode=handle.exit_code()
            if exitcode is not None:
                log_event(log,"worker_exit",pid=pid,exit_code=exitcode)
                return 0 if exitcode==0 else 3
            now=time.monotonic()
            verify=now>=audit_due
            try:
                state,details=sample(database,pid,stale,verify,identity)
            except (sqlite3.Error,ValueError,OSError) as exc:
                state,details="database_unavailable",{"error":str(exc)}
            if verify:
                audit_due=now+60
            if state!=last:
                log_event(log,state,pid=pid,**details)
                last=state
            if once:
                return 0 if state=="healthy" else 2
            time.sleep(interval)
    finally:
        handle.close()


if __name__=="__main__":
    p=argparse.ArgumentParser(description="再再 3.0 独立只读运行监测")
    p.add_argument("--database",required=True,type=Path)
    p.add_argument("--log",required=True,type=Path)
    p.add_argument("--parent",required=True,type=int,help="需要观测的生命循环进程号")
    p.add_argument("--interval",type=float,default=2)
    p.add_argument("--stale-after",type=float,default=45)
    p.add_argument("--identity",help="预期个体编号，填写后核对对话表")
    p.add_argument("--once",action="store_true")
    options=p.parse_args()
    raise SystemExit(monitor(options.database.resolve(),options.log.resolve(),options.parent,
                            max(.05,options.interval),max(.1,options.stale_after),options.identity,options.once))
