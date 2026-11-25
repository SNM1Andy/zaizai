from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import re
import subprocess

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

cl=root/'cl'
with TemporaryDirectory(prefix='live native PCGM closed-fold accounting ') as td:
    d=Path(td);inputs=d/'build_inputs';inputs.mkdir()
    seed=d/'actor.cl'
    fold_fixture=root/'fixtures'/'closed-fold.cl'
    # One unsatisfied aggregate goal exercises the native needs scanner without treating it as an ordinary comparator.
    seed.write_text(fold_fixture.read_text()+'? total(active,777@cny_cent).\n')
    state=d/'individual'
    pkg_source=inputs/'ledger.cl';pkg_source.write_bytes(fold_fixture.read_bytes())
    stages=root/'profiles'/'closed-folds.clcp'
    profile=inputs/'ledger.clcp';profile.write_bytes(stages.read_bytes())
    profile_sha=digest(profile.read_bytes());source_sha=digest(pkg_source.read_bytes())
    image=run(cl,'profile-build',profile,profile_sha,pkg_source)
    image_sha=digest(image)
    assert image.startswith(b'CLIR-4\n')
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert 'POSITIVE' in issue(actor,'total(active,155@cny_cent)')
        assert 'supported' in issue(actor,':needs')
        while True:
            line=actor.stdout.readline()
            assert line and 'QUERY_ERROR' not in line
            if line.startswith('needs_end'):break
        p=issue(actor,':pin baseline')
        assert p.startswith('pin_committed')
        assert issue(actor,':observe fresh claims(active,spare,50@cny_cent)').startswith('observation_version')
        assert 'POSITIVE' in issue(actor,'total(active,205@cny_cent)')
        frozen=receive(state,'historical baseline total(active,155@cny_cent)')['result']
        assert frozen['status']=='POSITIVE'
        before=state.read_bytes()
        assert 'multiple amounts for one item' in issue(actor,':observe bad claims(active,early,10@cny_cent)')
        assert 'contains contradicted evidence' in issue(actor,':observe clash !claims(active,late,55@cny_cent)')
        assert before==state.read_bytes()
        assert 'withdrawn fresh' in issue(actor,':withdraw fresh')
        assert 'POSITIVE' in issue(actor,'total(active,155@cny_cent)')
        stamp=digest(state.read_bytes())
        stage=issue(actor,f':stage_cl ledger {profile_sha} {source_sha} {stamp}')
        assert image_sha in stage and stage.startswith('cl_staged'),stage
        done=issue(actor,f':commit_cl ledger {image_sha} {stamp}')
        assert done.startswith('cl_committed'),done
        pkg_source.unlink();profile.unlink()
        plain=receive(state,'proof artifact_ledger__total(active,155@cny_cent)')
        projected=receive(state,'slice artifact_ledger__total(active,155@cny_cent)')['proofs']
        assert plain['results']==projected['results'] and plain['results'][0]['status']=='POSITIVE'
        assert 'artifact_ledger__claims' in json.dumps(projected) and 'qty_fold_sum' in json.dumps(projected)
        batch=receive(state,'batch 4 artifact_ledger__total(active,155@cny_cent); artifact_ledger__total(empty,0@cny_cent)')
        assert len(batch['planes'])==1 and all(r['status']=='POSITIVE' for r in batch['results'])
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'proof artifact_ledger__total(active,155@cny_cent)')['results']==plain['results']
        ready=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'historical baseline total(active,155@cny_cent)')['result']==frozen
        assert receive(state,'proof artifact_ledger__total(active,155@cny_cent)')['results']==plain['results']
        assert 'POSITIVE' in issue(actor,'total(active,155@cny_cent)')
print('PASS: real native PCGM supports qualified authored CLIR-4 in its own engine, keeps it in dependency projections and proofs, recomputes on typed facts, safely declines conflicts, and restores proof and identity across hard exit and A/B.')
