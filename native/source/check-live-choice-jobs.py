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
        output=json.loads(issue(actor,':choice_job_commit '+chosen))
        assert output['status']=='committed' and output['options'][output['selected']]['kind']=='rewrite'
        after=state.read_bytes()
        assert 'unknown active' in issue(actor,':choice_job_commit '+chosen) and state.read_bytes()==after
        assert issue(actor,'monitor(alpha)').startswith('POSITIVE')
        assert issue(actor,'later(kept)').startswith('POSITIVE')
        unused=json.loads(issue(actor,':choice_job_start'))['id']
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        assert 'unknown active' in issue(actor,':choice_job_commit '+unused)
        report=receive(state,'review 0 0 8')
        decisions=report['decisions']['results']
        assert len(decisions)==1 and decisions[0]['trace']['trigger']=='live_job:'+chosen
        assert issue(actor,'monitor(alpha)').startswith('POSITIVE')
        stay=json.loads(issue(actor,':choice_job_start'))['id']
        assert wait_for(actor,stay)['decision']['status']=='stay'
        before=state.read_bytes()
        assert json.loads(issue(actor,':choice_job_commit '+stay))['status']=='stay'
        assert before==state.read_bytes()
print('PASS: actual native PCGM computes while writer remains responsive; late evidence invalidates old choice, cancelled and killed jobs cannot commit, one fresh rewrite persists with the same identity.')
