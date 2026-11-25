"""Resolve discourse roles and question modifiers; all outputs are proposals about a source span."""
import re
from copy import deepcopy
import context25 as cx
VERSION="discourse-frame/3"
CHOICE=re.compile(r"(?:第\s*([一二两三四五六七八九1-9])\s*(?:份|个|项|种|条|本|件)|(?P<side>前者|后者|前一(?:个|份)|后一(?:个|份)))")
ASK_WORD=re.compile("能否|能不能|能够|可以|可否|是否|究竟|到底|有没有|[吗么呢？?]")
STRUCTURE_GUARD=re.compile(r"假设|假如|倘若|如果|若是|据说|转述|原话|抄下|引用|不知道|不确定|并没|忽略|绕过|跳过|强制|擦掉|抹掉|写入|改权限|授权|撤回|删除|不想|并不想|别选|不选")
OLD_REF=re.compile(r"(?:刚才|上次|上一|刚刚|刚说|前一|上个|之前|刚问).{0,18}(?:算式|问题|那道题|这道题|那一题|依据|凭据|证据|判断|结果|再核|再算|理由|那件事)")
COMMAND=re.compile(r"(?:绕开|跳过|忽略|不用|避开).{0,10}(?:规则|核对|检查|验证|权限).{0,30}(?:写|标|改|执行|删|存档)")
QUOTED=re.compile(r"^\s*[‘“「『](?P<quoted>.+?)[’”」』]\s*(?:就|也|仅|只|不过|都|是|我|抄|引|下|来|的|一|段|句|转述|原话|材料|话语|文字|而已|记录|引用|照录|文本|话|。|！|\s)+$")
ATTRIBUTED=re.compile(r"^\s*(?P<speaker>[\u4e00-\u9fffA-Za-z]{1,12}?)(?:留言|写下|转发|贴出|记录|回复|写道|说道|表示|转述|复述)[：:，,]\s*[‘“「『](?P<quoted>[^’”」』]{1,350})[’”」』]\s*(?:[，,。；;]?\s*(?:我|这里)(?:只|仅)(?:是|仅)?(?:引述|复述|转述|引用|照录)[^！？?。]{0,18}[。！!]?)?$")
CHOOSE_WORD=re.compile(r"我指|选错|说错|改口|我说的|这次说的|(?:换|改)(?:成|为)|那[一层个种]?(?:意思|义)|那个意思|那一义")
UNIT_PAIR=re.compile(r"(?P<a>"+cx.NUM+r")\s*(?P<u1>[只本件张份米斤盒台册条])(?P<n1>[\u4e00-\u9fff]{0,8}?)(?:再)?(?:加上|加|和|\+)\s*(?P<b>"+cx.NUM+r")\s*(?P<u2>[只本件张份米斤盒台册条])(?P<n2>[\u4e00-\u9fff]{0,8}?)(?:[,，。]|一共|合计|总共|合起来|是多少|有多少)")

def _as_choice(out,prev,opts,selected):
    picked=deepcopy(selected)
    picked["source_refs"]=list(dict.fromkeys(picked.get("source_refs",[])+["utterance:"+out["utterance_id"]]))
    out.update(intent="query",alternatives=[picked],clarified_options=deepcopy(opts),missing=[],disambiguation="unique",
               resolution="explicit_choice",ref_utterance_id=prev["utterance_id"])
    out["context25"].update(scope="selection",selected=picked,entities=_entities(prev))

