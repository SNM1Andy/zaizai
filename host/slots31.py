"""Versioned host-side L/C ports. An unbound slot has no implementation."""
from contextlib import contextmanager
from contextvars import ContextVar
import base64
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
ABI = "zaizai.slots/1"
PORTS = {"L": tuple("L"+str(i) for i in range(1,7)), "C":tuple("C"+str(i) for i in range(1,10))}
VALUE_DOMAIN = {"support":"POSITIVE","counter":"NEGATIVE","insufficient":"UNKNOWN","conflict":"CONFLICT"}
ID = re.compile(r"[a-z][a-z0-9-]{0,62}")
SOURCE_MAX = 2*1024*1024
BUDGET_MS = {"L":4000,"C":4000}
_quota=ContextVar("slot31_remaining_budget",default=None)
_restoring=ContextVar("slot31_inside_restore",default=False)
@contextmanager
def quota_context(remaining_ms):
    token=_quota.set(remaining_ms)
    try:yield
    finally:_quota.reset(token)
BUILTIN = {
 "legacy-cl":{"slot":"L","id":"legacy-cl","name":"CL 语言过渡适配器","version":"0.157","interface_version":ABI,
              "capabilities":list(PORTS["L"]),"value_domain":VALUE_DOMAIN,"state_format":"immutable-CL-package/1",
              "formats":[".cl"],"provider_type":"legacy","artifacts":{"bin/cl.exe":"905049c095ec5caf0d1573209dac51213fb49762018bcb12ce6b7e404758e4cb",
              "lexicon/lexicon_core.clpkg":"0109b3b1ebdc047765d5bfa0b8df815e961c509869394b0d1650d91b33c9eaaf",
              "lexicon/lexicon_core.cl":"deca13b92a44d0cb00022be2c41a6bb3579e213f2480e3c6ac8183b82bb144a2"},
              "limits":"L1 解析原生目标或已登记词义；L4 转述带依据的既成结论。"},
 "legacy-pcgm":{"slot":"C","id":"legacy-pcgm","name":"PCGM 认知过渡适配器","version":"0.159","interface_version":ABI,
              "capabilities":list(PORTS["C"]),"value_domain":{},"state_format":"opaque-pcgm-managed/0.159",
              "formats":[],"provider_type":"legacy","artifacts":{"bin/pcgm-alpha.exe":"8c189990c44d6be73d975d20964d18501d54a9ebd4c7df0817aba622c1099564","bin/pcgm-beta.exe":"a2a4fa40661dc930335b8668cecfedebc8e9860fe8053cd96b74858e7e8f7a54"},
              "limits":"C3 重用已登记的旧版工作通道基数；C5 调度、C6 缺测和 C8 原生请求号采用兼容实现。"}}
_joint_registry=ROOT/"host/joint25-providers.json"
if _joint_registry.is_file():
    BUILTIN.update(json.loads(_joint_registry.read_bytes()))
