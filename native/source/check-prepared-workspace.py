from hashlib import sha256
from pathlib import Path
from shutil import copy2,rmtree,which
from tempfile import TemporaryDirectory
import json
import os
import shlex
import subprocess

root=Path(__file__).resolve().parent
installed=Path(os.environ['CL_KIT_VALIDATION_ROOT']) if 'CL_KIT_VALIDATION_ROOT' in os.environ else None
cl=(installed/'bin/cl') if installed else root/'cl'
def call(exe,*args,cwd=None):
    p=subprocess.run([exe,*args],cwd=cwd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=40)
    assert p.returncode==0,(p.args,p.returncode,p.stdout[:300],p.stderr[:900])
    return p.stdout
def put(p,x):
    p.write_bytes(x.encode() if isinstance(x,str) else x)
    return p
def pin(f):
    return sha256(f.read_bytes()).hexdigest()
with TemporaryDirectory(prefix='detached immutable CL workspace C SDK ') as tmp:
    d=Path(tmp);sender=d/'publisher';sender.mkdir()
    lib=put(sender/'supply.cl','module supply.\nexport row.\n: row(sym).\n'+
        ''.join(f'& r{i} row(x{i}).\n' for i in range(1600)))
    liblock=put(sender/'library.lock',call(cl,'lock',lib))
    api=put(sender/'library.api',call(cl,'project-api',lib,liblock))
    package=put(sender/'supply.clpkg',call(cl,'project-pack',lib,liblock,api))
    deps=put(sender/'workspace.lock',f'CLWORK-1\nsupply supply.clpkg {pin(package)} -\n')
    lock=pin(deps)
    common='''module app.
use supply.
: first(sym).
: second(sym).
: output(sym).
first($v) <- supply::row($v).
second($v) <- first($v).
'''
    a=put(sender/'app_a.cl',common+'output($v) <- second($v).\n')
    b=put(sender/'app_b.cl',common+'output($v) <- second($v) & sym_ne($v,x0).\n')
    w1=put(d/'generation-a.clw',call(cl,'workspace-pack',a,deps,lock))
    w2=put(d/'generation-b.clw',call(cl,'workspace-pack',b,deps,lock))
    assert pin(w1)!=pin(w2)
    g1=put(d/'g1.txt','output(x0)\noutput(x1599)\noutput(missing)\n')
    g2=put(d/'g2.txt','second(x1)\noutput(x1200)\noutput("x1200")\n')
    p1=put(d/'a1.json',call(cl,'workspace-prove',w1,pin(w1),lock,g1))
    p2=put(d/'a2.json',call(cl,'workspace-prove',w1,pin(w1),lock,g2))
    p3=put(d/'b1.json',call(cl,'workspace-prove',w2,pin(w2),lock,g1))
    assert [r['status'] for r in json.loads(p1.read_bytes())['results']]==['POSITIVE','POSITIVE','UNKNOWN']
    assert [r['status'] for r in json.loads(p2.read_bytes())['results']]==['POSITIVE','POSITIVE','UNKNOWN']
    assert [r['status'] for r in json.loads(p3.read_bytes())['results']]==['UNKNOWN','POSITIVE','UNKNOWN']
    rmtree(sender)
    recipient=d/'host without CLI';recipient.mkdir()
    if installed:
        pkg_env={**os.environ,'PKG_CONFIG_PATH':'','PKG_CONFIG_LIBDIR':str(installed/'lib/pkgconfig')}
        sdk_flags=subprocess.check_output([which('pkg-config'),'--cflags','--libs','CLMemory'],env=pkg_env,text=True)
        executable=recipient/'check'
        subprocess.run([which('cc'),'-std=c11','-Wall','-Wextra','-Werror','-pthread',
            installed/'share/cl/examples/prepared-workspace-host.c','-o',executable,
            *shlex.split(sdk_flags),'-Wl,-rpath,$ORIGIN'],check=True,capture_output=True)
        copy2(installed/'lib/libcl_memory.so',recipient)
    else:
        executable=copy2(root/'cl-prepared-workspace-sdk-check',recipient/'check')
        copy2(root/'libcl_memory.so',recipient)
    results=json.loads(call(executable,w1,pin(w1),lock,w2,pin(w2),g1,p1,g2,p2,p3,cwd=recipient))
    assert results['archive_bytes']==w1.stat().st_size and results['samples']==15
    assert all(results[k]>0 for k in ('prepare_ns','oneshot_median_ns','prepared_median_ns'))
    assert sorted(x.name for x in recipient.iterdir())==['check','libcl_memory.so']
    print('BENCHMARK: '+json.dumps(results,sort_keys=True))
print('PASS: native CL prepares a full bounded pinned workspace once, gives byte-identical proofs across distinct immutable generations and six concurrent detached C readers after releasing archive input buffers, and refuses wrong pins, type and incomplete budgets.')
