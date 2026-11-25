"""The host freezes and scores the tests. Only the selected ports receive the blind input."""
import hashlib
import json
import slots31

def pin(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def proof(db,program):
    slot=slots31.snapshot(db)["L"]
    if slot["state"]=="ready" and ".cl" not in slot.get("formats",[]):
        raise slots31.SlotUnavailable("L","unsupported","这份旧课程需要声明 .cl 输入格式的语言槽")
    result=slots31.dispatch(db,"L2",{"source":program},input_version=pin(program),pin=slot,timeout_ms=4500)
    output=result["output"]
    return {"engine":result["adapter"],"version":result["version"],"program_sha256":output["source_sha256"],
            "proof_sha256":output["proof_ref"].removeprefix("sha256:"),"results":output["results"],
            "program":program,"sources":result["sources"],"input_version":result["input_version"],"value_domain":slot["value_domain"]}

def induce(db,training):
    slot=slots31.snapshot(db)["C"]
    e=slots31.dispatch(db,"C3",{"purpose":"lesson-candidate","training":training},
                       input_version=pin(training),pin=slot,timeout_ms=4500)
    rules=e["output"].get("lesson_candidate")
    if not isinstance(rules,list) or len(rules)!=2 or not all(isinstance(r,list) and 0<len(r)<=12 and all(isinstance(x,str) for x in r) for r in rules):
        raise ValueError("认知槽尚未提交符合本课程格式的候选规则")
    return rules

def examine(db,rules,cases):
    # The representation of this older course is explicit; it is not a universal result vocabulary.
    from legacy_workbook31 import blind_program
    blind=[{"features":tuple(c["features"])} for c in cases]
    source=blind_program(rules,blind)
    measured=proof(db,source)
    answer={r["goal"]["arguments"][0]["value"]:r["status"] for r in measured["results"]}
    actual=[answer.get("item_"+str(i)) for i in range(len(cases))]
    reference={"POSITIVE":"support","NEGATIVE":"counter","UNKNOWN":"insufficient","CONFLICT":"conflict"}
    expected=[measured["value_domain"].get(reference[row["expected"]]) for row in cases]
    correct=len(answer)==len(cases) and all(want is not None and want==observed for want,observed in zip(expected,actual))
    measured.update(actual=actual,contexts=[c["context"] for c in cases],passed=correct,grading="host/frozen-cases-v1",
                    blind_input_sha256=pin(blind),scored_case_count=len(cases))
    return correct,measured

