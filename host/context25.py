"""Read-only nominal roles, scoped speech and session references for the joint Chinese adapter.

This module can form a grounded *question*. It never answers one or supplies a
world observation. Span offsets always refer to the original unmodified UTF-8.
"""
from copy import deepcopy
import re
import unicodedata

VERSION="zh-context-roles/2026-11-25.1"
ZNUM="零〇一二两兩三四五六七八九十百千万萬"
NUM=r"(?:[0-9]{1,6}|["+ZNUM+r"]{1,15})"
SEP=r"[ \t，,：:]*"
# The entire utterance has to match. Only complete bounded addition questions can be normalized.
END=r"(?:结果|总数|总和|答案|一共|总共)?(?:等于|是|为|得|有|=)?(?:几|多少|[?？])"
ADD_RE=re.compile(r"(?:(?:再再|小洛|请问|请算一下|帮我算一下|算一下)"+SEP+r")*(?:把\s*)?(?:(?P<a>"+NUM+r")\s*(?:\+|加上|加)\s*(?P<b>"+NUM+r")|(?P<x>"+NUM+r")\s*(?:和|与|及)\s*(?P<y>"+NUM+r")\s*(?:的?和|之和|相加|加起来|合起来)|(?:两|二|2)个\s*(?P<twice>"+NUM+r")\s*(?:相加|合起来|加在一起))"+SEP+END+r"[?？/。！! \t]*")
def _chinese(v):
    digits="零一二三四五六七八九"
    def group(n):
        out=""; gap=False
        for power,suffix in [(1000,"千"),(100,"百"),(10,"十"),(1,"")]:
            q,n=divmod(n,power)
            if q:
                if gap:out+="零"
                out+=digits[q]+suffix;gap=False
            elif out and n:gap=True
        return out
    if not v:return "零"
    high,low=divmod(v,10000)
    text=(group(high)+"万" if high else "")+("零" if high and 0<low<1000 else "")+group(low)
    return text[1:] if text.startswith("一十") else text

def _number(token):
    if token.isascii() and token.isdigit():
        return int(token)
    token=token.replace("兩","二").replace("两","二").replace("〇","零").replace("萬","万")
    digits="零一二三四五六七八九"
    if all(c in digits for c in token) and (len(token)==1 or token.startswith("零")):
        return int("".join(str(digits.index(c)) for c in token))
    total=section=val=0
    for c in token:
        if c in digits:val=digits.index(c)
        elif c=="万":total+=(section+val)*10000;section=val=0
        else:section+=(val or 1)*{"十":10,"百":100,"千":1000}[c];val=0
    value=total+section+val
    return value if value<=999999 and token in (_chinese(value),"一"+_chinese(value) if _chinese(value).startswith("十") else "") else None

def normalize_addition(raw,expected_operands):
    if not isinstance(raw,str) or len(raw)>160 or any(c in raw for c in "\r\n"):return None
    # Convert only full-width ASCII and ideographic spaces. NFKC would turn
    # superscripts, circled numbers and other distinct notation into operands.
    text="".join(chr(ord(ch)-0xFEE0) if "！"<=ch<="～" else " " if ch=="　" else ch for ch in raw.strip())
    m=ADD_RE.fullmatch(text)
    if not m:return None
    args=[m["a"],m["b"]] if m["a"] else [m["x"],m["y"]] if m["x"] else [m["twice"]]*2
    numbers=[_number(t) for t in args]
    if any(v is None or not 0<=v<=999999 for v in numbers):return None
    if len(expected_operands)!=2 or any(not re.fullmatch("[0-9]{1,6}",str(v)) for v in expected_operands):return None
    if list(map(int,expected_operands))!=numbers:return None
    return str(numbers[0])+"+"+str(numbers[1])+"=?"