def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def hash_json(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()
def empty(role):
    return {"slot":role,"id":"empty","name":"空槽","version":None,"revision":0,"interface_version":ABI,
        "capabilities":[],"formats":[],"value_domain":{},"state_format":None,"artifacts":{},"selftest":None,
        "state":"empty","reason":"尚未绑定槽件","provider_type":"empty","manifest_sha256":None}

class SlotUnavailable(RuntimeError):
    def __init__(self,slot,code,detail):
        self.slot=slot;self.code=code;self.detail=str(detail)[:700]
        super().__init__(f"{slot} 槽不可用 [{code}] {self.detail}")

def setup(db):
    for sql in (
        "CREATE TABLE IF NOT EXISTS slot31_registry(adapter_id TEXT PRIMARY KEY,slot TEXT NOT NULL,manifest TEXT NOT NULL,pin TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS slot31_bindings(slot TEXT PRIMARY KEY,adapter_id TEXT NOT NULL,revision INTEGER NOT NULL,health TEXT NOT NULL,reason TEXT NOT NULL,selftest TEXT)",
        "CREATE TABLE IF NOT EXISTS slot31_changes(seq INTEGER PRIMARY KEY,slot TEXT,prior TEXT,current TEXT,revision INTEGER,stamp REAL,manifest_pin TEXT)",
        "CREATE TABLE IF NOT EXISTS slot31_port_receipts(slot TEXT,adapter TEXT,port TEXT,event_id TEXT,input_pin TEXT NOT NULL,output TEXT NOT NULL,stamp REAL NOT NULL,PRIMARY KEY(slot,adapter,port,event_id))",
        "CREATE TABLE IF NOT EXISTS slot31_private_state(adapter_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,state_format TEXT NOT NULL,state_sha256 TEXT NOT NULL,opaque BLOB NOT NULL,source_pin TEXT NOT NULL,stamp REAL NOT NULL,PRIMARY KEY(adapter_id,manifest_sha256))",
        "CREATE TABLE IF NOT EXISTS slot31_private_restore_due(adapter_id TEXT PRIMARY KEY,manifest_pin TEXT NOT NULL,state_sha256 TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS slot31_detach_notes(adapter_id TEXT PRIMARY KEY,manifest_pin TEXT NOT NULL,reason TEXT NOT NULL,stamp REAL NOT NULL)",
    ):db.execute(sql)
    for m in BUILTIN.values():
        v=canonical(m)
        db.execute("INSERT OR IGNORE INTO slot31_registry VALUES(?,?,?,?)",(m["id"],m["slot"],v,hash_json(m)))
    for s in PORTS:
        db.execute("INSERT OR IGNORE INTO slot31_bindings VALUES(?,'empty',0,'empty','尚未绑定槽件',NULL)",(s,))

def checkpoint(db):
    result={s:empty(s) for s in PORTS}
    try:
        rows=db.execute("""SELECT b.slot,b.adapter_id,b.revision,b.health,b.reason,b.selftest,r.manifest,r.pin
            FROM slot31_bindings b LEFT JOIN slot31_registry r ON b.adapter_id=r.adapter_id""").fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):raise
        return result
    for role,aid,rev,state,reason,probe,encoded,pin in rows:
        if role not in PORTS:raise ValueError("槽表含未知角色")
        m=empty(role) if aid=="empty" else json.loads(encoded or "{}")
        if aid!="empty" and (hash_json(m)!=pin or m.get("id")!=aid or m.get("slot")!=role):
            raise ValueError("槽件清单摘要或角色不匹配")
        result[role]=dict(m,revision=rev,state=state,reason=reason,selftest=json.loads(probe) if probe else None,manifest_sha256=pin)
    return result

