from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import re
import subprocess
import time

root=Path(__file__).resolve().parent
alpha,beta=root/'pcgm-alpha',root/'pcgm-beta'
def parse(line,key):
    return re.search(fr'{key}=(\w+)',line)[1]
def digest(data):
    return sha256(data).hexdigest()
def run(exe,*args,data=b'',code=0):
    p=subprocess.run([exe,*args],input=data,capture_output=True,timeout=15)
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:400])
    return p.stdout
@contextmanager
def live(exe,*args):
    with subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:
                p.kill();p.wait(timeout=5)
def issue(p,cmd):
    p.stdin.write(cmd+'\n');p.stdin.flush()
    result=p.stdout.readline().strip()
    assert result,(cmd,p.poll())
    return result
def receive(state,cmd,ok=True,endpoint=None):
    if endpoint:
        raw=run(alpha,'--fifo-query',endpoint,'1',cmd,code=0 if ok else 2)
    else:
        raw=run(alpha,'--read-channel',state,data=('one '+cmd+'\n').encode())
    wire=json.loads(raw)
    assert wire['ok']==ok,wire
    return wire['payload'] if ok else wire['error']
def write_packet(folder,name,uid,question,source,fact,sha=None):
    pin=sha or question['request_sha256']
    raw=f"PCGM_ANSWER_1 {uid} {question['id']} {source} {pin}\n{fact}\n".encode()
    packet=folder/(name+'.answer')
    packet.write_bytes(raw)
    return digest(raw)

