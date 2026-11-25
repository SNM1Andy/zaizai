from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, re, subprocess, time

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
def pin(path):return sha256(path.read_bytes()).hexdigest()
def val(line,key):return re.search(fr'{key}=([a-z0-9]+)',line)[1]
def short(tool,*args,data=None):
    p=subprocess.run([tool,*args],input=data,capture_output=True,timeout=20)
    assert p.returncode==0,(p.args,p.returncode,p.stderr)
    return p.stdout
@contextmanager
def live(exe,*args):
    with subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def request(actor,s):
    actor.stdin.write(s+'\n');actor.stdin.flush()
    row=actor.stdout.readline().strip()
    assert row,(s,actor.poll())
    return row
def settle(p):
    p.stdin.write('sample(alpha)\n');p.stdin.flush()
    for _ in range(30):
        if p.stdout.readline().strip().startswith('POSITIVE plus=obs:signal'):return
    raise AssertionError('writer did not finish')
def read(state,command,ok=True,binary=alpha):
    r=json.loads(short(binary,'--read-channel',state,data=f'r {command}\n'.encode()))
    assert r['ok']==ok,(command,r)
    return r['payload' if ok else 'error']
def selected(decision):return decision['options'][decision['selected']]['kind']

with TemporaryDirectory(prefix='PCGM real retained choices with later observations ') as tmp:
    d=Path(tmp)
    source=d/'seed.cl'
    source.write_text((root/'fixtures/producer.cl').read_text()+"""
: trusted(sym).
: phase(sym).
: marked(sym).
& mark marked(initial).
trusted(alpha).
!trusted($x) <- monitor($x) & phase(repair).
| hard positive trusted(alpha).
| wish positive monitor(alpha).
""")
    state=d/'state'
    with live(alpha,'--init-managed',source,state) as writer:
        who=val(writer.stdout.readline(),'individual')
        plan=re.search(r'plan_ready (\w+)',request(writer,':plan'))[1]
        settle(writer)
        assert 'revision_applied' in request(writer,':apply '+plan)
        settle(writer)
        job=json.loads(request(writer,':choice_job_start'))
        deadline=time.monotonic()+12
        while True:
            result=json.loads(request(writer,':choice_job_collect '+job['id']))
            if result['phase']=='ready':break
            assert time.monotonic()<deadline,result
            time.sleep(.001)
        historical=json.loads(request(writer,':choice_job_commit_explained '+job['id']))
        assert historical['status']=='stay' and selected(historical)=='stay'
        old_head=pin(state)
        simple=read(state,f"choice_reassess {job['id']} {old_head}")
        assert simple['committable'] is False and simple['observation_changes']==[]
        assert simple['original']==historical and simple['reassessed']['options']==historical['options']
        assert 'observed released' in request(writer,':observe released phase(repair)')
        assert 'withdrawn mark' in request(writer,':withdraw mark')
        assert 'observed later' in request(writer,':observe later sample(gamma)')
        assert 'CONFLICT' in request(writer,'trusted(alpha)')
        assert 'POSITIVE' in request(writer,'monitor(alpha)')
        current=pin(state)
        report=read(state,f"choice_reassess {job['id']} {current}")
        assert pin(state)==current and report['original']==historical and report['status']=='verified'
        assert report['committable'] is False and selected(report['reassessed'])=='rollback',report
        assert report['reassessed']['status']=='recommended' and report['head_sha256']==current
        assert [x['kind'] for x in report['reassessed']['options']]==[x['kind'] for x in historical['options']]
        options={row['kind']:row for row in report['reassessed']['options']}
        assert options['stay']['blocked_reason']=='hard objective not met' and options['rollback']['eligible']
        assert any(x['goal']['predicate']=='trusted' and x['before']=='CONFLICT' and x['after']=='POSITIVE'
                   for x in options['rollback']['criteria']),options
        assert report['observation_changes']==[
            {'id':'later','fact':'sample(gamma)','active':True,'added':True},
            {'id':'mark','fact':'marked(initial)','active':False,'added':False},
            {'id':'released','fact':'phase(repair)','active':True,'added':True}]
        assert 'head digest mismatch' in read(state,f"choice_reassess {job['id']} {old_head}",ok=False)
        archival=Path(str(state)+'.episodes')/(report['basis_sha256']+'.snap')
        payload=archival.read_bytes()
        archival.write_bytes(payload[:-1])
        assert 'snapshot digest mismatch' in read(state,f"choice_reassess {job['id']} {current}",ok=False)
        archival.write_bytes(payload)
        assert pin(state)==current
        writer.kill();assert writer.wait(timeout=5)<0
    with live(alpha,'--resume',state) as writer:
        assert val(writer.stdout.readline(),'individual')==who
        assert read(state,f"choice_reassess {job['id']} {pin(state)}")==report
        ready=short(beta,'--prepare',state).decode()
        moved=request(writer,':handoff beta '+val(ready,'binary_sha256')+' '+val(ready,'snapshot_sha256'))
        assert moved.startswith('handoff_prepared') and writer.wait(timeout=10)==0
    with live(beta,'--claim',state,val(moved,'nonce')) as writer:
        assert val(writer.stdout.readline(),'individual')==who
        later_head=pin(state)
        observed=read(state,f"choice_reassess {job['id']} {later_head}",binary=beta)
        assert observed=={**report,'head_sha256':later_head},observed
        assert 'CONFLICT' in request(writer,'trusted(alpha)')
        assert 'POSITIVE' in request(writer,'sample(gamma)')
        assert 'UNKNOWN' in request(writer,'marked(initial)')
        assert pin(state)==later_head
        current_decision=json.loads(request(writer,':decide_versions_parallel_json'))['decision']
        assert current_decision['status']=='committed' and selected(current_decision)=='rollback',current_decision
        assert 'POSITIVE' in request(writer,'trusted(alpha)')
        assert 'POSITIVE' in request(writer,'sample(gamma)')
        assert 'UNKNOWN' in request(writer,'monitor(alpha)')
        updated=read(state,f"choice_reassess {job['id']} {pin(state)}",binary=beta)
        assert updated=={**report,'head_sha256':pin(state)}
print('PASS: real PCGM replays identical retained alternatives with later durable observations, recommends a previously losing rollback without applying it, removes withdrawn facts uniformly, pins both states, stays exact after SIGKILL and A/B, and a fresh live PCGM comparison independently commits rollback without discarding later evidence.')
