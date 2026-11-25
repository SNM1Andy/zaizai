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
    def app(maximum,secondary):
        src=release/'program.cl'
        src.write_text(f"module budget.\nuse benefit.\nuse cost.\nexport result.\nexport reserve.\n"
                       f": result(sym).\n: reserve(sym).\n"
                       f"result($who) <- cost::spent($who,$spent) & benefit::gain($who,$gain) & "
                       f"qty_sub($spent,$gain,$net) & qty_le($net,{maximum}@cny_cent).\n"
                       f"reserve($who) <- cost::spent($who,$spent) & benefit::gain($who,$gain) & "
                       f"qty_sub($spent,$gain,$net) & qty_le($net,{secondary}@cny_cent).\n")
        bundle=run(cl,'workspace-pack',src,lock,lock_pin)
        tmp=d/'temp.clw';tmp.write_bytes(bundle)
        ir=run(cl,'workspace-bundle-ir',tmp,digest(bundle),lock_pin)
        return bundle,digest(bundle),digest(ir)
    a,b=app(10000,10500),app(12000,12500)
    incoming.write_bytes(a[0])
    build=d/'build_inputs';build.mkdir()
    recipe=build/'suite.recipe.clir';scope=build/'suite.recipe.scope'
    raw=d/'recipe.cl'
    base="""
: scope_slot(sym,qty(cny_cent)).
: evidence_value(qty(cny_cent)).
: rewrite_slot(sym,qty(cny_cent),qty(cny_cent)).
rewrite_slot(main,$old,$new) <- scope_slot(main,$old) & evidence_value($new).
rewrite_slot(reserve,$old,$new) <- scope_slot(reserve,$old) & evidence_value($amount) & qty_add($amount,500@cny_cent,$new).
"""
    raw.write_text(base);recipe.write_bytes(run(cl,'compile',raw))
    scope.write_text("""CLWRECIPE-2
slot main result qty_le 2 10000@cny_cent 9000@cny_cent 12200@cny_cent hint
slot reserve reserve qty_le 2 10500@cny_cent 9500@cny_cent 13000@cny_cent hint
""")
    rp,sp=digest(recipe.read_bytes()),digest(scope.read_bytes())
    fact='hint(12000@cny_cent)'
    args=['workspace-synthesize-quantity',incoming,a[1],lock_pin,recipe,rp,scope,sp,fact]
    assert run(cl,*args)==b[0]
    def deny(argument,error):
        result=subprocess.run([cl,*argument],capture_output=True,timeout=10)
        assert result.returncode==1 and error in result.stderr and not result.stdout,result
    for mutation,error in [
        (base+'!rewrite_slot(main,10000@cny_cent,12000@cny_cent).\n',b'conflicting'),
        (base+'rewrite_slot(main,10000@cny_cent,12100@cny_cent).\n',b'multiple positive'),
        ('\n'.join(line for line in base.splitlines() if not line.startswith('rewrite_slot(reserve')),b'every slot')]:
        raw.write_text(mutation)
        changed=d/'bad.clir';changed.write_bytes(run(cl,'compile',raw))
        deny(args[:4]+[changed,digest(changed.read_bytes())]+args[6:],error)
    outside=d/'other.scope'
    outside.write_text(scope.read_text().replace('13000@','12100@'))
    deny(args[:6]+[outside,digest(outside.read_bytes()),fact],b'outside exact slot')
    for f in release.iterdir():f.unlink()
    seed=d/'person.cl'
    seed.write_text(f"""
: mode(sym).
: memo(sym).
: hint(qty(cny_cent)).
~ sensor hint.
~ sensor mode.
= sensor versions suite.
%%+ sensor suite hint {a[1]} {rp} {sp}.
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(grow).
| wish positive artifact_suite__reserve(beta) when mode(grow).
""")
    state=d/'individual';inbox=d/'incoming';inbox.mkdir()
    (inbox/'growth.packet').write_text(f'source sensor 1\n{fact}\nmode(grow)\n')
    (inbox/'restraint.packet').write_text('source sensor 2\nmode(safe)\n')
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert 'package_installed' in issue(actor,f':install_workspace suite {a[1]} {lock_pin}')
        incoming.unlink()
        assert 'cycle_committed' in issue(actor,':cycle growth')
        result=actor.stdout.readline().strip();outcome=actor.stdout.readline().strip()
        assert 'workspace_recipe_retained' in result and b[2] in result,result
        assert 'version_switched' in outcome and b[2] in outcome,outcome
        assert 'POSITIVE' in issue(actor,'artifact_suite__result(beta)')
        assert 'POSITIVE' in issue(actor,'artifact_suite__reserve(beta)')
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        assert 'observed preserved' in issue(actor,':observe preserved memo(new_fact)')
        assert 'cycle_committed' in issue(actor,':cycle restraint')
        assert a[2] in actor.stdout.readline()
        assert issue(actor,'artifact_suite__result(beta)')=='UNKNOWN'
        assert issue(actor,'artifact_suite__reserve(beta)')=='UNKNOWN'
        assert issue(actor,'memo(new_fact)').startswith('POSITIVE')
print('PASS: independent compound CL proof changes both scoped operands in one candidate, rejects conflicting/partial/out-of-range outcomes, and actual PCGM adopts both or neither; rollback and hard exit preserve new facts.')
