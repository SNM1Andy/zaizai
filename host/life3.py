"""Persistent local life loop. Native CL supplies proofs and PCGM supplies its question feed."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import native as n
import inner3
import study3
import evolution3
import inquiry3
import round31
import slots31
import life_slots31 as boundary
import host_memory31

def stamp():return time.time()
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def meta(db,key,default=""):
    row=db.execute("SELECT value FROM life3_meta WHERE key=?",(key,)).fetchone()
    return row[0] if row else default
def put(db,key,value):
    db.execute("INSERT INTO life3_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))
def setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS life3_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS life3_events(id TEXT PRIMARY KEY,kind TEXT NOT NULL,topic TEXT NOT NULL,summary TEXT NOT NULL,created REAL NOT NULL,detail TEXT NOT NULL,integrated INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS life3_pending ON life3_events(integrated,created);
    CREATE INDEX IF NOT EXISTS life3_by_lane ON life3_events(json_extract(detail,'$.executed_lane'),created DESC);
    CREATE TABLE IF NOT EXISTS life3_notices(id TEXT PRIMARY KEY,session TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,delivered REAL);
    CREATE TABLE IF NOT EXISTS life3_questions(id TEXT PRIMARY KEY,scope TEXT,state TEXT,packet TEXT,created REAL,touched REAL);
    CREATE TABLE IF NOT EXISTS life3_flows(topic TEXT PRIMARY KEY,activation REAL NOT NULL,status TEXT NOT NULL,last_run REAL NOT NULL,certainty INTEGER NOT NULL,examined INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS life3_origin(topic TEXT,origin TEXT,polarity TEXT,proof TEXT,active INTEGER NOT NULL,PRIMARY KEY(topic,origin,polarity));
    CREATE TABLE IF NOT EXISTS life3_flow_basis(topic TEXT PRIMARY KEY,basis TEXT NOT NULL,proof TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS life3_links(parent TEXT,child TEXT,weight REAL NOT NULL,last_seen REAL NOT NULL,PRIMARY KEY(parent,child));
    CREATE TABLE IF NOT EXISTS life3_files(id TEXT PRIMARY KEY,source TEXT,sha256 TEXT,bytes INTEGER,created REAL,excerpt TEXT);
    """)
    with db:
        inner3.setup(db);study3.setup(db);evolution3.setup(db);inquiry3.setup(db);round31.setup(db);boundary.setup(db);host_memory31.setup(db)
        for k,v in {"identity":n.IDENTITY,"enabled":"1","paused":"0","dnd":"0","network":"1","mode":"起步"}.items():
            db.execute("INSERT OR IGNORE INTO life3_meta VALUES(?,?)",(k,v))
        if meta(db,"identity")!=n.IDENTITY:raise ValueError("生命账本与原生身份不符")

def notice(db,key,body,session="main"):
    db.execute("INSERT OR IGNORE INTO life3_notices VALUES(?,?,?,?,NULL)",(key,session,body,stamp()))
def visible_notices(db,session,deliver=False):
    if not deliver:
        return db.execute("SELECT id,body FROM life3_notices WHERE session=? AND delivered IS NOT NULL ORDER BY delivered DESC LIMIT 6",(session,)).fetchall()[::-1]
    if not boundary.pair_available(boundary.bindings(db)):return []
    if meta(db,"dnd")=="1" or inner3.current(db).get("relation",{}).get("availability")=="暂缓":return []
    now=stamp()
    sent,last=db.execute("SELECT count(*),max(delivered) FROM life3_notices WHERE delivered>?",(now-86400,)).fetchone()
    if sent>=3 or (last and last>now-1800):return []
    return db.execute("SELECT id,body FROM life3_notices WHERE session=? AND delivered IS NULL ORDER BY created LIMIT 1",(session,)).fetchall()
def delivered(db,key):
    db.execute("UPDATE life3_notices SET delivered=coalesce(delivered,?) WHERE id=?",(stamp(),key))

def question(db,key,topic,kind,source,attempted,missing,session="main"):
    label={"value":"问用户","concept":"查教材或咨询语言顾问","evidence":"查观察和可重复实验","capability":"登记迭代需求"}.get(kind,"核对来源")
    route={"value":"user","concept":"advisor","evidence":"local","capability":"iteration"}.get(kind,"local")
    packet=dict(topic=topic,question=topic,kind=kind,route=route,route_label=label,source=source,attempted=attempted,
                attempts=[attempted],blocking=missing,changes_if="增加有来源的独立证据",answer_format="材料、适用条件与反例",hypothesis="证据尚不充分",
                confidence="未定",blocker=missing,change_condition="补充有来源的独立证据或反例",expected="来源、适用条件和可复核的实例")
    now=stamp()
    db.execute("INSERT OR IGNORE INTO life3_questions VALUES(?,?,'open',?,?,?)",(key,session,n.canonical(packet),now,now))
    if route=="user":notice(db,key,f"我在复核「{topic}」。{missing}。你希望我据什么判断？",session)
    return packet

