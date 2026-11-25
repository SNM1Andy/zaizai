"""Administrative Windows bridge for the delivered PCGM. All writes require an explicit command."""
import argparse,hashlib,json,msvcrt,os,re,subprocess,threading
from contextlib import nullcontext
from pathlib import Path
from joint25_handoff import exe,guard,invoke,read,require,snapshot,pin,remaining

def token(value):
    require(isinstance(value,str) and value and not any(ch.isspace() or ord(ch)<32 for ch in value),"expected one protocol token");return value
def digest(value):return hashlib.sha256(value.encode("utf8")).hexdigest()
def checkstate(bin_dir,path):
    data=snapshot(exe(bin_dir,"alpha"),path)
    return exe(bin_dir,data["owner"]),data
def work_agenda(bin_dir,path):
    active,s=checkstate(bin_dir,path);obj=read(active,path,"agenda")
    require(obj["actor"]==s["individual"] and obj["schema"]=="pcgm-work-agenda-v1" and not obj["writes_state"],"invalid native agenda")
    return obj
def reasoned_outcome(bin_dir,path,case,goal,since=None):
    require(len(goal.encode("utf8"))<=320 and not any(ch in goal for ch in "\r\n\0"),"goal is too long or contains a line break")
    operation="reasoned_outcome "+token(case)+" "+goal+(" since "+token(since) if since else "")
    active,_=checkstate(bin_dir,path);return read(active,path,operation)
