"""Trace the actual Windows host decision separately from its post-commit inner-state update."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time

import inner3

ROOT = Path(__file__).resolve().parent
FEATURES = ('energy','mean_amplitude','max_amplitude','min_amplitude','variance','spatial_gradient_energy')
BIASES = ('exploration','persistence','switching')
MODULES = ('round31.py','life3.py','life3_worker.py','inner3.py','evolution3.py')

def packed(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def fingerprint(obj):
    return hashlib.sha256(packed(obj).encode()).hexdigest()

@lru_cache(maxsize=1)
def versions():
    return {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in MODULES}

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS round31_scope (
        id INTEGER PRIMARY KEY CHECK(id=1), started_ns INTEGER NOT NULL,
        previous_life_count INTEGER NOT NULL, previous_inner_sequence INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS round31_events (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, channel TEXT NOT NULL, session TEXT NOT NULL,
        created INTEGER NOT NULL, sample TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS round31_session_time ON round31_events(session,created DESC)")
    db.execute("""CREATE TABLE IF NOT EXISTS round31_native_reference (
        receipt_sha256 TEXT PRIMARY KEY, identity TEXT NOT NULL, module_sha256 TEXT NOT NULL,
        initialized_event TEXT NOT NULL, bound_ns INTEGER NOT NULL, scope_after INTEGER)""")
    if not any(row[1]=="scope_after" for row in db.execute("PRAGMA table_info(round31_native_reference)")):
        db.execute("ALTER TABLE round31_native_reference ADD COLUMN scope_after INTEGER")
    legacy_triggers(db)
    db.execute("""INSERT OR IGNORE INTO round31_scope
        SELECT 1,?,(SELECT count(*) FROM life3_events),
        coalesce((SELECT json_extract(body,'$.sequence') FROM inner3_state WHERE id=1),0)
        WHERE NOT EXISTS(SELECT 1 FROM round31_scope)""",(time.time_ns(),))

def legacy_triggers(db):
    """An already-open 3.0 window can complete its transaction during a host update."""
    db.execute("""CREATE TRIGGER IF NOT EXISTS round31_legacy_dialogue
        AFTER INSERT ON life3_events
        WHEN NEW.kind IN ('dialogue','dialogue_error') AND
             NOT EXISTS(SELECT 1 FROM round31_events WHERE id=NEW.id)
        BEGIN
          INSERT INTO round31_events(id,kind,channel,session,created,sample)
          SELECT NEW.id,NEW.kind,'dialogue',coalesce(req_session,'unknown-session'),
                 coalesce(at_ns,CAST(NEW.created*1000000000 AS INTEGER)),
                 json_object(
                   'schema','zaizai-host-round-3.1-v1','round_id',NEW.id,
                   'compatibility','SQLite 接收原 3.0 对话事务；旧进程没有自报代码摘要',
                   'versions',json_object('resident_python_module_sha256',NULL),
                   'input_source',json_extract(NEW.detail,'$.source'),
                   'content_evidence_sha256',json_extract(NEW.detail,'$.proof_sha256'),
                   'scope','旧桌面进程在3.1起点后新提交的对话事务','decision',NULL,
                   'output',json_object('kind',CASE NEW.kind WHEN 'dialogue_error' THEN '请求失败或结果未知' ELSE '请求原生回执所对应的答复' END,
                      'request',NEW.id,'answer_digest',json_extract(NEW.detail,'$.answer_digest'),
                      'proof_sha256',json_extract(NEW.detail,'$.proof_sha256'),'request_phase',phase,
                      'native_receipt',native_receipt),
                   'post_update',json_object('origin','R28/IntegratedLife','event',json_extract(sample,'$.event'),
                      'sequence',json_extract(sample,'$.sequence'),'checkpoint',json_extract(sample,'$.source'),
                      'axes',json_extract(sample,'$.axes'),'switches',json_extract(sample,'$.apply'),
                      'field',json_object('step',json_extract(sample,'$.field.steps'),'time',json_extract(sample,'$.field.time'),
                          'stopped',json_extract(sample,'$.field.stopped'),'features',json_extract(sample,'$.field.features'),
                          'biases',json_extract(sample,'$.field.biases'),'calibration',json_extract(sample,'$.field.calibration'),
                          'geometry_sha256',json_extract(sample,'$.field.geometry_hash'),
                          'state_sha256',json_extract(sample,'$.field.state_sha256'),'event_head',json_extract(sample,'$.field.source_event_head'))),
                   'emotion',json_object('state',CASE
                      WHEN json_type(sample,'$.apply.emotion')='false' THEN '关闭'
                      WHEN json_type(sample,'$.apply.emotion')='true'
                        AND json_type(sample,'$.axes.P') IN ('real','integer') AND json_type(sample,'$.axes.T') IN ('real','integer')
                      THEN '开启但未参与' ELSE '缺测' END,
                      'reason',CASE NEW.kind WHEN 'dialogue_error' THEN '旧宿主在请求出错后写入观察，本轮没有回复候选排序'
                             ELSE '旧宿主在答复形成后写入同号观察，本轮没有回复候选排序' END,
                      'axes_source',json_extract(sample,'$.source'),'score_axes',NULL),
                   'native_0159',json_object('role','旧宿主记录R28；本轮没有采样原生场','live_sample',NULL,
                       'install_reference',json((SELECT json_object('receipt_sha256',receipt_sha256,'module_sha256',module_sha256,
                              'initialized_event',initialized_event,'scope_after_inner_sequence',scope_after)
                          FROM round31_native_reference ORDER BY bound_ns DESC LIMIT 1))))
          FROM (SELECT i.sample,i.at_ns,r.session AS req_session,r.phase,r.native_receipt
                FROM (SELECT 1) singleton LEFT JOIN inner3_events i ON i.id=NEW.id LEFT JOIN requests r ON r.id=NEW.id);
        END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS round31_request_receipt
        AFTER UPDATE OF phase,native_receipt ON requests
        WHEN NEW.phase='committed' AND NEW.native_receipt IS NOT NULL
        BEGIN
          UPDATE round31_events SET sample=json_set(sample,'$.output.native_receipt',NEW.native_receipt,
                                                    '$.output.request_phase',NEW.phase)
          WHERE id=NEW.id AND kind='dialogue';
        END""")



def bind_native(db,*,identity,module_sha256,receipt_sha256,initialized_event):
    """Bind an already verified installation receipt. Its timestamp is never a live field sample."""
    if not isinstance(initialized_event,str) or not initialized_event.strip():
        raise ValueError("缺少原生场初始化事件")
    if any(not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin)
           for pin in (module_sha256,receipt_sha256)):
        raise ValueError("原生模块和安装回执须提供 SHA256")
    if db.execute("SELECT identity FROM inner3_state WHERE id=1").fetchone()[0]!=identity:
        raise ValueError("原生初始化回执的身份不匹配")
    values=(receipt_sha256,identity,module_sha256,initialized_event)
    prev=db.execute("SELECT receipt_sha256,identity,module_sha256,initialized_event FROM round31_native_reference WHERE receipt_sha256=?",(receipt_sha256,)).fetchone()
    if prev and tuple(prev)!=values:
        raise ValueError("同一原生回执存在不同绑定")
    cutoff=db.execute("SELECT json_extract(body,'$.sequence') FROM inner3_state WHERE id=1").fetchone()[0]
    db.execute("INSERT OR IGNORE INTO round31_native_reference VALUES(?,?,?,?,?,?)",(*values,time.time_ns(),cutoff))
    db.execute("UPDATE round31_native_reference SET scope_after=? WHERE receipt_sha256=? AND scope_after IS NULL",(cutoff,receipt_sha256))

def is_number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def snapshot(state):
    field=state.get("field") or {}
    return {"origin":"R28/IntegratedLife","event":state.get("event"),"sequence":state.get("sequence"),
            "checkpoint":state.get("source"),"axes":state.get("axes"),"switches":state.get("apply"),
            "field":{"step":field.get("steps"),"time":field.get("time"),"stopped":field.get("stopped"),
                     "features":{k:(field.get("features") or {}).get(k) for k in FEATURES},
                     "biases":{k:(field.get("biases") or {}).get(k) for k in BIASES},
                     "calibration":field.get("calibration"),"geometry_sha256":field.get("geometry_hash"),
                     "state_sha256":field.get("state_sha256"),"event_head":field.get("source_event_head")}}

def rank_input(db,state,name,previous,base):
    """Produce the host's existing score and its terms from exactly one state snapshot."""
    recent=db.execute("SELECT id,detail FROM life3_events WHERE json_extract(detail,'$.executed_lane')=? ORDER BY created DESC LIMIT 4",(name,)).fetchall()
    gains=[bool(json.loads(row[1]).get("progress")) for row in recent]
    progress_term=(sum(gains)/len(gains)-.5)*.10 if gains else 0.0
    novelty=float(name!=previous)
    switching=float(bool(previous) and name!=previous)
    mode="review" if name=="integration" else "explore"
    b=inner3.seed()
    parts=inner3.components(b,state,name,novelty,switching,mode)
    adjustment=inner3.clipped(sum(parts.values()),-.1,.1)
    last=db.execute("SELECT max(created) FROM life3_events WHERE json_extract(detail,'$.executed_lane')=?",(name,)).fetchone()[0]
    score_time=time.time()
    age_term=min(.16,(score_time-last)/600) if last else 0.0
    # Keep the original order of floating-point operations.
    final_score=((base+progress_term)+adjustment)+age_term
    return {"eligible":True,"reason":"通过当前宿主工作队列判定","intrinsic_score":base,
            "progress_term":progress_term,"recent_progress_receipts":[r[0] for r in recent],
            "last_completed_at":last,"score_time":score_time,"age_term":age_term,
            "base_score":(base+progress_term)+age_term,"components":parts,"bounded_adjustment":adjustment,
            "bounds":[-.1,.1],"final_score":final_score,"mode":mode,"novelty":novelty,"switching":switching,
            "geometry_channel":"persistence" if mode=="review" else ("switching" if switching else "exploration")}

