"""One bounded JSON request per audited local provider process."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

MAX_OUTPUT=2*1024*1024
def exchange(root,m,port,payload,iv,budget):
    script=(root/m["entry"]).resolve(strict=True)
    directory=(root/"slot-providers"/m["id"]).resolve(strict=True)
    if script.parent!=directory or script.name!="provider.py":raise ValueError("发行件入口位置异常")
    frame={"interface_version":"zaizai.slots/1","slot":m["slot"],"port":port,"adapter":m["id"],"version":m["version"],
           "input_version":iv,"budget_ms":budget,"input":payload}
    wire=json.dumps(frame,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()+b"\n"
    # Only explicitly registered local code can be loaded. No capture of shell syntax or host credentials.
    env={k:os.environ[k] for k in ("SYSTEMROOT","WINDIR","TEMP","TMP") if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="zaizai-slot-call-") as work:
        proc=subprocess.Popen([sys.executable,"-I","-S","-B","-X","utf8",script],cwd=work,env=env,
             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        data=bytearray();oversize=threading.Event()
        def read():
            try:
                while True:
                    buf=proc.stdout.read(16384)
                    if not buf:break
                    if len(data)+len(buf)>MAX_OUTPUT:
                        oversize.set()
                        try:proc.kill()
                        except OSError:pass
                        return
                    data.extend(buf)
            finally:proc.stdout.close()
        def send():
            try:proc.stdin.write(wire);proc.stdin.flush()
            except (BrokenPipeError,OSError):pass
            finally:proc.stdin.close()
        reader=threading.Thread(target=read,daemon=True);writer=threading.Thread(target=send,daemon=True)
        reader.start();writer.start()
        try:proc.wait(timeout=max(1,budget)/1000)
        except subprocess.TimeoutExpired as exc:
            proc.kill();proc.wait(timeout=2);raise TimeoutError("槽件超过宿主时限") from exc
        finally:reader.join(1);writer.join(1)
        if oversize.is_set():raise ValueError("槽件输出超过宿主配额")
        if proc.returncode:raise RuntimeError(f"{port} 槽件退出码 {proc.returncode}")
    answer=json.loads(bytes(data).decode("utf8"))
    expected={k:frame[k] for k in ("interface_version","slot","adapter","version","port","input_version")}
    if not isinstance(answer,dict) or any(answer.get(k)!=v for k,v in expected.items()):raise ValueError("响应协议、槽件或输入版本与请求不符")
    if "output" not in answer or "sources" not in answer:raise ValueError("返回缺少输出或来源")
    return answer

def read_release(root,aid):
    from slots31 import ABI,PORTS,BUILTIN,hash_json
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,59}",aid) or aid in BUILTIN or aid=="empty":raise ValueError("发行编号格式不合格")
    base=root/"slot-providers"/aid
    if base.resolve()!=base or not base.is_dir():raise ValueError("槽件发行目录异常")
    file=base/"manifest.json";script=base/"provider.py"
    if file.resolve()!=file or script.resolve()!=script:raise ValueError("发行件存在重定向")
    m=json.loads(file.read_bytes())
    if m.get("id")!=aid or m.get("interface_version")!=ABI or m.get("slot") not in PORTS:raise ValueError("槽件清单与角色不匹配")
    role=m["slot"]
    if set(m.get("capabilities",[]))!=set(PORTS[role]) or len(m["capabilities"])!=len(PORTS[role]):raise ValueError("发行件必须列全本角色契约")
    for key in ("name","version","state_format"):
        if not isinstance(m.get(key),str) or not 0<len(m[key])<=200:raise ValueError("缺少发行件必要字段 "+key)
    if role=="L":
        dom=m["value_domain"]
        if not isinstance(dom,dict) or not {"support","counter","insufficient"}<=dom.keys() or len(set(dom.values()))!=len(dom) or any(not isinstance(v,str) or not v for v in dom.values()):
            raise ValueError("语言状态值域缺少互斥的支持、反证、缺证角色")
    entry=script.relative_to(root).as_posix()
    pin=hashlib.sha256(script.read_bytes()).hexdigest()
    if m.get("artifacts")!={entry:pin} or m.get("entry")!=entry or m.get("provider_type")!="external":raise ValueError("只接受已核验的单文件本地协议提供方")
    cert=root/"evidence/slot31-acceptance"/(aid+".json")
    if not cert.is_file() or cert.resolve()!=cert:raise ValueError("缺少独立的本机换槽验收凭据")
    g=json.loads(cert.read_bytes())
    if (g.get("passed") is not True or g.get("manifest_sha256")!=hash_json(m) or g.get("dialogue_gate") is not True or
        not all(g.get("ports",{}).get(p) is True for p in PORTS[role]) or
        not all(g.get("faults",{}).get(k) is True for k in ("timeout","crash","invalid"))):
        raise ValueError("冻结契约、故障或对话验收与当前发行件不一致")
    return m
def probe(root,m):
    from slots31 import hash_json,_validate
    role=m["slot"];port="L6" if role=="L" else "C9";p={} if role=="L" else {"operation":"describe"}
    v=exchange(root,m,port,p,hash_json(p),2500)
    _validate(port,v["output"],m)
    if not isinstance(v.get("sources"),list) or not v["sources"]:raise ValueError("槽件自检缺少来源")
    return {"passed":True,"port":port,"capabilities":m["capabilities"],"output_sha256":hash_json(v["output"]),"time":time.time()}

