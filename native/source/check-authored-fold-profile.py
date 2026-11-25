from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess

root=Path(__file__).resolve().parent
cl=root/'cl'
def call(*args,code=0,reason=b''):
    p=subprocess.run([cl,*args],capture_output=True,timeout=30)
    assert p.returncode==code,(p.args,p.returncode,p.stderr[:1000],p.stdout[:1000])
    if reason:assert reason in p.stderr,(p.args,p.stderr[:1000])
    return p.stdout
def h(x):return sha256(x).hexdigest()
def put(path,bytes):path.write_bytes(bytes);return path
with TemporaryDirectory(prefix='CL-authored closed-fold profile ') as tmp:
    d=Path(tmp)
    fixture=root/'fixtures'/'closed-fold.cl'
    grammar=root/'stages'/'standalone-grammar.clir'
    lower=root/'stages'/'lowerer.clir'
    text_grammar=root/'fixtures'/'standalone-grammar.cl'
    checker_src=root/'fixtures'/'closed-fold-type-checker.cl'
    binary_checker=call('compile',checker_src)
    checker=put(d/'typed.clir',binary_checker)
    stages=call('compiler-profile',grammar,checker,lower)
    profile=put(d/'strict.clcp',stages)
    program=call('compile',fixture)
    assert program.startswith(b'CLIR-4\n')
    assert json.loads(call('grammar-numeric-check',text_grammar,checker_src,fixture))['passed']
    assert call('profile-build',profile,h(stages),fixture)==program
    assert call('grammar-direct-ir-segmented',grammar,checker,lower,fixture)==program
    assert call('profile-build',profile,h(stages),checker_src)==binary_checker
    previous=root/'profiles'/'standard.clcp'
    call('profile-build',previous,h(previous.read_bytes()),fixture,code=1,reason=b'does not support closed folds')
    tests={
        'wrong_unit':(': total(sym,qty(cny_cent))',': total(sym,qty(items))','variable_type'),
        'computed':('? total(empty,0@cny_cent).','? total(empty,0@cny_cent).\nclaims(active,bad,9@cny_cent).','sealed_fold_source_missing_proof'),
        'bad_group':('qty_fold_sum(claims,$g,$amount)','qty_fold_sum(claims,3,$amount)','literal_type'),
        'unknown_scope':('qty_fold_sum(claims,$g,$amount)','qty_fold_sum(private,$g,$amount)','sealed_fold_source_missing_proof'),
        'unbound_group':('qty_fold_sum(claims,$g,$amount)','qty_fold_sum(claims,$unseen,$amount)','operator_input_binding_missing_proof'),
        'dynamic_source':('qty_fold_sum(claims,$g,$amount)','qty_fold_sum($g,$g,$amount)','sealed_fold_source_missing_proof'),
    }
    for name,(old,new,error) in tests.items():
        f=put(d/(name+'.cl'),fixture.read_text().replace(old,new).encode())
        bad=json.loads(call('grammar-numeric-check',text_grammar,checker_src,f,code=2))
        assert not bad['passed'] and any(x['reason']==error for x in bad['diagnostics']),bad
        call('grammar-direct-ir-segmented',grammar,checker,lower,f,code=2,reason=error.encode())
    compiled=put(d/'fold.clir',program)
    assert b'total(empty,0@cny_cent) POSITIVE' in call('ir-run',compiled)
print('PASS: authored CL stage proves closed input and types, rebuilds itself byte-identically, and rejects six distinct invalid folds before the independent IR gate.')
