"""Host-side evidence-bound requests for the Windows joint native agenda; no automatic fact or rule adoption."""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib
import json
import msvcrt
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
COG="joint25-pcgm"
HEX=re.compile(r"[0-9a-f]{64}\Z")
NAME=re.compile(r"[a-z][a-z0-9_]{0,46}\Z")
ACTIONS={"agenda","repair_review","answer_review","withdraw_review","enroll","repair","answer","withdraw","enroll_receipt","answer_receipt","scope_review","scope_install","scope_receipt"}
def packed(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def sha(v):return hashlib.sha256(packed(v).encode()).hexdigest()
def atom(a):
    if not isinstance(a,dict):return ""
    return ("!" if a.get("polarity")=="negative" else "")+a["predicate"]+"("+",".join(str(x["value"]) for x in a["arguments"])+")"
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS joint25_reviews(pin TEXT PRIMARY KEY,kind TEXT NOT NULL,session TEXT NOT NULL,
        actor TEXT NOT NULL,head TEXT NOT NULL,manifest TEXT NOT NULL,native_pin TEXT NOT NULL,body TEXT NOT NULL,
        phase TEXT NOT NULL,request TEXT,receipt TEXT,created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS joint25_watch(id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT NOT NULL,
        host_version TEXT NOT NULL,due REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS joint25_session_review ON joint25_reviews(session,kind,created)")
@lru_cache(maxsize=4)
def _engines(root):
    helpers=root/"releases/joint25/tools"
    if not helpers.is_dir():raise RuntimeError("缺少联合原生管道适配器")
    sys.path.insert(0,str(helpers))
    try:
        native=importlib.import_module("joint25_handoff");gateway=importlib.import_module("joint25_gateway")
    finally:sys.path.pop(0)
    if any(Path(x.__file__).resolve().parent!=helpers.resolve() for x in (native,gateway)):
        raise RuntimeError("已载入的原生维护程序属于另一发行")
    return native,gateway

def _scope_spec(tag):
    if not isinstance(tag,str) or not re.fullmatch(r"local_[a-z][a-z0-9_]{0,15}",tag):
        raise ValueError("请提供 local_ 开头、其后至多16字符的小写英文字母/数字/下划线前缀")
    stalled,confirmed,output=(tag+x for x in ("_stalled","_confirmed","_candidate"))
    source=f": {stalled}(sym).\n: {confirmed}(sym).\n: {output}(sym).\n@ {stalled} {confirmed} {output}.\n"
    return tag+"_scope",(stalled,confirmed,output),source.encode()

def _compatible_module(parent,name,content,publish):
    from tempfile import NamedTemporaryFile
    import os
    folder=parent/"modules"
    if not folder.exists() and publish:folder.mkdir(exist_ok=True)
    if folder.resolve()!=folder or not folder.is_dir():raise ValueError("模块目录与当前存档不匹配")
    dst=folder/(name+".cl")
    if dst.resolve()!=dst:raise ValueError("模块路径重定向")
    if dst.exists():
        if not dst.is_file() or dst.read_bytes()!=content:raise ValueError("另一份同名模块已存在，保留原件")
    elif publish:
        with NamedTemporaryFile(dir=folder,suffix=".candidate",delete=False) as f:
            f.write(content);f.flush();os.fsync(f.fileno());tmp=Path(f.name)
        try:
            try:os.rename(tmp,dst)
            except FileExistsError:
                if dst.read_bytes()!=content:raise ValueError("模块路径刚被另一版本占用")
        finally:tmp.unlink(missing_ok=True)

def _scope_preview(n,b,state,snap,tag):
    import tempfile,shutil
    name,keys,content=_scope_spec(tag);prefix=snap["source"]
    if any(re.search(r"\b"+re.escape(key)+r"\b",prefix) for key in (name,*keys)):
        raise ValueError("请求的模块名或谓词已在原程序使用，不能扩写其权限")
    if len(re.findall(r"(?m)^\s*@[ \t]+",prefix))>=8:raise ValueError("原生受限修复范围已达八项")
    _compatible_module(state.parent,name,content,False)
    active=n.exe(b,snap["owner"])
    original_history=n.history(active,state)
    # Only the native save and the native auxiliaries participate. No desktop DB, identity copy
    # activation, external calls, or course records are required by this detached preflight.
    with tempfile.TemporaryDirectory(prefix="zaizai-scope-proposal-") as td:
        dst=Path(td).resolve()/"state";dst.mkdir();sample=dst/state.name
        shutil.copy2(state,sample)
        for suffix in (".history",".episodes"):
            path=state.with_name(state.name+suffix)
            if path.exists():
                if path.resolve()!=path or not path.is_dir():raise ValueError("附属状态目录异常")
                shutil.copytree(path,dst/path.name)
        (dst/"modules").mkdir();_compatible_module(dst,name,content,True)
        raw=n.invoke(active,["--resume",sample],(":install "+name+"\n").encode()).splitlines()
        if len(raw)!=2 or not raw[-1].endswith("module_installed "+name):raise ValueError("原生模块预演无有效回执")
        old,added=n.fields(raw[0]),n.fields(raw[-1])
        out=n.snapshot(active,sample)
        if (out["individual"]!=snap["individual"] or out["inactive"]!=snap["inactive"] or old["facts"]!=added["facts"]
                or not out["source"].startswith(prefix) or out["source"][len(prefix):].strip()!="# module "+name+"\n"+content.decode().strip()):
            raise ValueError("预演改变了既有事实或超出固定授权内容")
        result=json.loads(n.invoke(active,["--resume",sample],b":repair_compare\n").splitlines()[-1])
        decision=result["decision"];idx=decision["selected"]
        if len(original_history)!=int(old["event"]):raise ValueError("预演期间原生历史已改变")
        data={"actor":snap["individual"],"head":snap["head"],"module":name,"tag":tag,"predicates":list(keys),
              "module_sha256":n.digest(content),"source_sha256":n.digest(prefix.encode()),"expected_head":out["head"],
              "original_source_bytes":len(prefix.encode()),"original_history_sha256":n.pin(original_history),
              "native_before_event":int(old["event"]),"native_epoch":int(added["epoch"]),"existing_facts":int(old["facts"]),
              "proposed_code":content.decode(),"decision_after_install":decision["options"][idx]["kind"] if idx is not None else None,
              "refusals":[x.get("blocked_reason") for x in decision["options"] if x.get("blocked_reason")],"predicted_install_receipt":raw[-1]}
        return dict(data,review_sha256=sha(data))

def _scope_receipt(n,b,state,snap,v):
    if v["actor"]!=snap["individual"]:raise ValueError("范围回执身份不匹配")
    if snap["head"]==v["expected_head"]:return "recorded"
    if snap["head"]==v["head"]:return "not_recorded"
    # An ACK can be lost before a later unrelated event. Identify our original prefix,
    # the exact next event and the appended module bytes; never retry when that proof is absent.
    if "original_history_sha256" not in v:return "uncertain"
    events=n.history(n.exe(b,snap["owner"]),state);prior=v["native_before_event"]
    source=snap["source"].encode();off=v["original_source_bytes"]
    if (len(events)>prior and n.pin(events[:prior])==v["original_history_sha256"]
        and events[prior]==f"event={prior+1} install {v['module']}"
        and n.digest(source[:off])==v["source_sha256"]
        and source[off:].lstrip(b"\r\n").startswith(("# module "+v["module"]+"\n"+v["proposed_code"]).encode())):
        return "recorded"
    return "uncertain"

def _scope_apply(n,b,state,snap,v,review_pin):
    import subprocess
    tag=v["tag"];name,keys,content=_scope_spec(tag)
    if v.get("actor")!=snap["individual"] or name!=v.get("module") or list(keys)!=v.get("predicates") or n.digest(content)!=v.get("module_sha256"):
        raise ValueError("已复核的身份、范围或预览文档不一致")
    original={k:value for k,value in v.items() if k!="review_sha256"}
    if sha(original)!=review_pin:raise ValueError("初始范围复核摘要不匹配")
    active=n.exe(b,snap["owner"])
    def receipt(written):
        return {"actor":v["actor"],"module":v["module"],"scope_pin":review_pin,"module_sha256":v["module_sha256"],
                "prior_head":v["head"],"head_sha256":v["expected_head"],"native_event":v["native_before_event"]+1,
                "existing_facts":v["existing_facts"],"decision_in_preview":v["decision_after_install"],"observations_added":0,
                "writes_state":written,"repair_committed":False}
    if snap["head"]==v["expected_head"]:return receipt(False)
    if snap["head"]!=v["head"]:raise ValueError("原状态已改变，须重新复核，不发过期批准")
    # Keep the native write lock between the last head check and the native installation.
    with subprocess.Popen([active,"--resume",state],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW) as p:
        import threading
        timer=threading.Timer(n.remaining(),lambda:p.kill() if p.poll() is None else None);timer.daemon=True;timer.start()
        try:
            hello=p.stdout.readline().decode("utf8");locked=n.snapshot(active,state)
            if not hello.startswith("individual="+v["actor"]+" ") or locked["head"]!=v["head"]:raise ValueError("原生写者未锁住已复核的状态")
            _compatible_module(state.parent,name,content,True)
            output,error=p.communicate(input=(":install "+name+"\n").encode(),timeout=n.remaining())
            if p.returncode or error or output.decode().strip()!=v["predicted_install_receipt"]:
                raise ValueError("模块提交结果不明，须按原批准核对")
        finally:
            if p.poll() is None:p.kill();p.communicate()
            timer.cancel()
    current=n.snapshot(active,state)
    if current["head"]!=v["expected_head"]:raise ValueError("提交后状态头与预演不符，保留原记录")
    return receipt(True)



def adapter(root,manifest,port,p,budget,db):
    """Called only by the enrolled provider's normal C3/C4/C8 dispatcher."""
    root=Path(root).resolve();n,g=_engines(root);b=root/"releases/joint25/bin";state=root/"state/individual.pcgm"
    op=p["joint25_op"]
    if manifest.get("id")!=COG or op not in ACTIONS:raise ValueError("错误的原生运维请求")
    if port=="C8" and p.get("phase")!="commit":raise ValueError("运维申请只由已固定申请的提交端消费")
    def respond(result,**extra):
        result=dict(result);refs=["joint25-operation:"+op,"sha256:"+sha(result)]
        if port=="C3":return {"candidates":[],"review":result,**extra},refs
        if port=="C4":return {"questions":[],"review":result,**extra},refs
        return {"phase":"replayed" if result.get("writes_state") is False else "committed","request":p["request"],
                "receipt":"native:"+sha(result),"native_result":result},refs
    try:
        with n.deadline_scope(max(1,int(budget))/1000):
            if port=="C4" and op=="agenda":return respond(g.work_agenda(b,state))
            if port=="C3" and op=="repair_review":return respond(g.review_repair(b,state))
            binary,snap=g.checkstate(b,state)
            actor=snap["individual"];head=snap["head"]
            if port=="C3" and op=="scope_review":
                return respond(_scope_preview(n,b,state,snap,p["tag"]))
            if port=="C4" and op=="scope_receipt":
                v=p["entry"]["values"]
                return respond({"actor":actor,"head_sha256":head,"module":v["module"],
                    "status":_scope_receipt(n,b,state,snap,v)})
            if port=="C8" and op=="scope_install":
                entry=p["entry"]
                return respond(_scope_apply(n,b,state,snap,entry["values"],entry["native_pin"]))
            if port=="C4" and op=="answer_review":
                x=p["answer"];member=x["member"];ticket=x["ticket"]
                if not NAME.fullmatch(member) or not NAME.fullmatch(ticket) or not all(HEX.fullmatch(x[k]) for k in ("request_pin","artifact","package","snapshot")):
                    raise ValueError("答卷的题号、成员或版本标识无效")
                parent=state.parent/"incoming";path=(parent/(member+".clef")).resolve(strict=True)
                if parent.resolve()!=parent or path.parent!=parent or path.name!=member+".clef" or n.filehash(path)!=x["artifact"]:
                    raise ValueError("冻结答卷成员或摘要不匹配")
                result=json.loads(n.invoke(binary,["--frozen-question-review",state,ticket,x["request_pin"],path,x["artifact"],x["package"],x["snapshot"]]))
                if result.get("individual")!=actor or result.get("observation_written") is not False:raise ValueError("冻结审阅身份或只读标记不符")
                ticket_data=n.read(binary,state,"question "+ticket)
                if re.search(r'"predicate"\s*:\s*"(?:labelled_support|scoped_claim)"',packed(ticket_data)):
                    raise ValueError("该题涉及联合来源专用谓词；须按具体来源投影复核")
                return respond({"actor":actor,"head":head,"answer":x,"verified":result,"review_sha256":sha(result)})
            if port=="C4" and op=="withdraw_review":
                x=p["answer"];options=SimpleNamespace(op="answer-receipt",bin=b,state=state,actor=actor,ticket=x["ticket"],request_pin=x["request_pin"],
                    artifact=x["artifact"],package=x["package"],snap=x["snapshot"],proof=x["proof"])
                actual=g.execute(options,host_locked=True)
                if actual.get("status")!="recorded" or not NAME.fullmatch(actual.get("observation","")):
                    raise ValueError("没有仍生效且归属此冻结答卷的原生观察")
                return respond({"actor":actor,"head":head,"observation":actual["observation"],"parent_answer":x,"review_sha256":sha(actual)})
            if port=="C4" and op in ("enroll_receipt","answer_receipt"):
                entry=p["entry"];values=entry["values"]
                if op=="enroll_receipt":args=dict(op="enrollment-receipt",head=entry["head"],review=entry["native_pin"])
                else:
                    x=values["answer"];args=dict(op="answer-receipt",ticket=x["ticket"],request_pin=x["request_pin"],artifact=x["artifact"],
                                               package=x["package"],snap=x["snapshot"],proof=values["verified"]["proof_sha256"])
                return respond(g.execute(SimpleNamespace(bin=b,state=state,actor=entry["actor"],**args),host_locked=True))
            if port!="C8" or op not in {"enroll","repair","answer","withdraw"}:raise ValueError("操作与原生端口不匹配")
            entry=p["entry"];v=entry["values"];args=dict(bin=b,state=state,actor=entry["actor"],head=entry["head"],apply=True)
            if op=="enroll":args.update(op="enroll",review=entry["native_pin"])
            elif op=="repair":args.update(op="repair-apply",review=entry["native_pin"])
            elif op=="withdraw":args.update(op="withdraw",observation=v["observation"])
            else:
                x=v["answer"];args.update(op="answer",ticket=x["ticket"],request_pin=x["request_pin"],member=x["member"],
                    artifact=x["artifact"],package=x["package"],snap=x["snapshot"],proof=v["verified"]["proof_sha256"])
            return respond(g.execute(SimpleNamespace(**args),host_locked=True))
    except (ValueError,FileNotFoundError) as exc:
        # Refusal is a domain result; valid lack of supported schemas/approval must not fault the entire slot.
        return {"refused":True,"reason":str(exc)[:500]},["native-refusal:"+op]

def checked(db):
    import slots31
    c=slots31.snapshot(db)["C"]
    if c["id"]!=COG or c["state"]!="ready":return None
    return c
def port(db,slot,which,operation,extra=None,ms=2400):
    import slots31
    p={"joint25_op":operation,**(extra or {})}
    answer=slots31.dispatch(db,which,p,pin=slot,input_version=sha(p),timeout_ms=ms)
    out=answer["output"]
    if out.get("refused"):raise ValueError(str(out["reason"]))
    return out["native_result" if which=="C8" else "review"]
def remember(db,scope,kind,c,value):
    actor=value["actor"];head=value.get("revision_sha256") or value["head"]
    native_pin=value["review_sha256"]
    if not HEX.fullmatch(head) or not HEX.fullmatch(native_pin):raise ValueError("缺少原生审核摘要")
    key=sha([scope,kind,actor,head,native_pin,c["manifest_sha256"]])
    db.execute("INSERT OR IGNORE INTO joint25_reviews VALUES(?,?,?,?,?,?,?,?,'reviewed',NULL,NULL,?)",
               (key,kind,scope,actor,head,c["manifest_sha256"],native_pin,packed(value),time.time()))
    return key
def unique(a):
    review=a.get("proposed_review") or {};inv=review.get("investigation") or {}
    return (a.get("schema")=="pcgm-work-agenda-v1" and a.get("reason")=="pending_approval" and a.get("search_complete") is True
            and a.get("eligible_count")==1 and len(a.get("eligible_goals",[]))==1 and isinstance(inv.get("premise"),dict)
            and a.get("writes_state") is False and a.get("outbound") is False and HEX.fullmatch(a.get("review_sha256") or "") is not None)
def entry(row):
    return {"actor":row["actor"],"head":row["head"],"native_pin":row["native_pin"],"values":json.loads(row["body"])}
def approve(db,c,kind,pin_text,scope,ms=3900):
    import slots31
    if db.in_transaction:raise ValueError("需在已落盘的宿主请求边界审批，无其它未提交工作")
    if not HEX.fullmatch(pin_text):raise ValueError("请提供该会话展示的完整申请编号")
    row=db.execute("SELECT * FROM joint25_reviews WHERE pin=? AND session IN (?, 'host')",(pin_text,scope)).fetchone()
    if not row or row["kind"]!=kind or row["manifest"]!=c["manifest_sha256"]:raise ValueError("找不到符合本次操作及发行的申请")
    if row["phase"]=="committed":return json.loads(row["receipt"])
    payload=entry(row);request="a"+pin_text[:32]
    if row["phase"]=="issued":
        if kind in {"enroll","answer","scope_install"}:
            found=port(db,c,"C4",("scope_receipt" if kind=="scope_install" else kind+"_receipt"),{"entry":payload},ms=ms)
            if found.get("status") in {"recorded","withdrawn"}:
                with db:db.execute("UPDATE joint25_reviews SET phase='committed',receipt=? WHERE pin=?",(packed(found),pin_text))
                return found
            if not(found.get("status")=="not_recorded" and found.get("head_sha256")==row["head"]):
                raise ValueError("此前请求未能核对至同一状态头；保留原记录，不再次派发")
        else:raise ValueError("此前请求已发出且未能确认效果；保留原记录，不再次派发")
    # This method is invoked only from the quiescent writer command path, before other local effects.
    with db:db.execute("UPDATE joint25_reviews SET phase='issued',request=? WHERE pin=?",(request,pin_text))
    result=port(db,c,"C8",kind,{"request":request,"phase":"commit","entry":payload},ms=ms)
    with db:db.execute("UPDATE joint25_reviews SET phase='committed',receipt=? WHERE pin=?",(packed(result),pin_text))
    return result

def owner_hint(db, action, *, background=False):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name IN ('deleg25_control','life3_meta')")}
    control=db.execute("SELECT v FROM deleg25_control WHERE k='enabled'").fetchone() if "deleg25_control" in tables else None
    if control and control[0]!="1":
        return "委托已暂停。输入「执行报告」查看已有记录，「恢复委托」恢复处理。"
    if background and "life3_meta" in tables:
        state=dict(db.execute("SELECT key,value FROM life3_meta WHERE key IN ('paused','enabled')"))
        if state.get("enabled")!="1" or state.get("paused")=="1":
            return "本机后台当前已停止或暂停。本轮只复核，进度可在「执行报告」查看。"
    return action+" 结果可在「执行报告」查看。"

def preview_hint(db, action, original, *, background=False):
    return owner_hint(db,action,background=background)+"\n旧申请兼容指令「"+original+"」。"

def describe_agenda(a):
    reason={"pending_approval":"存在一项可区分的缺口","tied":"有多个同等候选，暂不替它们选一个","already_ticketed":"当前缺口已有问题号",
            "scan_truncated":"本轮扫描未完整收束","none":"当前未发现合格的新问题"}.get(a["reason"],a["reason"])
    goals="、".join(atom(x) for x in a.get("eligible_goals",[])[:8])
    return f"原生议程：{reason}。合格目标 {a['eligible_count']} 个。"+("\n"+goals if goals else "")+"\n状态头 "+a["revision_sha256"]
def command(db,text,session,rid):
    key=text.strip().rstrip("。！？?!")
    ops={"批准内部问询":"enroll","批准规则方案":"repair","批准原生答卷":"answer","批准撤回观察":"withdraw","批准修复范围":"scope_install"}
    name,sep,arg=key.partition(" ")
    if name=="复核答卷":name="复核原生答卷"
    if name not in {*ops,"原生议程","复核改进","复核修复范围","复核原生答卷","复核撤回","原生申请","原生申请回执"}:return None
    setup(db);c=checked(db)
    if not c:return "当前未绑定可用的联合认知件，原生运维没有派发。"
    try:
        if name=="原生议程":
            a=port(db,c,"C4","agenda");body=describe_agenda(a)
            if unique(a):
                k=remember(db,session,"enroll",c,a);body+="\n"+preview_hint(db,"后台会在空闲时重查这一项缺口，符合条件就登记内部问题。","批准内部问询 "+k,background=True)
            else:
                body+="\n"+owner_hint(db,"出现唯一可询缺口后，后台会在空闲时重查并登记内部问题。",background=True)
            return body
        if name=="复核修复范围":
            from scope_existing25 import existing
            prior=existing(db,ROOT,c,arg)
            if prior is not None:
                return f"原生第 {prior['native_event']} 项已登记 {prior['module']}。本轮只核对原凭据。\n"+owner_hint(db,f"输入「登记修复范围 {arg}」可沿用这份原始登记，原申请 {prior['original_review']}。")
            v=port(db,c,"C3","scope_review",{"tag":arg},ms=3800);k=remember(db,session,"scope_install",c,v)
            return f"新范围 {v['module']} 的原生副本预演：\n{v['proposed_code']}事实数 {v['existing_facts']} 保持，安装后比较选 {v['decision_after_install']}。本轮只预演。\n"+preview_hint(db,f"需要登记时输入「登记修复范围 {arg}」，宿主会校验范围并返回原生回执。","批准修复范围 "+k)
        if name=="复核改进":
            a=port(db,c,"C3","repair_review");k=remember(db,session,"repair",c,a)
            dec=a["review"]["decision"];opts=dec["options"];selected=dec["selected"]
            return "原生复核选项："+ "、".join(x["kind"] for x in opts)+f"。当前选择 {opts[selected]['kind'] if selected is not None else '未决'}。本轮只复核。\n"+preview_hint(db,"输入「执行规则改进」可由宿主复核并执行原生选出的合格变更。","批准规则方案 "+k)
        if name=="复核原生答卷":
            words=arg.split()
            if len(words)!=6:return "只读复核格式：复核原生答卷 题号 请求摘要 成员名 制品摘要 包摘要 快照摘要。"+owner_hint(db,"提交时使用相同六个字段，输入「提交本地冻结答卷 …」由宿主自动核验。")
            x=dict(zip(("ticket","request_pin","member","artifact","package","snapshot"),words))
            result=port(db,c,"C4","answer_review",{"answer":x});k=remember(db,session,"answer",c,result)
            return f"冻结答卷已只读核对，证明 {result['verified']['proof_sha256']}。\n"+preview_hint(db,"输入「提交本地冻结答卷 "+arg+"」，宿主按原生证明核验并处理。","批准原生答卷 "+k)
        if name=="复核撤回":
            old=db.execute("SELECT * FROM joint25_reviews WHERE pin=? AND kind='answer' AND session=? AND phase='committed'",(arg,session)).fetchone()
            if not old:raise ValueError("没有该会话已采纳的答卷")
            body=json.loads(old["body"]);x=dict(body["answer"],proof=body["verified"]["proof_sha256"])
            result=port(db,c,"C4","withdraw_review",{"answer":x});k=remember(db,session,"withdraw",c,result)
            return f"将撤回观察 {result['observation']}。本轮只复核。\n"+preview_hint(db,"已委托采纳的答卷可用「撤回已提交答卷 原委托任务编号」处理。","批准撤回观察 "+k)
        if name in ops:
            result=approve(db,c,ops[name],arg,session)
            if ops[name]=="repair":
                decision=result["decision"];index=decision["selected"]
                selection=decision["options"][index]["kind"] if index is not None else "未决"
                body=f"原生比较选择 {selection}，实际写入 {result['writes_state']}，决策事件 {result.get('decision_event')}。"
            else:body=packed(result)[:1300]
            return "原生操作回执："+body+"\n申请 "+arg
        if name=="原生申请回执":
            row=db.execute("SELECT kind,phase,actor,head,receipt FROM joint25_reviews WHERE pin=? AND session IN (?, 'host')",(arg,session)).fetchone()
            return "当前会话没有这张申请。" if not row else "申请 "+arg+"\n"+packed(dict(row))[:2400]
        rows=db.execute("SELECT pin,kind,phase FROM joint25_reviews WHERE session IN (?, 'host') ORDER BY created DESC LIMIT 12",(session,)).fetchall()
        return "\n".join(f"{x['kind']} · {x['phase']} · {x['pin']}" for x in rows) or "尚无已登记的原生申请。"
    except (ValueError,FileNotFoundError) as exc:return "原生操作未执行或待核对："+str(exc)
@contextmanager
def available_writer(root):
    streams=[]
    try:
        for p in (root/"writer.guard",root/"state/desktop-writer.lock"):
            f=p.open("a+b");f.seek(0)
            try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                f.close();yield False;return
            streams.append(f)
        yield True
    finally:
        for f in reversed(streams):
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1);f.close()
def pump(db):
    """Run from a separate idle I/O connection; never nest with service.writer or a DB transaction."""
    if db.in_transaction:return None
    import life3_worker as host
    import slots31
    if host.active("foreground"):return None
    opts=dict(db.execute("SELECT key,value FROM life3_meta WHERE key IN ('paused','enabled')"))
    if opts.get("paused")=="1" or opts.get("enabled")!="1":return None
    with available_writer(ROOT) as owned:
        if not owned or host.active("foreground"):return None
        c=checked(db)
        if not c:return None
        from autonomy_reconcile25 import issued_enrollment
        setup(db)
        event=issued_enrollment(db,c)
        if event:return event
        now=time.time()
        last=db.execute("SELECT fingerprint,host_version,due FROM joint25_watch WHERE id=1").fetchone()
        local=db.execute("SELECT coalesce(max(seq),0) FROM turns").fetchone()[0]
        version=sha([c["revision"],local])
        if last and last[1]==version and now<last[2]:return None
        try:a=port(db,c,"C4","agenda",ms=500)
        except (slots31.SlotUnavailable,TimeoutError,ValueError):return None
        brief=sha([a["actor"],a["reason"],a["eligible_goals"],a["ticketed_count"],a.get("review_sha256")])
        with db:db.execute("INSERT OR REPLACE INTO joint25_watch VALUES(1,?,?,?)",(brief,version,now+60))
        if not unique(a):
            if last and brief==last[0]:return None
            return {"kind":"native_joint_agenda","topic":"原生议程","summary":describe_agenda(a),"source":"pcgm:"+a["revision_sha256"],
                    "status":"waiting","progress":False,"executed":False,"receipt":brief}
        if host.active("foreground"):return None
        with db:k=remember(db,"host","enroll",c,a)
        done=db.execute("SELECT phase FROM joint25_reviews WHERE pin=?",(k,)).fetchone()[0]
        if done=="committed":return None
        # Internal enrollment only. No external query, evidence approval, rule adoption, or file access is delegated.
        try:r=approve(db,c,"enroll",k,"host",ms=450)
        except (ValueError,slots31.SlotUnavailable,TimeoutError) as exc:
            return {"kind":"native_agenda_wait","topic":"原生问询","summary":str(exc)[:270],"source":"pcgm:"+a["revision_sha256"],"progress":False}
        return {"kind":"native_agenda_enrollment","topic":"原生问询","summary":"原生为唯一缺口登记内部票 "+str(r["ticket"]),
                "source":"pcgm:"+a["revision_sha256"],"ticket":r["ticket"],"review_pin":k,"progress":True,"receipt":sha(r)}