def _described_choice(raw,options):
    if len(options)<2 or re.search(r"还是|或者|不是|不指|都|别选|不想|两种|两者",raw):return None
    for option in options:
        target=_from_option(option)
        if target and target.get("surface") and target["surface"] in raw:
            if sum(bool((t:=_from_option(o)) and t.get("surface") and t["surface"] in raw) for o in options)==1:return option
    glosses=[(o.get("lexical_record") or {}).get("gloss","") for o in options]
    if not all(glosses):return None
    grams=lambda s:{m[1] for m in re.finditer(r"(?=([\u4e00-\u9fff]{2}))",s)}
    # Only two non-overlapping terms distinctive to the same frozen candidate may resolve a paraphrase.
    # Typical reporting words do not distinguish senses.
    ignore={"表示","行为","意思","某种","一个","指的","就是","是一","的是","某人","某事"}
    words=[grams(g) for g in glosses];chosen=[]
    for i,own in enumerate(words):
        unique=(own-set().union(*(v for j,v in enumerate(words) if j!=i)))-ignore
        positions=[m.start() for m in re.finditer(r"(?=([\u4e00-\u9fff]{2}))",raw) if m[1] in unique]
        if positions and positions[-1]-positions[0]>=2:chosen.append(options[i])
    return chosen[0] if len(chosen)==1 else None
def _pred(text,lex):
    pairs=[]
    for word,entries in lex.surface_forms_by_length(kind="predicate"):
        if word in text:pairs.extend(e.canonical for e in entries if len(e.arg_types)==1)
    for pred,regex in cx.FACETS:
        if re.search(regex,text):pairs.append(pred)
    if re.search(r"(?:阅(?:读)?|读|浏览)",text) and "借阅" not in text:pairs.append("readable")
    if re.search(r"(?:核对|校对|复核|核查)(?:完|过|了|好|清楚)?",text) and not re.search("凭据|依据",text):pairs.append("verified")
    distinct=set(pairs)
    if distinct=={"copy_ready","ready_item"}:return "copy_ready"
    return next(iter(distinct)) if len(distinct)==1 else None
def _all_options(prev):
    if not prev:return []
    if prev.get("clarified_options"):return prev["clarified_options"]
    if prev.get("disambiguation")=="ambiguous":return prev.get("alternatives") or []
    return []
def _from_option(a):
    m=a.get("metadata") or {}
    if isinstance(m.get("target"),dict) and m["target"].get("value"):return m["target"]
    g=a.get("goal") or {};args=g.get("arguments") or []
    if len(args)==1:
        v=args[0].get("value")
        if isinstance(v,str):return dict(value=v,surface=m.get("surface") or a.get("display") or v)
    return None
def _entities(prev):
    ctx=(prev or {}).get("context25") or {}
    if ctx.get("entities"):return ctx["entities"]
    return [v for v in (_from_option(a) for a in _all_options(prev)) if v]
def enrich(out,raw,prev,lex):
    import turn_reference25 as ref
    resolved = ref.resolve(out, raw, prev)
    if resolved is not None:
        return resolved
    return ref.retain(_enrich(out, raw, prev, lex), prev)