TITLES=re.compile(r"《([^《》\r\n]{1,40})》|「([^「」\r\n]{1,40})」|『([^『』\r\n]{1,40})』|“([^“”\r\n]{1,40})”")
ID_NOUN=re.compile(r"(?:档案|节点|标本|样本|卷宗|文档|设备|工单|资料|文件|记录|物件|条目)(?:编号|代号)?[ \t]*(?:[A-Za-zＡ-Ｚａ-ｚ]+[-_－]?[0-9０-９]+|[0-9０-９]+[-_－]?[A-Za-zＡ-Ｚａ-ｚ0-9０-９]*|["+ZNUM+r"]+号)(?:号)?")
LABELED=re.compile(r"(?:(?:[红橙黄绿青蓝紫黑白灰棕银金]色?|[东西南北甲乙丙丁戊己庚辛壬癸])(?:[A-Za-z0-9_-]{0,8})(?:档案|文件|文档|资料|记录|样本|书架|节点|柜|卷|架|册|盒|箱)|(?:第?[0-9０-９"+ZNUM+r"]+号)(?:档案|资料|文件|样本|文档))")
PLACE=re.compile(r"(?P<loc>(?:(?:[东西南北左右中上下甲乙丙丁戊己庚辛壬癸]|[红橙黄绿青蓝紫黑白灰]色?)(?:侧|边)?(?:书架|货架|书柜|档案柜|架|柜|箱|房)(?:第[0-9０-９"+ZNUM+r"]+层)?|第[0-9０-９"+ZNUM+r"]+(?:层|排|行|列)))(?:上面的|下面的|里边的|里面的|内部的|下方的|上的|里的|内的|中的|的|中(?:的)?|内(?:的)?|里(?:的)?)")
FACETS=(
 ("copy_ready",r"(?:副本(?:已)?(?:备妥|就绪|可用))"),
 ("verified",r"(?:(?:校对|核对|复核|核查)(?:完毕|完成|好|过)?|已校对|已核对)"),
 ("borrow",r"(?:(?:能够|可以|可供|能|可)?(?:外借|借阅|借出))"),
 ("readable",r"(?:(?:能够|可以|可供|能|可)?(?:阅读|读阅|读))"),
 ("ready_item",r"(?:准备(?:完成|好了?|妥当)|就绪|备妥|好了?|可用)"),
)
FACET_RE=[(name,re.compile(pattern)) for name,pattern in FACETS]
QSTART=r"(?:请(?:帮我)?(?:核对|确认|看看|查(?:看|一下)?)|麻烦(?:帮我)?(?:核对|确认|看看|查(?:看|一下)?)|我想(?:查|确认|知道)|请问)?\s*[:：，,]?\s*"
TAIL=r"(?:了没(?:有)?|过没(?:有)?|了吗|了么|吗|么|呢|了|过)?[？?。.!！/\s]*"
MODAL=r"(?:现在|目前|如今|究竟|到底|已经|还|仍然|是否|是不是|能不能|可不可以|有没有|能否|可否|有无|已|仍)*"
NEG_MARK=re.compile(r"未(?:核|校|复|准备|就绪|曾|能)|尚未|没有(?:核|校|准备|就绪)|不能|不可|无法|不允许")
NEUTRAL_Q=re.compile(r"能不能|可不可以|有没有|是不是|是否|能否|好没好|对没对")
ASK=re.compile(r"[?？]|吗|么|(?:好|过|完)了?没(?:有)?(?:[。！!/\s]*)$|能不能|可不可以|有没有|是否|是不是|能否|可否|有无|^(?:请|麻烦|我想(?:确认|知道))")
DISCOURSE=re.compile(r"(?:据(?:说|称)|转述|转告|引述|听说|听(?:别人|某人|他|她)说|引用|原话|有人(?:说|表示)|(?:报告|报道)(?:称|说|写道)|(?:表示|告诉我|声称|写道|提到|说)[:：，,]?[‘'“「『])")
UNCERTAIN=re.compile(r"我(?:还|也|仍)?(?:说不上|没把握|不清楚|不知道|说不准|不能确定|不敢断言|不确定|不能断定|并没(?:有)?(?:说|断言|确认))|只是(?:猜测|举例)|先留作未知")
CONDITION=re.compile(r"^(?:请设想|假使|假设|如果|假如|倘若|要是|设若|设想|若是|只要|除非|若)")
SPEAKER=re.compile(r"^(?P<speaker>[\u4e00-\u9fffA-Za-z]{1,12}?)(?:曾经|刚才)?(?:转告(?:我)?|转述|表示|告诉我|声称|写道|提到|说)[:：，,]?\s*[‘'“「『](?P<content>.+?)[’'”」』]")
SELF=re.compile(r"^我(?:自己)?(?:今天|刚才|现在|最近|好像|这会儿|有时候|这两天)*(?:感觉|觉得)?(?:有点|有些|很|挺|特别|有一点儿|有一点)?(?:累|疲[惫劳倦]|困|饿|疼|难受|轻松|紧张|放松|高兴|开心|迷茫|糊涂|好奇|烦|焦虑|担心|安心|兴奋)(?:了)?[呀啊呢啦。！!\s]*$")
INTRO=re.compile(r"^(?:(?:我|我们|手上|我手上|我这边|我这里|这里|这儿|眼前|书库|库里|现在|手头|资料库|清单|列表)[^。！？?；;]{0,12}?(?:有|拿到|提到|包括|包含|列出|见到|看见|是|分别是)|(?:现有|手头有|新增|给你两份|列出))")
NO_JOIN=re.compile(r"[。！？?!;；\r\n].+")
BAD_NOUN=re.compile(r"(?:忽略规则|覆盖权限|批准|删除|改写|撤回|执行|直接写入|对外|强制|请勿|直接放行)")
REF=re.compile(r"(?:它们?|那(?:个|份|本|项|条|件)|这(?:个|份|本|项|条|件)|刚才(?:那|这)|上述|前述|另一(?:个|份|本)|后者|前者)")
CARRY=re.compile(r"^(?:(?:那|现在|最终|到底|究竟|那么|它|那份|现在到底|归根结底))*\s*(?:能不能|可不可以|行不行|有还是没有|到底如何|结果如何)[呢了么吗？?。！\s]*$")
ORDINAL=re.compile(r"^(?:(?:不对|不|更正一下|更正|改口|等等|抱歉|我改口)[，,。:：\s]*)?(?:(?:我(?:说的(?:是)?|指的(?:是)?|指|是说|选(?:择)?)|我(?:的)?意思(?:是)?|应(?:该)?是|选择|选|是|改成|换成|指的?是)?\s*)(?P<n>第[0-9一二三四五六七八九]|前者|后者|前一|后一|前面那|后面那|最前面那|最后那)(?:个|份|项|次|条|种|件|本)?(?:的)?(?:资料|文档|文件|解释|候选|记录)?[。！!?？/\s]*$")
DATE=re.compile(r"[0-9０-９]{4}年\s*[0-9０-９]{1,2}月\s*[0-9０-９]{1,2}日")
def _span(raw,start,end,kind):
    return {"start":len(raw[:start].encode()),"end":len(raw[:end].encode()),"kind":kind,"raw_bytes_utf8":raw[start:end]}
