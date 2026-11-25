from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, re, subprocess, time

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
def short(binary,*args,data=b''):
    out=subprocess.run([binary,*args],input=data,capture_output=True,timeout=25)
    assert out.returncode==0,(out.args,out.returncode,out.stderr)
    return out.stdout
def val(s,name):return re.search(fr'{name}=([a-z0-9]+)',s)[1]
@contextmanager
def live(binary,*args):
    with subprocess.Popen([binary,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def start(p,value):
    p.stdin.write(value+'\n');p.stdin.flush()
def cmd(p,value):
    start(p,value)
    row=p.stdout.readline()
    assert row,(value,p.poll())
    return row
def read(state,query):
    response=json.loads(short(alpha,'--read-channel',state,data=('r '+query+'\n').encode()))
    assert response['ok'],response
    return response['payload']
def pin(state):return sha256(state.read_bytes()).hexdigest()

with TemporaryDirectory(prefix='real restart durable PCGM pending intent ') as work:
    d=Path(work)
    seed=d/'seed.cl'
    seed.write_text((root/'fixtures/producer.cl').read_text()+"""
: later(sym).
stable(run).
| hard positive stable(run).
| wish positive monitor(alpha).
""")
    state=d/'state'
    stale,runid,other=('d'+str(x)*32 for x in range(1,4))
    with live(alpha,'--init-managed',seed,state) as writer:
        uid=val(writer.stdout.readline(),'individual')
        assert read(state,'choice_intent '+stale)['status']=='not_recorded'
        initial=pin(state)
        assert 'choice_intent_queued' in cmd(writer,':queue_choice '+stale)
        open_state=state.read_bytes()
        assert 'choice_intent_unchanged' in cmd(writer,':queue_choice '+stale)
        assert state.read_bytes()==open_state
        assert read(state,'choice_intent '+stale)=={
            'schema':'pcgm-choice-intent-v1','id':stale,'status':'queued','initial_basis_sha256':initial}
        assert 'another choice is active' in cmd(writer,':queue_choice '+other)
        assert 'durable choice intent is already active' in cmd(writer,':choice_job_start')
        assert 'observed injected' in cmd(writer,':observe injected later(keep)')
        fresh_pin=pin(state)
        assert read(state,'choice_intent '+stale)['status']=='stale'
        assert 'choice intent is stale' in cmd(writer,':run_queued_choice '+stale) and pin(state)==fresh_pin
        assert 'choice_intent_cancelled' in cmd(writer,':cancel_queued_choice '+stale)
        cancelled=pin(state)
        assert 'choice_intent_cancelled' in cmd(writer,':cancel_queued_choice '+stale) and pin(state)==cancelled
        assert read(state,'choice_intent '+stale)['status']=='cancelled'
        assert 'choice intent has been cancelled' in cmd(writer,':run_queued_choice '+stale)
        assert 'choice_intent_queued' in cmd(writer,':queue_choice '+runid)
        queued=pin(state)
        writer.kill();assert writer.wait(timeout=5)<0
    with live(alpha,'--resume',state) as writer:
        assert val(writer.stdout.readline(),'individual')==uid
        assert pin(state)==queued and read(state,'choice_intent '+runid)['status']=='queued'
        assert 'UNKNOWN' in cmd(writer,'monitor(alpha)')
        intent=read(state,'choice_intent '+runid)
        episode=Path(str(state)+'.episodes')/(intent['initial_basis_sha256']+'.snap')
        original=episode.read_bytes()
        episode.write_bytes(original[:-1])
        assert 'snapshot digest mismatch' in cmd(writer,':run_queued_choice '+runid) and pin(state)==queued
        episode.write_bytes(original)
        start(writer,':run_queued_choice '+runid)
        deadline=time.monotonic()+12
        while pin(state)==queued:
            assert time.monotonic()<deadline
            time.sleep(.001)
        record=read(state,'choice_receipt '+runid)
        assert record['status']=='committed' and record['basis_sha256']==queued
        completed=pin(state)
        writer.kill();assert writer.wait(timeout=5)<0
    with live(alpha,'--resume',state) as writer:
        assert val(writer.stdout.readline(),'individual')==uid
        one=cmd(writer,':run_queued_choice '+runid)
        assert one==cmd(writer,':run_queued_choice '+runid)
        assert json.loads(one)==record['decision'] and pin(state)==completed
        assert 'status=completed' in cmd(writer,':queue_choice '+runid) and pin(state)==completed
        assert 'completed choice intent cannot be cancelled' in cmd(writer,':cancel_queued_choice '+runid)
        basis=read(state,'choice_basis '+runid+'; monitor(alpha); later(keep)')
        assert basis['status']=='verified' and basis['decision']==record['decision']
        assert 'POSITIVE' in cmd(writer,'later(keep)') and 'POSITIVE' in cmd(writer,'monitor(alpha)')
        assert read(state,'choice_intent '+runid)['status']=='completed'
        ready=short(beta,'--prepare',state).decode()
        move=cmd(writer,':handoff beta '+val(ready,'binary_sha256')+' '+val(ready,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and writer.wait(timeout=10)==0
    with live(beta,'--claim',state,val(move,'nonce')) as writer:
        assert val(writer.stdout.readline(),'individual')==uid
        after=pin(state)
        assert one==cmd(writer,':run_queued_choice '+runid) and pin(state)==after
        assert read(state,'choice_receipt '+runid)==record
print('PASS: pending choice survives actual process termination, a writer correctly declines stale/cancelled intents, and committed execution is reconciled byte-identically without replay after hard exits and A/B.')
