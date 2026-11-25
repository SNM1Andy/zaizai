from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import json, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def put(p,s):p.write_bytes(s if isinstance(s,bytes) else s.encode());return p
def pin(p):return sha256(p.read_bytes()).hexdigest()
def run(exe,*args,code=0,error=b''):
    job=subprocess.run([exe,*args],capture_output=True,timeout=25,env={'PATH':'','LC_ALL':'C'})
    assert job.returncode==code,(job.args,job.returncode,job.stderr)
    if error:assert error in job.stderr and not job.stdout,job
    return job.stdout
with TemporaryDirectory(prefix='CL scoped explicit conversion SDK ') as temp:
    d=Path(temp);source=d/'source';source.mkdir()
    scope=root/'stages/module-scope.clir'
    rates='''module rates.
export raw.
: raw(sym,sym,i64,i64).
& forward raw(cny_cent,token,3,2).
& reverse raw(token,cny_cent,2,3).
'''
    app='''module ledger.
use rates.
: exchanged(qty(token)).
exchanged($out) <- qty_convert_ceil(rates::raw,5@cny_cent,token,$out).
'''
    scope_src=source/'rates.cl';put(scope_src,rates)
    lock=put(source/'rate.lock',run(cl,'lock',scope_src))
    api=put(source/'rate.api',run(cl,'project-api',scope_src,lock))
    native=put(source/'rates.clpkg',run(cl,'project-scoped-pack',scope_src,lock,api,scope,pin(scope)))
    lock=put(source/'workspace.lock',f'CLWORK-1\nrates {native.name} {pin(native)} {pin(scope)}\n')
    app_path=put(source/'app.cl',app)
    locked=pin(lock)
    archive=put(d/'archive',run(cl,'workspace-pack',app_path,lock,locked))
    goals=put(d/'goals','exchanged(8@token)\nexchanged(7@token)\n')
    wanted=put(d/'wanted',run(cl,'workspace-prove',archive,pin(archive),locked,goals))
    report=json.loads(wanted.read_bytes())['results']
    assert [x['status'] for x in report]==['POSITIVE','UNKNOWN']
    assert 'rates__raw' in json.dumps(report) and 'forward' in json.dumps(report)
    (source/'modules').mkdir();(source/'modules/rates.cl').write_text(rates)
    named=put(source/'merger.lock',run(cl,'lock',app_path))
    checked=json.loads(run(cl,'project-scoped-report',app_path,named,scope,pin(scope)))
    assert any((s['symbol'],s['role'],s['permission'])==('raw','fold','ALLOWED') for s in checked['sites'])
    private=source/'modules/rates.cl'
    old=pin(private)
    private.write_text(rates.replace('export raw.\n',''))
    run(cl,'lock',app_path,code=1,error=b'private fold source')
    put(named,named.read_text().replace(old,pin(private)))
    run(cl,'project-scoped-compile',app_path,named,scope,pin(scope),code=1,error=b'private fold source')
    huge_app=put(source/'huge.cl',app.replace('5@cny_cent','9223372036854775807@cny_cent'))
    tiny=put(d/'huge',run(cl,'workspace-pack',huge_app,lock,locked))
    run(cl,'workspace-prove',tiny,pin(tiny),locked,goals,code=1,error=b'signed 64-bit ratio overflow')
    rmtree(source)
    client=d/'native';client.mkdir()
    for name in ('cl-unit-conversion-sdk-check','libcl_runtime.so'):copy2(root/name,client/name)
    assert not run(client/'cl-unit-conversion-sdk-check',archive,pin(archive),locked,goals,wanted)
print('PASS: independent scoped CL workspaces enforce public quote visibility, include exact rate witness, reject signed overflow, and a detached C host verifies byte-identical proof and index limits.')
