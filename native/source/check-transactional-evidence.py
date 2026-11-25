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
    with live('evidence-init',*args) as actor:
        before=issue(actor,'observe 0 marker spare(first)')
        assert before['revision']==1 and state.read_bytes().startswith(b'CLES-1\n')
        same=state.read_bytes()
        assert issue(actor,'receipt tx')['status']=='not_recorded'
        bad='batch tx 1 ; observe pass sample(x) ; observe fail claims(coal,later,25@hour)'
        assert 'type' in issue(actor,bad,False)
        assert state.read_bytes()==same and issue(actor,'view')==before
        body='batch tx 1 ; observe pass sample(x) ; observe second sample(y) ; observe cost claims(coal,later,25@cny_cent)'
        receipt=issue(actor,body)
        assert receipt['status']=='committed' and receipt['revision']==2 and receipt['edits']==3
        assert receipt['basis_sha256']==digest(same)
        assert state.read_bytes().startswith(b'CLES-2\n')
        result=issue(actor,'check')
        assert result['rows']==4 and result['revision']==2
        assert summary(result)==[(['POSITIVE'],2),(['POSITIVE'],1),(['UNKNOWN','POSITIVE'],2)]
        assert issue(actor,'receipt tx')==receipt
        assert issue(actor,body)=={**receipt,'status':'replayed'}
        assert 'different bytes' in issue(actor,body.replace('25@cny_cent','27@cny_cent'),False)
        later=issue(actor,'withdraw 2 pass')
        assert later['revision']==3 and issue(actor,'receipt tx')==receipt
        # Send another revision and intentionally never read stdout. Poll the journal for the durable boundary, then kill.
        another='batch follow 3 ; observe recovered sample(x) ; withdraw cost'
        actor.stdin.write('old '+another+'\n');actor.stdin.flush()
        import time
        for _ in range(100):
            if b'follow' in state.read_bytes():break
            time.sleep(0.01)
        else:raise AssertionError('second batch never reached stable storage')
        actor.kill();assert actor.wait(timeout=5)<0
    with live('evidence-resume',*args) as actor:
        assert issue(actor,'receipt tx')==receipt
        follow=issue(actor,'receipt follow')
        assert follow['status']=='committed' and follow['revision']==4
        assert issue(actor,another)=={**follow,'status':'replayed'}
        assert summary(issue(actor,'check'))==[(['POSITIVE'],1),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)]
        assert issue(actor,'receipt absent')['status']=='not_recorded'
    broken=d/'broken';broken.write_bytes(state.read_bytes()[:-1]+b'!')
    invoke('evidence-resume',bundle,pin,goals,broken,code=1,error=b'journal digest mismatch')
    assert digest(bundle.read_bytes())==pin
print('PASS: independent CL upgrades old journal only at valid compound commit, persists exact receipt with single coherent revision, recomputes affected proof planes once, refuses malformed or conflicting reuse, and recovers unread receipt after actual process kill.')
