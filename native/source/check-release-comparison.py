from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import json, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_bytes(data);return p
def call(tool,*args,code=0):
    r=subprocess.run([tool,*args],capture_output=True,timeout=20,env={'PATH':'','LC_ALL':'C'})
    assert r.returncode==code,(r.args,r.returncode,r.stderr)
    return r.stdout if not code else r.stderr

with TemporaryDirectory(prefix='CL release comparison with typed goals ') as tmp:
    d=Path(tmp)
    stage=root/'stages/module-scope.clir'
    source=b'''module market.
export permit.
export amount.
: permit(sym).
: quote(sym).
: route(sym).
: amount(qty(cny_cent)).
& listed quote(active).
& held route(active).
& base amount(10@cny_cent).
permit($x) <- quote($x).
'''
    def pack(name,text,scoped):
        directory=d/name;directory.mkdir()
        f=write(directory/'main.cl',text)
        lock=write(directory/'main.lock',call(cl,'lock',f))
        api=write(directory/'main.api',call(cl,'project-api',f,lock))
        body=call(cl,'project-scoped-pack',f,lock,api,stage,pin(stage)) if scoped else call(cl,'project-pack',f,lock,api)
        rmtree(directory)
        return write(d/(name+'.clpkg'),body)
    base=pack('before',source,True)
    compatible=pack('additive',source.replace(b'permit($x) <- quote($x).',b'permit($x) <- route($x).')+
                    b'export extra.\n: extra(sym).\nextra($x) <- quote($x).\n',True)
    breaking=pack('breaking',source.replace(b'export permit.\n',b'').replace(b'permit(',b'clearance(').
        replace(b'export amount.',b'input amount.').replace(b'cny_cent',b'usd_cent'),False)
    altered=pack('evidence',source.replace(b'quote(active)',b'quote(other)'),True)
    goals=write(d/'goals',b'permit(active)\namount(10@cny_cent)\n')
    def report(candidate):
        raw=call(cl,'package-compare',base,pin(base),candidate,pin(candidate),goals)
        value=json.loads(raw)
        assert value['semantic_equivalence_proved'] is False and value['committable'] is False
        assert value['baseline_sha256']==pin(base) and value['candidate_sha256']==pin(candidate)
        return value,raw
    add,raw_add=report(compatible)
    assert add['interface']=='additive' and add['scope']=='unchanged'
    assert add['observations']=={'added':0,'removed':0,'changed':0}
    assert add['tested_outcomes_changed']==0 and add['same_outcome_different_proof']==1,add
    assert add['proofs'][0]['same_sign_different_proof'] and not add['proofs'][1]['same_sign_different_proof']
    assert [e['change'] for e in add['exports']]==['added']
    bad,raw_bad=report(breaking)
    assert bad['interface']=='breaking' and bad['scope']=='removed'
    assert [p['after'] for p in bad['proofs']]==['UNAVAILABLE','UNAVAILABLE']
    assert bad['exports'][0]['before']=={'direction':'output','types':'qty(cny_cent)'}
    assert bad['exports'][0]['after']=={'direction':'input','types':'qty(usd_cent)'}
    changed,_=report(altered)
    assert changed['interface']=='unchanged' and changed['scope']=='unchanged'
    assert changed['observations']['changed']==1 and changed['tested_outcomes_changed']==1
    assert changed['proofs'][0]['after']=='UNKNOWN'
    assert b'candidate package digest mismatch' in call(cl,'package-compare',base,pin(base),compatible,'0'*64,goals,code=1)
    isolated=d/'native';isolated.mkdir()
    names={'cl-release-compare-sdk-check','libcl_runtime.so'}
    for name in names:copy2(root/name,isolated/name)
    executable=isolated/'cl-release-compare-sdk-check'
    for package,raw in ((compatible,raw_add),(breaking,raw_bad)):
        target=write(d/'receipt',raw)
        assert not call(executable,base,pin(base),package,pin(package),goals,target)
    assert {p.name for p in isolated.iterdir()}==names
print('PASS: independent native CL release comparison distinguishes exported API shape, scope downgrade, changed observations, changed signs and changed witnesses; isolated C SDK exactly matches CLI and reports no partial proof on exhaustion.')
