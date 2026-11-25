from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, re, subprocess

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
def pin(path):return sha256(path.read_bytes()).hexdigest()
def val(row,key):return re.search(fr'{key}=([a-z0-9]+)',row)[1]
def call(tool,*args,data=None):
    p=subprocess.run([tool,*args],input=data,capture_output=True,timeout=20)
    assert p.returncode==0,(p.args,p.returncode,p.stderr,p.stdout)
    return p.stdout
@contextmanager
def open_actor(tool,*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def issue(actor,s):
    actor.stdin.write(s+'\n');actor.stdin.flush()
    row=actor.stdout.readline().strip()
    assert row,(s,actor.poll())
    return row
def read(state,request):
    reply=json.loads(call(beta,'--read-channel',state,data=('t '+request+'\n').encode()))
    assert reply['ok'],reply
    return reply['payload']
def transfer(state,actor):
    ready=call(beta,'--prepare',state).decode()
    moved=issue(actor,':handoff beta '+val(ready,'binary_sha256')+' '+val(ready,'snapshot_sha256'))
    assert moved.startswith('handoff_prepared') and actor.wait(timeout=10)==0,moved
    return val(moved,'nonce')
with TemporaryDirectory(prefix='native choice queue ownership continuity ') as temp:
    d=Path(temp)
    seed=d/'seed.cl'
    seed.write_text((root/'fixtures/producer.cl').read_text()+'''
: later(sym).
stable(run).
| hard positive stable(run).
| wish positive monitor(alpha).
''')
    cases=[(d/'one','d'+'1'*32,'clean'),(d/'two','d'+'2'*32,'pre_change'),(d/'three','d'+'3'*32,'post_change')]
    for state,id,mode in cases:
        with open_actor(alpha,'--init-managed',seed,state) as actor:
            who=val(actor.stdout.readline(),'individual')
            old=val(issue(actor,':queue_choice '+id),'basis_sha256')
            if mode=='pre_change':
                assert 'observed injected' in issue(actor,':observe injected later(keep)')
            harvested=transfer(state,actor)
        with open_actor(beta,'--claim',state,harvested) as actor:
            assert val(actor.stdout.readline(),'individual')==who
            p=pin(state)
            assert read(state,'choice_intent '+id)['status']=='stale'
            assert 'choice intent is stale' in issue(actor,':run_queued_choice '+id) and pin(state)==p
            bind=lambda expected: ':rebind_queued_choice '+id+' '+old+' '+expected
            assert 'head changed' in issue(actor,bind('0'*64)) and pin(state)==p
            if mode=='pre_change':
                assert 'requires only completed native handoffs' in issue(actor,bind(p))
                assert pin(state)==p and 'POSITIVE' in issue(actor,'later(keep)')
                assert 'choice_intent_cancelled' in issue(actor,':cancel_queued_choice '+id)
                continue
            episode=Path(str(state)+'.episodes')/(old+'.snap')
            original=episode.read_bytes()
            episode.write_bytes(original[:-1])
            assert 'snapshot digest mismatch' in issue(actor,bind(p)) and pin(state)==p
            episode.write_bytes(original)
            assert issue(actor,bind(p)).startswith('choice_intent_rebound')
            q=read(state,'choice_intent '+id)
            assert q['status']=='queued' and q['initial_basis_sha256']==old and q['bound_basis_sha256']==p
            assert read(state,'choice_receipt '+id)['status']=='not_recorded'
            assert 'UNKNOWN' in issue(actor,'monitor(alpha)')
            if mode=='post_change':
                assert 'observed after' in issue(actor,':observe after later(fresh)')
                guard=pin(state)
                assert read(state,'choice_intent '+id)['status']=='stale'
                assert 'choice intent is stale' in issue(actor,':run_queued_choice '+id)
                assert pin(state)==guard and 'POSITIVE' in issue(actor,'later(fresh)')
                continue
            stamp=pin(state)
            actor.kill();assert actor.wait(timeout=5)<0
        wrong=subprocess.run([alpha,'--resume',state],capture_output=True,timeout=10)
        assert wrong.returncode!=0 and pin(state)==stamp,wrong
        with open_actor(beta,'--resume',state) as actor:
            assert val(actor.stdout.readline(),'individual')==who
            assert pin(state)==stamp and read(state,'choice_intent '+id)==q
            rebound_file=Path(str(state)+'.episodes')/(p+'.snap')
            intact=rebound_file.read_bytes()
            rebound_file.write_bytes(intact[:-1])
            assert 'snapshot digest mismatch' in issue(actor,':run_queued_choice '+id)
            assert pin(state)==stamp
            rebound_file.write_bytes(intact)
            receipt=issue(actor,':run_queued_choice '+id)
            assert json.loads(receipt)['status']=='committed'
            frozen=pin(state)
            assert receipt==issue(actor,':run_queued_choice '+id) and pin(state)==frozen
            assert read(state,'choice_intent '+id)['status']=='completed'
            assert 'pending choice and initial basis do not match' in issue(actor,bind(frozen))
            assert 'POSITIVE' in issue(actor,'monitor(alpha)')
            actor.kill();assert actor.wait(timeout=5)<0
        dest=d/'export'
        assert b'transfer_exported' in call(beta,'--export-complete',state,dest)
        assert f'episode {old}' in (dest/'TRANSFER').read_text()
        assert f'episode {p}' in (dest/'TRANSFER').read_text()
        separate=d/'staged'
        assert b'activation=required' in call(beta,'--restore-copy',dest,separate)
        assert read(separate,'choice_intent '+id)==read(state,'choice_intent '+id)
        assert read(separate,'choice_receipt '+id)==read(state,'choice_receipt '+id)
print('PASS: native pending PCGM intent explicitly crosses a real owner-only handoff, fails closed on semantic history or tampered basis, survives forced restart, runs exactly once and exports both exact bases.')
