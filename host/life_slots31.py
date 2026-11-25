"""Host-owned observation queue, budget and selection at the L/C boundary."""
import hashlib
import json
import math
import time

import evolution3
import inner3
import round31
import slots31

LANES = {"study":("learning",2), "flow":("reasoning",2), "integration":("storage",1), "native":("questions",1)}
WORK_MS = 1200
WORK_UNITS = 4

def packed(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)

def pin(obj):return hashlib.sha256(packed(obj).encode()).hexdigest()

def setup(db):
    slots31.setup(db)
    db.execute("""CREATE TABLE IF NOT EXISTS life31_frames(
        id TEXT PRIMARY KEY, content TEXT NOT NULL, content_hash TEXT NOT NULL, at REAL NOT NULL,
        channel TEXT NOT NULL, speaker TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL,
        family TEXT NOT NULL, revision TEXT NOT NULL, context TEXT NOT NULL, stage TEXT NOT NULL,
        evidence TEXT NOT NULL, contradicts TEXT NOT NULL, derived TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS life31_ack(
        frame TEXT NOT NULL, consumer TEXT NOT NULL, receipt TEXT NOT NULL, at REAL NOT NULL,
        PRIMARY KEY(frame,consumer))""")
    db.execute("CREATE INDEX IF NOT EXISTS life31_frame_lineage ON life31_frames(channel,context)")
    db.execute("""CREATE TABLE IF NOT EXISTS life31_index(
        kind TEXT NOT NULL, item TEXT NOT NULL, revision TEXT NOT NULL,
        PRIMARY KEY(kind,item))""")
    db.execute("""CREATE TABLE IF NOT EXISTS life31_proof(
        ref TEXT PRIMARY KEY, slot_version TEXT NOT NULL, batch TEXT NOT NULL, version TEXT NOT NULL,
        lane TEXT NOT NULL, status TEXT NOT NULL, sources TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS life31_wait(
        singleton INTEGER PRIMARY KEY, reason TEXT NOT NULL, changed REAL NOT NULL, state_key TEXT NOT NULL)""")

def bindings(db):
    snap=slots31.snapshot(db)
    return {k:{f:snap[k].get(f) for f in ("id","version","state","revision","manifest_sha256","interface_version","state_format","capabilities","value_domain","formats")}
            for k in ("L","C")}

def supports(side,port):
    return side.get("state")=="ready" and port in (side.get("capabilities") or ())

def pair_available(b):
    return all(supports(b["L"],p) for p in ("L2",)) and all(supports(b["C"],p) for p in ("C3","C5"))

def legacy_pair(b):
    return (b["L"]["id"],b["C"]["id"]) in {("legacy-cl","legacy-pcgm"),("joint25-cl","joint25-pcgm")} and pair_available(b)

def record_frame(db,identifier,content,*,source,at,channel,speaker,category,revision,stage="observed",family=None,context="local",
                 evidence=(),contradicts=(),derived=()):
    text=content if isinstance(content,str) else packed(content)
    digest=hashlib.sha256(text.encode()).hexdigest()
    revision=str(revision)
    previous=db.execute("SELECT content_hash,source,revision FROM life31_frames WHERE id=?",(identifier,)).fetchone()
    if previous:
        if tuple(previous)!=(digest,source,revision):raise ValueError("观察帧重复编号携带不同来源或内容")
        return
    db.execute("INSERT INTO life31_frames VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (identifier,text,digest,at,channel,speaker,category,source,family or source,revision,context,stage,
                packed(evidence),packed(contradicts),packed(derived)))

def from_event(db,identifier,channel,text,result,session):
    if channel=="dialogue":
        source="local-request:"+identifier
        speaker="用户" if result.get("source") in {"desktop","cli"} else "验收程序"
        category="teacher" if inner3.teaching_observation(text) else "statement"
        family=f"{speaker}:{session}:"+pin(text)
    else:
        source=str(result.get("source") or result.get("source_receipt") or "local-event:"+identifier)
        speaker="宿主" if not result.get("advisor") else "顾问"
        category="external_claim" if result["kind"]=="fetch" else "host_event"
        family=source
    record_frame(db,"event:"+identifier,text,source=source,at=time.time(),channel=channel,speaker=speaker,
                 category=category,revision=result.get("proof_sha256") or identifier,family=family,context=session,
                 stage="quarantine" if result["kind"] in {"fetch","discovery","source_review"} else "observed",
                 evidence=[result["proof_sha256"]] if result.get("proof_sha256") else (),
                 derived=result.get("members") or ())

