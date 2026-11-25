from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import json
import subprocess
import struct

root=Path(__file__).resolve().parent
tool=root/'cl'
env={'PATH':'','LC_ALL':'C'}
def h(raw):return sha256(raw).hexdigest()
def binary(program,*args,expected=0,data=None,wd=None):
    done=subprocess.run([program,*args],env=env,cwd=wd,input=data,capture_output=True,timeout=20)
    assert done.returncode==expected,(done.args,done.returncode,done.stdout[:500],done.stderr[:500])
    return done
def put(path,value):
    path.write_bytes(value);return path
with TemporaryDirectory(prefix='native CL verified frontier ') as td:
    d=Path(td);isolated=d/'offline host';isolated.mkdir()
    host=copy2(root/'cl-checkpoint-audit-sdk-check',isolated/'consumer')
    copy2(root/'libcl_memory.so',isolated/'libcl_memory.so')
    src=put(d/'chain.cl',('module chain.\n: edge(sym,sym).\n: route(sym,sym).\n'
                            'route($a,$b) <- edge($a,$b).\n'
                            'route($a,$c) <- route($a,$b) & edge($b,$c).\n'+
                            ''.join(f'& e{i} edge(n{i},n{i+1}).\n' for i in range(43))).encode())
    lock=put(d/'lock',binary(tool,'lock',src).stdout)
    api=put(d/'clapi',binary(tool,'project-api',src,lock).stdout)
    pkg=put(d/'program.clpkg',binary(tool,'project-pack',src,lock,api).stdout)
    goals=put(d/'goals',b'route(n0,n43)\nroute(n43,n0)\n')
    for item in src,lock,api:item.unlink()
    args=pkg,h(pkg.read_bytes()),goals
    checkpoint=d/'current.clcpt'
    with subprocess.Popen([tool,'package-round-checkpoint',*args,checkpoint],
                       env=env,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
        assert json.loads(process.stdout.readline())['rounds']==0
        process.stdin.write('step 16\ncheckpoint\n');process.stdin.flush()
        partial=json.loads(process.stdout.readline())
        saved=json.loads(process.stdout.readline())
        assert partial['rounds']==16 and partial['status']=='running' and saved['state']==partial
        process.kill();assert process.wait(timeout=5)<0
    raw=checkpoint.read_bytes()
    digest=h(raw)
    assert digest==saved['sha256']
    report=binary(tool,'package-round-audit',*args,checkpoint,digest).stdout
    assert binary(host,'valid',*args,checkpoint,digest,wd=isolated).stdout==report
    metadata=json.loads(report)
    for k in ('rounds','facts','probes','indexed'):assert metadata[k]==partial[k]
    assert metadata['valid'] and 'proof' not in metadata and len(list(isolated.iterdir()))==2
    finished=binary(tool,'package-round-reopen-verified',*args,checkpoint,digest,data=b'finish\nproof\n').stdout
    expected=binary(tool,'package-prove',*args).stdout
    assert finished.splitlines(keepends=True)[-1]==expected
    package,inner,body=raw.split(b'\n',2)
    # Two fixtures preserve the envelope and hashes but describe inconsistent work.
    at=0
    for _ in range(2):at+=4+struct.unpack_from('>I',body,at)[0]
    def changed(offset,new):
        b=bytearray(body);struct.pack_into('>I',b,at+offset,new)
        return package+b'\n'+h(b).encode()+b'\n'+b
    count=struct.unpack_from('>I',body,at+20)[0]
    for fixture,reason in (
        (changed(20,count+1),b'independently recomputed prefix'),
        (changed(16,92),b'at or after fixpoint'),
    ):
        altered=put(d/'inconsistent.clcpt',fixture)
        p=h(fixture)
        assert reason in binary(tool,'package-round-audit',*args,altered,p,expected=1).stderr
        assert not binary(tool,'package-round-reopen-verified',*args,altered,p,expected=1).stdout
        failed=binary(host,'invalid',*args,altered,p,wd=isolated)
        assert not failed.stdout and reason in failed.stderr
    wrong=put(d/'other.goals',goals.read_bytes()+b'# different bytes\n')
    assert b'goals mismatch' in binary(tool,'package-round-audit',args[0],args[1],wrong,checkpoint,digest,expected=1).stderr
    assert b'resource limits mismatch' in binary(tool,'package-round-audit',*args,checkpoint,digest,'100',expected=1).stderr
    assert b'does not match supplied' in binary(tool,'package-round-audit',*args,checkpoint,'0'*64,expected=1).stderr
    assert checkpoint.read_bytes()==raw
print('PASS: native memory SDK independently audits exact recursive CL prefix after a killed writer, checked reopen continues canonical state to the same proof, and rehashed inconsistent checkpoints produce no answer.')
