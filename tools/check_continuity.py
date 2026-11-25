from pathlib import Path
from contextlib import closing
from uuid import uuid4
import subprocess,sys,json,time,re
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import service as s,native as n
def main():
    s.setup();s.recover()
    report={}
    suffix=uuid4().hex[:10]
    def ask(text,session="qa_dialogue"):
        r=s.process(text,session,source="验收");s.deliver(r["id"]);return r
    def head():return n.sha(n.SAVE.read_bytes())
    def question(qid):return n.readcmd("question "+qid)["results"][0]
    # Restore any evidence from the last acceptance run before injecting fresh, named answers.
    qid=re.search(r"question (\w+) \w+ ready_to_use\(local_term\)",n.execute(":ask"))[1]
    q=question(qid)
    prefix="qa"+suffix
    src=prefix[:13]
    addr=q["request_sha256"];unchanged=head()
    try:ask("回答 "+qid+" "+"0"*64+" "+src+" term_defined(local_term)")
    except ValueError:pass
    else:raise AssertionError("stale pin accepted")
    assert head()==unchanged
    try:ask("回答 "+qid+" "+addr+" "+src+" identity_restored(zaizai)")
    except ValueError:pass
    else:raise AssertionError("wrong fact accepted")
    first=ask("回答 "+qid+" "+addr+" "+src+" term_defined(local_term)")
    pos=question(qid); assert pos["status"]=="answered",pos
    second=ask("回答 "+qid+" "+pos["request_sha256"]+" "+src+"b !term_defined(local_term)")
    both=question(qid);assert both["status"]=="conflicted"
    for x in both["evidence"]:
        if x.get("active") and x.get("source_label","").startswith(src):ask("撤回观察 "+x["observation"])
    assert question(qid)["status"]=="open"
    report["question"]={"id":qid,"first":first["id"],"counter":second["id"],"both":both,"after_withdrawal":question(qid)}
    first=ask("状态","qa_focus_a");second=ask("最近回执","qa_focus_b")
    a=ask("为什么","qa_focus_a");b=ask("为什么","qa_focus_b")
    assert "identity_restored" in a["answer"] and "receipt_available" in b["answer"]
    word=ask("词义 验证","qa_focus_a")
    pick=ask("选择 hypothesis_test","qa_focus_a")
    assert "检验" in pick["answer"]
    remembered=ask("记住 Windows部署回执 = "+suffix,"qa_focus_a")
    recovered=ask("回忆 Windows部署回执","qa_focus_b")
    assert suffix in recovered["answer"]
    report["dialogue"]={k:v["id"] for k,v in dict(a=a,b=b,lexicon=word,chosen=pick,remembered=remembered,recovered=recovered).items()}
    obs=prefix+"obs"
    phrase="采集 Windows本机验收 | "+obs+" term_grounded("+prefix+")"
    first=ask(phrase);again=ask(phrase);assert "已收过" in again["answer"]
    before=head()
    try:ask(phrase.replace("term_grounded","term_local_match"))
    except ValueError:pass
    else:raise AssertionError("conflicting same-ID observation accepted")
    assert head()==before
    ask("撤回观察 "+obs);ask("恢复观察 "+obs);ask("撤回观察 "+obs)
    report["observation"]={"request":first["id"],"repeat":again["id"],"id":obs}
    review=ask("提议词条 本机会话代号"+suffix+" | 状态 | 本机运行","qa_focus_a")
    cid=json.loads(review["plan"])["change"][1]
    adopted=ask("采用 "+cid,"qa_focus_a");assert "已采用" in adopted["answer"]
    assert "当前 PCGM" in ask("本机会话代号"+suffix,"qa_focus_a")["answer"]
    assert "不能确定" in ask("本机会话代号"+suffix,"qa_focus_b")["answer"]
    rev=ask("撤回词条 "+cid,"qa_focus_a")
    assert "不能确定" in ask("本机会话代号"+suffix,"qa_focus_a")["answer"]
    report["lexicon"]={"candidate":cid,"adoption":adopted["id"],"withdraw":rev["id"]}
    stamp=n.status()
    with s.writer():
        ab=n.switch();ba=n.switch()
    assert n.status()["owner"]==stamp["owner"] and n.status()["state"]["individual"]==n.IDENTITY
    assert "identity_restored" in n.execute(":transcript qa_focus_a")
    report["ab"]=[ab,ba]
    report["newest_head"]=head()
    (ROOT/"evidence/continuity.json").write_text(n.canonical(report),encoding="utf8")
    print("question/counterevidence, two native session foci, memory, observation, lexicon adoption/revocation and A/B verified")
if __name__=="__main__":main()

