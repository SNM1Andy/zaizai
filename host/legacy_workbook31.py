"""Compatibility encoding of three legacy CL exercises; the answer key stays with the host."""
from itertools import combinations
import re
ID=re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
def synthesize(cases):
    rules=[]
    for label in ("POSITIVE","NEGATIVE"):
        yes=[set(c["features"]) for c in cases if c["expected"]==label]
        no=[set(c["features"]) for c in cases if c["expected"]!=label]
        shared=sorted(set.intersection(*yes))
        for n in range(1,len(shared)+1):
            selected=next((x for x in combinations(shared,n) if all(not set(x)<=other for other in no)),None)
            if selected:
                rules.append(list(selected));break
        else:
            raise ValueError("训练观察不能区分正反例，需要补充反例")
    return rules

def blind_program(rules,cases):
    symbols=sorted({x for row in cases for x in row["features"]} | {x for rule in rules for x in rule})
    if not all(ID.fullmatch(x) for x in symbols):
        raise ValueError("操作标签格式无效")
    lines=[": matched(sym).",*(": feature_"+x+"(sym)." for x in symbols)]
    for prefix,rule in zip(("","!"),rules):
        lines.append(prefix+"matched($x) <- "+" & ".join("feature_"+x+"($x)" for x in rule)+".")
    for i,row in enumerate(cases):
        for j,feature in enumerate(row["features"]):
            lines.append(f"& case_{i}_{j} feature_{feature}(item_{i}).")
    lines.extend(f"? matched(item_{i})." for i in range(len(cases)))
    return "\n".join(lines)+"\n"
