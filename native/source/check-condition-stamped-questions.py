from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, re, subprocess

root=Path(__file__).resolve().parent
cl,alpha,beta=root/'cl',root/'pcgm-alpha',root/'pcgm-beta'
def h(p):return sha256(p.read_bytes()).hexdigest()
def put(path,data):path.write_bytes(data if isinstance(data,bytes) else data.encode());return path
def call(tool,*args,data=None):
    p=subprocess.run([tool,*args],input=data,capture_output=True,timeout=20)
    assert p.returncode==0,(p.args,p.returncode,p.stderr,p.stdout)
    return p.stdout
@contextmanager
def live(tool,*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def ask(p,s):
    p.stdin.write(s+'\n');p.stdin.flush();line=p.stdout.readline().strip()
    assert line,(s,p.poll())
    return line
def observe(p,n=1):
    assert ask(p,':ask')=='questions_created '+str(n)
    while True:
        line=p.stdout.readline()
        assert line
        if line.startswith('questions_end'):return
def get(state,request):
    reply=json.loads(call(alpha,'--read-channel',state,data=('c '+request+'\n').encode()))
    assert reply['ok'],reply
    return reply['payload']
def token(s,key):return re.search(fr'{key}=([a-z0-9]+)',s)[1]
def package(inbox,name,fact,relation):
    src=put(inbox/(name+'.cl'),f'module {name}.\n: {relation}(sym).\n& anchored {fact}.\n')
    lock=put(src.with_suffix('.lock'),call(cl,'lock',src))
    api=put(src.with_suffix('.api'),call(cl,'project-api',src,lock))
    out=put(src.with_suffix('.clpkg'),call(cl,'project-pack',src,lock,api))
    for x in (src,lock,api):x.unlink()
    return out
def review(state,q,payload):
    return json.loads(call(alpha,'--question-bundle-review',state,q['id'],q['request_sha256'],payload,h(payload)))
def admit(actor,q,path,record):
    return ask(actor,f":admit_cl {q['id']} {q['request_sha256']} {path.stem} {h(path)} {record}")
with TemporaryDirectory(prefix='native PCGM choice criteria independent evidence ') as tmp:
    root_work=Path(tmp);inbox=root_work/'incoming';inbox.mkdir()
    script=''': signed_gate(sym).
: submitted(sym).
: dormant(sym).
: permit(sym).
: goal(sym).
: closed(sym).
: never(sym).
: closed_negative(sym).
& ready stable(yes).
permit(ready) <- signed_gate(check).
goal(verified) <- submitted(record).
never(open) <- dormant(unsolicited).
!closed(off).
| hard positive stable(yes).
| wish positive goal(verified) when permit(ready).
| wish positive never(open) when closed(off).
| wish positive never(open) when !closed_negative(no).
'''
    ordinary=put(root_work/'old.cl',script)
    with live(alpha,'--init',ordinary,root_work/'ordinary') as a:
        a.stdout.readline()
        observe(a,0)
    main=put(root_work/'actor.cl',script+'? criteria.\n')
    state=root_work/'actor'
    gate=package(inbox,'gate','signed_gate(check)','signed_gate')
    objective=package(inbox,'submission','submitted(record)','submitted')
    with live(alpha,'--init-managed',main,state) as p:
        who=token(p.stdout.readline(),'individual')
        observe(p)
        questions=get(state,'question_feed 0 16')['results']
        assert len(questions)==1 and questions[0]['origin']=='decision_guard',questions
        first=questions[0]
        assert first['status']=='open' and first['needed']['predicate']=='signed_gate'
        observe(p,0);assert get(state,'question_feed 0 16')['results']==questions
        old=h(state)
        proof=review(state,first,gate)
        assert proof['observation_written'] is False and h(state)==old
        assert proof['cl_proof']['results'][0]['status']=='POSITIVE'
        assert 'does not match reviewed proof' in admit(p,first,gate,'0'*64)
        assert h(state)==old
        response=admit(p,first,gate,proof['proof_sha256'])
        assert response.startswith('cl_evidence_committed')
        guard_obs=response.split()[2]
        observe(p)
        questions=get(state,'question_feed 0 16')['results']
        assert len(questions)==2 and questions[0]['status']=='answered',questions
        second=questions[1]
        assert second['origin']=='decision_goal' and second['needed']['predicate']=='submitted'
        drafted=review(state,second,objective)
        assert 'withdrawn' in ask(p,':withdraw '+guard_obs)
        old=h(state)
        assert 'no longer open' in admit(p,second,objective,drafted['proof_sha256']) and h(state)==old
        assert get(state,'question '+second['id'])['results'][0]['status']=='superseded'
        assert 'restored' in ask(p,':restore '+guard_obs)
        assert get(state,'question '+second['id'])['results'][0]['request_sha256']==second['request_sha256']
        assert 'observed noise' in ask(p,':observe noise dormant(unrelated)')
        assert get(state,'question '+second['id'])['results'][0]['request_sha256']==second['request_sha256']
        assert 'observed standin' in ask(p,':observe standin signed_gate(check)')
        assert 'withdrawn' in ask(p,':withdraw '+guard_obs)
        assert 'POSITIVE' in ask(p,'permit(ready)')
        changed=get(state,'question '+second['id'])['results'][0]
        assert changed['id']==second['id'] and changed['status']=='open'
        assert changed['condition_context_sha256']!=second['condition_context_sha256']
        assert changed['request_sha256']!=second['request_sha256']
        clean=h(state)
        assert 'no longer open' in admit(p,second,objective,drafted['proof_sha256']) and h(state)==clean
        refreshed=review(state,changed,objective)
        assert refreshed['proof_sha256']==drafted['proof_sha256']
        observe(p,0)
        assert admit(p,changed,objective,refreshed['proof_sha256']).startswith('cl_evidence_committed')
        current=get(state,'question_feed 0 16')['results']
        assert [item['status'] for item in current]==['answered','answered']
        assert current[0]['evidence'][0]['cl_proof_sha256']==proof['proof_sha256']
        assert current[1]['evidence'][0]['cl_proof_sha256']==drafted['proof_sha256']
        assert b'\ndecision ' not in state.read_bytes() and 'POSITIVE' in ask(p,'goal(verified)')
        p.kill();assert p.wait(timeout=5)<0
    with live(alpha,'--resume',state) as p:
        assert token(p.stdout.readline(),'individual')==who
        assert get(state,'question_feed 0 16')['results']==current
        ready=call(beta,'--prepare',state).decode()
        swap=ask(p,':handoff beta '+token(ready,'binary_sha256')+' '+token(ready,'snapshot_sha256'))
        assert swap.startswith('handoff_prepared') and p.wait(timeout=10)==0
    with live(beta,'--claim',state,token(swap,'nonce')) as p:
        assert token(p.stdout.readline(),'individual')==who
        assert get(state,'question_feed 0 16')['results']==current
        observe(p,0)
print('PASS: a true PCGM decision guard with a different actual witness rotates a durable ticket address, an unrelated observation does not, and the same CL proof is only accepted after fresh context verification, surviving restart and A/B.')
