from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copy2, rmtree
import json, re, struct, subprocess, time

root=Path(__file__).resolve().parent
cl,alpha,beta=root/'cl',root/'pcgm-alpha',root/'pcgm-beta'
def h(b):return sha256(b).hexdigest()
def pin(p):return h(p.read_bytes())
def call(*args,code=0,error=b''):
    p=subprocess.run(args,input=b'',capture_output=True,timeout=20)
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout[:200])
    if error:assert error in p.stderr and not p.stdout,p
    return p.stdout
@contextmanager
def live(exe,*args):
    with subprocess.Popen([exe,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def ask(actor,s):
    actor.stdin.write(s+'\n');actor.stdin.flush()
    row=actor.stdout.readline().strip()
    assert row,(s,actor.poll())
    return row
def wait_result(actor,job):
    deadline=time.monotonic()+10
    while True:
        p=json.loads(ask(actor,':choice_job_collect '+job))
        if p['phase']=='ready':return p
        assert time.monotonic()<deadline,p
        time.sleep(.001)
def write(path,bytes):path.write_bytes(bytes);return path
def cells(raw):
    marker,digest,body=raw.split(b'\n',2)
    assert marker==b'PCGMC-1' and h(body).encode()==digest
    out=[];at=0
    while at<len(body):
        size=struct.unpack_from('>I',body,at)[0];at+=4
        out.append(body[at:at+size]);at+=size
    assert len(out)==4 and at==len(body)
    return out
def encode(parts):
    body=b''.join(struct.pack('>I',len(p))+p for p in parts)
    return b'PCGMC-1\n'+h(body).encode()+b'\n'+body

with TemporaryDirectory(prefix='portable native choice audit ') as temp:
    d=Path(temp); origin=d/'origin'; origin.mkdir()
    imports=origin/'imports';imports.mkdir()
    generator=origin/'generator.cl'
    def image(amount):
        generator.write_text((root/'fixtures/generator.cl').read_text().replace('10000',str(amount)))
        base=root/'fixtures/base.cl'
        return call(cl,'generate-ir',generator,base,pin(base),root/'fixtures/bounded.scope')
    a,b=image(10000),image(12000)
    assert h(a)!=h(b)
    src=origin/'seed.cl'
    src.write_text('''& retained stable(ok).
| hard positive stable(ok).
| wish positive artifact_budget__affordable(beta).
''')
    state=origin/'state'
    native=imports/'budget.clir'
    native.write_bytes(a)
    with live(alpha,'--init-managed',src,state) as writer:
        who=re.search(r'individual=(\w+)',writer.stdout.readline())[1]
        assert ask(writer,':install_ir budget '+h(a)).startswith('artifact_installed')
        native.write_bytes(b)
        assert ask(writer,':replace_ir budget '+h(a)+' '+h(b)+' '+pin(state)).startswith('artifact_switched')
        native.unlink()
        assert ask(writer,':replace_ir budget '+h(b)+' '+h(a)+' '+pin(state)).startswith('artifact_switched')
        first=json.loads(ask(writer,':choice_job_start'));wait_result(writer,first['id'])
        original=ask(writer,':choice_job_commit_explained '+first['id']).encode()
        data=json.loads(original)
        assert data['status']=='committed' and data['options'][data['selected']]['target']=='budget:'+h(b),data
        exact=pin(state)
        raw=call(alpha,'--export-choice-capsule',state,first['id'],exact)
        assert raw==call(beta,'--export-choice-capsule',state,first['id'],exact) and pin(state)==exact
        call(alpha,'--export-choice-capsule',state,first['id'],'0'*64,code=1,error=b'head digest mismatch')
        call(alpha,'--export-choice-capsule',state,'d'+'0'*32,exact,code=1,error=b'retained explained outcome')
        capsule_pin, basis_pin, receipt_pin=h(raw),first['basis_sha256'],h(original)
        parts=cells(raw)
        assert parts[0]==first['id'].encode() and h(parts[2])==basis_pin and parts[3]==original
        writer.kill();assert writer.wait(timeout=5)<0
    rmtree(origin)
    isolated=d/'isolated';isolated.mkdir()
    tool=copy2(beta,isolated/'audit')
    capsule=write(isolated/'payload',raw)
    operation=(tool,'--verify-choice-capsule',capsule,capsule_pin,basis_pin,receipt_pin)
    result=json.loads(call(*operation))
    assert result['committable'] is False and result['status']=='verified' and result['decision']==data
    assert result['individual']==who and result['basis_sha256']==basis_pin and result['receipt_sha256']==receipt_pin
    assert {p.name for p in isolated.iterdir()}=={'audit','payload'}
    call(*operation[:-1],'0'*64,code=1,error=b'receipt pin mismatch')
    call(*operation[:-2],'0'*64,receipt_pin,code=1,error=b'basis pin mismatch')
    call(*operation[:-3],'0'*64,basis_pin,receipt_pin,code=1,error=b'external digest mismatch')
    mutable=bytearray(raw);mutable[-1]=ord('x')
    wrong=write(d/'corrupt',mutable)
    call(tool,'--verify-choice-capsule',wrong,pin(wrong),basis_pin,receipt_pin,code=1,error=b'body digest mismatch')
    forged=parts[:];forged[3]=original.replace(b'"committed"',b'"recommended"',1)
    tamper=write(d/'forged',encode(forged))
    call(tool,'--verify-choice-capsule',tamper,pin(tamper),basis_pin,h(forged[3]),code=1,error=b'differs from independent native replay')
    forged=parts[:];forged[1]=b'unchanged'
    tamper=write(d/'wrong_kind',encode(forged))
    call(tool,'--verify-choice-capsule',tamper,pin(tamper),basis_pin,receipt_pin,code=1,error=b'outcome kind differs')
    copy=write(d/'not-state',raw)
    p=subprocess.run([tool,'--inspect',copy],capture_output=True,timeout=10)
    assert p.returncode!=0 and not p.stdout
    assert {p.name for p in isolated.iterdir()}=={'audit','payload'}
print('PASS: exact retained-artifact PCGM choice exports once, detached read-only binary recomputes the entire receipt without original files or any writes, refuses repinned forgery, and the capsule cannot open as state.')
