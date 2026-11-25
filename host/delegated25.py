"""Delegated execution of bounded native operations. Sources, rule generation, proof and eligibility remain native."""
from pathlib import Path
import hashlib
import json
import re
import time

import joint25_agenda_host as agenda
import joint25_evidence as evidence

ROOT=Path(__file__).resolve().parents[1]
POLICY="joint25-local-delegation/1"
ACTOR="宿主（本机用户委托）"
AID=re.compile(r"[0-9a-f]{64}\Z")
def packed(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)
def pin(v):return hashlib.sha256(packed(v).encode()).hexdigest()
def stamp():return time.time_ns()
def setup(db):
    for sql in (
        """CREATE TABLE IF NOT EXISTS deleg25_control(k TEXT PRIMARY KEY,v TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS deleg25_jobs(
           id TEXT PRIMARY KEY,kind TEXT NOT NULL,scope TEXT NOT NULL,trigger_id TEXT NOT NULL,inputs TEXT NOT NULL,
           phase TEXT NOT NULL,reason TEXT NOT NULL,actor TEXT NOT NULL,native_review TEXT,head_before TEXT,head_after TEXT,
           receipt TEXT,created_ns INTEGER NOT NULL,changed_ns INTEGER NOT NULL)""",
        """CREATE INDEX IF NOT EXISTS deleg25_pending ON deleg25_jobs(phase,created_ns)""",
        """CREATE TABLE IF NOT EXISTS deleg25_log(seq INTEGER PRIMARY KEY,job TEXT NOT NULL,phase TEXT NOT NULL,
           reason TEXT NOT NULL,head_before TEXT,head_after TEXT,result_sha256 TEXT,at_ns INTEGER NOT NULL)"""):
        db.execute(sql)
def enabled(db):
    r=db.execute("SELECT v FROM deleg25_control WHERE k='enabled'").fetchone()
    return not r or r[0]=="1"
def put(db,k,v):db.execute("INSERT OR REPLACE INTO deleg25_control VALUES(?,?)",(k,str(v)))
def get(db,k,default=""):
    r=db.execute("SELECT v FROM deleg25_control WHERE k=?",(k,)).fetchone()
    return r[0] if r else default
def job(db,k):return db.execute("SELECT * FROM deleg25_jobs WHERE id=?",(k,)).fetchone()
def queue(db,kind,scope,trigger,values,why):
    key=pin([POLICY,kind,scope,values])
    if not job(db,key):
        now=stamp()
        db.execute("INSERT INTO deleg25_jobs VALUES(?,?,?,?,?,'queued',?,?,NULL,NULL,NULL,NULL,?,?)",
                   (key,kind,scope,trigger,packed(values),why,ACTOR,now,now))
        db.execute("INSERT INTO deleg25_log(job,phase,reason,at_ns) VALUES(?,'queued',?,?)",(key,why,now))
    return key
def status(db,key,phase,why,*,review=None,before=None,after=None,result=None):
    db.execute("""UPDATE deleg25_jobs SET phase=?,reason=?,native_review=coalesce(?,native_review),
        head_before=coalesce(?,head_before),head_after=coalesce(?,head_after),receipt=coalesce(?,receipt),
        changed_ns=? WHERE id=?""",(phase,why,review,before,after,packed(result) if result is not None else None,stamp(),key))
    db.execute("INSERT INTO deleg25_log(job,phase,reason,head_before,head_after,result_sha256,at_ns) VALUES(?,?,?,?,?,?,?)",
               (key,phase,why,before,after,pin(result) if result is not None else None,stamp()))
def short(db,key):
    r=job(db,key)
    if not r:return "没有这条委托任务。"
    value=json.loads(r["receipt"]) if r["receipt"] else {}
    details={k:value[k] for k in ("ticket","native_truth","families","edits","observation","decision_event","writes_state","module","selected","status","head_sha256","sha256") if k in value}
    return f"{r['kind']} · {r['phase']} · {r['reason']}\n执行方 {r['actor']}；任务 {r['id']}"+("\n"+packed(details) if details else "")
