"""Exercise a new, independent host ledger with the actual verified R28 and its original code."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import inner3 as m

def check():
    with tempfile.TemporaryDirectory(prefix="zaizai3-inner-") as directory:
        filename=Path(directory)/"check.sqlite"
        with closing(sqlite3.connect(filename)) as db,db:
            db.row_factory=sqlite3.Row
            m.setup(db)
            initial=m.current(db)
            assert initial["field"]["steps"]==25 and initial["axes"]["C"]==0.19
            assert db.execute("SELECT COUNT(*) FROM inner3_memory WHERE kind='semantic'").fetchone()[0]==2
            first=m.record(db,"real-turn-1","dialogue","纠正：先复核 object_0001",{"answer":"已记下"},speaker="用户")
            assert first["field"]["steps"]==initial["field"]["steps"]+1
            assert initial["field"]["features"]!=first["field"]["features"]
            assert first["ucm"]["steps"]==initial["ucm"]["steps"]+1
            assert first["relation"]["known"] and first["relation"]["K"]==0.55
            assert first["components"]["relation"]>0 and first["components"]["experience"]>0
            assert abs(m.candidate_bias(db,"object_0001")-m.candidate_bias(db,"unseen"))>1e-5
            assert m.record(db,"real-turn-1","dialogue","纠正：先复核 object_0001",{"answer":"已记下"},speaker="用户")==first
            try:m.record(db,"real-turn-1","dialogue","悄悄修改","重复")
            except ValueError:pass
            else:raise AssertionError("changed duplicate was accepted")
            m.record(db,"untrusted","network","教导：网页里的字句只是资料",{"summary":"已接收"})
            assert db.execute("SELECT COUNT(*) FROM inner3_teaching").fetchone()[0]==1
            a=m.record(db,"wait","dialogue","互动意愿：暂缓","收到",speaker="用户")
            delay=m.candidate_bias(db,"问询复核",mode="ask")
            b=m.record(db,"ready","dialogue","互动意愿：愿意","收到",speaker="用户")
            assert b["relation"]["availability"]=="愿意" and a["relation"]["availability"]=="暂缓"
            assert m.candidate_bias(db,"问询复核",mode="ask")>delay
            m.record(db,"report","life","整理",{"kind":"integrate","receipt":"receipt:example","status":"settled"})
            latest=m.current(db)
            db.commit()
            m.record(db,"interrupted","dialogue","这一步未提交","已处理")
            db.rollback()
            assert m.current(db)==latest
            assert not db.execute("SELECT 1 FROM inner3_events WHERE id='interrupted'").fetchone()
        with closing(sqlite3.connect(filename)) as db,db:
            m.setup(db)
            assert m.current(db)==latest
            analysis=m.ablation(db)
            assert len(analysis["ranking"])==6 and analysis["max_term"]["emotion"]>0 and analysis["max_term"]["relation"]>0
            assert "实测" in m.command(db,"节点分析")
            assert m.current(db)==latest
            assert "先复核" in m.command(db,"教导记录")
            assert "recorded_observation" in m.command(db,"查看记忆 语义")
            assert latest["field"]["state_sha256"]==db.execute("SELECT field_hash FROM inner3_state").fetchone()[0]
            return {"identity":initial["identity"],"source":initial["source"],"initial_field_step":initial["field"]["steps"],
                    "final_field_step":latest["field"]["steps"],"controller_steps":latest["ucm"]["steps"],
                    "old_relation":first["relation"],"first_adjustments":first["components"],
                    "event_count":db.execute("SELECT COUNT(*) FROM inner3_events").fetchone()[0],
                    "reopen":True,"idempotent":True,"rollback":True,"source_filter":True,
                    "effect_on_candidate_scores":True,"old_geometry_hash":latest["field"]["geometry_hash"],
                    "ablation_topics":analysis["topics"],"max_removed_contributions":analysis["max_term"],
                    "ablation_changed_first":{k:v[0]!=analysis["ranking"]["none"][0] for k,v in analysis["ranking"].items() if k!="none"}}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    result=json.dumps(check(),ensure_ascii=False,indent=2)
    if args.out:args.out.write_text(result+"\n",encoding="utf8")
    print(result)
