from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import json, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def h(b):return sha256(b).hexdigest()
def pin(p):return h(p.read_bytes())
def put(f,s):f.write_bytes(s if isinstance(s,bytes) else s.encode());return f
def run(tool,*args,code=0,error=b'',text_in=None):
    p=subprocess.run([tool,*args],input=text_in,capture_output=True,timeout=40,env={'PATH':'','LC_ALL':'C'})
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:600])
    if error:assert error in p.stderr and not p.stdout,p
    return p.stdout
def check(r,proof=None):
    rows=r['rules']; c=r['totals']
    assert sum(x['probes'] for x in rows)==c['probes']
    assert sum(x['indexed'] for x in rows)+c['between_rule_indexed']==c['indexed']
    assert c['queued_conclusions']==sum(x['queued_conclusions'] for x in rows)
    assert all(x['rounds_reached']<=c['rounds'] for x in rows)
    if proof:
        assert r['complete'] and r['resource_limit'] is None and r['proof_sha256']==h(proof)
        assert c['committed_facts']-c['initial_facts']==c['queued_conclusions']
    else:
        assert not r['complete'] and r['resource_limit'] and r['proof_sha256'] is None
with TemporaryDirectory(prefix='real logical rule budget profile ') as temp:
    d=Path(temp);source=d/'source';source.mkdir()
    program='''module main.
: edge(sym,sym).
: path(sym,sym).
: complete(sym).
path($x,$y) <- edge($x,$y).
path($x,$z) <- path($x,$y) & edge($y,$z).
complete(yes) <- path(n0,n27).
'''+''.join(f'& e{i} edge(n{i},n{i+1}).\n' for i in range(27))
    entry=put(source/'main.cl',program)
    lock=put(source/'main.lock',run(cl,'lock',entry))
    api=put(source/'main.api',run(cl,'project-api',entry,lock))
    pkg=put(d/'package',run(cl,'project-pack',entry,lock,api))
    deps=put(source/'controls.cl','module controls.\nexport accepted.\n: accepted(sym).\n& ready accepted(yes).\n')
    lock=put(source/'controls.lock',run(cl,'lock',deps))
    api=put(source/'controls.api',run(cl,'project-api',deps,lock))
    member=put(source/'controls.clpkg',run(cl,'project-pack',deps,lock,api))
    app=put(source/'linked.cl',program.replace('module main.','module main.\nuse controls.'))
    selected=put(source/'workspace.lock',f'CLWORK-1\ncontrols {member.name} {pin(member)} -\n')
    lock_pin=pin(selected)
    archive=put(d/'archive',run(cl,'workspace-pack',app,selected,lock_pin))
    rmtree(source)
    goals=put(d/'goals','complete(yes)\npath(n2,n18)\n')
    pkg_args=(pkg,pin(pkg),goals)
    work_args=(archive,pin(archive),lock_pin,goals)
    p=run(cl,'package-prove',*pkg_args)
    w=run(cl,'workspace-prove',*work_args)
    report1=run(cl,'package-profile',*pkg_args)
    report2=run(cl,'workspace-profile',*work_args)
    complete=json.loads(report1);check(complete,p);check(json.loads(report2),w)
    assert run(cl,'package-profile',*pkg_args)==report1
    assert run(cl,'package-prove',*pkg_args)==p
    assert len(complete['rules'])==3 and max(complete['rules'],key=lambda x:x['probes'])['rule']==2
    rounds=run(cl,'package-round-session',*pkg_args,text_in=b'finish\n')
    counters=json.loads(rounds.splitlines()[-1])
    for k in ('rounds','probes','indexed'):
        assert complete['totals'][k]==counters[k],(k,counters,complete)
    partial=None
    for caps,kind in [(('1','12000','2000000','2000000'),'fixpoint budget'),
                      (('128','1','2000000','2000000'),'fact limit'),
                      (('128','12000','1','2000000'),'join budget'),
                      (('128','12000','2000000','1'),'join index budget')]:
        raw=run(cl,'package-profile',*pkg_args,*caps)
        if kind=='join budget':partial=raw
        q=json.loads(raw)
        check(q);assert q['resource_limit']==kind,q
    run(cl,'package-profile',pkg,'0'*64,goals,code=1,error=b'profile package SHA')
    isolated=d/'host';isolated.mkdir()
    for name in ('cl-cost-profile-sdk-check','libcl_runtime.so'):copy2(root/name,isolated/name)
    expected1=put(d/'profile1',report1);expected2=put(d/'profile2',report2);lim=put(d/'limited',partial)
    assert not run(isolated/'cl-cost-profile-sdk-check',pkg,pin(pkg),archive,pin(archive),lock_pin,goals,expected1,expected2,lim)
print('PASS: native package and workspace profiles attribute deterministic work to actual source rules, match active-session counters and exact proof digests, report limited executions without proof, and match a detached native C client.')