def ranked(db,event_id,inputs,checks,candidates):
    prior=inner3.current(db)
    previous=inputs["previous_lane"]
    scores={name:rank_input(db,prior,name,previous,base) for name,base in candidates.items()}
    for name,reason in checks.items():
        if name not in scores:scores[name]={"eligible":False,"reason":reason,"base_score":None,"components":None,"final_score":None}
    ordered=sorted(candidates,key=lambda name:scores[name]["final_score"],reverse=True)
    return ordered,{"phase":"排名前","decision_domain":"Windows 宿主工作通道","state_used":snapshot(prior),
        "emotion_inputs":inner3.seed()["modules"]["development"]["content"]["axes"],
        "eligibility_inputs":inputs,"candidates":scores,"order":ordered,"preference_first":ordered[0],
        "eligibility_sha256":fingerprint([inputs,sorted(candidates)]),"round_id":event_id}

def finish_selection(db,decision,actual):
    row=db.execute("""SELECT pressure,base_choice,candidate_choice,revision,trial,arm,chosen
        FROM evo3_assignments WHERE event_id=?""",(decision["round_id"],)).fetchone()
    if row is None or row[6]!=actual or actual not in decision["order"]:
        raise ValueError("本轮调度记录和实际派工不一致")
    decision["policy"]={"pressure":json.loads(row[0]),"base_choice":row[1],"candidate_choice":row[2],
                        "revision":row[3],"trial":row[4],"arm":row[5]}
    decision["actual_choice"]=actual
    decision["selection_reason"]=("首选通过本轮治理策略" if actual==decision["preference_first"] else
                                  "本轮治理策略在合格通道中调整了顺序")

