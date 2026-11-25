"""Durable desktop turns, independent CL proofs, and PCGM delivery receipts."""
from contextlib import contextmanager,closing
from functools import lru_cache
import json
import errno
import msvcrt
import re
import sqlite3
import time
from uuid import uuid4
import native as n
import slots31
import host_turn31 as hostturn
import life3

ID=re.compile(r"[a-z][a-z0-9_]{0,46}")
HELP="""「槽状态」「宿主状态」「最近回执」「旧记忆」「回忆 对象编号」可查看宿主记录。
可以直接问「你现在怎么样」「最近回执」「为什么」，或输入「词义 验证」「问题」。
用「证明 identity_restored(zaizai)」查来源。「编译」下一行可写 CL 源码，也可打开 .cl 文件。
「记住 名称 = 内容」和「回忆 名称」使用长期记忆。「咨询 片段」把这段话交给 DSHarness 提词义建议。用「采用 候选号」「撤回词条 候选号」管理会话词条。
「学习 片段」会比较 DSHarness 建议和本地证据，再再据此采用或保留候选。「比较方案」查看原生选项，「采纳最优方案」按当前约束裁定。
「开启词条自学」后，本会话里用「词义」查到的缺词会自动咨询顾问、求证并记录取舍。「关闭词条自学」随时关闭。
「生命状态」「课程」「学情」「问询」「内在状态」「迭代状态」读取本机工作记录；「暂停生命循环」「继续生命循环」「开启勿扰」控制后台与主动消息。
「采集 来源 | 观察号 原子」保存带出处的观察。用「回答 题号 版本 来源 原子」答复原问题。「原生几何状态」查正式场和最近操作；「本轮依据」「调度依据」查宿主轮次。完整原生操作可用「PCGM :命令」。
已接入联合槽时，用「运行账户」「委托状态」「执行报告」查看操作方、待办和回执。「暂停委托」和「恢复委托」可控制自动执行。"""
FOLLOW={"为什么","然后呢","依据呢","再说明一下","刚才说的那项，再说明一下","为什么这么说","根据是什么"}
def store():
    db=sqlite3.connect(n.DB.as_uri()+"?mode=rw",uri=True,timeout=8)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA synchronous=FULL")
    return db
