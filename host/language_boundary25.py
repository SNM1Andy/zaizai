"""Host-side scope gate for proposal-only Chinese records. It never approves a fact or issues a native command."""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata

VERSION="zh-source-scope-20261125.1"
QUOTES={"“":"”","‘":"’","「":"」","『":"』","\"":"\"","'":"'"}
BREAK=re.compile(r"[。！？；\n]")
OVERRIDE=re.compile(r"(?:忽[略视]|无[视需]|绕[过开]|跳过|覆盖|越过|丢弃|废除|作废|取消|关闭|不要遵[循守]|不必遵[循守]|不需要遵[循守]|别管).{0,20}(?:规则|约束|审[核批]|校验|验证|权限|边界|指[令示]|限制|策略|说明|系统消息)|(?:system|developer)\s*(?:[:：]|message\s*:)|(?:ignore|bypass)\s+(?:all\s+|the\s+|previous\s+|prior\s+|system\s+)*(?:instructions?|rules?|policy|permissions?)",re.I)
BULK=re.compile(r"(?:撤回|删[去除]|清[除空理]|重置|移除|覆盖).{0,8}(?:所[有余]|全部|一切|全部记录|整份存档|整个历史|全库)|(?:所[有余]|全部|一切).{0,9}(?:撤回|删[去除]|清[除空理])")
SPEECH=re.compile(r"(?:说(?:道|过)?|表[示明]|声称|称|写(?:着|道|的)?|记载|提[及到]|报道|转述|引用|据称|原话(?:是)?|引文(?:是)?|标签(?:上)?|摘录(?:为)?)[\s:：,，]*$")
FRAMING=re.compile(r"(?:引号|引文|原文|原话|文本|题干|摘录|包装上|所引|转述|仅为.*(?:示例|文字)|只是.*(?:说法|引文|例句|示例))")
REPORT=re.compile(r"(?:据(?:报道|记载|称)|(?:对方|他人|同事|老师|管理员|编辑|用户|报告|材料|包装|标签|说明书|日志|记录|消息|信中)(?:\s*里|\s*中|\s*上)?(?:说(?:道|过)?|称|写[着道]|提[及到]|表[示明]|记载|声称))")
IF=re.compile(r"(?:假(?:如|设|使|定)|如(?:果|若)|倘(?:若|使)|要是|除非|即[使便]|只有|只要|若(?!干|水)|在.{1,16}前提下)")
DENY_KNOW=re.compile(r"(?:没有|没|并未|未曾|不曾|不能|无法|难以|没法|不敢)(?:亲自|直接|明确|完全|据此|因此|就此|武断地)?(?:说(?:过)?|断言|确认|证实|认定|认为|保证|判断|确定|宣称|主张|知道)|(?:不知道|不确定|尚不清楚|还不清楚|无法得知|并不知|未核实|证据不足|有待核实|不见得|不代表|不能说明|不能证明|尚无依据)")
NEG=re.compile(r"(?:并不|并非|不(?:可|能|准|许|得|是)|未(?:经|曾|核|校|审|检|备|获|被|就绪)|没有(?:获|通过|完成|核对|许可|准备)|尚未)")
CHOICE_QUESTION=re.compile(r"(?:能不能|可不可以|能否|有没有|是否|是不是|对不对|有无|可否)")
ACTION=re.compile(r"(?:删[除去]|撤回|清空|改写|执行|写入|覆盖|生效|放行|认证|核对|不能读|可读|外借|合格)")
ROLE_ALIASES={"doc_a":"甲资料","doc_b":"乙资料","shelf_a":"甲架","shelf_b":"乙架","spare_part":"备用件","data_backup":"数据备份"}
def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def quotes_in(text):
    stack=[];result=[]
    for index,ch in enumerate(text):
        if stack and ch==stack[-1][0]:
            end,start=stack.pop()
            if not stack:result.append((start,index+1))
        elif ch in QUOTES:
            if ch in ("'","\"") and index and index+1<len(text) and text[index-1].isascii() and text[index-1].isalnum() and text[index+1].isascii() and text[index+1].isalnum():
                continue
            stack.append((QUOTES[ch],index))
    return result, bool(stack)
