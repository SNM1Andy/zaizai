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
: evidence_slot(sym,qty(cny_cent)).
: rewrite_slot(sym,qty(cny_cent),qty(cny_cent)).
rewrite_slot(main,$old,$new) <- scope_slot(main,$old) & evidence_slot(main,$new).
rewrite_slot(reserve,$old,$new) <- scope_slot(reserve,$old) & evidence_slot(reserve,$amount) & qty_add($amount,500@cny_cent,$new).
"""
    raw.write_text(base);recipe.write_bytes(run(cl,'compile',raw))
    scope.write_text("""CLWRECIPE-3
slot main result qty_le 2 10000@cny_cent 9000@cny_cent 12200@cny_cent hint
slot reserve reserve qty_le 2 10500@cny_cent 9500@cny_cent 13000@cny_cent ledger
via main sensor
via reserve accountant
""")
    rp,sp=digest(recipe.read_bytes()),digest(scope.read_bytes())
    fact='hint(12000@cny_cent)'
    evidence=(
        'CLWPROOFS-1\n'
        f'main sensor 1 {"a"*64} sensor_sensor_1_1 {fact}\n'
        f'reserve accountant 1 {"b"*64} sensor_accountant_1_1 ledger(12000@cny_cent)\n'
    )
    args=['workspace-synthesize-quantity',incoming,a[1],lock_pin,recipe,rp,scope,sp,evidence]
    assert run(cl,*args)==b[0]
    for bad in (evidence.rsplit('reserve',1)[0],evidence.replace('accountant 1','sensor 1'),
                evidence.replace('sensor_accountant_1_1','sensor_sensor_1_1'),evidence.replace('ledger(','hint('),
                evidence.replace('ledger(12000@cny_cent)','ledger(12000@hours)'),evidence.replace('ledger(12000','ledger(13000')):
        result=subprocess.run([cl,*args[:-1],bad],capture_output=True,timeout=10)
        assert result.returncode==1 and not result.stdout,result
    seed=d/'person.cl'
    seed.write_text(f"""
: mode(sym).
: memo(sym).
: hint(qty(cny_cent)).
: ledger(qty(cny_cent)).
~ sensor hint.
~ sensor mode.
~ accountant ledger.
= sensor versions suite.
%%+ sensor suite hint {a[1]} {rp} {sp}.
stable(ok).
| hard positive stable(ok).
| hard unknown artifact_suite__result(beta) when mode(safe).
| wish positive artifact_suite__result(beta) when mode(grow).
| wish positive artifact_suite__reserve(beta) when mode(grow).
""")
    state=d/'individual';inbox=d/'incoming';inbox.mkdir()
    def packet(name,source,seq,*facts):
        (inbox/(name+'.packet')).write_text(f'source {source} {seq}\n'+'\n'.join(facts)+'\n')
    packet('first','sensor',1,fact,'mode(grow)')
    packet('advice','accountant',1,'ledger(12000@cny_cent)')
    packet('later','sensor',2,fact)
    packet('ambiguous','accountant',2,'ledger(12000@cny_cent)','ledger(12100@cny_cent)')
    packet('third','sensor',3,fact)
    packet('clear','accountant',3,'ledger(12000@cny_cent)')
    packet('fourth','sensor',4,fact)
    packet('fifth','sensor',5,fact)
    packet('restraint','sensor',6,'mode(safe)')
    expected_evidence=(
        'CLWPROOFS-1\n'
        f'main sensor 5 {digest((inbox/"fifth.packet").read_bytes())} sensor_sensor_5_1 {fact}\n'
        f'reserve accountant 3 {digest((inbox/"clear.packet").read_bytes())} sensor_accountant_3_1 ledger(12000@cny_cent)\n'
    )
    expected_pin=digest(expected_evidence.encode())
    with live(alpha,'--init-managed',seed,state) as actor:
        uid=parse(actor.stdout.readline(),'individual')
        assert 'package_installed' in issue(actor,f':install_workspace suite {a[1]} {lock_pin}')
        incoming.unlink()
        def cycle(name,expected=None,outcome=None):
            assert 'cycle_committed' in issue(actor,':cycle '+name),(name,actor.poll())
            if expected:
                got=actor.stdout.readline().strip()
                assert expected in got,(name,got,expected)
            if outcome:
                got=actor.stdout.readline().strip()
                assert outcome in got,(name,got,outcome)
        cycle('first','waiting for a required source receipt','blocked')
        cycle('advice')
        assert 'withdrawn' in issue(actor,':withdraw sensor_accountant_1_1')
        cycle('later','lacks active positive evidence','blocked')
        cycle('ambiguous')
        cycle('third','ambiguous','blocked')
        cycle('clear')
        (inbox/'clear.packet').unlink()
        assert 'observed contradiction' in issue(actor,':observe contradiction !ledger(12000@cny_cent)')
        cycle('fourth','contradicted','blocked')
        assert 'withdrawn' in issue(actor,':withdraw contradiction')
        assert issue(actor,'artifact_suite__result(beta)')=='UNKNOWN'
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        cycle('fifth','workspace_recipe_retained suite '+b[2],'version_switched')
        assert 'POSITIVE' in issue(actor,'artifact_suite__result(beta)')
        assert 'POSITIVE' in issue(actor,'artifact_suite__reserve(beta)')
        assert 'observed preserved' in issue(actor,':observe preserved memo(new_fact)')
        cycle('restraint',a[2])
        assert issue(actor,'artifact_suite__result(beta)')=='UNKNOWN'
        assert issue(actor,'artifact_suite__reserve(beta)')=='UNKNOWN'
        assert issue(actor,'memo(new_fact)').startswith('POSITIVE')
    (inbox/'fifth.packet').unlink()
    result=receive(state,'packages')
    candidate=next(row for row in result['results'] if row['ir_sha256']==b[2])
    assert not candidate['active'] and candidate['workspace_recipe_evidence_sha256']==expected_pin,candidate
print('PASS: two separately authorized native sensor receipts are required for one atomic CL candidate; incomplete, withdrawn, ambiguous or contradictory evidence refuses; after hard exit the same PCGM chooses both edits and can roll back with later facts intact.')
