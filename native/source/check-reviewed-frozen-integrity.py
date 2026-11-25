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

cl=root/'cl'
with TemporaryDirectory(prefix='pcgm advisory evidence only ') as td:
    d=Path(td); subject=d/'subject.cl'; state=d/'individual'
    subject.write_text(': clue(sym).\n: ready(sym).\nready($x) <- clue($x).\n? ready(alpha).\n')
    rules=d/'world.cl';lock=d/'lock';api=d/'api';pkg=d/'world.clpkg';goal=d/'goals'
    rules.write_text("""module world.
: p(sym).
: alt(sym).
: clue(sym).
clue($x) <- p($x).
clue($x) <- alt($x).
!clue($x) <- !alt($x).
""")
    lock.write_bytes(run(cl,'lock',rules));api.write_bytes(run(cl,'project-api',rules,lock));pkg.write_bytes(run(cl,'project-pack',rules,lock,api))
    package=digest(pkg.read_bytes())
    def make(label,goal_atom,*atoms):
        goal.write_text(goal_atom+'\n')
        journal=d/(label+'.journal')
        data=('x batch seed 0'+''.join(f' ; observe a{i} {a}' for i,a in enumerate(atoms))+'\n').encode()
        assert json.loads(run(cl,'evidence-init',pkg,package,goal,journal,data=data))['ok']
        snapshot=digest(journal.read_bytes())
        frozen=d/(label+'.clef')
        frozen.write_bytes(run(cl,'evidence-freeze',pkg,package,goal,journal,snapshot))
        return frozen,digest(frozen.read_bytes()),package,snapshot
    dirty=make('dirty','clue(alpha)','p(alpha)','!p(alpha)')
    clean=make('clean','clue(alpha)','p(alpha)','!p(alpha)','alt(alpha)')
    negative=make('negative','clue(alpha)','!alt(alpha)')
    conflict=make('conflict','clue(alpha)','p(alpha)','!alt(alpha)')
    foreign=make('foreign','clue(beta)','alt(beta)')
    def review(binary,q,args):
        return json.loads(run(binary,'--frozen-question-integrity',state,q['id'],q['request_sha256'],*args))
    def same(binary,q,raw,integrity,advisory,args):
        report=review(binary,q,args)
        assert (report['cl_proof']['results'][0]['status'],report['cl_integrity']['results'][0][integrity[0]+'_status'],report['clean_signed_advisory'])==(raw,integrity[1],advisory)
        assert report['cl_integrity']==json.loads(run(cl,'evidence-frozen-integrity',*args))
        assert not report['observation_written']
        return report
    with live(alpha,'--init-managed',subject,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,':ask')=='questions_created 1'
        actor.stdout.readline();assert actor.stdout.readline().startswith('questions_end')
        q=receive(state,'question_feed 0 1')['results'][0]
        before=state.read_bytes()
        same(alpha,q,'POSITIVE',('positive','DISPUTED_ANCESTRY'),False,dirty)
        expected=same(alpha,q,'POSITIVE',('positive','CLEAN_WITNESS'),True,clean)
        same(alpha,q,'NEGATIVE',('negative','CLEAN_WITNESS'),True,negative)
        same(alpha,q,'CONFLICT',('positive','DIRECT_DISPUTE'),False,conflict)
        wrong=subprocess.run([alpha,'--frozen-question-integrity',state,q['id'],q['request_sha256'],*foreign],capture_output=True,timeout=15)
        assert wrong.returncode==1 and b'exactly the requested goal' in wrong.stderr
        bad=subprocess.run([alpha,'--frozen-question-integrity',state,q['id'],q['request_sha256'],clean[0],'0'*64,*clean[2:]],capture_output=True,timeout=15)
        assert bad.returncode==1 and b'artifact pin mismatch' in bad.stderr and not bad.stdout
        stale=subprocess.run([alpha,'--frozen-question-integrity',state,q['id'],'0'*64,*clean],capture_output=True,timeout=15)
        assert stale.returncode==1 and b'stale request address' in stale.stderr and not stale.stdout
        assert state.read_bytes()==before and uid==expected['individual']
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        ready=run(beta,'--prepare',state).decode()
        moved=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert moved.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(moved,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        before=state.read_bytes()
        assert review(beta,q,clean)==expected
        assert state.read_bytes()==before and receive(state,'proof ready(alpha)')['results'][0]['status']=='UNKNOWN'
print('PASS: PCGM read-only exact review distinguishes signed support from clean eligibility, refuses wrong goal, matches the CL report and keeps state/identity unchanged after forced restart and A/B.')
