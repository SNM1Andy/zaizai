"""Run partial-bind, deadline, candidate provenance and empty-disk checks without touching the live store."""
from pathlib import Path
import argparse,json,sys,time
from contextlib import closing
from uuid import uuid4
p=argparse.ArgumentParser();p.add_argument("--root",required=True,type=Path);p.add_argument("--empty-disk",action="store_true");p.add_argument("--out",required=True,type=Path);a=p.parse_args()
root=a.root.resolve();sys.path.insert(0,str(root/"host"))
import service as s, life3,life3_worker as worker,life_slots31 as boundary,slots31,inquiry3,study3,native
if (root/"state/dashboard-split.sqlite").samefile(Path("D:/再再2.0/state/dashboard-split.sqlite")):raise ValueError("请在独立验证副本运行")
s.setup();report={}
with closing(s.store()) as d:
    with d:slots31.bind(d,language="empty",cognition="empty");life3.put(d,"network","0")
    with d:study3.command(d,"导入学习卡 宿主框架 | 独立检验 "+uuid4().hex+" | 缺证应保留为未决，不能当作反例。")
    levels=lambda:[tuple(x) for x in d.execute("SELECT id,level FROM study3_card ORDER BY id")]
    prior=levels()
    if a.empty_disk:
        assert not (root/"bin/cl.exe").exists() and not (root/"bin/pcgm-alpha.exe").exists()
        assert not (root/"state/individual.pcgm").exists()
        report["absence_confirmed"]=["CL image","PCGM image","PCGM mutable save"]
    for _ in range(180):
        ev=worker.select_step(d)
        if not ev:break
    else:raise AssertionError("host queue never reaches wait")
    assert not ev
    n=d.execute("select count(*) from life3_events").fetchone()[0]
    assert worker.select_step(d) is None and d.execute("select count(*) from life3_events").fetchone()[0]==n
    report["next_idle_pass_events_added"]=0
    assert levels()==prior
    report["reading_or_mastery_unchanged"]=len(prior)
    assert "宿主已保存" in life3.command(d,"观察队列","check","r")
    assert "未采集" in life3.command(d,"原生几何状态","check","r")
    assert "缺测" in life3.command(d,"内在状态","check","r")
    if not a.empty_disk:
        # With only C, receive actual sourced frames; no grades or action choices.
        with d:slots31.bind(d,language="empty",cognition="legacy-pcgm")
        ack=d.execute("select count(*) from life31_ack").fetchone()[0]
        choices=d.execute("select count(*) from evo3_assignments").fetchone()[0]
        worker.select_step(d)
        assert d.execute("select count(*) from life31_ack").fetchone()[0]==ack+1
        assert choices==d.execute("select count(*) from evo3_assignments").fetchone()[0] and levels()==prior
        report["c_only_acks"]=1
        with d:slots31.bind(d,language="legacy-cl",cognition="empty")
        worker.select_step(d)
        assert choices==d.execute("select count(*) from evo3_assignments").fetchone()[0] and levels()==prior
        report["l_only_selections"]=0
        with d:slots31.bind(d,language="legacy-cl",cognition="legacy-pcgm")
        try:
            with slots31.quota_context(lambda:0):slots31.dispatch(d,"L2",{"source":": x(sym).\n? x(a).\n"})
        except TimeoutError:report["quota_enforced"]=True
        else:raise AssertionError("zero budget allowed dispatch")
        actual=inquiry3.fact_for("检验",inquiry3.PUBLIC["testable_prediction"],d)
        assert actual["status"]=="POSITIVE" and actual["sources"]
        report["independent_L3"]=actual["proof_sha256"]
        with d:
            while boundary.index_materials(d):pass
        dispatch=slots31.dispatch
        sent=[]
        def impossible(db,port,payload,**kwargs):
            frame=dispatch(db,port,payload,**kwargs)
            if port=="C3":
                for c in frame["output"]["candidates"]:c["cost"]=999
                sent.append(port)
            return frame
        slots31.dispatch=impossible
        try:
            for i in range(12):
                outcome=worker.select_step(d)
                if outcome and outcome["kind"]=="selection_deferred":break
            else:raise AssertionError("invalid candidate set not traced")
            assert worker.select_step(d) is None and len(sent)==1,sent
            report["unchanged_excluded_set_called_once"]=True
        finally:slots31.dispatch=dispatch
        with d:slots31.bind(d,language="empty",cognition="empty")
a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8");print(report)
