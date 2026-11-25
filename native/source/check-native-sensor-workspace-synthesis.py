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
    note=release/'program.cl'
    expected_source=digest(note.read_bytes())
    store_input=d/'build_inputs';store_input.mkdir()
    incoming.write_bytes(a[0])
    recipe_source=d/'recipe.cl'
    content="""
: scope_value(qty(cny_cent)).
: evidence_value(qty(cny_cent)).
: rewrite_amount(qty(cny_cent),qty(cny_cent)).
rewrite_amount($old,$new) <- scope_value($old) & evidence_value($new).
"""
    recipe_source.write_text(content)
    recipe=store_input/'suite.recipe.clir';recipe.write_bytes(run(cl,'compile',recipe_source))
    scope=store_input/'suite.recipe.scope'
    scope.write_text('CLWRECIPE-1\nresult qty_le 2 10000@cny_cent 8000@cny_cent 12500@cny_cent hint\n')
    recipe_pin,scope_pin=digest(recipe.read_bytes()),digest(scope.read_bytes())
    evidence='hint(12000@cny_cent)'
    choices=('workspace-synthesize-quantity',incoming,a[1],lock_pin,recipe,recipe_pin,scope,scope_pin)
    assert run(cl,*choices,evidence)==b[0]
    executable=d/'variant.clir'
    def bad_policy(addition,expected):
        recipe_source.write_text(content+addition)
        executable.write_bytes(run(cl,'compile',recipe_source))
        args=(choices[:4]+(executable,digest(executable.read_bytes()))+choices[6:]+(evidence,))
        p=subprocess.run([cl,*args],capture_output=True,timeout=10)
        assert p.returncode==1 and expected in p.stderr and not p.stdout,p
    bad_policy('!rewrite_amount(10000@cny_cent,12000@cny_cent).\n',b'output is conflicting')
    bad_policy('rewrite_amount(10000@cny_cent,12100@cny_cent).\n',b'more than one positive')
    bad_policy('& fake evidence_value(12000@cny_cent).\n',b'cannot manufacture')
    def refuse(atom,error):
        p=subprocess.run([cl,*choices,atom],capture_output=True,timeout=10)
        assert p.returncode==1 and error in p.stderr and not p.stdout,p
    refuse('hint(14000@cny_cent)',b'outside its exact scoped range')
    refuse('hint(12000@items)',b'wrong quantity unit')
    refuse('elsewhere(12000@cny_cent)',b'evidence predicate')
    for f in release.iterdir():f.unlink()
    seed=d/'person.cl'
    seed.write_text(f"""
: mode(sym).
: note(sym).
: hint(qty(cny_cent)).
~ sensor hint.
~ sensor !hint.
%% sensor suite hint {a[1]} {recipe_pin} {scope_pin}.
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(expand).
""")
    state=d/'individual';goal='artifact_suite__result(beta)'
    inbox=d/'incoming';inbox.mkdir()
    def packet(label,sequence,*facts):
        (inbox/(label+'.packet')).write_text(f"source sensor {sequence}\n"+'\n'.join(facts)+'\n')
    packet('conflict',1,'hint(12100@cny_cent)','!hint(12100@cny_cent)')
    packet('too_high',2,'hint(14000@cny_cent)')
    packet('paused',3,'hint(11900@cny_cent)')
    packet('permitted',4,evidence)
    def tick(actor,name,outcome):
        first=issue(actor,':cycle '+name)
        assert first.startswith('cycle_committed'),first
        detail=actor.stdout.readline().strip()
        assert outcome in detail,detail
        return detail
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,f':install_workspace suite {a[1]} {lock_pin}').startswith('package_installed')
        assert 'exactly one new clean' in tick(actor,'conflict','workspace_recipe_blocked')
        assert issue(actor,'hint(12100@cny_cent)').startswith('CONFLICT')
        assert 'outside its exact scoped range' in tick(actor,'too_high','workspace_recipe_blocked')
        assert issue(actor,'hint(14000@cny_cent)').startswith('POSITIVE')
        assert len(receive(state,'packages')['results'])==1
        assert 'paused' in issue(actor,':auto_pause sensor')
        tick(actor,'paused','workspace_recipe_paused')
        assert actor.stdout.readline().startswith('auto_revision paused')
        assert issue(actor,'hint(11900@cny_cent)').startswith('POSITIVE')
        assert len(receive(state,'packages')['results'])==1
        assert 'enabled' in issue(actor,':auto_resume sensor')
        assert b[2] in tick(actor,'permitted','workspace_recipe_retained')
        assert issue(actor,goal)=='UNKNOWN'
        proof=receive(state,'packages')['results']
        candidate=next(row for row in proof if not row['active'])
        assert candidate['workspace_recipe_sha256']==recipe_pin and candidate['workspace_recipe_evidence_sha256']==digest(evidence.encode())
        assert candidate['workspace_source_sha256']==expected_source and candidate['package_sha256']==b[1]
        before=state.read_bytes()
        assert issue(actor,':cycle permitted')=='cycle_unchanged sensor 4'
        assert state.read_bytes()==before
        incoming.unlink();recipe.unlink();scope.unlink()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and receive(state,'packages')['results']==proof
        assert issue(actor,'hint(12000@cny_cent)').startswith('POSITIVE')
        assert 'observed preference' in issue(actor,':observe preference mode(expand)')
        picked=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert picked['options'][picked['selected']]['target']=='suite:'+b[2]
        assert issue(actor,goal).startswith('POSITIVE')
        assert 'observed saved' in issue(actor,':observe saved note(retained)')
        assert 'observed safe' in issue(actor,':observe safe mode(safe)')
        back=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert back['options'][back['selected']]['target']=='suite:'+a[2]
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(retained)').startswith('POSITIVE')
        prepare=run(beta,'--prepare',state).decode()
        handoff=issue(actor,':handoff beta '+parse(prepare,'binary_sha256')+' '+parse(prepare,'snapshot_sha256'))
        assert handoff.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(handoff,'nonce')) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        assert receive(state,'packages')['results']==proof and issue(actor,'note(retained)').startswith('POSITIVE')
        assert issue(actor,':cycle permitted')=='cycle_unchanged sensor 4'
print('PASS: on actual authorized PCGM sensor evidence, native CL automatically generates an independently verified workspace variant without separate source request; invalid and paused evidence stays without mutation, replay/hard exit/A/B preserve both activity and audit.')
