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
cl=root/'cl'
with TemporaryDirectory(prefix='native PCGM admission of cross-library workspace evidence ') as td:
    d=Path(td);inbox=d/'incoming';inbox.mkdir()
    source=d/'questions.cl'
    source.write_text("""
: clearance(sym).
: granted(sym).
: audit(sym).
granted($x) <- clearance($x).
? granted(alpha).
? granted(beta).
""")
    state=d/'individual'
    def publish(name,*facts):
        publisher=d/(name+'_publisher');publisher.mkdir()
        entries=[]
        for module in ('controls','evid'):
            src=publisher/(module+'.cl');lock=src.with_suffix('.lock');api=src.with_suffix('.api')
            pkg=src.with_suffix('.clpkg')
            if module=='controls':
                src.write_text("module controls.\nexport active.\n: active(sym).\n& enabled active(gate).\n")
            else:
                src.write_text("module evid.\nexport recorded.\n: recorded(sym).\n"+
                    "".join(f"& f{i} {fact}.\n" for i,fact in enumerate(facts)))
            lock.write_bytes(run(cl,'lock',src))
            api.write_bytes(run(cl,'project-api',src,lock))
            if module=='controls':
                stage=root/'stages/module-scope.clir'
                scope=digest(stage.read_bytes())
                pkg.write_bytes(run(cl,'project-scoped-pack',src,lock,api,stage,scope))
            else:
                scope='-'
                pkg.write_bytes(run(cl,'project-pack',src,lock,api))
            entries.append(f"{module} {pkg.name} {digest(pkg.read_bytes())} {scope}\n")
        app=publisher/'app.cl'
        app.write_text("""module evidence.
use controls.
use evid.
: clearance(sym).
: audit(sym).
clearance($x) <- controls::active(gate) & evid::recorded($x).
!clearance($x) <- controls::active(gate) & !evid::recorded($x).
& decoy audit(unauthorized).
""")
        lock=publisher/'workspace.lock';lock.write_text('CLWORK-1\n'+''.join(entries))
        work_pin=digest(lock.read_bytes())
        archive=inbox/(name+'.clw')
        archive.write_bytes(run(cl,'workspace-pack',app,lock,work_pin))
        for item in publisher.iterdir():item.unlink()
        publisher.rmdir()
        return archive,digest(archive.read_bytes()),work_pin
    def review(binary,q,archive):
        return json.loads(run(binary,'--workspace-question-review',state,q['id'],q['request_sha256'],*archive))
    def admit(q,archive,receipt):
        candidate,pin,lock=archive
        return f":admit_workspace {q['id']} {q['request_sha256']} {candidate.stem} {pin} {lock} {receipt}"
    supported=publish('positive','recorded(alpha)')
    opposed=publish('negative','!recorded(beta)')
    conflicted=publish('both','recorded(alpha)','!recorded(alpha)')
    undetermined=publish('none','recorded(beta)')
    counterfeit=inbox/'counterfeit.clw'
    counterfeit.write_bytes(supported[0].read_bytes()[:-1]+b'x')
    tampered=(counterfeit,digest(counterfeit.read_bytes()),supported[2])
    with live(alpha,'--init-managed',source,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,':ask')=='questions_created 2'
        for i in range(2):assert actor.stdout.readline().startswith('question ')
        assert 'questions_end' in actor.stdout.readline()
        output=receive(state,'question_feed 0 2')
        key={q['needed']['arguments'][0]['value']:q for q in output['results']}
        a,b=key['alpha'],key['beta']
        before=state.read_bytes()
        for bad in (conflicted,undetermined):
            reviewed=review(alpha,a,bad)
            assert reviewed['cl_proof']['results'][0]['status'] in ('CONFLICT','UNKNOWN')
            assert 'cannot admit unknown or conflicted' in issue(actor,admit(a,bad,reviewed['proof_sha256']))
        assert 'archive body digest mismatch' in issue(actor,admit(a,tampered,'0'*64))
        wrong_lock=supported[0],supported[1],'0'*64
        assert 'lock does not match' in issue(actor,admit(a,wrong_lock,'0'*64))
        assert 'match reviewed proof' in issue(actor,admit(a,supported,'0'*64))
        assert 'stale request address' in issue(actor,admit(dict(a,request_sha256='0'*64),supported,'0'*64))
        reviewed=review(alpha,a,supported)
        assert reviewed['observation_written'] is False and reviewed['individual']==uid
        assert reviewed['cl_proof']['results'][0]['status']=='POSITIVE'
        assert reviewed['cl_proof']['results'][0]['goal']['arguments'][0]['value']=='alpha'
        exact=reviewed['proof_sha256']
        exact_goal=d/'exact-goal';exact_goal.write_text('clearance(alpha)\n')
        independently=run(cl,'workspace-prove',*supported,exact_goal)
        assert digest(independently)==exact and json.loads(independently)==reviewed['cl_proof']
        assert 'match reviewed proof' in issue(actor,admit(b,supported,exact))
        exact_negative=review(alpha,b,opposed)['proof_sha256']
        assert before==state.read_bytes()
        first=admit(a,supported,exact)
        second=admit(b,opposed,exact_negative)
        assert issue(actor,':observe side audit(keep)').startswith('observation_version')
        commit=issue(actor,first)
        assert commit.startswith('workspace_evidence_committed') and exact in commit
        obs=commit.split()[2]
        state1=state.read_bytes()
        question=receive(state,'question '+a['id'])['results'][0]
        assert question['status']=='answered'
        assert question['evidence']==[{'observation':obs,'active':True,'cl_workspace_archive_sha256':supported[1],
                                        'cl_proof_sha256':exact,'request_sha256':a['request_sha256'],
                                        'cl_workspace_lock_sha256':supported[2]}]
        assert receive(state,'proof granted(alpha)')['results'][0]['status']=='POSITIVE'
        assert receive(state,'proof audit(unauthorized)')['results'][0]['status']=='UNKNOWN'
        assert issue(actor,first).startswith('workspace_evidence_unchanged') and state1==state.read_bytes()
        assert issue(actor,second).startswith('workspace_evidence_committed')
        assert receive(state,'question '+b['id'])['results'][0]['status']=='opposed'
        supported[0].unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        before=state.read_bytes()
        assert 'workspace_evidence_unchanged' in issue(actor,first) and before==state.read_bytes()
        ready=run(beta,'--prepare',state).decode()
        moved=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert moved.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(moved,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'question '+a['id'])['results'][0]==question
        saved=state.read_bytes()
        assert issue(actor,first).startswith('workspace_evidence_unchanged') and saved==state.read_bytes()
        assert 'POSITIVE' in issue(actor,'audit(keep)')
        assert 'withdrawn '+obs in issue(actor,':withdraw '+obs)
        assert receive(state,'question '+a['id'])['results'][0]['evidence'][0]['active'] is False
        logical=receive(state,'storage')['logical_sha256']
        sealed=issue(actor,':seal_history '+logical)
        assert sealed.startswith('archive_sealed'),sealed
        logical=receive(state,'storage')['logical_sha256']
        compact=issue(actor,':compact_state '+logical)
        assert compact.startswith('state_representation compact'),compact
        assert state.read_bytes().startswith(b'PCGM-COMPACT-1\n')
        stopped=state.read_bytes()
        assert issue(actor,first).startswith('workspace_evidence_unchanged') and state.read_bytes()==stopped
        assert receive(state,'proof granted(alpha)')['results'][0]['status']=='UNKNOWN'
print('PASS: independent CL proofs span two locked libraries; PCGM reviews read-only, adopts only the exact question observation, rejects forgery or ambiguity, and retains exact provenance through restart, A/B, compaction and source removal without duplicate admission.')
