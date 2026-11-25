"""Bind an explicit source review to a registered, closed CL target and native PCGM batch receipts."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from tempfile import TemporaryDirectory
import shutil

import source_provenance25 as provenance

ROOT=Path(__file__).resolve().parents[1]
SYMBOL=r"[a-z][a-z0-9_]{0,47}"
GOAL=re.compile(r"scoped_claim\(("+SYMBOL+"),("+SYMBOL+"),("+SYMBOL+r")\)")
REQUEST=re.compile(r"[a-z][a-zA-Z0-9_.:-]{0,119}")
RULES=(": labelled_support(sym,sym,sym).",": scoped_claim(sym,sym,sym).",
       "scoped_claim($s,$a,$o) <- labelled_support($s,$a,$o).",
       "!scoped_claim($s,$a,$o) <- !labelled_support($s,$a,$o).")
packed=provenance.canonical
def pin(value):return hashlib.sha256(packed(value).encode()).hexdigest()


def setup(db):
    for statement in (
        """CREATE TABLE IF NOT EXISTS joint25_source_requests(
          id TEXT PRIMARY KEY,claim TEXT NOT NULL,scope TEXT NOT NULL,atom TEXT NOT NULL,approval TEXT NOT NULL,
          payload TEXT NOT NULL,phase TEXT NOT NULL,receipt TEXT,created_ns INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS joint25_source_batches(request TEXT NOT NULL,sequence INTEGER NOT NULL,
          id TEXT NOT NULL UNIQUE,basis TEXT NOT NULL,wire TEXT NOT NULL,receipt TEXT,PRIMARY KEY(request,sequence))""",
        """CREATE TABLE IF NOT EXISTS joint25_source_views(
          claim TEXT PRIMARY KEY,scope TEXT NOT NULL,atom TEXT NOT NULL UNIQUE,approval TEXT NOT NULL,
          last_request TEXT NOT NULL,signature TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS joint25_source_pending ON joint25_source_requests(claim,phase)"):
        db.execute(statement)


def exists(db,name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None


_RESERVED = re.compile(r"\b(?:labelled_support|scoped_claim|jv[0-9a-f]{28})\b")
_SOURCE_ATOM = re.compile(r"\b(?:labelled_support|scoped_claim)\s*\(\s*("+SYMBOL+r")\s*,\s*("+SYMBOL+r")\s*,\s*("+SYMBOL+r")\s*\)")
_RAW_ARTIFACT_WRITES = {
    ":admit_workspace",":admit_frozen",":admit_cl",":admit_cl_decide",":answer_packet",
    ":install_ir",":install_pkg",":install_scoped_pkg",":install_workspace",":replace_ir",
    ":replace_pkg",":replace_workspace",":stage_cl",":commit_cl",":stage_from_evidence",
}


def guard_command(db,text,session="main",*,root=None):
    """Guard the local interactive maintenance surface before any raw native command is dispatched."""
    q=text.strip().rstrip("。！？?! ")
    prefix,_,arg=q.partition(" ");arg=arg.strip()
    if prefix not in {"采集","回答","撤回观察","恢复观察","证明","求证","PCGM"} or not arg:return None
    # Only this integration owns the namespace; legacy installations without it keep their original protocol.
    registered=exists(db,"joint25_goals") and db.execute("SELECT 1 FROM joint25_goals LIMIT 1").fetchone()
    if not registered:
        module=Path(root or ROOT)/"state/modules/dialogue25.cl"
        registered=(module.is_file() and module.stat().st_size<=2*1024*1024 and
                    "scoped_claim($s,$a,$o) <- labelled_support($s,$a,$o)." in module.read_text(encoding="utf-8-sig"))
    if not registered and not (exists(db,"slot31_bindings") and
        db.execute("SELECT 1 FROM slot31_bindings WHERE slot='C' AND adapter_id='joint25-pcgm'").fetchone()):
        return None
    if prefix=="PCGM" and ("\n" in arg or "\r" in arg):return "本机原生运维只接收单条命令。"
    cmd=arg.split(maxsplit=1)[0] if prefix=="PCGM" else prefix
    if prefix=="PCGM" and cmd in _RAW_ARTIFACT_WRITES:
        return "这个原生命令会从另一份制品导入内容。请使用带目标及版本核对的答卷或模块发布接口。"
    if prefix=="PCGM" and cmd in {":repair_step",":withdraw_review"}:
        from joint25_agenda_host import owner_hint
        action=("输入「执行规则改进」，由宿主复核原生选项并处理合格变更。" if cmd==":repair_step" else "已委托采纳的答卷可用「撤回已提交答卷 原委托任务编号」处理。")
        return "此原始指令未派发。"+owner_hint(db,action)
    if prefix=="PCGM" and cmd==":install":
        parts=arg.split()
        if len(parts)!=2 or not re.fullmatch(SYMBOL,parts[1]):return "模块名称格式无效。"
        folder=(Path(root or ROOT)/"state/modules").resolve()
        path=folder/(parts[1]+".cl")
        if path.resolve()!=path or not path.is_file() or path.stat().st_size>2*1024*1024:return "模块未以可核对的本地普通文件提供。"
        source=path.read_text(encoding="utf-8-sig")
        if _RESERVED.search(source) or re.search(r"(?m)^\s*@",source):
            return "本模块涉及来源专用谓词或新增修复范围。请分别走联合版本发布或「复核修复范围」，原命令未执行。"
        return None
    inspected=arg
    if prefix=="采集":
        inspected="|".join(arg.split("|")[1:])
    elif prefix=="回答":
        fields=arg.split(maxsplit=3)
        inspected=fields[3] if len(fields)==4 else ""
    inspected=re.sub(r'"(?:[^"\\]|\\.)*"','""',inspected)
    if prefix in {"采集","回答","撤回观察","恢复观察"} and _RESERVED.search(inspected):
        from joint25_agenda_host import owner_hint
        return "这项观察由来源账本托管，请先登记或撤回来件。"+owner_hint(db,"宿主会为已映射的命题排队核验，可用「来源投影 命题号」查询。",background=True)
    if not _RESERVED.search(inspected):return None
    if prefix=="PCGM" and cmd.startswith(":") and cmd not in {
        ":proof_integrity",":explain",":json",":then",":then_why",":time_diff"
    }:
        return "这项原生操作涉及受管来源。请通过「来源投影 命题号」核对依据；本次没有原生写入。"
    atoms=list(_SOURCE_ATOM.finditer(inspected))
    if not atoms or len(atoms)!=len(list(_RESERVED.finditer(inspected))):return "请以完整的三参数目标或该命题编号核对来源。"
    for atom in atoms:
        goal="scoped_claim("+",".join(atom.groups())+")"
        guard=target_guard(db,goal)
        if not guard["current"]:
            return "来源投影待复核："+guard["reason"]+"。旧原生状态不能作为本轮现行结论，请核对原申请。"
    return None


def target(db,claim):
    if not exists(db,"joint25_goals"):raise ValueError("宿主尚未登记可核准的联合目标")
    row=db.execute("SELECT atom,goal,description FROM joint25_goals WHERE claim_id=?",(claim,)).fetchone()
    if not row:raise ValueError("先明确登记这份来源针对的联合语义目标，再核准")
    atom,goal,description=row
    match=GOAL.fullmatch(atom)
    if not match:raise ValueError("只允许已登记、完全具名的 scoped_claim(义项,主体,对象)")
    import verify_sense_version
    issue=verify_sense_version.for_atom(db,atom)
    if issue:raise ValueError(issue)
    structured=json.loads(goal)
    exact={"predicate":"scoped_claim","polarity":"positive","arguments":[{"type":"sym","value":a} for a in match.groups()]}
    if structured!=exact or claim!="claim_"+pin(exact)[:24]:raise ValueError("命题编号、原子与结构化语义目标未全部对齐")
    return dict(claim=claim,atom=atom,goal_sha256=pin(structured),description=str(description or ""))


def review(db,claim,scope):
    t=target(db,claim);gate=provenance.assess(db,claim,scope_key=scope)
    approval=pin({"protocol":"joint25-source-binding/1","target":t,"scope":scope,"source_snapshot":gate["input_sha256"]})
    return {"target":t,"source_admission":gate,"approval_sha256":approval}


def target_guard(db,atom):
    """Call before displaying a jointly-managed conclusion. An unapproved changed source invalidates current use."""
    registered=db.execute("SELECT claim_id FROM joint25_goals WHERE atom=? LIMIT 1",(atom,)).fetchone() if exists(db,"joint25_goals") else None
    stages=exists(db,"joint25_source_requests")
    pending=db.execute("SELECT id FROM joint25_source_requests WHERE atom=? AND phase='prepared' LIMIT 1",(atom,)).fetchone() if stages else None
    if pending:return {"current":False,"status":"pending","request":pending[0],"reason":"正在核对原生批次回执"}
    view=db.execute("SELECT claim,scope,approval,last_request FROM joint25_source_views WHERE atom=?",(atom,)).fetchone() if stages else None
    if not view:
        if registered and exists(db,"prov25_sources") and db.execute("SELECT 1 FROM prov25_sources WHERE claim_id=? LIMIT 1",(registered[0],)).fetchone():
            return {"current":False,"status":"awaiting_approval","claim_id":registered[0],"reason":"来源与当前命题仍待核验，可查看执行报告"}
        return {"current":True,"status":"unmanaged"}
    try:r=review(db,view[0],view[1])
    except ValueError as ex:return {"current":False,"status":"changed_goal","claim_id":view[0],"reason":str(ex)}
    if r["approval_sha256"]!=view[2]:return {"current":False,"status":"stale","claim_id":view[0],"reason":"目标或来源版本已变化，等待当前版本的核验回执。"}
    gate=r["source_admission"]
    if gate["admission"] in {"unknown","invalid_source"} and gate["independent_families"]:
        return {"current":False,"status":"unresolved_admission","claim_id":view[0],"reason":"保留独立来源，当前尚不可作整体肯定或否定"}
    return {"current":True,"status":"synchronized","claim_id":view[0],"source_admission":r["source_admission"]["admission"],
            "last_request":view[3],"approval_sha256":view[2]}


class Native:
    def __init__(self,state,binaries):
        self.state=Path(state).resolve(strict=True);self.bin=Path(binaries).resolve(strict=True)
    def run(self,owner,args,data=b""):
        if owner not in ("alpha","beta"):raise ValueError("原生端点无效")
        p=subprocess.run([self.bin/("pcgm-"+owner+".exe"),*args],input=data,capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW,timeout=12)
        if p.returncode:raise RuntimeError("PCGM 返回错误："+(p.stderr or p.stdout).decode("utf8","replace")[-300:])
        return p.stdout
    def snapshot(self):
        snap=json.loads(self.run("alpha",["--desktop-snapshot",self.state]))
        if not re.fullmatch("[0-9a-f]{64}",snap["head"]) or not snap["individual"]:raise ValueError("原生状态头无效")
        return snap
    def read(self,query):
        out=json.loads(self.run("alpha",["--read-channel",self.state],("review "+query+"\n").encode()))
        if out.get("id")!="review" or not out.get("ok"):raise ValueError("原生读回失败："+str(out.get("error",""))[:220])
        return out["payload"]
    def batch(self,snap,wire):
        lines=self.run(snap["owner"],["--resume",self.state],(wire+"\n").encode()).decode().splitlines()
        if not lines or not lines[0].startswith("individual="+snap["individual"]+" "):raise ValueError("原生写入身份错误")
        if len(lines)!=2 or lines[1].startswith("QUERY_ERROR"):raise ValueError("批次未获原生系统接受："+" ".join(lines[1:])[:260])
        return json.loads(lines[1])


def projection(reviewed):
    gate=reviewed["source_admission"];atom=reviewed["target"]["atom"];base=atom.replace("scoped_claim(","labelled_support(",1)
    result={}
    for family,entry in gate["independent_families"].items():
        direction=entry["stance"];label="jv"+pin([reviewed["target"]["claim"],atom,family,direction])[:28]
        result[label]={"family":family,"fact":("!" if direction=="opposes" else "")+base,"evidence_ids":entry["evidence_ids"]}
    return result


def independent_check(db,view,desired,scope):
    """Verify the direction of the approved witnesses via a real L2/L5 pair, never an expected-data oracle."""
    import slots31
    slots=slots31.snapshot(db)
    if not all(slots[k]["state"]=="ready" and slots[k]["id"]==aid for k,aid in (("L","joint25-cl"),("C","joint25-pcgm"))):
        raise ValueError("核准需要当前就绪并绑定的 joint25-cl 和 joint25-pcgm")
    atom=view["target"]["atom"];goal=view["approval_sha256"];lines=list(RULES)
    lines += [f"& {label} {record['fact']}." for label,record in sorted(desired.items())]
    source="\n".join(lines+[f"? {atom}.",""])
    result=slots31.dispatch(db,"L2",{"source":source},input_version=goal,pin=slots["L"],owner=scope)
    check=slots31.dispatch(db,"L5",{"source":source,"receipt":result},input_version=goal,pin=slots["L"],owner=scope)
    signs={v["fact"].startswith("!") for v in desired.values()}
    role="conflict" if len(signs)>1 else "counter" if signs=={True} else "support" if signs=={False} else "insufficient"
    rows=result["output"]["results"]
    if (not check["output"].get("matches") or check["output"]["proof_ref"]!=result["output"]["proof_ref"] or
        len(rows)!=1 or pin(rows[0]["goal"])!=view["target"]["goal_sha256"] or
        rows[0]["status"]!=slots["L"]["value_domain"][role] or result["output"]["source_sha256"]!=hashlib.sha256(source.encode()).hexdigest()):
        raise ValueError("独立 L2/L5 回执、来源方向或值域不一致")
    return {"role":role,"status":rows[0]["status"],"proof_ref":result["output"]["proof_ref"],"language":slots31.pin(slots["L"]),
            "cognition":slots31.pin(slots["C"]),"input_version":goal,"program_sha256":hashlib.sha256(source.encode()).hexdigest(),
            "sources":result["sources"],"replayed":True}


def _edits(snap,atom,desired,managed):
    facts={};inactive=set(snap["inactive"]);target_fact=atom.replace("scoped_claim(","labelled_support(",1)
    for label,sign,fact in re.findall(r"(?m)^\s*&\s+([a-z][a-z0-9_]*)\s+(!?)(labelled_support\([^()\r\n]+\))\s*\.",snap["source"]):
        if fact.replace(" ","")!=target_fact:continue
        if label not in managed:
            raise ValueError("此目标已有其他来源机制的观察，需明确归并，原记录保持原样")
        facts[label]=sign+fact.replace(" ","")
    current=set(facts)-inactive
    changes=["withdraw "+x for x in sorted(current-desired.keys())]
    for label,obj in sorted(desired.items()):
        if label in facts and facts[label]!=obj["fact"]:raise ValueError("原生来源号已绑定其他内容")
        if label not in current:
            changes.append("restore "+label if label in facts else "observe "+label+" "+obj["fact"])
    return changes


def closed_namespace(source):
    found=set()
    for raw in source.splitlines():
        line=raw.partition("#")[0].strip()
        if not re.search(r"\b(?:labelled_support|scoped_claim)\b",line):continue
        compact=re.sub(r"\s+","",line)
        if line.startswith(":") and compact in {":labelled_support(sym,sym,sym).",":scoped_claim(sym,sym,sym)."}:
            found.add(compact);continue
        if re.fullmatch(r"\?!?scoped_claim\("+SYMBOL+","+SYMBOL+","+SYMBOL+r"\)\.",compact):continue
        if re.fullmatch(r"&[a-z][a-z0-9_]*!?labelled_support\("+SYMBOL+","+SYMBOL+","+SYMBOL+r"\)\.",compact):continue
        rule=re.fullmatch(r"(!?)scoped_claim\((\$[a-z]\w*),(\$[a-z]\w*),(\$[a-z]\w*)\)<-\1labelled_support\(\2,\3,\4\)\.",compact)
        if rule and len(set(rule.groups()[1:]))==3:found.add("rule"+rule[1]);continue
        raise ValueError("联合来源谓词参与了未获本接口验证的规则或动作；保持只读")
    if found!={":labelled_support(sym,sym,sym).",":scoped_claim(sym,sym,sym).","rule","rule!"}:
        raise ValueError("当前原生源缺少完整的封闭正反投影定义")


def preview(native,current,claim,atom,request,approval,edits,expected):
    plans=[]
    with TemporaryDirectory(prefix="zaizai-source-preflight-") as td:
        dest=Path(td)/native.state.name
        shutil.copyfile(native.state,dest)
        for folder in ("modules",native.state.name+".history",native.state.name+".episodes"):
            p=native.state.parent/folder
            if p.is_dir():shutil.copytree(p,dest.parent/folder)
        trial=Native(dest,native.bin);start=trial.snapshot()
        if start["head"]!=current["head"] or start["individual"]!=current["individual"]:raise ValueError("副本起点已变化")
        offset=0
        while offset<len(edits):
            seq=len(plans);ops=[];batch="jb"+pin([current["individual"],request,approval,seq])[:26]
            wire=":observation_batch "+batch+" "+start["head"]
            for op in edits[offset:offset+8]:
                candidate=wire+" ; "+op
                if len(candidate.encode())>512:break
                wire=candidate;ops.append(op)
            if not ops:raise ValueError("单条来源变更超过原生 512 字节预算")
            offset+=len(ops)
            receipt=trial.batch(start,wire);after=trial.snapshot()
            if receipt.get("status")!="committed" or receipt.get("basis_sha256")!=start["head"]:raise ValueError("副本核准回执不完整")
            plans.append(dict(batch=batch,basis=start["head"],wire=wire,head=after["head"],edits=ops))
            start=after
        checked=trial.read("reasoned_outcome evidence "+atom)
        if checked.get("status")!=expected:raise ValueError("独立 CL 预期与同身份原生试提交不同；没有写入正式存档")
    return plans


def sync(db,claim,approval,request_id,scope,*,root=None,bin_dir=None,state=None,after_native=None,after_prepare=None):
    """Caller holds the same host writer as ordinary turns. This route must precede other mutable host work."""
    if db.in_transaction:raise ValueError("来源核准必须在独立的宿主请求边界开始")
    if not REQUEST.fullmatch(request_id) or not re.fullmatch("[0-9a-f]{64}",approval):raise ValueError("核准请求号或摘要格式错误")
    setup(db)
    prior=db.execute("SELECT claim,scope,atom,approval,payload,phase,receipt FROM joint25_source_requests WHERE id=?",(request_id,)).fetchone()
    if prior and (prior[0],prior[1],prior[3])!=(claim,scope,approval):raise ValueError("相同请求号携带不同的来源核准")
    if prior and prior[5]=="committed":return dict(json.loads(prior[6]),duplicate=True)
    if prior and prior[5] in {"cancelled","partial"}:raise ValueError("此前该请求已对账封存；继续同步须重新核准当前版本")
    v=review(db,claim,scope);atom=v["target"]["atom"];desired=projection(v)
    import slots31
    live_slots=slots31.snapshot(db)
    if not all(live_slots[k]["state"]=="ready" and live_slots[k]["id"]==name for k,name in (("L","joint25-cl"),("C","joint25-pcgm"))):
        raise ValueError("来源投影只能在联合包两槽实际绑定后运行")
    root=Path(root or ROOT).resolve();native=Native(state or root/"state/individual.pcgm",bin_dir or root/"releases/joint25/bin")
    current=native.snapshot()
    if exists(db,"life3_meta"):
        host=db.execute("SELECT value FROM life3_meta WHERE key='identity'").fetchone()
        if not host or host[0]!=current["individual"]:raise ValueError("目标存档和当前宿主身份不符")
    closed_namespace(current["source"])
    if prior and prior[2]!=atom:raise ValueError("原请求的目标已改变，不可重投")
    other=db.execute("SELECT id FROM joint25_source_requests WHERE phase='prepared' AND id<>? LIMIT 1",(request_id,)).fetchone()
    if other:raise ValueError("另有来源核准待核对："+other[0])
    old=db.execute("SELECT scope,atom,signature,claim FROM joint25_source_views WHERE claim=? OR atom=?",(claim,atom)).fetchall()
    if len(old)>1 or (old and (old[0][0],old[0][1],old[0][3])!=(scope,atom,claim)):raise ValueError("此目标已有其他会话或命题的核准绑定")
    if not prior:
        if v["approval_sha256"]!=approval:raise ValueError("目标或来源摘要已过期，未送入原生系统")
        if not old and not desired:raise ValueError("没有可核准的独立来源，也没有需要撤回的旧投影")
        check=independent_check(db,v,desired,scope)
        known=set(json.loads(old[0][2])) if old else set()
        for row in db.execute("SELECT payload FROM joint25_source_requests WHERE claim=? AND atom=? AND phase IN ('committed','partial')",(claim,atom)):
            known.update(json.loads(row[0])["desired"])
        edits=_edits(current,atom,desired,known)
        expected={"support":"POSITIVE","counter":"NEGATIVE","conflict":"CONFLICT","insufficient":"UNKNOWN"}[check["role"]]
        plans=preview(native,current,claim,atom,request_id,approval,edits,expected)
        payload={"actor":current["individual"],"start_head":current["head"],"check":check,"target":v["target"],
                 "source_snapshot":v["source_admission"]["input_sha256"],"admission":v["source_admission"]["admission"],
                 "desired":desired,"edits":edits,"plans":plans,"created_ns":time.time_ns()}
        # No native operation before the host has durably recorded this exact intent.
        with db:
            db.execute("INSERT INTO joint25_source_requests VALUES(?,?,?,?,?,?,'prepared',NULL,?)",
                       (request_id,claim,scope,atom,approval,packed(payload),payload["created_ns"]))
            db.executemany("INSERT INTO joint25_source_batches VALUES(?,?,?,?,?,NULL)",
                [(request_id,i,v["batch"],v["basis"],v["wire"]) for i,v in enumerate(plans)])
        if after_prepare:after_prepare()
    else:payload=json.loads(prior[4])
    if current["individual"]!=payload["actor"]:raise ValueError("原生身份不符")
    for role,key in (("L","language"),("C","cognition")):
        old_binding=payload["check"][key];binding=live_slots[role]
        if any(binding.get(k)!=old_binding.get(k) for k in ("id","version","manifest_sha256")):
            raise ValueError("执行前的槽件与原核准凭据不一致，未重发")
    receipts=[];edits=payload["edits"]
    chunks=[row["edits"] for row in payload["plans"]]
    for seq,ops in enumerate(chunks):
        saved=db.execute("SELECT id,basis,wire FROM joint25_source_batches WHERE request=? AND sequence=?",(request_id,seq)).fetchone()
        if not saved:raise ValueError("预先试提交的原操作缺失，保留未决")
        batch,basis,wire=saved
        digest=hashlib.sha256(wire.encode()).hexdigest()
        receipt=native.read("observation_batch "+batch+" "+digest)
        if receipt["status"]=="not_recorded":
            current=native.snapshot()
            if v["approval_sha256"]!=approval or current["head"]!=basis or current["individual"]!=payload["actor"]:
                raise ValueError("未查到此批次且依据改变，保留原单，不盲目重发")
            native.batch(current,wire)
            if after_native:after_native()
            if native.snapshot()["head"]!=payload["plans"][seq]["head"]:raise ValueError("原生投影与预演头不符，保留原单")
            receipt=native.read("observation_batch "+batch+" "+digest)
        if (receipt.get("status") not in ("committed","already_applied") or receipt.get("individual")!=payload["actor"]
            or receipt.get("request_sha256")!=digest or receipt.get("basis_sha256")!=basis or receipt.get("edits")!=len(ops)):
            raise RuntimeError("原生批次回执不匹配，保留未决")
        receipts.append(receipt)
        with db:db.execute("UPDATE joint25_source_batches SET receipt=? WHERE request=? AND sequence=?",(packed(receipt),request_id,seq))
    result=native.read("reasoned_outcome evidence "+atom)
    expected={"support":"POSITIVE","counter":"NEGATIVE","conflict":"CONFLICT","insufficient":"UNKNOWN"}[payload["check"]["role"]]
    if result.get("status")!=expected:raise ValueError("原生现存结论与独立 CL 来源投影不同，需要复核；保留回执")
    current=native.snapshot()
    if result.get("state_revision")!=current["head"] or pin(result.get("goal"))!=payload["target"]["goal_sha256"]:
        raise ValueError("原生回读对应其他目标或版本，不能报告本轮结论")
    # Verify that the observed state agrees with every expected family label, even after a lost acknowledgement.
    if _edits(current,atom,payload["desired"],set(payload["desired"])|{v.split()[1] for v in edits}|
              {k for x in db.execute("SELECT payload FROM joint25_source_requests WHERE atom=?",(atom,)) for k in json.loads(x[0])["desired"]}):
        raise ValueError("实际观察投影未对齐")
    out={"request":request_id,"claim":claim,"atom":atom,"scope":scope,"approval_sha256":approval,"admission":payload["admission"],
         "proof":payload["check"],"native_truth":result["status"],"native_head":current["head"],
         "batch_receipts":receipts,"families":len(payload["desired"]),"duplicate":False}
    with db:
        db.execute("""INSERT INTO joint25_source_views VALUES(?,?,?,?,?,?) ON CONFLICT(claim) DO UPDATE SET
          approval=excluded.approval,last_request=excluded.last_request,signature=excluded.signature""",
          (claim,scope,atom,approval,request_id,packed(payload["desired"])))
        db.execute("UPDATE joint25_source_requests SET phase='committed',receipt=? WHERE id=?",(packed(out),request_id))
    return out


def reconcile(db,request,scope,*,root=None,bin_dir=None,state=None):
    """Reconcile exact batch receipts. Never sends unacknowledged edits as part of this operation."""
    if db.in_transaction:raise ValueError("对账必须在宿主单写边界独立开始")
    setup(db)
    row=db.execute("SELECT claim,atom,approval,phase,payload,receipt FROM joint25_source_requests WHERE id=? AND scope=?",(request,scope)).fetchone()
    if not row:raise ValueError("本会话没有该核准号")
    claim,atom,approval,phase,encoded,wire=row
    if phase!="prepared":return {"request":request,"phase":phase,"stored":json.loads(wire) if wire else None}
    import slots31
    c=slots31.snapshot(db)["C"]
    if c["state"]!="ready" or c["id"]!="joint25-pcgm":raise ValueError("等待原认知槽重新就绪")
    root=Path(root or ROOT);native=Native(state or root/"state/individual.pcgm",bin_dir or root/"releases/joint25/bin")
    payload=json.loads(encoded);now=native.snapshot()
    if now["individual"]!=payload["actor"]:raise ValueError("对账不属于此原生身份")
    # Cross the actual native writer gate so that an orphaned writer cannot publish after a no-write decision.
    native.run(now["owner"],["--resume",native.state],b"")
    current=native.snapshot();receipts=[];not_recorded=[]
    for seq,plan in enumerate(payload["plans"]):
        wire=plan["wire"];digest=hashlib.sha256(wire.encode()).hexdigest()
        out=native.read("observation_batch "+plan["batch"]+" "+digest)
        if out["individual"]!=payload["actor"] or out["request_sha256"]!=digest:raise ValueError("原批次回执内容不符")
        if out["status"]=="not_recorded":
            not_recorded.append(plan["batch"]);continue
        if out["status"] not in {"committed","already_applied"} or out["basis_sha256"]!=plan["basis"] or out["edits"]!=len(plan["edits"]) or not_recorded:
            raise ValueError("部分批次回执不连续，暂保留未决状态")
        receipts.append(out)
    if not not_recorded:
        # All stored bytes were already applied and independently reread. sync only finalizes the host envelope.
        out=sync(db,claim,approval,request,scope,root=root,bin_dir=bin_dir,state=state)
        return {"request":request,"phase":"committed","stored":out}
    final="partial" if receipts else "cancelled"
    result={"request":request,"phase":final,"confirmed":receipts,"never_dispatched_or_not_recorded":not_recorded,
            "native_head":current["head"],"resume_requires_new_explicit_approval":True}
    with db:
        if receipts:
            old=db.execute("SELECT signature FROM joint25_source_views WHERE claim=?",(claim,)).fetchone()
            labels=json.loads(old[0]) if old else {}
            labels.update(payload["desired"])
            db.execute("""INSERT INTO joint25_source_views VALUES(?,?,?,?,?,?) ON CONFLICT(claim) DO UPDATE SET
                approval=excluded.approval,last_request=excluded.last_request,signature=excluded.signature""",
                (claim,scope,atom,"partial:"+request,request,packed(labels)))
        db.execute("UPDATE joint25_source_requests SET phase=?,receipt=? WHERE id=?",(final,packed(result),request))
    return result


def command(db,text,session,rid,*,root=None,bin_dir=None,state=None):
    op,_,arg=text.strip().partition(" ")
    if op not in {"来源投影","核准来源","核对来源回执","对账来源"}:return None
    if op=="对账来源":
        out=reconcile(db,arg.strip(),session,root=root,bin_dir=bin_dir,state=state)
        return "原生和宿主已核对该请求 "+out["request"]+"，阶段 "+out["phase"]+"。"
    if op=="核对来源回执":
        if not exists(db,"joint25_source_requests"):return "尚无来源核准请求。"
        row=db.execute("SELECT claim,atom,phase,approval,receipt FROM joint25_source_requests WHERE id=? AND scope=?",(arg.strip(),session)).fetchone()
        if not row:return "此会话没有对应来源核准号。"
        return f"{arg.strip()} · {row[2]} · {row[0]} → {row[1]}\n核准摘要 {row[3]}。"
    if op=="来源投影":
        v=review(db,arg.strip(),session);t=v["target"];s=v["source_admission"];state_now=target_guard(db,t["atom"])
        return (f"{t['claim']} → {t['atom']}：{t['description']}\n来源准入 {s['admission']}，独立家族 {s['independent_family_count']}。"
                f"当前投影 {state_now['status']}。\n绑定目标与来源的核准摘要 {v['approval_sha256']}。")
    fields=arg.rsplit(None,1)
    if len(fields)!=2:raise ValueError("用「核准来源 命题编号 核准摘要」；用「来源投影 命题编号」先核对语义目标")
    out=sync(db,fields[0],fields[1],rid,session,root=root,bin_dir=bin_dir,state=state)
    return (f"来源核准 {out['request']} · {out['atom']} · 该次核准时原生读回 {out['native_truth']}。独立家族 {out['families']} 支。"
            f"\nCL 复验 {out['proof']['proof_ref']}，原生状态 {out['native_head']}。")
