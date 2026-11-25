from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import re
import signal
import subprocess
import time

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
env={'PATH':'','LC_ALL':'C'}
def h(x):return sha256(x.encode() if isinstance(x,str) else x).hexdigest()
def call(exe,*args,input=None,code=0,cwd=None):
    p=subprocess.run([exe,*args],input=input,env=env,cwd=cwd,capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stdout[:400],p.stderr[:800])
    return p
@contextmanager
def live(exe,*args,cwd=None):
    with subprocess.Popen([exe,*args],env=env,cwd=cwd,stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill()
            p.wait(timeout=5)
def raw(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
def ask(p,s):
    raw(p,s);row=p.stdout.readline().strip()
    assert row,(p.poll(),s)
    return row
def key(line,name):
    return re.search(fr'{name}=([a-z0-9]+)',line)[1]
def rechecksum(raw):
    tag,_,body=raw.split(b'\n',2)
    value=14695981039346656037
    for b in body:value=((value^b)*1099511628211)&((1<<64)-1)
    return tag+b'\n'+str(value).encode()+b'\n'+body

with TemporaryDirectory(prefix='PCGM durable local atomic observation batch ') as work:
    d=Path(work);state=d/'state';seed=d/'seed.cl'
    special='"新增 ; 和#标点😀"'
    seed.write_text(''' : input(sym).
: gate(sym).
: pulse(sym).
: later(sym).
& old input(first).
& reserve gate(ready).
& sensor_manual input(protected).
pulse(now) <- input(first).
!pulse(now) <- input('''+special+''').
| hard positive gate(ready).
| wish positive pulse(now).
'''.lstrip(),encoding='utf-8')
    def get(operation,ok=True,engine=alpha):
        r=json.loads(call(engine,'--read-channel',state,cwd=d,input=('q '+operation+'\n').encode()).stdout)
        assert r['ok']==ok,(operation,r)
        return r['payload' if ok else 'error']
    def logical(engine=alpha):
        return get('storage',engine=engine)['logical_sha256']
    def receipt(batch,raw,ok=True,engine=alpha):
        return get(f'observation_batch {batch} {h(raw)}',ok,engine)
    def cut(actor):
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--init-managed',seed,state,cwd=d) as a:
        who=key(a.stdout.readline(),'individual')
        assert ask(a,'pulse(now)').startswith('POSITIVE')
        wat=ask(a,':watch revision pulse(now)')
        assert wat.startswith('watch'),wat
        assert 'withdrawn reserve' in ask(a,':withdraw reserve')
        basis=logical()
        before=state.read_bytes()
        missing=f':observation_batch absent {basis} ; observe valid input(one)'
        assert receipt('absent',missing)['status']=='not_recorded'
        rejected=[
            (f':observation_batch bad {basis} ; observe valid input(one) ; withdraw missing','unknown, imported'),
            (f':observation_batch bad {basis} ; observe valid input(one) ; observe bad input(42)','type mismatch'),
            (f':observation_batch bad {basis} ; withdraw old ; restore old','distinct ordinary'),
            (f':observation_batch bad {basis} ; withdraw sensor_manual','distinct ordinary'),
            (f':observation_batch bad {basis} ; restore old','make no change'),
            (f':observation_batch bad {basis} ; observe old input(other)','replace or reuse'),
            (f':observation_batch bad {basis} ; observe x non_declared(problem)','predicate not declared'),
            (f':observation_batch bad {"0"*64} ; withdraw old','base SHA-256'),
            (f':observation_batch bad {basis} ; observe okay input($not_ground)','must be ground'),
            (f':observation_batch bad {basis}'+''.join(f' ; observe r{i} later(a{i})' for i in range(9)),'operation or count')
        ]
        for attempt,error in rejected:
            response=ask(a,attempt)
            assert response.startswith('QUERY_ERROR') and error in response,(attempt,response)
            assert state.read_bytes()==before
        assert receipt('bad',rejected[0][0])['status']=='not_recorded'
        assert ask(a,'input(one)').startswith('UNKNOWN') and ask(a,'pulse(now)').startswith('POSITIVE')
        command=f':observation_batch swap {basis} ; observe replacement input({special}) ; withdraw old ; restore reserve'
        # Stop before invocation; no evidence is written.
        os.kill(a.pid,signal.SIGSTOP)
        cut(a)
        assert state.read_bytes()==before
    with live(alpha,'--resume',state,cwd=d) as a:
        assert key(a.stdout.readline(),'individual')==who
        assert receipt('swap',command)['status']=='not_recorded'
        # Submit but deliberately do not read the acknowledgement. Wait for actual
        # state publication, terminate, and reconcile through a separate reader.
        raw(a,command)
        deadline=time.monotonic()+5
        while state.read_bytes()==before:
            assert time.monotonic()<deadline and a.poll() is None
            time.sleep(.002)
        cut(a)
    after=state.read_bytes()
    committed=receipt('swap',command)
    assert committed=={'schema':'pcgm-observation-batch-v1','id':'swap','individual':who,
        'request_sha256':h(command),'status':'committed','basis_sha256':basis,'event':7,
        'observation_version':4,'edits':3},committed
    assert state.read_bytes()==after
    watched=get('notices 0 revision')['results']
    assert len(watched)==1 and watched[0]['before']=='POSITIVE' and watched[0]['after']=='NEGATIVE',watched
    assert get('proof pulse(now)')['results'][0]['status']=='NEGATIVE'
    assert get('proof gate(ready)')['results'][0]['status']=='POSITIVE'

    # Integrity: ordinary journal and separately pinned batch metadata must agree.
    malformed=d/'malformed'
    malformed.write_bytes(rechecksum(after.replace(b'withdraw old\n',b'withdraw reserve\n',1)))
    refused=call(alpha,'--resume',malformed,cwd=d,code=1)
    assert b'batch edit order' in refused.stderr,refused.stderr
    # A typed, parseable replacement of the same observation ID must also be rejected.
    lines=after.splitlines(keepends=True)
    lines=[b'& replacement input(forged).\n' if x.startswith(b'& replacement ') else x for x in lines]
    malformed.write_bytes(rechecksum(b''.join(lines)))
    refused=call(alpha,'--resume',malformed,cwd=d,code=1)
    assert b'batch differs from its source fact' in refused.stderr,refused.stderr

    with live(alpha,'--resume',state,cwd=d) as a:
        assert key(a.stdout.readline(),'individual')==who
        assert json.loads(ask(a,command))=={**committed,'status':'already_applied'}
        assert state.read_bytes()==after
        changed=command.replace('restore reserve','withdraw reserve')
        assert 'different request bytes' in ask(a,changed)
        assert 'different request bytes' in receipt('swap',changed,ok=False)
        for n in range(132):
            assert f'observed noise{n}' in ask(a,f':observe noise{n} later(n{n})')
        assert ask(a,':seal_history '+logical()).startswith('archive_sealed')
        compact_head=logical()
        assert ask(a,':compact_state '+compact_head).startswith('state_representation compact')
        assert state.read_bytes().startswith(b'PCGM-COMPACT-1\n')
        assert receipt('swap',command)==committed
        assert logical()==compact_head
        wrong=f':observation_batch wrong {h(state.read_bytes())} ; withdraw replacement'
        assert 'base SHA-256' in ask(a,wrong)
        decision=json.loads(ask(a,':choice_job_start'))['id']
        new=f':observation_batch keep {compact_head} ; observe following later(continuous)'
        live_commit=json.loads(ask(a,new))
        assert receipt('keep',new)==live_commit and live_commit['status']=='committed'
        written=state.read_bytes()
        assert 'job is stale' in ask(a,':choice_job_commit_explained '+decision)
        assert state.read_bytes()==written
        assert json.loads(ask(a,':choice_job_cancel '+decision))['id']==decision
        prepared=call(beta,'--prepare',state,cwd=d).stdout.decode()
        hand=ask(a,':handoff beta '+key(prepared,'binary_sha256')+' '+key(prepared,'snapshot_sha256'))
        assert hand.startswith('handoff_prepared') and a.wait(timeout=8)==0
    with live(beta,'--claim',state,key(hand,'nonce'),cwd=d) as b:
        assert key(b.stdout.readline(),'individual')==who
        before_retry=state.read_bytes()
        assert json.loads(ask(b,new))=={**live_commit,'status':'already_applied'}
        assert json.loads(ask(b,command))=={**committed,'status':'already_applied'}
        assert receipt('swap',command,engine=beta)==committed and receipt('keep',new,engine=beta)==live_commit
        assert state.read_bytes()==before_retry
        assert ask(b,'pulse(now)').startswith('NEGATIVE') and ask(b,'later(continuous)').startswith('POSITIVE')
        cut(b)
    assert receipt('swap',command,engine=beta)==committed
print('PASS: native PCGM commits mixed local observation corrections in one state, publishes no intermediate conflict, reconciles unread receipts after hard stops and A/B, refuses partial/stale/corrupt input, and retains full proof after compaction.')
