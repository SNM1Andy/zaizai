"""Ground safe Chinese read requests in source spans, without asserting a property or authorizing changes."""
from copy import deepcopy
import re

from language_boundary25_v2 import apply as previous_gate
from language_boundary25_v2 import field, named

VERSION="zh-source-scope-20261125.3a"
# Reconsider only a missing grammatical analysis. Safety, quotation, conditional,
# polarity and knowledge denials have already been classified by the frozen gate.
REPARSE={"no_executable_proposition","unresolved_interpretation","unbound_entities"}
READ_VERB=r"(?:核对|核验|核实|复核|检查|检视|查询|查看|确认|查一查|查一下|查下|看看|看一下|看一看)"
COURTESY=r"(?:(?:能不能|可不可以|是否可以|能否|可否|可以|能)?(?:请你|请您|请|麻烦你|麻烦您|麻烦|烦请|劳烦|帮我|替我)?(?:帮我|替我|先)?|我想(?:请你|请您|先)?)"
INTRO=re.compile(r"^\s*(?:(?:"+COURTESY+r")?"+READ_VERB+r"(?:一下|一下子)?\s*[,，:：]?\s*|请问\s*)")
MODAL=r"是否|有没有|是不是|能不能|可不可以|能否|可否|有无"
STATE=(r"(?:已经|现在|目前|已|仍然|仍|可供|能够)?(?:可以阅读|可以读|能读|可读|阅读|读取|读|借阅|外借|可借阅|可借|可外借|"
       r"能够使用|可以使用|可用|在库|在架|在册|上架|入藏|入库|登记在册|登记完成|登记|"
       r"校对完成|核对完成|核验完成|校验完成|检查完毕|校对完毕|完成校对|完成核验|"
       r"副本就绪|准备就绪|准备好|就绪|备妥|归档|已收录|收录|开放|在线|签收|签发|完成|通过|生效|失效|加密|脱敏)")
QUERY=re.compile(r"^(?P<noun>.{1,68}?)(?:(?P<modal>"+MODAL+r")(?P<attr>"+STATE+r")(?P<end>了[吗么]?|[吗么])?|"
                 r"(?P<plain>"+STATE+r")(?P<ask>了?[吗么]|了没(?:有)?|没有|[？?]))\s*[？?。.！!]*$")
LOCATED=re.compile(r"^(?P<place>[^《》]{1,25}?)(?:正上方的|正下方的|里面的|上面的|下面的|内部的|下方的|上那|里那|内那|"
                    r"中的|上的|里的|内的|下的|旁的|旁边的|前的|后的)(?P<item>.+)$")
COUNTABLE=(r"(?:[份本张册件卷个]?)(?:档案袋|资料袋|文件袋|记录本|笔记本|登记簿|登记册|"
           r"借阅证|借阅卡|索引卡|样本瓶|样品盒|工具箱|备份盘|书签|档案|资料|文件|文档|卷宗|记录册|册子|目录|册|书|卡片|卡|"
           r"样本|样品|清单|报告|图纸|账册|账本|手册|凭证|表格|票据|清册|台账|读本|纸本|地图|书目|图册|本子|副本|纸条|样册)")
COLOR=(r"(?:亮|暗|深|浅|淡|墨|天|藏|乳|米|砖|粉|银|金)?(?:红|橙|黄|绿|青|蓝|紫|粉|灰|黑|白|棕|褐|银|金)(?:颜色|色|封皮|皮)?")
CODE=r"(?:[甲乙丙丁戊己庚辛壬癸]{1,2}|[A-Za-z0-9][A-Za-z0-9_-]{0,15}|[零一二两三四五六七八九十百]{1,4}(?:号|组))"
OBJECT=re.compile(r"^(?:(?:"+COLOR+"|"+CODE+r")(?:的)?"+COUNTABLE+"|"+COUNTABLE+r"(?:编号|号|-)?" +CODE+r")$")
PLACE_NOUN=r"(?:区|排|号)?(?:书架|货架|展架|陈列架|资料架|档案架|存放架|档案柜|资料柜|展柜|储物柜|书柜|文件柜|陈列柜|样品柜|收件箱|架|柜|箱|盒|库|仓|隔间|展台|台|层)"
PLACE=re.compile(r"^(?:(?:[东西南北上下左右前后中](?:边|侧|面|排|区|端)?|中央|门口|"+COLOR+"|"+CODE+r")"+PLACE_NOUN+
                 r"|"+PLACE_NOUN+r"(?:第|编号|号|-)?" +CODE+r")$")
