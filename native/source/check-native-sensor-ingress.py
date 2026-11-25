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
~ sensor mode.
= sensor versions suite.
%%+ sensor suite hint {a[1]} {recipe_pin} {scope_pin}.
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
    packet('paused',3,'hint(13900@cny_cent)')
    packet('permitted',4,evidence,'mode(expand)')
    packet('safe',5,'mode(safe)')
    packet('neutral',6,'mode(neutral)')
    def tick(actor,name,outcome):
        first=issue(actor,':cycle '+name)
        assert first.startswith('cycle_committed'),first
        detail=actor.stdout.readline().strip()
        assert outcome in detail,detail
        return detail
    def submit(actor,message):
        return json.loads(issue(actor,message))
    def frame(token,uid,label,forced=None):
        return f'{token} submit {uid} {label} {forced or digest((inbox/(label+".packet")).read_bytes())}'
    with live(alpha,'--init-managed',seed,state) as setup:
        uid=parse(setup.stdout.readline(),'individual')
        assert issue(setup,f':install_workspace suite {a[1]} {lock_pin}').startswith('package_installed')
        setup.kill();assert setup.wait(timeout=5)<0
    with live(alpha,'--resume-sensor-feed',state) as actor:
        start=json.loads(actor.stdout.readline())
        assert start['schema']=='pcgm-sensor-feed-v1' and start['individual']==uid
        frozen=state.read_bytes()
        false_hash=submit(actor,frame('misdigest',uid,'permitted','0'*64))
        assert false_hash['id']=='misdigest' and not false_hash['ok'] and 'SHA-256 mismatch' in false_hash['error']
        wrong_user=submit(actor,frame('misidentity','0'*32,'permitted'))
        assert wrong_user['id']=='misidentity' and not wrong_user['ok'] and 'another individual' in wrong_user['error']
        assert not submit(actor,':observe injection mode(expand)')['ok']
        assert not submit(actor,'x inspect '+uid+' permitted '+'0'*64)['ok']
        assert not submit(actor,'escape submit '+uid+' ../permitted '+'0'*64)['ok']
        assert not submit(actor,'a'*600)['ok']
        assert state.read_bytes()==frozen
        extra=subprocess.run([alpha,'--resume-sensor-feed',state],capture_output=True,timeout=6)
        assert extra.returncode==1 and b'writer' in extra.stderr
        for i,name in enumerate(('conflict','too_high','paused','permitted'),1):
            receipt=submit(actor,frame('request'+str(i),uid,name))
            assert receipt['ok'] and receipt['status']=='committed' and receipt['sequence']==i,receipt
            assert receipt['id']=='request'+str(i) and receipt['individual']==uid
        assert receipt['automatic_status']=='version_switched' and b[2] in receipt['automatic_detail']
        assert receive(state,'proof '+goal)['results'][0]['status']=='POSITIVE'
        placed=state.read_bytes()
        again=submit(actor,frame('duplicate',uid,'permitted'))
        assert again['status']=='already_applied' and again['automatic_detail']==receipt['automatic_detail']
        assert again['id']=='duplicate' and state.read_bytes()==placed
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert uid in actor.stdout.readline()
        pre=run(beta,'--prepare',state).decode()
        move=issue(actor,':handoff beta '+parse(pre,'binary_sha256')+' '+parse(pre,'snapshot_sha256'))
        assert move.startswith('handoff_prepared') and actor.wait(timeout=10)==0
    assert b'individual='+uid.encode() in run(beta,'--claim',state,parse(move,'nonce'))
    with live(beta,'--resume-sensor-feed',state) as actor:
        assert json.loads(actor.stdout.readline())['individual']==uid
        undone=submit(actor,frame('later',uid,'safe'))
        assert undone['status']=='committed' and undone['automatic_status']=='version_switched' and a[2] in undone['automatic_detail']
        assert receive(state,'proof '+goal)['results'][0]['status']=='UNKNOWN'
        assert receive(state,'proof hint(12000@cny_cent)')['results'][0]['status']=='POSITIVE'
        frozen=state.read_bytes()
        again=submit(actor,frame('recovered',uid,'permitted'))
        assert again['status']=='already_applied' and state.read_bytes()==frozen
        assert len(receive(state,'review 0 0 8')['decisions']['results'])==2
print('PASS: native correlated ingress is limited to preauthorized digest-pinned observations, demonstrates actual bounded CL generation/PCGM selection, denies other commands and wrong identity/hash, and replays idempotently after kill/A/B.')
