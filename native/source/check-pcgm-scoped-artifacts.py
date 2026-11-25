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
with TemporaryDirectory(prefix='PCGM real scoped package family ') as td:
    d=Path(td);inputs=d/'imports';inputs.mkdir();incoming=inputs/'law.clpkg'
    project=d/'project';project.mkdir()
    scope=(root/'fixtures'/'module-scope.cl').read_text()
    def authored(label,text):
        src=d/(label+'.cl');src.write_text(text)
        path=d/(label+'.clir');path.write_bytes(run(cl,'compile',src))
        return path,digest(path.read_bytes())
    required=authored('required',scope)
    other=authored('other',scope+': flag(sym).\nflag(other).\n')
    def built(maximum,policy=None):
        src=project/'root.cl';lock=project/'root.lock';api=project/'root.clapi'
        src.write_text(f"""
module root.
export result.
: spent(sym,qty(cny_cent)).
: result(sym).
& payment spent(beta,11000@cny_cent).
result($x) <- spent($x,$cost) & qty_le($cost,{maximum}@cny_cent).
""")
        lock.write_bytes(run(cl,'lock',src))
        api.write_bytes(run(cl,'project-api',src,lock))
        body=run(cl,'project-scoped-pack',src,lock,api,*policy) if policy else run(cl,'project-pack',src,lock,api)
        path=d/'exact';path.write_bytes(body)
        image=run(cl,'package-ir',path)
        return body,digest(body),digest(image)
    a=built(10000,required)
    b=built(12000,required)
    unscoped=built(12000)
    wrong=built(12000,other)
    legacy=built(9000)
    seed=d/'person.cl'
    seed.write_text("""
: mode(sym).
: note(sym).
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_law__result(beta) when mode(safe).
| wish positive artifact_law__result(beta) when mode(expand).
""")
    state=d/'individual';goal='artifact_law__result(beta)'
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        before=state.read_bytes()
        incoming.write_bytes(a[0])
        assert 'explicit scoped installation' in issue(actor,':install_pkg law '+a[1])
        assert 'does not satisfy' in issue(actor,f':install_scoped_pkg law {a[1]} {other[1]}')
        assert state.read_bytes()==before
        outcome=issue(actor,f':install_scoped_pkg law {a[1]} {required[1]}')
        assert outcome.startswith('package_installed') and a[2] in outcome
        assert issue(actor,goal)=='UNKNOWN'
        info=receive(state,'packages')['results'][0]
        assert info['package_sha256']==a[1] and info['scope_policy_sha256']==required[1]
        assert len(info['scope_report_sha256'])==64 and info['active']
        assert 'different scope policy' in issue(actor,f':install_scoped_pkg law {a[1]} {other[1]}')
        assert 'observed expansion' in issue(actor,':observe expansion mode(expand)')
        before=state.read_bytes()
        memo=digest(before)
        for candidate in (unscoped,wrong):
            incoming.write_bytes(candidate[0])
            assert 'does not satisfy' in issue(actor,f':replace_pkg law {a[2]} {candidate[1]} {memo}')
            assert state.read_bytes()==before
        assert 'full-package revision route' in issue(actor,f':replace_ir law {a[2]} {b[2]} {memo}')
        incoming.write_bytes(b[0])
        refreshed=issue(actor,f':replace_pkg law {a[2]} {b[1]} {memo}')
        assert refreshed.startswith('package_switched') and b[1] in refreshed,refreshed
        assert issue(actor,goal).startswith('POSITIVE')
        rows=receive(state,'packages')['results']
        assert len(rows)==2 and all(x['scope_policy_sha256']==required[1] for x in rows)
        assert next(x for x in rows if x['active'])['package_sha256']==b[1]
        incoming.unlink();assert 'observed afterward' in issue(actor,':observe afterward note(retained)')
        assert 'observed safe' in issue(actor,':observe safe mode(safe)')
        receipt=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert receipt['status']=='committed' and receipt['options'][receipt['selected']]['target']=='law:'+a[2]
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(retained)').startswith('POSITIVE')
        assert next(x for x in receive(state,'packages')['results'] if x['active'])['package_sha256']==a[1]
        (inputs/'old.clpkg').write_bytes(legacy[0])
        assert issue(actor,':install_pkg old '+legacy[1]).startswith('package_installed')
        assert 'scope_policy_sha256' not in next(x for x in receive(state,'packages')['results'] if x['alias']=='old')
        (inputs/'old.clpkg').unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        patch=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(patch,'binary_sha256')+' '+parse(patch,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert sorted(x['scope_policy_sha256'] for x in receive(state,'packages')['results'] if x['alias']=='law')==[required[1],required[1]]
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(retained)').startswith('POSITIVE')
        before=state.read_bytes()
        assert 'package_unchanged' in issue(actor,f':install_scoped_pkg law {a[1]} {required[1]}')
        assert state.read_bytes()==before
print('PASS: native live PCGM keeps one externally pinned CL scope for all approved family versions, rejects v1/wrong-scope/raw bypasses, can choose the retained original, and preserves provenance, evidence and identity through SIGKILL and A/B.')
