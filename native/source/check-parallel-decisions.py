from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess,json,re,sys,time

root=Path(__file__).resolve().parent
cl=root/'cl'
pcgm=root/'pcgm-alpha'
def short(exe,*args,data=b'',code=0):
    p=subprocess.run([exe,*args],input=data,capture_output=True,timeout=15)
    assert p.returncode==code,(p.args,p.returncode,p.stdout,p.stderr)
    return p.stdout,p.stderr
@contextmanager
def live(exe,*args):
    p=subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:yield p
    finally:
        if p.poll() is None:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def request(p,command):
    p.stdin.write(command+'\n');p.stdin.flush()
    s=p.stdout.readline().strip();assert s,(command,p.poll())
    return s
def status(p,cursor=0):
    d=json.loads(request(p,f'viewer inspect * {cursor}; artifact_budget__affordable(beta); sample(gamma); monitor(alpha)'))
    assert d['ok'],d
    return d['payload']
def truths(p):
    return [a['status'] for a in p['proofs']['results']]
def settle(p):
    p.stdin.write('sample(alpha)\n');p.stdin.flush()
    for _ in range(30):
        if p.stdout.readline().strip().startswith('POSITIVE plus=obs:signal'):return
    raise AssertionError('writer did not finish')
def h(x):return sha256(x).hexdigest()
with TemporaryDirectory(prefix='PCGM choice over real versions ') as tmp:
    d=Path(tmp);imports=d/'imports';imports.mkdir();image=imports/'budget.clir'
    generator=d/'generator.cl';base=root/'fixtures'/'base.cl'
    input_rules=(root/'fixtures'/'generator.cl').read_text()
    def build(limit):
        generator.write_text(input_rules.replace('10000',str(limit)))
        return short(cl,'generate-ir',generator,base,h(base.read_bytes()),root/'fixtures'/'bounded.scope')[0]
    a,b,c=[build(x) for x in (10000,12000,13000)]
    seed=d/'seed.cl'
    seed.write_text((root/'fixtures'/'producer.cl').read_text()+'''
: mode(sym).
: realm(sym).
: outcome(sym,sym,sym).
> demo realm(test).
> other realm(other).
& current realm(test).
& fixed stable(ok).
| hard positive stable(ok).
| hard unknown artifact_budget__affordable(beta) when mode(safety).
| wish positive artifact_budget__affordable(beta) when mode(expand).
| wish positive monitor(alpha) when mode(repair).
''')
    with seed.open('a') as stress:
        stress.write(': dense_input(sym).\n: stage1(sym).\n: stage2(sym).\n: stage3(sym).\n')
        stress.write('stage1($x) <- dense_input($x).\nstage2($x) <- stage1($x).\nstage3($x) <- stage2($x).\n')
        for i in range(750):stress.write(f'& bulk{i} dense_input(n{i}).\n')
    state=d/'state' 
    image.write_bytes(a)
    with live(pcgm,'--init',seed,state) as writer:
        uid=re.search(r'individual=(\w+)',writer.stdout.readline())[1]
        init=request(writer,':install_ir budget '+h(a))
        assert init.startswith('artifact_installed'),init
        def insert(old,new,prepare=True):
            if prepare:image.write_bytes(new)
            cmd=f':replace_ir budget {h(old)} {h(new)} {h(state.read_bytes())}'
            res=request(writer,cmd)
            assert res.startswith('artifact_switched'),res
            if image.exists():image.unlink()
        def evaluate(op):
            result=[request(writer,op)]
            for _ in range(100):
                if result[-1].startswith('decision '):return result
                result.append(writer.stdout.readline().strip())
            raise AssertionError(result)
        def equivalent():
            exact=state.read_bytes()
            serial=json.loads(request(writer,':compare_versions_json'))
            line=request(writer,':compare_versions_parallel_json'); assert line.startswith('{'),line; parallel=json.loads(line)
            assert parallel['decision']==serial and state.read_bytes()==exact,(parallel,serial)
            assert parallel['backend']=='cpu' and parallel['workers']>=2 and parallel['jobs']>=2
            return parallel
        def events():
            result=[request(writer,':history')]
            for _ in range(100):
                if result[-1].startswith('history_end'):return result
                result.append(writer.stdout.readline().strip())
            raise AssertionError(result)
        insert(a,b)
        insert(b,a,False)
        image.unlink(missing_ok=True)
        assert 'observed opening' in request(writer,':observe opening mode(expand)')
        before=state.read_bytes()
        cand=evaluate(':compare_versions')
        assert cand[-1]==f'decision artifact budget:{h(b)} preview' and state.read_bytes()==before,cand
        decided=evaluate(':decide_versions')
        assert decided[-1]==f'decision artifact budget:{h(b)} committed',decided
        r=next(x for x in events() if f'decision artifact budget:{h(b)}' in x)
        decision='e'+re.search(r'^event=(\d+) ',r)[1]
        assert 'observed good' in request(writer,f':observe good outcome({decision},demo,success)')
        assert request(writer,f':feedback {decision} good').startswith('feedback_recorded')
        insert(b,c);insert(c,a,False)
        frozen=state.read_bytes()
        parallel=equivalent()
        assert parallel['jobs']==4 and parallel['peak_active']>=2,parallel
        picked=parallel['decision']['selected']
        assert parallel['decision']['options'][picked]['target']=='budget:'+h(b)
        boosted=evaluate(':compare_versions')
        assert boosted[-1]==f'decision artifact budget:{h(b)} preview' and state.read_bytes()==frozen,boosted
        assert any(x.startswith('option artifact ') and x.endswith('memory=1') for x in boosted),boosted
        assert 'withdrawn good' in request(writer,':withdraw good')
        tied_state=state.read_bytes()
        no=equivalent()
        assert no['decision']['status']=='tied' and no['decision']['selected'] is None
        no_commit=json.loads(request(writer,':decide_versions_parallel_json'))
        assert no_commit['decision']==no['decision'] and state.read_bytes()==tied_state
        tied=evaluate(':decide_versions')
        assert tied[-1]=='decision none; maintain current state' and state.read_bytes()==tied_state,tied
        eligible=[x for x in tied if x.startswith('option artifact ')]
        assert len(eligible)==2 and eligible[0]==eligible[1],tied
        ticket=json.loads(request(writer,':choice_job_start'))['id']
        deadline=time.monotonic()+10
        while json.loads(request(writer,':choice_job_collect '+ticket))['phase']!='ready':
            assert time.monotonic()<deadline
            time.sleep(.002)
        accepted=json.loads(request(writer,':choice_job_commit_explained '+ticket))
        assert accepted['status']=='tied' and accepted['selected'] is None
        head=state.read_bytes()
        attribution=json.loads(short(pcgm,'--read-channel',state,
            data=f'view choice_attribution {ticket} {h(head)}\n'.encode())[0])
        assert attribution['ok'] and state.read_bytes()==head
        explanation=attribution['payload']
        assert explanation['full']=={'status':'tied','selected':None,'kind':None}
        assert not explanation['changed'] and not explanation['committable'] and explanation['minimal_sufficient_sets']==[]
        assert 'restored good' in request(writer,':restore good')
        assert evaluate(':decide_versions')[-1]==f'decision artifact budget:{h(b)} committed'
        assert 'observed keep' in request(writer,':observe keep mode(safety)')
        for _ in range(2):
            conservative=evaluate(':compare_versions')
            assert conservative[-1]==f'decision artifact budget:{h(a)} preview',conservative
            assert any('hard objective not met' in a for a in conservative),conservative
        comparison=equivalent()['decision']
        committed=json.loads(request(writer,':decide_versions_parallel_json'))['decision']
        assert committed['status']=='committed'
        assert committed['options']==comparison['options'] and committed['selected']==comparison['selected']
        assert committed['options'][committed['selected']]['target']=='budget:'+h(a)
        assert 'observed fix' in request(writer,':observe fix mode(repair)')
        fix=equivalent()['decision']
        done=json.loads(request(writer,':decide_versions_parallel_json'))['decision']
        assert done['options']==fix['options']
        assert done['options'][done['selected']]['kind']=='rewrite' 
        history=events()
        assert sum(f'decision artifact budget:{h(a)}' in x for x in history)==1
        assert sum(f'decision artifact budget:{h(b)}' in x for x in history)==2
        writer.kill();assert writer.wait(timeout=5)<0
    assert not image.exists()
    reopened=short(pcgm,'--resume',state,data=b':experiences\nmonitor(alpha)\nartifact_budget__affordable(beta)\n')[0].decode()
    assert uid in reopened and 'POSITIVE plus=' in reopened and reopened.endswith('UNKNOWN\n'),reopened
    assert ' artifact:budget:'+h(b)+' context=demo ' in reopened,reopened
    rewind_seed=d/'rewind.cl'
    rewind_seed.write_text((root/'fixtures'/'producer.cl').read_text()+"""
& initial trusted(alpha).
!trusted($x) <- monitor($x).
| hard positive trusted(alpha).
| wish unknown monitor(alpha).
""")
    rewind=d/'rewind'
    with live(pcgm,'--init',rewind_seed,rewind) as actor:
        uid=re.search(r'individual=(\w+)',actor.stdout.readline())[1]
        outcome=request(actor,':plan')
        plan=re.search(r'plan_ready (\w+)',outcome)[1]
        settle(actor)
        assert request(actor,':apply '+plan).startswith('revision_applied')
        settle(actor)
        assert 'observed late' in request(actor,':observe late sample(gamma)')
        view=json.loads(request(actor,':compare_json'))
        matched=json.loads(request(actor,':compare_parallel_json'))['decision']
        assert matched==view
        done=json.loads(request(actor,':decide_parallel_json'))['decision']
        assert done['status']=='committed' and done['options']==view['options']
        assert done['options'][done['selected']]['kind']=='rollback'
        assert request(actor,'sample(gamma)').startswith('POSITIVE') and request(actor,'monitor(alpha)')=='UNKNOWN'
        actor.kill();assert actor.wait(timeout=5)<0
    out=short(pcgm,'--resume',rewind,data=b'trusted(alpha)\nsample(gamma)\n')[0].decode()
    assert uid in out and out.count('POSITIVE')==2
print('PASS: actual PCGM candidates overlap on native CPU workers, serial receipts equal parallel snapshots, ties and branch policy preserved, only one winner commits, and rollback retains later facts.')
