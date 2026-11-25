"""Inspect the host's optional L/C bindings or apply a verified change at a request boundary."""
import argparse
from contextlib import ExitStack,closing,contextmanager
import json
import msvcrt
from pathlib import Path
import sqlite3
import sys

@contextmanager
def hold(p):
    with p.open("a+b") as f:
        f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def main():
    a=argparse.ArgumentParser(description="再再 3.1 宿主槽件配置")
    a.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    a.add_argument("--language",help="empty、legacy-cl 或已验收的本地发行件")
    a.add_argument("--cognition",help="empty、legacy-pcgm 或已验收的本地发行件")
    a.add_argument("--enroll",help="登记已通过独立契约与对话验收的本机发行编号")
    a.add_argument("--revert",choices=["L","C"],help="恢复此槽上一个经过登记的绑定")
    a.add_argument("--selftest",action="store_true",help="实际复验当前已绑定的件")
    args=a.parse_args()
    root=args.root.resolve(strict=True);sys.path.insert(0,str(root/"host"));import slots31 as api
    if api.ROOT!=root:raise RuntimeError("槽件管理器路径不符")
    writable=any(v is not None for v in (args.language,args.cognition,args.enroll,args.revert)) or args.selftest
    mode="rw" if writable else "ro"
    with ExitStack() as stack:
        if writable:
            for p in (root/"writer.guard",root/"state/desktop-writer.lock"):
                stack.enter_context(hold(p))
        d=stack.enter_context(closing(sqlite3.connect((root/"state/dashboard-split.sqlite").as_uri()+"?mode="+mode,uri=True,timeout=8)))
        d.row_factory=sqlite3.Row
        if writable:
            with d:
                api.setup(d)
                if args.enroll:api.register_release(d,args.enroll)
                if args.revert:
                    prior=d.execute("SELECT prior FROM slot31_changes WHERE slot=? ORDER BY seq DESC LIMIT 1",(args.revert,)).fetchone()
                    if not prior:raise ValueError("没有可恢复的旧登记")
                    if args.revert=="L":args.language=prior[0]
                    else:args.cognition=prior[0]
                if args.selftest:
                    rows=api.checkpoint(d)
                    for role,meta in rows.items():
                        if meta["id"]!="empty":
                            probe=api._probe(d,meta)
                            if not probe["passed"]:raise RuntimeError("自检失败："+role)
                            d.execute("UPDATE slot31_bindings SET health='ready',reason='',selftest=? WHERE slot=?",(api.canonical(probe),role))
                result=api.bind(d,language=args.language,cognition=args.cognition)
        else:result=api.snapshot(d)
        print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

