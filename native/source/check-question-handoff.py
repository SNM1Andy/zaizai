from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import re
import subprocess
import sys

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

with TemporaryDirectory(prefix='PCGM typed native question and durable local answer ') as td:
    d=Path(td)
    inbox=d/'incoming';inbox.mkdir()
    source=d/'questions.cl'
    source.write_text('''
: clearance(sym).
: granted(sym).
: audit(sym).
granted($x) <- clearance($x).
? granted(alpha).
? granted(beta).
? granted(gamma).
''')
    state=d/'individual'
    with live(alpha,'--init-managed',source,state) as p:
        uid=parse(p.stdout.readline(),'individual')
        assert issue(p,':ask')=='questions_created 3'
        for _ in range(3):
            assert p.stdout.readline().startswith('question ')
        assert 'questions_end count=3' in p.stdout.readline()
        before=digest(state.read_bytes())
        page=receive(state,'question_feed 0 1')
        assert page['schema']=='pcgm-question-feed-v1' and page['more'] and page['revision_sha256']==before
        extra=receive(state,f"question_feed {page['cursor']} 32")
        assert not extra['more'] and extra['cursor']>page['cursor']
        questions=page['results']+extra['results']
        by_name={q['needed']['arguments'][0]['value']:q for q in questions}
        one,two,three=[by_name[x] for x in ('alpha','beta','gamma')]
        assert len(questions)==3 and all(q['status']=='open' and not q['evidence'] for q in questions)
        assert state.exists() and digest(state.read_bytes())==before
        with live(alpha,'--serve-fifo',state,d/'lanes','1') as service:
            assert 'lanes=1' in service.stdout.readline()
            assert receive(state,'question '+one['id'],endpoint=d/'lanes')['results']==[one]
            service.terminate();assert service.wait(timeout=8)==0
        write_packet(inbox,'foreign','0'*32,one,'local','clearance(alpha)')
        assert 'different individual' in issue(p,':answer_packet foreign')
        write_packet(inbox,'wrong',uid,one,'local','clearance(beta)')
        assert 'does not match question' in issue(p,':answer_packet wrong')
        write_packet(inbox,'bad_pin',uid,one,'local','clearance(alpha)',sha='0'*64)
        assert 'no longer open' in issue(p,':answer_packet bad_pin')
        assert digest(state.read_bytes())==before
        plus=write_packet(inbox,'good',uid,one,'desk','clearance(alpha)')
        assert issue(p,':observe later audit(kept)').startswith('observation_version')
        committed=issue(p,':answer_packet good')
        recv_id=committed.split()[2]
        assert committed.startswith('answer_packet_committed ') and plus in committed
        next=receive(state,'question '+one['id'])['results'][0]
        assert next['status']=='answered' and next['request_sha256']!=one['request_sha256']
        assert next['evidence']==[{'observation':recv_id,'active':True,'source_label':'desk','packet_sha256':plus}]
        after=digest(state.read_bytes())
        assert issue(p,':answer_packet good').startswith('answer_packet_unchanged') and digest(state.read_bytes())==after
        write_packet(inbox,'late',uid,one,'second','!clearance(alpha)')
        assert 'no longer open' in issue(p,':answer_packet late') and digest(state.read_bytes())==after
        negative=write_packet(inbox,'negative',uid,two,'desk','!clearance(beta)')
        assert negative in issue(p,':answer_packet negative')
        assert receive(state,'question '+two['id'])['results'][0]['status']=='opposed'
        assert receive(state,'question '+three['id'])['results'][0]['status']=='open'
        proof=receive(state,'proof granted(alpha)')['results'][0]
        assert proof['status']=='POSITIVE'
        p.kill();assert p.wait(timeout=5)<0
    if len(sys.argv)>1:
        legacy=Path(sys.argv[1]).resolve()
        prior=state.read_bytes()
        reject=subprocess.run([legacy,'--resume',state],capture_output=True,timeout=5)
        assert reject.returncode==1 and b'invalid persistent event' in reject.stderr and state.read_bytes()==prior
    with live(alpha,'--resume',state) as p:
        assert uid in p.stdout.readline()
        old=digest(state.read_bytes())
        assert issue(p,':answer_packet good').startswith('answer_packet_unchanged')
        assert issue(p,':answer_packet negative').startswith('answer_packet_unchanged') and digest(state.read_bytes())==old
        data=run(beta,'--prepare',state).decode()
        moved=issue(p,':handoff beta '+parse(data,'binary_sha256')+' '+parse(data,'snapshot_sha256'))
        assert moved.startswith('handoff_prepared') and p.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(moved,'nonce')) as p:
        assert uid in p.stdout.readline()
        old=digest(state.read_bytes())
        assert issue(p,':answer_packet good').startswith('answer_packet_unchanged') and digest(state.read_bytes())==old
        assert 'POSITIVE' in issue(p,'audit(kept)')
        assert receive(state,'question '+one['id'])['results'][0]==next
        for index in range(130):
            assert issue(p,f':observe more{index} audit(t{index})').startswith('observation_version')
        assert issue(p,':seal_history '+digest(state.read_bytes())).startswith('archive_sealed')
        assert issue(p,':compact_state '+digest(state.read_bytes())).startswith('state_representation compact')
        assert issue(p,':answer_packet good').startswith('answer_packet_unchanged')
        assert receive(state,'question '+one['id'])['results'][0]==next
    transfer=d/'transfer'
    out=run(beta,'--export-compact',state,transfer)
    assert b'transfer_exported' in out and (transfer/'TRANSFER').read_text().startswith('PCGM_TRANSFER_3 ')
    restored=d/'restored'
    assert b'activation=required' in run(beta,'--restore-copy',transfer,restored)
    assert receive(restored,'question '+one['id'])['results'][0]==next
    assert run(beta,'--resume',restored,code=1)==b''
print('PASS: PCGM independently publishes native question pins and commits local typed answer evidence exactly once across later observations, hard exit, A/B handoff and compact archives.')
