from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, re, subprocess

root=Path(__file__).resolve().parent
cl, pcgm=root/'cl',root/'pcgm-alpha'
fixture=root/'fixtures/closed-portfolio.cl'
grammar, lower=root/'stages/standalone-grammar.clir',root/'stages/lowerer.clir'
def h(value):return sha256(value).hexdigest()
def pin(path):return h(path.read_bytes())
def put(path,data):path.write_bytes(data);return path
def run(exe,*args,code=0,data=None,reason=b''):
    r=subprocess.run([exe,*args],input=data,capture_output=True,timeout=25)
    assert r.returncode==code,(r.args,r.returncode,r.stderr[:2000])
    if reason:assert reason in r.stderr and not r.stdout,r
    return r.stdout
@contextmanager
def live(exe,*args):
    with subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def frame(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
    out=p.stdout.readline()
    assert out,(s,p.poll())
    return out
def results(ent):
    return [r['status'] for r in ent['results']]

with TemporaryDirectory(prefix='native closed portfolio calculations ') as tmp:
    d=Path(tmp)
    text=fixture.read_bytes()
    expectation=[
        ('support_count(active,3)','POSITIVE'),('support_count(active,4)','UNKNOWN'),
        ('support_count(empty,0)','POSITIVE'),('top(empty,0@cny_cent)','UNKNOWN'),
        ('bottom(empty,0@cny_cent)','UNKNOWN'),('bottom(active,-9223372036854775808@cny_cent)','POSITIVE'),
        ('top(active,9223372036854775807@cny_cent)','POSITIVE'),
        ('top(active,17@cny_cent)','UNKNOWN'),('diversified(active)','POSITIVE')]
    goals=put(d/'goals',(''.join(goal+'\n' for goal,_ in expectation)).encode())
    image=run(cl,'compile',fixture)
    assert image.startswith(b'CLIR-5\n')
    ir=put(d/'portfolio.ir',image)
    assert run(cl,'ir-run',ir)==b''  # No built-in report goals in the reusable rules.
    legacy=root/'fixtures/closed-fold.cl'
    old=run(cl,'compile',legacy)
    assert old.startswith(b'CLIR-4\n')
    assert b'155@cny_cent' in run(cl,'ir-run',put(d/'legacy.ir',old))
    run(cl,'ir-run',put(d/'downgrade.ir',image.replace(b'CLIR-5\n',b'CLIR-4\n',1)),
        code=1,reason=b'extended closed folds require CLIR-5')
    run(cl,'ir-run',put(d/'upgrade.ir',old.replace(b'CLIR-4\n',b'CLIR-5\n',1)),
        code=1,reason=b'noncanonical arithmetic image version')
    stage=put(d/'checker.clir',run(cl,'compile',root/'fixtures/closed-fold-v2-type-checker.cl'))
    profile=put(d/'fold-v2.clcp',run(cl,'compiler-profile',grammar,stage,lower))
    assert stage.read_bytes()==(root/'stages/closed-fold-v2-type-checker.clir').read_bytes()
    assert profile.read_bytes()==(root/'profiles/closed-portfolio.clcp').read_bytes()
    assert run(cl,'profile-build',profile,pin(profile),fixture)==image
    assert run(cl,'grammar-direct-ir-segmented',grammar,stage,lower,fixture)==image
    old_profile=root/'profiles/closed-folds.clcp'
    run(cl,'profile-build',old_profile,pin(old_profile),fixture,code=1,reason=b'does not support extended closed folds')
    invalid=put(d/'invalid.cl',text.replace(b': support_count(sym,i64)',b': support_count(sym,qty(cny_cent))'))
    run(cl,'compile',invalid,code=1,reason=b'closed fold operand type mismatch')
    rr=json.loads(run(cl,'grammar-numeric-check',root/'fixtures/standalone-grammar.cl',
                      root/'fixtures/closed-fold-v2-type-checker.cl',invalid,code=2))
    assert rr['passed'] is False and b'variable_type' in json.dumps(rr).encode(),rr
    module=put(d/'ledger.cl',b'module ledger.\n'+text)
    lock=put(d/'lock',run(cl,'lock',module))
    api=put(d/'api',run(cl,'project-api',module,lock))
    pkg=put(d/'ledger.clpkg',run(cl,'project-pack',module,lock,api))
    proof=run(cl,'package-prove',pkg,pin(pkg),goals)
    assert results(json.loads(proof))==[state for _,state in expectation]
    full=json.loads(proof)['results']
    assert all(word in json.dumps(full) for word in ('qty_fold_count','qty_fold_min','qty_fold_max','quotes','middle'))
    journal=d/'journal'
    with live(cl,'evidence-init',pkg,pin(pkg),goals,journal) as writer:
        assert json.loads(frame(writer,'one view'))['ok']
        response=json.loads(frame(writer,'one batch addmore 0 ; observe new quotes(active,new,22@cny_cent)'))
        assert response['ok'],response
        newer=json.loads(frame(writer,'one view'))
        before=journal.read_bytes()
        bad=json.loads(frame(writer,'one batch duplicate_amt 1 ; observe conflicting quotes(active,middle,18@cny_cent)'))
        assert not bad['ok'] and journal.read_bytes()==before,bad
        writer.kill();assert writer.wait(timeout=5)<0
    with live(cl,'evidence-resume',pkg,pin(pkg),goals,journal) as writer:
        restored=json.loads(frame(writer,'one check'))
        for item in (newer,restored):
            for plane in item['payload']['planes']:plane.pop('evaluations')
        assert restored==newer
        assert restored['payload']['revision']==1
        receipt=json.loads(frame(writer,'one receipt addmore'))
        assert receipt['ok'] and 'committed' in json.dumps(receipt),receipt
    state=d/'pcgm-state'
    build=d/'build_inputs';build.mkdir()
    shell=put(build/'ledger.cl',text)
    shipped_profile=put(build/'ledger.clcp',profile.read_bytes())
    def key(line,k):return re.search(k+r'=([0-9a-z]+)',line)[1]
    def native_proof(state,atom):
        value=json.loads(run(pcgm,'--read-channel',state,data=('p proof '+atom+'\n').encode()))
        assert value['ok'],value
        return value['payload']['results'][0]
    with live(pcgm,'--init-managed',fixture,state) as actor:
        who=actor.stdout.readline()
        assert 'individual=' in who,who
        assert 'POSITIVE' in frame(actor,'support_count(active,3)')
        assert 'POSITIVE' in frame(actor,'bottom(active,-9223372036854775808@cny_cent)')
        before=state.read_bytes()
        assert 'contradicted evidence' in frame(actor,':observe deny !quotes(active,middle,17@cny_cent)')
        assert state.read_bytes()==before
        assert frame(actor,':observe fresh quotes(active,new,22@cny_cent)').startswith('observation_version')
        assert 'POSITIVE' in frame(actor,'support_count(active,4)')
        original=pin(state)
        stage_reply=frame(actor,f':stage_cl ledger {pin(shipped_profile)} {pin(shell)} {original}')
        assert h(image) in stage_reply,stage_reply
        commit=frame(actor,f':commit_cl ledger {h(image)} {original}')
        assert commit.startswith('cl_committed'),commit
        sealed=native_proof(state,'artifact_ledger__support_count(active,3)')
        assert sealed['status']=='POSITIVE'
        shell.unlink();shipped_profile.unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(pcgm,'--resume',state) as actor:
        assert actor.stdout.readline().split('individual=')[1].split()[0]==who.split('individual=')[1].split()[0]
        assert 'POSITIVE' in frame(actor,'support_count(active,4)')
        withdraw=frame(actor,':withdraw fresh');assert 'withdrawn fresh' in withdraw,withdraw
        assert 'POSITIVE' in frame(actor,'support_count(active,3)')
        assert native_proof(state,'artifact_ledger__support_count(active,3)')==sealed
        beta=root/'pcgm-beta'
        ready=run(beta,'--prepare',state).decode()
        move=frame(actor,':handoff beta '+key(ready,'binary_sha256')+' '+key(ready,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=8)==0
    with live(beta,'--claim',state,key(move,'nonce')) as replacement:
        assert key(replacement.stdout.readline(),'individual')==key(who,'individual')
        assert native_proof(state,'artifact_ledger__support_count(active,3)')==sealed
print('PASS: real native CLIR-5 count/min/max with empty, negative, extreme and conflicting records; authored stage and native IR agree; old IR compatibility, sealed evidence journal restart, and PCGM observation, authored artifact, recovery, and A/B are verified.')