def index_materials(db,limit=12):
    """Register source material without changing mastery or the prior evidence disposition."""
    cards=db.execute("""SELECT c.* FROM study3_card c LEFT JOIN life31_index i ON i.kind='course' AND i.item=c.id
        WHERE i.revision IS NOT c.version ORDER BY c.id LIMIT ?""",(limit,)).fetchall()
    added=0
    for c in cards:
        body={"card":c["id"],"title":c["title"],"claim":c["body"],"locator":c["locator"]}
        key="card:"+pin([c["id"],c["version"]])
        record_frame(db,key,body,source=c["source"],at=time.time(),channel="textbook",speaker="教材",
                     category="external_claim",revision=c["version"],family=c["source"],context=c["id"],stage="source_claim")
        db.execute("INSERT OR REPLACE INTO life31_index VALUES('course',?,?)",(c["id"],c["version"]))
        added+=1
    observations=db.execute("""SELECT o.*,s.family,s.version,s.uri,s.active,s.seen,
        o.stage||':'||CAST(s.active AS TEXT) current_stage FROM study3_observation o JOIN study3_source s ON s.id=o.source_id
        LEFT JOIN life31_index i ON i.kind='intake' AND i.item=o.id
        WHERE i.revision IS NOT (o.stage||':'||CAST(s.active AS TEXT)) ORDER BY o.rowid LIMIT ?""",(limit,)).fetchall()
    for o in observations:
        key="intake:"+pin([o["id"],o["current_stage"]])
        stage="withdrawn" if not o["active"] else "observed" if o["stage"]=="evidence" else "quarantine"
        record_frame(db,key,{"claim":o["claim"],"signed":o["sign"],"locator":o["locator"],"disposition":o["stage"]},
                     source=o["uri"],at=o["seen"],channel="intake",speaker="来源登记",category="external_claim",
                     revision=o["version"],family=o["family"],context=o["id"],stage=stage,evidence=[o["source_id"]])
        db.execute("INSERT OR REPLACE INTO life31_index VALUES('intake',?,?)",(o["id"],o["current_stage"]))
        added+=1
    return added

class PortDeclined(Exception):
    """A valid provider can decline work while remaining available."""

def port_call(db,port,payload,*,version=None,budget_ms=WORK_MS):
    frame=slots31.dispatch(db,port,payload,input_version=version,timeout_ms=max(1,int(budget_ms)))
    if frame["output"].get("refused"):raise PortDeclined(f"{port}：{frame['output']['reason']}")
    return frame

def unacked(db,b):
    consumer=pin([b["C"]["id"],b["C"]["version"],b["C"].get("manifest_sha256"),b["C"].get("state_format")])
    row=db.execute("""SELECT f.* FROM life31_frames f LEFT JOIN life31_ack a ON a.frame=f.id AND a.consumer=?
        WHERE a.frame IS NULL AND f.stage!='quarantine' AND f.category!='host_event'
        AND (f.channel NOT IN ('textbook','intake') OR NOT EXISTS
            (SELECT 1 FROM life31_frames newer WHERE newer.channel=f.channel AND newer.context=f.context AND newer.rowid>f.rowid))
        ORDER BY CASE WHEN f.stage='withdrawn' THEN 0 WHEN f.channel='dialogue' THEN 1 ELSE 2 END,f.at,f.id LIMIT 1""",(consumer,)).fetchone()
    return row,consumer

def deliver_frame(db,b,elapsed_budget):
    if not supports(b["C"],"C1"):return False
    frame,consumer=unacked(db,b)
    if not frame:return False
    packet={k:frame[k] for k in ("id","source","at","speaker","channel","content","revision","category","content_hash","context","family","stage")}
    for k in ("evidence","contradicts","derived"):packet[k]=json.loads(frame[k])
    version=pin(packet)
    answer=port_call(db,"C1",packet,version=version,budget_ms=elapsed_budget)
    output=answer["output"]
    if not output.get("accepted") or output.get("id")!=frame["id"]:raise ValueError("认知槽未确认对应的观察编号")
    db.execute("INSERT OR IGNORE INTO life31_ack VALUES(?,?,?,?)",(frame["id"],consumer,packed(answer),time.time()))
    return True

def wait_reason(db,reason,state_key):
    current=db.execute("SELECT reason,state_key FROM life31_wait WHERE singleton=1").fetchone()
    if not current or tuple(current)!=(reason,state_key):
        db.execute("INSERT OR REPLACE INTO life31_wait VALUES(1,?,?,?)",(reason,time.time(),state_key))
    return reason

