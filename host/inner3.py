"""3.0 host continuity for actual R28 affect, controller, field and evidence-linked memory."""
from contextlib import contextmanager
import copy
from functools import lru_cache
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import threading
import time

import legacy_memory

ROOT = Path(__file__).resolve().parents[1]
R28 = ROOT/"state/native/offline-six-module-r28-20261120"
BUNDLE = R28/"r14/bundle"
KINDS = {"工作": "working", "情景": "episodic", "语义": "semantic", "程序": "procedural", "技能": "skill"}
TEACHING = {"教导": "instruction", "纠正": "correction", "更正": "correction",
            "价值判断": "value", "共情反馈": "empathy", "互动意愿": "availability"}
USER_CHANNELS = {"dialogue", "dialog", "chat", "desktop", "turn", "user", "教导", "对话"}
STATUSES = {"POSITIVE", "NEGATIVE", "UNKNOWN", "CONFLICT"}
HEX = re.compile(r"[0-9a-f]{64}\Z")

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def clipped(value, low, high):
    return max(low,min(value,high))

def seed():
    with _SEED_LOCK:
        return _load_seed()

_SEED_LOCK=threading.RLock()

@lru_cache(maxsize=1)
def _load_seed():
    """Load the pinned old decoder under a separate Python package name."""
    data, individual = legacy_memory.checkpoint()
    freeze = (BUNDLE/"FREEZE.json").read_bytes()
    pin = json.loads((R28/"parent-sources.json").read_bytes())["source_files"]["r14/bundle/FREEZE.json"]
    if digest(freeze) != pin:
        raise ValueError("原版运行库冻结清单摘要不符")
    for name, sha in json.loads(freeze)["files"].items():
        if name.startswith("lib/al01/") and digest((BUNDLE/name).read_bytes()) != sha:
            raise ValueError("原版模块摘要不符："+name)
    package = "_zaizai3_r28_al01"
    directory = BUNDLE/"lib/al01"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(package, directory/"__init__.py", submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        spec.loader.exec_module(module)
    def original(name):
        return importlib.import_module(package+"."+name)
    runtime = original("coupled_runtime").CoupledRuntime
    dev, ctl, neural = original("development"), original("control_embryos"), original("neural_control")
    _, solver, calibration = runtime._decode(data["core_joint"], multi_action=True)
    modules = data["modules"]
    development = modules["development"]
    dev.validate_development(development)
    targets = [{"entity_ref":name,"position":row["position"],"baseline_score":0.0}
               for name,row in sorted(individual["observed"].items())]
    u0 = neural.evaluate_u0(individual,targets,enabled=bool(modules["switches"]["ucm"])) if targets else None
    anchor = json.loads((ROOT/"state/imported.json").read_bytes())
    return {"id":individual["id"],"snapshot":anchor["checkpoint_sha256"],"freeze":pin,
            "modules":modules,"objects":individual["observed"],"solver":solver,"calibration":calibration,
            "dev":dev,"ctl":ctl,"neural":neural,"u0":u0}

def blob_of(field):
    return field.astype("<c16").tobytes()

def sample_field(solver, calibration):
    manifest = solver.manifest()
    return {"features":manifest["features"],"biases":calibration.biases(manifest["features"]),
            "time":manifest["time"],"steps":manifest["steps"],"stopped":solver.stopped,
            "stop_reason":solver.stop_reason,"geometry_hash":manifest["geometry_hash"],
            "source_event_head":manifest["source_event_head"],"calibration":calibration.calibration_id}

def memory(db,event,kind,key,value,source,status,when):
    db.execute("""INSERT INTO inner3_memory(event,kind,item_key,body,source,status,at_ns)
               VALUES(?,?,?,?,?,?,?)""",(event,kind,key,packed(value),source,status,when))

def setup(db):
    """Use caller's transaction and keep existing records and field intact on reopen."""
    db.execute("""CREATE TABLE IF NOT EXISTS inner3_state(
        id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL, body TEXT NOT NULL,
        field BLOB NOT NULL, field_hash TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS inner3_events(
        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, at_ns INTEGER NOT NULL, channel TEXT NOT NULL,
        speaker TEXT, topic TEXT NOT NULL, excerpt TEXT NOT NULL, outcome TEXT NOT NULL, sample TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS inner3_memory(
        event TEXT NOT NULL, kind TEXT NOT NULL, item_key TEXT NOT NULL, body TEXT NOT NULL,
        source TEXT NOT NULL, status TEXT NOT NULL, at_ns INTEGER NOT NULL,
        PRIMARY KEY(event,kind,item_key))""")
    db.execute("""CREATE TABLE IF NOT EXISTS inner3_teaching(
        event TEXT PRIMARY KEY, speaker TEXT NOT NULL, at_ns INTEGER NOT NULL, kind TEXT NOT NULL,
        body TEXT NOT NULL, disposition TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS inner3_mem_by_kind ON inner3_memory(kind,at_ns)")
    db.execute("CREATE INDEX IF NOT EXISTS inner3_events_by_topic ON inner3_events(topic,at_ns)")
    db.execute("CREATE INDEX IF NOT EXISTS inner3_events_recent ON inner3_events(at_ns)")
    db.execute("CREATE INDEX IF NOT EXISTS inner3_teaching_recent ON inner3_teaching(at_ns)")
    existing=db.execute("SELECT identity FROM inner3_state WHERE id=1").fetchone()
    b = seed()
    if existing:
        if existing[0]!=b["id"]:
            raise ValueError("内在状态与当前个体身份不符")
        return
    s = b["solver"]
    control = b["modules"]["control"]
    content = b["modules"]["development"]["content"]
    source = "r28:"+b["snapshot"]
    state = {"source":source,"identity":b["id"],"event":None,"sequence":0,"topic":"",
             "axes":content["axes"],"apply":b["modules"]["switches"],"ucm":control,
             "relation":{"target":None,"K":0.5,"known":False,"availability":None},
             "field":sample_field(s,b["calibration"]),"signal":0.0,"mode_hint":"explore","components":{}}
    raw = blob_of(s.field)
    state["field"]["state_sha256"]=digest(raw)
    cur = db.execute("INSERT OR IGNORE INTO inner3_state VALUES(1,?,?,?,?)",(b["id"],packed(state),raw,digest(raw)))
    if cur.rowcount == 0:
        return
    for kind in ("working","episodic","semantic","procedural","skill"):
        values = b["modules"]["skills"]["catalog"] if kind=="skill" else content[kind]
        pairs = values.items() if isinstance(values,dict) else enumerate(values)
        for key,item in pairs:
            code = item.get("status","recorded")
            if kind=="semantic" and "ref" in item:
                code = "recorded_observation"
            memory(db,source,kind,str(key),item,source,code,0)

def current(db):
    row = db.execute("SELECT body FROM inner3_state WHERE id=1").fetchone()
    if row is None:
        raise RuntimeError("3.0 内在状态尚未初始化")
    return json.loads(row[0])

def teaching(text):
    match = re.match(r"^\s*(价值判断|共情反馈|互动意愿|教导|更正|纠正)(?:\s*[:：]\s*|\s+)([\s\S]+?)\s*$",text)
    return (TEACHING[match[1]],match[2]) if match else None

def teaching_observation(text):
    marked=teaching(text)
    if marked:
        return marked
    patterns=(("correction",r"^(?:我纠正一下|你刚才说错了|我的意思是|我指的是)"),
              ("value",r"^(?:我更看重|我更希望|对我来说最重要的是|我希望你优先)"),
              ("empathy",r"^(?:我理解你的感受|我能理解你刚才|谢谢你刚才)"))
    for code,pattern in patterns:
        if re.match(pattern,text.strip()) and len(text.strip())>5:
            return code,text.strip()
    return None

def words(value):
    # Preserve named entities and documents in focus; keep each token within the frozen U0 ABI.
    parts = re.findall(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]{1,6}",value)
    return [p[:128] for p in parts[:32]] or ["当前事件"]

def resume_field(b,raw,state,expected_hash):
    import numpy as np
    if len(raw)!=64*64*16 or digest(raw)!=expected_hash:
        raise ValueError("3.0 几何场恢复摘要不符")
    s=copy.copy(b["solver"])
    s._field=np.frombuffer(raw,dtype="<c16").copy().reshape(64,64)
    s.time=state["field"]["time"]
    s.steps=state["field"]["steps"]
    s.stopped=state["field"]["stopped"]
    s.stop_reason=state["field"]["stop_reason"]
    if not s.stopped:
        # Keep the original physical drive and its causal event head: ordinary speech has no world coordinates.
        try:
            s.step()
        except ValueError:
            if not s.stopped:
                raise
    return s

def relation_for(b,tokens):
    dev = b["modules"]["development"]
    entries = dev["content"]["relationships"]
    target = next((name for name in tokens if name in entries),None)
    if target:
        v = b["dev"].relationship_value(dev,target)
        return {"target":target,"K":v,"known":True,"evidence":entries[target]["source_refs"][-1]["hash"]}
    return {"target":None,"K":0.5,"known":False}

def components(b,state,topic,novelty,switching,mode):
    tokens = words(topic)
    flags = state["apply"]
    dev = b["modules"]["development"]
    obj = next((s for s in tokens if s in b["objects"]),None)
    experience = b["dev"].score_adjustment(dev,b["objects"][obj]["position"]) if obj and flags["experience"] else 0.0
    emotion = b["dev"].emotion_adjustment(dev,novelty=novelty,switching=switching) if flags["emotion"] else 0.0
    related = relation_for(b,tokens)
    rel = .02*(related["K"]-.5) if related["known"] and flags["relation"] else 0.0
    # An explicit invitation/deferral is a separate user preference for a questioning candidate.
    if mode=="ask" and state["relation"].get("availability") in {"愿意","暂缓"}:
        rel += .02 if state["relation"]["availability"]=="愿意" else -.02
    u0 = 0.0
    if flags["ucm"]:
        previous = b["neural"].candidate_offset(b["u0"],obj) if obj and b["u0"] else 0.0
        u0 = .5*(previous+b["ctl"].candidate_offset(state["ucm"],{"tokens":tokens,"novelty":novelty}))
    field_mode = "persistence" if mode in {"review","consolidate","integrate"} else "switching" if switching else "exploration"
    field = b["calibration"].beta*state["field"]["biases"][field_mode] if not state["field"]["stopped"] else 0.0
    return {"experience":experience,"emotion":emotion,"relation":rel,"ucm":u0,"field":field}

def candidate_bias(db,topic,*,novelty=1.0,switching=0.0,mode="explore"):
    state=current(db)
    parts=components(seed(),state,str(topic),clipped(float(novelty),0.,1.),clipped(float(switching),0.,1.),mode)
    return clipped(sum(parts.values()),-.1,.1)

def verified_claims(db,event,info,when):
    items=info.get("verified_claims")
    if not isinstance(items,list):
        return
    for idx,item in enumerate(items[:32]):
        if not isinstance(item,dict) or item.get("transfer_passed") is not True:
            continue
        proof, source = item.get("proof_sha256"),item.get("source")
        status,claim = item.get("status"),item.get("claim")
        if not isinstance(proof,str) or not HEX.fullmatch(proof) or not source or not claim or status not in STATUSES:
            continue
        if learning_proof_status(db,proof)!="active":
            continue
        reference = source if isinstance(source,str) else packed(source)
        memory(db,event,"semantic",str(idx),{"claim":claim,"proof_sha256":proof},reference,status,when)
        if status=="POSITIVE":
            memory(db,event,"skill",str(idx),{"transfer":claim,"proof_sha256":proof},reference,"transfer_passed",when)

def learning_proof_status(db,proof):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='study3_judgment' AND type='table'").fetchone():
        return "unavailable"
    import study3
    return study3.proof_status(db,proof)

def displayed_memory(db,row):
    key,body,source,status=row
    value=json.loads(body)
    if isinstance(value,dict) and value.get("proof_sha256"):
        status += "，证明当前状态 "+learning_proof_status(db,value["proof_sha256"])
    return f"{key} · {body[:240]} · {status} · 来源 {source[:160]}"

def node_readings(db):
    rows=db.execute("SELECT id,channel,sample FROM inner3_events ORDER BY at_ns DESC LIMIT 64").fetchall()
    if not rows:
        return "还没有可比较的内在事件。"
    samples=[json.loads(row[2]) for row in rows]
    energy=[s["field"]["features"]["energy"] for s in samples]
    gates=[s["ucm"]["gate"] for s in samples]
    dialogue=sum(row[1] in USER_CHANNELS for row in rows)
    peak=max(samples,key=lambda s:abs(s["components"].get("emotion",0.)))
    return (f"最近 {len(samples)} 条实测，其中 {dialogue} 条来自对话。"
            f"几何场能量范围 {min(energy):.6f}—{max(energy):.6f}，UCM 门值范围 {min(gates):.4f}—{max(gates):.4f}。"
            f"\n数值情绪项对评分的最大绝对贡献 {abs(peak['components'].get('emotion',0.)):.5f}；事件 {peak['event']}。")

def ablation(db):
    """Offline comparison on recent actual topics, holding the current snapshot and base score fixed."""
    rows=db.execute("SELECT topic,COUNT(*) AS n FROM inner3_events GROUP BY topic ORDER BY MAX(at_ns) DESC LIMIT 8").fetchall()
    if len(rows)<2:
        return {"topics":len(rows),"ranking":{},"detail":"至少需要两个实际出现过的议题"}
    state=current(db)
    scores={}
    for topic,count in rows:
        scores[topic]=components(seed(),state,topic,1./(count+1),float(topic!=state["topic"]),"explore")
    ranks={}
    effects={}
    for omitted in ("none","experience","emotion","relation","ucm","field"):
        values={topic:clipped(sum(v for k,v in terms.items() if k!=omitted),-.1,.1) for topic,terms in scores.items()}
        ranks[omitted]=sorted(values,key=lambda name:(-values[name],name))
        if omitted!="none":
            effects[omitted]=max(abs(terms[omitted]) for terms in scores.values())
    return {"topics":len(rows),"state_event":state["event"],"ranking":ranks,
            "max_term":effects,"assumption":"当前快照、近期实际议题，同等基础分"}

@contextmanager
def transaction(db):
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT inner3_record")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO inner3_record")
        raise
    finally:
        db.execute("RELEASE inner3_record")

def record(db,event_id,channel,text,outcome,*,speaker=None):
    """Store exactly one host observation and numerical update inside the caller's transaction."""
    if not isinstance(event_id,str) or not event_id or not channel:
        raise ValueError("内在观察缺少来源或事件号")
    text = str(text or "")
    channel = str(channel)
    caller = str(speaker) if speaker else ("用户" if channel in USER_CHANNELS else None)
    info = outcome if isinstance(outcome,dict) else {"summary":str(outcome or "")}
    fingerprint=digest(packed([channel,caller,text,info]).encode())
    with transaction(db):
        prior=db.execute("SELECT fingerprint,sample FROM inner3_events WHERE id=?",(event_id,)).fetchone()
        if prior:
            if fingerprint!=prior[0]:
                raise ValueError("同一内在观察号对应不同内容")
            return json.loads(prior[1])
        row=db.execute("SELECT body,field,field_hash,identity FROM inner3_state WHERE id=1").fetchone()
        if not row:
            raise RuntimeError("缺少原版检查点，不能新建个体")
        b=seed()
        before=json.loads(row[0])
        if row[3]!=b["id"] or before["source"]!="r28:"+b["snapshot"]:
            raise ValueError("不能把状态接到另一个检查点或个体")
        classified = teaching_observation(text) if channel in USER_CHANNELS else None
        topic = str(info.get("topic") or text or info.get("kind") or channel)[:192]
        count = db.execute("SELECT COUNT(*) FROM inner3_events WHERE topic=?",(topic,)).fetchone()[0]
        novelty = 1.0/(count+1)
        switching = float(bool(before["topic"]) and before["topic"]!=topic)
        salience = 1.0 if classified else .8 if channel in USER_CHANNELS else .5
        tokens = words(topic)
        if classified:
            tokens.insert(0,classified[0])
        previous_memory = before["ucm"]["focus"]
        ctl = b["ctl"].update_control(before["ucm"],{"tokens":tokens,"salience":salience,"novelty":novelty},previous_memory) if before["apply"]["ucm"] else before["ucm"]
        s = resume_field(b,row[1],before,row[2])
        field = sample_field(s,b["calibration"])
        raw=blob_of(s.field)
        field["state_sha256"]=digest(raw)
        field["previous_sha256"]=row[2]
        rel = relation_for(b,words(text+" "+topic))
        rel["availability"]=before["relation"].get("availability")
        if classified and classified[0]=="availability" and classified[1] in {"暂缓","愿意","恢复默认"}:
            rel["availability"]=None if classified[1]=="恢复默认" else classified[1]
        state={**before,"event":event_id,"sequence":before["sequence"]+1,"topic":topic,"ucm":ctl,"field":field,"relation":rel}
        mode="explore" if novelty>.5 else "review"
        state["components"]=components(b,state,topic,novelty,switching,mode)
        state["signal"]=clipped(sum(state["components"].values()),-.1,.1)
        state["mode_hint"]=mode
        when=time.time_ns()
        state["at_ns"]=when
        status=str(info.get("status") or info.get("kind") or "observed")
        excerpt=text[:1024]
        summary=str(info.get("summary") or info.get("answer") or status)[:1024]
        db.execute("INSERT INTO inner3_events VALUES(?,?,?,?,?,?,?,?,?)",
                   (event_id,fingerprint,when,channel,caller,topic,excerpt,summary,packed(state)))
        memory(db,event_id,"working","focus",{"focus":ctl["focus"]},event_id,"observed",when)
        memory(db,event_id,"episodic","receipt",{"topic":topic,"outcome":summary,"speaker":caller},event_id,status,when)
        if channel not in USER_CHANNELS and info.get("kind") and info.get("receipt"):
            memory(db,event_id,"procedural","step",{"kind":info["kind"],"receipt":info["receipt"]},event_id,"executed",when)
        if channel not in USER_CHANNELS:
            verified_claims(db,event_id,info,when)
        if classified:
            code,statement=classified
            disposition="speaker_preference" if code in {"value","empathy","availability"} else "reported_observation"
            db.execute("INSERT INTO inner3_teaching VALUES(?,?,?,?,?,?)",(event_id,caller,when,code,statement,disposition))
        db.execute("UPDATE inner3_state SET body=?,field=?,field_hash=? WHERE id=1",(packed(state),raw,field["state_sha256"]))
        return state

def command(db,text):
    query=text.strip().rstrip("。！？?!")
    if query=="内在状态":
        s=current(db)
        a,f,u=s["axes"],s["field"],s["ucm"]
        return (f"原检查点的连续性 C={a['C']:.3f}、预测误差 T={a['T']:.3f}、新奇度 P={a['P']:.3f}。"
                f"\n几何场步数 {f['steps']}，能量 {f['features']['energy']:.6f}。UCM 焦点：{'、'.join(u['focus']) or '空'}。"
                f"\n本轮关系对象：{s['relation']['target'] or '无对应的旧关系证据'}。调度修正 {s['signal']:+.4f}。"
                f"\n最近观察 {s['event'] or s['source']}。")
    if query=="五类记忆":
        counts=dict(db.execute("SELECT kind,COUNT(*) FROM inner3_memory GROUP BY kind"))
        labels=[f"{name} {min(8,counts.get(key,0)) if key=='working' else counts.get(key,0)}" for name,key in KINDS.items()]
        return "当前记忆记录："+"、".join(labels)+"。输入「查看记忆 语义」等可查最近来源；工作记忆显示最近 8 条。"
    if query=="节点分析":
        return node_readings(db)
    if query=="内在消融":
        check=ablation(db)
        if not check["ranking"]:return check["detail"]
        labels={"none":"全部读数","experience":"去掉经验","emotion":"去掉情绪项","relation":"去掉关系项","ucm":"去掉 UCM","field":"去掉几何场"}
        return check["assumption"]+"。离线重排首选：\n"+"\n".join(labels[k]+"："+topics[0] for k,topics in check["ranking"].items())
    if query.startswith("查看记忆 "):
        name=query[5:].strip().removesuffix("记忆")
        if name not in KINDS:
            return "可查工作、情景、语义、程序、技能。"
        rows=db.execute("SELECT item_key,body,source,status FROM inner3_memory WHERE kind=? ORDER BY at_ns DESC,rowid DESC LIMIT 8",(KINDS[name],)).fetchall()
        return "\n".join(displayed_memory(db,row) for row in rows) or "此类目前没有带来源的记录。"
    if query=="记忆轨迹" or query.startswith("记忆轨迹 "):
        key=query.partition(" ")[2]
        row=db.execute("SELECT id,channel,speaker,at_ns,sample FROM inner3_events "+("WHERE id=?" if key else "ORDER BY at_ns DESC LIMIT 1"),(key,) if key else ()).fetchone()
        if not row:
            return "还没有对应事件的内在记录。"
        s=json.loads(row[4])
        return f"{row[0]} · {row[1]} · {row[2] or '本机'} · {row[3]}\n各项调度贡献 {packed(s['components'])}\n检查点 {s['source']}，几何场步数 {s['field']['steps']}。"
    if query=="教导记录":
        rows=db.execute("SELECT kind,body,speaker,at_ns,event FROM inner3_teaching ORDER BY at_ns DESC LIMIT 8").fetchall()
        return "\n".join(f"{w} · {k} · {s[:180]} · {t} · {e}" for k,s,w,t,e in rows) or "尚无有来源的教导、纠正或价值反馈。"
    if teaching(text):
        return "我会把这条教导与本次对话回执一起保存，记录发言人和时间。可用「教导记录」复核。"
    return None
