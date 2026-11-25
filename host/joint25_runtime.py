"""Registered Windows joint providers. Native PCGM outcomes are the sole source of goal truth."""
from pathlib import Path
import hashlib,json,re,sqlite3,time
import slot31_legacy as compat
import joint25_language as lang
import release25_lexicon as dictionary

LANG="joint25-cl";COG="joint25-pcgm"
class Layout:
    def __init__(self,root):self.install=Path(root);self.release=self.install/"releases/joint25"
    def __truediv__(self,key):
        path=Path(key)
        return (self.release if path.parts and path.parts[0]=="bin" else self.install)/path
def native_read(layout,operation,deadline):
    return compat.read_channel(layout,operation,deadline)
def proof_sources(outcome):
    refs=["pcgm-head:"+outcome["state_revision"],compat.ref(outcome)]
    for sign in ("positive_proof","negative_proof"):
        for node in (outcome.get(sign) or {}).get("nodes",[]):
            if node.get("origin") and str(node["origin"]) not in refs:refs.append(str(node["origin"]))
    return refs[:24]
def conclusion(text,refs,**extras):
    refs=list(dict.fromkeys(refs))[:50]
    return dict(text=text,evidence_refs=refs,**extras)

def cognitive(layout,p,deadline,db):
    rec=p.get("parsed") or {};ctx=p.get("context") or {};case=ctx.get("request","query")
    if not lang.ID.fullmatch(case):raise ValueError("原生请求编号不合法")
    base=["utterance-sha256:"+rec["raw_sha256"],"parser:"+rec["source_release"]]
    session=ctx.get("session","main")
    import clause_read25
    antecedents=clause_read25.antecedents(db,session,rec)
    base.extend("context-utterance:"+item["utterance_id"]+"@sha256:"+item["raw_sha256"] for item in antecedents)
    alts=rec.get("alternatives",[])
    boundary=rec.get("boundary",{})
    import context25
    if boundary.get("decision")!="reject":
        observation=context25.nonfact(rec)
        if observation is not None:
            return conclusion(observation["text"],base+[compat.ref(rec.get("context25",{}))],kind=observation["kind"])
    if boundary.get("decision")=="clarify" and len(alts)<2:
        specific=next((x.get("clarification_question") for x in rec.get("missing",[]) if x.get("clarification_question")),None)
        return conclusion("我还不能确定这句表达的具体指向。"+(specific or "你要核对哪个对象、哪项属性？"),base+[compat.ref(boundary)],kind="clarification")
    if boundary.get("decision") in {"explain","reject"}:
        return conclusion(boundary["reason"],base+[compat.ref(boundary)],kind="scope_"+boundary["decision"])
    if rec.get("disambiguation")!="unique" or len(alts)!=1:
        missing=rec.get("missing") or []
        if len(alts)>1:
            labels=[]
            for i,a in enumerate(alts[:8]):
                label=a.get("display")
                if not label:
                    arg=(a.get("goal") or {}).get("arguments",[])
                    val=str(arg[0]["value"]) if arg else a.get("candidate_id")
                    label={"doc_a":"甲资料","doc_b":"乙资料","shelf_a":"甲架","shelf_b":"乙架","spare_part":"备用件","data_backup":"数据备份"}.get(val,val)
                labels.append(f"{i+1}. {str(label).rstrip('。')}")
            q="你指的是哪一种？"+"；".join(labels)+"。"
            return conclusion(q,base,kind="clarification",choices=labels)
        if rec.get("intent")=="context_introduction":
            entities=[x["raw_bytes_utf8"] for x in rec.get("input_spans",[]) if x.get("kind")=="entity" and x.get("raw_bytes_utf8")]
            return conclusion("本会话记下了"+("、".join(dict.fromkeys(entities)) if entities else "刚才提到的对象")+"。要先核对哪一项？",base,kind="context")
        # Report a versioned dictionary candidate only as lexical evidence. It cannot answer an unrelated question.
        m=next((x for x in rec.get("dictionary_mentions",[]) if x.get("candidate_count",0)>1 and len(x["word"])>=2),None)
        if m and rec["raw_text"].strip().rstrip("？?。") in {m["word"],m["word"]+"是什么意思","什么是"+m["word"]}:
            return conclusion("「"+m["word"]+"」有这些候选义项："+"；".join(f"{v['sense_id']} {v['gloss_zh']}" for v in m["entries"])+"。你指哪个语境？",
                base+["lexicon:"+dictionary.RELEASE_PIN],kind="dictionary_candidates")
        import joint25_materials
        lessons=joint25_materials.find(db,rec["raw_text"])
        if lessons:
            lines=[": cited(sym,sym).",": documented(sym).","documented($x) <- cited($x,$source)."]
            for i,item in enumerate(lessons):lines.append(f"& card{i} cited(c{i},s{lang.sha(item['source']+item['version'])[:24]}).")
            lines.extend(f"? documented(c{i})." for i in range(len(lessons)))
            proof=compat.compile_source(layout,"\n".join(lines)+"\n",deadline)
            if not all(row["status"]=="POSITIVE" for row in proof["results"]):raise ValueError("课程引用未能复验")
            return conclusion(joint25_materials.attribute(lessons),base+[proof["proof_ref"]]+["card:"+x["id"]+"@"+x["version"] for x in lessons],
                              kind="attributed_curriculum",lesson_ids=[x["id"] for x in lessons],citation_evidence=proof["proof"])
        if missing:
            q=next((m["clarification_question"] for m in missing if m.get("clarification_question")),None)
            if q:return conclusion(q,base,kind="clarification")
        return conclusion("我还不能确定这句话对应的命题。你想核对哪个对象、它的哪项属性？",base,kind="parse_gap")
    alt=alts[0];op=alt.get("dispatch_target");goal=alt.get("goal") or {}
    if op=="host:read_only_state_query":
        read=rec["boundary"]["read_query"]
        subject=read["subject"]["surface"];attribute=read["property"]["surface"];location=read.get("location_qualifier")
        typed=clause_read25.mapped(alt,read,lang.vocabulary().get(lang.VERSION))
        if typed:
            alt=typed;goal=typed["goal"]
        else:
            return conclusion(f"要查的是{subject}的「{attribute}」"+(f"，范围限于{location['surface']}" if location else "")+"。目前没有能同时核对这些条件的已登记依据。",base,kind="unmapped_property",literal_request=read)
    if op=="solver:qty_add":
        args=goal.get("arguments") or []
        original=rec.get("query_source_raw",rec["raw_text"])
        proof=compat.call(layout/"bin/pcgm-alpha.exe",["--ask-basic-arithmetic"],deadline,(original+"\n").encode())
        rows=proof.decode().splitlines()
        answer=json.loads(rows[0]) if len(rows)==1 else {}
        vals=[v.get("value") for v in args[:2]]
        if answer.get("status")!="solved" and len(vals)==2 and all(re.fullmatch(r"[0-9]{1,6}",str(i)) for i in vals):
            # The lexical normalizer must recover both same operands from the complete source utterance.
            import discourse25
            q=discourse25.normalized_math(original,vals)
            if q is not None:
                answer=json.loads(compat.call(layout/"bin/pcgm-alpha.exe",["--ask-basic-arithmetic"],deadline,(q+"\n").encode()))
        if answer.get("status")=="solved" and answer.get("proof",{}).get("status")=="POSITIVE":
            checks=answer["proof"]["positive"]["nodes"][0]["checks"]
            if not checks or checks[0]["predicate"]!="qty_add":raise ValueError("缺少原生加法计算依据")
            expressions=[str(x["value"]).split("@")[0] for x in checks[0]["arguments"]]
            if list(map(str,vals))!=expressions[:2]:raise ValueError("解析操作数与原生计算依据不符")
            refs=base+[compat.ref(answer)]
            return conclusion(f"{expressions[0]} 加 {expressions[1]} 等于 {answer['value']}。",refs,kind="native_arithmetic",native=answer)
        return conclusion("这个表达未通过当前整数加法求解器的输入检查。",base,kind="parse_gap")
    if rec.get("intent") in {"quotation","reported_speech","report","conditional","hypothetical","counterfactual"} or alt.get("metadata",{}).get("conditional") or rec.get("attribution"):
        return conclusion("我保留了你给出的转述或条件以及它的来源；当前没有可据此确认的外部事实。",base,kind="reported_only")
    # Resolving a referent corrects a question, not a world observation.
    read_correction = (rec.get("intent") == "correction" and rec.get("resolution") == "explicit_choice" and
                       (rec.get("context25") or {}).get("read_referent_correction") is True and
                       (alt.get("metadata") or {}).get("non_destructive_correction") is True and
                       boundary.get("decision") == "pass" and op == "read-channel:reasoned_outcome")
    if op=="proposal:observe" or (rec.get("intent") in {"assertion","correction","retraction"} and not read_correction):
        return conclusion("已把这次"+({"correction":"更正","retraction":"撤回请求"}.get(rec["intent"],"陈述"))+"连同原文留在本会话。若要改变事实证据，请核对具体来源编号。",base,kind="user_statement")
    if not goal or alt.get("variables"):
        return conclusion("还缺能唯一确定对象或量纲的条件，请补充要比较的对象。",base,kind="missing_arguments")
    asking_negative=goal.get("polarity")=="negative"
    atom=lang.goal_atom(dict(goal,polarity="positive"))
    if not goal["predicate"] in declared(layout,deadline):
        return conclusion("已解析到 "+atom+"，本个体当前载入的规则还未声明这个目标。",base,kind="undeclared")
    if goal["predicate"]=="scoped_claim":
        import verify_sense_version
        lexical_issue=verify_sense_version.for_atom(db,atom)
        if lexical_issue:return conclusion(lexical_issue,base,kind="stale_lexical_version")
        import joint25_evidence
        guard=joint25_evidence.target_guard(db,atom)
        if not guard.get("current"):
            return conclusion(f"来源快照已变化，命题 {alt.get('claim_id','')} 的旧结论需按当前材料复核。",base+[compat.ref(guard)],kind="stale_source",guard=guard)
    out=native_read(layout,"reasoned_outcome "+case+" "+atom,deadline)
    if out.get("schema")!="pcgm-reasoned-outcome-v1" or out.get("source_id")!=compat.identity(layout):
        raise ValueError("原生 outcome 身份或协议不符")
    from zaizai_adapter.stage_d import render_reasoned_outcome
    rendered=render_reasoned_outcome(out)   # Keep the complete native record and Gemini projection in the receipt.
    display=(alt.get("display") or atom).rstrip("。")
    status=out["status"]
    if asking_negative:
        status={"POSITIVE":"NEGATIVE","NEGATIVE":"POSITIVE","UNKNOWN":"UNKNOWN","CONFLICT":"CONFLICT"}[status]
        display="不成立("+display+")"
    text={"POSITIVE":"有正向依据","NEGATIVE":"有反向依据","UNKNOWN":"目前证据不足","CONFLICT":"正反两边都有依据"}[status]+"："+display+"。"
    if status in {"POSITIVE","NEGATIVE","CONFLICT"}:
        origins=[v for v in proof_sources(out)[2:] if v.startswith("obs:")]
        if origins:text+="\n来源 "+"、".join(origins[:6])+"。"
    if status=="UNKNOWN" and out.get("missing"):
        gaps=", ".join(str(x.get("predicate","")) for x in out["missing"][:3]);text+=" 待核对前提："+gaps+"。"
    if alt.get("claim_id"):text+="\n来源命题 "+alt["claim_id"]
    if out.get("question_ticket"):text+="\n原生问询 "+out["question_ticket"]
    if antecedents and clause_read25.FOLLOW_EVIDENCE.search(rec.get("raw_text","")):
        text+="\n承接本会话的「"+antecedents[0]["text"]+"」，本轮已重新核对该命题。"
    return conclusion(text,base+proof_sources(out),kind="reasoned_outcome",native=out,rendered=rendered,
                      claim_id=alt.get("claim_id"),context_sources=antecedents)