def queue_summary(db,session=None):
    n=db.execute("SELECT count(*) FROM life31_frames").fetchone()[0]
    counts=dict(db.execute("SELECT stage,count(*) FROM life31_frames GROUP BY stage").fetchall())
    b=bindings(db)["C"]
    status="等待认知槽确认" if not supports(b,"C1") else "可向当前认知槽提交"
    text=f"宿主已保存 {n} 个带来源的观察帧，候选隔离区 {counts.get('quarantine',0)} 个；可交付的材料{status}。"
    if session is not None:
        rows=db.execute("""SELECT id,channel,stage FROM life31_frames WHERE channel NOT IN ('dialogue','file') OR context=?
            ORDER BY rowid DESC LIMIT 4""",(session,))
        text+="\n"+"\n".join(f"{r[0]} · {r[1]} · {r[2]}" for r in rows)
    return text

def remaining(deadline,preempt):
    if preempt():raise InterruptedError("对话抢占")
    ms=int((deadline-time.monotonic())*1000)
    if ms<1:raise TimeoutError("后台预算耗尽")
    return ms

def eligibility(db,offers,version,b,quota):
    reply=port_call(db,"L2",{"operation":"offer_eligibility","offers":list(offers.values()),
        "sources":["host:available-work/"+version]},version=version,budget_ms=quota)
    proof=reply["output"];results=proof.get("results") or proof["proof"]["results"]
    records={}
    for row in results:
        lane=row.get("subject")
        if lane not in offers or lane in records:raise slots31.SlotUnavailable("L","invalid","L2资格查询的目标不符")
        ref=pin([pin(b["L"]),version,proof["proof_ref"],lane,row["status"],reply["sources"]])
        record={"ref":ref,"status":row["status"],"input_version":version}
        db.execute("INSERT OR IGNORE INTO life31_proof VALUES(?,?,?,?,?,?,?)",
                   (ref,pin(b["L"]),proof["proof_ref"],version,lane,row["status"],packed(reply["sources"])))
        records[lane]=record
    if set(records)!=set(offers):raise slots31.SlotUnavailable("L","invalid","L2缺少本批候选的资格结果")
    return records

RETRY_WINDOW_SECONDS=300

def retry_load(db,names,now):
    """Use the same last sixteen assigned results, expiring failed attempts after five minutes."""
    rows=db.execute("""SELECT e.lane,e.progress,e.failed,e.created FROM evo3_events e JOIN evo3_assignments a
        ON a.event_id=e.event_id AND e.lane=a.chosen ORDER BY e.seq DESC LIMIT 16""")
    stamps={k:[] for k in names};done=set()
    for lane,gain,failed,when in rows:
        if lane not in stamps or lane in done or when+RETRY_WINDOW_SECONDS<=now:continue
        if gain>0 and not failed:done.add(lane)
        else:stamps[lane].append(when)
    return stamps

