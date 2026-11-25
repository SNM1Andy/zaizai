"""Job-external CLI and fixed local JSON subprocess transport. Never imports Runtime."""
import hashlib
import json
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

COMMANDS = {"列出目录": "LIST_SCOPE", "读取 question-1.txt": "READ_TEXT"}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

class NotConnected:
    def snapshot(self):
        return dict(identity=None, instance=None, revision=None, stage="NOT_CONNECTED", receipts=[])
    def propose(self, operation):
        return None
    def dispatch(self, proposal):
        raise RuntimeError("NOT_CONNECTED")

def persistent_diagnostic(diag):
    reason=diag.get("reason") or {}
    transport=diag.get("transport_error") or {}
    binding=diag.get("binding") or {}
    return dict(status=diag.get("status"),reason=reason.get("text"),reason_sha256=reason.get("sha256"),
        reason_redacted=reason.get("redacted"),reason_truncated=reason.get("truncated"),
        attempt_id=diag.get("attempt_id"),request_sha256=binding.get("request_sha256"),
        proposal_sha256=binding.get("proposal_sha256"),monotonic_start=diag.get("monotonic_start"),
        monotonic_end=diag.get("monotonic_end"),elapsed=diag.get("elapsed"),
        transport_error_type=diag.get("transport_error_type"),transport_error=transport.get("text"),
        transport_error_sha256=transport.get("sha256"))

