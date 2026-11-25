from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys

root=Path(__file__).resolve().parent
cl=root/'cl'
pcgm=root/'pcgm-alpha'
def h(data):return sha256(data).hexdigest()
def run(exe,*args,expected=0,error=b'',data=b''):
    p=subprocess.run([exe,*args],input=data,capture_output=True,timeout=20)
    assert p.returncode==expected,(p.args,p.returncode,p.stderr[:1200],p.stdout[:300])
    if error:assert error in p.stderr,(p.args,p.stderr)
    return p.stdout
@contextmanager
def live(*args):
    with subprocess.Popen([cl,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as process:
        try:yield process
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
def get(p,value):
    p.stdin.write(value+'\n');p.stdin.flush()
    line=p.stdout.readline()
    assert line,(value,p.poll())
    return json.loads(line),line.encode()
with TemporaryDirectory(prefix='CL sealed quantity reduction ') as td:
    d=Path(td)
    sample=root/'fixtures'/'closed-fold.cl'
    binary=run(cl,'compile',sample)
    assert binary.startswith(b'CLIR-4\n')
    image=d/'before.clir';image.write_bytes(binary)
    if len(sys.argv)>1:run(Path(sys.argv[1]).resolve(),'ir-run',image,expected=1,error=b'unsupported or truncated')
    spoof=d/'spoof.clir';spoof.write_bytes(binary.replace(b'CLIR-4\n',b'CLIR-3\n',1))
    run(cl,'ir-run',spoof,expected=1,error=b'closed folds require CLIR-4')
    assert run(cl,'ir-run',image)==run(cl,'run',sample)
    proof=json.loads(run(cl,'ir-slice',image,'total(active,155@cny_cent)','total(empty,0@cny_cent)'))
    assert all(x['status']=='POSITIVE' for x in proof['results'])
    joined=json.dumps(proof['results'][0])
    assert 'qty_fold_sum' in joined and all(term in joined for term in ['early','late','out'])
    assert 'proposed' not in joined
    assert b'POSITIVE' in run(pcgm,sample,data=b'total(active,155@cny_cent)\n')
    run(cl,'profile-build',root/'profiles'/'standard.clcp',h((root/'profiles'/'standard.clcp').read_bytes()),sample,
        expected=1,error=b'does not support closed folds')
    def problem(label,edit,reason,cmd='run'):
        f=d/(label+'.cl');f.write_text(edit(sample.read_text()))
        run(cl,cmd,f,expected=1,error=reason)
    problem('bad_unit',lambda s:s.replace(': total(sym,qty(cny_cent))',': total(sym,qty(items))'),
            b'closed fold operand type mismatch','compile')
    problem('dynamic',lambda s:s+'claims(active,new,1@cny_cent).\n',
            b'closed fold source must contain observations only','compile')
    problem('conflict',lambda s:s+'& conflict !claims(active,early,120@cny_cent).\n',
            b'contains contradicted evidence')
    problem('double',lambda s:s+'& conflict claims(active,early,99@cny_cent).\n',
            b'has multiple amounts for one item')
    problem('overflow',lambda s:s+'& big claims(active,extra,9223372036854775807@cny_cent).\n',
            b'signed 64-bit sum overflow')
    problem('many',lambda s:s+''.join(f'& v{i} claims(active,i{i},1@cny_cent).\n' for i in range(65)),
            b'group exceeds 64 items')
    large=d/'large.cl'
    extra=''.join(f'& k{i} claims(active,item{i},1@cny_cent).\n' for i in range(14))
    compensated=('& max1 claims(active,big_a,9223372036854775807@cny_cent).\n'
                 '& max2 claims(active,big_b,9223372036854775807@cny_cent).\n'
                 '& min1 claims(active,tiny_a,-9223372036854775807@cny_cent).\n'
                 '& min2 claims(active,tiny_b,-9223372036854775807@cny_cent).\n')
    large.write_text('module large.\n'+sample.read_text()+extra+compensated)
    lock=d/'large.lock';lock.write_bytes(run(cl,'lock',large))
    api=d/'large.clapi';api.write_bytes(run(cl,'project-api',large,lock))
    pack=d/'large.clpkg';pack.write_bytes(run(cl,'project-pack',large,lock,api))
    stamp=h(pack.read_bytes())
    q=d/'goals';q.write_text('total(active,169@cny_cent)\ntotal(empty,0@cny_cent)\n')
    receipt=run(cl,'package-prove',pack,stamp,q)
    assert all(x['status']=='POSITIVE' for x in json.loads(receipt)['results'])
    run(cl,'package-prove-budget',pack,stamp,q,'128','12000','4','2000000',expected=1,error=b'join budget')
    checkpoint=d/'cp'
    with live('package-round-checkpoint',pack,stamp,q,checkpoint) as p:
        assert json.loads(p.stdout.readline())['rounds']==0
        assert get(p,'step 1')[0]['status']=='running'
        pin=get(p,'checkpoint')[0]['sha256']
        assert h(checkpoint.read_bytes())==pin
        p.kill();assert p.wait(timeout=5)<0
    with live('package-round-reopen',pack,stamp,q,checkpoint,pin) as p:
        assert json.loads(p.stdout.readline())['rounds']==1
        assert get(p,'finish')[0]['status']=='complete'
        assert get(p,'proof')[1]==receipt
    mods=d/'modules';mods.mkdir()
    data=mods/'dataset.cl'
    data.write_text("module dataset.\nexport claims.\n: claims(sym,sym,qty(cny_cent)).\n& observation claims(coal,truck,700@cny_cent).\n")
    exported=mods/'reducer.cl'
    exported.write_text("module reducer.\nuse dataset.\nexport total.\n: total(qty(cny_cent)).\ntotal($amount) <- qty_fold_sum(dataset::claims,coal,$amount).\n")
    top=d/'nested.cl'
    top.write_text("module nested.\nuse reducer.\n: shown(qty(cny_cent)).\nshown($v) <- reducer::total($v).\n? shown(700@cny_cent).\n")
    lock=d/'nested.lock';lock.write_bytes(run(cl,'lock',top))
    api=d/'nested.clapi';api.write_bytes(run(cl,'project-api',top,lock))
    packed=d/'nested.clpkg';packed.write_bytes(run(cl,'project-pack',top,lock,api))
    output=run(cl,'package-run',packed)
    assert b'shown(700@cny_cent) POSITIVE' in output, output
    data.write_text(data.read_text().replace('export claims.\n',''))
    run(cl,'lock',top,expected=1,error=b'private fold source')
print('PASS: native CL sealed grouping preserves exact units and audit sources, rejects contradictions/overflow/non-input writers/legacy images, and its >8-witness receipt resumes after SIGKILL.')
