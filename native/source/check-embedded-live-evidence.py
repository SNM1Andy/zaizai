from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def digest(raw):return sha256(raw).hexdigest()
def invoke(*args,code=0,error=b''):
    out=subprocess.run([cl,*args],capture_output=True,timeout=12)
    assert out.returncode==code and (code==0 or error in out.stderr),out
    return out.stdout
@contextmanager
def live(*args):
    with subprocess.Popen([cl,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as actor:
        try:yield actor
        finally:
            if actor.poll() is None:actor.kill();actor.wait(timeout=5)
def issue(actor,command,ok=True):
    actor.stdin.write('t '+command+'\n');actor.stdin.flush()
    raw=actor.stdout.readline()
    assert raw,(command,actor.poll())
    out=json.loads(raw)
    assert out['ok']==ok,(command,out)
    return out['payload'] if ok else out['error']
def summary(payload):
    return [([item['status'] for item in plane['results']],plane['evaluations']) for plane in payload['planes']]
def read(a,query,ok=True):
    a.stdin.write('reader '+query+'\n');a.stdin.flush()
    out=json.loads(a.stdout.readline())
    assert out['ok']==ok,(query,out)
    return out

with TemporaryDirectory(prefix='standalone incremental CL ') as temporary:
    d=Path(temporary)
    source=d/'module.cl'
    source.write_text("""module signal.
: sample(sym).
: accepted(sym).
: warning(sym).
: spare(sym).
: claims(sym,sym,qty(cny_cent)).
: total(sym,qty(cny_cent)).
accepted($x) <- sample($x).
!accepted($x) <- !sample($x).
total(coal,$sum) <- qty_fold_sum(claims,coal,$sum).
& marker warning(ok).
& original claims(coal,opening,25@cny_cent).
""")
    lock=d/'a.lock';lock.write_bytes(invoke('lock',source))
    api=d/'a.clapi';api.write_bytes(invoke('project-api',source,lock))
    bundle=d/'program.clpkg';bundle.write_bytes(invoke('project-pack',source,lock,api))
    pin=digest(bundle.read_bytes())
    for f in (source,lock,api):f.unlink()
    goals=d/'goals';goals.write_text('accepted(x)\nwarning(ok)\ntotal(coal,25@cny_cent)\ntotal(coal,50@cny_cent)\n')
    state=d/'session'
    args=bundle,pin,goals,state
    install=d/'app';install.mkdir()
    for k in ('libcl_runtime.so','cl-live-sdk-check'):
        shutil.copy2(root/k,install/k)
    for member,name in ((bundle,'package'),(goals,'goals')):
        shutil.copy2(member,install/name)
    assert not (install/'cl').exists() and not (install/'pcgm-alpha').exists()
    with subprocess.Popen([install/'cl-live-sdk-check',pin],cwd=install,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,env={'PATH':'','LC_ALL':'C'},text=True,bufsize=1) as native:
        start=json.loads(native.stdout.readline())
        assert start['ok'] and start['payload']['revision']==0
        issued=json.loads(native.stdout.readline())
        receipt=issued['payload']
        assert receipt['status']=='committed' and receipt['revision']==1
        audit=json.loads(subprocess.check_output([cl,'evidence-audit',bundle,pin,goals,install/'journal'],
                      input=b'cli receipt latest stable\n',timeout=5))
        assert audit['ok'] and audit['result']==receipt
        invoke('evidence-resume',bundle,pin,goals,install/'journal',code=1,error=b'already has a writer')
        native.stdin.write('r\n');native.stdin.flush()
        reopened=json.loads(native.stdout.readline())
        final=json.loads(native.stdout.readline())
        repeated=json.loads(native.stdout.readline())
        assert native.wait(timeout=5)==0
        assert reopened==issued and repeated['payload']=={**receipt,'status':'replayed'}
        assert final['payload']['revision']==1
        assert summary(final['payload'])==[(['POSITIVE'],1),(['POSITIVE'],1),(['UNKNOWN','POSITIVE'],1)]
    confirmation=json.loads(subprocess.check_output([cl,'evidence-resume',bundle,pin,goals,install/'journal'],
                           input=b'c check\n',timeout=5))
    assert confirmation==final
print('PASS: a true relocated C app modifies a CL journal in process with the same writer lease; independent CLI audit reads viable receipts live, CLI cannot open second writer, C reopens and recovers exact receipts, final full proof bytes match CLI.')