def current_head():
    n,_=agenda._engines(ROOT)
    b=ROOT/"releases/joint25/bin"
    return n.snapshot(n.exe(b,"alpha"),ROOT/"state/individual.pcgm")["head"]

def after_source(db,claim,session,event_id):
    """Call inside the host transaction containing the recorded/retracted source. Only enqueue."""
    setup(db)
    try:v=evidence.review(db,claim,session)
    except ValueError:return None  # Materials without a registered structured target stay in the source ledger.
    values={"claim":claim,"approval":v["approval_sha256"],"goal":v["target"]["goal_sha256"]}
    key=queue(db,"source",session,event_id,values,"来源或撤回改变了可复核输入；待独立语言核验")
    for row in db.execute("SELECT id,inputs FROM deleg25_jobs WHERE kind='source' AND scope=? AND phase='queued' AND id!=?",(session,key)).fetchall():
        if json.loads(row["inputs"])["claim"]==claim:status(db,row["id"],"superseded","有更新的同范围来源快照")
    return key
def source_change(db,text,session,event_id):
    op,_,body=text.strip().partition(" ")
    if op=="来源登记":
        try:claim=json.loads(body)["claim_id"]
        except (TypeError,ValueError,KeyError):return None
    elif op=="撤回来源记录":claim=body.partition("|")[0].strip()
    else:return None
    return after_source(db,claim,session,event_id)

def _frozen_review(db,c,values):
    ticket,request,member,artifact,package,snap=values["fields"]
    d=dict(ticket=ticket,request_pin=request,member=member,artifact=artifact,package=package,snapshot=snap)
    return agenda.port(db,c,"C4","answer_review",{"answer":d},ms=3700)
def _withdraw_review(db,c,scope,key):
    previous=job(db,key)
    if not previous or previous["scope"]!=scope or previous["kind"]!="answer" or previous["phase"]!="committed" or not previous["native_review"]:
        raise ValueError("只能撤回本会话已有真实采纳回执的答卷。")
    old=db.execute("SELECT body,receipt FROM joint25_reviews WHERE pin=? AND kind='answer' AND phase='committed'",(previous["native_review"],)).fetchone()
    if not old:raise ValueError("缺少原生答卷的持久回执")
    before=json.loads(old["body"]);fields=dict(before["answer"],proof=before["verified"]["proof_sha256"])
    return agenda.port(db,c,"C4","withdraw_review",{"answer":fields},ms=3000)
def _choice(review):
    d=review["review"]["decision"];i=d["selected"]
    if i is None:return "undecided",None
    o=d["options"][i]
    if not o.get("eligible"):return "ineligible",None
    return o["kind"],next((q for q in review["review"]["rule_reviews"] if q["option_index"]==i),None)

def _confirmed_unsent(db,row):
    """The inner native gateway writes its own durable intent before its first effect."""
    if not row["head_before"] or current_head()!=row["head_before"]:return False
    if row["kind"]=="source":
        return not (evidence.exists(db,"joint25_source_requests") and
                    db.execute("SELECT 1 FROM joint25_source_requests WHERE id=?",("d"+row["id"][:32],)).fetchone())
    if not row["native_review"]:return False
    marker=db.execute("SELECT phase FROM joint25_reviews WHERE pin=?",(row["native_review"],)).fetchone()
    return bool(marker and marker[0]=="reviewed")
def _closed_rule(review):
    selected,r=_choice(review)
    if selected not in ("rewrite","rollback"):return selected,False
    if not r or not AID.fullmatch(r.get("compiled_cl_slice_sha256") or ""):return selected,False
    # Native terminal checks and the host's finite syntactic boundary both apply.
    rule=r["rule"].strip()
    m=re.fullmatch(r"([a-z][a-z0-9_]{0,47})\(\$([a-z]\w*)\)\s*<-\s*([a-z][a-z0-9_]{0,47})\(\$\2\)\.",rule)
    if not m:return selected,False
    banned=("geom_","artifact_","sensor_","permission_","host_","joint25_")
    if any(x.startswith(banned) or x in {"scoped_claim","labelled_support"} for x in (m[1],m[3])):return selected,False
    return selected,True