class JsonBackend:
    """Fixed local API only. Timeout never kills a live controller or retries it."""
    def __init__(self, source="local_operator_unverified"):
        if source not in ("local_operator_unverified", "COORDINATOR_TEST_CONFIRMATION"):
            raise ValueError("confirmation source")
        self.source=source
        self.path=Path(__file__).with_name("backend_api.py")
        self.pending_processes=[]
    def call(self, request):
        raw=(json.dumps(request,ensure_ascii=False,separators=(",", ":"))+"\n").encode("utf8")
        if len(raw)>65536:raise ValueError("API_INPUT_BOUND")
        p=subprocess.Popen([sys.executable,"-X","utf8","-I","-S","-B",str(self.path)],
            cwd=str(self.path.parent),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        buffers=[bytearray(),bytearray()];overflow=[False,False];io_errors=[]
        def drain(stream,index):
            try:
                while True:
                    data=stream.read(4096)
                    if not data:break
                    room=65536-len(buffers[index])
                    buffers[index].extend(data[:max(0,room)])
                    if len(data)>room:overflow[index]=True
            except Exception:io_errors.append("OUTPUT_IO")
        def feed():
            try:p.stdin.write(raw);p.stdin.close()
            except Exception:io_errors.append("INPUT_IO")
        threads=[threading.Thread(target=drain,args=(p.stdout,0),daemon=True),threading.Thread(target=drain,args=(p.stderr,1),daemon=True),threading.Thread(target=feed,daemon=True)]
        for t in threads:t.start()
        try:p.wait(timeout=90)
        except subprocess.TimeoutExpired:
            self.pending_processes.append((p,threads,buffers))
            raise RuntimeError("API_TIMEOUT_UNKNOWN_NO_KILL_NO_RETRY")
        for t in threads:t.join(timeout=2)
        if any(t.is_alive() for t in threads) or io_errors or any(overflow) or p.returncode!=0 or buffers[1]:
            raise RuntimeError("API_OUTPUT_OR_EXIT_UNCONFIRMED")
        def unique(pairs):
            value=dict(pairs)
            if len(value)!=len(pairs):raise ValueError("API_DUPLICATE_KEY")
            return value
        result=json.loads(bytes(buffers[0]).decode("utf8"),object_pairs_hook=unique)
        if type(result) is not dict:raise ValueError("API_OBJECT_REQUIRED")
        return result
    def snapshot(self):
        r=self.call(dict(op="status"))
        if r.get("status")!="OK" or type(r.get("snapshot")) is not dict:raise ValueError("STATUS_UNCONFIRMED")
        return r["snapshot"]
    def propose(self,operation):
        command=next(k for k,v in COMMANDS.items() if v==operation)
        snapshot=self.snapshot()
        nonce=secrets.token_hex(16)
        r=self.call(dict(op="propose",command=command,state_sha256=digest(snapshot),nonce=nonce))
        p=r.get("proposal")
        if r.get("status")!="CANDIDATE" or type(p) is not dict or r.get("proposal_sha256")!=digest(p) or p.get("candidate_nonce")!=nonce:return None
        return p
    def dispatch(self,proposal):
        # One shared external attempt gate, before even starting the API process.
        root=str(self.path.parent)
        if root not in sys.path:sys.path.insert(0,root)
        from attempt_gate import reserve_client, record_error
        from cli_diagnostic import evaluate
        request=dict(op="confirm",proposal=proposal,proposal_sha256=digest(proposal),
            confirmation="确认 "+proposal["proposal_id"],confirmation_source=self.source)
        started=time.monotonic();attempt=None;response=None;error=None
        try:
            attempt=reserve_client(request)
            if (type(attempt) is not dict or not attempt.get("attempt_id")
                or attempt.get("request_sha256")!=digest(request)):
                raise RuntimeError("ATTEMPT_BINDING_UNCONFIRMED")
            response=self.call(dict(request,attempt=attempt))
            if response.get("status")=="VERIFIED" and (
                response.get("attempt_id")!=attempt["attempt_id"]
                or response.get("request_sha256")!=attempt["request_sha256"]):
                raise RuntimeError("RESPONSE_ATTEMPT_BINDING_MISMATCH")
        except Exception as exc:error=exc
        result=evaluate(request,proposal,response,started=started,ended=time.monotonic(),error=error)
        diag=result["diagnostic"]
        diag["attempt_id"]=attempt.get("attempt_id") if type(attempt) is dict else None
        diag["attempt_request_sha256"]=attempt.get("request_sha256") if type(attempt) is dict else None
        if not diag["success"]:
            if attempt is not None:
                try:diag["error_record"]=record_error(attempt,persistent_diagnostic(diag),actor="client")
                except Exception as exc:diag["error_record_failed"]=type(exc).__name__[:80]
            return dict(status="UNKNOWN",reason="BACKEND_NOT_VERIFIED",diagnostic=diag,retry=False)
        response=dict(response);response["diagnostic"]=diag
        return response

class Shell:
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else NotConnected()
        self.pending = None
        self.held = False
    def handle(self, text):
        # Exact syntax only. No normalization, path parsing, inferred consent or shell evaluation.
        if type(text) is not str or len(text.encode("utf8")) > 256:
            self.pending = None
            return dict(status="REFUSED", reason="INPUT_BOUND")
        if text == "退出":
            self.pending = None
            return dict(status="EXIT")
        if text == "取消":
            self.pending = None
            return dict(status="CANCELLED", executed=False)
        if text in ("状态", "回执"):
            return dict(status="STATE" if text == "状态" else "RECEIPTS", snapshot=self.backend.snapshot(), held=self.held)
        if text.startswith("确认 "):
            p = self.pending
            self.pending = None  # Wrong/replayed confirmation also consumes this UI candidate.
            if self.held or p is None or text != "确认 " + p["token"]:
                return dict(status="REFUSED", reason="EXACT_CURRENT_CONFIRMATION_REQUIRED")
            if digest(self.backend.snapshot()) != p["snapshot_sha256"]:
                return dict(status="HOLD", reason="STATE_CHANGED", executed=False)
            # Once the handoff starts its outcome can be unknown. UI must never auto-retry.
            self.held = True
            try:
                result = self.backend.dispatch(p["proposal"])
            except Exception:
                return dict(status="UNKNOWN", reason="DISPATCH_NOT_CONFIRMED", retry=False)
            if (type(result) is not dict or result.get("status") != "VERIFIED"
                or type(result.get("receipt_ref")) is not str or not result["receipt_ref"]
                or result.get("source") != "APPLICATION_BROKER_CAPTURE"
                or any(result.get(k) != p["proposal"].get(k) for k in ("operation","identity","instance"))
                or result.get("proposal_sha256") != digest(p["proposal"])):
                return dict(status="UNKNOWN", reason="NO_VERIFIED_RECEIPT", retry=False,
                    diagnostic=result.get("diagnostic") if type(result) is dict else None)
            self.held = False
            return dict(status="RESULT", evidence=result)
        self.pending = None
        if text not in COMMANDS:
            return dict(status="CLARIFY", supported=list(COMMANDS), executed=False)
        if self.held:
            return dict(status="HOLD", reason="UNRESOLVED_HANDOFF", executed=False)
        snapshot = self.backend.snapshot()
        if snapshot["stage"] == "NOT_CONNECTED":
            return dict(status="HOLD", reason="LIVE_BACKEND_NOT_CONNECTED", executed=False)
        operation = COMMANDS[text]
        expected = {"READY_LIST":"LIST_SCOPE", "LIST_VERIFIED":"READ_TEXT"}.get(snapshot["stage"])
        if operation != expected:
            return dict(status="REFUSED", reason="ALREADY_EXECUTED_OR_WRONG_STAGE", executed=False)
        proposal = self.backend.propose(operation)
        if (type(proposal) is not dict or proposal.get("operation") != operation
            or any(proposal.get(k)!=snapshot.get(k) for k in ("identity","instance"))
            or proposal.get("state_sha256")!=digest(snapshot)
            or type(proposal.get("proposal_id")) is not str or not proposal["proposal_id"]
            or len(proposal["proposal_id"])>128):
            return dict(status="HOLD", reason="NO_MATCHING_NATIVE_PROPOSAL", executed=False)
        if digest(self.backend.snapshot()) != digest(snapshot):
            return dict(status="HOLD", reason="PROPOSAL_CHANGED_STATE", executed=False)
        token=proposal["proposal_id"]
        self.pending=dict(proposal=proposal, snapshot_sha256=digest(snapshot), token=token)
        return dict(status="CANDIDATE", command=text, proposal=proposal, identity=snapshot["identity"],
                    confirmation="确认 "+token, executed=False)

def readable(result):
    status=result.get("status")
    if status=="CANDIDATE":
        p=result["proposal"]
        return "候选："+result["command"]+"\n身份："+str(result["identity"])+"\n尚未执行。确认请输入："+result["confirmation"]+"；放弃请输入：取消"
    if status=="RESULT":
        e=result["evidence"];d=e.get("display",{})
        title="真实 Broker 结果（准备的本地工程输入，非第一手自主经验）"
        if d.get("kind")=="LIST_SCOPE" and type(d.get("entries")) is list:
            lines=[str(x.get("name",x.get("relative_path","")))+" ["+str(x.get("kind",""))+"]" for x in d["entries"] if type(x) is dict]
            return title+"\n"+"\n".join(lines)
        if d.get("kind")=="READ_TEXT" and type(d.get("text")) is str:
            return title+"\n"+str(d.get("name","question-1.txt"))+"：\n"+d["text"]
        return title+"\n回执已绑定，但后端未提供可读正文；请核验机器证据，不能猜测内容。"
    if status in ("STATE","RECEIPTS"):
        s=result["snapshot"]
        return "身份："+str(s.get("identity"))+"\n阶段："+str(s.get("stage"))+"；版本："+str(s.get("revision"))+"\n已记录回执："+str(len(s.get("receipts",[])))
    if status=="UNKNOWN" and type(result.get("diagnostic")) is dict:
        d=result["diagnostic"];reason=d.get("reason") or d.get("transport_error") or {}
        return "执行结果未知，禁止重发。后端状态："+str(d.get("status"))+"\n诊断："+str(reason.get("text","未提供原因"))+"\n尝试ID："+str(d.get("attempt_id"))
    return {"CANCELLED":"已取消，未提交业务。","EXIT":"已退出。","CLARIFY":"不支持或语义不明确；仅支持列出目录、读取 question-1.txt。","REFUSED":"已拒绝，不能重复执行或跳过阶段。","HOLD":"暂停：准入或状态尚未确认，不会自动重试。","UNKNOWN":"执行结果未知，已禁止自动重发；请保留现场核验。"}.get(status,str(status))

def main():
    shell=Shell(JsonBackend() if Path(__file__).with_name("backend_api.py").is_file() else None)
    print("再再本地交互：状态 / 回执 / 列出目录 / 读取 question-1.txt / 取消 / 退出。候选不执行；输入完整确认短语后才提交。")
    while True:
        try: line=input("> ")
        except EOFError: break
        try: result=shell.handle(line)
        except Exception:
            shell.pending=None
            shell.held=True
            result=dict(status="HOLD",reason="BACKEND_UNCONFIRMED_NO_RETRY")
        print(readable(result))
        print("机器证据："+json.dumps(result,ensure_ascii=False,sort_keys=True))
        if result["status"]=="EXIT": break

if __name__ == "__main__": main()
