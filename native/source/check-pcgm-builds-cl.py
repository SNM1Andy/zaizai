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
with TemporaryDirectory(prefix='PCGM invoking independent CL ') as t:
    d=Path(t)
    inputs=d/'build_inputs';inputs.mkdir()
    source=inputs/'law.cl';profile=inputs/'law.clcp'
    grammar=home/'profiles'/'forward.clcp'
    pbytes=grammar.read_bytes();profile.write_bytes(pbytes)
    standard=(home/'fixtures'/'arithmetic.cl').read_text()
    alternative=standard.replace(
        'bill($x,$sum) <- invoice($x,$a) & shipping($x,$b) & qty_add($a,$b,$sum).',
        'invoice($x,$a) & shipping($x,$b) & qty_add($a,$b,$sum) => bill($x,$sum).')
    source.write_text(alternative)
    assert not run(cl,'compile',source,ok=1)
    expected=run(cl,'profile-build',profile,h(pbytes),source)
    one=h(pbytes);two=h(source.read_bytes());image=h(expected)
    seed=d/'seed.cl';seed.write_text(': later(sym).\nready(ok).\n')
    state=d/'state'
    def cmds(basis,source_sha=two):
        return f':stage_cl law {one} {source_sha} {basis}'
    def commit(basis,product=image):
        return f':commit_cl law {product} {basis}'
    with live(pcgm,'--init',seed,state,wd=d) as p:
        uid=re.search(r'individual=(\w+)',p.stdout.readline())[1]
        initial=state.read_bytes()
        assert 'source transfer digest mismatch' in issue(p,cmds(h(initial),'0'*64))
        assert state.read_bytes()==initial
        good=issue(p,cmds(h(initial)))
        assert good.startswith('cl_staged law ') and image in good
        assert h(initial)==h(state.read_bytes()) and not (d/'imports').exists()
        assert 'observed later_one' in issue(p,':observe later_one later(sample)')
        now=h(state.read_bytes())
        assert now!=h(initial)
        assert 'snapshot changed' in issue(p,commit(h(initial)))
        assert 'unverified or stale' in issue(p,commit(now))
        assert image in issue(p,cmds(now))
        p.kill();assert p.wait(timeout=5)<0
    with live(pcgm,'--resume',state,wd=d) as p:
        assert uid in p.stdout.readline()
        assert 'unverified or stale' in issue(p,commit(now))
        assert image in issue(p,cmds(now))
        assert 'unverified or stale' in issue(p,commit(now,'1'*64))
        source.unlink();profile.unlink();seed.unlink()
        ratified=issue(p,commit(now))
        assert ratified.startswith('cl_committed law ') and image in ratified
        stored=state.read_bytes()
        assert stored!=initial
        p.kill();assert p.wait(timeout=5)<0
    observed=run(pcgm,'--read-channel',state,wd=d,data=b'r generated\np inspect * 0; artifact_law__bill(alpha,6000@cny_cent); later(sample)\n')
    a,b=[json.loads(x)['payload'] for x in observed.splitlines()]
    assert a['schema']=='pcgm-cl-origins-v1' and a['state']['individual']==uid
    assert a['results']==[{'alias':'law','profile_sha256':one,'source_sha256':two,'ir_sha256':image,'active':True}]
    assert [r['status'] for r in b['proofs']['results']]==['POSITIVE','POSITIVE']
    assert b['status']['state']['individual']==uid
    assert image in json.dumps(b) and 'qty_add' in json.dumps(b)
    audit=run(pcgm,'--resume',state,wd=d,data=b':history\n')
    assert audit.count(b' artifact_generated law ')==1
    assert not list(inputs.iterdir()) and not (d/'imports').exists() and state.read_bytes()==stored
print('PASS: compiled CL runs in the actual PCGM process, stage is invisible until commit, stale/crashed stages are not replayed, verified source/profile/IR provenance and later evidence reopen.')
