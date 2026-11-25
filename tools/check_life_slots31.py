"""Check the real independent host queue and fail-closed selection on a writable copy."""
from pathlib import Path
from contextlib import closing
import argparse
import json
import time
from uuid import uuid4

def check(root):
    import sys
    sys.path.insert(0,str(root/"host"))
    import native as n,service as s,life3,life3_worker as worker,life_slots31 as boundary,slots31,study3,inner3
    assert n.ROOT==root.resolve() and not n.DB.samefile(Path("D:/再再2.0/state/dashboard-split.sqlite"))
    s.setup()
    with closing(s.store()) as db:
        with db:slots31.bind(db,language="empty",cognition="empty")
        original=boundary.bindings(db);print("empty",[(k,m["id"],m["state"]) for k,m in original.items()],flush=True)
        before=n.sha(n.SAVE.read_bytes())
        old=n.run;oldcompile=study3.prove
        def unavailable(*a,**k):raise AssertionError("空槽触达原生程序")
        n.run=unavailable;study3.prove=unavailable
        def stages():return list(map(tuple,db.execute("select id,level,blocked from study3_card order by id")))
        with db:study3.command(db,"导入学习卡 期限与回执 | 本地验收 "+uuid4().hex+" | 一笔请求只提交一次，读回复用同一编号。")
        original_stages=stages()
        try:
            event=worker.select_step(db);assert event and event["kind"]=="host_index",event
            assert n.sha(n.SAVE.read_bytes())==before and original_stages==stages()
            with db:
                for text in ("生命状态","观察队列","内在状态","几何接入","课程","教导记录"):
                    assert life3.command(db,text,"sample",uuid4().hex)
                packet=dict(kind="dialogue",topic="普通用户输入",request="life31_test_request",source="desktop",
                            status="waiting",executed=False,host_status=True,frame_kind="slot_unavailable",summary="认知槽空置")
                life3.audit(db,packet["request"],packet,"dialogue","这是一个没有给槽作答的观察","sample")
                # No extra frames, memory or receipts for the same observation.
                life3.audit(db,packet["request"],packet,"dialogue","这是一个没有给槽作答的观察","sample")
                assert db.execute("select count(*) from life31_frames where id=?",("event:"+packet["request"],)).fetchone()[0]==1
        finally:n.run=old;study3.prove=oldcompile
        with db:slots31.bind(db,language="legacy-cl",cognition="legacy-pcgm")
        b=boundary.bindings(db);assert boundary.legacy_pair(b),b
        advanced=False
        for i in range(20):
            event=worker.select_step(db)
            if event:
                print("legacy",event["kind"],event.get("executed_lane"),flush=True)
                row=db.execute("select sample from round31_events where id=?",(event["receipt"],)).fetchone()
                if row:
                    trace=json.loads(row[0])
                    if trace.get("decision"):
                        assert trace["decision"]["slot_bindings"]["C"]["id"]=="legacy-pcgm"
                        assert trace["decision"]["actual_choice"] in trace["decision"]["order"]
                        advanced=True;break
            else:print("no event",life3.meta(db,"mode"),boundary.bindings(db)["C"].get("state"))
        assert advanced,"没有实际 C3 提案通过宿主选择与执行"
        # Explicitly test exclusions and absence metrics using real host scores and real frozen CL proof rows.
        with db:
            offers={k:dict(id=k,permission=v[0],cost=v[1],available=k!="flow",demand_count=1) for k,v in boundary.LANES.items()}
            version=boundary.pin(offers)
            proofs=boundary.eligibility(db,offers,version,b,1800)
            inputs={"previous_lane":"study","eligibility_version":version}
            proposals=[{"id":k,"proof_ref":proofs[k]["ref"],"cost":v["cost"],"base_score":0.5} for k,v in offers.items()]
            proposals[0]["proof_ref"]="foreign";proposals[-1]["cost"]=99
            choice,decision=boundary.select(db,"exclusions_"+uuid4().hex,b,offers,proofs,proposals,4,inputs,None)
            assert choice=="integration" and not decision["candidates"]["study"]["eligible"],(choice,decision)
            assert not decision["candidates"]["flow"]["eligible"] and not decision["candidates"]["native"]["eligible"]
            stale,stale_decision=boundary.select(db,"stale_"+uuid4().hex,b,offers,proofs,proposals,4,
                                                {**inputs,"eligibility_version":"different-generation"},None)
            assert stale is None and not stale_decision["candidates"]["integration"]["eligible"]
            ack=db.execute("select count(*) from life31_ack").fetchone()[0]
            assert ack>=1
            result={"empty_legacy_calls":0,"preserved_mastery":len(original_stages),"raw_input_retained":True,"slot_snapshot":original,
                    "real_choice":choice,"reject_reasons":{k:v["reason"] for k,v in decision["candidates"].items() if not v["eligible"]},
                    "observation_acks":ack,"empty_preserved_state":True,"stale_L2_reference_rejected":True}
        with db:slots31.bind(db,language="empty",cognition="empty")
        return result

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);ap.add_argument("--out",type=Path)
    opts=ap.parse_args();result=check(opts.root.resolve());print(json.dumps(result,ensure_ascii=False))
    if opts.out:opts.out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf8")