def invalidate_flow(db,topic):
    db.execute("""WITH RECURSIVE affected(topic) AS (SELECT ? UNION SELECT l.child FROM life3_links l JOIN affected a ON l.parent=a.topic)
        UPDATE life3_flows SET activation=1,examined=0 WHERE topic IN (SELECT topic FROM affected)""",(topic,))

def is_cyclic(db,start,target):
    return bool(db.execute("""WITH RECURSIVE reachable(topic) AS (SELECT ? UNION SELECT l.child FROM life3_links l JOIN reachable r ON l.parent=r.topic)
        SELECT 1 FROM reachable WHERE topic=? LIMIT 1""",(start,target)).fetchone())

def flow_event(db,event):
    topic=str(event["topic"]);source=str(event.get("source") or "")
    status=event.get("status","UNKNOWN");proof=event.get("proof");now=stamp()
    db.execute("INSERT OR IGNORE INTO life3_flows VALUES(?,0,'UNKNOWN',0,0,0)",(topic,))
    if proof and "origins" in event:
        before={tuple(x) for x in db.execute("SELECT origin,polarity,proof FROM life3_origin WHERE topic=? AND active=1",(topic,))}
        now_active={(o["family"],"POSITIVE" if o["sign"]>0 else "NEGATIVE") for o in event["origins"]}
        db.execute("UPDATE life3_origin SET active=0 WHERE topic=?",(topic,))
        for origin,side in now_active:
            db.execute("INSERT OR REPLACE INTO life3_origin VALUES(?,?,?,?,1)",(topic,origin,side,str(proof)))
        if before!={(o,s,str(proof)) for o,s in now_active}:invalidate_flow(db,topic)
    elif (event.get("withdrawn") or event.get("retracted")) and source:
        db.execute("UPDATE life3_origin SET active=0 WHERE topic=? AND origin=?",(topic,source))
        invalidate_flow(db,topic)
    elif source and proof and status in {"POSITIVE","NEGATIVE","CONFLICT"}:
        signs=("POSITIVE","NEGATIVE") if status=="CONFLICT" else (status,)
        for sign in signs:
            p=proof if isinstance(proof,str) else n.canonical(proof)
            changed=db.execute("""INSERT INTO life3_origin VALUES(?,?,?,?,1) ON CONFLICT(topic,origin,polarity)
                DO UPDATE SET active=1,proof=excluded.proof WHERE active=0 OR proof!=excluded.proof""",(topic,source,sign,p)).rowcount
            if changed:invalidate_flow(db,topic)
    for parent in event.get("dependencies") or ():
        if topic.startswith("card:") and ":" not in str(parent):parent="card:"+str(parent)
        if parent and parent!=topic:
            if db.execute("INSERT OR IGNORE INTO life3_links VALUES(?,?,0,?)",(str(parent),topic,now)).rowcount:
                invalidate_flow(db,topic)