def emotion_state(used,ranked):
    switch=(used.get("switches") or {}).get("emotion")
    if switch is False:return "关闭"
    if switch is not True:return "缺测"
    axes=(ranked.get("emotion_inputs") if ranked and ranked.get("score_kind")!="geometric_port" else used.get("axes")) or {}
    if not all(is_number(axes.get(k)) for k in ("P","T")):return "缺测"
    if ranked is None or ranked.get("score_kind")=="geometric_port":return "开启但未参与"
    contributions=[c["components"].get("emotion") for c in ranked["candidates"].values() if c["eligible"]]
    if not contributions or not all(is_number(v) for v in contributions):return "缺测"
    return "参与并写入"

def write(db,event_id,channel,session,outcome,inner,decision):
    after=snapshot(inner)
    used=decision["state_used"] if decision else after
    reference=db.execute("""SELECT receipt_sha256,module_sha256,initialized_event,scope_after FROM round31_native_reference
        ORDER BY bound_ns DESC LIMIT 1""").fetchone()
    if outcome.get("host_status"):
        output={"kind":"宿主数据或槽状态","request":event_id,"frame_kind":outcome.get("frame_kind"),"answer_digest":outcome.get("answer_digest")}
        why="本轮履行宿主数据或状态查询，没有提交认知候选排序"
    elif decision:
        output={"kind":"已执行的工作通道","choice":decision["actual_choice"]}
        why=("本轮按认知基础分和有界几何偏好选择，情绪读数未进合成评分" if decision.get("score_kind")=="geometric_port" else
             "已计算各合格通道评分并执行治理选中的通道；参与计分可包括零贡献，不能由此断言改变了首选")
    elif channel=="dialogue" and outcome["kind"]=="dialogue_error":
        output={"kind":"请求失败或结果未知","request":event_id,"request_phase":outcome.get("status"),"native_receipt":None}
        why="请求出错后记录了内在状态，本轮没有回复候选排序"
    elif channel=="dialogue":
        output={"kind":"请求原生回执所对应的答复","request":event_id,"answer_digest":outcome.get("answer_digest"),
                "proof_sha256":outcome.get("proof_sha256")}
        why="可见答复及其原生事务先形成，内在读数在提交时记录；本路径没有调用宿主候选评分"
    else:
        output={"kind":"已发生的宿主事件","lane":outcome.get("executed_lane"),"result":outcome.get("status")}
        why="此轮使用维护、I/O 或错误记录路径，没有调用宿主候选评分"
    summary={"schema":"zaizai-host-round-3.1-v1","round_id":event_id,"versions":versions(),
             "input_source":outcome.get("source") or outcome.get("source_receipt") or channel,
             "content_evidence_sha256":outcome.get("basis") or outcome.get("proof_sha256"),
             "scope":"实际提交的宿主生命/对话事务","decision":decision,"output":output,
             "post_update":after,
             "emotion":{"state":emotion_state(used,decision),"reason":why,"axes_source":used.get("checkpoint"),
                        "score_axes":decision["emotion_inputs"] if decision else None},
             "native_0159":{"role":"独立原生场；本宿主评分调用 R28，未取用 0.159 场作本轮输入",
                 "live_sample":None,"install_reference":dict(zip(("receipt_sha256","module_sha256","initialized_event","scope_after_inner_sequence"),reference)) if reference else None}}
    summary["slot_bindings"]=outcome.get("slot_bindings")
    summary["c6_measurements"]=decision.get("c6") if decision else None
    db.execute("INSERT INTO round31_events VALUES(?,?,?,?,?,?)",(event_id,outcome["kind"],channel,session,time.time_ns(),packed(summary)))

