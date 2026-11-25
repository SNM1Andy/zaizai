from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import json
import subprocess

root=Path(__file__).resolve().parent
env={'PATH':'','LC_ALL':'C'}
def h(raw):return sha256(raw).hexdigest()
def call(exe,*args,data=b'',wd=None):
    p=subprocess.run([exe,*args],input=data,capture_output=True,cwd=wd,env=env,timeout=15)
    assert p.returncode==0,(p.args,p.returncode,p.stdout[:300],p.stderr[:800])
    return p.stdout
def unpack(raw,count):
    values=[]
    for _ in range(count):
        n,raw=raw.split(b'\n',1);n=int(n);assert len(raw)>=n
        values.append(raw[:n]);raw=raw[n:]
    assert not raw
    return values
def signs(report):
    return [z['status'] for p in report['planes'] for z in p['results']]
with TemporaryDirectory(prefix='detached CL evidence transitions ') as tmp:
    d=Path(tmp);offline=d/'isolated';offline.mkdir()
    host=offline/'consumer'
    copy2(root/'cl-transition-sdk-check',host)
    copy2(root/'libcl_memory.so',offline/'libcl_memory.so')
    cli=root/'cl'
    source=d/'logic.cl'
    source.write_text('module demo.\n: observation(sym).\n: conclusion(sym).\nconclusion($x) <- observation($x).\n!conclusion($x) <- !observation($x).\n')
    lock=d/'logic.lock';lock.write_bytes(call(cli,'lock',source))
    api=d/'logic.clapi';api.write_bytes(call(cli,'project-api',source,lock))
    pkg=offline/'input.clpkg';pkg.write_bytes(call(cli,'project-pack',source,lock,api))
    for item in source,lock,api:item.unlink()
    goals=offline/'requests';goals.write_bytes(b'conclusion(case0)\n')
    pins=(pkg,h(pkg.read_bytes()),goals)
    initial,=unpack(call(host,'init',*pins,wd=offline),1)
    file_state=d/'journal'
    call(cli,'evidence-init',*pins,file_state)
    assert initial==file_state.read_bytes()
    basis=offline/'prior'
    def run(old,frame,want=None,pin=None,goals_override=None):
        basis.write_bytes(old)
        keep=set(offline.iterdir())
        args=(pkg,pins[1],goals_override or goals,basis,pin if pin is not None else h(old),frame)
        if want:
            message,=unpack(call(host,'reject',*args,wd=offline),1)
            assert want in message,message
        else:
            snap,receipt,proof=unpack(call(host,'batch',*args,wd=offline),3)
        assert basis.read_bytes()==old and set(offline.iterdir())==keep
        if not want:return snap,json.loads(receipt),json.loads(proof)
    first='r batch first 0 ; observe yes observation(case0) ; observe no !observation(case0)'
    nxt,receipt,proof=run(initial,first)
    alternate,alt_receipt,alt_proof=run(initial,'r batch alternate 0 ; observe no !observation(case0)')
    assert alt_receipt['basis_sha256']==receipt['basis_sha256']==h(initial)
    assert alternate!=nxt and signs(alt_proof)==['NEGATIVE']
    run(alternate,first,b'revision is stale')
    row,before=[json.loads(x)['payload'] for x in call(cli,'evidence-resume',*pins,file_state,data=(first+'\nr view\n').encode()).splitlines()]
    assert row==receipt and nxt==file_state.read_bytes()
    assert signs(proof)==['CONFLICT'] and [p['results'] for p in proof['planes']]==[p['results'] for p in before['planes']]
    flip='r batch withdrawal 1 ; withdraw no'
    after,_,visible=run(nxt,flip)
    assert signs(visible)==['POSITIVE']
    replay,again,current=run(after,first)
    assert replay==after and again=={**receipt,'status':'replayed'} and signs(current)==['POSITIVE']
    back,_,conflict=run(after,'r batch restoration 2 ; restore no')
    assert back!=nxt and signs(conflict)==['CONFLICT']
    call(cli,'evidence-resume',*pins,file_state,data=(flip+'\nr batch restoration 2 ; restore no\n').encode())
    assert file_state.read_bytes()==back
    run(initial,flip,b'revision is stale')
    run(after,first.replace('observe yes','observe another'),b'binds different bytes')
    run(after,'r batch malformed 2 ; withdraw yes ; observe bad observation(1)',b'type')
    run(after,'r batch repeat 2 ; withdraw yes ; restore yes',b'repeats a row')
    run(after,first,b'basis SHA-256 mismatch',pin='0'*64)
    wrong=offline/'wrong-goals';wrong.write_bytes(b'conclusion(case1)\n')
    run(after,first,b'goal identity differs',goals_override=wrong)
    run(after[:-1]+b'?',first,b'journal digest mismatch')
    frozen=call(cli,'evidence-freeze',*pins,file_state,h(back))
    assert frozen.startswith(b'CLEF-1\n')
    basis.write_bytes(back)
    native_frozen,=unpack(call(host,'seal',*pins,basis,h(back),'-',wd=offline),1)
    assert native_frozen==frozen
    artifact=offline/'sealed';artifact.write_bytes(native_frozen)
    verified,=unpack(call(host,'verify',*pins,artifact,h(native_frozen),h(back),wd=offline),1)
    assert verified==call(cli,'evidence-frozen-verify',artifact,h(native_frozen),pins[1],h(back))

print('PASS: detached native C host initializes and forks exact CL evidence bytes, reopens with receipt replay, withdraws/restores the negative witness, and independently matches actual durable CLI output with empty partial results on error.')