def declared(layout,deadline):
    packet=compat.jsoncall(layout/"bin/pcgm-alpha.exe",["--desktop-snapshot",compat.private_state(layout)],deadline)
    if packet["individual"]!=compat.identity(layout):raise ValueError("读取到其他身份")
    return set(re.findall(r"(?m)^\s*:\s*([a-z][a-z_0-9]*)\(",packet["source"]))

def selftest(root,m):
    layout=Layout(root);d=time.monotonic()+5
    if m["slot"]=="L":
        caps=compat.jsoncall(layout/"bin/cl.exe",["capabilities"],d)
        native=compat.compile_source(layout,compat.CHECK_SOURCE,d)
        probe=sqlite3.connect(":memory:");probe.row_factory=sqlite3.Row
        try:rec=lang.parse(probe,{"text":"十六加二十四是多少","context":{"session":"probe","request":"q"}})
        finally:probe.close()
        if not (rec["alternatives"][0]["dispatch_target"]=="solver:qty_add" and caps["release"]=="0.157" and [r["status"] for r in native["results"]]==["POSITIVE","NEGATIVE","UNKNOWN"]):
            raise ValueError("中文解析或原生 CL 核验失败")
        test={"native":native["proof_ref"],"language":compat.ref(rec),"lexicon":dictionary.RELEASE_PIN}
    else:
        st=compat.status(layout,d)
        q=native_read(layout,"agenda",d)
        raw=compat.call(layout/("bin/pcgm-"+st["owner"]+".exe"),["--resume",compat.private_state(layout)],d,b":field_status\n").decode()
        if q["schema"]!="pcgm-work-agenda-v1" or not raw.startswith("individual="+compat.identity(layout)+" ") or "QUERY_ERROR" in raw:
            raise ValueError("原生所有权、已安装几何或议程自检失败")
        test={"agenda":compat.ref(q),"owner":st["owner"],"state":q["revision_sha256"]}
    return {"passed":True,"provider":m["id"],"version":m["version"],"tested":test,"capabilities":m["capabilities"],"time":time.time()}