def _execute(db,key,checkpoint=None):
    """Run at the host writer boundary with no other open transaction."""
    if db.in_transaction:raise ValueError("委托工作需要独立宿主事务边界")
    row=job(db,key)
    if not row or row["phase"]!="queued" or not enabled(db):return False
    c=agenda.checked(db)
    if not c:return False
    kind=row["kind"];scope=row["scope"];data=json.loads(row["inputs"])
    before=current_head();issued=False;review_id=None
    try:
        if kind=="source":
            candidate=evidence.review(db,data["claim"],scope)
            if candidate["approval_sha256"]!=data["approval"]:
                with db:status(db,key,"superseded","输入版本已有变化，使用来源账本中新任务",before=before)
                return True
            phase=candidate["source_admission"]["admission"]
            prior=evidence.exists(db,"joint25_source_views") and db.execute("SELECT 1 FROM joint25_source_views WHERE claim=?",(data["claim"],)).fetchone()
            if phase not in {"admitted","conflict"} and not prior:
                with db:status(db,key,"waiting","尚无独立准入依据，保留在来源账本",before=before,result={"status":phase})
                return True
            request="d"+key[:32]
            with db:status(db,key,"issued","绑定结构化目标与当前来源版本，交独立 L2/L5 与原生批次核对",before=before,review=data["approval"])
            issued=True
            if checkpoint:checkpoint("issued")
            out=evidence.sync(db,data["claim"],data["approval"],request,scope)
        else:
            if kind=="scope_install":
                from scope_existing25 import existing
                prior=existing(db,ROOT,c,data["tag"])
                if prior is not None:
                    with db:status(db,key,"committed","已按原生历史与旧回执核对，沿用原登记",review=prior["original_review"],
                                   before=before,after=prior["head_sha256"],result=prior)
                    return True
                candidate=agenda.port(db,c,"C3","scope_review",{"tag":data["tag"]},ms=3500)
            elif kind=="answer":candidate=_frozen_review(db,c,data)
            elif kind=="withdraw":candidate=_withdraw_review(db,c,scope,data["answer_job"])
            elif kind=="repair":
                candidate=agenda.port(db,c,"C3","repair_review",ms=3000)
                selected,ok=_closed_rule(candidate)
                if not ok:
                    with db:status(db,key,"waiting","原生选择 "+selected+"，没有符合本轮委托边界且通过独立复验的变更",before=before,result={"selected":selected})
                    return True
            else:raise ValueError("未知工作类别")
            with db:
                review_id=agenda.remember(db,scope,kind,c,candidate)
                status(db,key,"issued","已锁定原生复核、版本、身份，执行已委托操作",review=review_id,before=before)
            issued=True
            if checkpoint:checkpoint("issued")
            out=agenda.approve(db,c,kind,review_id,scope)
        if checkpoint:checkpoint("after_native")
        after=current_head()
        with db:status(db,key,"committed","原生结果与持久回执已核对",before=before,after=after,result=out)
    except Exception as ex:
        if db.in_transaction:db.rollback()
        # An explicit native refusal before issuing has no effect. During/after dispatch,
        # uncertainty must be reconciled with the exact request; never automatically retry it.
        phase="uncertain" if issued else "refused"
        if issued:
            try:
                if _confirmed_unsent(db,job(db,key)):phase="refused"
            except (RuntimeError,ValueError,OSError):pass
        with db:status(db,key,phase,str(ex)[:500],before=before,review=review_id)
    return True