def _add_span(rec,span):
    if span not in rec["input_spans"]:rec["input_spans"].append(span)
def _canonical(value,lex):
    entries=lex.lookup_surface(value,kind="entity") if lex else []
    return [(e.canonical,e.sense_id) for e in entries] or [("sym_"+value,None)]
def _entities(raw,lex):
    items=[]
    for m in TITLES.finditer(raw):
        i=next(i for i,v in enumerate(m.groups(),1) if v is not None)
        if len(m[i])<=38 and not BAD_NOUN.search(m[i]):items.append((m.start(i),m.end(i),1))
    for pattern in (ID_NOUN,LABELED):
        items.extend((m.start(),m.end(),0) for m in pattern.finditer(raw))
    if lex:
        for surface,entries in lex.surface_forms_by_length(kind="entity"):
            at=raw.find(surface)
            while at>=0:
                items.append((at,at+len(surface),0));at=raw.find(surface,at+len(surface))
    # Select complete entities before smaller overlaps such as '7号' inside '档案7号'.
    occupied=set();picked=[]
    for left,right,quoted in sorted(set(items),key=lambda t:(-t[2],t[0]-t[1],t[0])):
        if any(i in occupied for i in range(left,right)):continue
        occupied.update(range(left,right));picked.append((left,right,quoted))
    return [{"surface":raw[a:b],"char_start":a,"char_end":b,"quoted":bool(quoted),"value":v,"sense":sid}
            for a,b,quoted in sorted(picked) for v,sid in _canonical(raw[a:b],lex)]
