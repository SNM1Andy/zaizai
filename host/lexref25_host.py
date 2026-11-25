"""Owner-delegated native word-reference operations; a fresh head and exact request receipts guard each write."""
from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time

import native_lexref25 as native

ROOT=Path(__file__).resolve().parents[1]
OPS={"设置原生词表":"select","使用原生词表":"select","原生引用义项":"bind","撤回原生词义":"retire",
     "读取原生词义":"read","原生词义凭据":"receipt","原生引用回执":"reconcile","原生词表状态":"status"}

def encoded(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"))
def pin(value):return native.sha(encoded(value).encode())
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS native_lexref25_requests(
      id TEXT PRIMARY KEY,session TEXT NOT NULL,request_text TEXT NOT NULL,actor TEXT NOT NULL,
      plan TEXT NOT NULL,phase TEXT NOT NULL,verification TEXT,created REAL NOT NULL,committed REAL)""")

def clone(j,where):
    folder=where/"state";folder.mkdir()
    target=folder/"individual.pcgm";shutil.copy2(j.state,target)
    for suffix in (".history",".episodes"):
        src=j.state.with_name(j.state.name+suffix)
        if src.is_dir():shutil.copytree(src,target.with_name(target.name+suffix))
    shutil.copytree(j.state.parent/"modules",folder/"modules")
    return native.Journal(where,j.bins,j.actor)

def execute(j,action,head):
    op=action["op"]
    if op=="install":return j.install(head)
    if op=="select":return j.select(action["release"],head)
    if op=="bind":return j.bind_pins(action["name"],action["sid"],action["sense_sha256"],action["release"],head)
    if op=="retire":return j.retire(action["name"],head)
    raise ValueError("不支持的词义操作")

def plan(j,actions):
    original=j.snap()
    with tempfile.TemporaryDirectory(prefix="native-lexref-preflight-") as tmp:
        simulated=clone(j,Path(tmp));steps=[]
        for action in actions:
            before=simulated.snap()
            result=execute(simulated,action,before["head"])
            after=simulated.snap()
            batch=result.get("receipt",result)
            if not isinstance(batch,dict):batch={}
            steps.append({"action":action,"before":before["head"],"after":after["head"],
                          "batch":batch.get("batch"),"request_pin":batch.get("request_pin"),"event":batch.get("event")})
    return {"initial":original["head"],"final":steps[-1]["after"],"actions":steps}

def recorded(j,step):
    if step["before"]==step["after"]:return True
    if step["action"]["op"]=="install":
        fresh=j.snap()
        if "# module lexref25\n" not in fresh["source"]:return False
        j.verify_source(fresh);return True
    if not step["batch"] or not step["request_pin"]:return False
    actual=j.read("observation_batch "+step["batch"]+" "+step["request_pin"])
    if actual.get("status")=="not_recorded":return False
    native.need(actual.get("event")==step["event"] and actual.get("basis_sha256")==step["before"],"native batch receipt does not match the issued operation")
    return True

def reconcile(db,j,ident,session):
    row=db.execute("SELECT * FROM native_lexref25_requests WHERE id=? AND session=?",(ident,session)).fetchone()
    native.need(row and row["actor"]==j.actor,"这个会话没有此项词义运维原单")
    if row["phase"]!="prepared":return json.loads(row["verification"])
    action_plan=json.loads(row["plan"]);head=j.snap()["head"]
    steps=action_plan["actions"];positions=[i for i,v in enumerate(steps) if v["before"]==head]
    if positions and head!=action_plan["final"]:
        for step in steps[positions[0]:]:
            native.need(j.snap()["head"]==step["before"],"原生状态已改变，保留原单等待对账")
            execute(j,step["action"],step["before"])
            native.need(j.snap()["head"]==step["after"],"原生提交与独立预演不符，保留原单")
    outcomes=[recorded(j,v) for v in steps]
    finished=all(outcomes)
    phase="committed" if finished else ("partial" if any(outcomes) else "not_recorded")
    verification={"request":ident,"phase":phase,"step_receipts":outcomes,"initial_head":action_plan["initial"],"expected_head":action_plan["final"],
                  "observed_head":j.snap()["head"],"batches":[v["batch"] for v in steps if v["batch"]],
                  "operation":steps[-1]["action"],"verified":True}
    with db:db.execute("UPDATE native_lexref25_requests SET phase=?,verification=?,committed=? WHERE id=?",
                       (phase,encoded(verification),time.time(),ident))
    return verification

def command(db,text,session,rid,*,root=None,bin_dir=None,catalog_path=None):
    """Called in the host writer before unrelated SQLite work. None means another host command owns this input."""
    words=text.strip().rstrip("。！？?! ").split()
    if not words or words[0] not in OPS:return None
    import slots31,native as host,release25_lexicon as lex
    base=Path(root or ROOT).resolve(strict=True)
    bound=slots31.snapshot(db)["C"]
    if bound["id"]!="joint25-pcgm" or bound["state"]!="ready":return "当前没有可用的联合认知槽，未向原生词义账本提交操作。"
    native.need(not db.in_transaction,"词义运维需要处于宿主写锁内的独立事务边界")
    setup(db);j=native.Journal(base,bin_dir or base/"releases/joint25/bin",host.IDENTITY)
    catalog=Path(catalog_path or base/"learning_materials/release25-lexicon/lexicon-r002.sqlite")
    op=OPS[words[0]];args=words[1:];snap=j.snap();installed="# module lexref25\n" in snap["source"]
    if op=="status":
        release=j.selected(j.records(snap)) if installed else None
        return "原生词义引用模块："+("已登记" if installed else "待首次授权操作登记")+"。\n当前选用的词表发布："+str(release or "暂无")+"。"
    if op=="reconcile":
        native.need(len(args)==1,"用法：原生引用回执 原请求号")
        return "原生词义原单："+encoded(reconcile(db,j,args[0],session))
    if op in ("read","receipt"):
        native.need(len(args)==1,"需要一个精确的原生词义记录号")
        if not installed:return "尚无原生词义引用记录。"
        if op=="receipt":return "原生固定地址与证明："+encoded(j.receipt(args[0]))
        result=j.read_binding(args[0],catalog)
        val=result["content"] or {}
        return (f"原生记录 {args[0]} · {result['sense_id']} · "+("墓碑" if result["tombstone"] else "保留")+"\n词表发布 "+result["release_sha256"]+
                "\n义项原文摘要 "+result["sense_digest"]+"\n"+("正文按来源审查条件保留。" if result["content_withheld"] else
                 str(val.get("definition",""))+"\n签名 "+str(val.get("cl",""))+"\n例句 "+str((val.get("examples") or [""])[0])))
    existing=db.execute("SELECT session,request_text FROM native_lexref25_requests WHERE id=?",(rid,)).fetchone()
    if existing:
        native.need(tuple(existing)==(session,text),"相同请求号携带不同会话或词义操作")
        result=reconcile(db,j,rid,session)
        return "该词义操作已按原单核对："+encoded(result)
    native.need(not db.execute("SELECT 1 FROM native_lexref25_requests WHERE phase='prepared' LIMIT 1").fetchone(),"已有待对账词义操作，请先读取原单")
    actions=[] if installed else [{"op":"install"}]
    chosen=j.selected(j.records(snap)) if installed else None
    if op=="select":
        native.need(len(args)==1,"用法：设置原生词表 v1 或 v2")
        version={"v1":native.BASE,"v2":native.CURRENT}.get(args[0],args[0])
        native.need(version in j.releases,"未知发行版本")
        actions.append({"op":"select","release":version})
    elif op=="retire":
        native.need(installed and len(args)==1,"需要一个已存在的原生词义记录号")
        actions.append({"op":"retire","name":args[0]})
    else:
        native.need(len(args) in (1,2),"用法：原生引用义项 [记录号] LX-义项编号")
        name=("r"+pin([rid,session])[:12]) if len(args)==1 else args[0];sid=args[-1];native.record_key(name)
        release=chosen or native.CURRENT
        verified=lex.verify_index(catalog);native.need(verified["index_sha256"]==native.INDEX,"来源词库摘要不一致")
        info=native.lookup(catalog,sid,release)
        allowed=lex.resolve(sid,info["digest"],release_sha256=release,db=db,catalog_path=catalog)
        native.need(allowed["state"]=="importable" and not allowed["content_withheld"] and info["side"]=="importable","当前词库治理没有放行该候选引用")
        if not chosen:actions.append({"op":"select","release":release})
        actions.append({"op":"bind","name":name,"sid":sid,"sense_sha256":info["digest"],"release":release})
    prepared=plan(j,actions)
    with db:db.execute("INSERT INTO native_lexref25_requests VALUES(?,?,?,?,?,'prepared',NULL,?,NULL)",(rid,session,text,j.actor,encoded(prepared),time.time()))
    result=reconcile(db,j,rid,session)
    action=result["operation"]
    return "原生词义操作 "+op+" · "+result["phase"]+"。"+("记录号 "+action["name"]+"。" if "name" in action else "")+"\n请求 "+rid+"，回执 "+pin(result)+"。"