def reasoning_step(db):
    candidates=db.execute("SELECT * FROM life3_flows WHERE examined=0 AND last_run<? ORDER BY activation DESC,last_run,topic",(stamp()-1,)).fetchall()
    for r in candidates:
        waiting=db.execute("SELECT l.parent FROM life3_links l JOIN life3_flows f ON f.topic=l.parent WHERE l.child=? AND f.examined=0",(r["topic"],)).fetchall()
        if all(is_cyclic(db,r["topic"],x[0]) for x in waiting):break
    else:return None
    topic=r["topic"]
    entries=db.execute("SELECT * FROM life3_origin WHERE topic=? AND active=1 ORDER BY origin,polarity",(topic,)).fetchall()
    parents=db.execute("""SELECT l.parent,f.status,f.examined,b.basis FROM life3_links l LEFT JOIN life3_flows f ON f.topic=l.parent
        LEFT JOIN life3_flow_basis b ON b.topic=l.parent WHERE child=? ORDER BY l.parent""",(topic,)).fetchall()
    parent_pins=[]
    conditions=["pos($t,$s)"]
    lines=[": pos(sym,sym).",": neg(sym,sym).",": supported(sym).","!supported($t) <- neg($t,$s)."]
    for i,parent in enumerate(parents):
        pred=f"premise_{i}"
        lines.append(f": {pred}(sym).");conditions.append(pred+"($t)")
        cycle=is_cyclic(db,topic,parent["parent"])
        parent_pins.append((parent["parent"],"cycle" if cycle else parent["basis"]))
        if not cycle and parent["examined"]==1 and parent["status"]=="POSITIVE":lines.append(f"& p{i} {pred}(t).")
    lines.append("supported($t) <- "+" & ".join(conditions)+".")
    for i,row in enumerate(entries):
        lines.append(f"& e{i} {'pos' if row['polarity']=='POSITIVE' else 'neg'}(t,s{digest(row['origin'])[:20]}).")
    source="\n".join(lines+["? supported(t).",""])
    envelope=boundary.port_call(db,"L2",{"source":source})
    result=envelope["output"]
    status=result["proof"]["results"][0]["status"];origins={x["origin"] for x in entries}
    pinned=digest(n.canonical([[(x["origin"],x["polarity"],x["proof"]) for x in entries],parent_pins]))
    prior=db.execute("SELECT basis FROM life3_flow_basis WHERE topic=?",(topic,)).fetchone()
    changed=not prior or prior[0]!=pinned or status!=r["status"]
    db.execute("INSERT OR REPLACE INTO life3_flow_basis VALUES(?,?,?)",(topic,pinned,result["source_sha256"]))
    db.execute("UPDATE life3_flows SET examined=1,status=?,last_run=?,certainty=?,activation=0 WHERE topic=?",
               (status,stamp(),len(origins),topic))
    if changed:
        for link in db.execute("SELECT child,weight FROM life3_links WHERE parent=?",(topic,)).fetchall():
            distinct=db.execute("SELECT origin FROM life3_origin WHERE topic=? AND active=1",(link["child"],)).fetchall()
            independent=bool(origins and {x[0] for x in distinct}-origins)
            weight=min(1,link["weight"]*.9+(.3 if independent and status=="POSITIVE" else 0))
            db.execute("UPDATE life3_links SET weight=?,last_seen=? WHERE parent=? AND child=?",(weight,stamp(),topic,link["child"]))
            if not is_cyclic(db,link["child"],topic):
                db.execute("UPDATE life3_flows SET activation=?,examined=0 WHERE topic=?",(weight,link["child"]))
    if status=="CONFLICT":
        question(db,"conflict-"+digest(topic)[:18],topic,"evidence","已核验来源","分开检查支持与反证","需能区分两种解释的独立观察")
    return dict(kind="flow",topic=topic,summary=f"复核「{topic}」得到 {status}，独立来源 {len(origins)} 个。",progress=changed,status=status,
                sources=sorted(origins),basis=pinned,prerequisite_basis=parent_pins,cl_source=result["source_sha256"],proof=result["proof"],rule="host-source-projection-v1")

def consolidate(db):
    rows=db.execute("SELECT id,kind,topic,summary FROM life3_events WHERE integrated=0 AND kind!='integration' ORDER BY created LIMIT 12").fetchall()
    if not rows:return None
    ids=[r["id"] for r in rows]
    db.executemany("UPDATE life3_events SET integrated=1 WHERE id=?",[(i,) for i in ids])
    topics=list(dict.fromkeys(r["topic"] for r in rows))
    return dict(kind="integration",topic="经历整合",summary=f"整理 {len(rows)} 次经历，涉及 "+"、".join(topics[:4])+"。原始记录可按编号复核。",
                members=ids,topics=topics,progress=True)

