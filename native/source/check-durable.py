from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from contextlib import contextmanager
import subprocess,json,shutil
root=Path(__file__).resolve().parent
cl=root/'cl';file=root/'fixtures';bundles=root/'profiles'
def h(s):return sha256(s).hexdigest()
def call(*args,code=0):
    p=subprocess.run([cl,*args],capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stdout[:100],p.stderr[:1000])
    return p
@contextmanager
def live(*args):
    p=subprocess.Popen([cl,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:yield p
    finally:
        if p.poll() is None:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def get(p,req,ok=True):
    p.stdin.write(req+'\n');p.stdin.flush()
    response=json.loads(p.stdout.readline())
    assert response['ok']==ok,response
    return response.get('payload',response.get('error'))
with TemporaryDirectory(prefix='CL actual compiler journal ') as tmp:
    d=Path(tmp);w=d/'work';w.mkdir()
    smoke=d/'compile_smoke.cl';shutil.copyfile(file/'arithmetic.cl',smoke)
    expected=call('compile',smoke).stdout
    base_profile=d/'first.clcp';shutil.copyfile(bundles/'standard.clcp',base_profile)
    exchanged=w/'candidate.clcp';shutil.copyfile(bundles/'forward.clcp',exchanged)
    standard=w/'standard.cl';standard.write_bytes(smoke.read_bytes())
    new_source=w/'forward.cl';new_source.write_text(standard.read_text().replace(
        'bill($x,$sum) <- invoice($x,$a) & shipping($x,$b) & qty_add($a,$b,$sum).',
        'invoice($x,$a) & shipping($x,$b) & qty_add($a,$b,$sum) => bill($x,$sum).'))
    old=h(base_profile.read_bytes());future=h(exchanged.read_bytes());state=d/'compiler.clcs'
    with live('compiler-init',state,base_profile,w,smoke,h(expected)) as p:
        start=get(p,'check status')
        assert start['active_profile_sha256']==old and start['epoch']==0 and state.exists()
        initial=state.read_bytes();assert initial.startswith(b'CLCS-1\n')
        denied=call('compiler-resume',state,w,code=1)
        assert b'already has a writer' in denied.stderr and state.read_bytes()==initial
        ready=get(p,f'stage stage candidate {old} {future}')
        assert ready['staged_profile_sha256']==future and state.read_bytes()==initial
        p.kill();assert p.wait(timeout=5)<0
    assert state.read_bytes()==initial
    refused=call('compiler-init',state,base_profile,w,smoke,h(expected),code=1)
    assert b'already exists' in refused.stderr and state.read_bytes()==initial
    with live('compiler-resume',state,w) as p:
        status=get(p,'resume status')
        assert status==start
        assert 'grammar rejected' in get(p,'old build forward',False)
        get(p,f'stage stage candidate {old} {future}')
        result=get(p,'launch activate '+future)
        assert result['epoch']==1 and result['active_profile_sha256']==future and state.read_bytes()!=initial
        saved=state.read_bytes()
        assert bytes.fromhex(get(p,'exported build forward')['ir_hex'])==expected
        p.kill();assert p.wait(timeout=5)<0
    assert state.read_bytes()==saved
    for p in (base_profile,exchanged,smoke):p.unlink()
    with live('compiler-resume',state,w) as p:
        assert get(p,'status status')==result
        assert bytes.fromhex(get(p,'again build forward')['ir_hex'])==expected
        get(p,f'prior stage_retained {future} {old}')
        back=get(p,'back activate '+old)
        assert back['epoch']==2 and back['active_profile_sha256']==old
        assert p.poll() is None
    with live('compiler-resume',state,w) as p:
        assert get(p,'conf status')==back
        assert 'grammar rejected' in get(p,'previous build forward',False)
        assert get(p,'standard build standard')['ir_sha256']==h(expected)
    assert not list(d.glob('.compiler-pending-*'))
    interrupted=d/'broken.clcs';interrupted.write_bytes(saved[:-1])
    failure=call('compiler-resume',interrupted,w,code=1)
    assert b'journal digest mismatch' in failure.stderr and interrupted.read_bytes()==saved[:-1]
print('PASS: actual SIGKILL before and after activation, durable recovery and old version rollback with profile inputs removed, and concurrent writer refused.')