def _facet(raw):
    terms=[]
    for order,(pred,regex) in enumerate(FACET_RE):
        for m in regex.finditer(raw):terms.append((m.start(),m.end(),order,pred))
    if not terms:return None
    # Longest contextual construction prevails only for matches at the same place.
    # Two independent predicates are not silently reduced to one.
    remaining=[]
    for left,right,order,pred in sorted(terms,key=lambda x:(x[0]-x[1],x[2],x[0])):
        if not any(left<b and a<right for a,b,_,_ in remaining):remaining.append((left,right,order,pred))
    return remaining[0][3] if len({v[3] for v in remaining})==1 else None
def _suffix(raw):
    cleaned=raw.strip().lstrip("，,").strip()
    for pred,part in FACETS:
        pat=r"^[\s」』》”]*(?:的)?(?:(?:这|那)(?:份|个|件|本))?(?:的)?(?:资料|文件|文档|手册|副本)?\s*"+MODAL+part+TAIL+"$"
        if re.fullmatch(pat,cleaned):return pred
    return None
def _entity_view(entity,turn):
    return {"value":entity["value"],"surface":entity["surface"],"sense":entity.get("sense"),"utterance":turn}
def _read(ent,pred,rid,loc=None,polarity="positive"):
    args=[{"type":"sym","value":ent["value"]}];refs=["utterance:"+rid]
    if ent.get("utterance") and ent["utterance"]!=rid:refs.append("utterance:"+ent["utterance"])
    if loc:args.append({"type":"sym","value":loc["value"]})
    return {"candidate_id":"","goal":{"predicate":pred+("_at" if loc else ""),"polarity":polarity,"arguments":args},
            "variables":[],"premises":[],"sense_ids":([ent["sense"]] if ent.get("sense") else []),
            "source_refs":refs,"dispatch_target":"read-channel:reasoned_outcome","polarity":polarity,
            "display":((loc["surface"]+"的") if loc else "")+ent["surface"],"candidate_source":"versioned_contextual_roles",
            "metadata":{"role_binding":"subject_with_location" if loc else "subject","target":ent,"location":loc}}
def _set_candidates(r,alts,entities,pred,loc=None):
    for i,a in enumerate(alts,1):a["candidate_id"]="c"+str(i)
    r.update(intent="query",alternatives=alts,disambiguation="unique" if len(alts)==1 else "ambiguous",
             missing=[] if len(alts)==1 else [{"kind":"ambiguous_referent","candidate_ids":[x["candidate_id"] for x in alts],
                      "clarification_question":"你指的是哪一个对象？"}])
    r["context25"].update(entities=deepcopy(entities),predicate=pred,location=loc)
