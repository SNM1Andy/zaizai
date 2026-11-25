"""Structured questions and an interruption-safe, bounded DSHarness public terminology route."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import subprocess
import slots31
from contextlib import closing
import time
import uuid

import advisor_client
import native

PUBLIC = {
    "testable_prediction": {
        "card":"C-01","sense":"hypothesis_test","probe":"用可反驳的预测考察一个科学假说",
        "query":"公开科学方法术语：用独立观察考察一个科学假说。这个过程最简短的常用中文标准词是什么？",
        "question":"本机词典中，哪个中文短词可表达对科学假说进行检验这一过程？"
    }
}
OPEN = ("open","pending","waiting","awaiting")
def packed(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def sha(obj):
    if isinstance(obj,str):
        obj=obj.encode()
    return hashlib.sha256(obj).hexdigest()

def setup(db):
    for stmt in (
        """CREATE TABLE IF NOT EXISTS life3_questions(id TEXT PRIMARY KEY,scope TEXT,state TEXT,packet TEXT,created REAL,touched REAL)""",
        """CREATE TABLE IF NOT EXISTS inquiry3_case(question TEXT PRIMARY KEY,route TEXT NOT NULL,
        phase TEXT NOT NULL,version TEXT NOT NULL,local_check TEXT,task TEXT UNIQUE,created REAL NOT NULL,
        touched REAL NOT NULL,result TEXT)""",
        """CREATE TABLE IF NOT EXISTS inquiry3_answer(id TEXT PRIMARY KEY,question TEXT NOT NULL,
        version TEXT NOT NULL,speaker TEXT NOT NULL,at REAL NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS inquiry3_dispatch(corpus_key TEXT PRIMARY KEY,task TEXT NOT NULL,
        question TEXT NOT NULL,created REAL NOT NULL)""",
        """CREATE INDEX IF NOT EXISTS inquiry3_by_question ON inquiry3_answer(question,active,at)""",
        """CREATE TABLE IF NOT EXISTS inquiry3_answer_event(seq INTEGER PRIMARY KEY,answer TEXT NOT NULL,
        kind TEXT NOT NULL,at REAL NOT NULL)""",
        """CREATE INDEX IF NOT EXISTS inquiry3_dispatches ON inquiry3_case(route,phase,touched)"""):
        db.execute(stmt)

def native_question(scope,packet):
    return (scope in {"pcgm","native"} or packet.get("engine")=="pcgm"
            or any(k in packet for k in ("native_id","request_sha256","pcgm_question")))

def seed_public(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study3_card'").fetchone():
        return
    spec=PUBLIC["testable_prediction"]
    card=db.execute("SELECT level,version FROM study3_card WHERE id=?",(spec["card"],)).fetchone()
    if not card or card[0]<1:
        return
    packet={"route":"advisor","public_key":"testable_prediction","question":spec["question"],
            "attempts":["已读 C-01；先按完整表达查已冻结的本地词典。"],
            "hypothesis":"此表达可能对应一个已有科学方法义项。","confidence":"待核验",
            "blocking":"需要一个可由本地词典独立证明的词头。","changes_if":"引用的 CL 词义证明为 POSITIVE。",
            "answer_format":"一个中文短词","source_ref":"C-01@"+str(card[1])}
    now=time.time()
    db.execute("INSERT OR IGNORE INTO life3_questions VALUES(?, 'public', 'open', ?,?,?)",
               ("public-course-c01-lex",packed(packet),now,now))

@contextmanager
def short_write(db):
    if db.in_transaction:
        raise RuntimeError("问询 I/O 工作线程需要空闲的独立数据库连接")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()

def fact_for(label,spec,db=None):
    if db is None:
        import service
        with closing(service.store()) as existing:return fact_for(label,spec,existing)
    bindings=slots31.snapshot(db)
    if bindings["L"]["id"] not in {"legacy-cl","joint25-cl"} or bindings["L"]["state"]!="ready":
        raise slots31.SlotUnavailable("L","unavailable","旧公开课程所锁的词典协议当前未绑定")
    domain=bindings["L"]["value_domain"];key=bindings["L"]["manifest_sha256"]
    corpus=bindings["L"]["artifacts"]["lexicon/lexicon_core.clpkg"]
    if not isinstance(label,str) or not label or len(label)>48 or any(ord(c)<32 for c in label):
        return {"status":domain["insufficient"],"reason":"没有可查的短词","binding":key,"corpus_pin":corpus}
    reply=slots31.dispatch(db,"L3",{"word":label},pin=slots31.pin(bindings["L"]))
    proof=reply["output"].get("proof") or {}
    rows=[v for v in proof.get("results",[]) if len(v["goal"].get("arguments",[]))==3
          and [a["value"] for a in v["goal"]["arguments"]]==["zh",label,spec["sense"]]]
    return {"label":label,"sense":spec["sense"],"status":rows[0]["status"] if rows else domain["insufficient"],
            "proof_sha256":sha(packed(reply)),"binding":key,"corpus_pin":corpus,"input_version":reply["input_version"],
            "sources":reply["sources"],"evidence":rows}

def public_route(db):
    b=slots31.snapshot(db)
    return b["L"]["id"] in {"legacy-cl","joint25-cl"} and b["L"]["state"]=="ready" and b["C"]["id"] in {"legacy-pcgm","joint25-pcgm"} and b["C"]["state"]=="ready"

def save_case(db,qid,phase,check=None,result=None):
    db.execute("""UPDATE inquiry3_case SET phase=?,touched=?,local_check=COALESCE(?,local_check),
                  result=COALESCE(?,result) WHERE question=?""",
               (phase,time.time(),None if check is None else packed(check),None if result is None else packed(result),qid))

def close_matching_version(db,qid):
    row=db.execute("""SELECT c.version,q.packet FROM inquiry3_case c JOIN life3_questions q
                    ON q.id=c.question WHERE c.question=?""",(qid,)).fetchone()
    if row and row[0]==sha(packed(json.loads(row[1]))):
        db.execute("UPDATE life3_questions SET state='answered',touched=? WHERE id=?",(time.time(),qid))
        return True
    return False

def report(qid,kind,message,status,**extra):
    return {"kind":kind,"topic":qid,"summary":message,"status":status,
            "receipt":"inquiry:"+qid+":"+status,"progress":status in {"answered","candidate","routed"},**extra}

def process_public(db,qid,pin,spec):
    try:
        initial=fact_for(spec["probe"],spec,db)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        with short_write(db):
            save_case(db,qid,"local_failed",result={"error":str(exc)[:250]})
        return report(qid,"inquiry_local","本地词典读取失败，已保留原问题。","failed")
    with short_write(db):
        if initial["status"]=="POSITIVE":
            save_case(db,qid,"verified_local",initial,{"outcome":"verified_local"})
            close_matching_version(db,qid)
            return report(qid,"inquiry_local","本机冻结词典已有该表达的证明。","answered",proof_sha256=initial["proof_sha256"])
        fixed_key=sha(packed([spec["query"],spec["sense"],initial["corpus_pin"]]))
        prior=db.execute("""SELECT d.question,c.phase,c.result FROM inquiry3_dispatch d
                         JOIN inquiry3_case c ON c.question=d.question WHERE d.corpus_key=?""",(fixed_key,)).fetchone()
        if prior:
            result=json.loads(prior[2]) if prior[2] else {"outcome":"unknown"}
            linked="reused_verified" if prior[1]=="verified_sense" else "linked_existing"
            save_case(db,qid,linked,initial,{**result,"original_question":prior[0]})
            if linked=="reused_verified":close_matching_version(db,qid)
            return report(qid,"inquiry_link","同一公开问题已关联原咨询回执。","answered" if linked=="reused_verified" else "routed")
        task="t"+uuid.uuid4().hex
        owned=db.execute("""UPDATE inquiry3_case SET phase='consulting',task=?,local_check=?,touched=?
                         WHERE question=? AND version=? AND phase='checking'""",(task,packed(initial),time.time(),qid,pin)).rowcount
        if owned:
            db.execute("INSERT INTO inquiry3_dispatch VALUES(?,?,?,?)",(fixed_key,task,qid,time.time()))
    if not owned:
        return None
    if not public_route(db):
        with short_write(db):save_case(db,qid,"withheld_before_send",result={"outcome":"waiting","detail":"槽已切换，未派发咨询"})
        return report(qid,"inquiry_deferred","槽已切换，此公开问题未发出。","waiting")
    # Fixed public question and opaque random correlation ID are the entire request.
    # Egress never reads the user's question text, transcript, answers or identity.
    try:
        output=advisor_client.consult(spec["query"],task)
        if output.get("task")!=task:
            raise RuntimeError("顾问返回的任务号不匹配")
        candidate={key:str(output.get(key) or "")[:450] for key in ("canonical","domain","explanation","source")}
        if not candidate["source"].startswith("DSHarness/"):
            raise RuntimeError("顾问来源与当前接线不符")
        with short_write(db):
            save_case(db,qid,"candidate_received",result={"candidate":candidate})
        return review(db,qid,spec,candidate)
    except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as exc:
        # A broken stream cannot establish whether the provider already processed it.
        with short_write(db):
            row=db.execute("SELECT phase,result FROM inquiry3_case WHERE question=?",(qid,)).fetchone()
            if row[0]=="candidate_received":
                return report(qid,"inquiry_advisor","已保留顾问建议，等待再次进行本地核验。","candidate")
            save_case(db,qid,"uncertain_dispatch",result={"detail":str(exc)[:250],"outcome":"unknown"})
        return report(qid,"inquiry_advisor","已留存咨询任务号，未收到可归属的结果。","unknown")

def review(db,qid,spec,candidate):
    # Provider tone and narrative are retained for provenance and independent of this verdict.
    if not public_route(db):
        return report(qid,"inquiry_deferred","顾问建议已留在候选区，等待所需槽。","waiting")
    check=fact_for(candidate["canonical"],spec,db)
    verdict="verified_sense" if check["status"]=="POSITIVE" else "unverified_candidate"
    with short_write(db):
        save_case(db,qid,verdict,result={"candidate":candidate,"independent_check":check})
        if verdict=="verified_sense":
            close_matching_version(db,qid)
    return report(qid,"inquiry_advisor","候选「"+candidate["canonical"]+"」；冻结词典的独立证明为 "+check["status"]+"。",
                  "answered" if verdict=="verified_sense" else "candidate",proof_sha256=check.get("proof_sha256"),
                  provider=candidate["source"],public_only=True)

def observable(packet):
    key=packet.get("local_check")
    if key=="gpu_policy":
        path=native.ROOT/"INSTALL.json"
        raw=path.read_bytes()
        return {"source":"host:INSTALL.json#"+sha(raw),"value":json.loads(raw).get("gpu")}
    if key=="legacy_memory":
        return {"source":"verified R28 checkpoint","value":native.legacy_memory.overview()}
    return None

def work(db):
    now=time.time()
    with short_write(db):
        seed_public(db)
        db.execute("""UPDATE inquiry3_case SET phase='uncertain_dispatch',touched=?,result=?
            WHERE phase='consulting' AND touched<?""",
            (now,packed({"outcome":"unknown","detail":"咨询中断，保留任务号，不自动重发。"}),now-90))
        # Checking precedes dispatch and is repeatable. A stored reply resumes at local proof only.
        db.execute("DELETE FROM inquiry3_case WHERE phase='checking' AND task IS NULL AND touched<?",(now-90,))
        resume=db.execute("""SELECT q.id,q.packet,c.result FROM inquiry3_case c JOIN life3_questions q ON q.id=c.question
            WHERE c.phase='candidate_received' ORDER BY c.created LIMIT 1""").fetchone()
        if resume:
            qid,raw,cached=resume
            packet=json.loads(raw)
            spec=PUBLIC.get(packet.get("public_key"))
            if not spec:
                save_case(db,qid,"unverified_candidate")
                return report(qid,"inquiry_advisor","该公开概念已移出当前课程，建议保留。","candidate")
        else:
            row=db.execute("""SELECT q.id,q.scope,q.packet FROM life3_questions q
              LEFT JOIN inquiry3_case c ON c.question=q.id WHERE c.question IS NULL
              AND q.state IN ('open','pending','waiting','awaiting')
              ORDER BY CASE WHEN q.scope='public' THEN 0 ELSE 1 END,q.created LIMIT 1""").fetchone()
            if not row:
                return None
            qid,scope,raw=row
            packet=json.loads(raw)
            route=packet.get("route","user")
            if native_question(scope,packet):
                route="native"
            spec=PUBLIC.get(packet.get("public_key")) if scope=="public" else None
            if route=="advisor" and (spec is None or not spec["query"]):
                route="user"
            pin=sha(packed(packet))
            db.execute("INSERT INTO inquiry3_case VALUES(?,?, 'checking', ?,NULL,NULL,?,?,NULL)",(qid,route,pin,now,now))
            if route=="native":
                save_case(db,qid,"native_protocol")
                return report(qid,"inquiry_native","原生问题保留原题号、证据版本和答复入口。","routed")
            if route=="iteration":
                save_case(db,qid,"bottleneck")
                return report(qid,"inquiry_bottleneck","已将反复出现的能力缺口转给迭代账本。","failed",category="capability",reason="recurring_capability_gap")
            if route not in {"advisor","local"}:
                save_case(db,qid,"await_user")
                return report(qid,"inquiry_user","价值或私人问题已进入本机问询队列。","routed")
    if resume:
        return review(db,qid,spec,json.loads(cached)["candidate"])
    if route=="advisor":
        return process_public(db,qid,pin,spec)
    result=observable(packet)
    with short_write(db):
        resolved=result is not None and result["value"] is not None
        save_case(db,qid,"observed_local" if resolved else "needs_observation",result=result)
        if resolved:
            close_matching_version(db,qid)
    return report(qid,"inquiry_local","本机观察已附出处。" if resolved else "此题尚缺可执行的本机观察方法，保留未决。","answered" if resolved else "unknown")

def command(db,text):
    text=text.strip().rstrip("。")
    if text=="问询统计":
        phases=dict(db.execute("SELECT phase,COUNT(*) FROM inquiry3_case GROUP BY phase"))
        return "已处理问询："+"、".join(f"{k} {n}" for k,n in sorted(phases.items())) if phases else "暂无已处理问询。"
    op,space,rest=text.partition(" ")
    if not space or op not in {"问询详情","答复问询","撤回答复问询"}:
        return None
    address,sep,reply=(part.strip() for part in rest.partition("|"))
    fields=address.split()
    if len(fields) not in (1,2):
        return "请填写问询编号；可在编号后附上「问询详情」中的完整版本摘要。"
    qid=fields[0]
    q=db.execute("SELECT scope,state,packet FROM life3_questions WHERE id=?",(qid,)).fetchone()
    if not q:
        return "没有这个问询编号。"
    packet=json.loads(q[2])
    pin=sha(packed(packet))
    if len(fields)==2 and fields[1]!=pin:
        return "问询版本已变化或摘要不符，请按最新「问询详情」核对；此答复未保存。"
    if op=="问询详情":
        case=db.execute("SELECT phase,local_check,task,result FROM inquiry3_case WHERE question=?",(qid,)).fetchone()
        answers=db.execute("SELECT id,body,active FROM inquiry3_answer WHERE question=? ORDER BY at",(qid,)).fetchall()
        lines=[f"{qid} · {q[1]} · 版本 {pin}",str(packet.get("question") or packet.get("prompt") or "待复核的问题")]
        for label,key in (("已试","attempts"),("假设","hypothesis"),("置信","confidence"),("卡点","blocking"),("改判条件","changes_if"),("答复格式","answer_format")):
            if packet.get(key):
                value=packet[key]
                lines.append(label+"："+("；".join(map(str,value)) if isinstance(value,list) else str(value)))
        if case:
            lines.append("处理阶段 "+case[0]+("，任务 "+case[2] if case[2] else ""))
            if case[1]:lines.append("本地先查："+json.loads(case[1]).get("status","UNKNOWN"))
            if case[3]:
                result=json.loads(case[3]);candidate=result.get("candidate")
                if candidate:lines.append("顾问候选 "+candidate["canonical"]+" · "+candidate["source"]+"\n"+candidate["explanation"])
                if result.get("independent_check"):
                    proof=result["independent_check"]
                    lines.append("独立核验 "+proof["status"]+" · "+str(proof.get("proof_sha256","")))
                if result.get("value") is not None:lines.append("现场证据 "+packed(result["value"])[:1600])
                if result.get("detail"):lines.append(result["detail"])
        lines.extend(f"{a} · {'有效' if c else '已撤回'} · {b[:240]}" for a,b,c in answers)
        return "\n".join(lines)
    if native_question(q[0],packet):
        return "请从原生「问题」查看题号和版本，按「回答 题号 版本 来源 原子」答复。"
    if not sep or not reply or len(reply)>1200:
        return "请使用「"+op+" 编号 | 内容」，最多 1200 字。"
    if op=="撤回答复问询":
        removed=db.execute("UPDATE inquiry3_answer SET active=0 WHERE id=? AND question=? AND active=1",(reply,qid)).rowcount
        if not removed:return "此问询没有可撤回的该条答复。"
        db.execute("INSERT INTO inquiry3_answer_event(answer,kind,at) VALUES(?,'withdraw',?)",(reply,time.time()))
    else:
        aid="ia"+sha(packed([qid,pin,reply]))[:20]
        added=db.execute("INSERT OR IGNORE INTO inquiry3_answer VALUES(?,?,?,'本机用户',?,?,1)",(aid,qid,pin,time.time(),reply)).rowcount
        restored=db.execute("UPDATE inquiry3_answer SET active=1 WHERE id=? AND active=0",(aid,)).rowcount if not added else 0
        if added or restored:
            db.execute("INSERT INTO inquiry3_answer_event(answer,kind,at) VALUES(?,?,?)",(aid,"submit" if added else "restore",time.time()))
    if packet.get("route")=="user":
        count=db.execute("SELECT COUNT(*) FROM inquiry3_answer WHERE question=? AND version=? AND active=1",(qid,pin)).fetchone()[0]
        status="responded" if count==1 else "multiple_responses" if count>1 else "open"
        db.execute("UPDATE life3_questions SET state=?,touched=? WHERE id=?",(status,time.time(),qid))
    return ("已撤回该条答复，原记录保留。" if op=="撤回答复问询" else
            f"已保存本机用户的答复 {aid}，绑定当前问询版本。可用「问询详情 {qid}」查看来源。")
