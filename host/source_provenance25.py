"""Host source-admission records. Decisions here concern provenance, never the truth of a claim."""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from graphlib import CycleError, TopologicalSorter

CONTRACT = "grok-source-provenance/2026-11-23+windows.1"
CONTRACT_SHA256 = "28e98f028dadeb4b2a8bd0b55bcc8f9077a997f92a5b56717d1b100c968a7a89"
FIELDS = ("evidence_id","claim_id","stance","source_id","canonical_locator","observed_at",
          "source_family_id","derived_from","content_sha256","scope","review_status","supersedes","endpoint_mismatch")
MAX_SOURCES = 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _id(value):
    if not isinstance(value,str) or not 0<len(value)<=512 or value!=value.strip() or any(ord(c)<32 for c in value):
        raise ValueError("来源、命题和引用须使用非空、无控制符的稳定编号")
    return value


def normalize(row, claim):
    if not isinstance(row,dict) or set(row)!=set(FIELDS):
        raise ValueError("来源包需要契约的全部十三个字段")
    result={k:row[k] for k in FIELDS}
    for key in ("claim_id","source_id","evidence_id"):
        _id(result[key])
    if result["claim_id"]!=claim:raise ValueError("来源包的命题编号不匹配")
    if result["stance"] not in ("supports","opposes") or result["review_status"] not in ("recorded","withdrawn","invalid"):
        raise ValueError("来源方向或审查状态未声明")
    if type(result["endpoint_mismatch"]) is not bool:raise ValueError("终点失配字段须为布尔值")
    if result["source_family_id"] not in (None,""):_id(result["source_family_id"])
    for key in ("scope","canonical_locator"):
        if result[key] is None and key=="canonical_locator":result[key]=""
        if not isinstance(result[key],str) or len(result[key])>8192:raise ValueError("定位或适用范围格式无效")
    try:
        stamp=datetime.fromisoformat(result["observed_at"].replace("Z","+00:00"))
        if stamp.tzinfo is None:raise ValueError
    except (ValueError,AttributeError) as err:
        raise ValueError("observed_at 须为带时区的实际时间") from err
    if result["content_sha256"] is not None and not re.fullmatch("[0-9a-f]{64}",str(result["content_sha256"])):
        raise ValueError("内容摘要须为小写 SHA-256 或 null")
    for key in ("derived_from","supersedes"):
        links=result[key]
        if key=="derived_from" and links is None:continue
        if not isinstance(links,list) or len(links)>MAX_SOURCES:raise ValueError("来源引用列表格式无效")
        result[key]=sorted({_id(v) for v in links})
    return result


def _ordered(graph):
    """Return nodes whose complete dependency chain has a topological order."""
    topology=TopologicalSorter(graph)
    try:topology.prepare()
    except CycleError:pass
    while topology.is_active():
        ready=topology.get_ready()
        if not ready:break
        yield from ready
        topology.done(*ready)