def resident(bin_dir,path,frame,approved=False):
    """Inherited independent Windows pipe: the executable checks pipe type, read privileges and identity."""
    require("\r" not in frame and "\n" not in frame and len(frame.encode())<=1024,"invalid frame length")
    active,s=checkstate(bin_dir,path)
    r,w=os.pipe();h=msvcrt.get_osfhandle(r);saved=os.get_handle_inheritable(h);proc=None
    try:
        info=subprocess.STARTUPINFO();info.lpAttributeList={"handle_list":[h]}
        os.set_handle_inheritable(h,True)
        try:proc=subprocess.Popen([active,"--resume-agenda-local",path,str(h)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE,startupinfo=info,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
        finally:os.set_handle_inheritable(h,saved)
        os.close(r);r=None
        if approved:os.write(w,(frame+"\n").encode())
        os.close(w);w=None
        try:raw,why=proc.communicate(input=b"" if approved else (frame+"\n").encode(),timeout=remaining())
        except subprocess.TimeoutExpired as exc:raise TimeoutError("原生管道超时，先核对原请求") from exc
        require(proc.returncode==0,why.decode("utf8","replace")[:220]);records=[json.loads(line) for line in raw.splitlines()]
        require(len(records)==2 and records[0]["actor"]==s["individual"] and records[1]["channel"]==("approval" if approved else "read"),"unexpected resident reply")
        require(records[1]["ok"],records[1].get("error","native refusal"));return records[1]["payload"]
    finally:
        for f in (r,w):
            if f is not None:os.close(f)
        if proc is not None and proc.poll() is None:proc.kill();proc.communicate()
def review_repair(bin_dir,path):
    active,s=checkstate(bin_dir,path)
    lines=invoke(active,["--resume",path],b":repair_compare\n").splitlines()
    proposals=[json.loads(line) for line in lines if line.startswith("{")]
    require(len(proposals)==1 and not proposals[0].get("writes_state"),"native repair preview did not return one read-only proposal")
    return {"actor":s["individual"],"head":s["head"],"review_sha256":pin(proposals[0]),"review":proposals[0]}
def execute(args,*,host_locked=False):
    state=args.state.resolve(strict=True);b=args.bin.resolve(strict=True);op=args.op
    if op=="agenda":return work_agenda(b,state)
    if op=="outcome":return reasoned_outcome(b,state,args.case,args.goal,args.since)
    with (nullcontext() if host_locked else guard(state)):
        active,s=checkstate(b,state)
        if op=="repair-preview":return review_repair(b,state)
        require(args.actor==s["individual"],"unexpected native individual")
        if op in ("enroll","enrollment-receipt"):
            approval=digest("PCGM-LOCAL-AGENDA-APPROVAL-1\n"+args.actor+"\n"+token(args.head)+"\n"+token(args.review)+"\n")
            frame=" ".join(("enroll_agenda" if op=="enroll" else "agenda_receipt",args.actor,args.head,args.review,approval))
            if op=="enroll":
                require(args.apply,"explicit local approval required")
                # The engine validates current head for a new write and returns the original
                # ticket for an exact duplicate approval at its historical head.
            return resident(b,state,frame,op=="enroll")
        if op=="answer-receipt":
            return resident(b,state," ".join(map(token,("answer_receipt",args.actor,args.ticket,args.request_pin,args.artifact,args.package,args.snap,args.proof))))
        require(args.apply and args.head==s["head"],"explicit approval and fresh head required")
        if op=="answer":
            return resident(b,state," ".join(map(token,("answer",args.actor,args.head,args.ticket,args.request_pin,args.member,args.artifact,args.package,args.snap,args.proof))),True)
        if op in ("repair-apply","withdraw"):
            # Acquire the native writer lock as well. Direct engine callers are not required to use
            # the host writer.guard; checking a head before acquiring the native lock would race them.
            with subprocess.Popen([active,"--resume",state],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW) as proc:
                timer=threading.Timer(remaining(),lambda:proc.kill() if proc.poll() is None else None);timer.daemon=True;timer.start()
                def issue(line):
                    proc.stdin.write((line+"\n").encode());proc.stdin.flush()
                    response=proc.stdout.readline(2097153).decode("utf8").strip()
                    require(response and len(response.encode())<=2097152 and not response.startswith("QUERY_ERROR"),response[:240])
                    return response
                try:
                    hello=proc.stdout.readline().decode("utf8")
                    require(hello.startswith("individual="+args.actor+" "),"process did not obtain the expected writer")
                    issued=snapshot(active,state);require(issued["head"]==args.head and issued["individual"]==args.actor,"head changed before writer acquisition")
                    if op=="repair-apply":
                        preview=json.loads(issue(":repair_compare"))
                        require(not preview["writes_state"] and pin(preview)==args.review,"frozen comparison changed; inspect the new comparison")
                        return json.loads(issue(":repair_step"))
                    receipt=issue(":withdraw "+token(args.observation))
                    return {"actor":args.actor,"prior_head":args.head,"receipt":receipt,"after_head":snapshot(active,state)["head"]}
                finally:
                    if proc.stdin and not proc.stdin.closed:proc.stdin.close()
                    try:proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                    timer.cancel()
        raise ValueError("unsupported operation")
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--bin",type=Path,required=True);p.add_argument("--state",type=Path,required=True)
    subs=p.add_subparsers(dest="op",required=True)
    subs.add_parser("agenda");q=subs.add_parser("outcome");q.add_argument("case");q.add_argument("goal");q.add_argument("--since")
    subs.add_parser("repair-preview")
    for name in ("enroll","enrollment-receipt","answer","answer-receipt","repair-apply","withdraw"):
        q=subs.add_parser(name);q.add_argument("--actor",required=True)
        if name!="answer-receipt":q.add_argument("--head",required=True)
        if name in ("enroll","enrollment-receipt","repair-apply"):q.add_argument("--review",required=True)
        if name in ("answer","answer-receipt"):
            for arg in ("ticket","request-pin","artifact","package","snap","proof"):q.add_argument("--"+arg,required=True)
        if name=="answer":q.add_argument("--member",required=True)
        if name=="withdraw":q.add_argument("--observation",required=True)
        if name in ("enroll","answer","repair-apply","withdraw"):q.add_argument("--apply",action="store_true")
    result=execute(p.parse_args());print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

