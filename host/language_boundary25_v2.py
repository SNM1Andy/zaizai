"""Refine explicit read-only property queries with roles and original UTF-8 spans."""
from copy import deepcopy
import re
from language_boundary25 import apply as initial_gate

VERSION="zh-source-scope-20261125.2"
# A state request can contain a locating noun without offering an alternative target.
REQUEST=re.compile(r"^\s*(?:(?:请|麻烦|烦请|劳烦)(?:帮我|协助|先|再|直接|仔细)?|我想(?:请你)?)?"
    r"(?P<verb>核对|核实|确认|检查|查询|查看|查一下|查一查|看看|看一下|看一看)"
    r"(?:一下|一下子)?[，,：:\s]*(?P<nominal>[^，,。.;；?!！？：:\n]{1,50}?)"
    r"(?P<ask>是否|能否|可否|有没有|是不是|能不能|可不可以)"
    r"(?P<attribute>[^，,。.;；?!！？：:\n]{1,24}?)(?:了|吗|么)?[？?。.\s]*$")
LOCATED=re.compile(r"^(?P<location>.+?)(?:里面的|上面的|下方的|内部的|中的|上的|里的|内的|下的)(?P<object>.+)$")
# Unrecognized facets remain literal, provided that they are one simple state facet and not an instruction.
PROPERTY=re.compile(r"^(?:已经|已|仍然|目前|现在|仍)?(?:副本)?(?:就绪|备妥|可读|能读|可供阅读|可以阅读|开放|可用|在库|在线|归档|入库|签收|签发|完成|通过|失效|生效|可借|外借|核对(?:完成)?|校对(?:完成)?|加密|脱敏)$")
NAMED=re.compile(r"^(?:[甲乙丙丁戊己庚辛壬癸][\u3400-\u9fff]{1,5}|(?:节点|档案|资料|柜|设施|样本|货架|书架|箱|登记簿)[A-Za-z0-9零一二三四五六七八九十百_-]{1,16}(?:号|柜|架)?|[A-Za-z][A-Za-z0-9_-]{0,15}(?:号|柜|架|盒|箱|档案|资料))$")
SHARED=re.compile(r"还是|或者|或|以及|和|跟|及|并|哪|另一个|其他|其它|它|那份|这个|这些|它们|他们|撤回|写入|删除|修改|授权|批准我")
def field(raw,begin,end):
    return {"surface":raw[begin:end],"start":len(raw[:begin].encode()),"end":len(raw[:end].encode())}
def named(token,record):
    if SHARED.search(token):return False
    for s in record.get("input_spans",[]):
        if s.get("kind") in {"entity","novel_entity"} and s.get("raw_bytes_utf8")==token:return True
    return bool(NAMED.fullmatch(token))

def apply(record,raw):
    trusted=deepcopy(record)
    # Values embedded in an incoming record must never resurrect a previous disposition.
    trusted.pop("boundary",None)
    result=initial_gate(trusted,raw);b=result["boundary"];b["version"]=VERSION
    if b["category"] not in ("no_executable_proposition","unresolved_interpretation","unbound_entities"):
        return result
    if b["quoted_spans"]:return result
    parsed=REQUEST.fullmatch(raw)
    if not parsed:return result
    noun=parsed["nominal"];attr=parsed["attribute"];nominal_start=parsed.start("nominal")
    if SHARED.search(noun) or not PROPERTY.fullmatch(attr):return result
    loc=LOCATED.fullmatch(noun)
    if loc:
        target,location=loc["object"],loc["location"]
        if not named(target,result) or not named(location,result):return result
        subject_range=field(raw,nominal_start+loc.start("object"),nominal_start+loc.end("object"))
        place_range=field(raw,nominal_start+loc.start("location"),nominal_start+loc.end("location"))
    else:
        if not named(noun,result):return result
        subject_range=field(raw,nominal_start,parsed.end("nominal"));place_range=None
    attr_range=field(raw,parsed.start("attribute"),parsed.end("attribute"))
    # The location constrains the lookup. It is neither a second subject nor an inferred location fact.
    lookup={"operation":"read_observed_property","subject":subject_range,"property":attr_range,"location_qualifier":place_range,
            "result":None,"unresolved_until":"registered, version-pinned read operation with evidence matching all roles"}
    args=[{"type":"sym","value":subject_range["surface"]},{"type":"sym","value":attr_range["surface"]}]
    if place_range:args.append({"type":"sym","value":place_range["surface"]})
    result["alternatives"]=[{"candidate_id":"scope_read_1","goal":{"predicate":"read_observed_property","arguments":args,"polarity":"positive"},
        "variables":[],"sense_ids":[],"source_refs":list(record.get("source_refs",[])),"premises":[],
        "dispatch_target":"host:read_only_state_query","candidate_source":"source_roles_in_explicit_read_request","polarity":"positive",
        "metadata":{"scope":lookup,"requires_verified_predicate_mapping":True,"user_did_not_assert_property":True}}]
    result.update(intent="query",disambiguation="unique",missing=[])
    b.update(decision="pass",category="explicit_read_only_property",allow_dispatch=True,allowed_operation="read_only",
             reason="原句明确请求读取一个对象的状态；保留处所修饰和原文字节范围，属性真值尚无结论。",read_query=lookup)
    return result

