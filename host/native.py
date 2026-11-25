"""Windows desktop adapter for the independent CL and PCGM command protocols."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from contextvars import ContextVar
from contextlib import contextmanager
_owner=ContextVar('held_owner',default=None)
@contextmanager
def request_context():
    mark=_owner.set('')
    try:yield
    finally:_owner.reset(mark)
import legacy_memory

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"
STATE=ROOT/"state"
SAVE=STATE/"individual.pcgm"
CL=BIN/"cl.exe"
PYTHON=ROOT/"runtime/python.exe"
DB=STATE/"dashboard-split.sqlite"
NATIVE=STATE/"native/offline-six-module-r28-20261120"
ANCHOR=json.loads((STATE/"native/joint-reopen.json").read_bytes())
IDENTITY=ANCHOR["identity"]
LEX=ROOT/"lexicon"
LEX_PIN="0109b3b1ebdc047765d5bfa0b8df815e961c509869394b0d1650d91b33c9eaaf"
CLAIM=re.compile(r"[a-z][a-z_0-9]{0,47}\([^\r\n()]{1,900}\)")
def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(obj): return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":"))
class LegacyUnavailable(RuntimeError):
    """The installed transition adapter could not complete an engine operation."""
    def __init__(self,slot,detail):
        self.slot=slot
        super().__init__(detail)

def run(binary,*args,data=b"",timeout=25):
    try:
        p=subprocess.run([str(binary),*map(str,args)],cwd=ROOT,input=data,capture_output=True,
                         timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError,subprocess.TimeoutExpired) as exc:
        if Path(binary).parent==BIN:
            raise LegacyUnavailable("L" if Path(binary)==CL else "C",f"{Path(binary).name} 无法完成调用：{exc}") from exc
        raise
    if p.returncode:
        message=f"{Path(binary).name} ({p.returncode}) "+(p.stderr or p.stdout).decode("utf8","replace").strip()[:1500]
        if Path(binary)==CL and args and args[0] in {"json","package-prove"} and p.returncode in (1,2):
            raise ValueError(message)
        if Path(binary).parent==BIN:
            raise LegacyUnavailable("L" if Path(binary)==CL else "C",message)
        raise RuntimeError(message)
    return p.stdout
def selected_binary(role,filename):
    if DB.is_file():
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='slot31_bindings'").fetchone():
                b=db.execute("SELECT adapter_id FROM slot31_bindings WHERE slot=?",(role,)).fetchone()
                if b and b[0] in ("joint25-cl","joint25-pcgm"):
                    return ROOT/"releases/joint25/bin"/filename
    return BIN/filename
def exe(owner):
    if owner not in {"alpha","beta"}:raise ValueError("未知 PCGM 端点")
    return selected_binary("C",f"pcgm-{owner}.exe")
def readcmd(query):
    if "\n" in query:raise ValueError("每次读取一条查询")
    packet=json.loads(run(exe("alpha"),"--read-channel",SAVE,data=("desktop "+query+"\n").encode()))
    if packet.get("protocol")!="pcgm-read-v1" or packet.get("id")!="desktop" or not packet.get("ok"):
        raise LegacyUnavailable("C",packet.get("error","读取协议错误"))
    return packet["payload"]
def status():
    s=readcmd("status")
    if s["state"]["individual"]!=IDENTITY:raise ValueError("身份与迁移记录不符")
    if _owner.get() is not None:_owner.set(s["owner"])
    return s
def execute(line):
    if "\n" in line or "\r" in line:raise ValueError("每个 PCGM 请求仅含一条命令")
    owner=_owner.get() or status()["owner"]
    out=run(exe(owner),"--resume",SAVE,data=(line+"\n").encode()).decode().splitlines()
    if not out or not out[0].startswith("individual="+IDENTITY+" "):raise LegacyUnavailable("C","PCGM 会话身份不符")
    errors=[x for x in out[1:] if x.startswith("QUERY_ERROR")]
    if errors:raise ValueError("\n".join(errors))
    return "\n".join(out[1:])
def switch():
    state=status()
    old=state["owner"];new="beta" if old=="alpha" else "alpha"
    if state["handoff_pending"]:return finish_switch()
    ready=run(exe(new),"--prepare",SAVE).decode().strip()
    fields=dict(re.findall(r"(\w+)=([^\s]+)",ready))
    if fields["individual"]!=IDENTITY or fields["build"]!=new or fields["binary_sha256"]!=sha(exe(new).read_bytes()):
        raise ValueError("待命端构建与准备回执不符")
    prepared=execute(":handoff "+new+" "+fields["binary_sha256"]+" "+fields["snapshot_sha256"])
    if not prepared.startswith("handoff_prepared "):raise RuntimeError(prepared)
    return finish_switch()
def finish_switch():
    before=status();old=before["owner"]
    output=run(exe(old),"--inspect",SAVE).decode()
    m=re.search(r"pending_handoff to=(alpha|beta) nonce=([0-9a-f]{32})",output)
    if not m:raise ValueError("缺少待接管回执")
    target,nonce=m.groups()
    try:
        run(exe(target),"--claim",SAVE,nonce)
    except Exception:
        after=status()
        if after["handoff_pending"] and after["owner"]==old:
            run(exe(old),"--cancel-handoff",SAVE,nonce)
        elif after["owner"]==target and not after["handoff_pending"]:
            return {"from":old,"to":target,"nonce":nonce,"state":after}
        raise
    after=status()
    if after["owner"]!=target or after["handoff_pending"]:raise RuntimeError("接管后状态不一致")
    return {"from":old,"to":target,"nonce":nonce,"state":after}
def negotiate():
    cl=json.loads(run(CL,"capabilities"))
    caps=[json.loads(run(exe(s),"--capabilities")) for s in ("alpha","beta")]
    if cl.get("release")!="0.157" or any(c.get("release")!="0.159" for c in caps):
        raise ValueError("不支持的 CL / PCGM 接口版本")
    return cl,caps
def ensure_desktop_modules():
    snapshot=json.loads(run(exe("alpha"),"--desktop-snapshot",SAVE))
    if snapshot["individual"]!=IDENTITY:raise ValueError("模块接入时身份不符")
    directory=STATE/"modules"
    directory.mkdir(exist_ok=True)
    for name in ("learning","desktop_criteria","r28_memory"):
        if f"# module {name}" in snapshot["source"].splitlines():continue
        contents=legacy_memory.definitions() if name=="r28_memory" else (ROOT/"host"/(name+".cl")).read_bytes()
        target=directory/(name+".cl")
        if target.exists() and target.read_bytes()!=contents:
            raise ValueError(f"待安装模块与本机构建不一致：{name}")
        if not target.exists():
            temporary=target.with_suffix(".cl.new")
            temporary.write_bytes(contents)
            os.replace(temporary,target)
        execute(":install "+name)
        snapshot=json.loads(run(exe("alpha"),"--desktop-snapshot",SAVE))
        if f"# module {name}" not in snapshot["source"].splitlines():
            raise RuntimeError(f"模块接入后未能读回：{name}")
def initialize():
    negotiate()
    legacy=json.loads(run(PYTHON,"-X","utf8","-I","-S","-B",ROOT/"tools/cold_read.py"))
    if legacy["identity"]!=IDENTITY:raise ValueError("原生存档身份不一致")
    if SAVE.exists():
        if status()["handoff_pending"]:finish_switch()
        if not (STATE/"imported.json").exists():
            snapshot=json.loads(run(exe("alpha"),"--desktop-snapshot",SAVE))
            seed=(STATE/"continuity.cl").read_bytes()
            if (snapshot["individual"]!=IDENTITY or not snapshot["source"].startswith(seed.decode())
                or legacy["receipt"] not in seed.decode() or not seed):
                raise RuntimeError("迁移标记缺失且原始导入数据无法核对")
            save_import_marker(legacy,seed)
        ensure_desktop_modules()
        return legacy
    if (STATE/"imported.json").exists():raise RuntimeError("已迁移的 PCGM 状态丢失，请从存档恢复")
    esc=lambda x:json.dumps(x,ensure_ascii=False)
    lines=[": saved_generation(sym,i64).",": saved_tick(sym,i64).",": saved_receipt(sym,sym).",
           ": identity_restored(sym).",": receipt_available(sym).",": term_defined(sym).",": ready_to_use(sym).",
           "identity_restored($a) <- saved_generation($a,$g) & saved_tick($a,$t).",
           "receipt_available($a) <- saved_receipt($a,$r).","ready_to_use($term) <- term_defined($term).",
           f"& r28_generation saved_generation(zaizai,{legacy['generation']}).",
           f"& r28_tick saved_tick(zaizai,{legacy['tick']}).",
           f"& r28_m5 saved_receipt(zaizai,{esc(legacy['receipt'])}).",
           "? identity_restored(zaizai).","? receipt_available(zaizai).","? ready_to_use(local_term)."]
    source=STATE/"continuity.cl"
    source.write_bytes(("\n".join(lines)+"\n").encode())
    (STATE/"incoming").mkdir(exist_ok=True)
    run(exe("alpha"),"--import-managed",source,SAVE,IDENTITY)
    if status()["state"]["individual"]!=legacy["identity"]:raise RuntimeError("导入后身份错误")
    save_import_marker(legacy,source.read_bytes())
    ensure_desktop_modules()
    return legacy
def save_import_marker(legacy,seed):
    tmp=STATE/"imported.json.new"
    tmp.write_text(canonical({"identity":IDENTITY,"source_sha256":sha(seed),
        "checkpoint_sha256":sha((NATIVE/"run/world/joint.json").read_bytes()),"m5_receipt":legacy["receipt"]}),encoding="utf8")
    os.replace(tmp,STATE/"imported.json")
def compile_text(text):
    with tempfile.NamedTemporaryFile(dir=STATE,suffix=".cl",delete=False) as f:
        path=Path(f.name);f.write(text.encode())
    try:
        proof=json.loads(run(selected_binary("L","cl.exe"),"json",path))
        return {"source_sha256":sha(text.encode()),"proof":proof}
    finally:path.unlink(missing_ok=True)
def proof_for(atom,compile_source=None):
    if not CLAIM.fullmatch(atom):raise ValueError("请提供带参数的 CL 目标，例如 identity_restored(zaizai)")
    snapshot=json.loads(run(exe("alpha"),"--desktop-snapshot",SAVE))
    if snapshot["individual"]!=IDENTITY:raise ValueError("证明快照身份不符")
    inactive=set(snapshot["inactive"])
    # PCGM-only choice, synthesis and sensor directives do not assert CL facts.
    lines=[line for line in snapshot["source"].splitlines() if not line.lstrip().startswith(("?","^","|","~","%","=","@"))
           and not ((m:=re.match(r"\s*&\s+(\w+)\s",line)) and m[1] in inactive)]
    result=(compile_source or compile_text)("\n".join(lines+[f"? {atom}.",""]))
    result["pcgm_head"]=snapshot["head"]
    owner=snapshot["owner"]
    if _owner.get() is not None:_owner.set(owner)
    packet=(":proof_integrity "+atom+"\n"+atom+"\n").encode()
    output=run(exe(owner),"--resume",SAVE,data=packet).decode().splitlines()
    if not output or not output[0].startswith("individual="+IDENTITY+" "):
        raise ValueError("原生证明返回其他身份")
    if any(line.startswith("QUERY_ERROR") for line in output):raise ValueError("\n".join(output[1:]))
    if len(output)<3 or not output[1].startswith("proof_integrity "+atom+" "):raise ValueError("证明协议缺少对应目标")
    ordinary=output[-1].split(maxsplit=1)[0]
    result["integrity"]="\n".join(output[1:-1])
    if result["proof"]["results"][0]["status"]!=ordinary:
        raise ValueError("独立 CL 的投影与 PCGM 当前规则不一致；此目标需要原生活动版本证明")
    return result
def lexicon(word):
    # Read candidate sense IDs from the original CL source; verify memberships with the packaged compiler.
    raw=(LEX/"lexicon_core.cl").read_text(encoding="utf8")
    labels=re.findall(r'&\s+\w+\s+label_entry\((zh|en),("(?:[^"\\]|\\.)*"|[\w-]+),(\w+),(\w+)\)',raw)
    value=lambda s:json.loads(s) if s.startswith('"') else s
    ids=sorted({sense for lang,label,sense,_ in labels if value(label).casefold()==word.casefold()})
    if not ids:return [],None
    goals=[f'lexical_sense({lang},{label},{sense})' for lang,label,sense,_ in labels
           if sense in ids and value(label).casefold()==word.casefold()]
    with tempfile.NamedTemporaryFile(dir=STATE,delete=False) as f:
        path=Path(f.name);f.write(("\n".join(dict.fromkeys(goals))+"\n").encode())
    try:proof=json.loads(run(CL,"package-prove",LEX/"lexicon_core.clpkg",LEX_PIN,path))
    finally:path.unlink(missing_ok=True)
    if any(row["status"]!="POSITIVE" for row in proof["results"]):raise ValueError("词条未通过 CL 证明")
    choices=[(i," / ".join(value(label) for lang,label,sense,form in labels if sense==i and form=="preferred")) for i in ids]
    return choices,proof

