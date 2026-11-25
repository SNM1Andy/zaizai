from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
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
    release=d/'evidence.clef'
    verify_dir=d/'external_auditor';verify_dir.mkdir()
    external=verify_dir/release.name
    with live('evidence-init',*args) as writer, live('evidence-audit',*args) as observer:
        issue(writer,"view") # Wait for initial durable write.
        initial=read(observer,'snapshot latest')['snapshot_sha256']
        original=invoke('evidence-freeze',bundle,pin,goals,state,initial)
        first=issue(writer,'batch intake 0 ; observe admitted sample(x) ; observe income claims(coal,extra,25@cny_cent)')
        assert first['revision']==1
        after=read(observer,'snapshot latest')['snapshot_sha256']
        payload=invoke('evidence-freeze',bundle,pin,goals,state,after)
        assert payload!=original and payload.startswith(b'CLEF-1\n')
        assert invoke('evidence-freeze',bundle,pin,goals,state,after)==payload
        invoke('evidence-freeze',bundle,pin,goals,state,initial,code=1,error=b'snapshot pin mismatch')
        release.write_bytes(payload)
        external.write_bytes(payload)
        issue(writer,'withdraw 1 admitted')
        final=read(observer,'snapshot latest')['snapshot_sha256']
        assert final!=after
        invoke('evidence-frozen-verify',external,digest(payload),pin,final,code=1,error=b'snapshot pin mismatch')
        actor=writer;actor.kill();assert actor.wait(timeout=5)<0
    bundle.unlink();goals.unlink();state.unlink();release.unlink()
    prove=invoke('evidence-frozen-verify',external,digest(payload),pin,after)
    report=json.loads(prove)
    assert report['context']['revision']==1 and report['context']['snapshot_sha256']==after
    assert [x['status'] for x in report['results']]==['POSITIVE','POSITIVE','UNKNOWN','POSITIVE']
    assert 'live_admitted' in prove.decode() and 'live_income' in prove.decode()
    invoke('evidence-frozen-verify',external,'f'*64,pin,after,code=1,error=b'artifact pin mismatch')
    broken=verify_dir/'repacked.clef'
    body=payload.split(b'\n',2)[2]
    assert b'"status":"POSITIVE"' in body
    forged=body.replace(b'"status":"POSITIVE"',b'"status":"NEGATIVE"',1)
    rebuilt=b'CLEF-1\n'+digest(forged).encode()+b'\n'+forged
    broken.write_bytes(rebuilt)
    invoke('evidence-frozen-verify',broken,digest(rebuilt),pin,after,code=1,error=b'proof differs from independent')
    broken.write_bytes(payload[:-1])
    invoke('evidence-frozen-verify',broken,digest(payload[:-1]),pin,after,code=1,error=b'artifact digest mismatch')
print('PASS: frozen standalone CL artifact reconstructs exact signed goals in another directory after writer exit and removal of originals, distinguishes later revisions, rejects stale pins, dishonest claims and truncation.')