def _enrich(out,raw,prev,lex):
    if len(raw)>800:return out
    ctx=out.setdefault("context25",{});rid=out["utterance_id"]
    attributed=ATTRIBUTED.fullmatch(raw)
    if attributed:
        ctx.update(scope="quotation",reported_literal=attributed["quoted"],speech_function="cited_text")
        out.update(intent="quotation",attribution={"speaker":attributed["speaker"],"direct_observation":False},alternatives=[],missing=[],disambiguation="not_applicable")
        return out
    quote=QUOTED.fullmatch(raw)
    if quote and re.search("原话|抄|引用|转述|照录",raw[quote.end("quoted")+1:]):
        ctx.update(scope="quotation",reported_literal=quote["quoted"],speech_function="cited_text")
        out.update(intent="quotation",attribution={"speaker":"未具名来源","direct_observation":False},alternatives=[],missing=[],disambiguation="not_applicable")
        return out
    if COMMAND.search(raw):
        ctx["speech_function"]="attempted_authority_override";return out
    # Keep an explicit negative correction separate from a negated proposition or a disavowal.
    correction=re.search(r"(?:说错|说反|弄反|不对|更正|改口|我的意思|我要问|我先问|我指)",raw)
    if STRUCTURE_GUARD.search(raw) or ctx.get("scope") in ("conditional","quotation","expressive_self_report"):return out
    if prev and OLD_REF.search(raw) and not CHOICE.search(raw) and prev.get("alternatives"):
        for k in ("alternatives","clarified_options","disambiguation","missing","binding_kind"):
            if k in prev:out[k]=deepcopy(prev[k])
        out.update(intent="follow_up",ref_utterance_id=prev["utterance_id"],query_source_raw=prev.get("query_source_raw",prev["raw_text"]))
        out["context25"]=dict(deepcopy(prev.get("context25") or {}),scope="recheck");return out
    nums=operands(raw)
    if nums is not None:
        senses=lex.lookup_surface("加",kind="operator")
        if senses:
            ids=[s.sense_id for s in senses]
            goal={"predicate":"qty_add","polarity":"positive","arguments":[{"type":"nat","value":v} for v in nums]+[{"type":"var","name":"$result","expected_type":"nat"}]}
            a=dict(candidate_id="c1",goal=goal,variables=[{"name":"$result","type":"nat","bound":False}],sense_ids=ids,
                   source_refs=["utterance:"+rid,"lexicon:"+lex.version+"#"+ids[0]],premises=[],dispatch_target="solver:qty_add",polarity="positive")
            out.update(intent="query",alternatives=[a],disambiguation="unique",missing=[])
            ctx.update(scope="arithmetic",operands=nums)
            return out
    units=UNIT_PAIR.search(raw)
    if units and units["u1"]!=units["u2"] and ASK_WORD.search(raw):
        ctx.update(scope="incompatible_units",units=[units["u1"],units["u2"]]);out.update(alternatives=[],missing=[],disambiguation="needs_clarification")
        return out
    opts=_all_options(prev);roles=_entities(prev);p=_pred(raw,lex)
    if opts and CHOOSE_WORD.search(raw):
        match=_described_choice(raw,opts)
        if match is not None:
            _as_choice(out,prev,opts,match);return out
    if "不是" in raw and re.search(r"(?:我(?:说|指|想|问)|我要)",raw):
        positive=raw.split("不是",1)[0]
        if opts and positive:
            matching=[o for o in opts if (t:=_from_option(o)) and t.get("surface") and t["surface"] in positive]
            if len(matching)==1:
                out.update(intent="query",alternatives=deepcopy(matching),clarified_options=deepcopy(opts),missing=[],disambiguation="unique",resolution="explicit_choice",ref_utterance_id=prev["utterance_id"])
                ctx.update(scope="selection",entities=roles,predicate=(matching[0].get("goal") or {}).get("predicate"));return out
    matches=list(CHOICE.finditer(raw))
    if len(matches)==1 and opts and not re.search("还是|或是|任选|不是第|不是前者|不是后者",raw) and (correction or ASK_WORD.search(raw)):
        m=matches[0]
        if m["side"]:index=0 if m["side"].startswith("前") else len(opts)-1
        else:index=(int(m[1]) if m[1].isdigit() else "一二三四五六七八九".index(m[1].replace("两","二"))+1)-1
        if 0<=index<len(opts):
            a=deepcopy(opts[index]);target=_from_option(a)
            if p and target and p!=(a.get("goal") or {}).get("predicate"):
                a=cx._read(target,p,rid,(prev.get("context25") or {}).get("location"))
            out.update(intent="query",alternatives=[a],clarified_options=deepcopy(opts),missing=[],disambiguation="unique",resolution="explicit_choice",ref_utterance_id=prev["utterance_id"])
            ctx.update(scope="selection",entities=roles,predicate=(a.get("goal") or {}).get("predicate"),selected=a);return out
    if out.get("binding_kind") or out.get("resolution")=="explicit_choice" or out.get("intent") in {"follow_up","conditional","quotation"}:return out
    ent=cx._entities(raw,lex)
    if len(ent)>1 and not p and not ASK_WORD.search(raw) and re.search("[、，,和及与跟]|还有|以及",raw) and not any(raw[x["char_end"]:y["char_start"]].strip()=="的" for x,y in zip(ent,ent[1:])):
        actual=[cx._entity_view(x,rid) for x in ent]
        for v in ent:cx._add_span(out,cx._span(raw,v["char_start"],v["char_end"],"entity"))
        ctx.update(scope="context_introduction",entities=actual)
        out.update(intent="context_introduction",disambiguation="not_applicable",alternatives=[],missing=[])
        return out
    if prev and p and not ent and re.search(r"那(?:个|份|它|本|件|项)|它|提到的|前述",raw) and ASK_WORD.search(raw):
        selected=(prev.get("context25") or {}).get("selected")
        use=[_from_option(selected)] if selected and _from_option(selected) else roles
        if use:
            cx._set_candidates(out,[cx._read(e,p,rid,(prev.get("context25") or {}).get("location")) for e in use],use,p)
            out.update(ref_utterance_id=prev["utterance_id"]);ctx.update(scope="read",complete_roles=len(use)==1)
    return out
