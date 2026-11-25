"""Host-owned append-only memory. Evidence identity is separate from repetition and presentation."""
import hashlib
import json
import sqlite3
import time

KINDS=("working","episodic","semantic","procedural","skill")
CATEGORIES=("firsthand","teacher","external","inference","replay")
def packed(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)
def sha(text):return hashlib.sha256(text.encode("utf8")).hexdigest()
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS host31_memory(
        id TEXT NOT NULL,revision INTEGER NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,category TEXT NOT NULL,
        source_ref TEXT NOT NULL,evidence TEXT NOT NULL,confidence TEXT NOT NULL,context TEXT NOT NULL,contrary TEXT NOT NULL,
        derived_from TEXT NOT NULL,source_families TEXT NOT NULL,content_sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL,
        owner TEXT NOT NULL,PRIMARY KEY(id,revision))""")
    db.execute("CREATE INDEX IF NOT EXISTS host31_memory_owner ON host31_memory(owner,created_ns)")
    db.execute("""CREATE VIEW IF NOT EXISTS host31_current_memory AS SELECT m.* FROM host31_memory m WHERE NOT EXISTS
        (SELECT 1 FROM host31_memory newer WHERE newer.id=m.id AND newer.revision>m.revision)""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS host31_memory_immutable BEFORE UPDATE ON host31_memory
        BEGIN SELECT RAISE(ABORT,'immutable memory; append a revision'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS host31_memory_no_delete BEFORE DELETE ON host31_memory
        BEGIN SELECT RAISE(ABORT,'immutable memory; retain counterevidence'); END""")

    _import_archive(db)

def insert(db,*,key,revision,kind,content,category,source_ref,evidence,confidence,context,contrary,derived,families,owner):
    if not key or not source_ref or not owner or kind not in KINDS or category not in CATEGORIES:
        raise ValueError("记忆种类或来源不完整")
    if type(revision) is not int or revision<1 or len(content)>128000:raise ValueError("记忆版本或长度不符")
    data=(key,revision,kind,content,category,source_ref,packed(sorted(set(evidence))),confidence,packed(context),
          packed(sorted(set(contrary))),packed(sorted(set(derived))),packed(sorted(set(families))),sha(content),owner)
    prior=db.execute("""SELECT id,revision,kind,content,category,source_ref,evidence,confidence,context,
        contrary,derived_from,source_families,content_sha256,owner FROM host31_memory WHERE id=? AND revision=?""",(key,revision)).fetchone()
    if prior:
        if tuple(prior)!=data:raise ValueError("同一记忆版本的内容或来源不同")
        return key
    db.execute("INSERT INTO host31_memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",data[:-1]+(time.time_ns(),owner))
    return key

def observe(db,event_id,channel,text_or_summary,source,speaker,metadata):
    meta=metadata or {};text=str(text_or_summary or "");kind=meta.get("kind","")
    owner=str(meta.get("session") or ("main" if channel=="dialogue" else "host"))
    teaching=channel=="dialogue" and speaker=="用户" and text.startswith(("教导","纠正","价值判断","共情","我指的是"))
    if teaching:category="teacher"
    elif channel=="dialogue":category="firsthand"
    elif kind in ("fetch","source_review","advisor","inquiry_advisor") or channel in ("network","advisor"):category="external"
    elif meta.get("replay"):category="replay"
    elif meta.get("proof") or meta.get("proof_sha256"):category="inference"
    else:category="firsthand"
    ref=str(source or channel)
    # A teacher's repeated account contributes one source family within this classroom/session.
    if category=="teacher":families=["teacher:"+owner+":"+str(speaker)]
    elif category=="external":families=["external:"+ref.partition(" @")[0].partition("#")[0]]
    elif category in ("inference","replay"):families=[]
    else:families=["event:"+event_id]
    version=meta.get("input_version",meta.get("source_version"))
    evidence=meta.get("proof_sha256") or meta.get("receipt")
    return insert(db,key=event_id,revision=1,kind="episodic",content=text,category=category,source_ref=ref,
        evidence=[str(evidence)] if evidence else [],confidence="reported" if teaching or category=="external" else "recorded",
        context={"channel":channel,"speaker":speaker,"version":version},contrary=[],derived=[],families=families,owner=owner)

def search(db,*,query="",owner="main",limit=12,category=None,since_ns=0,kind=None,source_ref=None):
    if not isinstance(query,str) or not isinstance(owner,str) or not owner:raise ValueError("记忆检索缺少会话")
    if category and category not in CATEGORIES:raise ValueError("未知来源类别")
    if type(limit) is not int or not 1<=limit<=32:raise ValueError("记忆检索预算超限")
    rows=db.execute("""SELECT m.* FROM host31_current_memory m WHERE owner IN (?, 'host')
          AND (?='' OR instr(content,?)>0 OR id=?) AND (? IS NULL OR category=?) AND created_ns>=? AND (? IS NULL OR kind=?) AND (? IS NULL OR source_ref=?)
          ORDER BY created_ns DESC LIMIT ?""",(owner,query,query,query,category,category,since_ns,kind,kind,source_ref,source_ref,limit)).fetchall()
    return [dict(r) for r in rows]
def propose(db,proposal,*,owner,source_ref):
    if not isinstance(proposal,dict) or set(proposal)-{"id","kind","content","parents","contrary","revision","supersedes","status"}:
        raise ValueError("未声明的记忆写入字段")
    key=proposal.get("id");kind=proposal.get("kind");body=proposal.get("content");parents=proposal.get("parents");contrary=proposal.get("contrary",[])
    if not isinstance(key,str) or not key.startswith("derived:") or len(key)>150 or not isinstance(body,str) or not body.strip():
        raise ValueError("派生记忆需要独立编号和正文")
    if not isinstance(parents,list) or not parents or not isinstance(contrary,list) or len(parents)+len(contrary)>24:
        raise ValueError("缺少可定位的前提或引用超预算")
    if any(not isinstance(x,str) or x==key for x in parents+contrary):raise ValueError("派生记录不能给自己提供证据")
    def pointer(ref):return db.execute("SELECT * FROM host31_current_memory WHERE id=? AND owner IN (?, 'host')",(ref,owner)).fetchone()
    source_rows=[pointer(x) for x in parents]
    if any(x is None for x in source_rows+[pointer(y) for y in contrary]):raise ValueError("前提或反证不在已获准的宿主记忆范围")
    # A proposal can cite a past inference, but may not create a cycle by revising an ancestor.
    pending=list(parents);seen=set()
    while pending:
        name=pending.pop()
        if name==key:raise ValueError("记忆依赖形成自证环")
        if name in seen:continue
        seen.add(name)
        if len(seen)>256:raise ValueError("记忆依赖核对超出单步预算")
        node=pointer(name)
        if node:pending.extend(json.loads(node["derived_from"]))
    bound_owner=db.execute("SELECT owner FROM host31_memory WHERE id=? LIMIT 1",(key,)).fetchone()
    if bound_owner and bound_owner[0]!=owner:raise ValueError("记忆属于其他会话")
    prior=pointer(key)
    revision=proposal.get("revision",1)
    if prior and prior["owner"]!=owner:raise ValueError("记忆属于其他会话")
    if not prior and revision!=1:raise ValueError("找不到上一版记忆")
    if prior and revision not in (prior["revision"],prior["revision"]+1):raise ValueError("记忆版本不连续")
    if prior and revision>prior["revision"] and proposal.get("supersedes")!=prior["content_sha256"]:raise ValueError("旧记忆版本已改变")
    if prior and not set(json.loads(prior["contrary"])).issubset(contrary):raise ValueError("记忆修订必须保留已有反证")
    disposition=proposal.get("status","hypothesis")
    if disposition not in ("hypothesis","contested","withdrawn"):raise ValueError("槽件不能自行认定掌握或核验通过")
    if any(r["confidence"]=="withdrawn" for r in source_rows) and disposition=="hypothesis":raise ValueError("不可使用撤回来源新增假设")
    return insert(db,key=key,revision=revision,kind=kind,content=body,category="inference",source_ref=source_ref,
        evidence=[r["id"]+"@"+str(r["revision"])+":"+r["content_sha256"] for r in source_rows],confidence=disposition,
        context={"scope":owner,"review":"host-candidate"},contrary=contrary,derived=parents,
        families=set().union(*(set(json.loads(r["source_families"])) for r in source_rows)),owner=owner)

def command(db,text,session):
    key=text.strip().rstrip("。！？?!")
    if key not in ("记忆来源","记忆溯源") and not key.startswith("记忆来源 "):return None
    query=key.partition(" ")[2]
    rows=search(db,query=query,owner=session,limit=6)
    if not rows:return "宿主还没有符合条件的新记忆来源记录；原存档仍可用「旧记忆」查看。"
    return "\n".join(f"{r['id']} v{r['revision']} · {r['kind']} / {r['category']} · {r['source_ref']} · {r['confidence']}" for r in rows)


def _import_archive(db):
    db.execute("CREATE TABLE IF NOT EXISTS host31_memory_import(batch TEXT PRIMARY KEY,rows_seen INTEGER NOT NULL)")
    if db.execute("SELECT 1 FROM host31_memory_import WHERE batch='inner3/v1'").fetchone():return
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inner3_memory'").fetchone():return
    # Reuse the original timestamp and provenance. Historical entries are not new experiences.
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    q="""SELECT m.event,m.kind,m.item_key,m.body,m.source,m.status,m.at_ns,"""
    if "requests" in tables:q+="r.session FROM inner3_memory m LEFT JOIN requests r ON r.id=m.event"
    else:q+="NULL FROM inner3_memory m"
    batch=[]
    for event,kind,key,body,source,status,at,session in db.execute(q):
        if kind not in KINDS:continue
        owner=session or "host";identifier="archive:"+sha(packed([event,kind,key]))
        batch.append((identifier,1,kind,body,"replay",source or event,packed([event]),"archived:"+status,
                      packed({"origin":"inner3_memory","original_event":event,"original_key":key,"scope":owner}),
                      "[]","[]","[]",sha(body),at,owner))
    db.executemany("INSERT OR IGNORE INTO host31_memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch)
    db.execute("INSERT INTO host31_memory_import VALUES('inner3/v1',?)",(len(batch),))

def handle(db,intent,*,owner="main",source_ref="slot:C2"):
    """Execute a validated host intent; the adapter never receives the database connection."""
    if not isinstance(intent,dict):raise ValueError("记忆申请格式无效")
    action=intent.get("operation")
    if action=="read":
        f=intent.get("filter",{})
        if not isinstance(f,dict) or set(f)-{"query","kind","source_ref","category","context","since","limit"}:raise ValueError("不支持的记忆筛选项")
        if "context" in f and f["context"]!=owner:raise ValueError("当前请求无权读取另一会话")
        limit=f.get("limit",12)
        if type(limit) is not int or not 1<=limit<=32:raise ValueError("查询数量超预算")
        rows=search(db,query=f.get("query",""),owner=owner,limit=limit,category=f.get("category"),since_ns=f.get("since",0),
                    kind=f.get("kind"),source_ref=f.get("source_ref"))
        for row in rows:
            for key in ("context","evidence","contrary","derived_from","source_families"):row[key]=json.loads(row[key])
            row["basis_state"]=basis_state(db,row,owner)
        return {"records":rows}
    if action!="append" or not isinstance(intent.get("record"),dict):raise ValueError("记忆端口只接受读取与追加申请")
    v=intent["record"]
    if set(v)-{"id","revision","kind","body","source_type","source_ref","context","confidence","evidence","conflicts","derived","previous"}:
        raise ValueError("未声明的申请字段")
    if v.get("source_type","inference") not in ("inference","内部推断") or v.get("context",owner)!=owner:
        raise ValueError("槽不能伪装来源或变更当前会话")
    if v.get("source_ref",source_ref)!=source_ref:raise ValueError("来源引用须与本次槽请求绑定")
    revision=v.get("revision",1)
    proposal={"id":v.get("id"),"kind":v.get("kind"),"content":v.get("body"),"parents":v.get("derived") or v.get("evidence"),
              "contrary":v.get("conflicts",[]),"revision":revision,"supersedes":v.get("previous"),"status":v.get("confidence","hypothesis")}
    key=propose(db,proposal,owner=owner,source_ref=source_ref)
    return {"id":key,"revision":revision,"confidence":proposal["status"]}

def basis_state(db,record,owner):
    if record["confidence"]=="withdrawn":return "withdrawn"
    if record["category"]!="inference":return "historical" if record["category"]=="replay" else "source"
    pending=list(record["evidence"]);visited=set()
    while pending:
        ref=pending.pop()
        if ref in visited:continue
        visited.add(ref)
        if len(visited)>256:return "review_required"
        try:
            key,stamp=ref.rsplit("@",1);rev,h=stamp.split(":",1);rev=int(rev)
        except (ValueError,AttributeError):return "review_required"
        r=db.execute("SELECT revision,confidence,category,content_sha256,evidence FROM host31_current_memory WHERE id=? AND owner IN (?, 'host')",(key,owner)).fetchone()
        if not r or r[0]!=rev or r[1]=="withdrawn" or r[3]!=h:return "review_required"
        if r[2]=="inference":pending.extend(json.loads(r[4]))
    return "pinned"

