from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess,json,re
home=Path(__file__).resolve().parent
cl,pcgm=home/'cl',home/'pcgm-alpha'
def h(data):return sha256(data).hexdigest()
def run(exe,*args,data=b'',ok=0,wd=None):
    p=subprocess.run([exe,*args],input=data,cwd=wd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=20)
    assert p.returncode==ok,(p.args,p.returncode,p.stdout[:100],p.stderr[:500])
    return p.stdout
@contextmanager
def live(exe,*args,wd=None):
    p=subprocess.Popen([exe,*args],cwd=wd,env={'PATH':'','LC_ALL':'C'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:yield p
    finally:
        if p.poll() is None:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def issue(p,command):
    p.stdin.write(command+'\n');p.stdin.flush()
    ans=p.stdout.readline().strip();assert ans,(command,p.poll());return ans
alpha,beta=home/'pcgm-alpha',home/'pcgm-beta'
def val(row,key):
    return re.search(fr'(?:^| ){key}=([0-9a-z]+)',row)[1]
with TemporaryDirectory(prefix='PCGM live compact journal ') as t:
    d=Path(t);seed=d/'seed.cl';state=d/'state'
    seed.write_text(': observed(sym).\n: tag(sym).\n& initial tag(ok).\n? tag(ok).\n')
    def get(p,request,good=True):
        answer=json.loads(issue(p,request))
        assert answer['ok']==good,answer
        return answer.get('payload',answer.get('error'))
    def logical(reader):return get(reader,'s storage')['logical_sha256']
    with live(alpha,'--init-managed',seed,state,wd=d) as p:
        who=val(p.stdout.readline(),'individual')
        for i in range(132):assert issue(p,f':observe record{i} observed(v{i})').startswith('observation_version')
        assert issue(p,':pin sample').startswith('pin_committed')
        assert issue(p,':chat anchor first focus tag(ok)').startswith('chat_committed')
        saved_reply=p.stdout.readline()
        for _ in range(2):assert issue(p,':seal_history '+h(state.read_bytes())).startswith('archive_sealed')
        original=state.read_bytes()
        with live(alpha,'--read-channel',state,wd=d) as reader:
            whole=get(reader,'r inspect * 0; observed(v131); tag(ok)')
            initial=get(reader,'s storage')
            assert initial['representation']=='materialized' and initial['physical_sha256']==initial['logical_sha256']==h(original)
            assert 'snapshot changed' in issue(p,':compact_state '+'0'*64)
            assert issue(p,':compact_state '+initial['logical_sha256']).startswith('state_representation compact')
            physical=state.read_bytes()
            assert physical.startswith(b'PCGM-COMPACT-1\n') and len(physical)<len(original)
            compact=get(reader,'s storage')
            assert compact['physical_sha256']==h(physical) and compact['logical_sha256']==initial['logical_sha256']
            assert compact['representation']=='compact' and get(reader,'r inspect * 0; observed(v131); tag(ok)')==whole
            assert 'snapshot changed' in issue(p,':materialize_state '+compact['physical_sha256'])
            assert issue(p,':observe later observed(future)').startswith('observation_version')
            assert state.read_bytes().startswith(b'PCGM-COMPACT-1\n')
            got=logical(reader)
            assert got!=h(state.read_bytes())
            prep=run(beta,'--prepare',state,wd=d).decode().strip()
            assert val(prep,'snapshot_sha256')==got
            hand=issue(p,':handoff beta '+val(prep,'binary_sha256')+' '+val(prep,'snapshot_sha256'))
            assert hand.startswith('handoff_prepared') and p.wait(timeout=8)==0
            with live(beta,'--claim',state,val(hand,'nonce'),wd=d) as b:
                assert val(b.stdout.readline(),'individual')==who
                assert issue(b,'observed(future)').startswith('POSITIVE')
                assert issue(b,':chat anchor first focus tag(ok)').startswith('chat_replayed')
                assert b.stdout.readline()==saved_reply
                assert state.read_bytes().startswith(b'PCGM-COMPACT-1\n')
                old_proof=get(reader,'hist historical sample observed(v131)')
                assert old_proof['result']['status']=='POSITIVE'
                b.kill();assert b.wait(timeout=5)<0
            with live(beta,'--resume',state,wd=d) as b:
                assert val(b.stdout.readline(),'individual')==who
                s=get(reader,'s storage')
                assert s['representation']=='compact'
                exact=s['logical_sha256']
                assert issue(b,':materialize_state '+exact).startswith('state_representation materialized')
                assert h(state.read_bytes())==exact
                assert get(reader,'s storage')['logical_sha256']==exact
                assert issue(b,':compact_state '+exact).startswith('state_representation compact')
                assert get(reader,'s storage')['logical_sha256']==exact
            archives=get(reader,'a archives')['segments']
            pth=d/'state.history'/(archives[0]['digest']+'.logseg')
            pth.write_bytes(pth.read_bytes()[:-1])
            assert 'digest mismatch' in get(reader,'s storage',False)
            untouched=state.read_bytes()
            assert not run(beta,'--resume',state,wd=d,ok=1)
            assert state.read_bytes()==untouched
print('PASS: real writer compacts and restores physical storage without changing a logical snapshot, continues recording, survives managed native handoff and SIGKILL, and refuses damaged history.')
