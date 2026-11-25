from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import json
import os
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
sandbox_env=dict(os.environ,PATH='',LC_ALL='C')
def call(exe,*args,cwd=None,stdin=None):
    p=subprocess.run([exe,*args],env=sandbox_env,cwd=cwd,input=stdin,capture_output=True,timeout=60)
    assert p.returncode==0,(p.args,p.returncode,p.stdout[:400],p.stderr[:1000])
    return p.stdout
def digest(p):
    return sha256(p.read_bytes()).hexdigest()
def put(p,data):
    p.write_bytes(data.encode() if isinstance(data,str) else data)
    return p
def pairs(*paths):
    return [x for p in paths for x in (p,digest(p))]

with TemporaryDirectory(prefix='Independent C host rebuilds its CL profile ') as path:
    d=Path(path)
    sdk=d/'relocated host';sdk.mkdir()
    for name in ('libcl_memory.so','cl-profile-rebuild-sdk-check'):
        copy2(root/name,sdk/name)
    host=sdk/'cl-profile-rebuild-sdk-check'
    baseline=root/'profiles'/'standard.clcp'
    std=root/'profiles'/'unicode-standard.clcp'
    grammar=copy2(root/'fixtures'/'unicode-standard-grammar.cl',d/'grammar.cl')
    types=copy2(root/'fixtures'/'numeric-type-checker.cl',d/'types.cl')
    lower=copy2(root/'fixtures'/'lowerer.cl',d/'lower.cl')
    smoke=put(d/'smoke.cl','? anchor(steady).\n: anchor(sym).\nanchor(steady).\n')
    smoke_ir=sha256(call(cl,'compile',smoke)).hexdigest()
    inputs=pairs(baseline,grammar,types,lower,smoke)+[smoke_ir]
    journal=d/'journal'
    live=call(cl,'compiler-init',journal,baseline,d,smoke,smoke_ir,stdin=(
        'a self_stage grammar types lower '+' '.join(map(digest,(baseline,grammar,types,lower)))+
        '\nb activate '+digest(std)+'\nc export_profile\n').encode())
    staged,active,exported=[json.loads(line) for line in live.splitlines()]
    assert staged['ok'] and staged['payload']['staged_profile_sha256']==digest(std)
    assert active['ok'] and active['payload']['active_profile_sha256']==digest(std)
    assert exported['ok']
    runtime=put(d/'unicode.cl',': data(sym).\ndata("独立回编").\n? data("独立回编").\n')
    expected=call(cl,'compile',runtime)
    result=d/'returned.clcp'
    receipt=d/'returned.json'
    def invoke(mode,args,*extra):
        return call(host,mode,*args,*extra,cwd=sdk)
    ir=invoke('rebuild',inputs,result,receipt,*pairs(runtime),digest(std))
    assert ir==expected
    assert result.read_bytes()==std.read_bytes()==bytes.fromhex(exported['payload']['profile_hex'])
    parsed=json.loads(receipt.read_bytes())
    assert parsed=={'schema':'cl-profile-rebuild-v1','baseline_sha256':digest(baseline),'grammar_sha256':digest(grammar),
        'types_sha256':digest(types),'lower_sha256':digest(lower),'smoke_source_sha256':digest(smoke),
        'smoke_ir_sha256':smoke_ir,'candidate_sha256':digest(result),'fixed_point':True,'applied':False}
    assert not invoke('audit',inputs,*pairs(result,receipt))
    assert not invoke('refuse-audit',inputs,baseline,'0'*64,*pairs(receipt),'candidate transfer digest mismatch')
    assert not invoke('refuse-audit',inputs,*pairs(baseline,receipt),'candidate differs from reconstruction')
    edited=put(d/'edited.json',receipt.read_bytes().replace(b'"applied":false',b'"applied":true'))
    assert not invoke('refuse-audit',inputs,*pairs(result,edited),'receipt differs from reconstruction')
    assert not invoke('refuse-audit',inputs,*pairs(result),receipt,'0'*64,'receipt transfer digest mismatch')
    for index,desc in [(1,'baseline profile'),(3,'grammar source'),(5,'type source'),(7,'lowering source'),(9,'smoke source')]:
        changed=inputs.copy();changed[index]='0'*64
        assert not invoke('refuse',changed,desc+' digest mismatch')
    assert not invoke('refuse',inputs[:-1]+['0'*64],'baseline failed the pinned smoke build')
    assert not invoke('refuse',pairs(std,grammar,types,lower,smoke)+[smoke_ir],'already active')
    broken=put(d/'reject_smoke.cl',Path(grammar).read_bytes()+b'\n!accept(unit) <- lex(0,ask).\n')
    assert not invoke('refuse',pairs(baseline,broken,types,lower,smoke)+[smoke_ir],'candidate stage self-check failed')
    assert set(x.name for x in sdk.iterdir())=={'libcl_memory.so','cl-profile-rebuild-sdk-check'}
print('PASS: relocated native C host emits the exact live-CL successor from pinned source, independently audits both buffers and refuses rehashed modifications, old/stale profiles and broken smoke; four threads and Unicode IR agree.')
