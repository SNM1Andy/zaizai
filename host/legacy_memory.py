"""Expose the preserved 1.0 checkpoint's observations, semantic memory and source references."""
import hashlib
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
def checkpoint():
    state=ROOT/"state"
    meta=json.loads((state/"imported.json").read_bytes())
    raw=(state/"native/offline-six-module-r28-20261120/run/world/joint.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=meta["checkpoint_sha256"]:
        raise ValueError("旧存档检查点与迁移时的摘要不符")
    data=json.loads(raw)["data"]
    legacy=data["core_joint"]["individual"]["state"]
    if legacy["id"]!=meta["identity"] or data["modules"]["semantic_memory"]["ledger_id"]!=meta["identity"]:
        raise ValueError("旧记忆与正式身份不符")
    return data,legacy

def target_symbol(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,45}",value):
        raise ValueError("不支持的旧存档对象编号")
    return value

def definitions():
    data,state=checkpoint()
    lines=[": r28_position(sym,i64,i64,i64).",": r28_recorded(sym,sym).",": r28_remembers(sym).",
           "r28_remembers($object) <- r28_position($object,$x,$y,$v) & r28_recorded($object,$digest)."]
    for i,(target,observed) in enumerate(sorted(state["observed"].items())):
        x,y=observed["position"];v=observed["value"]
        if not all(type(number) is int for number in (x,y,v)) or observed["target"]!=target:
            raise ValueError("不支持的旧观察格式")
        lines.append(f"& old_observed_{i} r28_position({target_symbol(target)},{x},{y},{v}).")
    for i,record in enumerate(data["modules"]["semantic_memory"]["records"]):
        claim=record["claim_hash"]
        if not re.fullmatch(r"[0-9a-f]{64}",claim):
            raise ValueError("旧语义记录缺少内容摘要")
        lines.append(f'& old_memory_{i} r28_recorded({target_symbol(record["target"])},"{claim}").')
    return ("\n".join(lines)+"\n").encode()

def records(target):
    data,state=checkpoint()
    found=[row for row in data["modules"]["semantic_memory"]["records"] if target in
           (row["target"],row["action_id"],row["claim_hash"])]
    return found

def overview():
    data,state=checkpoint()
    memory=data["modules"]["semantic_memory"]["records"]
    return {"generation":data["generation"],"tick":state["tick"],"observed":sorted(state["observed"]),
            "memory_targets":[row["target"] for row in memory],"modules":sorted(data["modules"]),
            "events":len(state["events"]),"pending":len(state["pending"]),"tasks":len(state["tasks"])}