def enrich(record,raw,previous=None,lexicon=None):
    r=deepcopy(record)
    if r.get("raw_text")!=raw:raise ValueError("本轮原文不一致")
    if not isinstance(raw,str) or len(raw)>1024:return r
    prev=previous or {};pc=prev.get("context25") or {};rid=r["utterance_id"]
    r["context25"]={"version":VERSION,"entities":[],"scope":"none"}
    c=r["context25"]; trimmed=raw.strip();clean=re.sub(r"[。！？?!/\s]+$","",trimmed)
    # Keep numbers/quoted text and the entire original proposal available for audit.
    c["original_intent"]=r.get("intent")
    for m in DATE.finditer(raw):_add_span(r,_span(raw,m.start(),m.end(),"date"))
    if r.get("binding_kind")=="explicit_scoped_lexical_claim" and r.get("disambiguation")=="ambiguous":return r
    if not clean or "\n" in clean or "\r" in clean:return r
    quoted=SPEAKER.search(clean)
    if quoted:
        c.update(scope="quotation",speaker=quoted["speaker"],quote=_span(raw,quoted.start("content")+raw.find(trimmed),quoted.end("content")+raw.find(trimmed),"quoted_literal"))
        _add_span(r,c["quote"]);r["attribution"]={"reported_speaker":quoted["speaker"],"source":"user","direct_observation":False}
        r["intent"]="quotation";r["disambiguation"]="not_applicable"
        content=quoted["content"];entities=_entities(content,lexicon);pred=_facet(content);alts=[]
        if len(entities)==1 and pred:
            alt=_read(_entity_view(entities[0],rid),pred,rid,polarity="negative" if NEG_MARK.search(content) else "positive");alt["dispatch_target"]="none";alts=[alt]
        r["alternatives"]=alts;return r
    if CONDITION.search(clean):
        c["scope"]="conditional";r["intent"]="conditional";r["disambiguation"]="not_applicable"
        parts=re.split(r"[，,；;]\s*(?:(?:那么|则|那就|才|我才|我就))?|(?:那么|才会|就会)",clean,maxsplit=1)
        if len(parts)==2:
            before,after=parts;ents=_entities(before,lexicon);p1,p2=_facet(before),_facet(after)
            c.update(antecedent=before,consequent=after)
            r["alternatives"]=[]
            if len(ents)==1 and p1 and p2:
                entity=_entity_view(ents[0],rid);alts=_read(entity,p2,rid)
                alts["premises"]=[_read(entity,p1,rid)["goal"]];alts["dispatch_target"]="none";alts["metadata"]["premise_asserted_as_fact"]=False
                r["alternatives"]=[alts]
        return r
    if DISCOURSE.search(trimmed) or UNCERTAIN.search(trimmed) or r.get("intent") in ("quotation","conditional","quoted_material","retraction","epistemic_clarification"):
        return r
    if SELF.fullmatch(trimmed):
        c["scope"]="expressive_self_report";r.update(intent="expressive_self_report",disambiguation="not_applicable",alternatives=[],missing=[]);return r
    choice=ORDINAL.fullmatch(trimmed)
    if choice:
        opts=prev.get("clarified_options") or (prev.get("alternatives",[]) if prev.get("disambiguation")=="ambiguous" else [])
        group=choice["n"]
        idx=(1 if group.startswith(("前","最前")) else len(opts) if group.startswith(("后","最后")) else
            int(group[1]) if group[1].isdigit() else "一二三四五六七八九".index(group[1])+1)
        if 0<idx<=len(opts):
            selected=deepcopy(opts[idx-1]);selected["source_refs"]=list(dict.fromkeys(selected["source_refs"]+["utterance:"+rid]))
            r.update(intent="query",disambiguation="unique",alternatives=[selected],missing=[],ref_utterance_id=prev["utterance_id"],
                resolution="explicit_choice",clarified_options=deepcopy(opts))
            c.update(scope="selection",entities=deepcopy(pc.get("entities",[])),predicate=(selected.get("goal") or {}).get("predicate"),
                     selected=deepcopy(selected),location=pc.get("location"));return r
    if r.get("binding_kind")=="explicit_scoped_lexical_claim" or r.get("resolution")=="explicit_choice" or r.get("intent")=="follow_up":return r
    if not ASK.search(trimmed) and INTRO.search(trimmed) and not NO_JOIN.search(clean):
        es=_entities(raw,lexicon)
        if es and not _facet(trimmed) and not BAD_NOUN.search(clean):
            ent=[_entity_view(x,rid) for x in es]
            for x in es:_add_span(r,_span(raw,x["char_start"],x["char_end"],"entity"))
            r.update(intent="context_introduction",disambiguation="not_applicable",alternatives=[],missing=[])
            c.update(scope="context_introduction",entities=ent)
            return r
    if not ASK.search(trimmed) or NO_JOIN.search(clean):return r
    if CARRY.fullmatch(trimmed) and prev.get("intent") in ("query","follow_up") and prev.get("alternatives"):
        alts=deepcopy(prev["alternatives"])
        if not all(x.get("goal") and not x.get("variables") and x.get("dispatch_target") in ("read-channel:proof","read-channel:reasoned_outcome","none") for x in alts):return r
        r.update(intent="query",alternatives=alts,disambiguation=prev["disambiguation"],missing=deepcopy(prev.get("missing",[])),
                 ref_utterance_id=prev["utterance_id"])
        c.update(pc);return r
    pm=PLACE.search(trimmed);off=raw.find(trimmed);loc=None
    if pm:
        loc={"value":_canonical(pm["loc"],lexicon)[0][0],"surface":pm["loc"],"utterance":rid}
    es=[x for x in _entities(raw,lexicon) if not(pm and x["char_start"]<off+pm.end() and x["char_end"]>off+pm.start())]
    pred=None
    if es:
        tail=max(x["char_end"] for x in es);pred=_suffix(raw[tail:])
        if not pred and re.fullmatch(r"[\s」』》”]*(?:(?:现在|究竟|是否|是不是|能不能|可否|有没有|已)*)(?:未核对|未校对|已核对|已校对|不(?:能|可)读|未准备好)[了过吗么呢？?。/]*",raw[tail:]):
            pred=_facet(raw[tail:])
        # Prefix must denote only the request, location and subject terms. No unbound clause may become a fact.
        begin=min(x["char_start"] for x in es);lead=raw[:begin].strip()
        if pm:lead=(raw[:off+pm.start()]+raw[off+pm.end():begin]).strip()
        allowed=re.fullmatch(QSTART+r"(?:这|那)?(?:份|本|个|件|项)?(?:称为|名为|叫做|叫|题为)?[《「『“]?",lead)
        if not allowed and not (DISCOURSE.search(lead) is None and re.fullmatch(r"正反(?:两|多)份(?:报告|记录|材料)(?:都|均)?(?:涉及|提到|提及)",lead)):
            return r
    elif REF.search(clean):
        pred=_suffix(re.sub(r"^(?:(?:那么|那)?它|那(?:份|本|个|件|项)|这(?:份|本|个|件|项)|刚才那(?:份|本|个))","",trimmed))
        if pc.get("selected"):es=[pc["selected"].get("metadata",{}).get("target") or {}]
        else:es=pc.get("entities") or []
        es=[x for x in es if x.get("value") and x.get("surface")]
        if es:r["ref_utterance_id"]=prev.get("utterance_id")
    if not (pred and es):return r
    if pm:_add_span(r,_span(raw,pm.start("loc")+off,pm.end("loc")+off,"location"))
    refs=[]
    for x in es:
        if "char_start" in x:
            _add_span(r,_span(raw,x["char_start"],x["char_end"],"entity"))
            refs.append(_entity_view(x,rid))
        else:refs.append(x)
    signed="negative" if NEG_MARK.search(NEUTRAL_Q.sub("",trimmed)) else "positive"
    _set_candidates(r,[_read(e,pred,rid,loc,signed) for e in refs],refs,pred,loc)
    c.update(scope="qualified_read" if loc else "read",complete_roles=True)
    return r