with TemporaryDirectory(prefix='actual live PCGM background decision ownership ') as td:
    d=Path(td)
    source=d/'brain.cl'
    profile=(root/'fixtures'/'producer.cl').read_text()
    stress=[': bench(sym).',': bench1(sym).',': bench2(sym).',': bench3(sym).',': bench4(sym).',
            'bench1($x) <- bench($x).','bench2($x) <- bench1($x).','bench3($x) <- bench2($x).','bench4($x) <- bench3($x).']
    stress += [f'& bulk{i} bench(n{i}).' for i in range(1050)]
    source.write_text(profile+"""
: later(sym).
~ meter later.
stable(run).
| hard positive stable(run).
| wish positive monitor(alpha).
"""+'\n'.join(stress)+'\n')
    state=d/'individual'
    def wait_for(p,id,kind='choice_job_collect'):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            turn=json.loads(issue(p,':'+kind+' '+id))
            if turn['phase'] not in ('running','draining'):
                return turn
            time.sleep(.002)
        raise AssertionError('job did not finish')
    with live(alpha,'--init-managed',source,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        before=state.read_bytes()
        started=json.loads(issue(actor,':choice_job_start'))
        old_job=started['id']
        assert started['phase']=='running' and started['basis_sha256']==digest(before)
        assert 'existing choice job' in issue(actor,':choice_job_start')
        assert 'unknown active' in issue(actor,':choice_job_status fake')
        assert 'still evaluating' in issue(actor,':choice_job_commit '+old_job)
        assert issue(actor,'monitor(alpha)')=='UNKNOWN'
        assert 'observed independent' in issue(actor,':observe independent later(kept)')
        staged=wait_for(actor,old_job)
        assert staged['phase']=='ready' and staged['stale']
        assert staged['head_sha256']==digest(state.read_bytes())!=staged['basis_sha256']
        assert staged['decision']['trigger']=='live_job:'+old_job
        prev=state.read_bytes()
        assert 'stale' in issue(actor,':choice_job_commit '+old_job) and state.read_bytes()==prev
        cancelled=json.loads(issue(actor,':choice_job_cancel '+old_job))
        assert cancelled['phase']=='cancelled'
        second=json.loads(issue(actor,':choice_job_start'))
        second_id=second['id']
        assert second_id!=old_job
        raw=json.loads(issue(actor,':choice_job_cancel '+second_id))
        assert raw['phase'] in ('cancelled','draining')
        assert 'was cancelled' in issue(actor,':choice_job_commit '+second_id)
        assert wait_for(actor,second_id,'choice_job_status')['phase']=='cancelled'
        third=json.loads(issue(actor,':choice_job_start'));chosen=third['id']
        ready=wait_for(actor,chosen)
        assert ready['phase']=='ready' and not ready['stale']
        serial=json.loads(issue(actor,':compare_versions_json'))
        assert ready['decision']['options']==serial['options']
        assert ready['decision']['selected']==serial['selected']
        output=json.loads(issue(actor,':choice_job_commit_explained '+chosen))
        assert output['status']=='committed' and output['options'][output['selected']]['kind']=='rewrite'
        after=state.read_bytes()
        assert json.loads(issue(actor,':choice_job_commit_explained '+chosen))==output and state.read_bytes()==after
        committed=receive(state,'choice_receipt '+chosen)
        assert committed['decision']==output and committed['status']=='committed'
        assert committed['individual']==uid and committed['basis_sha256']==ready['basis_sha256']
        explain_cmd='choice_basis '+chosen+'; monitor(alpha); later(later_arrival)'
        explained=receive(state,explain_cmd)
        assert explained['status']=='verified' and explained['basis_sha256']==ready['basis_sha256']
        assert explained['decision']==output and explained['before']['event']<explained['now']['event']
        assert explained['comparisons'][0]['before']['status']=='UNKNOWN'
        assert explained['comparisons'][0]['now']['status']=='POSITIVE'
        assert explained['comparisons'][1]['now']['status']=='UNKNOWN'
        query_goals='; monitor(alpha); later(later_arrival); missing_namespace(value)'
        chosen_index=output['selected']
        no_op=next(i for i,x in enumerate(output['options']) if x['kind']=='stay')
        rejected=next(i for i,x in enumerate(output['options']) if x['kind']=='rollback')
        choose_request=f'choice_option {chosen} {chosen_index}'+query_goals
        alternative_request=f'choice_option {chosen} {no_op}'+query_goals
        win=receive(state,choose_request)
        other=receive(state,alternative_request)
        assert win['was_selected'] and win['status']=='verified' and win['kind']=='rewrite'
        assert not other['was_selected'] and other['status']=='verified' and other['kind']=='stay'
        assert win['basis_sha256']==other['basis_sha256']==committed['basis_sha256']
        assert win['choice_receipt_sha256']==other['choice_receipt_sha256']
        assert [x['proof']['status'] for x in win['results']]==['POSITIVE','UNKNOWN','UNAVAILABLE']
        assert [x['proof']['status'] for x in other['results']]==['UNKNOWN','UNKNOWN','UNAVAILABLE']
        assert win['results'][0]['proof']['positive']['nodes'][0]['premises']
        block=receive(state,f'choice_option {chosen} {rejected}')
        assert block['status']=='blocked' and 'no tracked revision' in block['reason']
        assert 'outside recorded set' in receive(state,f'choice_option {chosen} 99',ok=False)

        assert 'observed future' in issue(actor,':observe future later(later_arrival)')
        updated=receive(state,explain_cmd)
        assert updated['basis_sha256']==explained['basis_sha256'] and updated['head_sha256']!=explained['head_sha256']
        assert updated['comparisons'][1]['before']['status']=='UNKNOWN' and updated['comparisons'][1]['now']['status']=='POSITIVE'
        assert updated['comparisons'][0]['before']==explained['comparisons'][0]['before']
        assert receive(state,choose_request)==win and receive(state,alternative_request)==other

        receipt_file=Path(str(state)+'.episodes')/(ready['basis_sha256']+'.snap')
        exact=receipt_file.read_bytes()
        receipt_file.write_bytes(exact[:-1])
        assert 'snapshot digest mismatch' in receive(state,explain_cmd,ok=False)
        assert 'snapshot digest mismatch' in receive(state,alternative_request,ok=False)

        receipt_file.write_bytes(exact)
        assert receive(state,explain_cmd)==updated

        assert issue(actor,'monitor(alpha)').startswith('POSITIVE')
        assert issue(actor,'later(kept)').startswith('POSITIVE')
        unused=json.loads(issue(actor,':choice_job_start'))['id']
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,explain_cmd)==updated
        assert receive(state,'choice_basis '+unused)['status']=='not_recorded'
        assert 'unknown active' in issue(actor,':choice_job_commit_recorded '+unused)
        assert receive(state,'choice_receipt '+unused)['status']=='not_recorded'
        assert receive(state,'choice_receipt '+chosen)==committed
        after=state.read_bytes()
        assert json.loads(issue(actor,':choice_job_commit_explained '+chosen))==output and state.read_bytes()==after
        report=receive(state,'review 0 0 8')
        decisions=report['decisions']['results']
        assert len(decisions)==1 and decisions[0]['trace']['trigger']=='live_job:'+chosen
        assert issue(actor,'monitor(alpha)').startswith('POSITIVE')
        stay=json.loads(issue(actor,':choice_job_start'))['id']
        assert wait_for(actor,stay)['decision']['status']=='stay'
        before=state.read_bytes()
        initial_epoch=receive(state,'status')['state']['epoch']
        unchanged=json.loads(issue(actor,':choice_job_commit_recorded '+stay))
        assert unchanged['status']=='stay' and before!=state.read_bytes()
        assert receive(state,'status')['state']['epoch']==initial_epoch
        no_change=receive(state,'choice_receipt '+stay)
        assert no_change['status']=='unchanged' and no_change['decision']==unchanged
        assert receive(state,'choice_basis '+stay)['status']=='basis_not_recorded'
        assert 'without an archived basis' in issue(actor,':choice_job_commit_explained '+stay)

        after=state.read_bytes()
        assert json.loads(issue(actor,':choice_job_commit_recorded '+stay))==unchanged and state.read_bytes()==after
        inbox=d/'incoming';inbox.mkdir()
        for step in range(1,4):
            (inbox/f'progress{step}.packet').write_text(f'source meter {step}\n'+
                ''.join(f'later(n{step}_{n})\n' for n in range(63)))
            assert issue(actor,':cycle progress'+str(step)).startswith('cycle_committed')
        assert issue(actor,':seal_history '+digest(state.read_bytes())).startswith('archive_sealed')
        assert issue(actor,':compact_state '+digest(state.read_bytes())).startswith('state_representation compact')
        assert receive(state,'choice_receipt '+chosen)==committed
        next_=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(next_,'binary_sha256')+' '+parse(next_,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        observe=state.read_bytes()
        assert receive(state,'choice_receipt '+chosen)==committed and receive(state,'choice_receipt '+stay)==no_change
        assert json.loads(issue(actor,':choice_job_commit_explained '+chosen))==output
        assert json.loads(issue(actor,':choice_job_commit_recorded '+stay))==unchanged and state.read_bytes()==observe
        assert receive(state,'choice_receipt '+unused)['status']=='not_recorded'
        reread=receive(state,explain_cmd)
        assert reread['comparisons']==updated['comparisons']
        assert reread['head_sha256']!=updated['head_sha256']
        assert reread['decision']==output
        assert receive(state,choose_request)==win and receive(state,alternative_request)==other

        with live(beta,'--serve-fifo',state,d/'review_lanes','1') as service:
            assert 'lanes=1' in service.stdout.readline()
            assert receive(state,'choice_receipt '+chosen,endpoint=d/'review_lanes')==committed
            service.terminate();assert service.wait(timeout=8)==0
    bundle=d/'archive'
    assert b'transfer_exported' in run(beta,'--export-compact',state,bundle)
    restored=d/'archived_copy'
    assert b'activation=required' in run(beta,'--restore-copy',bundle,restored)
    revived=receive(restored,explain_cmd)
    assert revived['basis_sha256']==updated['basis_sha256'] and revived['comparisons']==updated['comparisons']
    assert revived['decision']==output
    assert receive(restored,choose_request)==win and receive(restored,alternative_request)==other

    assert run(beta,'--resume',restored,code=1)==b''
    rollback_seed=d/'for_rewind.cl'
    rollback_seed.write_text((root/'fixtures'/'producer.cl').read_text()+"""
: note(sym).
& initial trusted(alpha).
!trusted($x) <- monitor($x).
| hard positive trusted(alpha).
| wish unknown monitor(alpha).
""")
    rewind=d/'rewind'
    def drain(actor):
        actor.stdin.write('sample(alpha)\n');actor.stdin.flush()
        for _ in range(100):
            line=actor.stdout.readline()
            if line.startswith('POSITIVE plus=obs:signal'):return
        raise AssertionError('could not drain actual writer')
    with live(alpha,'--init-managed',rollback_seed,rewind) as actor:
        assert 'individual=' in actor.stdout.readline()
        plan=issue(actor,':plan').split()[1]
        drain(actor)
        assert issue(actor,':apply '+plan).startswith('revision_applied')
        drain(actor)
        assert 'observed mid' in issue(actor,':observe mid note(kept)')
        job=json.loads(issue(actor,':choice_job_start'))['id']
        ready_job=wait_for(actor,job)
        pick=ready_job['decision']['selected']
        assert ready_job['decision']['options'][pick]['kind']=='rollback'
        final=json.loads(issue(actor,':choice_job_commit_explained '+job))
        assert final['status']=='committed'
        attached=receive(rewind,f'choice_option {job} {pick}; trusted(alpha); note(kept)')
        stay=next(i for i,row in enumerate(final['options']) if row['kind']=='stay')
        refused=receive(rewind,f'choice_option {job} {stay}; trusted(alpha)')
        assert attached['was_selected'] and attached['kind']=='rollback' and attached['status']=='verified'
        assert [p['proof']['status'] for p in attached['results']]==['POSITIVE','POSITIVE']
        # Staying is ineligible because it violates the same signed hard objective.
        assert refused['status']=='blocked' and 'hard objective' in refused['reason']
        assert 'POSITIVE' in issue(actor,'note(kept)') and issue(actor,'monitor(alpha)')=='UNKNOWN'
print('PASS: the native PCGM reader reproduces the original complete choice and both selected and unchosen CL proof graphs; blocked and unavailable states differ; same proof survives later evidence, SIGKILL, A/B and offline transfer.')
