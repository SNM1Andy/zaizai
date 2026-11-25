from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import subprocess

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
env={'PATH':'','LC_ALL':'C'}
def digest(raw):return sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest()
def run(exe,*args,input=None,code=0,cwd=None):
    p=subprocess.run([exe,*args],input=input,cwd=cwd,env=env,capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stdout[:300],p.stderr[:700])
    return p
@contextmanager
def live(*args,cwd=None):
    with subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill()
            assert p.wait(timeout=5) in (0,-9)
def ask(p,text):
    p.stdin.write(text+'\n');p.stdin.flush()
    line=p.stdout.readline().strip()
    assert line,(text,p.poll())
    return line
def key(s,label):return re.search(fr'{label}=([a-z0-9]+)',s)[1]
def rechecksum(raw):
    title,_,body=raw.split(b'\n',2)
    value=14695981039346656037
    for b in body:value=((value^b)*1099511628211)&((1<<64)-1)
    return title+b'\n'+str(value).encode()+b'\n'+body

with TemporaryDirectory(prefix='PCGM independently reconstructs historical observation correction ') as temp:
    d=Path(temp);state=d/'state';seed=d/'seed.cl'
    special='"从甲变乙 ; 复核"'
    seed.write_text(''' : source(sym).
: derived(sym).
: unchanged(sym).
: noise(sym).
& initial source(first).
& still unchanged(good).
derived(now) <- source(first).
!derived(now) <- source('''+special+''').
'''.lstrip(),encoding='utf-8')
    def read(op,actor=alpha,path=state,ok=True):
        ans=json.loads(run(actor,'--read-channel',path,input=('q '+op+'\n').encode(),cwd=d).stdout)
        assert ans['ok']==ok,(ans,op)
        return ans['payload' if ok else 'error']
    def logical(actor=alpha,path=state):return read('storage',actor,path)['logical_sha256']
    def replay(id,command,actor=alpha,path=state,ok=True):
        return read(f'observation_batch_audit {id} {digest(command)} ; derived(now) ; unchanged(good)',actor,path,ok)
    with live(alpha,'--init-managed',seed,state,cwd=d) as a:
        who=key(a.stdout.readline(),'individual')
        assert ask(a,'derived(now)').startswith('POSITIVE')
        assert ask(a,':watch tracked derived(now)').startswith('watch')
        assert ask(a,':watch untouched unchanged(good)').startswith('watch')
        basis=logical()
        older=f':observation_batch legacy {basis} ; observe noise1 noise(first)'
        assert json.loads(ask(a,older))['status']=='committed'
        assert replay('legacy',older)['status']=='basis_not_retained'
        assert replay('absent',older)['status']=='not_recorded'
        basis=logical()
        before=state.read_bytes()
        bad=f':observation_batch_audited rejected {basis} ; observe valid noise(two) ; withdraw missing'
        assert 'unknown' in ask(a,bad) and state.read_bytes()==before
        episodes=Path(str(state)+'.episodes')
        assert not episodes.exists()
        change=f':observation_batch_audited amendment {basis} ; observe current source({special}) ; withdraw initial'
        written=json.loads(ask(a,change))
        assert written['status']=='committed'
        post=state.read_bytes()
        assert (episodes/(basis+'.snap')).read_bytes()==before
        recovered=replay('amendment',change)
        assert state.read_bytes()==post and recovered['status']=='verified' and recovered['read_only']
        assert recovered['individual']==who and recovered['basis_sha256']==basis
        assert recovered['reconstructed_after_sha256']==digest(post)
        assert recovered['last_event']==written['event']+1
        assert recovered['observation_version']==written['observation_version']
        changed,same=recovered['results']
        assert changed['before']['status']=='POSITIVE' and changed['after']['status']=='NEGATIVE'
        assert changed['before_sha256']!=changed['after_sha256']
        assert same['before']['status']==same['after']['status']=='POSITIVE' and same['before_sha256']==same['after_sha256']
        # Even with a valid outer transport checksum, independent replay detects
        # a historical notice whose proof identity was changed.
        corrupted=d/'wrong-notice'
        marker=b'notice2 tracked derived(now) '
        lines=post.splitlines(keepends=True)
        i=next(i for i,row in enumerate(lines) if row.startswith(marker))
        parts=lines[i].split()
        parts[-1]=b'0'*64
        lines[i]=b' '.join(parts)+b'\n'
        wrongbytes=rechecksum(b''.join(lines))
        corrupt_assets=Path(str(corrupted)+'.episodes');corrupt_assets.mkdir()
        (corrupt_assets/(basis+'.snap')).write_bytes(before)
        corrupted.write_bytes(wrongbytes)
        assert 'notices differ' in replay('amendment',change,alpha,corrupted,ok=False)
        assert corrupted.read_bytes()==wrongbytes
        assert 'request SHA-256 does not match' in replay('amendment',change+' ',ok=False)
        assert 'historical queries' in read(f'observation_batch_audit amendment {digest(change)} ; !derived(now)',ok=False)
        assert json.loads(ask(a,change))=={**written,'status':'already_applied'}
        assert len(list(episodes.iterdir()))==1 and state.read_bytes()==post
        assert 'restored initial' in ask(a,':restore initial')
        assert read('proof derived(now)')['results'][0]['status']=='CONFLICT'
        assert replay('amendment',change)==recovered
        for i in range(131):
            assert f'observed add{i}' in ask(a,f':observe add{i} noise(n{i})')
        assert ask(a,':seal_history '+logical()).startswith('archive_sealed')
        assert ask(a,':compact_state '+logical()).startswith('state_representation compact')
        prepared=run(beta,'--prepare',state,cwd=d).stdout.decode()
        transfer=ask(a,':handoff beta '+key(prepared,'binary_sha256')+' '+key(prepared,'snapshot_sha256'))
        assert transfer.startswith('handoff_prepared') and a.wait(timeout=5)==0
    with live(beta,'--claim',state,key(transfer,'nonce'),cwd=d) as b:
        assert key(b.stdout.readline(),'individual')==who
        assert replay('amendment',change,beta)==recovered
        assert ask(b,'derived(now)').startswith('CONFLICT')
        b.kill();assert b.wait(timeout=5)<0
    assert replay('amendment',change,beta)==recovered
    archived=d/'archive'
    assert b'transfer_exported' in run(beta,'--export-compact',state,archived,cwd=d).stdout
    saved=archived/'episodes'/(basis+'.snap')
    savedbytes=saved.read_bytes()
    assert savedbytes==before
    missing=d/'missing'
    saved.unlink()
    assert b'cannot open' in run(beta,'--restore-copy',archived,missing,code=1,cwd=d).stderr
    assert not missing.exists()
    saved.write_bytes(savedbytes[:-1])
    assert b'pinned snapshot digest mismatch' in run(beta,'--restore-copy',archived,missing,code=1,cwd=d).stderr
    assert not missing.exists()
    saved.write_bytes(savedbytes)
    staged=d/'revived'
    assert b'activation=required' in run(beta,'--restore-copy',archived,staged,cwd=d).stdout
    assert replay('amendment',change,beta,staged)==recovered
    assert b'individual='+who.encode() in run(beta,'--activate-restored',staged,'--source-stopped',cwd=d).stdout
    assert replay('amendment',change,beta,staged)==recovered
    assert read('proof derived(now)',beta,staged)['results'][0]['status']=='CONFLICT'
    copy_asset=Path(str(staged)+'.episodes')/(basis+'.snap')
    copy_asset.write_bytes(savedbytes[:-1])
    stable=staged.read_bytes()
    assert 'pinned snapshot digest mismatch' in replay('amendment',change,beta,staged,ok=False)
    assert staged.read_bytes()==stable
    copy_asset.write_bytes(savedbytes)
print('PASS: native PCGM replays exact before/after proof and notices against the immutable audited request, rejects missing or corrupt bases/pins without writes, and preserves the exact historical answer after later changes, restart, A/B and activated compact transfer.')
