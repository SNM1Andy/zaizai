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

with TemporaryDirectory(prefix='PCGM choice attribution to exact later observations ') as tmp:
    d=Path(tmp)
    source=d/'seed.cl'
    source.write_text((root/'fixtures/producer.cl').read_text()+"""
: trusted(sym).
: phase(sym).
: indicator(sym).
trusted(alpha).
!trusted($x) <- monitor($x) & phase(repair).
!trusted($x) <- monitor($x) & phase(partial) & indicator(verified).
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
        unknown='d'+'0'*32
        assert read(state,f"choice_attribution {unknown} {old_head}")['status']=='not_recorded'
        base=read(state,f"choice_attribution {job['id']} {old_head}")
        assert base['status']=='verified' and not base['committable'] and not base['changed']
        assert base['change_ids']==base['minimal_sufficient_sets']==[]
        assert len(base['replays'])==1 and base['baseline']==base['full']
        simple=read(state,f"choice_reassess {job['id']} {old_head}")
        assert simple['committable'] is False and simple['observation_changes']==[]
        assert simple['original']==historical and simple['reassessed']['options']==historical['options']
        assert 'observed released' in request(writer,':observe released phase(repair)')
        assert 'observed left' in request(writer,':observe left phase(partial)')
        assert 'observed right' in request(writer,':observe right indicator(verified)')
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
            {'id':'left','fact':'phase(partial)','active':True,'added':True},
            {'id':'released','fact':'phase(repair)','active':True,'added':True},
            {'id':'right','fact':'indicator(verified)','active':True,'added':True}]
        attribution=read(state,f"choice_attribution {job['id']} {current}")
        assert attribution['status']=='verified' and not attribution['committable'] and attribution['changed']
        assert attribution['scope']=='net_observations_only' and attribution['individual']==who
        assert attribution['basis_sha256']==report['basis_sha256']
        assert attribution['original_receipt_sha256']==report['original_receipt_sha256']
        assert attribution['baseline']['kind']=='stay' and attribution['full']['kind']=='rollback'
        assert attribution['change_ids']==['later','left','released','right']
        assert attribution['minimal_sufficient_sets']==[['released'],['left','right']]
        replay={tuple(x['include']):x['choice']['kind'] for x in attribution['replays']}
        assert len(replay)==16 and replay[('later',)]=='stay'
        assert replay[('left',)]==replay[('right',)]=='stay'
        assert replay[('left','right')]==replay[('released',)]=='rollback'
        assert 'head digest mismatch' in read(state,f"choice_attribution {job['id']} {old_head}",ok=False)
        assert 'head digest mismatch' in read(state,f"choice_reassess {job['id']} {old_head}",ok=False)
        archival=Path(str(state)+'.episodes')/(report['basis_sha256']+'.snap')
        payload=archival.read_bytes()
        archival.write_bytes(payload[:-1])
        assert 'snapshot digest mismatch' in read(state,f"choice_reassess {job['id']} {current}",ok=False)
        assert 'snapshot digest mismatch' in read(state,f"choice_attribution {job['id']} {current}",ok=False)
        archival.write_bytes(payload)
        assert pin(state)==current
        writer.kill();assert writer.wait(timeout=5)<0
    with live(alpha,'--resume',state) as writer:
        assert val(writer.stdout.readline(),'individual')==who
        assert read(state,f"choice_reassess {job['id']} {pin(state)}")==report
        assert read(state,f"choice_attribution {job['id']} {pin(state)}")==attribution
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
        assert read(state,f"choice_attribution {job['id']} {later_head}",binary=beta)=={**attribution,'head_sha256':later_head}
        assert pin(state)==later_head
        current_decision=json.loads(request(writer,':decide_versions_parallel_json'))['decision']
        assert current_decision['status']=='committed' and selected(current_decision)=='rollback',current_decision
        assert 'POSITIVE' in request(writer,'trusted(alpha)')
        assert 'POSITIVE' in request(writer,'sample(gamma)')
        assert 'UNKNOWN' in request(writer,'monitor(alpha)')
        updated=read(state,f"choice_reassess {job['id']} {pin(state)}",binary=beta)
        assert updated=={**report,'head_sha256':pin(state)}
        assert read(state,f"choice_attribution {job['id']} {pin(state)}",binary=beta)=={**attribution,'head_sha256':pin(state)}
        extra=request(writer,':observe attribution_fifth sample(delta)');assert 'observed attribution_fifth' in extra,extra
        new_head=pin(state)
        assert 'at most four' in read(state,f"choice_attribution {job['id']} {new_head}",ok=False,binary=beta)
        assert pin(state)==new_head
print('PASS: PCGM attributes a later changed recommendation to exact minimal evidence subsets under the original comparator; jointly sufficient observations, alternatives, and unrelated evidence remain distinguishable across strong recovery without committing through the diagnostic.')
