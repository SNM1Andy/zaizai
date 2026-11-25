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
with TemporaryDirectory(prefix='native PCGM explicitly retained workspace dependency chain ') as td:
    d=Path(td);imports=d/'imports';imports.mkdir();incoming=imports/'suite.clw'
    publisher=d/'publisher';publisher.mkdir()
    def pack(path,module,statement):
        folder=publisher/path;folder.mkdir()
        src=folder/(module+'.cl');src.write_text(statement)
        lock=src.with_suffix('.lock');lock.write_bytes(run(cl,'lock',src))
        api=src.with_suffix('.clapi');api.write_bytes(run(cl,'project-api',src,lock))
        result=publisher/(path+'.clpkg');result.write_bytes(run(cl,'project-pack',src,lock,api))
        return path+'.clpkg',digest(result.read_bytes())
    cost=pack('cost','cost',"""
module cost.
export spent.
: spent(sym,qty(cny_cent)).
& source spent(beta,11000@cny_cent).
""")
    def benefit(path,factor,raw=100):
        return pack(path,'benefit',f"""
module benefit.
export gain.
: raw(sym,qty(cny_cent)).
: gain(sym,qty(cny_cent)).
& seed raw(beta,{raw}@cny_cent).
gain($x,$out) <- raw($x,$amount) & qty_ratio_floor($amount,{factor},1,$out).
""")
    dep_old,dep_new,dep_evidence=benefit('old',1),benefit('new',6),benefit('changed_evidence',8,200)
    def archive(label,dep,maximum=10600):
        lock=publisher/(label+'.lock')
        lock.write_text(f'CLWORK-1\nbenefit {dep[0]} {dep[1]} -\ncost {cost[0]} {cost[1]} -\n')
        pinned=digest(lock.read_bytes())
        src=publisher/'root.cl'
        src.write_text(f"module budget.\nuse benefit.\nuse cost.\nexport result.\n: result(sym).\n"
                       f"result($who) <- cost::spent($who,$spent) & benefit::gain($who,$gain) & "
                       f"qty_sub($spent,$gain,$net) & qty_le($net,{maximum}@cny_cent).\n")
        bytes_=run(cl,'workspace-pack',src,lock,pinned)
        path=d/'external.clw';path.write_bytes(bytes_)
        ir=run(cl,'workspace-bundle-ir',path,digest(bytes_),pinned)
        return bytes_,digest(bytes_),digest(ir),pinned
    old,new,changed=archive('first',dep_old),archive('second',dep_new),archive('bad',dep_evidence)
    positive_update=archive('positive_update',dep_new,10650)
    # The independently compiled folder and nested packages are not needed by the native receiver.
    state=d/'individual';source=d/'brain.cl'
    source.write_text("""
: mode(sym).
: memo(sym).
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safety).
| wish positive artifact_suite__result(beta) when mode(expand).
""")
    goal='artifact_suite__result(beta)'
    def admit(candidate,base,active=old,expected_lock=None):
        return (f":retain_workspace_dependencies suite {active[2]} {active[3]} "
                f"{expected_lock or candidate[3]} {candidate[1]} {base}")
    with live(alpha,'--init-managed',source,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        incoming.write_bytes(old[0])
        assert issue(actor,f':install_workspace suite {old[1]} {old[3]}').startswith('package_installed')
        assert issue(actor,goal)=='UNKNOWN'
        current=receive(state,'status')['state']['epoch']
        physical=state.read_bytes();stamp=digest(physical)
        incoming.write_bytes(new[0])
        assert 'baseline changed' in issue(actor,admit(new,'0'*64))
        assert 'lock does not match' in issue(actor,admit(new,stamp,expected_lock=changed[3]))
        incoming.write_bytes(changed[0])
        assert 'cannot replace observation evidence' in issue(actor,admit(changed,stamp))
        assert state.read_bytes()==physical
        incoming.write_bytes(new[0])
        introduced=issue(actor,admit(new,stamp))
        assert introduced.startswith('workspace_candidate_retained') and new[2] in introduced,introduced
        assert issue(actor,goal)=='UNKNOWN' and receive(state,'status')['state']['epoch']==current
        rows=receive(state,'packages')['results']
        assert len(rows)==2 and next(row for row in rows if row['active'])['workspace_lock_sha256']==old[3]
        assert {row['workspace_lock_sha256'] for row in rows}=={old[3],new[3]}
        incoming.unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        assert 'observed intention' in issue(actor,':observe intention mode(expand)')
        picked=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert picked['status']=='committed' and picked['options'][picked['selected']]['target']=='suite:'+new[2]
        assert issue(actor,goal).startswith('POSITIVE')
        # Same-lock replacements now use the selected version's lock, not whichever lock was first.
        incoming.write_bytes(positive_update[0])
        now=digest(state.read_bytes())
        result=issue(actor,f':replace_workspace suite {new[2]} {positive_update[1]} {now}')
        assert result.startswith('package_switched'),result
        incoming.unlink()
        assert 'observed retained' in issue(actor,':observe retained memo(later)')
        assert 'observed safety' in issue(actor,':observe safety mode(safety)')
        back=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert back['status']=='committed' and back['options'][back['selected']]['target']=='suite:'+old[2]
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'memo(later)').startswith('POSITIVE')
        history=receive(state,'packages')['results']
        ready=run(beta,'--prepare',state).decode()
        handoff=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert handoff.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(handoff,'nonce')) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        assert issue(actor,'memo(later)').startswith('POSITIVE')
        assert receive(state,'packages')['results']==history
print('PASS: native PCGM retains an explicitly pinned different workspace closure without activating it; real later scoring selects it and then returns to the previous lock, preserving immutable input/evidence and identity across forced exit and A/B.')
