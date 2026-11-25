from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parent

def h(x):return sha256(x).hexdigest()
def run(exe,*args,code=0,error=b'',cwd=None):
    p=subprocess.run([exe,*args],cwd=cwd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stderr[:1100],p.stdout[:500])
    if error:assert error in p.stderr and not p.stdout,(p.args,p)
    return p.stdout
with TemporaryDirectory(prefix='CL scoped portable distribution ') as td:
    d=Path(td)
    source=d/'pub';recipient=d/'recv';source.mkdir();recipient.mkdir()
    tree=source/'tree';shutil.copytree(root/'fixtures'/'portfolio_units',tree)
    author=shutil.copy2(root/'cl',source/'cl')
    consumer=shutil.copy2(root/'cl',recipient/'cl')
    entry=tree/'pilot.cl';data=tree/'pilot_data.cl';lock=source/'pilot.lock'
    lock.write_bytes(run(author,'lock',entry))
    api=source/'pilot.clapi';api.write_bytes(run(author,'project-api',entry,lock))
    standard=(root/'fixtures'/'module-scope.cl').read_text()
    def stage(label,text):
        src=source/(label+'.cl');src.write_text(text)
        target=source/(label+'.clir');target.write_bytes(run(author,'compile',src))
        return target,h(target.read_bytes())
    default=stage('standard',standard)
    alternate=stage('other',standard+': additional(sym).\nadditional(irrelevant).\n')
    conflicting=stage('refuse',standard+
                      '!scope_allow($id) <- scope_call($id,pilot_app,econ,verified) & scope_role($id,data).\n')
    ordinary=run(author,'project-pack',entry,lock,api,data)
    run(author,'project-scoped-pack',entry,lock,api,*conflicting,data,code=1,error=b'did not authorize')
    run(author,'project-scoped-pack',entry,lock,api,default[0],'0'*64,data,code=1,error=b'profile digest mismatch')
    auth=run(author,'project-scoped-pack',entry,lock,api,*default,data)
    second=run(author,'project-scoped-pack',entry,lock,api,*alternate,data)
    assert auth.startswith(b'CLPKG-2\n') and ordinary.startswith(b'CLPKG-1\n') and auth!=second
    pins=[default[1],alternate[1]]
    shutil.rmtree(source)
    for name,bytes in [('ordinary',ordinary),('release',auth),('another',second)]:
        (recipient/name).write_bytes(bytes)
    if len(sys.argv)>1:
        prev=Path(sys.argv[1]).resolve()
        run(prev,'package-verify',recipient/'release',code=1,error=b'unsupported or truncated')
    cwd={'cwd':recipient}
    observed=run(consumer,'package-verify-scope','release',h(auth),pins[0],**cwd)
    assert b'scope_package_ok' in observed and b'scope_report_sha256=' in observed
    assert run(consumer,'package-verify-scope','another',h(second),pins[1],**cwd)!=observed
    assert run(consumer,'package-ir','ordinary',**cwd)==run(consumer,'package-ir','release',**cwd)
    run(consumer,'package-verify-scope','ordinary',h(ordinary),pins[0],code=1,error=b'no authored scope profile',**cwd)
    run(consumer,'package-verify-scope','release',h(auth),pins[1],code=1,error=b'does not use the required',**cwd)
    run(consumer,'package-verify-scope','release',h(second),pins[0],code=1,error=b'does not match supplied',**cwd)
    version,_,body=auth.split(b'\n',2)
    altered=body[:-64]+b'0'*64
    tampered=version+b'\n'+h(altered).encode()+b'\n'+altered
    (recipient/'forged').write_bytes(tampered)
    run(consumer,'package-verify-scope','forged',h(tampered),pins[0],code=1,error=b'scope report differs',**cwd)
    weak=auth.replace(b'CLPKG-2\n',b'CLPKG-1\n',1)
    (recipient/'downgrade').write_bytes(weak)
    run(consumer,'package-verify','downgrade',code=1,error=b'trailing CL package bytes',**cwd)
    (recipient/'goals').write_text('feasible(test_a)\nfeasible(test_b)\n')
    result=json.loads(run(consumer,'package-prove','release',h(auth),'goals',**cwd))
    assert [x['status'] for x in result['results']]==['POSITIVE','NEGATIVE']
    assert not list(recipient.glob('*.cl')) and not (recipient/'modules').exists()
print('PASS: actual CLPKG-2 carries scoped policy through offline relocation without project source; exact scope/IR are rebuilt and wrong, forged, absent or downgraded policy refuses.')
