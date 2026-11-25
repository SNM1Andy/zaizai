from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'

def invoke(*args, code=0, reason=b''):
    r=subprocess.run([cl,*args],capture_output=True,timeout=12,env={'PATH':'','LC_ALL':'C'})
    assert r.returncode==code,(r.args,r.returncode,r.stderr,r.stdout[:200])
    if code:assert reason in r.stderr and not r.stdout,r
    return r.stdout

with TemporaryDirectory(prefix='real independent CL work planes ') as tmp:
    d=Path(tmp)
    source=d/'matrix.cl'
    program=['module matrix.', ': left(sym).', ': right(sym).', ': heard(sym).',
             ': dense(sym,sym).', ': observed(sym).', ': confirmed(sym).', ': unrelated(sym).',
             'dense($x,$y) <- left($x) & right($y).',
             'observed($x) <- heard($x).','confirmed($x) <- observed($x).',
             '& good heard(ok).','& quiet !unrelated(never).']
    program += [f'& l{i} left(n{i}).\n& r{i} right(n{i}).' for i in range(44)]
    source.write_text('\n'.join(program)+'\n')
    lock=d/'matrix.lock';lock.write_bytes(invoke('lock',source))
    api=d/'matrix.clapi';api.write_bytes(invoke('project-api',source,lock))
    package=d/'matrix.clpkg';package.write_bytes(invoke('project-pack',source,lock,api))
    p=sha256(package.read_bytes()).hexdigest()
    for file in (source,lock,api):file.unlink()
    goal=d/'goals'
    goal.write_text('dense(n0,n14)\nobserved(ok)\nunrelated(never)\nconfirmed(ok)\nconfirmed(unheard)\n')
    cmd=('package-plane-budget',package,p,goal)
    reduced=('90','12000','120','300','1')
    first=invoke(*cmd,*reduced)
    assert invoke(*cmd,*reduced[:-1],'4')==first
    out=json.loads(first); planes=out['planes']
    assert out['package_sha256']==p and out['goals_sha256']==sha256(goal.read_bytes()).hexdigest()
    assert [plane['goals'] for plane in planes]==[[0],[1,3,4],[2]],out
    for i,k in enumerate(('rounds','facts','probes','indexed')):
        assert sum(plane['quota'][k] for plane in planes)==int(reduced[i])
    assert not out['complete'] and planes[0]['status']=='exhausted' and not planes[0]['results']
    assert planes[0]['exhaustion']=='join budget'
    assert [x['status'] for x in planes[1]['results']]==['POSITIVE','POSITIVE','UNKNOWN']
    assert [x['status'] for x in planes[2]['results']]==['NEGATIVE']
    compare=json.loads(invoke('package-prove',package,p,goal))['results']
    high=('90','12000','12000','300','3')
    all_complete=invoke(*cmd,*high)
    assert invoke(*cmd,*high[:-1],'1')==all_complete
    full=json.loads(all_complete);assert full['complete']
    for plane in full['planes']:
        for i,row in zip(plane['goals'],plane['results']):assert row==compare[i],(i,row,compare[i])
    starved=json.loads(invoke(*cmd,'1','1','1','1','4'))
    assert [x['exhaustion'] for x in starved['planes'][1:]]==['no allocated quota','no allocated quota']
    invoke('package-plane-budget',package,'0'*64,goal,*high,code=1,reason=b'does not match supplied SHA-256')
print('PASS: actual pinned CL isolates exhausted joins, groups shared dependencies, preserves independent evidence, and yields byte-identical receipts across one and four workers.')
