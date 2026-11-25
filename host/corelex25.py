"""Read the pinned historical CL technical glossary and its Windows-verified examples."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ASSET=Path(__file__).with_name("corelex25.json")
ASSET_SHA256="d45f3691d7ce5ac898fc3e425e85af802ee29a35997000b5998da4619377a618"
ARCHIVE_SHA256="b66076fac44c7bacc1077244c93afd3611c5444e7162bcd86753cf73def6cc9a"

@lru_cache(maxsize=1)
def _records():
    raw=ASSET.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ASSET_SHA256:raise ValueError("技术词典索引与冻结的 Windows 版本不一致。")
    d=json.loads(raw);items=d["senses"]
    if d["archive_sha256"]!=ARCHIVE_SHA256 or len(items)!=500:raise ValueError("技术词典来源或行数不一致。")
    ids={r["sense_id"]:r for r in items};labels={}
    for r in items:
        # Distinguish identically spelled operations with different grammatical roles.
        for label in set([r["zh"],r["en"],r["canonical"],*r["aliases_zh"]]):
            labels.setdefault(label.casefold(),[]).append(r)
    return ids,labels,d["examples"]

def lookup(term):
    ids,labels,_=_records()
    if term in ids:return [ids[term]]
    key=term.casefold()
    if key in labels:return list(labels[key])
    return [row for row in ids.values() if row["canonical"].casefold().startswith(key+"(")]

def command(text):
    q=text.strip().rstrip("。！？")
    if q in ("核心词典","核心词库","CL技术词典"):
        _records()
        return ("CL 技术词典有 500 个义项，含 39 项基础构造、44 种组合用法和 417 项领域关系。原包面向 CL 0.157。"
                "当前 Windows 版复验了 1,003 条示例预期，其中 94 条使用修订夹具或项目命令。"
                "可输入「核心词条 qty_add」「核心词条 冲突」或「核心示例 src_module 1」。")
    m=re.fullmatch(r"(核心词条|核心词义|核心示例)\s+(.{1,180})",q)
    if not m:return None
    op,value=m.groups();index=1
    if op=="核心示例":
        p=re.fullmatch(r"(.+?)\s+([0-9]{1,3})",value)
        if p:value=p[1];index=int(p[2])
    rows=lookup(value.strip())
    if not rows:return f"CL 技术词典没有匹配「{value}」的义项。可用原编号、中文名、别名或 CL 构造名查找。"
    if len(rows)>1:
        return f"「{value}」对应 {len(rows)} 个技术义项。请指定编号。\n"+"\n".join(r["sense_id"]+" · "+r["zh"] for r in rows)
    row=rows[0];name=f"{row['zh']}（{row['sense_id']}）"
    if op!="核心示例":
        checks=row["examples"];adapted=sum("windows_adaptation" in v for v in checks)
        return (f"{name}\n{row['meaning_zh']}\n适用边界：{row['constraints_zh']}\nCL 写法：{row['canonical']}\n"
                f"来源：CL 0.157 技术词典，{row['source']}。原记录状态 {row['status']}。\n"
                f"现用 Windows 实测通过 {len(checks)} 项示例预期，其中 {adapted} 项有适配。输入「核心示例 {row['sense_id']} 1」查看。")
    cases=row["examples"]
    if not 1<=index<=len(cases):return f"{name}共有 {len(cases)} 项示例，请指定 1 至 {len(cases)}。"
    c=cases[index-1];patch=c.get("windows_adaptation");d=patch or c
    _,_,sources=_records();source=sources[d.get("fixture_sha256",c["fixture_sha256"])]
    reason=patch["change"] if patch else "沿用原夹具。"
    cmds=c.get("verified_command") or (patch.get("output",{}).get("argv") if patch else None)
    return (f"{name} · 示例 {index}/{len(cases)}\n原预期：{c.get('expect') or ('退出码 '+str(c.get('exit')) if 'exit' in c else '编译拒绝')}\n"
            f"现用 Windows 复验通过。{reason}\n"+(f"核验入口：{cmds}\n" if cmds else "")+
            f"示例源码（仅供阅读）：\n{source.strip()}\n来源 {row['original_section']}/{c['path']}，原夹具摘要 {c['fixture_sha256'][:16]}。")
