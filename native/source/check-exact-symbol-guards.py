from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import json
import re
import subprocess

root=Path(__file__).resolve().parent
cl,pcgm=root/'cl',root/'pcgm-alpha'
env={'PATH':'','LC_ALL':'C'}
def call(exe,*args,code=0,why=b'',data=None,cwd=None):
    p=subprocess.run([exe,*args],input=data,cwd=cwd,env=env,capture_output=True,timeout=30)
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:250])
    assert why in p.stderr,(p.args,p.stderr)
    return p.stdout
def put(p,x):
    p.write_bytes(x.encode() if isinstance(x,str) else x)
    return p
def dig(p):
    return sha256(p.read_bytes()).hexdigest()
@contextmanager
def live(*args,cwd=None):
    with subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def ask(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
    result=p.stdout.readline()
    assert result,(s,p.poll())
    return result.strip()

rules='''%placeholder%
: input(sym).
: same(sym).
: different(sym).
: next(sym,sym).
: reach(sym).
& a input(bare).
& b input("bare").
& c input("é").
& d input("é").
& e input("中文 @ ; #").
same($x) <- input($x) & sym_eq($x,"é").
different($x) <- input($x) & sym_ne($x,"bare").
& ab next(bare,"中文 @ ; #").
& bc next("中文 @ ; #","中文 @ ; #").
& cd next("中文 @ ; #","终点").
reach(bare).
reach($y) <- reach($x) & next($x,$y) & sym_ne($x,$y).
'''.replace('%placeholder%\n','')
queries='? same("é").\n? same("é").\n? different(bare).\n? different("bare").\n? different("失踪输入").\n? reach("终点").\n'
with TemporaryDirectory(prefix='native CL exact symbolic conditions ') as temp:
    d=Path(temp)
    program=put(d/'source.cl',rules+queries)
    exact=call(cl,'compile',program)
    assert exact.startswith(b'CLIR-8\n')
    image=put(d/'new.clir',exact)
    field_names=['schema','results']
    result=json.loads(call(cl,'ir-json',image))
    assert all(key in result for key in field_names)
    by_goal={(r['goal']['predicate'],r['goal']['arguments'][0]['value'],
             r['goal']['arguments'][0].get('encoding')):r for r in result['results']}
    for name,symbol,encoding,want in [
        ('same','é','quoted_utf8','POSITIVE'),('same','é','quoted_utf8','UNKNOWN'),
        ('different','bare',None,'POSITIVE'),('different','bare','quoted_utf8','UNKNOWN'),
        ('different','失踪输入','quoted_utf8','UNKNOWN'),('reach','终点','quoted_utf8','POSITIVE')]:
        assert by_goal[(name,symbol,encoding)]['status']==want
    same=by_goal[('same','é','quoted_utf8')]
    checks=[check for node in same['positive']['nodes'] for check in node['checks']]
    assert any(x['predicate']=='sym_eq' and x['arguments']==[{'type':'sym','value':'é','encoding':'quoted_utf8'}]*2 for x in checks)
    ne=[check for node in by_goal[('different','bare',None)]['positive']['nodes'] for check in node['checks']]
    assert any(x['predicate']=='sym_ne' and [q.get('encoding') for q in x['arguments']]==[None,'quoted_utf8'] for x in ne)
    plain=put(d/'old.cl',': known(sym).\nknown("旧字节").\n? known("旧字节").\n')
    old=call(cl,'compile',plain);assert old.startswith(b'CLIR-7\n')
    bad=put(d/'bad.clir',old.replace(b'CLIR-7',b'CLIR-8',1))
    assert not call(cl,'ir-verify',bad,code=1,why=b'noncanonical')
    put(bad,exact.replace(b'CLIR-8',b'CLIR-7',1))
    assert not call(cl,'ir-verify',bad,code=1,why=b'require CLIR-8')

    published=root/'profiles'/'exact-symbol-guards.clcp'
    grammar=root/'stages'/'unicode-standard-grammar.clir'
    type_ir=put(d/'types.clir',call(cl,'compile',root/'fixtures'/'symbol-guard-type-checker.cl'))
    compiled_profile=call(cl,'compiler-profile',grammar,type_ir,root/'stages'/'lowerer.clir')
    assert type_ir.read_bytes()==(root/'stages'/'symbol-guard-type-checker.clir').read_bytes()
    assert published.read_bytes()==compiled_profile
    assert call(cl,'profile-build',published,dig(published),program)==exact
    legacy=root/'profiles'/'unicode-standard.clcp'
    assert not call(cl,'profile-build',legacy,dig(legacy),program,code=1,why=b'does not support exact symbolic comparisons')
    invalid=d/'invalid.cl'
    bad_cases=[
        (': value(i64).\n: proof(i64).\nvalue(1).\nproof($x) <- value($x) & sym_eq($x,1).\n',b'inconsistent type'),
        (': target(sym).\ntarget(ok) <- sym_eq($x,ok).\n',b'must be bound'),
        (': target(sym).\ntarget(ok) <- !sym_eq(ok,ok).\n',b'positive rule condition'),
        ('sym_ne(ok,yes).\n',b'positive rule condition'),
        (': target(sym).\ntarget(ok) <- sym_eq(ok).\n',b'two arguments'),
        (': target(sym).\ntarget(ok) <- sym_ne("12",12@cny_cent).\n',b'argument type mismatch')]
    for source,why in bad_cases:
        assert not call(cl,'compile',put(invalid,source),code=1,why=why)
        assert not call(cl,'profile-build',published,dig(published),invalid,code=1,why=b'type audit rejected')
    peer=put(d/'peer.cl','module peer.\nexport input.\n: input(sym).\n& remote input("语言：离线").\n')
    lock=put(d/'peer.lock',call(cl,'lock',peer))
    api=put(d/'peer.api',call(cl,'project-api',peer,lock))
    pkg=put(d/'peer.clpkg',call(cl,'project-pack',peer,lock,api))
    ws=put(d/'ws.lock',f'CLWORK-1\npeer peer.clpkg {dig(pkg)} -\n')
    wspin=dig(ws)
    app=put(d/'app.cl','module app.\nuse peer.\n: exact(sym).\nexact($k) <- peer::input($k) & sym_eq($k,"语言：离线").\n')
    bundle=put(d/'app.clw',call(cl,'workspace-pack',app,ws,wspin))
    assert call(cl,'workspace-bundle-ir',bundle,dig(bundle),wspin).startswith(b'CLIR-8\n')
    goals=put(d/'goals','exact("语言：离线")\nexact("语言：未知")\n')
    hostd=d/'detached host';hostd.mkdir()
    host=copy2(root/'cl-unicode-sdk-check',hostd/'proof-host')
    copy2(root/'libcl_memory.so',hostd)
    for f in (peer,lock,api,pkg,ws,app):f.unlink()
    args=(bundle,dig(bundle),wspin,goals)
    proof=call(cl,'workspace-prove',*args)
    assert call(host,*args,cwd=hostd)==proof
    assert [x['status'] for x in json.loads(proof)['results']]==['POSITIVE','UNKNOWN']
    inbox=d/'build_inputs';inbox.mkdir()
    copy2(program,inbox/'exact.cl');copy2(published,inbox/'exact.clcp')
    state=d/'state'
    seed=put(d/'seed.cl',': gate(sym).\ngate(keep).\n')
    with live(pcgm,'--init',seed,state,cwd=d) as actor:
        who=re.search(r'individual=(\w+)',actor.stdout.readline())[1]
        initial=dig(state)
        stmt=f':stage_cl exact {dig(published)} {dig(program)} {initial}'
        attempt=ask(actor,stmt)
        assert attempt.startswith('cl_staged exact ') and dig(image) in attempt,attempt
        assert dig(state)==initial
        decision=ask(actor,f':commit_cl exact {dig(image)} {initial}')
        assert decision.startswith('cl_committed exact '),decision
    (inbox/'exact.cl').unlink();(inbox/'exact.clcp').unlink()
    pin=dig(state)
    evidence=call(pcgm,'--read-channel',state,cwd=d,
        data='o generated\np inspect * 0; artifact_exact__reach("终点"); artifact_exact__same("é")\n'.encode())
    origins,proofs=[json.loads(x)['payload'] for x in evidence.splitlines()]
    assert origins['state']['individual']==who and origins['results'][0]['ir_sha256']==dig(image)
    assert [p['status'] for p in proofs['proofs']['results']]==['POSITIVE','UNKNOWN']
    assert 'sym_ne' in json.dumps(proofs) and dig(state)==pin
print('PASS: exact typed CL symbol guards compare canonical bytes through recursion, modules, CLIR-8, authored opt-in and detached C parity; PCGM explicitly adopts the same checked artifact and recovers its proof.')
