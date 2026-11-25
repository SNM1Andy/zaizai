from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def h(x):return sha256(x).hexdigest()
def run(*args,code=0,error=b''):
    p=subprocess.run([cl,*args],capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stderr[:1000],p.stdout[:800])
    if error:assert error in p.stderr,(p.args,p.stderr[:1000])
    return p
with TemporaryDirectory(prefix='actual CL-authored project scope ') as td:
    d=Path(td)
    tree=d/'project';shutil.copytree(root/'fixtures'/'portfolio_units',tree)
    entry=tree/'pilot.cl';data=tree/'pilot_data.cl';lock=d/'pilot.lock'
    lock.write_bytes(run('lock',entry).stdout)
    standard=root/'fixtures'/'module-scope.cl'
    def author(name,text):
        src=d/(name+'.cl');src.write_text(text)
        target=d/(name+'.clir');target.write_bytes(run('compile',src).stdout)
        return target,h(target.read_bytes())
    default=author('normal',standard.read_text())
    plain=run('project-compile',entry,lock,data).stdout
    report=json.loads(run('project-scoped-report',entry,lock,*default,data).stdout)
    assert report['passed'] and report['profile_sha256']==default[1]
    assert report['lock_sha256']==h(lock.read_bytes())
    assert len(report['sites'])>18 and all(s['permission']=='ALLOWED' for s in report['sites'])
    seen=[s for s in report['sites'] if s['caller']=='pilot_app' and s['provider']=='econ' and s['role']=='data']
    assert len(seen)==7 and all(s['file']=='pilot_data.cl' and s['line']>0 for s in seen)
    assert run('project-scoped-compile',entry,lock,*default,data).stdout==plain
    deny='!scope_allow($site) <- scope_call($site,pilot_app,econ,verified) & scope_role($site,data).\n'
    conflicted=author('conflicted',standard.read_text()+deny)
    refusal=json.loads(run('project-scoped-report',entry,lock,*conflicted,data,code=2).stdout)
    assert not refusal['passed'] and len([s for s in refusal['sites'] if s['permission']=='CONFLICT'])==2
    assert run('project-scoped-compile',entry,lock,*conflicted,data,code=2,error=b'CONFLICT').stdout==b''
    lower=standard.read_text().splitlines()
    without='\n'.join(line for line in lower if not line.startswith('scope_allow($site) <- scope_call($site,$caller,$provider,$predicate) & scope_direct($caller,$provider) & scope_input'))
    denied=author('denied',without+'\n'+deny)
    check=json.loads(run('project-scoped-report',entry,lock,*denied,data,code=2).stdout)
    assert set(s['permission'] for s in check['sites'])=={'ALLOWED','DENIED','NO_PROOF'}
    run('project-scoped-compile',entry,lock,default[0],'0'*64,data,code=1,error=b'profile digest mismatch')
    manufactured=author('fake',standard.read_text()+'scope_module(fake).\n')
    run('project-scoped-compile',entry,lock,*manufactured,data,code=1,error=b'cannot manufacture graph facts')
    secret=tree/'modules'/'econ.cl'
    original=secret.read_text()
    secret.write_text(original.replace('export feasible.\n',''))
    run('project-scoped-compile',entry,lock,*default,data,code=1,error=b'project lock mismatch')
    # Pin replacement project bytes explicitly; native privacy remains independent of the authored stage.
    lock.write_text(lock.read_text().replace(h(original.encode()),h(secret.read_bytes())))
    run('project-scoped-compile',entry,lock,*default,data,code=1,error=b'private predicate')
    sub=d/'fold_project';(sub/'modules').mkdir(parents=True)
    claims=sub/'modules'/'claims.cl'
    claims.write_text('module claims.\nexport ledger.\n: ledger(sym,sym,qty(cny_cent)).\n& receipt ledger(group,item,12@cny_cent).\n')
    top=sub/'entry.cl'
    top.write_text('module entry.\nuse claims.\n: total(qty(cny_cent)).\ntotal($x) <- qty_fold_sum(claims::ledger,group,$x).\n? total(12@cny_cent).\n')
    pin=d/'fold.lock';pin.write_bytes(run('lock',top).stdout)
    fold_report=json.loads(run('project-scoped-report',top,pin,*default).stdout)
    used=next(s for s in fold_report['sites'] if s['role']=='fold')
    assert used['provider']=='claims' and used['symbol']=='ledger' and used['permission']=='ALLOWED'
    assert run('project-scoped-compile',top,pin,*default).stdout.startswith(b'CLIR-4\n')
print('PASS: native standalone CL authored scope permits ordinary locked link byte-parity, denies or detects conflicting policy/data/fold calls, and cannot bypass basic native module privacy.')
