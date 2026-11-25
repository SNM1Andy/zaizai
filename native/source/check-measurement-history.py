from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess,json,re,sys

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
~ critic elapsed_raw.
~ guest outcome.
: elapsed_raw(sym,sym,qty(hour)).
: measured_outcome(sym,sym,sym).
: certified(sym).
& initial_certification certified(yes).
measured_outcome($d,$c,success) <- elapsed_raw($d,$c,$elapsed) & qty_le($elapsed,20@hour) & certified(yes).
measured_outcome($d,$c,failure) <- elapsed_raw($d,$c,$elapsed) & qty_lt(20@hour,$elapsed).
= critic measurement elapsed_raw.
& current realm(test).
& fixed stable(ok).
| hard positive stable(ok).
| hard unknown artifact_budget__affordable(beta) when mode(safety).
| wish positive artifact_budget__affordable(beta) when mode(expand).
| wish positive monitor(alpha) when mode(repair).
''')
    invalid=d/'invalid.cl'
    invalid.write_text(seed.read_text()+'\n= critic.\n')
    assert b'measurement source cannot' in short(pcgm,'--init',invalid,d/'bad',code=1)[1]
    assert not (d/'bad').exists()
    inbox=d/'incoming';inbox.mkdir()
    def packet(name,source,sequence,*facts):
        contents=(f'source {source} {sequence}\n'+'\n'.join(facts)+'\n').encode()
        (inbox/(name+'.packet')).write_bytes(contents)
        return h(contents)
    def feed(state,source,cursor=0,count=8,ok=True):
        data=json.loads(short(pcgm,'--read-channel',state,data=(f'one outcome_requests {source} {cursor} {count}\n').encode())[0])
        assert data['ok']==ok,data
        return data.get('payload',data.get('error'))
    def learned(state,event,ok=True):
        data=json.loads(short(pcgm,'--read-channel',state,data=('one learned_outcome '+event+'\n').encode())[0])
        assert data['ok']==ok,data
        return data.get('payload',data.get('error'))
    def historical(state,event,ok=True):
        response=json.loads(short(pcgm,'--read-channel',state,
                                    data=('one measurement_history '+event+'\n').encode())[0])
        assert response['ok']==ok,response
        return response.get('payload',response.get('error'))
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
        snapshot=state.read_bytes()
        job=feed(state,'critic')['results'][0]
        assert job['decision']==decision and job['context']=='demo' and job['shape']=='elapsed_raw(sym,sym,qty:hour)'
        pin_request=job['request_sha256']
        assert len(pin_request)==64 and state.read_bytes()==snapshot
        assert 'not authorized' in feed(state,'guest',ok=False)
        packet('outside','guest',1,f'outcome({decision},demo,success)')
        assert request(writer,':cycle outside').startswith('cycle_committed')
        assert 'no automatically learned' in learned(state,decision,False)
        assert feed(state,'critic')['results']==[job]
        snapshot=state.read_bytes()
        packet('wrongcontext','critic',1,f'# trace review:1:measurement@{pin_request}',f'elapsed_raw({decision},other,12@hour)')
        packet('unbound','critic',1,f'elapsed_raw({decision},demo,12@hour)')
        packet('wrongpin','critic',1,'# trace review:1:measurement@'+'f'*64,f'elapsed_raw({decision},demo,12@hour)')
        packet('wrongunit','critic',1,f'# trace review:1:measurement@{pin_request}',f'elapsed_raw({decision},demo,12@cny_cent)')
        packet('verdict','critic',1,f'# trace review:1:measurement@{pin_request}',f'outcome({decision},demo,success)')
        for name in ('wrongcontext','unbound','wrongpin','wrongunit','verdict'):
            assert 'measurement' in request(writer,':cycle '+name),(name,writer.poll())
            assert state.read_bytes()==snapshot,name
        assert 'no automatically learned' in learned(state,decision,False)
        # The measurement exists, but the CL assessment lacks a separate premise. No learning yet.
        assert 'withdrawn' in request(writer,':withdraw initial_certification')
        packet('pending','critic',1,f'# trace review:1:measurement@{pin_request}',f'elapsed_raw({decision},demo,11@hour)')
        assert request(writer,':cycle pending').startswith('cycle_committed')
        assert 'no automatically learned' in learned(state,decision,False)
        assert feed(state,'critic')['results']==[job]
        assert 'withdrawn' in request(writer,':withdraw sensor_critic_1_1')
        assert 'restored' in request(writer,':restore initial_certification')
        pin=packet('confirmed','critic',2,f'# trace review:1:measurement@{pin_request}',f'elapsed_raw({decision},demo,12@hour)')
        assert request(writer,':cycle confirmed').startswith('cycle_committed')
        assert not feed(state,'critic')['results']
        snapshot=state.read_bytes()
        packet('settled','critic',3,f'# trace review:1:measurement@{pin_request}',f'elapsed_raw({decision},demo,12@hour)')
        assert 'settled' in request(writer,':cycle settled')
        assert state.read_bytes()==snapshot
        receipt=learned(state,decision)
        assert receipt['packet_sha256']==pin and receipt['source']=='critic' and receipt['sequence']==2 and receipt['index']==1
        assert receipt['observation']=='sensor_critic_2_1' and receipt['active_contribution']==1 and receipt['original_contribution']==1 and receipt['measured']
        before_read=state.read_bytes()
        original=historical(state,decision)
        assert state.read_bytes()==before_read
        assert original['then_contribution']==original['now_contribution']==1
        assert original['historical_proof']['results'][0]['status']=='POSITIVE'
        assert 'obs:sensor_critic_2_1@' in json.dumps(original['historical_proof'])
        assert 'obs:initial_certification' in json.dumps(original['historical_proof'])
        snapshot=state.read_bytes()
        assert request(writer,':cycle confirmed')=='cycle_unchanged critic 2' and state.read_bytes()==snapshot
        (inbox/'confirmed.packet').unlink()
        insert(b,c);insert(c,a,False)
        frozen=state.read_bytes()
        parallel=equivalent()
        assert parallel['jobs']==4 and parallel['peak_active']>=2,parallel
        picked=parallel['decision']['selected']
        assert parallel['decision']['options'][picked]['target']=='budget:'+h(b)
        boosted=evaluate(':compare_versions')
        assert boosted[-1]==f'decision artifact budget:{h(b)} preview' and state.read_bytes()==frozen,boosted
        assert any(x.startswith('option artifact ') and x.endswith('memory=1') for x in boosted),boosted
        assert 'withdrawn sensor_critic_2_1' in request(writer,':withdraw sensor_critic_2_1')
        assert learned(state,decision)['active_contribution']==0
        tied_state=state.read_bytes()
        no=equivalent()
        assert no['decision']['status']=='tied' and no['decision']['selected'] is None
        no_commit=json.loads(request(writer,':decide_versions_parallel_json'))
        assert no_commit['decision']==no['decision'] and state.read_bytes()==tied_state
        tied=evaluate(':decide_versions')
        assert tied[-1]=='decision none; maintain current state' and state.read_bytes()==tied_state,tied
        eligible=[x for x in tied if x.startswith('option artifact ')]
        assert len(eligible)==2 and eligible[0]==eligible[1],tied
        assert 'restored sensor_critic_2_1' in request(writer,':restore sensor_critic_2_1')
        assert learned(state,decision)==receipt
        genuine=state.read_bytes()
        # An admitted measurement may lose its proven force when a later premise is withdrawn.
        assert 'withdrawn' in request(writer,':withdraw initial_certification')
        assessment=learned(state,decision)
        assert assessment['active_contribution']==0 and assessment['original_contribution']==1
        frozen=historical(state,decision)
        assert frozen['historical_proof']==original['historical_proof'] and frozen['basis_sha256']==original['basis_sha256']
        assert frozen['now_contribution']==0 and frozen['current_proof']['results'][0]['status']=='UNKNOWN'
        assert 'restored' in request(writer,':restore initial_certification')
        assert learned(state,decision)==receipt and state.read_bytes()!=genuine
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
        assert request(writer,':seal_history '+h(state.read_bytes())).startswith('archive_sealed')
        assert request(writer,':compact_state '+h(state.read_bytes())).startswith('state_representation compact')
        writer.kill();assert writer.wait(timeout=5)<0
    assert not image.exists()
    reopened=short(pcgm,'--resume',state,data=b':experiences\nmonitor(alpha)\nartifact_budget__affordable(beta)\n')[0].decode()
    assert uid in reopened and 'POSITIVE plus=' in reopened and reopened.endswith('UNKNOWN\n'),reopened
    assert ' artifact:budget:'+h(b)+' context=demo ' in reopened,reopened
    assert learned(state,decision)==receipt
    reopened=feed(state,'critic')
    assert all(row['decision']!=decision for row in reopened['results']) and len(reopened['results'])>=1
    moved=d/'detached';moved.mkdir()
    portable=moved/'transfer'
    assert b'transfer_exported' in short(pcgm,'--export-portable-policies',state,portable)[0]
    clone=moved/'copied'
    assert b'activation=required' in short(root/'pcgm-beta','--restore-copy',portable,clone)[0]
    transplanted=feed(clone,'critic')
    assert transplanted['individual']==uid and transplanted['results']==reopened['results']
    assert learned(clone,decision)==receipt
    check=historical(clone,decision)
    assert check['historical_proof_sha256']==original['historical_proof_sha256']
    assert check['historical_proof']==original['historical_proof']
    stored=Path(str(clone)+'.episodes')/(original['basis_sha256']+'.snap')
    good=stored.read_bytes()
    stored.write_bytes(good[:-1])
    assert 'digest mismatch' in historical(clone,decision,False)
    stored.write_bytes(good)
    assert historical(clone,decision)==check
    print("PASS: original measured-outcome proof is independently regenerated from its sealed historical evidence after later withdrawal, native compaction, forced stop, and staged migration; tampered history is refused, never guessed from current proof.")
