"""Two real lexicon lookups through the local session and the installed DSHarness."""
import json
from pathlib import Path
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
import service as s

def main():
    sid="study_"+uuid4().hex[:10]
    evidence={"session":sid,"cycles":[]}
    def ask(text):
        r=s.process(text,sid,source="桌面接口验收")
        return r["id"],json.loads(r["plan"])
    ask("开启词条自学")
    try:
        for term in ("帮我看看当前的运行状态","辨一辨这个说法是否值得信赖"):
            rid,first=ask("词义 "+term)
            if first.get("provider")=="unavailable":
                raise RuntimeError(first["answer"])
            change=first["change"]
            assert first["provider"].startswith("DSHarness/") and first["review"]["batch"]
            assert change[1]=="c"+rid[1:17] and change[2]==term
            second_id,again=ask("词义 "+term)
            assert "provider" not in again and ("learned" in again or change[1] in again["answer"])
            assert change[-1] in {"adopted","candidate"}
            evidence["cycles"].append({"request":rid,"review_head":first["review"]["basis"],"provider":first["provider"],
                "phrase":term,"candidate":change[1],"status":change[-1],"proof":first["review"]["result"]["integrity"],
                "subsequent_request":second_id,"subsequent_answer":again["answer"]})
    finally:
        ask("关闭词条自学")
    assert {r["status"] for r in evidence["cycles"]}=={"adopted","candidate"},evidence
    (ROOT/"evidence/learning.json").write_text(n.canonical(evidence),encoding="utf8")
    print("Two real consultations and two subsequent local lookups:",[r["status"] for r in evidence["cycles"]])

if __name__=="__main__":main()
