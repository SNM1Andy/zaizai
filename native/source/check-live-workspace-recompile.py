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
with TemporaryDirectory(prefix='PCGM native multi-library workspace versions ') as td:
    d=Path(td);imports=d/'imports';imports.mkdir();incoming=imports/'suite.clw'
    release=d/'release';release.mkdir()
    def create_lib(module,predicate,value):
        src=release/(module+'.cl')
        src.write_text(f"module {module}.\nexport {predicate}.\n: {predicate}(sym,qty(cny_cent)).\n& origin {predicate}(beta,{value}@cny_cent).\n")
        lock=release/(module+'.lock');lock.write_bytes(run(cl,'lock',src))
        api=release/(module+'.clapi');api.write_bytes(run(cl,'project-api',src,lock))
        pkg=release/(module+'.clpkg')
        pkg.write_bytes(run(cl,'project-pack',src,lock,api))
        return pkg,digest(pkg.read_bytes())
    cost,cost_pin=create_lib('cost','spent',11000)
    bonus,bonus_pin=create_lib('benefit','gain',200)
    lock=release/'production.lock'
    lock.write_text(f'CLWORK-1\nbenefit benefit.clpkg {bonus_pin} -\ncost cost.clpkg {cost_pin} -\n')
    lock_pin=digest(lock.read_bytes())
    other=release/'alternative.lock'
    alias=release/'cost2.clpkg';alias.write_bytes(cost.read_bytes())
    other.write_bytes(lock.read_bytes().replace(b'cost.clpkg',b'cost2.clpkg'))
    alt_pin=digest(other.read_bytes())
    def app(maximum,current=lock,key=lock_pin):
        src=release/'program.cl'
        src.write_text(f"module budget.\nuse benefit.\nuse cost.\nexport result.\n: result(sym).\n"
                       f"result($who) <- cost::spent($who,$spent) & benefit::gain($who,$gain) & "
                       f"qty_sub($spent,$gain,$net) & qty_le($net,{maximum}@cny_cent).\n")
        bundle=run(cl,'workspace-pack',src,current,key)
        tmp=d/'temp.clw';tmp.write_bytes(bundle)
        ir=run(cl,'workspace-bundle-ir',tmp,digest(bundle),key)
        return bundle,digest(bundle),digest(ir)
    a=app(10000)
    b=app(12000)
    new_source=(release/'program.cl').read_bytes()
    store_input=d/'build_inputs';store_input.mkdir()
    patch=store_input/'suite.cl';patch.write_bytes(new_source)
    incoming.write_bytes(a[0])
    candidate_pin=digest(new_source)
    generated=run(cl,'workspace-rebuild',incoming,a[1],lock_pin,patch,candidate_pin)
    assert generated==b[0],(digest(generated),b[1])
    def refusal(command,code,error):
        p=subprocess.run(command,capture_output=True,timeout=15)
        assert p.returncode==code and error in p.stderr and not p.stdout,(p.args,p)
    refusal([cl,'workspace-rebuild',incoming,a[1],lock_pin,patch,'0'*64],1,b'candidate source SHA-256 mismatch')
    changed_source=patch.parent/'bad.cl'
    changed_source.write_bytes(new_source+b'& injection result(beta).\n')
    refusal([cl,'workspace-rebuild',incoming,a[1],lock_pin,changed_source,digest(changed_source.read_bytes())],
            1,b'cannot change ground observations')
    renamed=patch.parent/'renamed.cl'
    renamed.write_bytes(new_source.replace(b'module budget.',b'module missing.'))
    refusal([cl,'workspace-rebuild',incoming,a[1],lock_pin,renamed,digest(renamed.read_bytes())],
            1,b'cannot change application module identity')
    changed_source.unlink();renamed.unlink()
    for f in release.iterdir():f.unlink()
    seed=d/'person.cl'
    seed.write_text("""
: mode(sym).
: note(sym).
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(expand).
""")
    state=d/'individual';goal='artifact_suite__result(beta)'
    def stage(stamp,source_pin=candidate_pin,base=a[1]):
        return f":retain_workspace_source suite {a[2]} {lock_pin} {base} {source_pin} {stamp}"
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,f':install_workspace suite {a[1]} {lock_pin}').startswith('package_installed')
        assert issue(actor,goal)=='UNKNOWN'
        before=state.read_bytes();head=digest(before)
        assert 'baseline changed' in issue(actor,stage('0'*64))
        assert 'not active' in issue(actor,stage(head,base='0'*64))
        assert 'source SHA-256 mismatch' in issue(actor,stage(head,source_pin='0'*64))
        assert state.read_bytes()==before
        retained=issue(actor,stage(head))
        assert retained.startswith('workspace_candidate_retained') and b[2] in retained,retained
        assert issue(actor,goal)=='UNKNOWN'
        meta=receive(state,'packages')['results']
        latest=next(row for row in meta if not row['active'])
        assert latest['workspace_source_sha256']==candidate_pin and latest['package_sha256']==b[1]
        assert latest['workspace_lock_sha256']==lock_pin
        incoming.unlink();patch.unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        assert 'observed expansion' in issue(actor,':observe expansion mode(expand)')
        basis=json.loads(issue(actor,':choice_job_start'))
        import time
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            ready=json.loads(issue(actor,':choice_job_status '+basis['id']))
            if ready['phase']=='ready':break
            time.sleep(.002)
        else: raise AssertionError('native source selection job did not resolve')
        completed=json.loads(issue(actor,':choice_job_commit_explained '+basis['id']))
        assert completed['options'][completed['selected']]['target']=='suite:'+b[2]
        assert issue(actor,goal).startswith('POSITIVE')
        info=receive(state,'choice_basis '+basis['id']+'; '+goal)
        assert info['comparisons'][0]['before']['status']=='UNKNOWN'
        assert info['comparisons'][0]['now']['status']=='POSITIVE'
        assert 'observed retained' in issue(actor,':observe retained note(later)')
        assert 'observed late' in issue(actor,':observe late mode(safe)')
        back=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert back['status']=='committed' and back['options'][back['selected']]['target']=='suite:'+a[2]
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(later)').startswith('POSITIVE')
        history=receive(state,'packages')['results']
        ready=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'packages')['results']==history
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(later)').startswith('POSITIVE')
        proof=receive(state,'choice_option '+basis['id']+' '+str(completed['selected'])+'; '+goal)
        assert proof['status']=='verified' and proof['results'][0]['proof']['status']=='POSITIVE'
print('PASS: actual independent CL recompiles pinned source into the identical full workspace archive; PCGM retains a source-built variant in-process, chooses and rolls it back, and preserves both provenance and the live individual across hard exit and A/B.')
