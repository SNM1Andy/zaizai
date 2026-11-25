from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import json
import re
import subprocess
import shutil

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
        src.write_text(f"module {module}.\nexport {predicate}.\n: {predicate}(sym,qty(cny_cent)).\n& origin {predicate}(beta,{value}@cny_cent).\n"+
                       f"& additional {predicate}(gamma,{value+(700 if module=='cost' else 0)}@cny_cent).\n")
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
    a,b,c=app(10000),app(11200),app(12000)
    inputs=d/'build_inputs';inputs.mkdir()
    source=d/'recipe.cl'
    source.write_text("""
: scope_value(qty(cny_cent)).
: evidence_value(qty(cny_cent)).
: rewrite_amount(qty(cny_cent),qty(cny_cent)).
rewrite_amount($old,$new) <- scope_value($old) & evidence_value($new).
""")
    stage=run(cl,'compile',source);recipe_pin=digest(stage)
    (inputs/f'suite.{recipe_pin}.clir').write_bytes(stage)
    def scope(prior,low,high):
        line=f'CLWRECIPE-1\nresult qty_le 2 {prior}@cny_cent {low}@cny_cent {high}@cny_cent hint\n'.encode()
        key=digest(line);(inputs/f'suite.{key}.scope').write_bytes(line)
        return key
    first_scope=scope(10000,9900,11500)
    second_scope=scope(11200,11000,13000)
    incoming.write_bytes(a[0])
    for f in release.iterdir():f.unlink()
    seed=d/'individual.cl'
    seed.write_text(f"""
: mode(sym).
: transfer_trace(sym).
: hint(qty(cny_cent)).
~ sensor hint.
~ sensor mode.
= sensor versions suite.
%%+ sensor suite hint {a[1]} {recipe_pin} {first_scope}.
%%+ sensor suite hint {b[1]} {recipe_pin} {second_scope}.
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(first).
| wish positive artifact_suite__result(gamma) when mode(second).
""")
    state=d/'individual';vault=Path(str(state)+'.workspaces')
    inbox=d/'incoming';inbox.mkdir()
    for sequence,items in enumerate((('hint(11200@cny_cent)','mode(first)'),
                ('hint(12000@cny_cent)','mode(second)'),('mode(safe)',),('hint(11100@cny_cent)',)),1):
        (inbox/f'event{sequence}.packet').write_text(f'source sensor {sequence}\n'+'\n'.join(items)+'\n')
    def auto(actor,n,recipe_msg=None,action='version_switched'):
        first=issue(actor,f':cycle event{n}'); assert first.startswith('cycle_committed'),first
        if recipe_msg:
            candidate=actor.stdout.readline().strip()
            assert recipe_msg in candidate,candidate
        chosen=actor.stdout.readline().strip()
        assert chosen.startswith('auto_revision '+action),chosen
        return chosen
    def stored(item):
        return vault/(item[1]+'.clw')
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,f':install_workspace suite {a[1]} {lock_pin}').startswith('package_installed')
        assert stored(a).read_bytes()==a[0]
        incoming.unlink()
        assert b[2] in auto(actor,1,'workspace_recipe_retained')
        assert stored(b).read_bytes()==b[0] and not incoming.exists() and not stored(c).exists()
        assert issue(actor,'artifact_suite__result(beta)').startswith('POSITIVE')
        assert issue(actor,'artifact_suite__result(gamma)')=='UNKNOWN'
        assert issue(actor,':pin first_generation').startswith('pin_committed')
        for n in range(130):
            assert 'observed history' in issue(actor,f':observe history{n} transfer_trace(n{n})')
        assert issue(actor,':seal_history '+digest(state.read_bytes())).startswith('archive_sealed')
        assert issue(actor,':compact_state '+digest(state.read_bytes())).startswith('state_representation compact')
        actor.kill();assert actor.wait(timeout=5)<0
    source_state=state
    bundle=d/'moved_release'
    assert b'transfer_exported' in run(alpha,'--export-complete',source_state,bundle)
    manifest=(bundle/'TRANSFER').read_text()
    assert manifest.startswith('PCGM_TRANSFER_4 ') and manifest.count('workspace ')==2
    assert 'episode ' in manifest and 'archive ' in manifest
    portable=bundle/'workspaces'/(b[1]+'.clw')
    payload=portable.read_bytes()
    assert payload==b[0]
    portable.write_bytes(payload[:-1])
    refuse=d/'rejected'
    r=subprocess.run([alpha,'--restore-copy',bundle,refuse],capture_output=True,timeout=15)
    assert r.returncode==1 and b'transferred workspace archive digest mismatch' in r.stderr
    assert not refuse.exists() and not Path(str(refuse)+'.workspaces').exists()
    portable.unlink()
    r=subprocess.run([alpha,'--restore-copy',bundle,refuse],capture_output=True,timeout=15)
    assert r.returncode==1 and b'cannot open transfer component' in r.stderr and not refuse.exists()
    portable.write_bytes(payload)
    target=d/'other_environment';target.mkdir()
    shutil.copytree(inputs,target/'build_inputs')
    shutil.copytree(inbox,target/'incoming')
    state=target/'individual';vault=Path(str(state)+'.workspaces')
    assert b'activation=required' in run(alpha,'--restore-copy',bundle,state)
    assert stored(a).read_bytes()==a[0] and stored(b).read_bytes()==b[0]
    assert not (target/'imports').exists() and not stored(c).exists()
    assert run(alpha,'--resume',state,code=1)==b''
    assert receive(state,'status')['restore_staged']
    hint=receive(state,'historical first_generation artifact_suite__result(beta)')['result']
    assert hint['status']=='POSITIVE'
    assert b'individual='+uid.encode() in run(alpha,'--activate-restored',state,'--source-stopped')
    assert not receive(state,'status')['restore_staged']
    # Make publisher vault and transfer copy unavailable, so the second generation can only use restored bytes.
    Path(str(source_state)+'.workspaces').rename(d/'retired_workspace')
    shutil.rmtree(bundle)
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        assert issue(actor,'transfer_trace(n100)').startswith('POSITIVE')
        assert c[2] in auto(actor,2,'workspace_recipe_retained')
        assert stored(c).read_bytes()==c[0] and not incoming.exists()
        assert all(issue(actor,'artifact_suite__result('+key+')').startswith('POSITIVE') for key in ('beta','gamma'))
        assert a[2] in auto(actor,3)
        assert issue(actor,'artifact_suite__result(beta)')=='UNKNOWN'
        assert issue(actor,'hint(12000@cny_cent)').startswith('POSITIVE')
        stamped=receive(state,'packages')['results']
        assert len(stamped)==3 and all(x['workspace_lock_sha256']==lock_pin for x in stamped)
        assert [x['target'] for x in receive(state,'review 0 0 8')['decisions']['results']]==['suite:'+q[2] for q in (b,c,a)]
        original=stored(a).read_bytes();stored(a).write_bytes(original[:-1])
        detail=auto(actor,4,'immutable local workspace archive digest mismatch',action='blocked')
        assert 'digest mismatch' in detail and issue(actor,'hint(11100@cny_cent)').startswith('POSITIVE')
        assert receive(state,'packages')['results']==stamped
        stored(a).write_bytes(original)
        checkpoint=state.read_bytes()
        assert issue(actor,':cycle event2')=='cycle_unchanged sensor 2' and state.read_bytes()==checkpoint
print('PASS: native complete offline transfer conserves the actor and all exact workspace dependencies and history; a new directory completes a second native generation without manual archive injection, and missing/corrupt inputs never activate a target.')
