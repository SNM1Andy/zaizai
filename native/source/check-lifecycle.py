from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess,json,re
home=Path(__file__).resolve().parent
cl,pcgm=home/'cl',home/'pcgm-alpha'
def h(data):return sha256(data).hexdigest()
def run(exe,*args,data=b'',ok=0,wd=None):
    p=subprocess.run([exe,*args],input=data,cwd=wd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=20)
    assert p.returncode==ok,(p.args,p.returncode,p.stdout[:100],p.stderr[:500])
    return p.stdout
@contextmanager
def live(exe,*args,wd=None):
    p=subprocess.Popen([exe,*args],cwd=wd,env={'PATH':'','LC_ALL':'C'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:yield p
    finally:
        if p.poll() is None:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def issue(p,command):
    p.stdin.write(command+'\n');p.stdin.flush()
    ans=p.stdout.readline().strip();assert ans,(command,p.poll());return ans
alpha,beta=home/'pcgm-alpha',home/'pcgm-beta'
def val(row,key):
    return re.search(fr'(?:^| ){key}=([0-9a-z]+)',row)[1]
with TemporaryDirectory(prefix='same individual across native compiler and runtime updates ') as folder:
    d=Path(folder);inputs=d/'build_inputs';inputs.mkdir();incoming=d/'incoming';incoming.mkdir()
    names=('plan.clcp','plan.cl','plan.generator.cl','plan.scope')
    profile=d/'build_inputs'/names[0];profile.write_bytes((home/'profiles'/'standard.clcp').read_bytes())
    base=d/'build_inputs'/names[1];base.write_bytes((home/'fixtures'/'base.cl').read_bytes())
    gen=d/'build_inputs'/names[2];g=(home/'fixtures'/'generator.cl').read_text().replace('& a21 amount_cfg(balance,2,1,10000).\n','')
    gen.write_text(g+': budget_hint(i64).\namount_cfg(balance,2,1,$n) <- budget_hint($n).\n')
    scope=d/'build_inputs'/names[3];scope.write_text((home/'fixtures'/'bounded.scope').read_text()+'evidence budget_hint\n')
    pp,bp,gp,sp=[h(p.read_bytes()) for p in (profile,base,gen,scope)]
    seed=d/'seed.cl'
    seed.write_text(f'''
: budget_hint(i64).
: stable(sym).
: preserved(sym).
: trend(sym).
~ meter budget_hint.
~ meter trend.
= meter versions plan.
% meter plan budget_hint {pp} {bp} {gp} {sp}.
& low budget_hint(10000).
& anchor stable(ok).
| hard positive stable(ok).
| hard unknown artifact_plan__affordable(beta) when trend(safety).
| wish positive artifact_plan__affordable(beta) when trend(expand).
''')
    goal='artifact_plan__affordable(beta)'
    state=d/'state'
    assert h(alpha.read_bytes())!=h(beta.read_bytes())
    def cycle(p,name,source_row,raw):
        (incoming/(name+'.packet')).write_text(source_row+'\n'+raw+'\n')
        assert issue(p,':cycle '+name).startswith('cycle_committed')
        detail=p.stdout.readline().strip()
        assert detail.startswith('auto_revision version_switched'),detail
        return detail
    def transcript(p,cmd,truth,replayed=False):
        assert issue(p,':chat budget '+cmd).startswith('chat_replayed' if replayed else 'chat_committed')
        output=p.stdout.readline().strip()
        assert f'reply {goal} {truth}' in output,output
        return output
    def prepare(who):
        return run(who,'--prepare',state,wd=d).decode().strip()
    def handoff(p,place,address):
        return issue(p,':handoff '+place+' '+val(address,'binary_sha256')+' '+val(address,'snapshot_sha256'))
    with live(alpha,'--init-managed',seed,state,wd=d) as a:
        info=a.stdout.readline()
        uid=val(info,'individual')
        stamp=h(state.read_bytes())
        c=issue(a,f':stage_from_evidence plan {pp} {bp} {gp} {sp} {stamp} budget_hint')
        initial=val(c,'ir_sha256')
        assert issue(a,f':commit_cl plan {initial} {stamp}').startswith('cl_committed')
        assert issue(a,':watch budget '+goal).startswith('watch_registered')
        original=transcript(a,'opening focus '+goal,'UNKNOWN')
        assert issue(a,':pin initial_view').startswith('pin_committed')
        got=cycle(a,'grow','source meter 1','budget_hint(12000)\ntrend(expand)')
        raised=re.search(r'reason=plan:([a-f0-9]{64})',got)[1]
        assert raised!=initial
        assert issue(a,':pin grown_view').startswith('pin_committed')
        stale=prepare(beta)
        assert issue(a,':observe late preserved(news)').startswith('observation_version')
        assert 'prepared snapshot is stale' in handoff(a,'beta',stale)
        good=prepare(beta)
        record=handoff(a,'beta',good)
        assert record.startswith('handoff_prepared') and a.wait(timeout=10)==0
    a_history=run(alpha,'--read-channel',state,wd=d,data=b'c status\n')
    assert json.loads(a_history)['payload']['handoff_pending']
    with live(beta,'--claim',state,val(record,'nonce'),wd=d) as b:
        assert val(b.stdout.readline(),'individual')==uid
        assert transcript(b,'opening focus '+goal,'UNKNOWN',True)==original
        change=transcript(b,'grown status','POSITIVE')
        assert issue(b,':then initial_view '+goal).endswith('UNKNOWN')
        assert issue(b,':then grown_view '+goal).endswith('POSITIVE')
        assert 'POSITIVE plus=obs:late' in issue(b,'preserved(news)')
        for x in (profile,base,gen,scope):x.unlink()
        assert initial in cycle(b,'safe','source meter 2','trend(safety)')
        backward=transcript(b,'again status','UNKNOWN')
        assert change!=backward
        assert 'POSITIVE plus=obs:late' in issue(b,'preserved(news)')
        b.kill();assert b.wait(timeout=5)<0
    with live(beta,'--resume',state,wd=d) as b:
        assert val(b.stdout.readline(),'individual')==uid
        assert transcript(b,'after_kill status','UNKNOWN')==backward
        assert issue(b,':then grown_view '+goal).endswith('POSITIVE')
        ready=prepare(alpha)
        reverse=handoff(b,'alpha',ready)
        assert reverse.startswith('handoff_prepared') and b.wait(timeout=10)==0
    with live(alpha,'--claim',state,val(reverse,'nonce'),wd=d) as a:
        hello2=a.stdout.readline()
        assert val(hello2,'individual')==uid and 'owner=alpha' in hello2
        assert 'withdrawn sensor_meter_2_1' in issue(a,':withdraw sensor_meter_2_1')
        assert raised in cycle(a,'grow_again','source meter 3','trend(expand)')
        transcript(a,'after_handoff status','POSITIVE')
    row=run(alpha,'--read-channel',state,wd=d,data=b's inspect * 0; artifact_plan__affordable(beta); preserved(news)\ng generated\n')
    snapshot,generated=[json.loads(x)['payload'] for x in row.splitlines()]
    assert [x['status'] for x in snapshot['proofs']['results']]==['POSITIVE','POSITIVE']
    assert snapshot['status']['state']['individual']==generated['state']['individual']==uid
    assert [x['after'] for x in snapshot['notices']['results'] if x['kind']=='truth']==['POSITIVE','UNKNOWN','POSITIVE']
    assert len(generated['results'])==2 and next(x for x in generated['results'] if x['active'])['ir_sha256']==raised
    history=run(alpha,'--resume',state,wd=d,data=b':transcript budget\n:history\n')
    assert b'transcript_end turns=5' in history and history.count(b' artifact_synthesized plan ')==2
    assert not list(inputs.iterdir()) and not (d/'imports').exists()
print('PASS: same individual retains dialogue, historical proofs and later evidence across native self-synthesis, stale A/B refusal, actual Alpha→Beta→Alpha runtime handoff, evidence-driven rollback and hard process exit.')