def setup():
    with closing(store()) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,session TEXT NOT NULL,question TEXT NOT NULL,
            digest TEXT NOT NULL,source TEXT NOT NULL,phase TEXT NOT NULL,started INTEGER NOT NULL,
            before_head TEXT,plan TEXT,native_receipt TEXT,answer TEXT,seq INTEGER UNIQUE,delivered INTEGER,error TEXT);
        CREATE TABLE IF NOT EXISTS memory(name TEXT PRIMARY KEY,body TEXT NOT NULL,request TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,source TEXT NOT NULL,atom TEXT NOT NULL,
            captured_ns INTEGER NOT NULL,request TEXT NOT NULL,receipt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS senses(id TEXT PRIMARY KEY,session TEXT NOT NULL,term TEXT NOT NULL,word TEXT NOT NULL,
            scope TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,definition TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS options(name TEXT PRIMARY KEY,value TEXT);
        CREATE INDEX IF NOT EXISTS receipts_by_session ON requests(session,seq);
        """)
        with db:
            slots31.setup(db)
            hostturn.setup(db)
        life3.setup(db)
def row(db,request):
    return db.execute("""SELECT r.*,h.receipt_id AS host_receipt,h.frame_kind FROM requests r
                      LEFT JOIN host31_commits h ON h.request_id=r.id WHERE r.id=?""",(request,)).fetchone()
@contextmanager
def _held_writer_byte(stream, timeout=10.0):
    """Wait for the same Windows byte-range lock; a short holder should not cost a full CRT second."""
    deadline=time.monotonic()+timeout
    while True:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            break
        except OSError as error:
            remaining=deadline-time.monotonic()
            if (error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK)
                and getattr(error,"winerror",None) not in (32,33)) or remaining<=0:
                raise
            time.sleep(min(.01,remaining))
    try:
        yield
    finally:
        stream.seek(0)
        msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

@contextmanager
def maintenance_lock():
    with (n.ROOT/"writer.guard").open("a+b") as stream,_held_writer_byte(stream):
        yield
@contextmanager
def writer():
    with maintenance_lock(),(n.STATE/"desktop-writer.lock").open("a+b") as stream,_held_writer_byte(stream):
        yield
def last(db,session):
    return db.execute("SELECT * FROM requests WHERE session=? AND phase='committed' ORDER BY seq DESC LIMIT 1",(session,)).fetchone()
def history(session):
    with closing(store()) as db:
        return db.execute("""SELECT t.seq,t.request,t.response,r.id FROM turns t LEFT JOIN requests r ON t.seq=r.seq
        WHERE r.session=? OR (r.id IS NULL AND ?='main') ORDER BY t.seq""",(session,session)).fetchall()
def deliver(request):
    if request:
        with closing(store()) as db,db:
            db.execute("UPDATE requests SET delivered=COALESCE(delivered,?) WHERE id=? AND phase='committed'",(time.time_ns(),request))
def plan(answer,**kw):return dict(answer=answer,**kw)
def change(db,r,p):
    c=p.get("change")
    if not c:return
    if c[0]=="option":
        db.execute("INSERT OR REPLACE INTO options(name,value) VALUES(?,?)",c[1:])
    if c[0]=="remember":
        db.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?)",(c[1],c[2],r["id"]))
    if c[0]=="samples":
        _,source,items,when,receipt=c
        db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?)",[(i,source,f,when,r["id"],receipt) for i,f in items])
    if c[0]=="candidate":
        _,cid,term,a,*resolution=c
        db.execute("INSERT INTO senses VALUES(?,?,?,?,?,?,?,1,?)",(cid,r["session"],term,a["canonical"],a["domain"],a["source"],resolution[0] if resolution else "candidate",a["explanation"]))
    if c[0]=="sense_status":
        db.execute("UPDATE senses SET status=?,version=version+1 WHERE id=? AND session=?",(c[2],c[1],r["session"]))

@lru_cache(maxsize=1)
def host_checkpoint():
    view=n.legacy_memory.overview()
    return dict(identity=n.IDENTITY,generation=view["generation"],tick=view["tick"],receipt=n.ANCHOR["receipt"])

def monitor_state(db=None):
    if db is None:
        with closing(store()) as conn:return hostturn.summarize(conn)
    return hostturn.summarize(db)

def routed_plan(db,r,bindings,legacy):
    local=hostturn.operations(db,r,legacy,bindings)
    if local is not None:return local
    result=life3.command(db,r["question"].strip(),r["session"],r["id"])
    if result is not None:return hostturn.host_data(result,"本地生命账本",audit_key=r["id"])
    if any(bindings[k]["state"]!="ready" for k in ("L","C")):
        return hostturn.unavailable(bindings)
    if (bindings["L"]["id"],bindings["C"]["id"])==("joint25-cl","joint25-pcgm"):
        import joint25_runtime
        lexical=joint25_runtime.lexical_plan(db,r["question"],r["session"],r["id"])
        if lexical is not None:return lexical
        if not joint25_runtime.compat_turn(db,r["question"],r["session"]):
            return hostturn.generic_dialogue(db,r,bindings)
    if hostturn.is_legacy(bindings):
        import legacy_dialogue31 as adapter
        result=adapter.interpret(db,r,legacy)
        result["frame_kind"]="reply"
        return result
    return hostturn.generic_dialogue(db,r,bindings)

def route(db,r,*,prepared=False):
    stored=db.execute("SELECT bindings FROM host31_request_routes WHERE id=?",(r["id"],)).fetchone()
    if stored:return json.loads(stored[0])
    bindings=slots31.snapshot(db)
    # A prepared pre-upgrade request belongs to its historical PCGM instance.
    if prepared and not hostturn.is_legacy(bindings):
        raise PendingHook("此请求由旧件准备，等待原适配器恢复后按原请求号核对。")
    with db:db.execute("INSERT INTO host31_request_routes VALUES(?,?,?)",(r["id"],n.canonical(bindings),time.time_ns()))
    return bindings

class PendingHook(RuntimeError):pass
class CapacityConfirmed(ValueError):pass

def commit_hook(db,r,p,bindings,action,checkpoint):
    plan_pin=n.sha(r["plan"].encode())
    route_pin=n.sha(n.canonical(bindings).encode())
    original=db.execute("SELECT * FROM host31_commits WHERE request_id=?",(r["id"],)).fetchone()
    if original:
        if (original["plan_sha256"],original["route_sha256"],original["content_sha256"])!=(plan_pin,route_pin,r["digest"]):
            raise ValueError("已持久化的回执与请求版本不一致")
        return original["slot_receipt"],original["receipt_id"]
    frame_kind=p.get("frame_kind","reply")
    raw=None;sources=[]
    if frame_kind=="reply":
        payload={"session":r["session"],"request":r["id"],"action":action}
        with db:
            prepared=slots31.dispatch(db,"C8",dict(payload,phase="prepare"),pin=bindings["C"],input_version=plan_pin)
            if prepared["output"].get("refused"):
                raise PendingHook("槽件拒绝准备，本次未调用提交："+prepared["output"]["reason"])
            result=slots31.dispatch(db,"C8",dict(payload,phase="commit"),pin=bindings["C"],input_version=plan_pin)
            output=result["output"];sources=result["sources"]
            if output.get("refused") and bindings["C"]["id"]=="joint25-pcgm" and output.get("confirmed_no_write"):
                raise CapacityConfirmed(output["reason"])
            if output.get("refused"):
                raise PendingHook("槽件拒绝提交，请按原请求号核对："+output["reason"])
            if bindings["C"]["id"] in {"legacy-pcgm","joint25-pcgm"}:
                raw=output["raw"]
                lines=raw.splitlines()
                if not lines or lines[0] not in {f"chat_{k} {r['session']} {r['id']}" for k in ("committed","replayed")}:
                    raise PendingHook("旧认知槽回执未能绑定本次请求，等待核对。")
                if action.startswith("record ") and lines[1:]!=["recorded "+action.split()[1]]:
                    raise PendingHook("旧认知槽回执摘要不符，等待核对。")
            else:
                raw=n.canonical(output)
    if checkpoint:checkpoint("slot")
    pin=n.sha(n.canonical([n.IDENTITY,r["id"],r["session"],r["digest"],plan_pin,route_pin,frame_kind]).encode())
    with db:
        db.execute("INSERT INTO host31_commits VALUES(?,?,?,?,?,?,?,?,?)",
            (r["id"],pin,frame_kind,plan_pin,route_pin,r["digest"],raw,n.canonical(sources),time.time_ns()))
    return raw,pin

def finish(db,r,checkpoint=None):
    p=json.loads(r["plan"])
    bindings=route(db,r,prepared=True)
    action=p.get("action") or "record h"+n.sha(r["plan"].encode())
    try:raw,token=commit_hook(db,r,p,bindings,action,checkpoint)
    except CapacityConfirmed as exc:
        p=hostturn.unavailable(bindings,"本次原生会话或回合数达到已登记上限，已核对没有原生写入："+str(exc))
        with db:db.execute("UPDATE requests SET plan=? WHERE id=?",(n.canonical(p),r["id"]))
        r=row(db,r["id"]);raw,token=commit_hook(db,r,p,bindings,action,checkpoint)
    except PendingHook as ex:
        with db:db.execute("UPDATE requests SET error=? WHERE id=?",(str(ex),r["id"]))
        raise
    except slots31.SlotUnavailable as ex:
        message="已准备的请求等待原槽件核对提交回执："+str(ex)
        with db:
            slots31.mark_fault(db,ex,bindings["C"])
            db.execute("UPDATE requests SET error=? WHERE id=?",(message,r["id"]))
        raise PendingHook(message) from ex
    if checkpoint:checkpoint("native")
    answer=p["answer"]
    if p.get("render")=="follow":
        receipt="\n".join((raw or "").splitlines()[1:])
        answer="这次会话还没有焦点。你想了解状态、回执还是某个 CL 目标？" if "clarify no_focus" in receipt else "你刚才关注的是这项结论。原生证明如下。\n"+receipt
    with db:
        change(db,r,p)
        life3.dialogue_event(db,r,p,answer)
        build="3.1 宿主 / "+" / ".join(str(bindings[k]["id"])+"@"+str(bindings[k]["version"]) for k in ("L","C"))
        cur=db.execute("INSERT INTO turns(identity,request,response,build) VALUES(?,?,?,?)",(n.IDENTITY,r["question"],answer,build))
        db.execute("UPDATE requests SET phase='committed',native_receipt=?,answer=?,seq=?,error=NULL WHERE id=?",(raw,answer,cur.lastrowid,r["id"]))
    return dict(row(db,r["id"]))

def process(question,session="main",request=None,source="desktop",checkpoint=None):
    request=request or "t"+uuid4().hex
    if not ID.fullmatch(session) or not ID.fullmatch(request):raise ValueError("无效的会话或请求号")
    if not question.strip() or len(question)>128000:raise ValueError("消息为空或超长")
    from life3_worker import latch
    with latch("foreground"),writer(),n.request_context(),closing(store()) as db:
        old=row(db,request)
        if old and (old["question"],old["session"])!=(question,session):raise ValueError("相同请求号携带不同内容")
        if old and old["phase"]=="committed":return dict(old)
        if old and old["phase"] in {"unknown","running","failed"}:raise RuntimeError(old["error"] or "该请求结果待核对，未重做")
        if not old:
            bindings=slots31.snapshot(db)
            with db:
                db.execute("INSERT INTO requests(id,session,question,digest,source,phase,started) VALUES(?,?,?,?,?,'planned',?)",
                      (request,session,question,n.sha(question.encode()),source,time.time_ns()))
                db.execute("INSERT INTO host31_request_routes VALUES(?,?,?)",(request,n.canonical(bindings),time.time_ns()))
        r=row(db,request)
        if r["phase"]=="planned":
            if checkpoint:checkpoint("before")
            bindings=route(db,r)
            head=None
            current=slots31.snapshot(db) if old else bindings
            changed=not hostturn.same_binding(current,bindings)
            if not changed and hostturn.is_legacy(bindings):
                import legacy_dialogue31 as adapter
                head=adapter.head_or_none()
                if head is not None:
                    with db:db.execute("UPDATE requests SET phase='running',before_head=? WHERE id=?",(head,request))
            try:
                if changed:
                    p=hostturn.unavailable(current,"此请求登记后槽件绑定已经变更；原请求未调用新槽件")
                elif hostturn.is_legacy(bindings) and head is None:
                    fault=slots31.SlotUnavailable("C","state_unavailable","旧认知槽私有状态文件不可用")
                    with db:slots31.mark_fault(db,fault,bindings["C"])
                    p=routed_plan(db,r,slots31.snapshot(db),host_checkpoint())
                else:
                    p=routed_plan(db,r,bindings,host_checkpoint())
            except Exception as ex:
                db.rollback()
                unchanged=head is None or adapter.head_or_none()==head
                if unchanged and isinstance(ex,(slots31.SlotUnavailable,n.LegacyUnavailable)):
                    fault=ex if isinstance(ex,slots31.SlotUnavailable) else slots31.SlotUnavailable(ex.slot,"adapter_failure",str(ex))
                    with db:slots31.mark_fault(db,fault,bindings.get(fault.slot))
                    degraded=slots31.snapshot(db)
                    key=r["question"].strip().rstrip("。！？?! ").strip()
                    p=(hostturn.operations(db,r,host_checkpoint(),degraded)
                       if key in {"旧存档","旧记忆","原来的记忆","状态","最近回执","查看最近回执","回执"} or key.startswith("回忆 ") else None)
                    if p is None:p=hostturn.unavailable(degraded,str(fault))
                else:
                    known=isinstance(ex,(ValueError,FileNotFoundError))
                    phase="failed" if known and unchanged else "unknown"
                    with db:
                        db.execute("UPDATE requests SET phase=?,error=? WHERE id=?",(phase,str(ex),request))
                        life3.audit(db,request,dict(kind="dialogue_error",topic="请求失败",summary=str(ex)[:300],
                            status=phase,failed=True,progress=False,source=source),"dialogue",question,session)
                    raise
            with db:db.execute("UPDATE requests SET plan=?,phase='prepared' WHERE id=?",(n.canonical(p),request))
        result=finish(db,row(db,request),checkpoint)
        if question.strip()=="继续生命循环":
            from life3_worker import start
            start()
        if checkpoint:checkpoint("after")
        return result

def recover():
    with writer(),closing(store()) as db:
        with db:db.execute("UPDATE requests SET phase='unknown',error='进程在执行中退出，需要核对原回执' WHERE phase='running'")
        for r in db.execute("SELECT * FROM requests WHERE phase='prepared' ORDER BY started").fetchall():
            try:finish(db,r)
            except PendingHook:continue
        planned=db.execute("SELECT question,session,id,source FROM requests WHERE phase='planned' ORDER BY started").fetchall()
    for pending in planned:
        try:process(*pending)
        except PendingHook:continue
        except Exception:
            with closing(store()) as db:
                if row(db,pending["id"])["phase"] not in {"failed","unknown"}:raise

