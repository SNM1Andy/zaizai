from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import re
import subprocess

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
def parse(line,key):
    return re.search(fr'{key}=(\w+)',line)[1]
def digest(data):
    return sha256(data).hexdigest()
def run(exe,*args,data=b'',code=0):
    p=subprocess.run([exe,*args],input=data,capture_output=True,timeout=15)
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:400])
    return p.stdout
@contextmanager
def live(exe,*args):
    with subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:
                p.kill();p.wait(timeout=5)
def issue(p,cmd):
    p.stdin.write(cmd+'\n');p.stdin.flush()
    result=p.stdout.readline().strip()
    assert result,(cmd,p.poll())
    return result
def receive(state,cmd,ok=True,endpoint=None):
    if endpoint:
        raw=run(alpha,'--fifo-query',endpoint,'1',cmd,code=0 if ok else 2)
    else:
        raw=run(alpha,'--read-channel',state,data=('one '+cmd+'\n').encode())
    wire=json.loads(raw)
    assert wire['ok']==ok,wire
    return wire['payload'] if ok else wire['error']
def write_packet(folder,name,uid,question,source,fact,sha=None):
    pin=sha or question['request_sha256']
    raw=f"PCGM_ANSWER_1 {uid} {question['id']} {source} {pin}\n{fact}\n".encode()
    packet=folder/(name+'.answer')
    packet.write_bytes(raw)
    return digest(raw)

cl=root/'cl'
with TemporaryDirectory(prefix='native PCGM question independent CL review ') as td:
    d=Path(td);inbox=d/'incoming';inbox.mkdir()
    source=d/'questions.cl'
    source.write_text("""
: clearance(sym).
: granted(sym).
: audit(sym).
granted($x) <- clearance($x).
? granted(alpha).
""")
    state=d/'individual'
    def pack(name,*facts):
        src=d/(name+'.cl');lock=d/(name+'.lock');api=d/(name+'.clapi')
        src.write_text(f"module {name}.\n: clearance(sym).\n: extra(sym).\n"+''.join(f'& e{i} {atom}.\n' for i,atom in enumerate(facts)))
        lock.write_bytes(run(cl,'lock',src))
        api.write_bytes(run(cl,'project-api',src,lock))
        pkg=d/(name+'.clpkg');pkg.write_bytes(run(cl,'project-pack',src,lock,api))
        for f in (src,lock,api):f.unlink()
        return pkg,digest(pkg.read_bytes())
    supported=pack('positive','clearance(alpha)','extra(detail)')
    opposed=pack('negative','!clearance(alpha)')
    conflicted=pack('both','clearance(alpha)','!clearance(alpha)')
    undetermined=pack('none','clearance(beta)')
    def review(actor,part,code=0,error=b'',req=None,target=state,limits=()):
        args=[actor,'--question-bundle-review',target,ticket,req if req is not None else request,*part,*limits]
        p=subprocess.run(args,capture_output=True,timeout=15)
        assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:400])
        if code:
            assert not p.stdout and error in p.stderr,(p.args,p)
            return None
        return json.loads(p.stdout)
    with live(alpha,'--init-managed',source,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,':ask')=='questions_created 1'
        assert actor.stdout.readline().startswith('question ')
        assert 'questions_end' in actor.stdout.readline()
        q=receive(state,'question_feed 0 1')['results'][0]
        ticket,request=q['id'],q['request_sha256']
        before=state.read_bytes()
        for pair,verdict in [(supported,'POSITIVE'),(opposed,'NEGATIVE'),(conflicted,'CONFLICT'),(undetermined,'UNKNOWN')]:
            reply=review(alpha,pair)
            assert reply['observation_written'] is False and reply['individual']==uid and reply['question']==ticket
            assert reply['revision_sha256']==digest(before) and reply['request_sha256']==request
            goals=d/'goals';goals.write_text('clearance(alpha)\n')
            assert reply['cl_proof']==json.loads(run(cl,'package-prove',*pair,goals))
            assert reply['cl_proof']['results'][0]['status']==verdict
        assert before==state.read_bytes()
        assert receive(state,'proof granted(alpha)')['results'][0]['status']=='UNKNOWN'
        review(alpha,(supported[0],opposed[1]),code=1,error=b'package does not match')
        review(alpha,supported,code=1,error=b'fact limit',limits=('128','1','2000000','2000000'))
        review(alpha,supported,code=1,error=b'no longer open',req='0'*64)
        bad=d/'truncated';bad.write_bytes(supported[0].read_bytes()[:-1])
        review(alpha,(bad,digest(bad.read_bytes())),code=1,error=b'digest mismatch')
        other=d/'other_state'
        assert run(alpha,'--init-managed',source,other,data=b':ask\n')
        review(alpha,supported,code=1,error=b'no longer open',target=other)
        assert state.read_bytes()==before
        assert issue(actor,':observe ext audit(kept)').startswith('observation_version')
        buffered=review(alpha,supported)
        assert buffered['revision_sha256']!=digest(before) and buffered['request_sha256']==request
        prep=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(prep,'binary_sha256')+' '+parse(prep,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        check=review(beta,supported)
        assert check['cl_proof']==buffered['cl_proof'] and check['revision_sha256']!=buffered['revision_sha256']
        assert check['request_sha256']==request and check['observation_written'] is False
        write_packet(inbox,'manual',uid,q,'local','clearance(alpha)')
        assert issue(actor,':answer_packet manual').startswith('answer_packet_committed')
        review(beta,supported,code=1,error=b'no longer open')
print('PASS: PCGM native read-only review independently recomputes CL positive, negative, conflict and unknown results, does not admit evidence, and survives handoff while stale/over-budget packages refuse.')
