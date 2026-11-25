"""Export a consistent local, all-session view of the delegated work ledger."""
import argparse
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

PHASES = {
    "queued":"排队", "issued":"已派发", "committed":"已提交", "uncertain":"结果待核对",
    "refused":"已拒绝", "superseded":"输入已有新版", "waiting":"等待依据",
    "partial":"部分提交", "cancelled":"已取消", "prepared":"已准备","not_recorded":"原生核对未执行",
}
KINDS = {"answer":"采纳答卷","source":"来源更新","control":"委托开关","enroll":"内部问询",
         "repair":"规则复核","scope_install":"登记范围","withdraw":"撤回答卷","local_lexical_rule":"词义规则采纳或回退"}

def local_time(seconds):
    return datetime.fromtimestamp(seconds).astimezone().isoformat(timespec="seconds")

def plain(value):
    return " ".join(str(value or "").split()).replace("|","\\|")

def render(root):
    history = root/"state/dashboard-split.sqlite"
    with closing(sqlite3.connect(history.resolve(strict=True).as_uri()+"?mode=ro",uri=True,timeout=4)) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"deleg25_control","deleg25_jobs","deleg25_log"} <= tables:
            raise ValueError("此存档尚无委托执行账本")
        enabled=db.execute("SELECT v FROM deleg25_control WHERE k='enabled'").fetchone()
        counts=dict(db.execute("SELECT phase,count(*) FROM deleg25_jobs GROUP BY phase ORDER BY phase"))
        jobs=db.execute("SELECT kind,scope,phase,reason,changed_ns FROM deleg25_jobs ORDER BY changed_ns DESC LIMIT 50").fetchall()
        events=db.execute("SELECT job,phase,reason,result_sha256,at_ns FROM deleg25_log ORDER BY seq DESC LIMIT 100").fetchall()
        lexical=[]
        if "native_lexref25_requests" in tables:
            lexical=db.execute("SELECT id,session,phase,created FROM native_lexref25_requests ORDER BY created DESC LIMIT 20").fetchall()
    lines=["# 再再委托执行报告","",f"生成于 {local_time(datetime.now().timestamp())}。包括此存档的全部会话及后台任务。","",
           "委托执行"+("已启用" if enabled is None or enabled[0]=="1" else "已暂停")+"。"]
    if counts:
        lines+=["","累计任务 "+ "、".join(f"{PHASES.get(k,k)} {v}" for k,v in counts.items())+"。"]
    if jobs:
        lines+=["","## 最近任务（最多 50 条）","",
                "| 更新时间 | 会话 | 操作 | 状态 | 说明 |","|---|---|---|---|---|"]
        for j in jobs:
            lines.append(f"| {local_time(j['changed_ns']/1e9)} | {plain(j['scope'])} | {KINDS.get(j['kind'],plain(j['kind']))} | {PHASES.get(j['phase'],plain(j['phase']))} | {plain(j['reason'])} |")
    else:lines+=["","尚无委托任务。"]
    if events:
        lines+=["","## 最近状态变化（最多 100 条）",""]
        for e in events:
            lines+=["- "+local_time(e["at_ns"]/1e9)+" · "+PHASES.get(e["phase"],plain(e["phase"]))+" · "+plain(e["reason"]),
                    "  任务 "+plain(e["job"])]
            if e["result_sha256"]:lines.append("  结果 SHA-256 "+plain(e["result_sha256"]))
    if lexical:
        lines+=["","## 最近原生词义操作（最多 20 条）",""]
        for r in lexical:
            lines.append("- "+local_time(r["created"])+" · "+plain(r["session"])+" · "+PHASES.get(r["phase"],plain(r["phase"]))+" · 请求 "+plain(r["id"]))
    return "\n".join(lines)+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument("--out",type=Path)
    p.add_argument("--open",action="store_true")
    o=p.parse_args()
    text=render(o.root)
    dest=o.out or o.root/"evidence/joint25/委托执行报告.md"
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8-sig",dir=dest.parent,delete=False) as tmp:
        path=Path(tmp.name)
        tmp.write(text)
    try:os.replace(path,dest)
    finally:path.unlink(missing_ok=True)
    print(dest.resolve())
    if o.open:subprocess.Popen([str(Path(os.environ["SystemRoot"])/"System32/notepad.exe"),str(dest.resolve())])

if __name__=="__main__":
    main()
