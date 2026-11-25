"""Versioned local scheduling policy. Admission and scoring live outside the policy."""
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import time

ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = ROOT / "evidence" / "v3-gate.json"
CASE_IDS = ("W02", "W03", "W04", "W07", "W10", "W11", "W13", "W16")
CLASSES = {"knowledge":"知识", "rule":"规则", "ability":"能力", "performance":"性能", "resource":"资源"}
FAILURES = {"failed", "error", "rejected", "unknown", "conflict", "blocked", "timeout", "refused", "gap"}
GAP_SIGNALS = {"failed", "error", "rejected", "unknown", "conflict", "blocked", "timeout", "refused", "gap",
               "inquiry", "question", "stalled", "help", "failure", "over_budget"}
MIN_UPDATE_SECONDS = 3600
EVIDENCE_PROGRESS={"read","recall","source_review","fetch","discovery","research","flow","evidence"}
SQL = (
    """CREATE TABLE IF NOT EXISTS evo3_policies(
       id INTEGER PRIMARY KEY, parent INTEGER, retry_limit INTEGER NOT NULL CHECK(retry_limit BETWEEN 1 AND 4),
       cause INTEGER, created REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evo3_active(
       singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, changed REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evo3_events(
       seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, lane TEXT NOT NULL, topic TEXT NOT NULL,
       category TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, progress REAL NOT NULL,
       failed INTEGER NOT NULL, duration_ms REAL, created REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evo3_demands(
       id INTEGER PRIMARY KEY, category TEXT NOT NULL, lane TEXT NOT NULL, base INTEGER NOT NULL,
       first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL, evidence TEXT NOT NULL, phase TEXT NOT NULL,
       proposal TEXT NOT NULL, candidate INTEGER, shadow TEXT, evaluation TEXT, created REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evo3_assignments(
       event_id TEXT PRIMARY KEY, contenders TEXT NOT NULL, pressure TEXT NOT NULL, chosen TEXT NOT NULL,
       base_choice TEXT NOT NULL, candidate_choice TEXT, revision INTEGER NOT NULL, trial INTEGER,
       arm TEXT NOT NULL, created REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evo3_transitions(
       seq INTEGER PRIMARY KEY, demand INTEGER, previous INTEGER NOT NULL, current INTEGER NOT NULL,
       reason TEXT NOT NULL, detail TEXT NOT NULL, stamp REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS evo3_failure_stream ON evo3_events(failed,category,lane,seq)",
    "CREATE INDEX IF NOT EXISTS evo3_trial_assignments ON evo3_assignments(trial,arm)",
)


def _json(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def setup(db):
    for statement in SQL:
        db.execute(statement)
    # Assignments and their observations already have independent wall-clock receipts.
    # Record that interval when the operator has not supplied a higher-resolution duration.
    db.execute("""CREATE TRIGGER IF NOT EXISTS evo3_elapsed_work AFTER INSERT ON evo3_events
        WHEN NEW.duration_ms IS NULL AND EXISTS(SELECT 1 FROM evo3_assignments WHERE event_id=NEW.event_id)
        BEGIN UPDATE evo3_events SET duration_ms=max(0,1000*(NEW.created-(SELECT created FROM evo3_assignments WHERE event_id=NEW.event_id)))
        WHERE event_id=NEW.event_id; END""")
    db.execute("""UPDATE evo3_events SET duration_ms=max(0,1000*(created-(SELECT created FROM evo3_assignments a WHERE a.event_id=evo3_events.event_id)))
        WHERE duration_ms IS NULL AND EXISTS(SELECT 1 FROM evo3_assignments a WHERE a.event_id=evo3_events.event_id)""")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='life3_events'").fetchone():
        db.execute("""CREATE TRIGGER IF NOT EXISTS evo3_elapsed_turn AFTER INSERT ON life3_events
            WHEN NEW.kind='dialogue' AND json_type(NEW.detail,'$.elapsed_ms') IN ('integer','real')
            BEGIN UPDATE evo3_events SET duration_ms=json_extract(NEW.detail,'$.elapsed_ms')
            WHERE event_id=NEW.id AND duration_ms IS NULL; END""")
        db.execute("""CREATE TABLE IF NOT EXISTS evo3_event_corrections(event_id TEXT PRIMARY KEY,
            prior_failed INTEGER NOT NULL,reason TEXT NOT NULL,corrected REAL NOT NULL)""")
        db.execute("""INSERT OR IGNORE INTO evo3_event_corrections
            SELECT e.event_id,e.failed,'工作已取得进展；证据未知或有冲突与运行失败分别记账',?
            FROM evo3_events e JOIN life3_events l ON l.id=e.event_id WHERE e.failed=1 AND e.progress>0
            AND e.status IN ('unknown','conflict') AND json_extract(l.detail,'$.error') IS NULL
            AND coalesce(json_extract(l.detail,'$.failed'),0)=0 AND l.kind IN ("""+
            ",".join("?" for _ in EVIDENCE_PROGRESS)+")",(time.time(),*sorted(EVIDENCE_PROGRESS)))
        db.execute("UPDATE evo3_events SET failed=0 WHERE failed=1 AND event_id IN (SELECT event_id FROM evo3_event_corrections)")
        db.execute("""UPDATE evo3_demands SET phase='superseded',evaluation=? WHERE phase IN ('proposed','canary','shadow_pass')
            AND NOT EXISTS(SELECT 1 FROM json_each(evo3_demands.evidence) q JOIN evo3_events e ON e.event_id=q.value WHERE e.failed=1)""",
            (_json({"reason":"历史候选的依据已被纠正，保留原需求单与影子记录。"}),))
    db.execute("INSERT OR IGNORE INTO evo3_policies VALUES(1,NULL,3,NULL,0)")
    db.execute("INSERT OR IGNORE INTO evo3_active VALUES(1,1,0)")


@contextmanager
def _unit(db):
    # A release must NEVER commit another subsystem's transaction.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT evo3_unit")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO evo3_unit")
        db.execute("RELEASE evo3_unit")
        raise
    else:
        db.execute("RELEASE evo3_unit")


@lru_cache(maxsize=256)
def _file_hash(path, size, modified):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def protected_hashes():
    paths = list((ROOT/"host").glob("*.py"))
    paths += list((ROOT/"host").glob("*.cl"))
    paths += list((ROOT/"host").glob("*.json"))
    # Slot manifests independently pin optional engines. Authorizing a host update must not require an engine file.
    paths += [ROOT/"tools"/f for f in ("check_host_slots31.py","check_slots31.py","check_life_slots31.py",
            "check_slot_ownership31.py","check_slot_swap31.py","check_proof.py","check_learning.py",
            "gate_slots_release31.py","manage_slots31.py","save_state.py")]
    paths += [ROOT/"tools"/f for f in ("geometry31.py","geometry.cl","geometry31-protocol.json","gate_local3.py","check_crash.py","check_continuity.py","check_decisions.py","migrate.py")]
    for protected in ("study3_assets", "evolution3_assets"):
        folder = ROOT/"host"/protected
        if folder.is_dir():
            paths += [p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    hashes = {}
    for path in sorted(paths):
        st = path.stat()
        hashes[path.relative_to(ROOT).as_posix()] = _file_hash(path, st.st_size, st.st_mtime_ns)
    return hashes


def gate_status():
    try:
        gate = json.loads(GATE_FILE.read_bytes())
        if not isinstance(gate, dict) or not all(gate.get(k) is True for k in ("passed","latency_ok","errors_ok")):
            return False, "对话功能、时延或错误率回归门尚未通过"
        sections=gate.get("slot_groups",{})
        if gate.get("schema")!="zaizai-host-slot-gate/1" or not all(sections.get(k) is True for k in
                ("host_independent","legacy_dependent","port_contracts","binding_rehearsal","provenance","checkpoint")):
            return False, "宿主独立组、槽件能力组及换槽复验尚未完整通过"
        cases = gate.get("cases")
        if not isinstance(cases, dict) or any(cases.get(k) is not True for k in CASE_IDS):
            return False, "对话回归门缺少必要用例"
        if gate.get("protected_sha256") != protected_hashes():
            return False, "当前宿主或引擎与通过回归的版本不同"
        return True, "当前受保护构建已通过对话回归"
    except (OSError, ValueError):
        return False, "尚无可读的正式对话回归凭据"


def policy(db):
    row = db.execute("""SELECT p.id,p.retry_limit FROM evo3_active a
                        JOIN evo3_policies p ON p.id=a.revision WHERE a.singleton=1""").fetchone()
    return {"revision":row[0], "retry_limit":row[1]}


def _pick(lanes, pressure, limit):
    # Exhausted lanes still receive service once their failed samples leave the short history.
    return next((lane for lane in lanes if pressure.get(lane,0)<limit), lanes[0])


def _pressure(db, lanes):
    history = db.execute("""SELECT e.lane,e.progress,e.failed FROM evo3_events e
        JOIN evo3_assignments s ON s.event_id=e.event_id WHERE e.lane=s.chosen ORDER BY e.seq DESC LIMIT 16""")
    count = dict.fromkeys(lanes,0)
    done = set()
    for lane, gain, failed in history:
        if lane in count and lane not in done:
            if gain>0 and not failed:
                done.add(lane)
            else:
                count[lane]+=1
    return count


def select_lane(db, event_id, ordered_lanes):
    """Bind an upcoming real unit of work to its policy revision and contender set."""
    lanes = list(dict.fromkeys(ordered_lanes))
    if not lanes or len(lanes)>32 or any(not isinstance(x,str) or not 0<len(x)<=100 for x in lanes):
        raise ValueError("需要一至三十二个有效的后台工作通道")
    if not event_id:
        raise ValueError("工作步缺少请求号")
    with _unit(db):
        prior = db.execute("SELECT chosen,contenders FROM evo3_assignments WHERE event_id=?",(event_id,)).fetchone()
        if prior:
            if json.loads(prior[1]) != lanes:
                raise ValueError("相同工作步携带不同的候选通道")
            return prior[0]
        base = policy(db)
        counts = _pressure(db, lanes)
        primary = _pick(lanes, counts, base["retry_limit"])
        chosen,other,arm,trial,revision = primary,None,"active",None,base["revision"]
        staged = db.execute("""SELECT r.id,p.retry_limit,p.id FROM evo3_demands r
            JOIN evo3_policies p ON p.id=r.candidate WHERE r.phase='canary' AND r.base=?""",(revision,)).fetchone()
        if staged:
            trial,limit,candidate = staged
            other = _pick(lanes,counts,limit)
            if primary!=other:
                count = db.execute("""SELECT count(*) FROM evo3_assignments WHERE trial=?
                                      AND base_choice!=candidate_choice""",(trial,)).fetchone()[0]
                arm = "reference"
                if count%4==0 and gate_status()[0]:
                    chosen,revision,arm = other,candidate,"canary"
            else:
                arm = "unchanged"
        db.execute("INSERT INTO evo3_assignments VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (event_id,_json(lanes),_json(counts),chosen,primary,other,revision,trial,arm,time.time()))
        return chosen


def _number(value, default=0.0):
    try:
        val = float(value)
        return val if math.isfinite(val) else default
    except (TypeError,ValueError,OverflowError):
        return default


def _classify(kind, outcome, status):
    category = outcome.get("category", "")
    for k,v in CLASSES.items():
        if category in (k,v):
            return k
    desc = " ".join((kind, status, str(outcome.get("reason","")),str(outcome.get("error","")))).casefold()
    labels = (("resource",("resource","vram","memoryerror","资源","显存","超预算","over_budget")),
              ("performance",("timeout","slow","latency","性能","超时")),
              ("rule",("conflict","rule","reject","冲突","规则","拒绝")),
              ("ability",("capability","unsupported","error","能力","异常","failed")))
    return next((k for k,patterns in labels if any(p in desc for p in patterns)),"knowledge")


def observe(db, event_id, kind, outcome):
    """Record the actual worker/turn outcome once; external document prose is never a policy."""
    if not isinstance(outcome,dict):
        outcome = {"summary":str(outcome)}
    kind = str(kind)
    status = str(outcome.get("status","")).casefold()[:48]
    result = str(outcome.get("kind",kind)).casefold()[:64]
    gain = max(0.0,min(1.0,_number(outcome.get("progress",0))))
    failed = bool(outcome.get("failed") or outcome.get("error") or status in FAILURES or result in GAP_SIGNALS)
    if result in EVIDENCE_PROGRESS and gain>0 and status in {"unknown","conflict"} and not (outcome.get("failed") or outcome.get("error")):
        failed=False
    assignment = db.execute("SELECT chosen FROM evo3_assignments WHERE event_id=?",(event_id,)).fetchone()
    lane = str(outcome.get("executed_lane") or (assignment[0] if assignment else kind))[:100]
    if assignment and gain==0 and outcome.get("executed",True) and status not in ("idle","waiting","paused","completed"):
        failed = True
    if not outcome.get("executed",True):
        lane = "idle"
        failed = False
    summary = str(outcome.get("reason") or outcome.get("error") or outcome.get("summary") or status or result)[:360]
    elapsed = _number(outcome.get("duration_ms"),None)
    category = _classify(kind,outcome,status)
    db.execute("""INSERT OR IGNORE INTO evo3_events
       (event_id,lane,topic,category,status,detail,progress,failed,duration_ms,created)
       VALUES(?,?,?,?,?,?,?,?,?,?)""",(event_id,lane,str(outcome.get("topic",lane))[:120],category,
       status or result,summary,gain,int(failed),elapsed,time.time()))


def _work(kind, text, demand):
    return {"kind":kind,"summary":text,"topic":"需求单 "+str(demand),"progress":1,"demand":demand}


def _new_request(db):
    rows = db.execute("""SELECT e.category,e.lane,COUNT(*),MIN(e.seq),MAX(e.seq)
       FROM evo3_events e WHERE e.failed=1 AND e.seq>COALESCE((SELECT MAX(d.last_seq)
       FROM evo3_demands d WHERE d.category=e.category AND d.lane=e.lane),0)
       GROUP BY e.category,e.lane HAVING COUNT(*)>=3 ORDER BY MIN(e.seq) LIMIT 1""").fetchone()
    if not rows:
        return None
    category,lane,count,lo,hi = rows
    evidence = [r[0] for r in db.execute("""SELECT event_id FROM evo3_events WHERE failed=1
        AND seq BETWEEN ? AND ? AND category=? AND lane=? ORDER BY seq DESC LIMIT 12""",(lo,hi,category,lane))]
    proposal = {"现象":f"{lane} 通道出现 {count} 次{CLASSES[category]}类瓶颈","证据":evidence,
                "影响面":lane,"假设原因":"在缺少新证据时重复分配同一通道，待对照。",
                "候选":["保持现状","缩短无进展通道的连续尝试次数"],
                "验证":"按原排队记录影子比较，之后观察实际小流量工作结果和保持原样的对照。",
                "范围":"可逆的本地后台调度参数","授权":"L1 影子 / L2 有条件发布"}
    cur = db.execute("""INSERT INTO evo3_demands(category,lane,base,first_seq,last_seq,evidence,phase,
                     proposal,created) VALUES(?,?,?,?,?,?,'proposed',?,?)""",
                     (category,lane,policy(db)["revision"],lo,hi,_json(evidence),_json(proposal),time.time()))
    return _work("evolution_demand",proposal["现象"]+"，已生成需求单。",cur.lastrowid)


def _shadow(db, demand):
    base = policy(db)
    data = db.execute("""SELECT a.contenders,a.pressure,a.chosen,e.progress,e.failed FROM evo3_assignments a
       JOIN evo3_events e ON e.event_id=a.event_id AND e.lane=a.chosen
       WHERE a.revision=? AND e.seq<=? ORDER BY e.seq DESC LIMIT 128""",(base["revision"],demand["last_seq"]))
    samples = list(data)
    scores = []
    for limit in range(1,base["retry_limit"]):
        avoided=delayed=0
        for routes,pressure,actual,gain,failed in samples:
            if _pick(json.loads(routes),json.loads(pressure),limit)!=actual:
                if failed:
                    avoided+=1
                elif gain>0:
                    delayed+=1
        scores.append({"limit":limit,"avoided_failed":avoided,"delayed_progress":delayed,
                       "score":avoided-2*delayed})
    result = {"samples":len(samples),"stay_score":0,"alternatives":scores}
    winner = max(scores,key=lambda x:(x["score"],x["limit"])) if scores else None
    if not winner or winner["score"]<=0 or winner["avoided_failed"]<2:
        db.execute("UPDATE evo3_demands SET phase='stay',shadow=? WHERE id=?",(_json(result),demand["id"]))
        return _work("evolution_stay","保留现行策略。影子数据还不足以支持更换。",demand["id"])
    cur=db.execute("INSERT INTO evo3_policies(parent,retry_limit,cause,created) VALUES(?,?,?,?)",
                   (base["revision"],winner["limit"],demand["id"],time.time()))
    db.execute("UPDATE evo3_demands SET phase='shadow_pass',candidate=?,shadow=? WHERE id=?",
               (cur.lastrowid,_json(result),demand["id"]))
    return _work("evolution_shadow","影子比较发现可减少实际出现过的失败重试，候选等待对话回归门。",demand["id"])


def _transition(db,demand,old,new,reason,detail):
    changed = db.execute("UPDATE evo3_active SET revision=?,changed=? WHERE singleton=1 AND revision=?",
                         (new,time.time(),old)).rowcount
    if changed!=1:
        raise RuntimeError("策略基线已改变，请重新核对需求单")
    db.execute("INSERT INTO evo3_transitions(demand,previous,current,reason,detail,stamp) VALUES(?,?,?,?,?,?)",
               (demand,old,new,reason,_json(detail),time.time()))


def _canary(db,demand):
    samples=list(db.execute("""SELECT a.arm,e.event_id,e.progress,e.failed,e.duration_ms
       FROM evo3_assignments a JOIN evo3_events e ON e.event_id=a.event_id AND e.lane=a.chosen
       WHERE a.trial=? AND a.arm IN ('reference','canary') ORDER BY e.seq""",(demand["id"],)))
    groups={k:[r for r in samples if r[0]==k] for k in ("reference","canary")}
    if len(groups["canary"])<3 or len(groups["reference"])<6:
        return None
    summary={}
    for arm,rows in groups.items():
        durations=sorted(r[4] for r in rows if r[4] is not None)
        summary[arm]={"count":len(rows),"progress_rate":sum(r[2]>0 and not r[3] for r in rows)/len(rows),
                      "fail_rate":sum(r[3] for r in rows)/len(rows),"events":[r[1] for r in rows[:20]],
                      "median_ms":durations[len(durations)//2] if durations else None}
    trial,reference=summary["canary"],summary["reference"]
    wins=trial["progress_rate"]>reference["progress_rate"] and trial["fail_rate"]<=reference["fail_rate"]
    if reference["median_ms"] is not None and trial["median_ms"] is not None:
        wins=wins and trial["median_ms"]<=max(5.0,reference["median_ms"]*1.25)
    gate,why=gate_status()
    summary["gate"]=why
    if not wins or not gate:
        db.execute("UPDATE evo3_demands SET phase='stay',evaluation=? WHERE id=?",(_json(summary),demand["id"]))
        return _work("evolution_stay","实际候选样本未达到发布条件，保留原策略。",demand["id"])
    last=db.execute("SELECT changed FROM evo3_active WHERE singleton=1").fetchone()[0]
    if time.time()-last<MIN_UPDATE_SECONDS:
        return None
    _transition(db,demand["id"],demand["base"],demand["candidate"],"promoted",summary)
    db.execute("UPDATE evo3_demands SET phase='applied',evaluation=? WHERE id=?",(_json(summary),demand["id"]))
    return _work("evolution_applied","候选通过实际金丝雀对照，已在工作步之间原子切换。",demand["id"])


def rollback(db, reason="用户请求"):
    with _unit(db):
        revision=policy(db)["revision"]
        old=db.execute("SELECT parent,cause FROM evo3_policies WHERE id=?",(revision,)).fetchone()
        if not old[0]:
            return "当前已是初始策略。"
        _transition(db,old[1],revision,old[0],"rollback",{"reason":reason})
        db.execute("UPDATE evo3_demands SET phase='rolled_back' WHERE id=?",(old[1],))
        return f"已从调度策略 {revision} 回到 {old[0]}，经历与回执保存在原表。"


def advance(db):
    """At most one decision per invocation. The scheduler supplies the surrounding transaction."""
    with _unit(db):
        base=policy(db)
        current=db.execute("SELECT parent,cause FROM evo3_policies WHERE id=?",(base["revision"],)).fetchone()
        if current[0]:
            changed=db.execute("SELECT changed FROM evo3_active WHERE singleton=1").fetchone()[0]
            rows=list(db.execute("""SELECT e.failed,e.progress FROM evo3_assignments a JOIN evo3_events e
                 ON e.event_id=a.event_id AND e.lane=a.chosen WHERE a.revision=? AND a.created>?
                 ORDER BY e.seq DESC LIMIT 6""",(base["revision"],changed)))
            if len(rows)==6 and all(r[0] and r[1]<=0 for r in rows):
                return _work("evolution_rollback",rollback(db,"新策略最近六次实际派工均失败"),current[1])
        demand=db.execute("""SELECT * FROM evo3_demands WHERE phase IN ('proposed','shadow_pass','canary')
                             ORDER BY id LIMIT 1""").fetchone()
        if not demand:
            return _new_request(db)
        if demand["base"]!=base["revision"]:
            db.execute("UPDATE evo3_demands SET phase='stale' WHERE id=?",(demand["id"],))
            return _work("evolution_stale","所依据的策略已切换，候选未继续应用。",demand["id"])
        if demand["phase"]=="proposed":
            return _shadow(db,demand)
        if demand["phase"]=="shadow_pass":
            gate,reason=gate_status()
            if not gate:
                if demand["evaluation"]==reason:
                    return None
                db.execute("UPDATE evo3_demands SET evaluation=? WHERE id=?",(reason,demand["id"]))
                return _work("evolution_gate",reason,demand["id"])
            db.execute("UPDATE evo3_demands SET phase='canary' WHERE id=?",(demand["id"],))
            return _work("evolution_canary","对话回归通过，差异派工每四次抽一次给候选。",demand["id"])
        return _canary(db,demand)


def command(db,text):
    key=text.strip().rstrip("。？?!！")
    if key in ("回退调度策略","回滚调度策略"):
        return rollback(db)
    if key in ("瓶颈账本","失败账本"):
        tally=db.execute("""SELECT category,COUNT(*) FROM evo3_events WHERE failed=1
                             GROUP BY category ORDER BY COUNT(*) DESC""").fetchall()
        return "已记录的瓶颈："+"，".join(f"{CLASSES[k]} {n} 次" for k,n in tally) if tally else "当前还没有已记录的瓶颈。"
    if key in ("自我迭代","需求单","迭代需求","策略版本","迭代状态"):
        state=policy(db)
        rows=db.execute("SELECT id,category,lane,phase FROM evo3_demands ORDER BY id DESC LIMIT 6").fetchall()
        labels={"proposed":"待影子比较","shadow_pass":"待回归门","canary":"实际小流量对照","stay":"保留现状",
                "applied":"已应用","rolled_back":"已回退","stale":"依据已过期"}
        detail="\n".join(f"#{i} {CLASSES[c]} / {lane} · {labels[phase]}" for i,c,lane,phase in rows)
        return f"本地后台调度策略 {state['revision']}，连续无进展阈值 {state['retry_limit']}。"+("\n"+detail if detail else "\n尚无重复瓶颈产生的需求单。")
    if key.startswith("需求单 "):
        suffix=key[4:].strip().lstrip("#")
        if not suffix.isdecimal():
            return "请输入需求单编号，例如「需求单 1」。"
        row=db.execute("SELECT proposal,phase,shadow,evaluation FROM evo3_demands WHERE id=?",(int(suffix),)).fetchone()
        if not row:
            return "没有这个编号的需求单。"
        d=json.loads(row[0])
        return "\n".join(f"{k}：{'、'.join(v) if isinstance(v,list) else v}" for k,v in d.items())+f"\n阶段：{row[1]}\n影子结果：{row[2] or '待测'}\n金丝雀结果：{row[3] or '待测'}"
    return None