def command(db,text,session):
    q=text.strip().rstrip("。！？?!")
    if q not in ("本轮依据","调度依据") and not q.startswith("轮次依据 "):return None
    if q=="本轮依据":
        row=db.execute("SELECT sample FROM round31_events WHERE channel='dialogue' AND session=? ORDER BY created DESC LIMIT 1",(session,)).fetchone()
    elif q=="调度依据":
        row=db.execute("""SELECT sample FROM round31_events WHERE channel!='dialogue' AND json_type(sample,'$.decision')='object'
                          ORDER BY created DESC LIMIT 1""").fetchone()
    else:
        row=db.execute("SELECT sample FROM round31_events WHERE id=? AND (channel!='dialogue' OR session=?)",(q.partition(' ')[2].strip(),session)).fetchone()
    if not row:return "验收起点之后，还没有可在此会话查看的对应轮次。"
    data=json.loads(row[0]);d=data['decision'];out=data["output"]
    text=[f"轮次 {data['round_id']} · {data['emotion']['state']}",data["emotion"]["reason"]]
    if d:
        text.append(f"排名输入来自 R28 场第 {d['state_used']['field']['step']} 步。最终派工 {d['actual_choice']}。")
        for name,rec in d['candidates'].items():
            if rec["eligible"]:
                e=rec["components"].get("emotion")
                description="未参与" if e is None else f"{e:+.5f}"
                text.append(f"{name}  基础 {rec['base_score']:.5f}，几何项 {rec['components']['field']:+.5f}，情绪项 {description}，总分 {rec['final_score']:.5f}")
            else:text.append(name+"  未参与排序："+rec["reason"])
    else:text.append(f"提交后 R28 场步数 {data['post_update']['field']['step']}；输出为{out['kind']}。")
    return "\n".join(text)

