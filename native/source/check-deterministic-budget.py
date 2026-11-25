from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def invoke(*args, code=0, reason=b''):
    r=subprocess.run([cl,*args],capture_output=True,timeout=12)
    assert r.returncode==code,(r.args,r.returncode,r.stderr,r.stdout[:200])
    if code:
        assert reason in r.stderr and r.stdout==b'',r
    return r.stdout
def bundle(d,name,text):
    source=d/(name+'.cl');source.write_text(text)
    lock=d/(name+'.lock');lock.write_bytes(invoke('lock',source))
    api=d/(name+'.clapi');api.write_bytes(invoke('project-api',source,lock))
    target=d/(name+'.clpkg');target.write_bytes(invoke('project-pack',source,lock,api))
    return target,sha256(target.read_bytes()).hexdigest()

with TemporaryDirectory(prefix='CL deterministic actual bounded joins ') as tmp:
    d=Path(tmp)
    source=['module links.',': e(sym,sym).',': path(sym,sym).',
            'path($x,$y) <- e($x,$y).','path($x,$z) <- path($x,$y) & e($y,$z).']
    source += [f'& source{i} e(n{i},n{i+1}).' for i in range(35)]
    path, pin=bundle(d,'links','\n'.join(source)+'\n')
    goals=d/'goals';goals.write_text('path(n0,n35)\npath(n35,n0)\n')
    plain=('package-prove',path,pin,goals)
    costs=('package-prove-budget',path,pin,goals)
    full=invoke(*plain)
    assert [x['status'] for x in json.loads(full)['results']]==['POSITIVE','UNKNOWN']
    assert invoke(*costs,'128','12000','2000000','2000000')==full
    assert invoke(*costs,'64','1000','100000','10000')==full
    invoke(*costs,'2','12000','2000000','2000000',code=1,reason=b'fixpoint budget')
    invoke(*costs,'128','4','2000000','2000000',code=1,reason=b'fact limit')
    invoke(*costs,'128','12000','20','2000000',code=1,reason=b'join budget')
    invoke(*costs,'128','12000','2000000','4',code=1,reason=b'join index budget')
    invoke(*costs,'129','12000','2000000','2000000',code=1,reason=b'invalid CL resource ceiling: rounds')
    invoke(*costs,'128','0','2000000','2000000',code=1,reason=b'invalid CL resource ceiling: facts')
    receipt=d/'receipt';receipt.write_bytes(full)
    assert invoke('package-proof-check',path,pin,goals,receipt).startswith(b'proof_receipt_ok')
    cartesian=['module dense.',': left(sym).',': right(sym).',': product(sym,sym).',
               'product($x,$y) <- left($x) & right($y).']
    cartesian += [f'& l{i} left(n{i}).\n& r{i} right(n{i}).' for i in range(44)]
    product,product_pin=bundle(d,'dense','\n'.join(cartesian)+'\n')
    dense_goals=d/'dense_goals';dense_goals.write_text('product(n0,n14)\n')
    jobs=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i in range(12):
            cmd=('package-prove-budget',product,product_pin,dense_goals)
            if i%2:jobs.append((i,pool.submit(invoke,*cmd,'16','12000','20000','20000')))
            else:jobs.append((i,pool.submit(invoke,*cmd,'16','12000','120','20000',code=1,reason=b'join budget')))
    for i,f in jobs:
        out=f.result()
        if i%2:assert json.loads(out)['results'][0]['status']=='POSITIVE'
        else:assert not out
    assert invoke(*plain)==full and sha256(path.read_bytes()).hexdigest()==pin
print('PASS: real recursive and dense CL packages exercise all four deterministic ceilings, fail without proof bytes, and produce the original exact receipt when within budget.')