def _recover(db):
    # Recovery is read-only with respect to PCGM. It never re-enters the write operation.
    rows=db.execute("SELECT * FROM deleg25_jobs WHERE phase IN ('issued','uncertain') ORDER BY changed_ns LIMIT 3").fetchall()
    c=agenda.checked(db)
    if not c:return
    for r in rows:
        key=r["id"];kind=r["kind"];data=json.loads(r["inputs"])
        if kind=="local_lexical_rule":continue
        if r["phase"]=="issued" and _confirmed_unsent(db,r):
            with db:status(db,key,"queued","相同原生头与内层账本证明尚未派发，按原任务重新核对")
            continue
        if kind=="source":
            request="d"+key[:32]
            if evidence.exists(db,"joint25_source_requests"):
                old=db.execute("SELECT phase,receipt FROM joint25_source_requests WHERE id=?",(request,)).fetchone()
                if old and old[0]=="committed":
                    with db:status(db,key,"committed","恢复时按原来源批次找到已提交回执",after=current_head(),result=json.loads(old[1]))
                    continue
                if old and old[0]=="prepared":
                    try:
                        recovered=evidence.reconcile(db,request,r["scope"])
                        actual=db.execute("SELECT phase,receipt FROM joint25_source_requests WHERE id=?",(request,)).fetchone()
                        if actual and actual[0] in {"committed","partial","cancelled"}:
                            with db:status(db,key,actual[0],"按原生逐批回执对账，保留已发生的效果",after=current_head(),result=json.loads(actual[1]) if actual[1] else recovered)
                            continue
                    except (ValueError,RuntimeError,TimeoutError):pass
        elif r["native_review"]:
            old=db.execute("SELECT * FROM joint25_reviews WHERE pin=?",(r["native_review"],)).fetchone()
            if old and old["phase"]=="committed" and old["receipt"]:
                with db:status(db,key,"committed","恢复时按原申请找到已提交回执",after=current_head(),result=json.loads(old["receipt"]))
                continue
            if old and old["phase"]=="issued" and kind in {"answer","scope_install"}:
                try:
                    restored=agenda.port(db,c,"C4","answer_receipt" if kind=="answer" else "scope_receipt",{"entry":agenda.entry(old)})
                    if restored.get("status") in {"recorded","withdrawn"}:
                        with db:
                            db.execute("UPDATE joint25_reviews SET phase='committed',receipt=? WHERE pin=?",(packed(restored),old["pin"]))
                            status(db,key,"committed","按原生只读回执确认；没有再派发",after=current_head(),result=restored)
                        continue
                except (ValueError,RuntimeError):pass
        if r["phase"]=="issued":
            with db:status(db,key,"uncertain","写入意图已记录，结果尚待对账；没有再次派发")

def command(db,text,session,rid):
    op,_,arg=text.strip().rstrip("。！？?!").partition(" ")
    ops={"登记修复范围":"scope_install","提交冻结答卷":"answer","提交本地冻结答卷":"answer","撤回委托答卷":"withdraw",
         "撤回已提交答卷":"withdraw","执行规则改进":"repair","委托状态":"status","执行报告":"report","暂停委托":"pause","恢复委托":"resume"}
    if op not in ops:return None
    if db.in_transaction:raise ValueError("委托命令必须在宿主提交边界前派发")
    setup(db);agenda.setup(db);kind=ops[op]
    if kind in ("pause","resume"):
        with db:
            put(db,"enabled",int(kind=="resume"))
            action="已暂停新的委托工作，保留所有未决与回执。" if kind=="pause" else "本机有限委托已恢复。"
            key=queue(db,"control",session,rid,{"operation":kind,"request":rid},action)
            status(db,key,"committed",action,result={"enabled":kind=="resume"})
        return action
    if kind=="status":
        states=dict(db.execute("SELECT phase,count(*) FROM deleg25_jobs GROUP BY phase"))
        return ("委托执行已启用。" if enabled(db) else "委托执行已暂停。")+"当前只运行本机已绑定接口的内部问询、来源核验、冻结答卷与受限规则取舍。\n任务计数 "+packed(states)
    if kind=="report":
        if arg:
            if not AID.fullmatch(arg):return "格式：执行报告，或执行报告 任务编号。"
            row=job(db,arg)
            if not row or row["scope"] not in (session,"host"):return "本会话没有该委托任务。"
            return short(db,arg)
        rows=db.execute("SELECT id FROM deleg25_jobs WHERE scope IN (?, 'host') ORDER BY changed_ns DESC LIMIT 8",(session,)).fetchall()
        return "\n\n".join(short(db,r[0]) for r in rows) or "目前没有实际委托执行记录。"
    if kind=="scope_install":
        agenda._scope_spec(arg.strip());values={"tag":arg.strip()}
    elif kind=="answer":
        words=arg.split()
        if len(words)!=6 or not agenda.NAME.fullmatch(words[0]) or not agenda.NAME.fullmatch(words[2]) or not all(AID.fullmatch(words[i]) for i in (1,3,4,5)):
            return "格式：提交本地冻结答卷 题号 请求摘要 成员名 制品摘要 包摘要 快照摘要"
        values={"fields":words}
    elif kind=="withdraw":
        if not AID.fullmatch(arg):return "格式：撤回已提交答卷 原委托任务编号"
        values={"answer_job":arg}
    else:
        if not agenda.checked(db):return "联合认知槽未就绪，未派发规则改进。"
        values={"basis":current_head()}
    with db:key=queue(db,kind,session,rid,values,"用户已委托的本地操作："+op)
    _recover(db)
    if enabled(db):_execute(db,key)
    return short(db,key)+("\n执行报告 "+key)

