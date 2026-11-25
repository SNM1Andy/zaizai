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
    for k in ('libcl_runtime.so','cl-frozen-sdk-check'):
        shutil.copy2(root/k,install/k)
    with live('evidence-init',*args) as writer:
        issue(writer,'batch gathered 0 ; observe independent sample(x) ; observe change claims(coal,fresh,25@cny_cent)')
        snapshot=digest(state.read_bytes())
        (install/'artifact').write_bytes(invoke('evidence-freeze',bundle,pin,goals,state,snapshot))
        trusted=digest((install/'artifact').read_bytes())
        expected=invoke('evidence-frozen-verify',install/'artifact',trusted,pin,snapshot)
        (install/'expected').write_bytes(expected)
    for member,name in ((bundle,'package'),(goals,'goals'),(state,'journal')):
        shutil.move(member,install/name)
    assert not (install/'cl').exists() and not (install/'pcgm-alpha').exists()
    output=subprocess.check_output([install/'cl-frozen-sdk-check',pin,snapshot,trusted],cwd=install,
                                   env={'PATH':'','LC_ALL':'C'},timeout=20)
    assert output==b'independent native C proof fixture passed\n'
print('PASS: relocated real native C executable does 12 concurrent independent frozen evidence seal/verify pairs across four threads, exact CLI bytes, rejects wrong pins/aliases, without CLI or PCGM installed.')
