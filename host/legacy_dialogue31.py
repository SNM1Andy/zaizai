"""Transition dialogue adapter for the two approved legacy engines.

The host routes a turn here only after validating both bindings.
"""
import json
import os
import re
from pathlib import Path
import native as n
import slots31
from advisor_client import consult
from service import FOLLOW, HELP, ID, last, plan

def head_or_none():
    try:return n.sha(n.SAVE.read_bytes())
    except FileNotFoundError:return None

def lexicon(db,word):
    value=slots31.dispatch(db,"L3",{"word":word})["output"]
    return value["meanings"],value["proof"]

def compile_text(db,source):
    result=slots31.dispatch(db,"L2",{"source":source})["output"]
    if result.get("refused"):raise ValueError(result["reason"])
    return result

def proof_for(db,atom):
    return n.proof_for(atom,compile_source=lambda source:compile_text(db,source))

def short_proof(p):
    return "\n".join(n1["origin"] for r in p["results"] for sign in ("positive","negative")
                     for n1 in r.get(sign,{}).get("nodes",[]) if n1["origin"].startswith("obs:"))
def lookup(db,session,text):
    return db.execute("""SELECT * FROM senses WHERE session=? AND term=? AND status='adopted'
      ORDER BY version DESC""",(session,text)).fetchall()
def review_term(db,cid,term,word,explicit,rid):
    meanings,lex=lexicon(db,word)
    supported=word in {"状态","最近回执"} or len(meanings)==1
    local_hints={name for name,stem in (("最近回执","回执"),("状态","状态")) if stem in term}
    correlated=explicit or local_hints=={word}
    signals=["term_candidate"]
    if supported:signals.append("term_grounded")
    if correlated:signals.append("term_local_match")
    if len(local_hints)>1 or len(meanings)>1:signals.append("term_conflict")
    head=json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))["head"]
    batch="b"+rid[1:25]
    cmd=":observation_batch "+batch+" "+head
    for i,signal in enumerate(signals):
        cmd+=f" ; observe e{rid[1:25]}_{i} {signal}({cid})"
    receipt=n.execute(cmd)
    result=proof_for(db,"term_adopt("+cid+")")
    admissible=("positive=CLEAN_WITNESS negative=NO_SUPPORT" in result["integrity"] and
                result["proof"]["results"][0]["status"]=="POSITIVE")
    return admissible,{"batch":receipt,"basis":head,"term":word,"lexicon":lex,"result":result,
                       "corroboration":"user confirmation" if explicit else sorted(local_hints)}