def evaluate(claim_id, records, *, content_bytes=None, withdrawn=()):
    """Evaluate one claim. Optional content_bytes is keyed by evidence_id; bytes are never fetched."""
    _id(claim_id)
    if not isinstance(records,(list,tuple)) or len(records)>MAX_SOURCES:raise ValueError("每个命题至多 1024 项来源")
    content_bytes=content_bytes or {}
    withdrawn={_id(s) for s in withdrawn}
    rows={};by_evidence={};checks={};reasons={};available={}
    for source in records:
        row=normalize(source,claim_id)
        sid=row["source_id"];eid=row["evidence_id"]
        if eid in by_evidence and by_evidence[eid]!=sid:raise ValueError("相同证据号绑定了不同来源")
        if sid in rows and rows[sid]!=row:raise ValueError("相同来源号携带不同记录；新版本须有新号")
        rows[sid]=row;by_evidence[eid]=sid
    if set(content_bytes)-set(by_evidence):raise ValueError("待核对字节没有对应的证据号")
    for sid,row in rows.items():
        eid=row["evidence_id"];pin=row["content_sha256"]
        check="declared_only" if pin else "not_captured"
        if eid in content_bytes:
            body=content_bytes[eid]
            if not isinstance(body,bytes):raise ValueError("内容校验仅接受原始 bytes")
            observed=digest(body)
            check="mismatch" if pin and pin!=observed else "match" if pin else "computed_without_prior_pin"
            checks[eid]={"state":check,"observed_sha256":observed}
        else:checks[eid]={"state":check}
        if row["review_status"]=="withdrawn" or sid in withdrawn:reasons[sid]="withdrawn"
        elif row["review_status"]=="invalid" or not row["canonical_locator"].strip() or check=="mismatch":reasons[sid]="invalid_source"
        elif row["endpoint_mismatch"]:reasons[sid]="endpoint_mismatch"
        elif not row["source_family_id"] or row["derived_from"] is None:reasons[sid]="unknown_lineage"
        else:available[sid]=row
    graph={sid:set(r["derived_from"]) & available.keys() for sid,r in available.items()}
    roots={};lineage_order=list(_ordered(graph))
    for sid in lineage_order:
        row=available[sid];parents=row["derived_from"]
        if not parents:roots[sid]=row["source_family_id"];continue
        families={roots.get(parent) for parent in parents}
        if None in families:reasons[sid]="missing_or_ineligible_parent"
        elif len(families)!=1:reasons[sid]="multiple_origin_families"
        else:roots[sid]=families.pop()
    for sid in available.keys()-set(lineage_order):reasons[sid]="cyclic_or_cyclic_parent"

    # An explicit replacement can affect only the identified sources in its own family.
    # A corrected derivative can still trace back to its predecessor for lineage.
    temporal={}
    for sid,family in roots.items():
        targets=set(rows[sid]["supersedes"])
        invalid=any(t==sid or t not in rows or (t in roots and roots[t]!=family) or
                    (t not in roots and rows[t]["source_family_id"]!=family) for t in targets)
        if invalid:reasons[sid]="unresolved_replacement"
        else:temporal[sid]=targets & roots.keys()
    valid_order=list(_ordered({sid:refs & temporal.keys() for sid,refs in temporal.items()}))
    for sid in temporal.keys()-set(valid_order):reasons[sid]="cyclic_replacement"
    for sid in lineage_order:
        if sid in roots and any(p in reasons for p in rows[sid]["derived_from"]):
            reasons[sid]="missing_or_ineligible_parent"
    replaced={target for sid in valid_order if sid not in reasons for target in temporal[sid]}
    stale=set(replaced)
    for sid in lineage_order:
        if sid in reasons or sid not in roots:continue
        if not rows[sid]["supersedes"] and any(p in stale for p in rows[sid]["derived_from"]):
            stale.add(sid)
    members={}
    for sid,family in sorted(roots.items()):
        if sid in reasons:continue
        if sid in stale:reasons[sid]="superseded";continue
        members.setdefault(family,[]).append(sid)
    resolved={};unresolved=[]
    for family,ids in sorted(members.items()):
        signs={rows[sid]["stance"] for sid in ids}
        if len(signs)==1:
            resolved[family]={"stance":signs.pop(),"source_ids":ids,"evidence_ids":sorted(rows[s]["evidence_id"] for s in ids)}
        else:unresolved.append(family)
    signs={r["stance"] for r in resolved.values()}
    if len(signs)>1:status="conflict"
    elif unresolved:status="unknown"
    elif resolved:status="admitted"
    else:
        kinds=set(reasons.values())-{"withdrawn","superseded"}
        status="invalid_source" if kinds=={"invalid_source"} else "unknown"
    # A hash binds the inputs and byte checks, not a claim about the outside world.
    material={"version":CONTRACT,"claim":claim_id,"sources":[rows[s] for s in sorted(rows)],
              "withdrawn":sorted(withdrawn),"byte_checks":checks}
    return {"contract":CONTRACT,"contract_sha256":CONTRACT_SHA256,"claim_id":claim_id,
            "input_sha256":digest(canonical(material).encode()),"admission":status,
            "independent_family_count":len(resolved),"independent_families":resolved,
            "unresolved_families":unresolved,"excluded":dict(sorted(reasons.items())),"byte_checks":checks,
            "admitted_stance":next(iter(signs)) if status=="admitted" else None,
            "eligible_evidence":sorted(e for v in resolved.values() for e in v["evidence_ids"]) if status=="admitted" else [],
            "truth_result":None}


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS prov25_sources(
       scope_key TEXT NOT NULL, claim_id TEXT NOT NULL, source_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
       body TEXT NOT NULL, sha256 TEXT NOT NULL, recorded_ns INTEGER NOT NULL,
       PRIMARY KEY(scope_key,claim_id,source_id), UNIQUE(scope_key,claim_id,evidence_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS prov25_withdrawals(
       scope_key TEXT NOT NULL, claim_id TEXT NOT NULL, source_id TEXT NOT NULL, withdrawn_ns INTEGER NOT NULL,
       PRIMARY KEY(scope_key,claim_id,source_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS prov25_byte_checks(
       scope_key TEXT NOT NULL, claim_id TEXT NOT NULL, source_id TEXT NOT NULL,
       actual_sha256 TEXT NOT NULL, checked_ns INTEGER NOT NULL,
       PRIMARY KEY(scope_key,claim_id,source_id))""")


def record(db,row,*,scope_key="main",body=None):
    """Append one primary provenance record to the caller's transaction. Never insert a fact."""
    if not isinstance(row,dict) or "claim_id" not in row:raise ValueError("缺少来源记录或命题号")
    _id(scope_key);row=normalize(row,row["claim_id"])
    if row["source_id"].startswith("m7:") or row["evidence_id"].startswith("m7:"):raise ValueError("m7: 编号仅供已登记的学习来源")
    if body is not None:
        checked=evaluate(row["claim_id"],[row],content_bytes={row["evidence_id"]:body})
        if checked["byte_checks"][row["evidence_id"]]["state"]=="mismatch":raise ValueError("所给字节与已登记摘要不符")
    setup(db);scope=(scope_key,row["claim_id"]);wire=canonical(row);pin=digest(wire.encode())
    db.execute("""INSERT OR IGNORE INTO prov25_sources SELECT ?,?,?,?,?,?,?
        WHERE (SELECT count(*) FROM prov25_sources WHERE scope_key=? AND claim_id=?) < ?""",
        (*scope,row["source_id"],row["evidence_id"],wire,pin,time.time_ns(),*scope,MAX_SOURCES))
    existing=db.execute("""SELECT sha256 FROM prov25_sources WHERE scope_key=? AND claim_id=?
               AND (source_id=? OR evidence_id=?)""",(*scope,row["source_id"],row["evidence_id"])).fetchall()
    if not existing:raise ValueError("该命题的证据数已达上限")
    if len(existing)!=1 or existing[0][0]!=pin:raise ValueError("来源或证据号与原记录冲突")
    if body is not None:
        actual=digest(body)
        db.execute("INSERT OR IGNORE INTO prov25_byte_checks VALUES(?,?,?,?,?)",(*scope,row["source_id"],actual,time.time_ns()))
        if db.execute("SELECT actual_sha256 FROM prov25_byte_checks WHERE scope_key=? AND claim_id=? AND source_id=?",
                      (*scope,row["source_id"])).fetchone()[0]!=actual:
            raise ValueError("同一来源版本再次采集时字节不同；请另登记新版本")
    return pin


def study_records(db,claim_id):
    """Read an existing structured M7 registry observation. Unreviewed material stays outside the gate."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study3_observation'").fetchone():return []
    raw=db.execute("""SELECT o.id,o.sign,o.locator,o.kind,s.family,s.uri,s.version,s.active,s.seen
        FROM study3_observation o JOIN study3_source s ON s.id=o.source_id
        WHERE o.claim=? AND o.stage='evidence' AND o.kind IN ('registry_status','registry_method')
        ORDER BY o.id LIMIT ?""",(claim_id,MAX_SOURCES+1)).fetchall()
    if len(raw)>MAX_SOURCES:raise ValueError("观察范围超过单次核验预算")
    result=[]
    for ident,sign,locator,kind,family,uri,version,active,at in raw:
        ref="m7:"+ident
        result.append(dict(evidence_id=ref,claim_id=claim_id,source_id=ref,stance="supports" if sign==1 else "opposes",
            source_family_id=family,canonical_locator=uri+"#"+locator,observed_at=datetime.fromtimestamp(at,timezone.utc).isoformat(),
            derived_from=[],content_sha256=None,scope=f"{kind} · 版本 {version}",supersedes=[],endpoint_mismatch=False,
            review_status="recorded" if active else "withdrawn"))
    return result


def _stored(db,claim,scope_key):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prov25_sources'").fetchone():return [],[]
    rows=db.execute("SELECT body,sha256 FROM prov25_sources WHERE scope_key=? AND claim_id=? ORDER BY source_id",
                    (scope_key,claim)).fetchall()
    result=[]
    for wire,pin in rows:
        if digest(wire.encode())!=pin:raise ValueError("已记来源的存档摘要不符")
        result.append(json.loads(wire))
    withdrawn=[r[0] for r in db.execute("SELECT source_id FROM prov25_withdrawals WHERE scope_key=? AND claim_id=?",(scope_key,claim))]
    return result,withdrawn


def assess(db,claim_id,*,scope_key="main"):
    _id(claim_id);_id(scope_key)
    own,withdrawn=_stored(db,claim_id,scope_key)
    out=evaluate(claim_id,own+study_records(db,claim_id),withdrawn=withdrawn)
    verified=[]
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prov25_byte_checks'").fetchone():
        verified=[{"source":row[0],"sha256":row[1],"checked_ns":row[2]} for row in db.execute(
            "SELECT source_id,actual_sha256,checked_ns FROM prov25_byte_checks WHERE scope_key=? AND claim_id=? ORDER BY source_id",
            (scope_key,claim_id))]
    out["prior_byte_checks"]=verified
    if verified:out["input_sha256"]=digest(canonical([out["input_sha256"],verified]).encode())
    return out


def check_with_language(db,claim_id,*,scope_key="main"):
    """Run L2 and L5 only for admitted evidence; the generated query is about attestation."""
    out=assess(db,claim_id,scope_key=scope_key);out["language_proof"]=None
    if out["admission"]!="admitted":
        out["language_state"]="not_admitted";return out
    import slots31
    bound=slots31.snapshot(db)["L"]
    if bound["state"]!="ready":
        out["language_state"]=bound["state"];return out
    if ".cl" not in bound.get("formats",[]) or not {"L2","L5"}<=set(bound["capabilities"]):
        out["language_state"]="unsupported";return out
    # Only our private hashed identifiers are rendered into code. User/source prose is always data.
    atom="p"+digest(claim_id.encode())[:40]
    lines=[": source_attests(sym)."]
    for family,side in out["independent_families"].items():
        label="f"+digest(family.encode())[:40]
        sign="" if side["stance"]=="supports" else "!"
        lines.append(f"& {label} {sign}source_attests({atom}).")
    lines.append(f"? source_attests({atom}).")
    program="\n".join(lines)+"\n";version=out["input_sha256"]
    try:
        evidence=slots31.dispatch(db,"L2",{"source":program},pin=bound,input_version=version)
        repeat=slots31.dispatch(db,"L5",{"source":program,"receipt":evidence},pin=bound,input_version=version)
    except slots31.SlotUnavailable as err:
        out["language_state"]="unavailable";out["reason"]=str(err);return out
    result=evidence["output"]["results"]
    if len(result)!=1 or not repeat["output"]["matches"]:
        raise ValueError("语言槽未能复验同一来源约束的核验结果")
    expected=bound["value_domain"]["support" if out["admitted_stance"]=="supports" else "counter"]
    if result[0]["status"]!=expected:raise ValueError("语言槽计入的来源方向和准入回执不一致")
    out["language_state"]="reproduced"
    out["language_proof"]={"query":lines[-1],"scope":"admitted_source_attestation","slot":evidence["adapter"],
        "version":evidence["version"],"input_version":version,"sources":evidence["sources"],"result":result[0]["status"],
        "proof_ref":evidence["output"]["proof_ref"],"replay_verified":True}
    return out


def withdraw(db,claim_id,source_id,*,scope_key="main"):
    _id(claim_id);_id(source_id);_id(scope_key);setup(db)
    sources,_=_stored(db,claim_id,scope_key)
    if source_id not in {r["source_id"] for r in sources}:
        raise ValueError("本会话没有此来源；原有 M7 来源按其原来源编号撤回")
    db.execute("INSERT OR IGNORE INTO prov25_withdrawals VALUES(?,?,?,?)",(scope_key,claim_id,source_id,time.time_ns()))
    return assess(db,claim_id,scope_key=scope_key)


def command(db,text,session="main"):
    """Host inspection and explicit local record management, usable with language and cognition detached."""
    if text.strip() in ("来源核验","来源审查"):
        total=db.execute("SELECT COUNT(*) FROM prov25_sources WHERE scope_key=?",(session,)).fetchone()[0] if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prov25_sources'").fetchone() else 0
        return f"本会话来源记录 {total} 条。输入「来源审查 命题编号」查看来源家族与准入结果。"
    op,_,data=text.strip().partition(" ")
    if op not in ("来源登记","来源核验","来源审查","来源求证","撤回来源记录"):return None
    if op=="来源登记":
        try:row=json.loads(data)
        except ValueError as err:raise ValueError("需要包含全部来源字段的 JSON 对象") from err
        if not isinstance(row,dict) or "claim_id" not in row:raise ValueError("缺少命题编号")
        record(db,row,scope_key=session);out=assess(db,row["claim_id"],scope_key=session)
    elif op=="撤回来源记录":
        parts=[s.strip() for s in data.split("|")]
        if len(parts)!=2:raise ValueError("用法：撤回来源记录 命题编号 | 来源编号")
        out=withdraw(db,*parts,scope_key=session)
    elif op=="来源求证":
        out=check_with_language(db,data.strip(),scope_key=session)
        if out["language_proof"]:
            p=out["language_proof"]
            return f"来源准入 {out['admission']}；{p['slot']} 复验证据的陈述方向为 {p['result']}。\n证明 {p['proof_ref']}。"
        return f"来源准入 {out['admission']}，语言核验状态 {out['language_state']}。本轮没有新增事实。"
    else:out=assess(db,data.strip(),scope_key=session)
    groups="；".join(f"{k}（{v['stance']}）" for k,v in out["independent_families"].items())
    return (f"来源准入 {out['admission']}，可计入的独立家族 {out['independent_family_count']} 支。"
            +(f"\n{groups}" if groups else "")+f"\n准入输入摘要 {out['input_sha256']}。事实结论仍待语言槽独立核对。")
