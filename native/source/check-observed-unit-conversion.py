from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, subprocess

r=Path(__file__).resolve().parent
cl,alpha=r/'cl', r/'pcgm-alpha'
fixture=r/'fixtures/observed-unit-conversion.cl'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def put(p,data):p.write_bytes(data if isinstance(data,bytes) else data.encode());return p
def call(tool,*args,code=0,error=b'',data=None):
    p=subprocess.run([tool,*args],input=data,capture_output=True,timeout=25,env={'PATH':'','LC_ALL':'C'})
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:200])
    if error:assert error in p.stderr and not p.stdout,p
    return p.stdout
@contextmanager
def live(tool,*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def issue(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
    row=p.stdout.readline()
    assert row,(s,p.poll())
    return row
def evidence(p,s,good=True):
    value=json.loads(issue(p,'a '+s))
    assert value['ok']==good,value
    return value['payload'] if good else value['error']
def names(report):
    out={}
    items=report.get('results') if 'results' in report else [p for plane in report['planes'] for p in plane['results']]
    for i in items:
        goal=i['goal']
        key=goal.get('predicate') or goal.get('relation')
        val=tuple(str(x['value'])+('@'+x['unit'] if 'unit' in x else '') for x in goal['arguments'])
        out[key,val]=i['status']
    return out

with TemporaryDirectory(prefix='native CL observed conversion ') as temp:
    d=Path(temp)
    src=fixture.read_text()
    grammar=r/'stages/standalone-grammar.clir'
    checker=r/'stages/observed-unit-type-checker.clir'
    lower=r/'stages/lowerer.clir'
    profile=r/'profiles/observed-unit-conversion.clcp'
    native=call(cl,'compile',fixture)
    assert native.startswith(b'CLIR-6\n')
    assert call(cl,'compile',r/'fixtures/observed-unit-type-checker.cl')==checker.read_bytes()
    assert call(cl,'compiler-profile',grammar,checker,lower)==profile.read_bytes()
    assert call(cl,'profile-build',profile,pin(profile),fixture)==native
    assert call(cl,'grammar-direct-ir-segmented',grammar,checker,lower,fixture)==native
    old=r/'profiles/closed-portfolio.clcp'
    call(cl,'profile-build',old,pin(old),fixture,code=1,error=b'does not support observed unit conversions')
    altered=put(d/'forced-v5.ir',native.replace(b'CLIR-6\n',b'CLIR-5\n',1))
    call(cl,'ir-run',altered,code=1,error=b'unit conversion requires CLIR-6')
    errors={
        'output':(src.replace(': lower(sym,qty(token)).',': lower(sym,qty(kg)).'),'explicit target'),
        'rate':(src.replace(': quote(sym,sym,i64,i64).',': quote(sym,sym,i64,qty(token)).'),'conversion source requires'),
        'computed':(src+'quote(cny_cent,token,1,1).\n','must contain observations only'),
        'same':(src.replace('qty_convert_floor(quote,$amount,token,$v)','qty_convert_floor(quote,$amount,cny_cent,$v)'),'two distinct units'),
    }
    for name,(text,mismatch) in errors.items():
        f=put(d/(name+'.cl'),text)
        call(cl,'compile',f,code=1,error=mismatch.encode())
    authored=r/'fixtures/observed-unit-type-checker.cl'
    for name,reason in [('same','same_unit'),('computed','observed_conversion_source_missing_proof')]:
        rejection=json.loads(call(cl,'grammar-numeric-check',r/'fixtures/standalone-grammar.cl',authored,
                                  d/(name+'.cl'),code=2))
        assert not rejection['passed'] and reason in json.dumps(rejection),rejection
    module=put(d/'native.cl','module native.\n'+src)
    lock=put(d/'lock',call(cl,'lock',module))
    api=put(d/'api',call(cl,'project-api',module,lock))
    pkg=put(d/'package',call(cl,'project-pack',module,lock,api))
    goals=put(d/'goals','lower(negative,-8@token)\nupper(negative,-7@token)\nupper(positive,8@token)\ntotal(negative,-6@token)\n')
    args=pkg,pin(pkg),goals,d/'journal'
    stat=lambda v:[item['status'] for plane in v['planes'] for item in plane['results']]
    with live(cl,'evidence-init',*args) as actor:
        assert stat(evidence(actor,'view'))==['UNKNOWN']*4
        assert evidence(actor,'batch authorized 0 ; observe supplied quote(cny_cent,token,3,2)')['status']=='committed'
        good=evidence(actor,'check')
        assert stat(good)==['POSITIVE']*4,good
        assert 'supplied' in json.dumps(good)
        before=args[3].read_bytes()
        assert 'multiple asserted rates' in evidence(actor,'batch conflict 1 ; observe another quote(cny_cent,token,1,1)',False)
        assert 'is contradicted' in evidence(actor,'batch denied 1 ; observe denied !quote(cny_cent,token,3,2)',False)
        assert args[3].read_bytes()==before
        actor.kill();assert actor.wait(timeout=5)<0
    with live(cl,'evidence-resume',*args) as actor:
        refresh=evidence(actor,'check')
        for item in (good,refresh):
            for plane in item['planes']:plane.pop('evaluations')
        assert refresh==good
        assert evidence(actor,'batch invalid 1 ; withdraw supplied ; observe zero quote(cny_cent,token,3,0)',False).endswith('must be strictly positive')
        assert stat(evidence(actor,'check'))==['POSITIVE']*4
        assert evidence(actor,'batch drop 1 ; withdraw supplied')['status']=='committed'
        assert stat(evidence(actor,'view'))==['UNKNOWN']*4  # never infer reverse conversion
    state=d/'individual'
    with live(alpha,'--init-managed',fixture,state) as actor:
        who=actor.stdout.readline()
        assert 'individual=' in who
        assert 'UNKNOWN' in issue(actor,'lower(negative,-8@token)')
        assert issue(actor,':observe supplied quote(cny_cent,token,3,2)').startswith('observation_version')
        assert 'POSITIVE' in issue(actor,'lower(negative,-8@token)')
        assert 'POSITIVE' in issue(actor,'upper(positive,8@token)')
        actor.kill();assert actor.wait(timeout=5)<0
    with live(alpha,'--resume',state) as actor:
        assert who.split('individual=')[1].split()[0] in actor.stdout.readline()
        assert 'POSITIVE' in issue(actor,'total(negative,-6@token)')
        check=json.loads(call(alpha,'--read-channel',state,data=b'p slice total(negative,-6@token)\n'))
        assert check['ok'] and check['payload']['proofs']['results'][0]['status']=='POSITIVE'
        assert 'supplied' in json.dumps(check)
        assert 'withdrawn supplied' in issue(actor,':withdraw supplied')
        assert 'UNKNOWN' in issue(actor,'total(negative,-6@token)')
print('PASS: real CLIR-6 observed rational conversion, authored source/profile parity, signed rounding and dependency proof, no reverse inference, exact receipt recovery after SIGKILL, and actual PCGM evidence lifecycle.')
