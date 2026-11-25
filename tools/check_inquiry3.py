"""End-to-end public inquiry and local question accounting on a separate database."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import inquiry3 as q
import study3

def check(public):
    with tempfile.TemporaryDirectory(prefix="zaizai3-inquiries-") as folder, closing(sqlite3.connect(Path(folder)/"case.sqlite")) as db:
        db.row_factory=sqlite3.Row
        with db:
            q.setup(db)
            study3.setup(db)
        def add(key,scope,packet):
            with db:db.execute("INSERT INTO life3_questions VALUES(?,?,'open',?,?,?)",(key,scope,q.packed(packet),time.time(),time.time()))
        add("qa-values","local",{"question":"应优先讲清依据吗？","route":"user","confidence":"需本人说明"})
        assert q.work(db)["status"]=="routed"
        with db:
            pin=q.sha(q.packed(json.loads(db.execute("SELECT packet FROM life3_questions WHERE id='qa-values'").fetchone()[0])))
            assert pin in q.command(db,"问询详情 qa-values")
            assert "未保存" in q.command(db,"答复问询 qa-values "+"0"*64+" | 过时答复")
            assert not db.execute("SELECT 1 FROM inquiry3_answer").fetchone()
            assert "绑定" in q.command(db,"答复问询 qa-values "+pin+" | 我更看重依据")
            q.command(db,"答复问询 qa-values | 我更看重依据")
            assert db.execute("SELECT count(*) FROM inquiry3_answer").fetchone()[0]==1
            q.command(db,"答复问询 qa-values | 这次优先简短")
            assert db.execute("SELECT state FROM life3_questions WHERE id='qa-values'").fetchone()[0]=="multiple_responses"
            answer=db.execute("SELECT id FROM inquiry3_answer ORDER BY at DESC LIMIT 1").fetchone()[0]
            q.command(db,"撤回答复问询 qa-values | "+answer)
            assert db.execute("SELECT state FROM life3_questions WHERE id='qa-values'").fetchone()[0]=="responded"
        private="仅用于检查本地路由的验收文字"
        add("qa-private","private",{"question":private,"public_key":"testable_prediction","route":"advisor"})
        assert q.work(db)["kind"]=="inquiry_user"
        assert db.execute("SELECT COUNT(*) FROM inquiry3_dispatch").fetchone()[0]==0
        add("qa-observe","local",{"question":"显卡保护策略","local_check":"gpu_policy","route":"local"})
        assert q.work(db)["status"]=="answered"
        exact=json.loads(db.execute("SELECT result FROM inquiry3_case WHERE question='qa-observe'").fetchone()[0])
        assert exact["value"]["stop_c"]==87 and exact["value"]["reserve_mib"]==3072
        add("qa-native","pcgm",{"question":"原题","request_sha256":"x","route":"user"})
        assert q.work(db)["kind"]=="inquiry_native"
        with db:assert "原生" in q.command(db,"答复问询 qa-native | 不改原题")
        add("qa-repeat","local",{"question":"重复的能力失败","route":"iteration"})
        assert q.work(db)["kind"]=="inquiry_bottleneck"
        result={"user_reply_versioned":True,"counterresponses_retained":True,"native_protocol_preserved":True,
                "local_receipt":exact,"private_egress_count":0,"bottleneck_routed":True}
        spec=q.PUBLIC["testable_prediction"]
        result["independent_positive"]=q.fact_for("检验",spec)["status"]
        result["independent_unknown"]=q.fact_for("提议的新词头",spec)["status"]
        assert result["independent_positive"]=="POSITIVE" and result["independent_unknown"]=="UNKNOWN"
        if public:
            # Read the actual imported curriculum, through its ordinary work interface.
            for _ in range(180):
                with db:study3.do_work(db)
                if db.execute("SELECT level FROM study3_card WHERE id='C-01'").fetchone()[0]>=1:break
            assert db.execute("SELECT level FROM study3_card WHERE id='C-01'").fetchone()[0]>=1
            receipt=q.work(db)
            assert receipt and receipt["kind"]=="inquiry_advisor"
            row=db.execute("SELECT phase,task,result,local_check FROM inquiry3_case WHERE question='public-course-c01-lex'").fetchone()
            assert row["phase"] in {"verified_sense","unverified_candidate"},(row["phase"],row["result"])
            evidence=json.loads(row["result"])
            assert evidence["candidate"]["source"].startswith("DSHarness/") and json.loads(row["local_check"])["status"]=="UNKNOWN"
            add("qa-same-public","public",{"route":"advisor","public_key":"testable_prediction","question":"本地相关问法"})
            assert q.work(db)["kind"]=="inquiry_link"
            assert db.execute("SELECT COUNT(*) FROM inquiry3_dispatch").fetchone()[0]==1
            result["public"]={"request":row["task"],"question":spec["query"],"provider":evidence["candidate"]["source"],
                "suggested":evidence["candidate"]["canonical"],"local_status":evidence["independent_check"]["status"],
                "proof_sha256":evidence["independent_check"].get("proof_sha256"),"phase":row["phase"],"remote_requests":1}
        return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--public-consult",action="store_true")
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    result=json.dumps(check(args.public_consult),indent=2,ensure_ascii=False)
    if args.out:args.out.write_text(result+"\n",encoding="utf8")
    print(result)