@lru_cache(maxsize=128)
def _hash(path,size,mtime,ctime):
    with open(path,"rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def _checkfiles(m):
    for rel,pin in m["artifacts"].items():
        path=ROOT/rel
        try:
            st=path.stat()
            if _hash(str(path),st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=pin:return "产物校验失败 "+rel
        except OSError:return "缺少已登记的本地产物 "+rel
    if m["id"] in {"legacy-pcgm","joint25-pcgm"} and not (ROOT/"state/individual.pcgm").is_file():return "旧槽件的私有存档缺失"
    return ""
def snapshot(db):
    result=checkpoint(db)
    for m in result.values():
        if m["state"]=="ready":
            issue=_checkfiles(m)
            if issue:m.update(state="unavailable",reason=issue)
    return result

def pin(slot):return {k:slot[k] for k in ("id","revision","version","manifest_sha256")}
def check_pin(slot,p):
    if p is not None and any(p.get(k)!=slot.get(k) for k in ("id","revision","version","manifest_sha256") if k in p):
        raise SlotUnavailable(slot["slot"],"binding_changed","请求固定的槽版本当前未绑定")
def mark_fault(db,exc,pinned=None):
    if exc.code in ("empty","binding_changed","unsupported","rejected"):return
    q="UPDATE slot31_bindings SET health='unavailable',reason=? WHERE slot=? AND adapter_id!='empty'"
    vals=[exc.detail,exc.slot]
    if pinned is not None:
        q+=" AND adapter_id=? AND revision=?";vals.extend([pinned["id"],pinned["revision"]])
    db.execute(q,vals)

def _validate(port,out,m):
    if not isinstance(out,dict):raise ValueError("输出必须是对象")
    if out.get("refused") is True:
        if not isinstance(out.get("reason"),str) or not out["reason"]:raise ValueError("拒绝缺少原因")
        return
    required={
       "L1":("parsed",),"L2":("results","proof_ref"),"L3":("meanings",),"L4":("text",),
       "L5":("matches","proof_ref"),"L6":("passed","capabilities"),"C1":("accepted","id"),
       "C2":("operation",),"C3":("candidates",),"C4":("questions",),"C5":("mode","budget_ms","wake"),
       "C6":("integrity","unresolved_weight","prediction_error","information_gain"),"C7":("round_id","entries"),
       "C8":("phase","request"),"C9":("operation","state_format","state_sha256")}
    if any(k not in out for k in required[port]):raise ValueError(port+" 返回字段不完整")
    if port in {"L2","L5"} and (not isinstance(out["proof_ref"],str) or not out["proof_ref"]):raise ValueError("缺少证明引用")
    if port=="L2":
        if not isinstance(out["results"],list) or any(not isinstance(x,dict) or x.get("status") not in m["value_domain"].values() or not isinstance(x.get("goal"),dict) for x in out["results"]):
            raise ValueError("语言槽输出了未声明状态或不完整目标")
    if port=="L4" and (not isinstance(out["text"],str) or not out["text"]):raise ValueError("表达为空")
    if port=="C3" and (not isinstance(out["candidates"],list) or len(out["candidates"])>64 or
        any(not isinstance(x,dict) or not isinstance(x.get("id"),str) or not isinstance(x.get("proof_ref"),str) or
        not isinstance(x.get("base_score"),(int,float)) or not math.isfinite(x["base_score"]) or
        not isinstance(x.get("cost"),(float,int)) or not math.isfinite(x["cost"]) or x["cost"]<0 for x in out["candidates"])):
        raise ValueError("候选缺少合法性证明、成本或有限分数")
    if port=="C5" and (out["mode"] not in {"ready","wait","narrow","shelve","hypothesis"} or not isinstance(out["budget_ms"],(int,float)) or not math.isfinite(out["budget_ms"]) or out["budget_ms"]<0):raise ValueError("无效预算状态")
    if port=="C8" and out["phase"] not in {"prepared","committed","replayed"}:raise ValueError("无效提交状态")
    if port=="C9" and out["state_format"]!=m["state_format"]:raise ValueError("私有状态格式不匹配")
    if port in {"L3","C4","C7"}:
        name={"L3":"meanings","C4":"questions","C7":"entries"}[port]
        if not isinstance(out[name],list):raise ValueError("返回列表格式错误")
    if port=="L1" and not isinstance(out["parsed"],dict):raise ValueError("结构化解析格式错误")
    if port=="L6" and (out["passed"] is not True or sorted(out["capabilities"])!=sorted(m["capabilities"])):raise ValueError("声明能力与自检不一致")
    if port=="C1" and out["accepted"] is not True:raise ValueError("观察未确认")
    if port=="C6" and any(out[k] is not None and (not isinstance(out[k],(float,int)) or not math.isfinite(out[k])) for k in required[port]):
        raise ValueError("评价输入须为有限数值或缺测")

def _dbreceipt(db,m,port,event,pin_value):
    if not isinstance(event,str) or not 0<len(event)<=160:raise ValueError("需要有界事件编号")
    old=db.execute("SELECT input_pin,output FROM slot31_port_receipts WHERE slot=? AND adapter=? AND port=? AND event_id=?",
                   (m["slot"],m["id"],port,event)).fetchone()
    if old and old[0]!=pin_value:raise ValueError("原回执绑定了不同输入")
    return json.loads(old[1]) if old else None
def _store_receipt(db,m,port,event,iv,out):
    db.execute("INSERT OR IGNORE INTO slot31_port_receipts VALUES(?,?,?,?,?,?,?)",
            (m["slot"],m["id"],port,event,iv,canonical(out),time.time()))

def dispatch(db,port,payload,*,input_version=None,timeout_ms=None,pin=None,owner="main"):
    quota=_quota.get()
    if quota is not None:
        left=int(quota())
        if left<=0:raise TimeoutError("当前宿主工作步已收束")
        timeout_ms=min(left,timeout_ms) if timeout_ms is not None else left
    if not isinstance(port,str) or port not in sum((list(v) for v in PORTS.values()),[]):raise ValueError("未知槽端口")
    if not isinstance(payload,dict) or len(canonical(payload).encode())>SOURCE_MAX:raise ValueError("槽输入无效或过大")
    role=port[0];m=snapshot(db)[role]
    # Existing prepared work can reconcile the exact same implementation across a temporary outage.
    reconciling=(port=="C8" and pin and pin.get("manifest_sha256") and
                 all(pin.get(k)==m.get(k) for k in ("id","version","manifest_sha256")))
    if not reconciling:check_pin(m,pin)
    if m["state"]!="ready":raise SlotUnavailable(role,m["state"],m["reason"])
    if role=="C" and m["provider_type"]=="external" and not _restoring.get():
        due=db.execute("SELECT state_sha256 FROM slot31_private_restore_due WHERE adapter_id=?",(m["id"],)).fetchone()
        if due:
            if port=="C9" and payload.get("operation")=="restore" and payload.get("state_sha256")!=due[0]:
                raise SlotUnavailable(role,"restore_required","先恢复检查点登记的私有状态")
            resume_private(db)
    if port not in m["capabilities"]:raise SlotUnavailable(role,"unsupported",f"{m['id']} 未提供 {port}")
    if port=="L5" and "receipt" in payload:
        original=payload["receipt"]
        if not isinstance(original,dict) or original.get("port")!="L2" or original.get("adapter")!=m["id"] or original.get("version")!=m["version"] or original.get("manifest_sha256")!=m["manifest_sha256"]:
            raise SlotUnavailable(role,"binding_changed","必须用产生原证明的槽件及相同发行清单复验")
    iv=hash_json(payload) if input_version is None else input_version
    if not isinstance(iv,str) or not 0<len(iv)<=256:raise ValueError("缺少输入版本")
    event=payload.get("id") if port=="C1" else payload.get("request") if port=="C8" and payload.get("phase")=="commit" else None
    if event:
        old=_dbreceipt(db,m,port,event,hash_json(payload))
        if old and old["input_version"]==iv:return old
        if old:raise ValueError("观察的输入版本与首次派发不同")
    budget=min(BUDGET_MS[role],max(1,int(timeout_ms if timeout_ms is not None else BUDGET_MS[role])))
    try:
        if m["provider_type"]=="joint-native":
            import joint25_runtime
            out,src=joint25_runtime.handle(ROOT,m,port,payload,budget,db)
        elif m["provider_type"]=="legacy":
            import slot31_legacy
            out,src=slot31_legacy.handle(ROOT,m,port,payload,budget,db)
        else:
            import slot31_transport
            frame=slot31_transport.exchange(ROOT,m,port,payload,iv,budget)
            out,src=frame["output"],frame["sources"]
        _validate(port,out,m)
        if not isinstance(src,list) or not 1<=len(src)<=64 or any(not isinstance(v,str) or not 0<len(v)<=1024 for v in src):raise ValueError("缺少有效来源列表")
        if port=="C1" and not out.get("refused") and out.get("id")!=event:raise ValueError("观察确认号不同")
        if port=="C8" and not out.get("refused") and out.get("request")!=payload.get("request"):raise ValueError("槽回执请求号不同")
        if port=="L5" and out.get("matches") is True:
            prior=payload.get("proof_ref") or payload.get("receipt",{}).get("output",{}).get("proof_ref")
            if not prior or prior!=out["proof_ref"]:raise ValueError("复验声明一致但返回了不同证明")
        if port=="C7" and not out.get("refused") and out["round_id"]!=payload.get("round_id"):raise ValueError("审计返回了其他轮号")
        if port=="C3" and not out.get("refused"):
            permitted={offer["id"] for offer in payload.get("offers",[])}
            returned=[v["id"] for v in out["candidates"]]
            if len(set(returned))!=len(returned) or not set(returned)<=permitted:raise ValueError("认知槽扩展了本轮候选范围")
        if port=="L4" and not out.get("refused"):
            conclusion=payload.get("conclusion") or {}
            evidence=conclusion.get("evidence_refs") or conclusion.get("sources") or []
            if not evidence or not set(src)<=set(evidence):raise ValueError("表达引用了结论之外的来源")
            permitted=[conclusion["text"]]
            limits=conclusion.get("limits") or []
            permitted.extend([limits] if isinstance(limits,str) else limits)
            if out["text"] not in {permitted[0],"\n".join(permitted)}:raise ValueError("当前表达契约只接受经认知槽确认的结论与限度")
        if port=="C5" and not out.get("refused") and out["budget_ms"]>payload.get("budget_ms",budget):raise ValueError("槽试图扩大宿主预算")
        if port=="C2" and not out.get("refused"):
            import host_memory31
            if out["operation"]!=payload.get("operation"):raise ValueError("槽申请改变宿主授权操作")
            try:
                value=host_memory31.handle(db,out,owner=owner,source_ref="slot:"+m["id"]+":"+iv)
                out=dict(value,operation=out["operation"])
            except ValueError as exc:
                out={"refused":True,"reason":str(exc),"operation":out["operation"]}
    except SlotUnavailable:raise
    except (TimeoutError,ValueError,KeyError,TypeError,IndexError,RuntimeError,OSError) as e:
        code="timeout" if isinstance(e,TimeoutError) else "invalid" if isinstance(e,(ValueError,KeyError,TypeError,IndexError)) else "crash"
        failed=SlotUnavailable(role,code,e)
        mark_fault(db,failed,m)
        raise failed from e
    frame={"slot":role,"port":port,"adapter":m["id"],"version":m["version"],"revision":m["revision"],"manifest_sha256":m["manifest_sha256"],
           "input_version":iv,"sources":src,"output":out}
    if event:_store_receipt(db,m,port,event,hash_json(payload),frame)
    return frame

def register_release(db,adapter_id):
    """Admit a locally installed provider only after a separately recorded release gate."""
    import slot31_transport
    m=slot31_transport.read_release(ROOT,adapter_id)
    row=db.execute("SELECT pin FROM slot31_registry WHERE adapter_id=?",(m["id"],)).fetchone()
    if row and row[0]!=hash_json(m):raise ValueError("同一槽件登记号已有不同构建，请使用新的发行编号")
    db.execute("INSERT OR IGNORE INTO slot31_registry VALUES(?,?,?,?)",(m["id"],m["slot"],canonical(m),hash_json(m)))

def capture_private(db):
    """Called at a quiescent host writer boundary, before publishing a backup or detaching C."""
    m=checkpoint(db)["C"]
    if m["id"]=="empty" or m["provider_type"] in {"legacy","joint-native"}:
        return {"adapter_id":m["id"],"storage":"empty" if m["id"]=="empty" else "legacy-save-file"}
    due=db.execute("""SELECT d.manifest_pin,d.state_sha256,s.opaque,s.state_format FROM slot31_private_restore_due d
        LEFT JOIN slot31_private_state s ON s.adapter_id=d.adapter_id AND s.manifest_sha256=d.manifest_pin AND s.state_sha256=d.state_sha256
        WHERE d.adapter_id=?""",(m["id"],)).fetchone()
    if due:
        if due[0]!=m["manifest_sha256"] or due[2] is None or hashlib.sha256(due[2]).hexdigest()!=due[1]:
            raise SlotUnavailable("C","invalid","待还原槽件缺少完整的封存字节")
        return {"adapter_id":m["id"],"state_format":due[3],"state_sha256":due[1],"bytes":len(due[2]),"storage":"pending_restore"}
    frame=dispatch(db,"C9",{"operation":"save"},pin=m)
    out=frame["output"]
    try:data=base64.b64decode(out["opaque_base64"],validate=True)
    except (KeyError,ValueError,TypeError) as exc:raise SlotUnavailable("C","invalid","C9 没有返回有效的不透明状态") from exc
    state_hash=hashlib.sha256(data).hexdigest()
    if (out.get("operation")!="save" or out.get("state_format")!=m["state_format"] or len(data)>1024*1024
            or out.get("state_sha256")!=state_hash):raise SlotUnavailable("C","invalid","C9 状态封包的格式、大小或摘要不符")
    db.execute("""INSERT INTO slot31_private_state VALUES(?,?,?,?,?,?,?) ON CONFLICT(adapter_id,manifest_sha256)
        DO UPDATE SET state_format=excluded.state_format,state_sha256=excluded.state_sha256,opaque=excluded.opaque,
        source_pin=excluded.source_pin,stamp=excluded.stamp""",
        (m["id"],m["manifest_sha256"],m["state_format"],state_hash,data,hash_json(frame["sources"]),time.time()))
    return {"adapter_id":m["id"],"state_format":m["state_format"],"state_sha256":state_hash,"bytes":len(data),"storage":"opaque_sqlite"}

def resume_private(db):
    """Restore a pinned C private payload only for this exact release, at an explicit restore/attach boundary."""
    m=checkpoint(db)["C"]
    if m["id"]=="empty" or m["provider_type"] in {"legacy","joint-native"}:return {"adapter_id":m["id"],"restored":False,"legacy_file":m["provider_type"]=="legacy"}
    row=db.execute("SELECT state_format,state_sha256,opaque FROM slot31_private_state WHERE adapter_id=? AND manifest_sha256=?",
                   (m["id"],m["manifest_sha256"])).fetchone()
    due=db.execute("SELECT manifest_pin,state_sha256 FROM slot31_private_restore_due WHERE adapter_id=?",(m["id"],)).fetchone()
    if due and (not row or due[0]!=m["manifest_sha256"] or due[1]!=row[1]):
        raise SlotUnavailable("C","invalid","换回后的槽件与待恢复检查点不一致")
    if not row:return {"adapter_id":m["id"],"restored":False,"reason":"first_binding"}
    fmt,state_hash,data=row
    if fmt!=m["state_format"] or hashlib.sha256(data).hexdigest()!=state_hash:raise SlotUnavailable("C","invalid","已保存的槽状态损坏或版本不符")
    token=_restoring.set(True)
    try:
        unsafe_detach=db.execute("SELECT reason FROM slot31_detach_notes WHERE adapter_id=? AND manifest_pin=?",(m["id"],m["manifest_sha256"])).fetchone()
        if unsafe_detach and not due:
            current=dispatch(db,"C9",{"operation":"describe"},pin=m)["output"]
            if current.get("state_sha256")!=state_hash:
                raise SlotUnavailable("C","uncertain_restore","上次下线时未能导出状态；当前件需要按原存档对账")
        frame=dispatch(db,"C9",{"operation":"restore","state_format":fmt,"state_sha256":state_hash,
                                "opaque_base64":base64.b64encode(data).decode("ascii")},pin=m)
        out=frame["output"]
        if out.get("operation")!="restore" or out.get("state_sha256")!=state_hash:raise SlotUnavailable("C","invalid","外置槽未确认还原的检查点")
        checked=dispatch(db,"C9",{"operation":"describe"},pin=m)["output"]
        if checked.get("state_sha256")!=state_hash:raise SlotUnavailable("C","invalid","重新打开槽件后状态摘要不同")
        db.execute("DELETE FROM slot31_private_restore_due WHERE adapter_id=? AND manifest_pin=? AND state_sha256=?",(m["id"],m["manifest_sha256"],state_hash))
        db.execute("DELETE FROM slot31_detach_notes WHERE adapter_id=? AND manifest_pin=?",(m["id"],m["manifest_sha256"]))
    finally:_restoring.reset(token)
    return {"adapter_id":m["id"],"restored":True,"state_sha256":state_hash,"bytes":len(data)}

def _probe(db,m):
    issue=_checkfiles(m)
    if issue:raise SlotUnavailable(m["slot"],"artifact",issue)
    if m["provider_type"]=="joint-native":
        from joint25_runtime import selftest
        return selftest(ROOT,m)
    if m["provider_type"]=="legacy":
        from slot31_legacy import selftest
        return selftest(ROOT,m)
    from slot31_transport import probe
    return probe(ROOT,m)

def bind(db,*,language=None,cognition=None):
    """Atomic pair rebind; callers hold the same writer lock used for requests."""
    setup(db)
    changes=[]
    for role,aid in (("L",language),("C",cognition)):
        if aid is None:continue
        current=checkpoint(db)[role]
        if aid=="empty":m=empty(role);test=None
        else:
            row=db.execute("SELECT manifest FROM slot31_registry WHERE slot=? AND adapter_id=?",(role,aid)).fetchone()
            if not row:raise ValueError(role+" 槽件尚未登记或属于其他槽")
            m=json.loads(row[0]);test=_probe(db,m)
            if not test.get("passed"):raise SlotUnavailable(role,"selftest","本机适配器自检失败")
        if current["id"]!=aid or current["state"] not in ("ready","empty"):
            changes.append((role,m,current,test))
    with _transaction(db):
        for role,m,current,test in changes:
            if current["id"]!=m["id"] and db.execute("SELECT 1 FROM sqlite_master WHERE name='host31_request_routes'").fetchone():
                pending=db.execute("""SELECT r.id,x.bindings FROM requests r JOIN host31_request_routes x ON x.id=r.id
                    LEFT JOIN host31_commits c ON c.request_id=r.id WHERE r.phase IN ('running','prepared') AND c.request_id IS NULL""").fetchall()
                emergency_empty=m["id"]=="empty" and (current["state"]=="unavailable" or bool(_checkfiles(current)))
                if not emergency_empty and any(json.loads(raw).get(role,{}).get("id")==current["id"] for rid,raw in pending):
                    raise ValueError("存在使用当前绑定的未完成请求，请先按原号对账再换槽")
            if role=="C" and current["id"]!=m["id"] and current["provider_type"]=="external":
                try:capture_private(db)
                except SlotUnavailable as exc:
                    if m["id"]!="empty":raise
                    db.execute("INSERT OR REPLACE INTO slot31_detach_notes VALUES(?,?,?,?)",(current["id"],current["manifest_sha256"],str(exc),time.time()))
            rev=current["revision"]+int(current["id"]!=m["id"]);state="empty" if m["id"]=="empty" else "ready"
            db.execute("UPDATE slot31_bindings SET adapter_id=?,revision=?,health=?,reason=?,selftest=? WHERE slot=?",
                  (m["id"],rev,state,"尚未绑定槽件" if state=="empty" else "",canonical(test) if test else None,role))
            db.execute("INSERT INTO slot31_changes(slot,prior,current,revision,stamp,manifest_pin) VALUES(?,?,?,?,?,?)",
                (role,current["id"],m["id"],rev,time.time(),hash_json(m)))
            if role=="C" and current["id"]!=m["id"] and m["provider_type"]=="external":
                resume_private(db)
    return snapshot(db)
@contextmanager
def _transaction(db):
    db.execute("SAVEPOINT slot31_pair")
    try:yield
    except BaseException:
        db.execute("ROLLBACK TO slot31_pair");db.execute("RELEASE slot31_pair");raise
    else:db.execute("RELEASE slot31_pair")

