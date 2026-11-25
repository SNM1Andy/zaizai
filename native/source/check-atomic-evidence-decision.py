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
with TemporaryDirectory(prefix='verified CL evidence and equal native PCGM decision ') as td:
    d=Path(td);inbox=d/'incoming';inbox.mkdir()
    source=d/'growth.cl'
    profile=(root/'fixtures'/'producer.cl').read_text().replace('& permission authorized(alpha).\n','')
    source.write_text(profile+"""
: next_step(sym).
: necessary(sym).
: develop(sym).
: suspend(sym).
: audit(sym).
necessary($x) <- next_step($x).
authorized(alpha) <- next_step(go).
develop(run) <- next_step(go).
!develop(run) <- next_step(stop).
suspend(run) <- next_step(stop).
? necessary(go).
? necessary(stop).
? necessary(neutral).
stable(run).
| hard positive stable(run).
| wish positive monitor(alpha) when develop(run).
| wish unknown monitor(alpha) when suspend(run).
""")
    state=d/'individual'
    def pack(label):
        name='w_'+label
        src=d/(name+'.cl');lock=d/(name+'.lock');api=d/(name+'.clapi')
        src.write_text(f"module {name}.\n: next_step(sym).\n& evidence next_step({label}).\n")
        lock.write_bytes(run(cl,'lock',src));api.write_bytes(run(cl,'project-api',src,lock))
        pkg=inbox/(name+'.clpkg');pkg.write_bytes(run(cl,'project-pack',src,lock,api))
        return pkg,digest(pkg.read_bytes())
    def action(binary,label):
        q=next(q for q in receive(state,'question_feed 0 32')['results'] if q['needed']['arguments'][0]['value']==label)
        pkg,pin=pack(label)
        reviewed=json.loads(run(binary,'--question-bundle-review',state,q['id'],q['request_sha256'],pkg,pin))
        return q,f":admit_cl_decide {q['id']} {q['request_sha256']} {pkg.stem} {pin} {reviewed['proof_sha256']}"
    def trace(q):
        found=receive(state,'question '+q['id'])['results'][0]
        assert found['status']=='answered',found
        evidence=found['evidence'][0]
        assert evidence['active'] and 'cl_package_sha256' in evidence
        return evidence['assessment']
    with live(alpha,'--init-managed',source,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        ask=issue(actor,':ask')
        for _ in range(int(ask.split()[-1])):assert actor.stdout.readline().startswith('question ')
        assert 'questions_end' in actor.stdout.readline()
        go,rewrite=action(alpha,'go')
        output=issue(actor,rewrite)
        assert output.startswith('cl_evidence_committed'),output
        check=trace(go)
        assert check['status']=='committed' and check['options'][check['selected']]['kind']=='rewrite',check
        assert 'POSITIVE' in issue(actor,'monitor(alpha)')
        archive=state.read_bytes()
        assert issue(actor,rewrite).startswith('cl_evidence_unchanged') and state.read_bytes()==archive
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and trace(go)==check
        assert issue(actor,':observe later audit(kept)').startswith('observation_version')
        stop,revert=action(alpha,'stop')
        output=issue(actor,revert)
        assert output.startswith('cl_evidence_committed'),output
        rolled=trace(stop)
        assert rolled['status']=='committed' and rolled['options'][rolled['selected']]['kind']=='rollback',rolled
        assert {x['kind'] for x in rolled['options']}=={'stay','rollback','rewrite'}
        assert issue(actor,'monitor(alpha)')=='UNKNOWN'
        for fact in ('next_step(go)','next_step(stop)','audit(kept)'):
            assert issue(actor,fact).startswith('POSITIVE')
        before=receive(state,'status')['state']['epoch']
        plain,no_change=action(alpha,'neutral')
        assert issue(actor,no_change).startswith('cl_evidence_committed')
        stable=trace(plain)
        assert stable['status']=='stay' and stable['options'][stable['selected']]['kind']=='stay',stable
        assert receive(state,'status')['state']['epoch']==before
        archive=state.read_bytes()
        assert issue(actor,revert).startswith('cl_evidence_unchanged') and state.read_bytes()==archive
        returned=receive(state,'review 0 0 8; audit(kept)')
        assert [row['kind'] for row in returned['decisions']['results']]==['rewrite','rollback']
        prep=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(prep,'binary_sha256')+' '+parse(prep,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert trace(go)==check and trace(stop)==rolled and trace(plain)==stable
        assert issue(actor,'monitor(alpha)')=='UNKNOWN'
        assert 'POSITIVE' in issue(actor,'audit(kept)')
        before=state.read_bytes()
        assert issue(actor,no_change).startswith('cl_evidence_unchanged') and state.read_bytes()==before
print('PASS: verified local CL evidence and PCGM decision commit atomically; PCGM scores rewrite followed by rollback and stay, carries later evidence and receipts across SIGKILL and A/B, and never replays a decision.')