def interpret(db,r,legacy):
    q=r["question"].strip();key=q.rstrip("。！？?! ").strip()
    session=r["session"];rid=r["id"]
    aliases=json.loads((n.ROOT/"host/dialogue-aliases.json").read_bytes())
    if key in {"开启词条自学","关闭词条自学"}:
        enabled=key.startswith("开启")
        return plan("已开启本会话的词条自学。输入「词义」和要查的词即可。" if enabled else "已关闭本会话的词条自学。",
                    change=["option","lexical-learning:"+session,"on" if enabled else "off"])
    if key.startswith(("我指的是","我是说","我的意思是")):
        previous=last(db,session)
        gap=json.loads(previous["plan"]).get("gap") if previous else None
        if not gap:return plan("这次会话没有待澄清的表达。你想说明哪个词？")
        word=re.sub(r"^(我指的是|我是说|我的意思是)\s*","",key).strip("「」“” ")
        cid="c"+rid[1:17]
        allowed,review=review_term(db,cid,gap,word,True,rid)
        suggestion=dict(canonical=word,domain="本会话",source="用户澄清 "+rid,explanation="按同一会话中提出的缺口澄清")
        return plan(("我记下了这个用法。" if allowed else "这个解释仍有歧义，保留供复核。")+f"候选 {cid}。",
                    change=["candidate",cid,gap,suggestion,"adopted" if allowed else "candidate"],review=review)
    if key.startswith(("请解释","解释一下","什么叫")):
        word=re.sub(r"^(请解释|解释一下|什么叫)\s*","",key).strip("「」“” ")
        key="词义 "+word
    if key.startswith("你还记得") and key.endswith("吗"):
        key="回忆 "+key[4:-1].strip("「」“” ")
    senses=lookup(db,session,key)
    if len(senses)>1:return plan("这个表达有多个已采用的义项，请指定使用场景。\n"+"\n".join(x["scope"]+" · "+x["word"] for x in senses))
    if senses:key=senses[0]["word"]
    key={"status":"状态","receipt":"最近回执"}.get(aliases.get(key),key)
    if key in {"状态","现在什么状态","你是谁","查看状态","你现在怎么样","在吗","你好","你现在的状态","你现在的状态是什么"}:
        s=n.status();proof=proof_for(db,"identity_restored(zaizai)")
        return plan(f"我是再再。原存档是第 {legacy['generation']} 代、tick {legacy['tick']}。当前 PCGM 在 {s['owner']} 端点，已记录 {s['state']['event']} 个事件。",
                    proof=proof,action="focus identity_restored(zaizai)")
    if key in {"最近回执","查看最近回执","给我看最近的回执","回执"}:
        prior=last(db,session)
        return plan("原存档的 M5 回执为 "+legacy["receipt"]+("。\n本会话上一条已提交请求为 "+prior["id"] if prior else "")+"。",
                    proof=proof_for(db,"receipt_available(zaizai)"),action="focus receipt_available(zaizai)")
    if key in FOLLOW:
        previous=last(db,session)
        if previous:
            context=json.loads(previous["plan"])
            if context.get("meanings"):
                return plan("刚才查的是「"+context["word"]+"」。依据来自 CL 词典包。\n"+
                            "\n".join(label+"（"+sid+"）" for sid,label in context["meanings"]),
                            **{k:context[k] for k in ("word","meanings","lexical_proof")})
        return plan("",action="why",render="follow")
    if key.startswith("选择 "):
        previous=last(db,session)
        context=json.loads(previous["plan"]) if previous else {}
        sid=key[3:].strip()
        selected=[item for item in context.get("meanings",[]) if item[0]==sid]
        if not selected:raise ValueError("这个编号不在当前会话上一轮的候选义项中")
        return plan("本轮采用「"+selected[0][1]+"」。",word=context["word"],meanings=selected,lexical_proof=context["lexical_proof"])
    if key.startswith("提议词条 "):
        parts=[x.strip() for x in key[5:].split("|")]
        if len(parts)!=3 or not all(parts):raise ValueError("请用「提议词条 表达 | 标准词 | 使用场景」")
        term,word,scope=parts
        cid="c"+rid[1:17]
        a=dict(canonical=word,domain=scope,source="本地会话 "+rid,explanation="本地提出，待 CL 核验")
        return plan(f"词条候选 {cid} 已记录。输入「采用 {cid}」核验。",change=["candidate",cid,term,a])
    if key in {"帮助","你能做什么","使用说明"}:return plan(HELP)
    if key.startswith("记住 "):
        name,sep,body=key[3:].partition("=")
        if not sep or not name.strip() or not body.strip():raise ValueError("请用「记住 名称 = 内容」")
        return plan("记住了「"+name.strip()+"」。",change=["remember",name.strip(),body.strip()])
    if key.startswith("回忆 "):
        name=key[3:].strip()
        found=db.execute("SELECT body,request FROM memory WHERE name=?",(name,)).fetchone()
        if found:return plan(f"{name}：{found['body']}\n来源请求 {found['request']}")
        records=n.legacy_memory.records(name)
        if records:
            proof=proof_for(db,"r28_remembers("+records[0]["target"]+")")
            return plan("\n".join(f"旧存档记得 {x['target']}，位置 {x['claim']['position']}，观测值 {x['claim']['value']}。反馈记录 {x['feedback_ref']['index']}，摘要 {x['claim_hash']}。" for x in records),
                        legacy_records=records,proof=proof)
        return plan(f"还没有「{name}」的长期记忆。")
    if key in {"旧存档","旧记忆","原来的记忆"}:
        view=n.legacy_memory.overview()
        return plan(f"第 {view['generation']} 代存档保留了 {len(view['observed'])} 个观察对象、{len(view['memory_targets'])} 条语义记忆和 {view['events']} 个事件。"
                    +"\n可以输入「回忆 对象编号」查看依据。对象有 "+"、".join(view["observed"])+"。",legacy_state=view)
    if key in {"问题","有什么不懂","还有什么不知道"}:
        text=n.execute(":ask");feed=n.readcmd("question_feed 0 32")
        rows=feed["results"]
        return plan("\n".join(f"{e['id']} · {e['status']} · {atom(e['needed'])}\n答复版本 {e['request_sha256']}" for e in rows) or "当前没有待求证前提。",evidence=feed,native_result=text)
    if key.startswith("回答 "):
        parts=key.split(maxsplit=4)
        if len(parts)!=5:raise ValueError("需要题号、版本、来源标识和证据原子")
        _,qid,pin,source,fact=parts
        if not ID.fullmatch(qid) or not re.fullmatch("[0-9a-f]{64}",pin) or not re.fullmatch("[a-z][a-z0-9_]{0,23}",source) or not n.CLAIM.fullmatch(fact.lstrip("!")):
            raise ValueError("答复地址、来源或证据格式错误")
        name="reply_"+rid[:30]
        path=n.STATE/"incoming"/(name+".answer")
        packet=f"PCGM_ANSWER_1 {n.IDENTITY} {qid} {source} {pin}\n{fact}\n".encode()
        if path.exists() and path.read_bytes()!=packet:raise ValueError("答复文件内容冲突")
        if not path.exists():
            tmp=path.with_suffix(".pending");tmp.write_bytes(packet);os.replace(tmp,path)
        resp=n.execute(":answer_packet "+name)
        return plan(resp,evidence=n.readcmd("question "+qid))
    if key.startswith("采集 "):
        parts=[x.strip() for x in key[3:].split("|")]
        if len(parts)<2 or not parts[0] or len(parts)>9:raise ValueError("用「采集 来源 | 观察号 原子」，每批至多八条")
        source,*items=parts
        readings=[];seen=set();prior=[]
        for item in items:
            label,space,fact=item.partition(" ")
            if not space or not ID.fullmatch(label) or not n.CLAIM.fullmatch(fact.lstrip("!")) or label in seen:
                raise ValueError("观察号或原子不符合声明格式")
            seen.add(label)
            old=db.execute("SELECT * FROM samples WHERE id=?",(label,)).fetchone()
            if old:
                if old["atom"]!=fact or old["source"]!=source:raise ValueError("同一观察号的内容或来源发生变化")
                prior.append(old["receipt"])
            else:readings.append([label,fact])
        if not readings:return plan("已收过这批观察。\n"+"\n".join(dict.fromkeys(prior)))
        head=json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))["head"]
        cmd=":observation_batch b"+rid[1:26]+" "+head+"".join(f" ; observe {i} {f}" for i,f in readings)
        receipt=n.execute(cmd)
        return plan(receipt,change=["samples",source,readings,r["started"],receipt])
    if key.startswith(("撤回观察 ","恢复观察 ")):
        action,_,label=key.partition(" ")
        if not ID.fullmatch(label):raise ValueError("需要观察号")
        return plan(n.execute((":withdraw " if action=="撤回观察" else ":restore ")+label))
    if key in {"比较方案","方案比较","采纳最优方案"}:
        cmd=":decide_versions_parallel_json" if key=="采纳最优方案" else ":compare_versions_parallel_json"
        decision=json.loads(n.execute(cmd))["decision"]
        return plan("本轮取舍："+decision["status"]+"。\n"+"\n".join(
            f"{o['kind']} · 硬约束{'通过' if o['eligible'] else '未通过'} · 满足偏好 {o['wishes']} 项"
            for o in decision["options"]),decision=decision)
    if key.startswith("证明 ") or key.startswith("求证 "):
        target=key.split(maxsplit=1)[1].strip().rstrip(".")
        result=proof_for(db,target);status=result["proof"]["results"][0]["status"]
        declared=re.findall(r"(?m)^\s*\?\s*(.+?)\.\s*$",json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))["source"])
        if status=="UNKNOWN" and target in declared:
            questions=n.execute(":ask")
            missing=[line for line in questions.splitlines() if line.startswith("question ") and (" "+target+" ") in line]
            if missing:
                qids=[line.split()[1] for line in missing]
                packets=[n.readcmd("question "+qid)["results"][0] for qid in qids]
                return plan(f"{target} 目前证据不足。"+"\n"+"\n".join(
                    f"问题 {e['id']} 需要 {atom(e['needed'])}，答复版本 {e['request_sha256']}" for e in packets),
                    proof=result,questions=packets,action="focus "+target)
        return plan(f"{target} 的结果是 {status}。\n{result['integrity']}",proof=result,
                    **({"action":"focus "+target} if target in declared else {}))
    if q.startswith("编译文件 ") or q.startswith("编译\n") or q.startswith("CL\n"):
        if q.startswith("编译文件 "):
            path=Path(q[5:].strip().strip('"')).resolve(strict=True)
            source=path.read_text(encoding="utf-8-sig")
        else:source=q.partition("\n")[2]
        proof=compile_text(db,source)
        return plan("\n".join(atom(x["goal"])+" "+x["status"] for x in proof["proof"]["results"]) or "编译通过。此模块没有声明查询目标。",proof=proof)
    if key in {"词典","词条"}:
        return plan("基础词典有 31 个义项。输入「词义」加一个词查询，例如「词义 代表」。")
    if key.startswith("词义 "):
        term=key[3:].strip()
        learned=lookup(db,session,term)
        if learned:
            return plan("\n".join(f"「{x['term']}」在{x['scope']}指「{x['word']}」。来源 {x['source']}，版本 {x['version']}。" for x in learned),
                        learned=[x["id"] for x in learned])
        auto=db.execute("SELECT value FROM options WHERE name=?",("lexical-learning:"+session,)).fetchone()
        pending=db.execute("SELECT id,status,word FROM senses WHERE session=? AND term=? ORDER BY rowid DESC LIMIT 1",(session,term)).fetchone()
        if pending and pending["status"]=="candidate":
            return plan(f"「{term}」有一项待核验的解释「{pending['word']}」。候选 {pending['id']}，可以补充本地依据。",gap=term)
        if auto and auto[0]=="on" and 0<len(term)<=40 and not pending and not lexicon(db,term)[0]:
            key="学习 "+term
    if key.startswith(("咨询 ","学习 ","转译 ")):
        term=key.partition(" ")[2].strip()
        existing,_=lexicon(db,term)
        if existing:
            return plan("本地 CL 词典已有义项。\n"+"\n".join(label for _,label in existing))
        try:a=consult(term,rid)
        except (RuntimeError,OSError) as e:
            return plan(f"咨询未取得可用答复，缺词仍待澄清。{e}",gap=term,provider="unavailable")
        cid="c"+rid[1:17]
        if key.startswith("学习 "):
            adopted,review=review_term(db,cid,term,a["canonical"],False,rid)
            disposition="已核验采用" if adopted else "依据不足，保留为候选"
            return plan(f"「{term}」对应「{a['canonical']}」的建议{disposition}。\n{a['explanation']}\n词条 {cid}",
                        change=["candidate",cid,term,a,"adopted" if adopted else "candidate"],review=review,
                        gap=term,provider=a["source"])
        return plan(f"DSHarness 建议把「{term}」理解为「{a['canonical']}」。{a['explanation']}\n候选号 {cid}，适用场景 {a['domain']}。输入「采用 {cid}」可在本会话核验采用。",
                    change=["candidate",cid,term,a],gap=term,provider=a["source"])
    if key.startswith(("采用 ","撤回词条 ")):
        cmd,_,cid=key.partition(" ");item=db.execute("SELECT * FROM senses WHERE session=? AND id=?",(session,cid)).fetchone()
        if not item:raise ValueError("本会话没有该词条候选")
        if cmd=="撤回词条":
            snapshot=json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))
            inactive=set(snapshot["inactive"])
            signal_rows=re.findall(r"(?m)^& (e[a-f0-9]+_[0-9]) term_(?:candidate|local_match|grounded|conflict)\("+cid+r"\)\.",snapshot["source"])
            active=[i for i in signal_rows if i not in inactive]
            for offset in range(0,len(active),8):
                head=json.loads(n.run(n.exe("alpha"),"--desktop-snapshot",n.SAVE))["head"]
                n.execute(":observation_batch b"+rid[1:23]+"_"+str(offset)+" "+head+
                          "".join(" ; withdraw "+i for i in active[offset:offset+8]))
            return plan(f"已撤回词条 {cid}。",change=["sense_status",cid,"withdrawn"],review=proof_for(db,"term_adopt("+cid+")"))
        word=item["word"]
        approved,review=review_term(db,cid,item["term"],word,True,rid)
        if not approved:return plan("标准词仍有歧义或缺少本地依据，已保留候选。",review=review)
        return plan("已采用「"+item["term"]+"」对应的「"+word+"」，限当前会话。",review=review,
                    change=["sense_status",cid,"adopted"])
    if key in {"切换端点","切换 A/B"}:
        switch=n.switch();return plan(f"已从 {switch['from']} 切换到 {switch['to']}，原身份和会话已恢复。",handoff=switch)
    if q.startswith("PCGM "):
        cmd=q[5:].strip()
        if not cmd:raise ValueError("缺少原生命令")
        out=n.execute(cmd)
        return plan(out or "原生命令已完成。",native_command=cmd)
    if key.startswith("词义 "):word=key[3:].strip()
    else:word=key
    meanings,proof=lexicon(db,word)
    if meanings:
        intro="有多个义项。用「选择 义项编号」指定当前场景。" if len(meanings)>1 else "的词条如下。"
        return plan(f"「{word}」"+intro+"\n"+"\n".join(f"{label}（{sense}）" for sense,label in meanings),
                    lexical_proof=proof,meanings=meanings,word=word)
    return plan(f"我还不能确定「{word}」的意思。你指的是哪件事？如需词义建议，可以输入「咨询 {word}」。",gap=word)
def atom(obj):
    return ("!" if obj.get("polarity")=="negative" else "")+obj["predicate"]+"("+",".join(str(x["value"]) for x in obj["arguments"])+")"