def select(db,identifier,b,offers,evidence,candidates,units,inputs,evaluations):
    """Admit by capability, proof and quota, then score the admitted set of each policy arm."""
    state=inner3.current(db);previous=inputs["previous_lane"];scores={};used=set();valid={}
    def reject(reason,c=None):
        return {"eligible":False,"reason":reason,"proof_ref":(c or {}).get("proof_ref"),"base_score":None,"components":None,"final_score":None}
    for c in candidates:
        name=c.get("id")
        if not isinstance(name,str) or not name or name in used:raise slots31.SlotUnavailable("C","invalid","C3 候选编号错误或重复")
        used.add(name); offer=offers.get(name);ref=evidence.get(name)
        raw=c.get("base_score");cost=c.get("cost");why=""
        if offer is None:why="宿主不提供该通道"
        elif not offer["available"]:why="宿主队列没有到期工作"
        elif c.get("permission",offer["permission"])!=offer["permission"]:why="不具备该权限"
        elif not isinstance(cost,int) or isinstance(cost,bool) or cost<offer["cost"] or cost>units:why="成本未申报或超出宿主预算"
        elif not ref or c.get("proof_ref")!=ref["ref"]:why="缺少同输入版本的 L2 资格证明"
        elif not db.execute("""SELECT 1 FROM life31_proof WHERE ref=? AND lane=? AND status=? AND version=? AND slot_version=?""",
                            (ref["ref"],name,ref["status"],inputs["eligibility_version"],pin(b["L"]))).fetchone():
            why="资格回执的来源、版本或目标与当前工作不符"
        elif ref["status"]!=(b["L"]["value_domain"] or {}).get("support"):why="L2 未给出单向支持"
        elif not isinstance(raw,(int,float)) or isinstance(raw,bool) or not math.isfinite(raw):why="认知基础分无效"
        if why:scores[name]=reject(why,c)
        else:valid[name]=c
    for name in offers:
        if name not in used:scores[name]=reject("认知槽未提出此候选")
    if not valid:return None,{"candidates":scores,"reason":"没有满足宿主约束的候选"}

    now=time.time();base=evolution3.policy(db);revision=base["revision"]
    stamps=retry_load(db,valid,now);pressure={n:len(times) for n,times in stamps.items()}
    reference={name for name in valid if pressure[name]<base["retry_limit"]}
    trial=db.execute("""SELECT d.id,p.id,p.retry_limit FROM evo3_demands d JOIN evo3_policies p ON p.id=d.candidate
                        WHERE d.phase='canary' AND d.base=?""",(revision,)).fetchone()
    alternate={name for name in valid if pressure[name]<trial[2]} if trial else set()
    if not reference:
        for n,c in valid.items():scores[n]=reject("本轮重试额度已用完",c)
        refill=min(sorted(stamps[n])[len(stamps[n])-base["retry_limit"]]+RETRY_WINDOW_SECONDS for n in valid)
        return None,{"candidates":scores,"reason":"全部候选的重试额度已用完","wake_at":refill,
                     "retry_limit":base["retry_limit"],"pressure":pressure,"rule":"waiting-for-attempt-expiry"}

    # Reference and canary are evaluated at the same input. Each may only score its own admitted lanes.
    # Caching shared contributions avoids evaluating any lane twice. Hypothetical scores are never
    # assigned to a real excluded lane in the published decision.
    computed={}
    def score(name):
        if name not in computed:
            c=valid[name];novelty=float(name!=previous);switching=float(bool(previous) and name!=previous)
            mode="review" if name=="integration" else "explore"
            field=inner3.components(inner3.seed(),state,name,novelty,switching,mode)["field"]
            contribution=inner3.clipped(field,-.1,.1)
            computed[name]={"eligible":True,"reason":"宿主权限、证明、工作预算及重试额度均通过","proof_ref":c["proof_ref"],
                            "cost":c["cost"],"base_score":float(c["base_score"]),"final_score":float(c["base_score"])+contribution,
                            "components":{"field":field,"emotion":None},"bounded_adjustment":contribution,
                            "geometry_channel":"persistence" if mode=="review" else "switching" if switching else "exploration"}
        return computed[name]
    def ordered(admitted):
        return sorted(admitted,key=lambda lane:(-score(lane)["final_score"],lane))
    reference_order=ordered(reference);candidate_order=ordered(alternate)
    primary=reference_order[0];other=candidate_order[0] if candidate_order else None
    actual=reference_order;arm="active";selected_limit=base["retry_limit"]
    if trial:
        arm="unchanged" if other==primary else "reference" if other else "no_canary_candidates"
        if other and other!=primary:
            paired=db.execute("SELECT count(*) FROM evo3_assignments WHERE trial=? AND base_choice!=candidate_choice",(trial[0],)).fetchone()[0]
            if paired%4==0 and evolution3.gate_status()[0]:
                arm="canary";revision=trial[1];selected_limit=trial[2];actual=candidate_order
    for name,c in valid.items():
        scores[name]=computed[name] if name in actual else reject("本轮重试额度已用完",c)
    choice=actual[0]
    db.execute("INSERT INTO evo3_assignments VALUES(?,?,?,?,?,?,?,?,?,?)",
               (identifier,packed(reference_order),packed(pressure),choice,primary,other,revision,trial[0] if trial else None,arm,now))
    decision={"round_id":identifier,"phase":"比较前","decision_domain":"宿主选择点","state_used":round31.snapshot(state),
              "slot_bindings":b,"emotion_inputs":None,"c6":evaluations,"eligibility_inputs":inputs,"candidates":scores,"order":actual,
              "actual_choice":choice,"preference_first":choice,"eligibility_sha256":pin(evidence),
              "policy":{"revision":revision,"arm":arm,"trial":trial[0] if trial else None,"retry_limit":selected_limit,
                        "window_seconds":RETRY_WINDOW_SECONDS,"reference_admitted":sorted(reference),"canary_admitted":sorted(alternate),
                        "pressure":pressure,"base_choice":primary,"candidate_choice":other},
              "selection_reason":"按本轮权限、证明与资源配额过滤后的最高分"}
    return choice,decision
