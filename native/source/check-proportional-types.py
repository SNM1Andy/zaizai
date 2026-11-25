from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import random
import subprocess
import sys

root=Path(__file__).resolve().parent
cl=root/'cl'
pcgm=root/'pcgm-alpha'

def call(exe,*args,expected=0,error=b'',data=b''):
    p=subprocess.run([exe,*args],input=data,capture_output=True,timeout=20)
    assert p.returncode==expected,(p.args,p.returncode,p.stderr[:1200],p.stdout[:300])
    if error:assert error in p.stderr,(p.args,p.stderr)
    return p.stdout
def write(path,value):path.write_bytes(value);return path
def digest(data):return sha256(data).hexdigest()

with TemporaryDirectory(prefix='CL native checked proportional arithmetic ') as tmp:
    d=Path(tmp)
    sample=root/'fixtures'/'proportional.cl'
    built=call(cl,'compile',sample)
    assert built.startswith(b'CLIR-3\n'),built[:80]
    image=write(d/'compiled',built)
    assert call(cl,'ir-run',image)==call(cl,'run',sample)
    if len(sys.argv)>1:
        prev=Path(sys.argv[1]).resolve()
        call(prev,'ir-run',image,expected=1,error=b'unsupported or truncated CL IR image')
    spoof=write(d/'header_only',built.replace(b'CLIR-3\n',b'CLIR-2\n',1))
    call(cl,'ir-run',spoof,expected=1,error=b'requires CLIR-3')
    assert call(cl,'compile',root/'fixtures'/'arithmetic.cl').startswith(b'CLIR-2\n')
    expected=call(pcgm,sample,data=b'allocation(a,-668@cny_cent)\nreserve(a,-667@cny_cent)\n')
    assert expected.count(b'POSITIVE')==2
    grammar=root/'stages'/'standalone-grammar.clir'
    lower=root/'stages'/'lowerer.clir'
    checker=write(d/'ratio.clir',call(cl,'compile',root/'fixtures'/'proportional-type-checker.cl'))
    build_profile=call(cl,'compiler-profile',grammar,checker,lower)
    prof=write(d/'ratio.clcp',build_profile)
    stage=call(cl,'profile-build',prof,digest(build_profile),sample)
    assert stage==built,(stage[:80],built[:80])
    call(cl,'profile-build',root/'profiles'/'standard.clcp',digest((root/'profiles'/'standard.clcp').read_bytes()),sample,
         expected=1,error=b'does not support proportional arithmetic')
    inputs=d/'build_inputs';inputs.mkdir()
    transfer_source=write(inputs/'law.cl',sample.read_bytes())
    transfer_profile=write(inputs/'law.clcp',build_profile)
    seed=d/'seed.cl';seed.write_text('ready(ok).\n')
    actor=d/'actor'
    call(pcgm,'--init',seed,actor)
    state_before=digest(actor.read_bytes())
    commands=(f':stage_cl law {digest(build_profile)} {digest(transfer_source.read_bytes())} {state_before}\n'
              f':commit_cl law {digest(built)} {state_before}\n'
              'artifact_law__allocation(a,-668@cny_cent)\n')
    reports=call(pcgm,'--resume',actor,data=commands.encode())
    assert b'cl_staged law ' in reports and b'cl_committed law ' in reports and b'POSITIVE' in reports,reports
    for f in (transfer_source,transfer_profile):f.unlink()
    reopened=call(pcgm,'--read-channel',actor,data=b'x proof artifact_law__reserve(a,-667@cny_cent)\n')
    assert b'POSITIVE' in reopened and b'qty_ratio_ceil' in reopened,reopened
    wrong_type=d/'wrong_type.cl'
    wrong_type.write_text(sample.read_text().replace('reserve(sym,qty(cny_cent))','reserve(sym,qty(items))'))
    diag=call(cl,'grammar-numeric-check',root/'fixtures'/'standalone-grammar.cl',
              root/'fixtures'/'proportional-type-checker.cl',wrong_type,expected=2)
    assert b'variable_type' in diag or b'literal_type' in diag,diag
    def bad(old,new,reason,command='compile'):
        source=d/'incorrect.cl';source.write_text(sample.read_text().replace(old,new))
        call(cl,command,source,expected=1,error=reason)
    bad('rate(a,2,3)','rate(a,2,0)',b'denominator must be positive','run')
    bad('rate(a,2,3)','rate(a,2,-3)',b'denominator must be positive','run')
    bad('rate(a,2,3)','rate(a,9223372036854775807,1)',b'signed 64-bit ratio overflow','run')
    bad('qty_ratio_floor($pool,$numerator,$denominator,$result)',
        'qty_ratio_floor($pool,$pool,$denominator,$result)',b'ratio requires a quantity and two integer factors')
    bad('qty_ratio_floor($pool,$numerator,$denominator,$result)',
        'qty_ratio_floor($pool,$numerator,$missing,$result)',b'builtin input must be bound')
    bad('allocation(sym,qty(cny_cent))','allocation(sym,qty(items))',b'arithmetic result type mismatch')
    body=[': case(sym,qty(cny_cent),i64,i64).',': floor_to(sym,qty(cny_cent)).',': ceil_to(sym,qty(cny_cent)).',
          'floor_to($k,$r) <- case($k,$a,$b,$d) & qty_ratio_floor($a,$b,$d,$r).',
          'ceil_to($k,$r) <- case($k,$a,$b,$d) & qty_ratio_ceil($a,$b,$d,$r).']
    hi=2**63-1;lo=-2**63;rng=random.Random(42486)
    cases=[(hi,hi,hi),(lo,hi,hi),(hi,lo,hi),(lo,1,1),(0,lo,1),(1,lo,hi),
           (0,0,1),(-5,3,2),(5,-3,2),(-5,-3,2),(2,1,4),(hi,1,hi)]
    while len(cases)<360:
        a=rng.randint(lo,hi);b=rng.randint(lo,hi);divisor=rng.randint(1,hi)
        x=a*b//divisor;y=-((-a*b)//divisor)
        if lo<=x<=hi and lo<=y<=hi:cases.append((a,b,divisor))
    query=[]
    for number,(a,b,den) in enumerate(cases):
        key=f'i{number}'
        body.append(f'& e{number} case({key},{a}@cny_cent,{b},{den}).')
        expected=(a*b//den,-((-a*b)//den))
        for reference,goal in zip(expected,('floor_to','ceil_to')):
            query.append(f'{goal}({key},{reference}@cny_cent)')
    # Native CLI query limit is 64 per program; use the REPL's checked proof command on every row.
    random_src=d/'random.cl';random_src.write_text('\n'.join(body)+'\n')
    native=call(pcgm,random_src,data=('\n'.join(query)+'\n').encode())
    assert native.count(b'POSITIVE plus=')==len(query) and b'QUERY_ERROR' not in native
    for start in range(0,len(query),60):
        sample_path=d/'direct.cl'
        sample_path.write_text('\n'.join(body+['? '+goal+'.' for goal in query[start:start+60]])+'\n')
        output=call(cl,'run',sample_path)
        assert output.count(b'POSITIVE plus=')==len(query[start:start+60]),output[:300]
print('PASS: exact native CL proportional floor/ceil runs 720 checking queries against Python arbitrary-precision reference, PCGM shares semantics, authored profile compiles the same IR, and legacy/damaged images refuse.')