def audit(db,identifier,event,channel="life",user_text=None,session="main",decision=None):
    if db.execute("SELECT 1 FROM life3_events WHERE id=?",(identifier,)).fetchone():return
    result=dict(event);result.setdefault("kind",channel);result.setdefault("topic","本地工作")
    result.setdefault("summary",result["kind"])
    if channel!="dialogue" and result["kind"]!="flow" and (
        result.get("proof") or result.get("origins") or result.get("retracted") or result.get("verified_claims")
    ):
        flow_event(db,result)
    bound=boundary.bindings(db)
    result["slot_bindings"]=bound
    text=user_text if user_text is not None else result["summary"]
    boundary.from_event(db,identifier,channel,text,result,session)
    actor=("用户" if result.get("source") in {"desktop","cli"} else "验收程序") if channel=="dialogue" else "宿主"
    host_memory31.observe(db,identifier,channel,text,result.get("source") or result.get("source_receipt") or "local-event:"+identifier,actor,result)
    acceptance=channel=="dialogue" and result.get("source") not in {"desktop","cli"}
    inner=inner3.record(db,identifier,"验收对话" if acceptance else channel,user_text if user_text is not None else result["summary"],result,
                        speaker=("验收程序" if acceptance else "用户") if channel=="dialogue" else "再再")
    result["inner"]=inner
    evolution3.observe(db,identifier,result["kind"],result)
    round31.write(db,identifier,channel,session,result,inner,decision)
    db.execute("INSERT INTO life3_events VALUES(?,?,?,?,?,?,?)",(identifier,result["kind"],str(result["topic"]),result["summary"],stamp(),
               n.canonical(result),int(result["kind"] in {"integration","selection_deferred"})))
    if result.get("verified_claims"):
        notice(db,"learn-"+digest(str(result["topic"])+str(result.get("source")))[:22],result["summary"])
    if result.get("gap") and channel=="dialogue" and boundary.pair_available(bound):
        question(db,"gap-"+identifier,result["gap"][:160],"concept","本地会话 "+identifier,"本地意图、词典及会话焦点","尚待澄清具体含义",session)

def dialogue_event(db,r,plan,answer):
    topic=plan.get("word") or ("原生问题" if plan.get("questions") else "本轮对话")
    event={"kind":"dialogue","topic":topic,"summary":"已提交会话回执 "+r["id"],"request":r["id"],"session":r["session"],
           "progress":not bool(plan.get("gap")),"gap":plan.get("gap"),"source":r["source"],"answer_digest":digest(answer),
           "elapsed_ms":max(0,(time.time_ns()-r["started"])/1_000_000)}
    event["frame_kind"]=plan.get("frame_kind") or plan.get("kind") or "legacy_reply"
    if plan.get("host_status") or event["frame_kind"] in {"host_data","slot_unavailable"}:
        event.update(host_status=True,executed=False,status="waiting" if event["frame_kind"]=="slot_unavailable" else "recorded",gap=None)
    if plan.get("proof"):
        proof=plan["proof"]
        if isinstance(proof,dict):event["proof_sha256"]=proof.get("source_sha256")
    audit(db,r["id"],event,"dialogue",r["question"],r["session"])

def question_feed_revision(db,b):
    row=db.execute("SELECT coalesce(max(seq),0) FROM requests WHERE phase='committed'").fetchone()
    return boundary.pin([b["C"]["id"],b["C"]["version"],b["C"]["revision"],row[0]])

def native_agenda(db):
    before=question_feed_revision(db,boundary.bindings(db))
    if meta(db,"feed_seen")==before:return None
    receipt=boundary.port_call(db,"C4",{"operation":"feed","cursor":0,"limit":32})
    changed=[]
    for provider_question in receipt["output"]["questions"]:
        if "native" not in provider_question or receipt["adapter"] not in {"legacy-pcgm","joint25-pcgm"}:
            # A provider supplies a question, never an external dispatch policy.
            required=("id","goal","attempts","hypothesis","confidence","blocking","changes_if","answer_format")
            if not all(k in provider_question for k in required):continue
            address="slot-question-"+boundary.pin([receipt["adapter"],provider_question["id"]])[:24]
            prior=db.execute("SELECT packet FROM life3_questions WHERE id=?",(address,)).fetchone()
            topic=str(provider_question["goal"])[:200]
            details={**provider_question,"topic":topic,"question":topic,"route":"user","route_label":"等待宿主路由",
                     "source":"slot:"+receipt["adapter"],"blocker":str(provider_question["blocking"])[:600],
                     "slot_input_version":receipt["input_version"],"slot_sources":receipt["sources"]}
            encoded=n.canonical(details)
            if prior and prior[0]==encoded:continue
            db.execute("""INSERT INTO life3_questions VALUES(?,'main','open',?,?,?)
                ON CONFLICT(id) DO UPDATE SET packet=excluded.packet,state='open',touched=excluded.touched""",
                (address,encoded,stamp(),stamp()))
            changed.append(address)
            continue
        q=provider_question["native"]
        key="pcgm-"+q["id"];state=q["status"];pin=q["request_sha256"]
        old=db.execute("SELECT state,packet FROM life3_questions WHERE id=?",(key,)).fetchone()
        if old and old["state"]==state and json.loads(old["packet"]).get("request_sha256")==pin:continue
        atom=q.get("needed",{});topic=atom.get("predicate",q["id"]) if isinstance(atom,dict) else str(atom)
        details=question(db,key,topic,"evidence","PCGM "+q["id"],"读取同一身份的原生问题与当前证据","需要带来源、版本匹配的答复")
        details.update(native_id=q["id"],request_sha256=pin,evidence=q.get("evidence",[]),needed=atom)
        db.execute("UPDATE life3_questions SET state=?,packet=?,touched=? WHERE id=?",(state,n.canonical(details),stamp(),key))
        changed.append(key)
        if state=="open":notice(db,"ask-"+key+"-"+pin[:10],f"我在核对 {topic}，还缺一项有来源的答复。「问题」可查看题号和版本。")
    put(db,"feed_seen",before)
    return dict(kind="native_question",topic="认知槽问询",summary=f"从 {receipt['adapter']} 的 C4 端口更新了 {len(changed)} 个问题。",progress=True,questions=changed) if changed else None