def finish(out):
    ctx=out.get("context25",{});b=out.get("boundary",{})
    if ctx.get("speech_function")=="attempted_authority_override":
        b.update(decision="reject",category="instruction_override",allow_dispatch=False,reason="这句话提出越过核验并改写记录；已保留原文，没有将它作为事实或指令执行。")
        for a in out["alternatives"]:a["dispatch_target"]="none"
        out["intent"]="untrusted_instruction"
    elif ctx.get("speech_function")=="cited_text" and b.get("category") not in {"instruction_override", "invalid_source_span", "unterminated_quote"}:
        b.update(decision="explain",category="attributed_quotation",allow_dispatch=False,reason="引号内是被转述的原话；保留来源，没有执行其中的动作。")
    elif ctx.get("scope")=="incompatible_units":
        b.update(decision="clarify",category="incompatible_units",allow_dispatch=False)
        out["missing"]=[{"kind":"unit","clarification_question":"这里给了不同的单位「"+"」和「".join(ctx["units"])+"」。你想分别统计，还是按同一计量口径求和？"}]
    return out
def _math_wording(raw):
    source="".join(chr(ord(ch)-0xFEE0) if "！"<=ch<="～" else " " if ch=="　" else ch for ch in raw.strip())
    if len(source)>140 or any(x in source for x in "\r\n‘’“”《》「」;；"):return ""
    # Remove only discourse/politeness modifiers; never strip nouns, units, conditions or an arbitrary suffix.
    source=re.sub(r"^(?:(?:劳驾(?:您|你)?|麻烦(?:您|你)?|烦请|请问|请(?:您|你)?|帮(?:个忙|一下忙|忙|我)|帮(?:我|忙)(?:算一下|算算)?|给我|替我|再再|小洛|你能否|你能不能|能否|可以|能不能|算一算|算一下|算算|那么|改成|换成)[\s,，:：]*)+","",source)
    source=re.sub(r"(?<=[0-9零〇一二两三四五六七八九十百千万])\s*(?:算一下|算一算|算算)(?=\s*[,，?？]|$)","",source)
    source=re.sub(r"(?<=[,，])\s*(?:加在一起|合起来|加起来)(?=\s*(?:是|为|有)?多少)","",source)
    return re.sub(r"(?:呀|呢|啊)(?=[?？/。！!\s]*$)","",source)

def operands(raw):
    m=cx.ADD_RE.fullmatch(_math_wording(raw))
    if not m:return None
    terms=[m["a"],m["b"]] if m["a"] else [m["x"],m["y"]] if m["x"] else [m["twice"]]*2
    operands=[cx._number(v) for v in terms]
    return operands if all(isinstance(v,int) and 0<=v<=999999 for v in operands) else None

def normalized_math(raw,vals):
    return cx.normalize_addition(_math_wording(raw),vals)

