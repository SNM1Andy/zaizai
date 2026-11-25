"""Auditable compatibility implementation for the two optional, pinned Windows components."""
import base64
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

ID=re.compile(r"[a-z][a-z0-9_]{0,46}")
GOAL=re.compile(r'[a-z][a-z0-9_]{0,47}\([^()\r\n]{1,900}\)')
LEX_PIN="0109b3b1ebdc047765d5bfa0b8df815e961c509869394b0d1650d91b33c9eaaf"
CHECK_SOURCE=": slot_check(sym).\n& yes slot_check(x).\n& no !slot_check(y).\n? slot_check(x).\n? slot_check(y).\n? slot_check(z).\n"
def sha(b):return hashlib.sha256(b).hexdigest()
def packed(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def ref(obj):return "sha256:"+sha(packed(obj).encode())
class InputRejected(ValueError):pass

def call(exe,argv,deadline,data=b""):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError("适配器预算已尽")
    try:
        p=subprocess.run([str(exe),*map(str,argv)],input=data,capture_output=True,timeout=remaining,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:raise TimeoutError("旧件调用超时") from exc
    if p.returncode:
        detail=(p.stderr or p.stdout).decode("utf8","replace")[:600] or f"旧件退出 {p.returncode}"
        if (exe.name.lower()=="cl.exe" and list(argv[:1])==["json"] and p.returncode in (1,2)
                and re.search(r"\.cl:\d+(?::\d+)?:",detail)):
            raise InputRejected(re.sub(r"^.*?\.cl:", "源码行 ", detail).strip())
        raise RuntimeError(detail)
    return p.stdout
def jsoncall(exe,args,deadline,data=b""):
    return json.loads(call(exe,args,deadline,data))
def compile_source(root,source,deadline):
    if not isinstance(source,str) or len(source.encode())>2*1024*1024:raise ValueError("源码大小或类型不合格")
    with tempfile.TemporaryDirectory(prefix="zaizai-language-") as d:
        f=Path(d)/"input.cl";f.write_bytes(source.encode())
        proof=jsoncall(root/"bin/cl.exe",["json",f],deadline)
    if proof.get("engine")!="cl":raise RuntimeError("旧编译器标识错误")
    return {"source_sha256":sha(source.encode()),"proof":proof,"results":proof["results"],"proof_ref":ref(proof)}
def lexicon(root,word,deadline):
    if not isinstance(word,str) or not 0<len(word)<=512:raise ValueError("词条大小或类型不合格")
    lex=root/"lexicon"
    labels=re.findall(r'&\s+\w+\s+label_entry\((zh|en),("(?:[^"\\]|\\.)*"|[\w-]+),(\w+),(\w+)\)',(lex/"lexicon_core.cl").read_text(encoding="utf8"))
    value=lambda s:json.loads(s) if s.startswith('"') else s
    ids=sorted({sense for lang,label,sense,form in labels if value(label).casefold()==word.casefold()})
    if not ids:return {"meanings":[],"proof":None,"ambiguous":False,"proposals":[]}
    goals=list(dict.fromkeys(f"lexical_sense({lang},{label},{sense})" for lang,label,sense,form in labels if sense in ids and value(label).casefold()==word.casefold()))
    with tempfile.TemporaryDirectory(prefix="zaizai-lex-") as t:
        path=Path(t)/"goals";path.write_text("\n".join(goals)+"\n",encoding="utf8")
        proof=jsoncall(root/"bin/cl.exe",["package-prove",lex/"lexicon_core.clpkg",LEX_PIN,path],deadline)
    if any(v["status"]!="POSITIVE" for v in proof["results"]):raise RuntimeError("固定词典复验失败")
    return {"meanings":[[sense," / ".join(value(label) for lang,label,i,form in labels if i==sense and form=="preferred")] for sense in ids],
            "proof":proof,"ambiguous":len(ids)>1,"proposals":[]}
def private_state(root):return root/"state/individual.pcgm"
def read_channel(root,query,deadline):
    obj=jsoncall(root/"bin/pcgm-alpha.exe",["--read-channel",private_state(root)],deadline,("slot31 "+query+"\n").encode())
    if obj.get("protocol")!="pcgm-read-v1" or obj.get("id")!="slot31" or not obj.get("ok"):raise RuntimeError("旧认知件读取协议异常")
    return obj["payload"]
def identity(root):
    return json.loads((root/"state/native/joint-reopen.json").read_bytes())["identity"]
def status(root,deadline):
    result=read_channel(root,"status",deadline)
    if result["owner"] not in {"alpha","beta"} or result["state"]["individual"]!=identity(root):raise RuntimeError("旧认知件身份或所有者不符")
    return result
def selftest(root,m,deadline=None):
    d=deadline if deadline is not None else time.monotonic()+4
    if m["slot"]=="L":
        caps=jsoncall(root/"bin/cl.exe",["capabilities"],d)
        result=compile_source(root,CHECK_SOURCE,d)
        ok=caps.get("release")==m["version"] and [r["status"] for r in result["results"]]==["POSITIVE","NEGATIVE","UNKNOWN"]
        test={"signed_goals":result["proof_ref"]}
    else:
        caps=[jsoncall(root/("bin/pcgm-"+role+".exe"),["--capabilities"],d) for role in ("alpha","beta")]
        st=status(root,d)
        native_path=root/("bin/pcgm-"+st["owner"]+".exe")
        handshake=call(native_path,["--resume",private_state(root)],d,b"").decode()
        if not handshake.startswith("individual="+identity(root)+" "):
            raise ValueError("运行件不能作为这个存档的当前写入端")
        ok=all(x.get("release")==m["version"] for x in caps) and bool(st["state"]["individual"])
        test={"opaque_checkpoint":sha(private_state(root).read_bytes()),"readback":ref(st)}
    return {"passed":bool(ok),"provider":m["id"],"version":m["version"],"tested":test,"capabilities":m["capabilities"],"time":time.time()}

def handle(root,m,port,p,budget,db):
    d=time.monotonic()+budget/1000
    sources=["adapter:"+m["id"]+"@"+m["version"]]
    if port=="L6":
        out=selftest(root,m,d);sources.extend(out["tested"].values());return out,sources
    if port=="L2":
        if p.get("operation")=="offer_eligibility":
            offers=p.get("offers")
            if not isinstance(offers,list) or len(offers)>64 or not all(isinstance(x,dict) and isinstance(x.get("id"),str) and type(x.get("available")) is bool for x in offers):
                raise ValueError("资格快照格式异常")
            names=[x["id"] for x in offers]
            if len(set(names))!=len(offers):raise ValueError("资格快照含重复候选编号")
            # Untrusted labels never become CL source. An explicitly unavailable task receives counterevidence.
            lines=[": available(sym).",": eligible(sym).","eligible($t) <- available($t).","!eligible($t) <- !available($t)."]
            for i,x in enumerate(offers):lines.append(f"& obs{i} "+("" if x["available"] else "!")+f"available(t{i}).")
            lines.extend(f"? eligible(t{i})." for i in range(len(offers)))
            out=compile_source(root,"\n".join(lines)+"\n",d)
            out["results"]=[dict(row,subject=names[int(row["goal"]["arguments"][0]["value"][1:])]) for row in out["results"]]
            return out,[out["proof_ref"],ref(offers)]
        try:out=compile_source(root,p["source"],d)
        except InputRejected as exc:return {"refused":True,"reason":str(exc)},["sha256:"+sha(p["source"].encode())]
        return out,[out["proof_ref"],"sha256:"+out["source_sha256"]]
    if port=="L5":
        old=p.get("receipt") or {};previous=old.get("output",old)
        expected=p.get("proof_ref") or previous.get("proof_ref")
        out=compile_source(root,p["source"],d)
        if not expected or (previous.get("source_sha256") and previous["source_sha256"]!=out["source_sha256"]):raise ValueError("复验输入版本与原回执不同")
        return dict(out,matches=expected==out["proof_ref"]),[out["proof_ref"],"sha256:"+out["source_sha256"]]
    if port=="L3":
        out=lexicon(root,p["word"],d);return out,["sha256:"+LEX_PIN]+([ref(out["proof"])] if out["proof"] else [])
    if port=="L1":
        text=p.get("text","")
        if not isinstance(text,str) or not text.strip():return {"refused":True,"reason":"表达为空"},sources
        text=text.strip()
        if GOAL.fullmatch(text):return {"parsed":{"kind":"native_goal","goal":text}},["grammar:legacy-goal/1",ref(text)]
        if len(text)>512:return {"refused":True,"reason":"旧解析器不支持该表达"},sources
        found=lexicon(root,text,d)
        if not found["meanings"]:return {"refused":True,"reason":"当前词典和原生目标语法无法解析该表达"},["sha256:"+LEX_PIN]
        return {"parsed":{"kind":"lexical_senses","term":text,"meanings":found["meanings"],"ambiguous":found["ambiguous"]}},["sha256:"+LEX_PIN,ref(found["proof"])]
    if port=="L4":
        info=p.get("conclusion") or {}
        refs=info.get("evidence_refs") or info.get("sources") or []
        if not isinstance(info.get("text"),str) or not info["text"].strip() or not isinstance(refs,list) or not refs:
            return {"refused":True,"reason":"认知槽未提供有来源的结论"},sources
        # The compatibility renderer carries the prior conclusion and caveats verbatim.
        limits=info.get("limits",[])
        if isinstance(limits,str):limits=[limits]
        if not isinstance(limits,list) or not all(isinstance(x,str) for x in limits):raise ValueError("结论适用范围格式不合格")
        return {"text":"\n".join([info["text"],*limits])},refs
    if port=="C1":
        event=p["id"]
        if not all(p.get(k) is not None for k in ("source","speaker","channel","at","content")):raise ValueError("观察缺少来源、时间、说话人、通道或内容")
        if not all(isinstance(p[k],str) and p[k] for k in ("source","speaker","channel")) or not isinstance(p["at"],(int,float)):
            raise ValueError("观察来源或时点格式异常")
        return {"accepted":True,"id":event,"frame_ref":ref(p)},[p["source"],ref(p)]
    if port=="C2":
        return dict(p),sources
    if port=="C3":
        if p.get("purpose")=="lesson-candidate":
            from legacy_workbook31 import synthesize
            if set(p)!={"purpose","training"} or not isinstance(p["training"],list):raise ValueError("规则候选只能接收训练样本")
            return {"candidates":[],"lesson_candidate":synthesize(p["training"])},["compatibility:legacy-learning-rules",ref(p["training"])]
        offers=p.get("offers",[]);proofs=p.get("evidence_by_lane",{})
        if not isinstance(offers,list) or len(offers)>64 or not isinstance(proofs,dict):raise ValueError("工作候选格式不合格")
        candidates=[];refs=[]
        # These are the historical host's declared baseline scores, not learned PCGM scores.
        for offer in offers:
            ident=offer["id"];proof=proofs.get(ident) or {}
            pr=proof.get("ref") or proof.get("proof_ref")
            if not pr or ident not in ("study","flow","native","integration"):continue
            intrinsic={"study":.72,"flow":.69,"native":.83}.get(ident)
            if intrinsic is None:
                backlog=max(0,int(offer.get("demand_count",p.get("backlog",0))))
                intrinsic=.60+min(.4,backlog/42)+(.18 if p.get("resource_pressure") else 0)
            candidates.append({"id":ident,"base_score":intrinsic,"cost":offer.get("cost",1),"proof_ref":pr,
                               "basis":"legacy-host-lane-prior/3.0"})
            refs.append(pr)
        return {"candidates":candidates,"basis":"legacy-host-lane-prior/3.0"},(refs or sources)
    if port=="C4":
        page=read_channel(root,"question_feed 0 32",d);questions=[]
        for q in page.get("results",[]):
            questions.append({"id":q["id"],"native":q,"goal":q.get("needed"),"attempts":["已查原生问题和活动证据"],
                 "hypothesis":None,"confidence":None,"blocker":"缺少关联证据","changes_if":"新增或撤回一个与本题版本匹配的来源",
                 "answer_format":"题号、版本、证据来源及原子","source":"pcgm:"+q["id"]})
        return {"questions":questions},[ref(page)]
    if port=="C5":
        units=max(0,min(budget,int(p.get("budget_ms",0))))
        mode="wait" if p.get("preempt") or not p.get("has_work") else ("ready" if units else "shelve")
        return {"mode":mode,"budget_ms":units,"wake":"host_event_or_next_budget",
                "conclusion":None,"reason":"旧件只声明有界调度；未产生面向用户的新结论"},sources
    if port=="C6":
        st=status(root,d)
        return {"integrity":None,"unresolved_weight":None,"prediction_error":None,"information_gain":None,
                "missing":["integrity","unresolved_weight","prediction_error","information_gain"],
                "observed":{"identity_verified":True,"event":st["state"]["event"]}},[ref(st)]
    if port=="C7":
        rid=p["round_id"]
        rows=db.execute("""SELECT port,input_pin,output FROM slot31_port_receipts
                 WHERE adapter=? AND event_id=? ORDER BY port""",(m["id"],rid)).fetchall()
        return {"round_id":rid,"entries":[{"port":r[0],"input_hash":r[1],"receipt_ref":ref(json.loads(r[2]))} for r in rows]},["host-receipts:"+str(rid)]
    if port=="C8":
        session,rid,action=p["session"],p["request"],p["action"]
        if not all(isinstance(x,str) and ID.fullmatch(x) for x in (session,rid)) or not isinstance(action,str) or "\n" in action or "\r" in action:
            raise ValueError("对话幂等操作或请求号无效")
        if p["phase"]=="prepare":return {"phase":"prepared","request":rid,"intent":ref([session,rid,action])},sources
        if p["phase"]!="commit":raise ValueError("未知 C8 阶段")
        # Under the host writer, reuse a current owner only when this turn actually observed it.
        import native as n
        owner=n._owner.get() or status(root,d)["owner"]
        data=f":chat {session} {rid} {action}\n".encode()
        statepin=sha(private_state(root).read_bytes()) if m.get("provider_type")=="joint-native" else None
        raw=call(root/("bin/pcgm-"+owner+".exe"),["--resume",private_state(root)],d,data).decode().splitlines()
        if not raw or not raw[0].startswith("individual="+identity(root)+" "):raise ValueError("C8 原生回执身份不符")
        raw=raw[1:]
        limits={"QUERY_ERROR dialogue session limit","QUERY_ERROR dialogue turn limit"}
        if statepin and len(raw)==1 and raw[0] in limits and sha(private_state(root).read_bytes())==statepin:
            return {"refused":True,"reason":raw[0],"confirmed_no_write":True,"state_sha256":statepin},["private-state:"+statepin]
        expected={f"chat_{phase} {session} {rid}":phase for phase in ("committed","replayed")}
        if not raw or raw[0] not in expected:raise ValueError("C8 原生回执与请求不符")
        if action.startswith("record ") and raw[1:]!=["recorded "+action.split(" ",1)[1]]:raise ValueError("C8 原生动作摘要不符")
        body="\n".join(raw);return {"phase":expected[raw[0]],"request":rid,"raw":body},["native-receipt:"+sha(body.encode())]
    if port=="C9":
        st=status(root,d);state=private_state(root)
        if state.stat().st_size>24*1024*1024:raise ValueError("原生状态超过单帧导出上限")
        saved=state.read_bytes();pin=sha(saved)
        op=p.get("operation","describe")
        output={"operation":op,"state_format":m["state_format"],"state_sha256":pin,
                "identity":st["state"]["individual"],"event":st["state"]["event"]}
        if op=="save":
            if len(saved)>1024*1024:raise ValueError("请使用宿主流式检查点备份工具")
            output["opaque_base64"]=base64.b64encode(saved).decode("ascii")
        elif op=="geometry_status":
            field=root/"state/modules/geometry.cl"
            raw=call(root/("bin/pcgm-"+st["owner"]+".exe"),["--resume",state],d,b":field_status\n").decode().splitlines()
            if len(raw)!=2 or not raw[0].startswith("individual="+identity(root)+" ") or not raw[1].startswith("field_tick="):
                return {"refused":True,"reason":"旧槽件没有已初始化的原生几何状态"},["private-state:"+pin]
            if sha(state.read_bytes())!=pin:raise RuntimeError("只读场状态查询期间存档改变")
            output.update(field_status=raw[1],module_sha256=sha(field.read_bytes()))
        elif op=="restore":
            supplied=base64.b64decode(p["opaque_base64"],validate=True)
            if p.get("state_format")!=m["state_format"] or p.get("state_sha256")!=sha(supplied):raise ValueError("状态封包摘要或格式不符")
            if supplied!=saved:raise ValueError("旧件已有其他状态；需要使用协调存档还原，不能覆盖后续回执")
            output["reopened"]=True
        elif op!="describe":raise ValueError("未知状态操作")
        return output,["private-state:"+pin]
    raise ValueError("未登记端口")