def queue_work(db,session,text):
    if not text:return "请在「交办」后写希望调查的议题。"
    key="user-"+digest(session+"\n"+text)[:24]
    question(db,key,text,"value" if any(w in text for w in ("价值","偏好","应该")) else "evidence","用户交办","已登记来源和上下文","需要可复核的材料或例子",session)
    db.execute("INSERT OR IGNORE INTO life3_flows VALUES(?,1,'UNKNOWN',0,0,0)",(text,))
    return "已登记议题 "+key+"。可用「问询」查看缺口和依据。"

def monitor(db):
    row=db.execute("SELECT kind,summary,created FROM life3_events WHERE kind NOT IN ('dialogue','integration') ORDER BY created DESC LIMIT 1").fetchone()
    b=boundary.bindings(db)
    available=boundary.pair_available(b)
    mode="暂停" if meta(db,"paused")=="1" else meta(db,"mode","待启动") if available else "宿主等待槽"
    return {"mode":mode,"slots":b,"waiting_for_slots":not available,"heartbeat":meta(db,"heartbeat","0"),
            "worker":meta(db,"pid","0"),"latest":row["summary"] if row else "等待首次工作","when":row["created"] if row else None}
def command(db,text,session,rid):
    q=text.strip().rstrip("。！？?!")
    import delegated25
    delegated=delegated25.command(db,text,session,rid)
    if delegated is not None:return delegated
    if q=="运行账户":
        from windows_identity25 import compare
        import os
        token=compare(os.getpid())
        return ("宿主与当前桌面用户的 Windows 账号、会话、完整性及提升状态一致。" if token["same_account_integrity_elevation_session"] else "当前进程与桌面令牌有差异。")+" 完整性 "+token["application"]["integrity_sid"]+"。"
    import lexref25_host
    lexical_ref=lexref25_host.command(db,text,session,rid)
    if lexical_ref is not None:return lexical_ref
    import release25_lexicon
    import joint25_evidence
    guarded=joint25_evidence.guard_command(db,text,session)
    if guarded is not None:return guarded
    result25=release25_lexicon.command(db,text,session,rid)
    if result25 is not None:return result25
    if q.startswith(("核准来源 ","来源投影 ","对账来源 ")):
        import joint25_evidence
        return joint25_evidence.command(db,text,session,rid)
    if q.partition(" ")[0] in {"原生议程","复核改进","复核原生答卷","复核答卷","复核撤回","原生申请","原生申请回执","批准内部问询","批准规则方案","批准原生答卷","批准撤回观察","复核修复范围","批准修复范围"}:
        import joint25_agenda_host
        return joint25_agenda_host.command(db,text,session,rid)
    import source_provenance25
    admission=source_provenance25.command(db,text,session)
    if admission is not None:
        delegated25.source_change(db,text,session,rid)
        return admission
    import field31_status
    if q in {"原生几何状态","几何接入"}:
        cognition=boundary.bindings(db)["C"]
        if cognition["id"]!="legacy-pcgm" or not boundary.supports(cognition,"C9"):
            ref=db.execute("SELECT initialized_event,module_sha256 FROM round31_native_reference ORDER BY bound_ns DESC LIMIT 1").fetchone()
            return ("旧几何安装回执："+ref["initialized_event"]+"，模块 "+ref["module_sha256"]+"。" if ref else "没有封存的安装凭据。")+"当前没有启用原生几何适配器，未采集本轮读数。"
    field=field31_status.command(db,text)
    if field is not None:return field
    evidence=round31.command(db,text,session)
    if evidence is not None:return evidence
    if q in {"观察队列","宿主观察","观察帧"}:return boundary.queue_summary(db,session)
    if q.startswith("学习应用 ") and not boundary.supports(boundary.bindings(db)["L"],"L2"):
        return "当前语言槽未提供核验。既有课程记录和掌握度可查，本次应用题尚未作答。"
    if q.startswith("观察帧 "):
        row=db.execute("SELECT * FROM life31_frames WHERE id=?",(q[4:].strip(),)).fetchone()
        if not row or (row["channel"] in {"dialogue","file"} and row["context"]!=session):return "当前会话没有可读的该观察帧。"
        return f"{row['id']} · {row['category']} · {row['stage']}\n来源 {row['source']} · {row['speaker']}\n版本 {row['revision']} · SHA256 {row['content_hash']}"
    if q=="内在状态" and not boundary.legacy_pair(boundary.bindings(db)):
        historic=inner3.command(db,text)
        return (historic or "")+"\n以上为宿主 R28 观察。当前没有经本轮 C6 槽确认的预测误差、未决权重和预期信息增益，这三项记为缺测。"
    if q in {"生命状态","你在学什么","你刚才在想什么","我想看你的生命状态","你在想什么"}:
        m=monitor(db)
        if m["waiting_for_slots"]:return "宿主继续接收和保存观察。语言/认知槽未就绪，认知与学习队列等待。"+boundary.queue_summary(db)
        return f"当前模式：{m['mode']}。最近一次实际工作：{m['latest']}。"
    if q in {"生命记录","学习日志","最近的经历"}:
        rows=db.execute("SELECT summary FROM life3_events WHERE kind!='dialogue' ORDER BY created DESC LIMIT 6").fetchall()
        return "\n".join(x[0] for x in rows) or "还没有已提交的工作步。"
    if q in {"主动消息","问询","你有什么问题"}:
        rows=db.execute("SELECT id,state,packet FROM life3_questions ORDER BY touched DESC LIMIT 8").fetchall()
        return "\n".join(f"{x['id']} · {x['state']} · {json.loads(x['packet']).get('topic',json.loads(x['packet']).get('question',''))} · {json.loads(x['packet'])['route']} · {json.loads(x['packet']).get('blocker',json.loads(x['packet']).get('blocking',''))}" for x in rows) or "目前没有登记的本地问询。"
    if q.startswith("交办 "):return queue_work(db,session,q[3:].strip()[:200])
    if q in {"观察世界","观察本地世界"}:
        v=n.legacy_memory.overview()
        boundary.record_frame(db,"world:"+rid,v,source="R28:world/joint.json",at=stamp(),channel="world",
                              speaker="本地世界读取器",category="observed",revision=digest(n.canonical(v)))
        return f"原状态第 {v['generation']} 代，tick {v['tick']}，观察对象 "+"、".join(v["observed"])+f"，共 {v['events']} 个已存事件。"
    if q.startswith("观察文件 "):
        p=Path(q[5:].strip().strip('"')).resolve(strict=True)
        if not p.is_file() or p.stat().st_size>4*1024*1024:raise ValueError("本次可观察单个 4 MiB 以内的本地文件")
        raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        sample=raw[:400].decode("utf8","replace") if b"\0" not in raw[:400] else ""
        db.execute("INSERT OR IGNORE INTO life3_files VALUES(?,?,?,?,?,?)",(rid,str(p),sha,len(raw),stamp(),sample))
        boundary.record_frame(db,"file:"+rid,{"name":p.name,"bytes":len(raw),"sha256":sha},source=str(p),at=stamp(),
                              channel="file",speaker="用户授权的本机读取",category="observed",revision=sha,context=session)
        return f"已观察 {p.name}，{len(raw)} 字节，来源摘要 {sha}。"
    if q=="关闭后台":
        put(db,"enabled","0");return "当前工作到达边界后将退出后台。输入「继续生命循环」可重新启动。"
    if q=="继续生命循环":put(db,"enabled","1")
    switches={"暂停生命循环":("paused","1"),"继续生命循环":("paused","0"),"开启勿扰":("dnd","1"),"关闭勿扰":("dnd","0"),
              "暂停网络捕捞":("network","0"),"恢复网络捕捞":("network","1")}
    if q in switches:
        k,v=switches[q];put(db,k,v);return q+"，设置已保存。"
    for module in (inner3,study3,evolution3,inquiry3):
        reply=module.command(db,text)
        if reply is not None:return reply
    return None
