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
with TemporaryDirectory(prefix='PCGM approved evidence actual self revision ') as tmp:
    d=Path(tmp);inputs=d/'build_inputs';inputs.mkdir();incoming=d/'incoming';incoming.mkdir()
    base=inputs/'plan.cl';base.write_bytes((home/'fixtures'/'base.cl').read_bytes())
    profile=inputs/'plan.clcp';profile.write_bytes((home/'profiles'/'standard.clcp').read_bytes())
    gen=inputs/'plan.generator.cl'
    g=(home/'fixtures'/'generator.cl').read_text().replace('& a21 amount_cfg(balance,2,1,10000).\n','')
    gen.write_text(g+': budget_hint(i64).\namount_cfg(balance,2,1,$n) <- budget_hint($n).\n')
    scope=inputs/'plan.scope';scope.write_text((home/'fixtures'/'bounded.scope').read_text()+'evidence budget_hint\n')
    pp,bp,gp,sp=[h(x.read_bytes()) for x in (profile,base,gen,scope)]
    seed=d/'seed.cl'
    seed.write_text(f'''
: budget_hint(i64).
: stable(sym).
: state_note(sym).
: trend(sym).
~ meter budget_hint.
~ meter !budget_hint.
~ meter trend.
~ misc budget_hint.
= meter versions plan.
% meter plan budget_hint {pp} {bp} {gp} {sp}.
& old_hint budget_hint(10000).
& fitness stable(ok).
| hard positive stable(ok).
| hard unknown artifact_plan__affordable(beta) when trend(safety).
| wish positive artifact_plan__affordable(beta) when trend(expand).
''')
    marker='artifact_plan__affordable(beta)'
    state=d/'state'
    def query(*facts):
        args='q inspect * 0; '+'; '.join(facts)+'\n'
        o=json.loads(run(pcgm,'--read-channel',state,wd=d,data=args.encode()))
        assert o['ok'],o
        return o['payload']
    def observe_alias():
        o=json.loads(run(pcgm,'--read-channel',state,wd=d,data=b'gen generated\n'))['payload']
        return next(x for x in o['results'] if x['active']),o['results']
    def packet(name,who,index,*items):
        (incoming/(name+'.packet')).write_text(f'source {who} {index}\n'+'\n'.join(items)+'\n')
    def cycle(p,name,kind=None):
        out=issue(p,':cycle '+name)
        assert out.startswith('cycle_committed'),out
        if kind:
            line=p.stdout.readline().strip();assert line.startswith('auto_revision '+kind),line;return line
    with live(pcgm,'--init-managed',seed,state,wd=d) as p:
        uid=re.search(r'individual=(\w+)',p.stdout.readline())[1]
        stamp=h(state.read_bytes())
        prepared=issue(p,f':stage_from_evidence plan {pp} {bp} {gp} {sp} {stamp} budget_hint')
        old=re.search(r'ir_sha256=(\w+)',prepared)[1]
        assert issue(p,f':commit_cl plan {old} {stamp}').startswith('cl_committed')
        assert issue(p,':watch decision '+marker).startswith('watch_registered')
        assert query(marker)['proofs']['results'][0]['status']=='UNKNOWN'
        packet('unscoped','misc',1,'budget_hint(12500)')
        cycle(p,'unscoped')
        assert observe_alias()[0]['ir_sha256']==old
        packet('positive','meter',1,'budget_hint(12000)','trend(expand)')
        reason=cycle(p,'positive','version_switched')
        active,versions=observe_alias()
        new=active['ir_sha256']
        assert len(versions)==2 and new!=old and new in reason
        assert active['synthesis']['generator_sha256']==gp
        assert query(marker,'budget_hint(12000)')['proofs']['results'][0]['status']=='POSITIVE'
        current=state.read_bytes()
        assert issue(p,':cycle positive')=='cycle_unchanged meter 1' and state.read_bytes()==current
        packet('conflicting','meter',2,'budget_hint(15000)','!budget_hint(15000)')
        refused=cycle(p,'conflicting','stay')
        assert 'native synthesis blocked: new synthesis evidence is contradicted' in refused
        assert observe_alias()[0]['ir_sha256']==new and len(observe_alias()[1])==2
        assert query('budget_hint(15000)')['proofs']['results'][0]['status']=='CONFLICT'
        assert issue(p,':observe after state_note(keep)').startswith('observation_version')
        packet('conservative','meter',3,'trend(safety)')
        assert old in cycle(p,'conservative','version_switched')
        assert observe_alias()[0]['ir_sha256']==old
        pinned=re.search(r'sha256=(\w+)',issue(p,':pin encounter'))[1]
        def pinned_read(req,success=True,endpoint=None):
            if endpoint is None:
                raw=run(pcgm,'--read-channel',state,wd=d,data=('q '+req+'\n').encode())
            else:
                raw=run(pcgm,'--fifo-query',endpoint,'1',req,wd=d,ok=0 if success else 2)
            message=json.loads(raw)
            assert message['ok']==success,message
            return message['payload'] if success else message['error']
        cmd=f'pinned_review encounter {pinned} 0 0 1; {marker}'
        first_frozen=pinned_read(cmd)
        assert first_frozen['schema']=='pcgm-pinned-review-v1'
        assert first_frozen['proofs']['results'][0]['status']=='UNKNOWN'
        assert first_frozen['decisions']['more'] and len(first_frozen['decisions']['results'])==1
        assert first_frozen['proofs']['context']==first_frozen['status']['state']
        next_frozen_cmd=f"pinned_review encounter {pinned} {first_frozen['decisions']['cursor']} 0 8"
        second_frozen=pinned_read(next_frozen_cmd)
        assert len(second_frozen['decisions']['results'])==1 and not second_frozen['decisions']['more']
        assert second_frozen['snapshot_sha256']==pinned
        assert 'mismatch' in pinned_read(cmd.replace(pinned,'0'*64),False)
        assert 'beyond snapshot' in pinned_read(f'pinned_review encounter {pinned} 0 999 1',False)
        assert 'invalid coherent' in pinned_read(f'pinned_review encounter {pinned} 999 0 1',False)
        for f in (base,profile,gen,scope):f.unlink()
        p.kill();assert p.wait(timeout=5)<0
    with live(pcgm,'--resume',state,wd=d) as q:
        assert uid in q.stdout.readline()
        assert observe_alias()[0]['ir_sha256']==old
        assert 'withdrawn sensor_meter_3_1' in issue(q,':withdraw sensor_meter_3_1')
        packet('later','meter',4,'trend(expand)')
        assert new in cycle(q,'later','version_switched')
        outcome=query(marker,'state_note(keep)')
        assert [x['status'] for x in outcome['proofs']['results']]==['POSITIVE','POSITIVE']
        assert [x['after'] for x in outcome['notices']['results'] if x['kind']=='truth']==['POSITIVE','UNKNOWN','POSITIVE']
    before_read=state.read_bytes()
    payload=run(pcgm,'--read-channel',state,wd=d,data=(f'q review 0 0 1; {marker}; state_note(keep)\n').encode())
    row=json.loads(payload)['payload']
    assert row['schema']=='pcgm-review-v1' and row['revision_sha256']==h(before_read)
    assert row['proofs']['context']==row['status']['state']
    assert all(x['status']=='POSITIVE' for x in row['proofs']['results'])
    assert row['decisions']['more'] and len(row['decisions']['results'])==1
    first=row['decisions']['results'][0]
    assert first['kind']=='artifact' and first['trace']['trigger']=='observation:meter:1'
    assert first['trace']['options'][first['trace']['selected']]['target']=='plan:'+new
    assert len(row['notices']['results'])==3
    cursor=row['decisions']['cursor']
    notice=row['notices']['cursor']
    following=run(pcgm,'--read-channel',state,wd=d,data=(f'x review {cursor} {notice} 8\n').encode())
    part=json.loads(following)['payload']
    assert part['proofs'] is None and not part['decisions']['more']
    assert len(part['decisions']['results'])==2 and part['notices']['results']==[]
    assert part['revision_sha256']==row['revision_sha256'] and cursor<part['decisions']['cursor']
    assert state.read_bytes()==before_read
    lanes=d/'review_lanes'
    with live(pcgm,'--resume',state,wd=d) as owner:
        assert uid in owner.stdout.readline()
        with live(pcgm,'--serve-fifo',state,lanes,'2',wd=d) as service:
            assert 'lanes=2' in service.stdout.readline()
            assert 'observed extra' in issue(owner,':observe extra state_note(latest)')
            native=run(pcgm,'--fifo-query',lanes,'1',f'review {cursor} {notice} 8; state_note(latest)',wd=d)
            data=json.loads(native)['payload']
            assert data['revision_sha256']==h(state.read_bytes())!=row['revision_sha256']
            assert data['status']['state']['individual']==uid and len(data['decisions']['results'])==2
            assert data['proofs']['context']==data['status']['state'] and data['proofs']['results'][0]['status']=='POSITIVE'
            service.terminate();assert service.wait(timeout=8)==0
    history=run(pcgm,'--resume',state,wd=d,data=b':history\n')
    assert history.count(b' artifact_synthesized plan ')==2
    traces=re.findall(rb'decision_trace (e\d+) sha256=',history)
    once=run(pcgm,'--read-channel',state,wd=d,data=b'q decision '+traces[0]+b'\n')
    audit=json.loads(once)['payload']
    assert audit['trigger']=='observation:meter:1' and audit['status']=='committed'
    assert audit['options'][audit['selected']]['target']=='plan:'+new
    beta=home/'pcgm-beta'
    with live(pcgm,'--resume',state,wd=d) as p:
        assert uid in p.stdout.readline()
        for j in range(135):
            assert issue(p,f':observe move{j} state_note(t{j})').startswith('observation_version')
        assert issue(p,':seal_history '+h(state.read_bytes())).startswith('archive_sealed')
        sealed_state=h(state.read_bytes())
        assert issue(p,':compact_state '+sealed_state).startswith('state_representation compact')
        assert pinned_read(cmd)==first_frozen and pinned_read(next_frozen_cmd)==second_frozen
        with live(pcgm,'--serve-fifo',state,d/'frozen_lanes','1',wd=d) as server:
            assert 'lanes=1' in server.stdout.readline()
            assert pinned_read(cmd,endpoint=d/'frozen_lanes')==first_frozen
            server.terminate();assert server.wait(timeout=8)==0
        bits=run(beta,'--prepare',state,wd=d).decode()
        def pick(row,key):return re.search(fr'{key}=(\w+)',row)[1]
        move=issue(p,':handoff beta '+pick(bits,'binary_sha256')+' '+pick(bits,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and p.wait(timeout=10)==0
    with live(beta,'--claim',state,pick(move,'nonce'),wd=d) as p:
        assert uid in p.stdout.readline() and pinned_read(cmd)==first_frozen
        p.kill(); assert p.wait(timeout=5)<0
    with live(beta,'--resume',state,wd=d) as p:
        assert uid in p.stdout.readline() and pinned_read(next_frozen_cmd)==second_frozen
        blob=Path(str(state)+'.episodes')/(pinned+'.snap')
        correct=blob.read_bytes()
        blob.write_bytes(correct[:-1])
        assert 'pinned snapshot digest mismatch' in pinned_read(cmd,False)
        blob.write_bytes(correct)
        assert pinned_read(cmd)==first_frozen
    assert not list(inputs.iterdir()) and not (d/'imports').exists()
print('PASS: actual historical decision pages, proofs and notices stay exact across later writes, compaction, native FIFO, A/B handoff, hard exit and restoration of pinned bytes.')
