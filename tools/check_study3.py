"""Exercise the installed host against a temporary database, live public sources and cl.exe."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import study3 as study

def run(network=True):
    with tempfile.TemporaryDirectory(prefix="zaizai-study-only-") as scratch:
        path=Path(scratch)/"study.sqlite";db=sqlite3.connect(path);db.row_factory=sqlite3.Row
        study.setup(db);db.commit()
        total=db.execute("select count(*) from study3_card").fetchone()[0]
        assert total==len(study.asset("catalog.json")["items"])
        elapsed=[];events=[]
        for i in range(12):
            before=time.perf_counter()
            with db:r=study.do_work(db)
            elapsed.append(round(1000*(time.perf_counter()-before),2));events.append(r)
        levels=dict(db.execute("select id,level from study3_card where target=4"))
        assert set(levels.values())=={4},levels
        first=next(e for e in events if e["kind"]=="transfer")
        assert study.proof_status(db,first["verified_claims"][0]["proof_sha256"])=="active"
        assert "POSITIVE" in study.command(db,"学习应用 C-01 | empirical,exclusion")
        assert "CONFLICT" in study.command(db,"学习应用 C-01 | empirical,exclusion,fits_all")
        assert "UNKNOWN" in study.command(db,"学习应用 C-01 | empirical")
        assert "NEGATIVE" in study.command(db,"学习应用 C-01 | fits_all")
        stepcount=lambda:db.execute("select count(*) from study3_log").fetchone()[0]
        at=stepcount()
        try:
            with db:study.do_work(db,should_yield=lambda:True)
        except InterruptedError:pass
        else:raise AssertionError("抢占时仍执行")
        assert stepcount()==at
        with db:
            db.execute("update study3_card set due=0 where id='C-01'")
            reviewed=study.do_work(db,mode="review")
            assert reviewed["kind"]=="review"
            assert study.command(db,"导入学习卡 新课 | 来源甲 | 先观察再提出假说。")==study.command(db,"导入学习卡 新课 | 来源甲 | 先观察再提出假说。")
        def testimony(family,sign,note):
            with db:
                msg=study.command(db,f"学习证据 测试命题 | {sign} | {family} | 第一版 | {note}")
            return msg.split("来源 ")[1].split("、")[0]
        src1=testimony("观察甲","支持","记录一")
        assert testimony("观察甲","支持","记录一")==src1
        src2=testimony("观察乙","支持","记录二")
        src3=testimony("观察丙","反对","独立反例")
        def work_until_quiet():
            for _ in range(12):
                pending=db.execute("select count(*) from study3_judgment where dirty").fetchone()[0]
                waiting=db.execute("select count(*) from study3_observation where stage='candidate'").fetchone()[0]
                if not (pending or waiting):break
                with db:study.do_work(db)
        work_until_quiet()
        read=lambda:db.execute("select * from study3_judgment where claim='测试命题'").fetchone()
        assert read()["status"]=="CONFLICT" and len(json.loads(read()["origins"]))==3
        conflicts=read()["proof"]
        with db:study.command(db,"撤回学习来源 "+src3)
        assert study.proof_status(db,conflicts)=="withdrawn"
        work_until_quiet();assert read()["status"]=="POSITIVE"
        with db:study.command(db,"撤回学习来源 "+src1)
        work_until_quiet();assert read()["status"]=="POSITIVE" and len(json.loads(read()["origins"]))==1
        with db:study.command(db,"撤回学习来源 "+src2)
        work_until_quiet();assert read()["status"]=="UNKNOWN"
        assert study.command(db,"订阅学习来源 https://127.0.0.1/").startswith("当前捕捞支持")
        net=[]
        if network:
            for _ in range(2):
                with db:r=study.network_work(db)
                assert r["kind"]=="fetch",r
                net.append(r["source"])
            assert study.network_work(db) is None
            with db:
                db.execute("update study3_feed set next_at=0 where url=?",(study.STATUS_URL,))
            with db:duplicate=study.network_work(db)
            assert duplicate["kind"]=="source_unchanged"
            for _ in range(30):
                if not db.execute("select 1 from study3_observation where stage='candidate'").fetchone() and not db.execute("select 1 from study3_judgment where dirty").fetchone():break
                with db:study.do_work(db)
            known=db.execute("select * from study3_judgment where claim='HTTP 404 的登记名称为 Not Found'").fetchone()
            assert known and known["mastered"] and known["status"]=="POSITIVE" and study.proof_status(db,known["proof"])=="active"
            assert db.execute("select status from study3_judgment where claim='IANA 将 POST 标为幂等'").fetchone()[0]=="NEGATIVE"
            with db:
                directed=study.command(db,"捕捞议题 202")
                assert "选出" in directed,directed
            work_until_quiet()
            with db:
                curiosity=study.do_work(db,mode="explore")
                assert curiosity["kind"]=="discovery",curiosity
        db.close()
        db=sqlite3.connect(path);db.row_factory=sqlite3.Row
        with db:study.setup(db)
        assert study.command(db,"学习卡 C-01").startswith("C-01") and len(db.execute("select id from study3_card").fetchall())==total+1
        db.close()
        return {"catalog_entries":total,"mastery":levels,"transfer_receipt":first,"independent_and_transfer_round_ms":elapsed,
                "withdrawal_statuses":["CONFLICT","POSITIVE","POSITIVE","UNKNOWN"],"duplicate_observation":True,
                "preemption":True,"reopened":True,"feeds":net}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=run(not args.offline)
    data=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:args.output.write_text(data+"\n",encoding="utf8")
    print(data)

