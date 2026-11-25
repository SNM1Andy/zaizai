"""Let the existing PCGM choose its authorized local lexical rule after exact independent CL and private native replay."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
KIND="local_lexical_rule"
ALLOWED={"term_grounded","term_local_match"}
TRIGGERS={"requested_learning(current)","reconsider_learning(current)"}
RULE=re.compile(r"learned_use\(\$(\w+)\) <- (term_grounded|term_local_match)\(\$\1\) & (term_grounded|term_local_match)\(\$\1\)\.")

def signals(db,snapshot):
    active={}
    for m in re.finditer(r"(?m)^& ([a-zA-Z0-9_]+) ((?:term_grounded|term_local_match|requested_learning|reconsider_learning)\(current\))\.$",snapshot["source"]):
        if m[1] in snapshot["inactive"]:continue
        r=db.execute("SELECT source,atom,receipt FROM samples WHERE id=?",(m[1],)).fetchone()
        if r and r["source"].strip() and r["atom"]==m[2] and r["receipt"]:
            active.setdefault(m[2],[]).append({"observation":m[1],"source":r["source"],"receipt":r["receipt"]})
    return active

def native_decision(n,binary,state,command):
    result=json.loads(n.invoke(binary,["--resume",state],(command+"\n").encode()).splitlines()[-1])
    return result.get("decision",result)

def selected(decision):
    i=decision.get("selected")
    return decision["options"][i] if i is not None else {}

def scope(source):
    allowed=set(re.findall(r"(?m)^\^ learned_use ([a-zA-Z0-9_]+)\.$",source))
    if allowed!=ALLOWED or re.search(r"(?m)^[^#\n]* <- [^\n]*\blearned_use\s*\(",source):
        raise ValueError("当前既有局部词义授权改变或其输出被其它规则依赖")
    # Only ordinary rules and frozen objectives may refer to this local output.
    if any(re.search(r"\blearned_use\b",ln) for ln in source.splitlines() if ln.strip().startswith(("@","~","%","="))):
        raise ValueError("词义输出已接入其它原生策略")

def independent(n,binary,state,snapshot,language,folder,suffix):
    lines=[];inactive=set(snapshot["inactive"]);subjects={"current"}
    for ln in snapshot["source"].splitlines():
        if ln.lstrip().startswith(("?","^","|","~","%","=","@")):continue
        obs=re.match(r"\s*&\s+(\w+)\s",ln)
        if obs and obs[1] in inactive:continue
        if obs:
            subjects.update(re.findall(r"\b(?:term_grounded|term_local_match|learned_use)\(([a-zA-Z_][a-zA-Z0-9_]*)\)",ln))
        lines.append(ln)
    if len(subjects)>64:raise ValueError("本轮超出独立词义校验预算")
    goals={"identity_restored(zaizai)","receipt_available(zaizai)",*TRIGGERS,
           *("learned_use("+s+")" for s in subjects),"term_grounded(current)","term_local_match(current)"}
    program="\n".join(lines+["? "+g+"." for g in sorted(goals)]+[""])
    file=folder/(suffix+".cl");file.write_text(program,encoding="utf8")
    raw=n.invoke(language,["json",file]);out=json.loads(raw)
    proof={r["goal"]["predicate"]+"("+",".join(str(a["value"]) for a in r["goal"]["arguments"])+")":r["status"] for r in out["results"]}
    if set(proof)!=goals:raise ValueError("独立 CL 未完整覆盖本轮目标")
    # A single native read process checks every requested atom against the same version.
    packet="".join("q"+str(i)+" reasoned_outcome lexical "+g+"\n" for i,g in enumerate(sorted(goals)))
    native=[json.loads(line) for line in n.invoke(binary,["--read-channel",state],packet.encode()).splitlines()]
    if len(native)!=len(goals) or any(not r.get("ok") or r["id"]!="q"+str(i) or r["payload"]["status"]!=proof[g]
                                      for i,(r,g) in enumerate(zip(native,sorted(goals)))):
        raise ValueError("独立 CL 与真实原生语义不一致")
    return {"statuses":proof,"source_sha256":n.digest(program.encode()),"proof_sha256":n.digest(raw.encode())}

def prepare(db,n,binary,state,snap,decision,op,language,materials):
    scope(snap["source"])
    goal=selected(decision);rev=goal["target"]
    if not goal.get("eligible") or not re.fullmatch(r"p\d+",rev or ""):raise ValueError("选项没有受管修订号")
    if op=="rollback":
        prev=db.execute("SELECT trial FROM lexical25_intents WHERE revision=? AND action='rewrite' AND committed=1 ORDER BY rowid DESC LIMIT 1",(rev,)).fetchone()
        if not prev:raise ValueError("本委托没有这份修订的既有采纳回执")
        previous=json.loads(prev[0])
        if previous["actor"]!=snap["individual"]:raise ValueError("既有词义修订属于其他身份")
    with tempfile.TemporaryDirectory(prefix="lexical-review-") as t:
        dest=Path(t).resolve();other=dest/state.name;shutil.copy2(state,other)
        for extra in (".history",".episodes"):
            aux=state.with_name(state.name+extra)
            if aux.is_dir():shutil.copytree(aux,dest/aux.name)
        historic=n.history(binary,other)
        before=independent(n,binary,other,snap,language,dest,"before")
        checked=native_decision(n,binary,other,":decide_versions_json");after=n.snapshot(binary,other)
        if (checked["individual"]!=snap["individual"] or selected(checked)["kind"]!=op or selected(checked)["target"]!=rev
            or checked["status"]!="committed" or after["owner"]!=snap["owner"] or snap["inactive"]!=after["inactive"]):
            raise ValueError("原生副本选择或身份与提议不符")
        if op=="rewrite":
            if not after["source"].startswith(snap["source"]):raise ValueError("合成范围改变既有程序")
            offset=len(snap["source"]);delta=after["source"][offset:]
            code=[line.strip() for line in delta.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            matched=RULE.fullmatch(code[0]) if len(code)==1 else None
            if not matched or {matched[2],matched[3]}!=ALLOWED or len(delta)>16384:
                raise ValueError("候选超出原有局部词义生成范围")
        else:
            offset,delta=previous["offset"],previous["delta"]
            if snap["source"][offset:offset+len(delta)]!=delta or snap["source"][:offset]+snap["source"][offset+len(delta):]!=after["source"]:
                raise ValueError("回退预演未能精确保留后来输入")
        end=n.history(binary,other)
        if end[:len(historic)]!=historic:raise ValueError("预演改变已有原生历史")
        proof=independent(n,binary,other,after,language,dest,"after")
        statuses=proof["statuses"];expected="POSITIVE" if op=="rewrite" else "UNKNOWN"
        need_signal="requested_learning(current)" if op=="rewrite" else "reconsider_learning(current)"
        if (need_signal not in materials or before["statuses"][need_signal]!="POSITIVE"
            or any(statuses[x]!="POSITIVE" for x in ("identity_restored(zaizai)","receipt_available(zaizai)"))
            or statuses["learned_use(current)"]!=expected
            or (op=="rewrite" and not all(k+"(current)" in materials and before["statuses"][k+"(current)"]=="POSITIVE" for k in ALLOWED))):
            raise ValueError("本轮学习请求、两项语义依据、硬目标或独立结论未对齐")
        return {"actor":snap["individual"],"basis":snap["head"],"expected":after["head"],"action":op,"revision":rev,
                "offset":offset,"delta":delta,"original_events":len(historic),"history_sha256":n.pin(historic),
                "added_events":end[len(historic):],"before":before,"after":proof,"materials":materials,
                "decision_sha256":n.pin(checked)}

def recover(db,d,n,binary,state,snap):
    row=db.execute("SELECT i.job,i.trial FROM lexical25_intents i JOIN deleg25_jobs j ON j.id=i.job WHERE j.phase IN ('issued','uncertain') ORDER BY i.rowid LIMIT 1").fetchone()
    if not row:return False
    t=json.loads(row["trial"]);key=row["job"];events=n.history(binary,state);i=t["original_events"];suffix=t["added_events"]
    if snap["individual"]!=t["actor"] or len(events)<i or n.pin(events[:i])!=t["history_sha256"]:return True
    if suffix and events[i:i+len(suffix)]==suffix:
        with db:
            db.execute("UPDATE lexical25_intents SET committed=1 WHERE job=?",(key,))
            d.status(db,key,"committed","按原始版本和确切新增事件核实原生效果",before=t["basis"],after=snap["head"],
                     result={"selected":t["action"],"revision":t["revision"],"writes_state":True,"head_sha256":t["expected"],"proof":t["after"]["proof_sha256"]})
        return True
    if snap["head"]==t["basis"] and len(events)==i:
        with db:d.status(db,key,"not_recorded","按完整原生历史核实该次未执行，保留原单",before=t["basis"],after=snap["head"])
    return True

def work(db,root,checkpoint=None):
    import delegated25 as d,joint25_agenda_host as a,life3_worker as host,slots31
    if not d.enabled(db):return None
    state=root/"state/individual.pcgm";b=root/"releases/joint25/bin";stamp=state.stat()
    db.execute("CREATE TABLE IF NOT EXISTS lexical25_intents(job TEXT PRIMARY KEY,revision TEXT NOT NULL,action TEXT NOT NULL,trial TEXT NOT NULL,committed INTEGER NOT NULL DEFAULT 0)")
    tag=str(stamp.st_mtime_ns)+"/"+str(stamp.st_size)
    pending=db.execute("SELECT 1 FROM lexical25_intents i JOIN deleg25_jobs j ON j.id=i.job WHERE j.phase IN ('issued','uncertain') LIMIT 1").fetchone()
    if not pending and d.get(db,"lexical_seen")==tag:return None
    slots=slots31.snapshot(db)
    if any(slots[k]["id"]!=name or slots[k]["state"]!="ready" for k,name in (("C","joint25-pcgm"),("L","joint25-cl"))):return None
    n,g=a._engines(root);binary,snap=g.checkstate(b,state)
    if recover(db,d,n,binary,state,snap):return None
    with db:d.put(db,"lexical_seen",tag)
    materials=signals(db,snap)
    if not TRIGGERS.intersection(materials):return None
    choice=native_decision(n,binary,state,":compare_versions_json");opt=selected(choice);op=opt.get("kind")
    if op not in ("rewrite","rollback"):return None
    key=None
    try:
        with n.deadline_scope(3.0):
            trial=prepare(db,n,binary,state,snap,choice,op,b/"cl.exe",materials)
        if host.active("foreground"):
            with db:d.put(db,"lexical_seen","")
            return None
        with db:
            key=d.queue(db,KIND,"host","native-learning-change",{"actor":snap["individual"],"basis":snap["head"]},"已有学习偏好及本地资料触发比较")
            row=d.job(db,key)
            if row["phase"]!="queued":return None
            db.execute("INSERT INTO lexical25_intents(job,revision,action,trial) VALUES(?,?,?,?)",
                       (key,trial["revision"],op,d.packed(trial)))
            d.status(db,key,"issued","原生同版本预演与独立 CL 一致，提交既有局部词义方案",before=snap["head"])
        if checkpoint:checkpoint("issued")
        # The native writer owns this file from its handshake to exit. Hold it across the last head check.
        with subprocess.Popen([binary,"--resume",state],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW) as p:
            import threading
            timer=threading.Timer(4,lambda:p.kill() if p.poll() is None else None);timer.daemon=True;timer.start()
            try:
                hello=p.stdout.readline().decode()
                if not hello.startswith("individual="+snap["individual"]+" ") or n.snapshot(binary,state)["head"]!=snap["head"]:
                    raise ValueError("写入前版本或身份改变")
                result,err=p.communicate(input=b":decide_versions_json\n",timeout=4)
                if p.returncode or err or n.pin(json.loads(result))!=trial["decision_sha256"]:raise ValueError("原生操作需原单对账")
            finally:
                if p.poll() is None:p.kill();p.communicate()
                timer.cancel()
        if checkpoint:checkpoint("after_native")
        after=n.snapshot(binary,state)
        if after["head"]!=trial["expected"]:raise ValueError("正式结果与固定原生预演不同")
        recover(db,d,n,binary,state,after)
        return {"kind":"delegated_lexical_rule","topic":"原生词义规则","summary":"原生选择 "+op+"，修订 "+trial["revision"],
                "receipt":key,"executed":True,"progress":True,"source":"native-versions"}
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
        with db:
            if key:d.status(db,key,"uncertain","按原单对账："+str(exc)[:250],before=snap["head"])
            else:
                key=d.queue(db,KIND,"host","native-learning-change",{"actor":snap["individual"],"basis":snap["head"]},"对当前版本作独立核验")
                if d.job(db,key)["phase"]=="queued":d.status(db,key,"refused",str(exc)[:300],before=snap["head"])
        return {"kind":"delegated_lexical_review","topic":"原生词义规则","summary":str(exc)[:250],"receipt":key,"progress":False,"executed":False}
