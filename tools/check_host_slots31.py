"""Check the actual detached host with both slots empty and all engine execution denied."""
import argparse
from contextlib import closing
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

def forbid_engines():
    def check(event,args):
        if event=="subprocess.Popen":
            command=os.fsdecode(args[0]) if args[0] is not None else str(args[1]).split(".exe",1)[0]+".exe"
            if re.search(r"(?:^|[\\/])(?:cl|pcgm-alpha|pcgm-beta)\.exe$",command.strip('"'),re.I):
                raise AssertionError("empty host attempted an engine invocation: "+command)
    sys.addaudithook(check)

def main():
    args=parse()
    root=args.root.resolve(strict=True)
    live=Path("D:/再再2.0").resolve()
    if root==live or (root/"state/dashboard-split.sqlite").samefile(live/"state/dashboard-split.sqlite"):
        raise ValueError("仅在具有独立存档的复验副本运行")
    sys.path.insert(0,str(root/"host"))
    import native as n
    import service as s
    import slots31
    if n.ROOT!=root:raise ValueError("核对路径错误")
    forbid_engines()
    if args.worker:
        def interrupt(at):
            if at==args.worker:os._exit(71)
        s.process("独立宿主回合，中断边界 "+args.worker,"host_cut",args.request,"acceptance",checkpoint=interrupt)
        raise RuntimeError("未命中中断边界")
    s.setup()
    with closing(s.store()) as db:
        pins=slots31.snapshot(db)
        assert all(pins[k]["state"]=="empty" for k in "LC"),pins
        initial=db.execute("select count(*) from turns").fetchone()[0]
    session="empty"+uuid4().hex[:10]
    def ask(text,key=None):
        r=s.process(text,session,key,source="acceptance")
        assert r["phase"]=="committed" and r["host_receipt"] and not r["native_receipt"]
        s.deliver(r["id"])
        return r
    basic=ask("宿主状态");assert basic["frame_kind"]=="host_data" and n.IDENTITY in basic["answer"]
    ordinary=ask("我今天要去哪里学习？")
    assert ordinary["frame_kind"]=="slot_status" and "没有生成认知回复" in ordinary["answer"]
    duplicate=ask(ordinary["question"],ordinary["id"])
    assert all(ordinary[k]==duplicate[k] for k in ("seq","host_receipt","frame_kind"))
    try:ask("另一条内容",ordinary["id"])
    except ValueError:pass
    else:raise AssertionError("reused request ID was accepted with a different payload")
    old=ask("旧记忆")
    item=ask("回忆 object_0000")
    assert old["frame_kind"]==item["frame_kind"]=="host_data" and json.loads(item["plan"])["legacy_records"]
    recent=ask("最近回执");assert item["host_receipt"] in recent["answer"]
    mem=ask("记住 独立宿主回归 = 已记录")
    assert mem["id"] in ask("回忆 独立宿主回归")["answer"]
    checks=[]
    for boundary in ("before","slot","native","after"):
        key="t"+uuid4().hex
        p=subprocess.run([sys.executable,"-B","-X","utf8",__file__,"--root",str(root),"--worker",boundary,"--request",key],
                         timeout=15,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        assert p.returncode==71,p.stderr[-600:].decode("utf8","replace")
        with closing(s.store()) as db:previous=dict(s.row(db,key))
        expect={"before":"planned","slot":"prepared","native":"prepared","after":"committed"}[boundary]
        assert previous["phase"]==expect and previous["delivered"] is None,previous["phase"]
        s.recover()
        r=s.process("独立宿主回合，中断边界 "+boundary,"host_cut",key,"acceptance")
        second=s.process("独立宿主回合，中断边界 "+boundary,"host_cut",key,"acceptance")
        assert r["seq"]==second["seq"] and r["host_receipt"]==second["host_receipt"]
        with closing(s.store()) as db:
            assert db.execute("select count(*) from host31_commits where request_id=?",(key,)).fetchone()[0]==1
            assert db.execute("select count(*) from turns where seq=?",(r["seq"],)).fetchone()[0]==1
            assert db.execute("select count(*) from life3_events where id=?",(key,)).fetchone()[0]==1
        checks.append({"phase":boundary,"at_death":expect,"id":key,"seq":r["seq"],"receipt":r["host_receipt"]})
    packet_path=root/"evidence/window-slots.json"
    old_time=packet_path.stat().st_mtime_ns if packet_path.exists() else 0
    desktop_run=subprocess.run([sys.executable,"-B","-X","utf8",root/"host/desktop.py","--verify-slots"],
                               cwd=root,timeout=35,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert desktop_run.returncode==0,desktop_run.stderr.decode("utf8","replace")[-600:]
    assert packet_path.stat().st_mtime_ns>old_time
    ui=json.loads(packet_path.read_bytes())
    assert ui["window_mapped"] and ui["monitor_mapped"] and ui["message_displayed"] and ui["monitor_displayed"]
    assert ui["host_receipt"] and ui["frame_kind"]=="slot_status" and ui["status_label_displayed"] and not ui["error"]
    with closing(s.store()) as db:
        ui_row=s.row(db,ui["request"])
        assert ui_row["host_receipt"]==ui["host_receipt"] and ui_row["delivered"] is not None
    result={"passed":True,"preexisting_turns":initial,"scope":"独立存档；双槽空；业务测试进程禁止启动任一旧引擎",
            "engine_directory_present":n.BIN.is_dir(),"engine_files_present":[p.name for p in (n.CL,n.exe("alpha"),n.exe("beta")) if p.exists()],
            "native_save_present":n.SAVE.is_file(),"identity":n.IDENTITY,"typed_unavailable":ordinary["id"],
            "two_window_status":ui["request"],"memory_readback":item["id"],"duplicate_rejected":True,
            "interruptions":checks,"time":time.time()}
    if args.out:args.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(result,ensure_ascii=False))

def parse():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--worker",choices=["before","slot","native","after"])
    parser.add_argument("--request")
    parser.add_argument("--out",type=Path)
    return parser.parse_args()

if __name__=="__main__":main()
