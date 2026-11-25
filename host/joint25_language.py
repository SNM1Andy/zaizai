"""Gemini stages A–C, versioned local operator bindings and read-only DeepSeek proposals."""
from pathlib import Path
import copy
from functools import lru_cache
import hashlib
import json
import re
import sys
import time

import release25_lexicon as catalog
ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/"releases/joint25"
PKG=RELEASE/"language"
VERSION="windows-interface-20261125-r1"
ID=re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
def canon(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)
def sha(x):return hashlib.sha256(x.encode() if isinstance(x,str) else x).hexdigest()
def claim_id(goal):return "claim_"+sha(canon(goal))[:24]
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS joint25_turns(session TEXT NOT NULL,turn TEXT NOT NULL,raw_pin TEXT NOT NULL,
       parsed TEXT NOT NULL,source_version TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(session,turn))""")
    db.execute("""CREATE TABLE IF NOT EXISTS joint25_sessions(session TEXT PRIMARY KEY,version TEXT NOT NULL,state TEXT NOT NULL,
       last_record TEXT NOT NULL,last_turn TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS joint25_goals(claim_id TEXT PRIMARY KEY,atom TEXT NOT NULL,goal TEXT NOT NULL,description TEXT NOT NULL)""")
@lru_cache(maxsize=1)
def vocabulary():
    if str(PKG) not in sys.path:sys.path.insert(0,str(PKG))
    from zaizai_adapter import LexiconRegistry
    reg=LexiconRegistry();reg.register_file(RELEASE/"assets/operators.json",expected_version=VERSION)
    return reg
def goal_atom(goal):
    pred=goal.get("predicate");args=goal.get("arguments",[])
    if not isinstance(pred,str) or not ID.fullmatch(pred) or not args or len(args)>12:raise ValueError("目标不是可落地的原子")
    vals=[]
    for val in args:
        value=val.get("value")
        if val.get("type")=="sym" and isinstance(value,str) and ID.fullmatch(value):vals.append(value)
        elif val.get("type")=="sym" and isinstance(value,str) and len(value)<=48 and not any(ord(c)<32 for c in value):
            vals.append(json.dumps(value,ensure_ascii=False))
        elif val.get("type")=="i64" and re.fullmatch(r"-?\d{1,17}",str(value)):vals.append(str(value))
        else:raise ValueError("参数仍未绑定或类型不受支持")
    return ("!" if goal.get("polarity")=="negative" else "")+pred+"("+",".join(vals)+")"
def brief_sense(e):
    keys=("sense_id","headword","gloss_zh","domain","sense_digest","release_sha256","source_refs","status","decision")
    return {k:e.get(k) for k in keys}
def set_question(out,alts,reason):
    out.update(intent="query",alternatives=alts,disambiguation="unique" if len(alts)==1 else "ambiguous",
               missing=[] if len(alts)==1 else [{"kind":"typed_alternatives","detail":reason,"candidate_ids":[a["candidate_id"] for a in alts],
                   "clarification_question":reason}])
def remember_choice(out,prev,raw):
    if not prev:return False
    options=prev.get("clarified_options") or (prev.get("alternatives",[]) if prev.get("disambiguation") in ("ambiguous","needs_clarification") else [])
    if not options:return False
    text=raw.strip().rstrip("。！？?! ")
    if "不是" in text and re.search(r"[,，。]\s*(?:我指|我是说|是|改为)",text):
        text="我指"+re.split(r"[,，。]\s*(?:我指(?:的是)?|我是说|是|改为)",text)[-1]
    if not re.search(r"^(?:我(?:说的|指的|是说|指)|刚才我指|我的意思|选|第|就是|前者|后者)",text):return False
    match=re.search(r"(?:第|选(?:择)?\s*c?)\s*([一二三四五六七八九1-9])",text)
    if match:
        val=match[1];pos=int(val) if val.isdigit() else "一二三四五六七八九".index(val)+1
        selected=options[pos-1:pos]
    elif "前者" in text or "后者" in text:selected=(options[:1] if "前者" in text else options[-1:]) if len(options)==2 else []
    else:
        selected=[]
        for a in options:
            labels=[str(x) for x in a.get("sense_ids",[])]+[a.get("display","")]
            labels.extend(str(arg.get("value","")) for arg in (a.get("goal") or {}).get("arguments",[]))
            if any(x and x in text for x in labels):selected.append(a)
    if len(selected)!=1:return False
    picked=copy.deepcopy(selected[0]);picked.setdefault("source_refs",[]).append("utterance:"+out["utterance_id"])
    set_question(out,[picked],"");out["ref_utterance_id"]=prev["utterance_id"];out["resolution"]="explicit_choice";out["clarified_options"]=options
    return True

def typed_review(db,out,text):
    # One explicitly attributed relationship, not a world fact. Names stay data; only hashed symbols reach CL.
    match=re.fullmatch(r"(?:请问|请核对|核对|想问一下)?\s*[「“《]?([^「」“”《》\s，。？?!：:]{1,30}?)[」”》]?\s*对\s*[「“《]?([^「」“”《》\s，。？?!：:]{1,35}?)[」”》]?\s*的\s*[「“《]?([^「」“”《》\s，。？?!：:]{1,12}?)[」”》]?(?:是不是有依据|有没有依据|是否有依据|有依据吗|有记录吗|成立吗|通过了吗|获证了吗)[？?。！!]*",text.strip())
    if not match:return False
    actor,obj,term=match.groups();look=catalog.lookup(term,db=db,limit=12)
    entries=look.get("entries",[])
    if not entries or len(entries)!=look.get("candidate_count",len(entries)):return False
    options=[]
    for item in entries:
        sid=item["sense_id"];sense="lx_"+re.sub("[^0-9]","",sid)
        values=(sense,"a"+sha(actor)[:24],"o"+sha(obj)[:24])
        goal={"predicate":"scoped_claim","polarity":"positive","arguments":[{"type":"sym","value":v} for v in values]}
        key=claim_id(goal);label=item["gloss_zh"]
        info={"sense_id":sid,"sense_digest":item["sense_digest"],"term":term,"actor":actor,"object":obj,"gloss":label,
              "lexicon_version":catalog.RELEASE_PIN,"mapping":"scope + sense interpretation; requires separately approved source"}
        atom=goal_atom(goal)
        prior=db.execute("SELECT atom,goal,description FROM joint25_goals WHERE claim_id=?",(key,)).fetchone()
        if prior and (prior[0]!=atom or prior[1]!=canon(goal)):raise ValueError("目标编号冲突")
        db.execute("INSERT OR IGNORE INTO joint25_goals VALUES(?,?,?,?)",(key,atom,canon(goal),canon(info)))
        options.append({"candidate_id":"c"+str(len(options)+1),"goal":goal,"variables":[],"premises":[],
              "sense_ids":[sid],"source_refs":["lexicon:"+catalog.RELEASE_PIN+"#"+sid,"utterance:"+out["utterance_id"]],
              "dispatch_target":"read-channel:reasoned_outcome","polarity":"positive","display":label,"claim_id":key,"lexical_record":info})
    set_question(out,options,"「"+term+"」在这里是哪一层意思？"+"；".join(f"{i+1}. {x['display']}（{x['sense_ids'][0]}）" for i,x in enumerate(options)))
    out["binding_kind"]="explicit_scoped_lexical_claim";return True

def parse(db,p):
    setup(db);reg=vocabulary()
    from zaizai_adapter import DialogueAdapter
    from zaizai_adapter.stage_c import SessionState
    ctx=p.get("context") or {};session=ctx.get("session","main");turn=ctx.get("request") or "u"+sha(p["text"])[:28]
    text=p["text"];raw_pin=sha(text)
    if not isinstance(text,str) or not text.strip() or len(text)>128000:raise ValueError("输入为空或超出长度范围")
    old=db.execute("SELECT raw_pin,parsed FROM joint25_turns WHERE session=? AND turn=?",(session,turn)).fetchone()
    if old:
        if old[0]!=raw_pin:raise ValueError("相同语言回合携带不同原文")
        return json.loads(old[1])
    sess=db.execute("SELECT version,state,last_record FROM joint25_sessions WHERE session=?",(session,)).fetchone()
    a=DialogueAdapter(reg,VERSION);prev=json.loads(sess[2]) if sess else None
    if sess:
        local=json.loads(sess[1]);a.sessions[session]=SessionState.from_dict(local)
    rec=a.process_utterance(text,session_id=session,turn_id=turn,utterance_id=turn,case_id=session,lexicon_version=VERSION)
    out=rec.to_dict();out["dictionary_mentions"]=[]
    if len(text)<=512:
        found=catalog.mention(text,limit=6,db=db)
        for x in found:
            out["dictionary_mentions"].append({"word":x["word"],"byte_span":x["byte_span"],"candidate_count":x["candidate_count"],
                "pending_count":x["pending_count"],"entries":[brief_sense(e) for e in x["entries"][:5]],"source":"DeepSeek "+catalog.RELEASE_PIN})
    if re.search(r"(?:好了没|好了没有|就绪了没|核对过没)[？?。/]*$",text.strip()) and not re.search(r"(?:不能|不许|未能|还没|尚未)",text):
        for field in out["alternatives"]:
            if field.get("goal"):field["goal"]["polarity"]="positive";field["polarity"]="positive"
    selected=remember_choice(out,prev,text)
    if not selected and out.get("intent") not in {"quotation","reported_speech","conditional","retraction"}:typed_review(db,out,text)
    if prev and text.strip().strip("。！？? ") in {"我刚才问的那件事呢","刚才那件事呢","刚才的问题呢","刚才问的是什么","继续刚才的问题","为什么","依据呢"}:
        if prev.get("alternatives"):
            for k in ("alternatives","disambiguation","missing","binding_kind","clarified_options"):
                if k in prev:out[k]=copy.deepcopy(prev[k])
            out.update(intent="follow_up",ref_utterance_id=prev["utterance_id"],query_source_raw=prev.get("query_source_raw",prev["raw_text"]))
    # Register raw words as language, with exact quoted byte offsets. No proposal writes any native fact.
    raw=text.encode()
    for span in out.get("input_spans",[]):
        if not (0<=span["start"]<=span["end"]<=len(raw)):raise ValueError("语言桥返回越界的UTF-8区间")
    state=a.sessions[session].to_dict()
    # Store one immutable interpretation per turn; the separate session view only rehydrates a bounded working tail.
    # Old explicit references remain retrievable from joint25_turns and the host transaction log.
    if len(state.get("turns",{}))>64:
        state["turn_order"]=[key for key in state["turn_order"] if key in state["turns"]][-64:]
        state["turns"]={key:state["turns"][key] for key in state["turn_order"]}
    out["raw_sha256"]=raw_pin;out["source_release"]=VERSION;out["utterance_id"]=turn
    import context25
    import discourse25
    out=context25.enrich(out,text,prev,reg.get(VERSION))
    out=discourse25.enrich(out,text,prev,reg.get(VERSION))
    import clause_read25
    out=clause_read25.compose(out,text,reg.get(VERSION),prev)
    named_withdrawal=clause_read25.bind_withdrawal(db,out,text,session)
    from language_read25 import apply
    out=apply(out,text)
    out=context25.finish(out,text)
    out=discourse25.finish(out)
    out=clause_read25.finish(out,reg.get(VERSION))
    clause_read25.align_withdrawal_state(state,local if sess else None,out,named_withdrawal)
    out["interpretation_build"]=context25.VERSION+"+"+discourse25.VERSION+"+clause-read/1"
    db.execute("INSERT INTO joint25_turns VALUES(?,?,?,?,?,?)",(session,turn,raw_pin,canon(out),VERSION,time.time()))
    db.execute("INSERT OR REPLACE INTO joint25_sessions VALUES(?,?,?,?,?)",(session,VERSION,canon(state),canon(out),turn))
    return out

