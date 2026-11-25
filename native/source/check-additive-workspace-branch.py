from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import json, subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(path):return sha256(path.read_bytes()).hexdigest()
def put(path,data):path.write_bytes(data if isinstance(data,bytes) else data.encode());return path
def run(tool,*args,code=0,error=b''):
    p=subprocess.run([tool,*args],capture_output=True,timeout=20,env={'PATH':'','LC_ALL':'C'})
    assert p.returncode==code,(p.args,p.returncode,p.stderr)
    if error:assert error in p.stderr and not p.stdout,p
    return p.stdout

with TemporaryDirectory(prefix='native additive dependency workspace branch ') as work:
    d=Path(work);inputs=d/'inputs';inputs.mkdir()
    for name,amount in (('bank',80),('grant',20)):
        src=put(inputs/(name+'.cl'),f'module {name}.\nexport value.\n: value(qty(cny_cent)).\n& amt value({amount}@cny_cent).\n')
        lock=put(src.with_suffix('.lock'),run(cl,'lock',src))
        api=put(src.with_suffix('.api'),run(cl,'project-api',src,lock))
        put(src.with_suffix('.clpkg'),run(cl,'project-pack',src,lock,api))
    lock=put(inputs/'locked','CLWORK-1\n'+''.join(f'{m} {m}.clpkg {pin(inputs/(m+".clpkg"))} -\n' for m in ('bank','grant')))
    text='''module purse.
use bank.
use grant.
export invoice.
: invoice(qty(cny_cent)).
: rebate(qty(cny_cent)).
invoice($x) <- bank::value($x).
rebate($x) <- grant::value($x).
'''
    src=put(inputs/'source.cl',text)
    baseline=put(d/'baseline.clw',run(cl,'workspace-pack',src,lock,pin(lock)))
    scope=pin(lock)
    rmtree(inputs)
    new=text+'''export combined.
: combined(qty(cny_cent)).
combined($total) <- invoice($x) & rebate($y) & qty_add($x,$y,$total).
'''
    candidate=put(d/'candidate.cl',new)
    goals=put(d/'goals','invoice(80@cny_cent)\nrebate(20@cny_cent)\ninvoice(0@cny_cent)\n')
    def arguments():
        return baseline,pin(baseline),scope,candidate,pin(candidate),goals,pin(goals)
    archive=put(d/'next.clw',run(cl,'workspace-branch-additive',*arguments()))
    assert archive.read_bytes()!=baseline.read_bytes()
    extra=put(d/'extra-goals',goals.read_bytes()+b'combined(100@cny_cent)\n')
    proof=json.loads(run(cl,'workspace-prove',archive,pin(archive),scope,extra))
    assert [x['status'] for x in proof['results']]==['POSITIVE','POSITIVE','UNKNOWN','POSITIVE']
    run(cl,'workspace-rebuild',*arguments()[:-2],code=1,error=b'public API changed')
    bad=list(arguments());bad[-1]='0'*64
    run(cl,'workspace-branch-additive',*bad,code=1,error=b'regression goals digest mismatch')
    put(candidate,new.replace('export invoice.',''))
    run(cl,'workspace-branch-additive',*arguments(),code=1,error=b'preserve every existing public interface')
    put(candidate,new.replace('module purse.','module shuffled.'))
    run(cl,'workspace-branch-additive',*arguments(),code=1,error=b'cannot change application module identity')
    put(candidate,new+'& newfact invoice(10@cny_cent).\n')
    run(cl,'workspace-branch-additive',*arguments(),code=1,error=b'cannot change ground observations')
    put(candidate,new.replace('invoice($x) <- bank::value($x).','invoice($x) <- grant::value($x).'))
    run(cl,'workspace-branch-additive',*arguments(),code=1,error=b'changed a pinned regression outcome')
    put(candidate,new)
    consumer=d/'isolated';consumer.mkdir()
    names={'cl-additive-workspace-sdk-check','libcl_runtime.so'}
    for p in names:copy2(root/p,consumer/p)
    assert not run(consumer/'cl-additive-workspace-sdk-check',*arguments(),archive)
    assert {p.name for p in consumer.iterdir()}==names
print('PASS: native additive CL workspace branch retains exact old interfaces, observations, dependency pins and checked answers; new typed result proves after inputs are removed and detached SDK bytes equal CLI.')
