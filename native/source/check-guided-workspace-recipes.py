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
    seed.write_text("""
: mode(sym).
: note(sym).
: hint(qty(cny_cent)).
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(expand).
""")
    state=d/'individual';goal='artifact_suite__result(beta)'
    def request(head,atom=evidence,stage=recipe_pin):
        return f":retain_workspace_recipe suite {a[2]} {lock_pin} {a[1]} {stage} {scope_pin} {head} {atom}"
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert issue(actor,f':install_workspace suite {a[1]} {lock_pin}').startswith('package_installed')
        before=state.read_bytes();head=digest(before)
        assert 'requires a clean grounded fact' in issue(actor,request(head)) and state.read_bytes()==before
        assert 'observed approved' in issue(actor,':observe approved '+evidence)
        assert 'observed dispute' in issue(actor,':observe dispute !'+evidence)
        head=digest(state.read_bytes())
        assert 'requires a clean grounded fact' in issue(actor,request(head))
        assert 'withdrawn dispute' in issue(actor,':withdraw dispute')
        before=state.read_bytes();head=digest(before)
        failure=issue(actor,request(head,stage='0'*64))
        assert 'stage digest mismatch' in failure or 'recipe authority digest mismatch' in failure
        assert state.read_bytes()==before
        retained=issue(actor,request(head))
        assert retained.startswith('workspace_candidate_retained') and b[2] in retained,retained
        assert issue(actor,goal)=='UNKNOWN'
        candidate=next(row for row in receive(state,'packages')['results'] if not row['active'])
        assert candidate['workspace_source_sha256']==expected_source and candidate['package_sha256']==b[1]
        assert candidate['workspace_recipe_sha256']==recipe_pin and candidate['workspace_recipe_scope_sha256']==scope_pin
        assert candidate['workspace_recipe_evidence_sha256']==digest(evidence.encode())
        incoming.unlink();recipe.unlink();scope.unlink()
        assert not (store_input/'suite.cl').exists()
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline() and issue(actor,goal)=='UNKNOWN'
        assert 'observed desired' in issue(actor,':observe desired mode(expand)')
        selected=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert selected['status']=='committed' and selected['options'][selected['selected']]['target']=='suite:'+b[2]
        assert issue(actor,goal).startswith('POSITIVE')
        assert 'observed later' in issue(actor,':observe later note(retained)')
        assert 'observed safe' in issue(actor,':observe safe mode(safe)')
        reversed_=json.loads(issue(actor,':decide_versions_parallel_json'))['decision']
        assert reversed_['status']=='committed' and reversed_['options'][reversed_['selected']]['target']=='suite:'+a[2]
        notes=receive(state,'packages')['results']
        ready=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(ready,'binary_sha256')+' '+parse(ready,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    with live(beta,'--claim',state,parse(move,'nonce')) as actor:
        assert uid in actor.stdout.readline()
        assert receive(state,'packages')['results']==notes
        assert issue(actor,goal)=='UNKNOWN' and issue(actor,'note(retained)').startswith('POSITIVE')
print('PASS: actual CL generates a precisely scoped source variant from clean signed evidence inside PCGM, refuses contradictory/ambiguous/out-of-range recipes, and the PCGM writer chooses and revises independently across hard exit/A/B.')