def finish(record,raw):
    """Preserve explicit role coverage while respecting stronger scope and input-integrity guards."""
    b=record.get("boundary",{});ctx=record.get("context25") or {};category=b.get("category")
    if category=="instruction_override":
        record.update(intent="untrusted_instruction",disambiguation="rejected");return record
    if ctx.get("complete_roles") and category=="unbound_entities" and record.get("disambiguation")=="unique":
        # All entity spans are inside an explicitly parsed nominal or its place modifier. Never override quote/polarity guards.
        record["boundary"]=dict(b,decision="pass",category="location_and_subject_bound",allow_dispatch=True,
                                reason="对象与处所已分别绑定，按原文组成一个只读状态查询。")
        for alt in record["alternatives"]:alt["dispatch_target"]="read-channel:reasoned_outcome"
    return record

def nonfact(record):
    """A host may render these literal messages as context, without minting a fact/proof."""
    b=record.get("boundary",{});ctx=record.get("context25") or {};scope=ctx.get("scope")
    if b.get("decision")=="reject" or b.get("category") in ("instruction_override","invalid_source_span","unterminated_quote"):
        return None
    if scope=="context_introduction":
        labels=list(dict.fromkeys(x["surface"] for x in ctx["entities"]))
        return {"kind":"context","text":"本会话记下了"+"、".join(labels)+"。要先核对哪一项？"}
    if scope=="expressive_self_report":
        return {"kind":"user_statement","text":"你说「"+record["raw_text"]+"」。我把这句话记作你的自述，原因仍待你说明。"}
    return None

def scope_module():
    """Optional additive CL views. A location is a premise and cannot be inferred from the user's wording."""
    lines=[]
    for predicate in ("verified","copy_ready","borrow"):
        derived=predicate+"_at"
        lines.extend((f": {derived}(sym,sym).",
                      f"{derived}($x,$p) <- at_location($x,$p) & {predicate}($x).",
                      f"!{derived}($x,$p) <- at_location($x,$p) & !{predicate}($x)."))
    return "\n".join(lines)+"\n"