def apply(record,raw):
    if not isinstance(record,dict) or not isinstance(raw,str):raise ValueError("需要结构化语言记录与原句")
    result=deepcopy(record)
    alternatives=result.get("alternatives",[])
    if not isinstance(alternatives,list) or any(not isinstance(x,dict) for x in alternatives):raise ValueError("候选结构无效")
    supplied_text=result.get("raw_text")
    if supplied_text is not None and supplied_text!=raw:raise ValueError("原句与候选记录不匹配")
    result.setdefault("raw_text",raw)
    if isinstance(result.get("boundary"),dict) and result["boundary"].get("version")==VERSION:
        # Always recompute from the retained originals; a supplied decision flag cannot authorize dispatch.
        old=result["boundary"].get("original_alternatives")
        if isinstance(old,list):
            result["alternatives"]=deepcopy(old);alternatives=result["alternatives"]
    text=raw.strip()
    offsets=[0]
    for ch in raw:offsets.append(offsets[-1]+len(ch.encode("utf8")))
    quote,unclosed=quotes_in(raw); quote_data=[{"start":offsets[x],"end":offsets[y],"text":raw[x:y]} for x,y in quote]
    remaining=list(raw)
    for a,b in quote:remaining[a:b]=[" " for _ in range(b-a)]
    external=unicodedata.normalize("NFKC","".join(remaining))
    ds=result.get("disambiguation");intent=result.get("intent","")
    typed=[(a,a["goal"]) for a in alternatives if isinstance(a.get("goal"),dict)]
    entities=set();span_error=False
    for span in result.get("input_spans",[]):
        try:
            i,j=span["start"],span["end"]
            if type(i) is not int or type(j) is not int or not 0<=i<j<=offsets[-1]:raise ValueError()
            value=raw.encode("utf8")[i:j].decode()
            if span.get("raw_bytes_utf8") is not None and span["raw_bytes_utf8"]!=value:raise ValueError()
            if span.get("kind") in ("entity","novel_entity"):entities.add(value)
        except (ValueError,TypeError,KeyError,UnicodeError):span_error=True;break
    decision,category,reason="pass","proposal","该候选可依既有审批流程继续核验。"
    if span_error:
        decision,category,reason="reject","invalid_source_span","字节跨度与原文不匹配，请重新解析。"
    elif unclosed:
        decision,category,reason="clarify","unterminated_quote","引号没有闭合，需先确认引用的范围。"
    elif OVERRIDE.search(external):
        decision,category,reason="reject","instruction_override","这段文字要求改变既有指令、验证或权限，已按输入内容保留。"
    elif (intent in ("quotation","quoted_material") or REPORT.search(external) or any(
          SPEECH.search(raw[max(0,a-22):a]) or (FRAMING.search(external) and ACTION.search(raw[a:b]))
          or (not external.strip(" \t\r\n。！？,.?!:：") and ACTION.search(raw[a:b])) for a,b in quote)):
        decision,category,reason="explain","attributed_material","当前表达引用或转述了材料；内容按其来源展示，不能直接作为说话人的观察。"
    elif DENY_KNOW.search(external):
        decision,category,reason="explain","epistemic_or_negated_commitment","原句表达了不确定、未证实或对断言的否认；该命题的正反证据需要另行提供。"
    elif IF.search(external) or intent=="conditional":
        decision,category,reason="explain","hypothetical","原句含有条件。前提和后果应保留在条件内，实际是否满足前提仍待证。"
    elif BULK.search(external):
        decision,category,reason="clarify","unspecified_bulk_effect","需提供单条原记录编号和目标范围，整批更改没有获准。"
    elif "撤回" in external or intent=="retraction":
        requested=result.get("retract_target_id")
        valid=bool(isinstance(requested,str) and requested and ds=="unique" and len(typed)==1 and
                   typed[0][1].get("predicate")=="retract_proposal" and
                   [x.get("value") for x in typed[0][1].get("arguments",[]) if isinstance(x,dict)]==[requested])
        if not valid:
            decision,category,reason="clarify","unresolved_retraction","撤回尚未唯一绑定原记录。请指定要撤回的记录号。"
    elif (ds in ("ambiguous","needs_clarification","rejected") or
          (len(typed)>1 and len({digest(g) for _,g in typed})>1)):
        decision,category,reason="clarify","unresolved_interpretation","当前有多个解释或缺少必要信息。请区分具体对象、义项或条件。"
    elif (len(entities)>1 and typed and intent!="correction" and
          max((len(g.get("arguments",[])) for _,g in typed),default=0)<len(entities)):
        decision,category,reason="clarify","unbound_entities","原句包含多个不同对象，候选无法分别绑定全部角色。请指出本次询问的对象。"
    elif (NEG.search(CHOICE_QUESTION.sub("",external)) and intent not in ("correction","quoted_material") and typed
          and any(g.get("polarity")=="positive" for _,g in typed)):
        decision,category,reason="clarify","polarity_scope","原文的否定范围与正向候选不一致，需先核实命题的极性。"
    elif not typed:
        decision,category,reason="explain","no_executable_proposition","本句没有得到具有完整参数的可核验命题。"
    result["boundary"]={"version":VERSION,"decision":decision,"category":category,"reason":reason,
                        "allow_dispatch":decision=="pass","write_authority":"none","source_sha256":hashlib.sha256(raw.encode()).hexdigest(),
                        "original_alternatives":deepcopy(alternatives),"original_alternatives_sha256":digest(alternatives),
                        "original_input_spans_sha256":digest(result.get("input_spans",[])),"quoted_spans":quote_data}
    if decision!="pass":
        for alternative in alternatives:alternative["dispatch_target"]="none"
    return result

