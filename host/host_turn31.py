"""Host-owned frame, route and receipt metadata for independently replaceable slots."""
import json
import sqlite3
import time
from pathlib import Path
import native as n
import slots31

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS host31_request_routes(
         id TEXT PRIMARY KEY REFERENCES requests(id),bindings TEXT NOT NULL,started INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS host31_commits(
         request_id TEXT PRIMARY KEY REFERENCES requests(id),receipt_id TEXT UNIQUE NOT NULL,
         frame_kind TEXT NOT NULL,plan_sha256 TEXT NOT NULL,route_sha256 TEXT NOT NULL,
         content_sha256 TEXT NOT NULL,slot_receipt TEXT,proof_sources TEXT NOT NULL,created INTEGER NOT NULL)""")

def is_legacy(bindings):
    return ((bindings["L"]["id"],bindings["C"]["id"]) in {("legacy-cl","legacy-pcgm"),("joint25-cl","joint25-pcgm")}
            and all(bindings[x]["state"]=="ready" for x in ("L","C")))

def same_binding(left,right):
    fields=("id","version","revision","manifest_sha256","state")
    return all(left[k].get(f)==right[k].get(f) for k in ("L","C") for f in fields)

def status_line(bindings):
    names={"L":"语言槽 L","C":"认知槽 C"}
    def describe(k):
        item=bindings[k]
        if item["state"]=="empty":return names[k]+" 空缺"
        if item["state"]!="ready":return names[k]+" 不可用（"+str(item.get("reason") or "未通过自检")+"）"
        return names[k]+" "+str(item.get("name") or item["id"])+" "+str(item["version"])
    return " · ".join(describe(k) for k in ("L","C"))

def summarize(db):
    pins=slots31.snapshot(db)
    totals=db.execute("SELECT count(*),max(seq) FROM turns").fetchone()
    return {"identity":n.IDENTITY,"turns":totals[0],"last_seq":totals[1],"slots":pins,"display":status_line(pins)}

def host_data(text,source,**extra):
    return {"answer":str(text),"frame_kind":"host_data","host_status":True,"source":source,**extra}

def unavailable(bindings,reason=None):
    text="此请求已由宿主登记。"+(str(reason) if reason else status_line(bindings))+"。本轮没有生成认知回复。"
    return {"answer":text,"frame_kind":"slot_status","kind":"slot_unavailable","host_status":True,
            "source":"宿主槽件清单","slot_status":bindings}

def operations(db,r,legacy,bindings):
    """Read explicit operational commands without invoking a language or cognitive component."""
    q=r["question"].strip().rstrip("。！？?! ").strip()
    pair=is_legacy(bindings)
    if q in {"槽状态","语言槽状态","认知槽状态","宿主状态"} or (not pair and q=="状态"):
        count=db.execute("SELECT count(*) FROM turns").fetchone()[0]
        return host_data(f"身份 {n.IDENTITY}\n{status_line(bindings)}\n当前存档 {count} 个对话回合。","宿主状态",bindings=bindings)
    if q.startswith("编译文件 ") and not pair:
        path=Path(q[5:].strip().strip('"')).resolve(strict=True)
        if not path.is_file() or path.stat().st_size>4*1024*1024:raise ValueError("请选择 4 MiB 以内的核验文件")
        with path.open("rb") as stream:data=stream.read(4*1024*1024+1)
        if len(data)>4*1024*1024:raise ValueError("读取期间文件超过单次上限")
        pin=n.sha(data)
        observation={"path":str(path),"bytes":len(data),"sha256":pin}
        language=bindings["L"]
        if language["state"]=="ready" and "L2" in language["capabilities"] and path.suffix.lower() in language.get("formats",[]):
            proof=slots31.dispatch(db,"L2",{"source":data.decode("utf-8-sig")},input_version=pin,pin=language)
            out=proof["output"]
            if out.get("refused"):
                return host_data("语言槽拒绝核验："+out["reason"],"L2",file_observation=observation,port_receipt=proof)
            return host_data(f"已核验 {path.name}。证明引用 {out['proof_ref']}，输入版本 {pin}。","L2",
                             file_observation=observation,port_receipt=proof)
        return host_data(f"已读取 {path.name}，{len(data)} 字节，SHA-256 {pin}。\n{status_line(bindings)}。文件已作为资料登记，本轮没有槽证明。",
                         "用户选定的本机文件",file_observation=observation)
    if q in {"最近回执","查看最近回执","回执"} and not pair:
        previous=db.execute("""SELECT r.id,r.seq,h.receipt_id,r.native_receipt FROM requests r
                  LEFT JOIN host31_commits h ON h.request_id=r.id
                  WHERE r.session=? AND r.phase='committed' ORDER BY r.seq DESC LIMIT 1""",(r["session"],)).fetchone()
        recent=(f"\n本会话上次提交为 {previous['id']}（#{previous['seq']}），回执 "+str(previous["receipt_id"] or previous["native_receipt"] or "旧记录")) if previous else ""
        return host_data("原存档 M5 回执 "+legacy["receipt"]+recent,"宿主回执账本")
    if q in {"旧存档","旧记忆","原来的记忆"} and not pair:
        view=n.legacy_memory.overview()
        return host_data(f"第 {view['generation']} 代，tick {view['tick']}。保存 {len(view['memory_targets'])} 条语义记忆；观察对象 "+"、".join(view["observed"])+"。","R28 原检查点",legacy_state=view)
    if q.startswith("回忆 ") and not pair:
        key=q[3:].strip()
        local=db.execute("SELECT body,request FROM memory WHERE name=?",(key,)).fetchone()
        if local:return host_data(local["body"]+"\n来源请求 "+local["request"],"宿主长期记忆")
        records=n.legacy_memory.records(key)
        if not records:return host_data("未检索到名称或摘要匹配的原始记录。","宿主记忆索引")
        value="\n".join(f"{x['target']} · 位置 {x['claim']['position']} · 观测值 {x['claim']['value']} · 原记录摘要 {x['claim_hash']}" for x in records)
        return host_data(value,"R28 原检查点",legacy_records=records)
    if q.startswith("记住 ") and not pair:
        name,separator,body=q[3:].partition("=")
        if not separator or not name.strip() or not body.strip():raise ValueError("请用「记住 名称 = 内容」")
        return host_data("已登记明确提供的记忆「"+name.strip()+"」。","用户提供",change=["remember",name.strip(),body.strip()])
    if q=="帮助" and not pair:
        return host_data("可以查看「槽状态」「最近回执」「旧记忆」「回忆 对象编号」「生命状态」「学情」。历史查找、会话和证据窗可直接使用。","宿主帮助")
    return None

def generic_dialogue(db,r,bindings):
    """A new verified pair may produce a conclusion; a yield or gap only produces host status."""
    revision=r["digest"]
    def invoke(port,payload):
        return slots31.dispatch(db,port,payload,input_version=revision,pin=bindings[port[0]])
    ctx={"session":r["session"],"request":r["id"]}
    parsed=invoke("L1",{"text":r["question"],"context":ctx})
    if parsed["output"].get("refused"):
        return unavailable(bindings,"语言槽拒绝解析："+str(parsed["output"].get("reason","未给理由")))
    frame=dict(id=r["id"],source=r["source"],at=r["started"],speaker="用户",channel="dialogue",
               content=r["question"],revision=revision,category="observation",content_hash=revision,
               context=ctx,parsed=parsed["output"]["parsed"])
    observed=invoke("C1",frame)
    if observed["output"].get("refused"):
        return unavailable(bindings,"认知槽拒绝此次观察："+observed["output"]["reason"])
    thought=invoke("C5",{"budget_ms":800,"preempt":False,"has_work":True,"observation_id":r["id"],"parsed":frame["parsed"],"context":ctx})
    if thought["output"].get("refused"):
        return unavailable(bindings,"认知槽拒绝本次工作："+thought["output"]["reason"])
    conclusion=thought["output"].get("conclusion")
    if not conclusion:return host_data("认知槽已收束本次工作，状态 "+thought["output"]["mode"]+"，尚未提交可表达的结论。","C5",port_receipts=[parsed,observed,thought])
    answer=invoke("L4",{"conclusion":conclusion,"context":ctx})
    if answer["output"].get("refused"):
        return unavailable(bindings,"语言槽拒绝生成表达："+answer["output"]["reason"])
    return {"answer":answer["output"]["text"],"frame_kind":"reply","source":"C5/L4",
            "port_receipts":[parsed,observed,thought,answer]}