def handle(root,m,port,p,budget,db):
    layout=Layout(root);deadline=time.monotonic()+budget/1000
    if m["id"]==COG and p.get("joint25_op"):
        import joint25_agenda_host
        return joint25_agenda_host.adapter(root,m,port,p,budget,db)
    if port=="L1":
        if not isinstance(p.get("text"),str) or not p["text"].strip() or len(p["text"])>128000 or not isinstance(p.get("context",{}),dict):
            return {"refused":True,"reason":"表达为空、超长或会话结构不合格"},[compat.ref(p)]
        ctx=p.get("context") or {}
        if any(not isinstance(ctx[k],str) or not lang.ID.fullmatch(ctx[k]) for k in ("session","request") if k in ctx):
            return {"refused":True,"reason":"会话或请求编号格式不符"},[compat.ref(p)]
        import clause_read25
        issue=clause_read25.version_issue(db,p,lang.VERSION)
        if issue:return {"refused":True,"reason":issue},[compat.ref(p)]
        parsed=lang.parse(db,p);return {"parsed":parsed},["utterance:"+parsed["raw_sha256"],"lexicon:"+parsed["source_release"]]
    if port=="L6":
        test=selftest(root,m);return test,[compat.ref(test)]
    if port=="L3":
        out,refs=compat.handle(layout,m,port,p,budget,db)
        cp=dictionary.lookup(p["word"],db=db,limit=12);out.update(proposals=cp["entries"],candidate_count=cp["candidate_count"],
            candidate_release=cp["release_sha256"],candidate_view=cp["view"],pending_count=cp["pending_count"])
        return out,refs+["candidate-index:"+dictionary.RELEASE_PIN]
    if port=="C5" and p.get("parsed") is not None and p.get("observation_id"):
        units=min(budget,int(p.get("budget_ms",0)))
        if p.get("preempt") or units<=0:
            return {"mode":"wait","budget_ms":0,"wake":"host-authorized-budget"},[compat.ref({"preempt":p.get("preempt"),"budget_ms":units})]
        deadline=min(deadline,time.monotonic()+units/1000)
        origin=cognitive(layout,p,deadline,db)
        return {"mode":"ready","budget_ms":min(budget,int(p.get("budget_ms",budget))),"wake":"next_observation","conclusion":origin},origin["evidence_refs"]
    if port=="C4":
        out,refs=compat.handle(layout,m,port,p,budget,db)
        agenda=native_read(layout,"agenda",deadline);out["work_agenda"]=agenda
        return out,refs+[compat.ref(agenda)]
    return compat.handle(layout,m,port,p,budget,db)