def _repair_job(db):
    n,_=agenda._engines(ROOT)
    state=ROOT/"state/individual.pcgm";stat=state.stat();file_tag=f"{stat.st_mtime_ns}/{stat.st_size}"
    if get(db,"seen_native")==file_tag:return None
    snap=n.snapshot(n.exe(ROOT/"releases/joint25/bin","alpha"),state)
    data={"rules_and_observations":pin([snap["source"],snap["inactive"]])}
    with db:put(db,"seen_native",file_tag)
    if not re.search(r"(?m)^\s*@\s+",snap["source"]) or data["rules_and_observations"]==get(db,"seen_rules"):return None
    with db:
        put(db,"seen_rules",data["rules_and_observations"])
        return queue(db,"repair","host","native-change",data,"真实规则或观察版本变化，比较已有原生授权范围")
def pump(db):
    if db.in_transaction:return None
    import life3_worker as host
    if host.active("foreground"):return None
    setup(db);agenda.setup(db)
    if not enabled(db):return None
    opts=dict(db.execute("SELECT key,value FROM life3_meta WHERE key IN ('enabled','paused')"))
    if opts.get("enabled")!="1" or opts.get("paused")=="1":return None
    with agenda.available_writer(ROOT) as owned:
        if not owned or host.active("foreground") or not agenda.checked(db):return None
        from learning_governance25 import work as lexical_work
        lexical_event=lexical_work(db,ROOT)
        if lexical_event:return lexical_event
        # Polling is cheap after an unchanged observation; reconcile previously issued work by readback only.
        if time.time()-float(get(db,"last_recover","0"))>30:
            _recover(db)
            with db:put(db,"last_recover",time.time())
        queued=db.execute("SELECT id FROM deleg25_jobs WHERE phase='queued' ORDER BY created_ns LIMIT 1").fetchone()
        if not queued:
            key=_repair_job(db)
            queued=(key,) if key and job(db,key)["phase"]=="queued" else None
        if queued and not host.active("foreground") and _execute(db,queued[0]):
            r=job(db,queued[0])
            return {"kind":"delegated_"+r["kind"],"topic":"本机委托","summary":f"{r['kind']} · {r['phase']} · {r['reason']}",
                    "executed":r["phase"]=="committed","progress":r["phase"]=="committed","source":POLICY,"receipt":r["id"]}
    # The existing native agenda uses its own non-blocking lock and only enrolls a unique internal question.
    native=agenda.pump(db)
    if native and native.get("ticket"):
        with db:
            key=queue(db,"enroll","host","agenda",{"ticket":native["ticket"],"review":native.get("review_pin")},"真实原生议程识别唯一可询缺口")
            status(db,key,"committed","已登记内部票，未向外部发送",review=native.get("review_pin"),after=current_head(),result=native)
    return native

