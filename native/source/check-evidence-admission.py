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
with TemporaryDirectory(prefix='native PCGM admission of separately reviewed CL evidence ') as td:
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
    def pack(name,*facts):
        src=d/(name+'.cl');lock=d/(name+'.lock');api=d/(name+'.clapi')
        src.write_text(f"module {name}.\n: clearance(sym).\n"+''.join(f'& e{i} {atom}.\n' for i,atom in enumerate(facts)))
        lock.write_bytes(run(cl,'lock',src))
        api.write_bytes(run(cl,'project-api',src,lock))
        pkg=inbox/(name+'.clpkg');pkg.write_bytes(run(cl,'project-pack',src,lock,api))
        for f in (src,lock,api):f.unlink()
        return pkg,digest(pkg.read_bytes())
    def review(binary,q,pair):
        return json.loads(run(binary,'--question-bundle-review',state,q['id'],q['request_sha256'],*pair))
    def admit(q,pair,receipt):
        pkg,pin=pair
        return f":admit_cl {q['id']} {q['request_sha256']} {pkg.stem} {pin} {receipt}"
    supported=pack('positive','clearance(alpha)')
    opposed=pack('negative','!clearance(beta)')
    conflicted=pack('both','clearance(alpha)','!clearance(alpha)')
    undetermined=pack('none','clearance(beta)')
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
            assert 'cannot admit conflicted or unknown' in issue(actor,admit(a,bad,reviewed['proof_sha256']))
        assert 'match reviewed proof' in issue(actor,admit(a,supported,'0'*64))
        assert 'no longer open' in issue(actor,admit(dict(a,request_sha256='0'*64),supported,'0'*64))
        exact=review(alpha,a,supported)['proof_sha256']
        exact_negative=review(alpha,b,opposed)['proof_sha256']
        assert before==state.read_bytes()
        first=admit(a,supported,exact)
        second=admit(b,opposed,exact_negative)
        assert issue(actor,':observe side audit(keep)').startswith('observation_version')
        commit=issue(actor,first)
        assert commit.startswith('cl_evidence_committed') and exact in commit
        obs=commit.split()[2]
        state1=state.read_bytes()
        question=receive(state,'question '+a['id'])['results'][0]
        assert question['status']=='answered'
        assert question['evidence']==[{'observation':obs,'active':True,'cl_package_sha256':supported[1],
                                        'cl_proof_sha256':exact,'request_sha256':a['request_sha256']}]
        assert receive(state,'proof granted(alpha)')['results'][0]['status']=='POSITIVE'
        assert issue(actor,first).startswith('cl_evidence_unchanged') and state1==state.read_bytes()
        assert issue(actor,second).startswith('cl_evidence_committed')
        assert receive(state,'question '+b['id'])['results'][0]['status']=='opposed'
        supported[0].unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        before=state.read_bytes()
        assert 'cl_evidence_unchanged' in issue(actor,first) and before==state.read_bytes()
        ready=run(beta,'--prepare',state).decode()
        moved=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert moved.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(moved,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'question '+a['id'])['results'][0]==question
        saved=state.read_bytes()
        assert issue(actor,first).startswith('cl_evidence_unchanged') and saved==state.read_bytes()
        assert 'POSITIVE' in issue(actor,'audit(keep)')
        assert 'withdrawn '+obs in issue(actor,':withdraw '+obs)
        assert receive(state,'question '+a['id'])['results'][0]['evidence'][0]['active'] is False
        stopped=state.read_bytes()
        assert issue(actor,first).startswith('cl_evidence_unchanged') and state.read_bytes()==stopped
        assert receive(state,'proof granted(alpha)')['results'][0]['status']=='UNKNOWN'
print('PASS: native PCGM explicitly admits pinned single-sign CL evidence, refuses conflicts and stale or fabricated digest, retains exact receipt across kill/A/B, and replay does not restore withdrawn evidence.')