def lexical_plan(db,text,session,request):
    import slots31
    q=text.strip().rstrip("。！？?!")
    if not q.startswith("词义 "):return None
    word=q[3:].strip()
    if not word or len(word)>160:return None
    result=slots31.dispatch(db,"L3",{"word":word},input_version=lang.sha(q),owner=session)
    payload=result["output"]
    if payload.get("meanings") or not payload.get("proposals"):return None
    options=payload["proposals"]
    body=f"「{word}」在本机词库中有 {payload['candidate_count']} 个可查候选。\n"+"\n".join(x["sense_id"]+" · "+x["gloss_zh"] for x in options)
    return {"answer":body,"frame_kind":"reply","port_receipts":[result],"candidate_ids":[x["sense_id"] for x in options],
            "source":"DeepSeek 候选词库","candidate_release":payload["candidate_release"]}

def compat_turn(db,text,session):
    q=text.strip().rstrip("。！？?! ").strip()
    previous=db.execute("SELECT plan FROM requests WHERE session=? AND phase='committed' ORDER BY seq DESC LIMIT 1",(session,)).fetchone()
    prior=json.loads(previous[0]) if previous and previous[0] else {}
    if q in {"为什么","依据呢","然后呢","再说明一下","刚才说的那项，再说明一下","为什么这么说","根据是什么"}:
        return not any(x.get("port")=="C5" for x in prior.get("port_receipts",[]))
    if q in {"帮助","你能做什么","使用说明","状态","现在什么状态","你是谁","查看状态","你现在怎么样","在吗","你好","你现在的状态","你现在的状态是什么",
        "最近回执","查看最近回执","给我看最近的回执","回执","词典","词条","问题","有什么不懂","还有什么不知道",
        "比较方案","方案比较","采纳最优方案","切换端点","切换 A/B","开启词条自学","关闭词条自学"}:return True
    if q.startswith(("词义 ","采用 ","撤回词条 ","证明 ","求证 ","编译文件 ","编译\n","CL\n","回忆 ","记住 ","选择 ",
                     "提议词条 ","采集 ","撤回观察 ","恢复观察 ","回答 ","学习 ","转译 ","咨询 ")):return True
    if q.startswith(("我指的是","我是说","我的意思是")) and prior.get("gap") and not prior.get("port_receipts"):return True
    if q.startswith("PCGM "):
        # Raw state-changing administration remains explicit; free prose is never a native command.
        return True
    return bool(db.execute("SELECT 1 FROM senses WHERE session=? AND term=? AND status='adopted'",(session,q)).fetchone())