TITLE=re.compile(r"^《(?P<title>[^《》<>{}\[\]“”‘’「」『』\r\n。；！？?!]{1,36})》$")
UNSAFE=re.compile(r"删除|覆盖|授权|执行|写入|免审|绕过|跳过|忽略|强制|取消审批|撤回|当作事实|直接记为")
AMBIGUOUS=re.compile(r"那(?:份|本|个)|这(?:份|本|个)|哪|任选|任一|另一|其他|其它|它|他们|她们|各自|或|及|以及|和|与|还有|两(?:份|本|册)")

def _roles(noun,record):
    loc=LOCATED.fullmatch(noun)
    item=loc["item"] if loc else noun
    begin=loc.start("item") if loc else 0
    # These classifiers are unambiguous only with the explicit, delimited title that follows.
    classifier=re.match(r"^(?:那|这)?[本册份部](?=《)",item)
    if classifier:
        item=item[classifier.end():];begin+=classifier.end()
    title=TITLE.fullmatch(item)
    if title:
        if not title["title"].strip() or UNSAFE.search(title["title"]):return None
        target_begin=begin+1;target_end=begin+len(item)-1
    else:
        if AMBIGUOUS.search(item) or not (OBJECT.fullmatch(item) or named(item,record)):return None
        target_begin=begin;target_end=begin+len(item)
    if loc:
        place=loc["place"]
        if AMBIGUOUS.search(place) or not (PLACE.fullmatch(place) or named(place,record)):return None
    return target_begin,target_end,(loc.span("place") if loc else None),title is not None

def apply(record,raw):
    result=previous_gate(record,raw)
    b=result["boundary"];b["version"]=VERSION
    prior_positive=b["decision"]=="pass" and b["category"]=="proposal"
    if (b["category"] not in REPARSE and not prior_positive) or b["quoted_spans"] or "\n" in raw or UNSAFE.search(raw):
        return result
    intro=INTRO.match(raw);offset=intro.end() if intro else len(raw)-len(raw.lstrip())
    parsed=QUERY.fullmatch(raw[offset:].rstrip())
    if not parsed:return result
    noun=parsed["noun"]
    roles=_roles(noun,record)
    if prior_positive and LOCATED.fullmatch(noun) is None:return result
    # A plain unary proof cannot establish the more specific location-qualified query.
    # If either role is unresolved, retain the source and suppress the unqualified lookup.
    if prior_positive and (not roles or re.search(r"尚未|并不|不能|还没|没有|据说|称作|声称|好像|我想|是否|也许",noun)):
        b.update(decision="clarify",category="unresolved_location",allow_dispatch=False,allowed_operation=None,
                 reason="原句限定了处所；当前候选没有核实完整的对象与位置，需先对齐两个角色。")
        for alternative in result.get("alternatives",[]):alternative["dispatch_target"]="none"
        return result
    if not roles:return result
    if any(x in noun for x in ('"',"'","《《","》》", "，",",","；",";","。")):return result
    low,high,location,is_title=roles
    # Do not resolve alternate lexical senses by naming an object.
    goals=[a["goal"] for a in record.get("alternatives",[]) if isinstance(a.get("goal"),dict)]
    if len({g.get("predicate") for g in goals})>1:return result
    if len(goals)>1 and not location:return result
    anchor=offset+parsed.start("noun")
    subject=field(raw,anchor+low,anchor+high)
    place=field(raw,anchor+location[0],anchor+location[1]) if location else None
    role="attr" if parsed["attr"] is not None else "plain"
    attribute=field(raw,offset+parsed.start(role),offset+parsed.end(role))
    query={"operation":"read_observed_property","subject":subject,"property":attribute,"location_qualifier":place,
           "subject_form":"book_title" if is_title else "labelled_object","result":None,
           "unresolved_until":"registered, version-pinned property mapping with evidence matching the subject and every location qualifier"}
    args=[{"type":"sym","value":subject["surface"]},{"type":"sym","value":attribute["surface"]}]
    if place:args.append({"type":"sym","value":place["surface"]})
    result["alternatives"]=[{"candidate_id":"scope_read_1","goal":{"predicate":"read_observed_property","arguments":args,"polarity":"positive"},
        "variables":[],"sense_ids":[],"source_refs":list(record.get("source_refs",[])),"premises":[],
        "dispatch_target":"host:read_only_state_query","candidate_source":"source_roles_in_explicit_read_request","polarity":"positive",
        "metadata":{"scope":deepcopy(query),"requires_verified_predicate_mapping":True,"user_did_not_assert_property":True}}]
    result.update(intent="query",disambiguation="unique",missing=[])
    b.update(decision="pass",category="explicit_read_only_property",allow_dispatch=True,allowed_operation="read_only",
             read_query=query,reason="已按原文标出要查询的对象、属性和可选位置。真值仍需有来源的核对。")
    return result
