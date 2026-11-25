"""Kill a real desktop worker at paired commit boundaries and check recovery against the migrated state."""
import json,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
import service as s
def mark(when):
    if when==sys.argv[2]:
        print("BOUNDARY "+when,flush=True)
        time.sleep(35)
def main():
    report={}
    for boundary in ("before","native","after"):
        key="t"+uuid4().hex
        q="状态"
        owner=n.status()["state"]["event"]
        with subprocess.Popen([sys.executable,"-X","utf8","-B",__file__,"worker",boundary,key],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf8",creationflags=subprocess.CREATE_NO_WINDOW) as p:
            line=p.stdout.readline().strip()
            if line!="BOUNDARY "+boundary:raise RuntimeError(line+" "+p.stderr.read())
            p.kill();p.wait(timeout=8)
        with s.closing(s.store()) as db:prior=dict(s.row(db,key))
        s.recover()
        result=s.process(q,"crash_check",key,"acceptance")
        again=s.process(q,"crash_check",key,"acceptance")
        assert result["seq"]==again["seq"] and result["native_receipt"]==again["native_receipt"]
        assert n.status()["state"]["event"]==owner+1
        with s.closing(s.store()) as db:
            assert db.execute("select count(*) from requests where id=? and seq=?",(key,result["seq"])).fetchone()[0]==1
        assert prior["phase"]=={"before":"planned","native":"prepared","after":"committed"}[boundary]
        assert prior["delivered"] is None
        report[boundary]=dict(id=key,phase_at_kill=prior["phase"],final=result["phase"],seq=result["seq"],
                              identity=n.IDENTITY,native_events_added=1,receipt=result["native_receipt"])
    (ROOT/"evidence/crash.json").write_text(n.canonical(report),encoding="utf8")
    print("3 shutdown boundaries: one native commit and one SQLite receipt each")
if __name__=="__main__":
    if len(sys.argv)>1:s.process("状态","crash_check",sys.argv[3],"acceptance",checkpoint=mark)
    else:main()

