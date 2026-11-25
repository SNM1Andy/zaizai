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
with TemporaryDirectory(prefix='native PCGM event archive ') as t:
    d=Path(t);state=d/'state';seed=d/'seed.cl'
    seed.write_text(': tested(sym).\n: anchor(sym).\n& baseline anchor(active).\n')
    def found(exe):
        frame=json.loads(run(exe,'--read-channel',state,wd=d,data=b'r archives\n'))
        assert frame['ok'],frame
        return frame['payload']
    with live(alpha,'--init-managed',seed,state,wd=d) as p:
        uid=val(p.stdout.readline(),'individual')
        assert issue(p,':pin start').startswith('pin_committed')
        for i in range(140):
            assert issue(p,f':observe obs{i} tested(v{i})').startswith('observation_version')
        prior=state.read_bytes()
        assert 'history snapshot changed' in issue(p,':seal_history '+'0'*64)
        assert state.read_bytes()==prior
        first=issue(p,':seal_history '+h(prior))
        assert first.startswith('archive_sealed start=1 end=128'),first
        hash_one=val(first,'sha256')
        second=issue(p,':seal_history '+h(state.read_bytes()))
        assert second.startswith('archive_sealed start=129 '),second
        hash_two=val(second,'sha256')
        settled=state.read_bytes()
        assert issue(p,':seal_history '+h(settled))=='archive_unchanged'
        assert state.read_bytes()==settled
        audit=found(alpha)
        assert audit['individual']==uid and len(audit['segments'])==2
        assert audit['segments'][0]['digest']==hash_one and audit['segments'][1]['previous']==hash_one
        assert audit['segments'][1]['digest']==hash_two and audit['segments'][1]['start']==129
        assert audit['head']==audit['sealed_through']+1
        archive=d/'backup'
        outcome=run(alpha,'--export',state,archive,wd=d)
        assert b'transfer_exported' in outcome and (archive/'TRANSFER').read_text().startswith('PCGM_TRANSFER_2 ')
        for item in audit['segments']:
            segment=archive/'history'/(item['digest']+'.logseg')
            assert h(segment.read_bytes())==item['digest']
        restored=d/'copy'
        report=run(alpha,'--restore-copy',archive,restored,wd=d)
        assert b'activation=required' in report
        guarded=json.loads(run(alpha,'--read-channel',restored,wd=d,data=b'a archives\n'))
        assert guarded['payload']['individual']==uid and guarded['payload']['segments']==audit['segments']
        assert guarded['payload']['head']==audit['head']+1
        fail=run(alpha,'--resume',restored,wd=d,ok=1)
        assert not fail
        assert state.read_bytes()==settled
        bad_copy=archive/'history'/(hash_two+'.logseg')
        bad_copy.write_bytes(bad_copy.read_bytes()[:-1])
        refused=d/'refused'
        assert not run(alpha,'--restore-copy',archive,refused,wd=d,ok=1) and not refused.exists()
        ready=run(beta,'--prepare',state,wd=d).decode().strip()
        hand=issue(p,':handoff beta '+val(ready,'binary_sha256')+' '+val(ready,'snapshot_sha256'))
        assert hand.startswith('handoff_prepared') and p.wait(timeout=9)==0
    with live(beta,'--claim',state,val(hand,'nonce'),wd=d) as q:
        assert val(q.stdout.readline(),'individual')==uid
        assert issue(q,'tested(v139)').startswith('POSITIVE')
        assert found(alpha)['segments']==audit['segments']
        q.kill();assert q.wait(timeout=5)<0
    archive_state=found(beta)
    assert archive_state['segments']==audit['segments']
    actual=d/'state.history'/(hash_one+'.logseg')
    actual.write_bytes(actual.read_bytes()[:-1])
    before=state.read_bytes()
    assert not run(alpha,'--prepare',state,wd=d,ok=1)
    response=json.loads(run(beta,'--read-channel',state,wd=d,data=b'q archives\n'))
    assert not response['ok'] and 'digest mismatch' in response['error'] and state.read_bytes()==before
print('PASS: two immutable contiguous archive segments verify on native writer/read channel, survive handoff/crash and export/restore, and missing/corrupt bytes cannot claim a valid history.')
