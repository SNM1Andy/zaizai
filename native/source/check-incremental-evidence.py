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
        first=issue(actor,'view')
        assert summary(first)==[(['UNKNOWN'],1),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)],first
        invoke('evidence-resume',*args,code=1,error=b'already has a writer')
        change=issue(actor,'observe 0 fresh sample(x)')
        assert summary(change)==[(['POSITIVE'],2),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)]
        assert 'stale' in issue(actor,'observe 0 delayed sample(x)',False)
        change=issue(actor,'observe 1 opposed !sample(x)')
        assert summary(change)==[(['CONFLICT'],3),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)]
        change=issue(actor,'withdraw 2 fresh')
        assert summary(change)==[(['NEGATIVE'],4),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)]
        change=issue(actor,'restore 3 fresh')
        assert summary(change)==[(['CONFLICT'],5),(['POSITIVE'],1),(['POSITIVE','UNKNOWN'],1)]
        held=state.read_bytes()
        assert 'type' in issue(actor,'observe 4 incorrect claims(coal,later,25@hour)',False)
        assert state.read_bytes()==held
        change=issue(actor,'observe 4 addition claims(coal,later,25@cny_cent)')
        assert summary(change)==[(['CONFLICT'],5),(['POSITIVE'],1),(['UNKNOWN','POSITIVE'],2)]
        change=issue(actor,'observe 5 irrelevant spare(x)')
        assert summary(change)==[(['CONFLICT'],5),(['POSITIVE'],1),(['UNKNOWN','POSITIVE'],2)]
        held=state.read_bytes()
        assert issue(actor,'check')==change and issue(actor,'observe 6 irrelevant spare(x)')==change
        assert state.read_bytes()==held
        actor.kill();assert actor.wait(timeout=5)<0
    changed_goals=d/'other';changed_goals.write_text('warning(ok)\n')
    invoke('evidence-resume',bundle,pin,changed_goals,state,code=1,error=b'goal identity')
    with live('evidence-resume',*args) as actor:
        recovered=issue(actor,'check')
        assert recovered['revision']==6 and recovered['rows']==4
        assert [x['results'] for x in recovered['planes']]==[x['results'] for x in change['planes']]
        assert summary(issue(actor,'withdraw 6 opposed'))==[(['POSITIVE'],2),(['POSITIVE'],1),(['UNKNOWN','POSITIVE'],1)]
    corrupted=d/'corrupted'
    corrupted.write_bytes(state.read_bytes()[:-1]+b'!')
    invoke('evidence-resume',bundle,pin,goals,corrupted,code=1,error=b'journal digest mismatch')
    assert digest(bundle.read_bytes())==pin
print('PASS: standalone native CL keeps immutable package, recalculates only touched dependency planes including typed folds, matches full fresh proof byte-for-byte, and preserves exact observations across SIGKILL.')
