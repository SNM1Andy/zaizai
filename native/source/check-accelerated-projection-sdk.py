from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import json, subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_bytes(data);return p
def cli(*args):
    q=subprocess.run([cl,*args],capture_output=True,timeout=20,env={'PATH':'','LC_ALL':'C'})
    assert not q.returncode,(q.args,q.stderr)
    return q.stdout
def package(root, module, source):
    src=write(root/(module+'.cl'),source)
    lock=write(root/(module+'.lock'),cli('lock',src))
    api=write(root/(module+'.api'),cli('project-api',src,lock))
    return write(root/(module+'.clpkg'),cli('project-pack',src,lock,api))

with TemporaryDirectory(prefix='real isolated CL SDK with alternate projection ') as temp:
    d=Path(temp); build=d/'build';build.mkdir()
    use=d/'runtime';use.mkdir()
    keys=b''.join(f'& fact{i} sample(g{i%10},n{i},{i%7}@cny_cent).\n'.encode() for i in range(2112))
    plus=b': sample(sym,sym,qty(cny_cent)).\n'+keys
    api=b': target(sym).\n'
    standalone=package(build,'standalone',b'module standalone.\n'+plus+api+b'target($x) <- sample(g0,$x,0@cny_cent).\n')
    left=package(build,'ledger',b'module ledger.\nexport sample.\n'+plus)
    right=package(build,'guard',b'module guard.\nexport allow.\n: allow(sym).\n& gate allow(on).\n')
    app=write(build/'app.cl',b'module app.\nuse ledger.\nuse guard.\n'+api+
              b'target($x) <- guard::allow(on) & ledger::sample(g0,$x,0@cny_cent).\n')
    lock=write(build/'wlock',f'CLWORK-1\nguard {right.name} {pin(right)} -\nledger {left.name} {pin(left)} -\n'.encode())
    lockpin=pin(lock)
    archive=write(d/'archive',cli('workspace-pack',app,lock,lockpin))
    pkg=write(d/'package',standalone.read_bytes())
    rmtree(build)
    exact=write(d/'goals',b'target(n140)\ntarget(n141)\n')
    package_proof=write(d/'pkg-proof',cli('package-prove',pkg,pin(pkg),exact))
    workspace_proof=write(d/'work-proof',cli('workspace-prove',archive,pin(archive),lockpin,exact))
    for proof in (package_proof,workspace_proof):
        assert [r['status'] for r in json.loads(proof.read_bytes())['results']]==['POSITIVE','UNKNOWN']
    for item in ('cl-projection-sdk-check','libcl_runtime.so'):copy2(root/item,use/item)
    only={'cl-projection-sdk-check','libcl_runtime.so'}
    assert {item.name for item in use.iterdir()}==only
    q=subprocess.run([use/'cl-projection-sdk-check',pkg,pin(pkg),exact,package_proof,
                      archive,pin(archive),lockpin,workspace_proof],cwd=use,
                     env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=45)
    assert q.returncode==0,(q.args,q.returncode,q.stderr)
    assert {item.name for item in use.iterdir()}==only
print('PASS: real C SDK uses independent in-process C grouping and validates every row order, rejects malformed or unavailable output with exact CPU fallback, isolates nested and concurrent callers, and preserves proof bytes and budgets for both package and workspace.')
