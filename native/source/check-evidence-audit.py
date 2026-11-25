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
    with live('evidence-init',*args) as writer, live('evidence-audit',*args) as observer:
        issue(writer,"view") # Wait for initial durable write before the independent reader.
        original=state.read_bytes()
        exact=read(observer,'snapshot latest')
        assert exact['snapshot_sha256']==digest(original) and exact['revision']==0
        assert read(observer,'batch latest tx',False)['error'].startswith('unknown read-only')
        assert state.read_bytes()==original
        one=issue(writer,'batch zfirst 0 ; observe positive sample(x)')
        issue(writer,'observe 1 unused spare(any)')
        two=issue(writer,'batch asecond 2 ; observe cost claims(coal,extra,25@cny_cent)')
        revised=state.read_bytes()
        lookup=read(observer,'receipt latest zfirst')
        assert lookup['result']==one and lookup['revision']==3
        assert read(observer,'snapshot '+exact['snapshot_sha256'],False)['error'].startswith('CL evidence audit snapshot changed')
        pin_revision=lookup['snapshot_sha256']
        page=read(observer,'feed '+pin_revision+' 0 1')['result']
        assert page=={'events':[one],'next_cursor':1,'more':True}
        assert read(observer,'feed '+pin_revision+' 1 1')['result']=={'events':[two],'next_cursor':3,'more':False}
        assert read(observer,'feed '+pin_revision+' 3 1')['result']=={'events':[],'next_cursor':3,'more':False}
        assert read(observer,'receipt latest missing')['result']['status']=='not_recorded'
        assert state.read_bytes()==revised
        writer.kill();assert writer.wait(timeout=5)<0
        assert read(observer,'feed '+pin_revision+' 0 2')['result']['events']==[one,two]

    relocated=d/'relocated';relocated.mkdir()
    copy=relocated/'foreign'
    copy.write_bytes(state.read_bytes())
    with live('evidence-audit',bundle,pin,goals,copy) as observer:
        assert read(observer,'receipt '+pin_revision+' asecond')['result']==two
        assert not (relocated/'foreign.lock').exists()
        displaced=d/'moved';relocated.rename(displaced)
        assert 'directory moved' in read(observer,'snapshot latest',False)['error']
    broken=d/'broken';broken.write_bytes(state.read_bytes()[:-1]+b'!')
    with live('evidence-audit',bundle,pin,goals,broken) as observer:
        assert 'digest mismatch' in read(observer,'receipt latest zfirst',False)['error']
        assert not (d/'broken.lock').exists()
    assert digest(bundle.read_bytes())==pin
print('PASS: independent native CL audit observes exact chronological commits alongside a live writer, pins pages, refuses stale/corrupt revisions, never creates locks, and reads exact receipts after writer SIGKILL and copy.')
