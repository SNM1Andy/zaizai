from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, shutil, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(data):return sha256(data).hexdigest()
def run(exe,*args,cwd=None,ok=True):
    p=subprocess.run([exe,*args],cwd=cwd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=25)
    assert (p.returncode==0)==ok,(p.args,p.returncode,p.stderr.decode(errors='replace'))
    return p.stdout if ok else p.stderr

with TemporaryDirectory(prefix='independent native workspace SDK ') as temp:
    d=Path(temp); origin=d/'original developer folder';origin.mkdir()
    portable=d/'isolated C runtime';portable.mkdir(); inputs=d/'transported byte buffers';inputs.mkdir()
    for name in ('cl-workspace-sdk-check','libcl_runtime.so'):shutil.copy2(root/name,portable/name)
    (origin/'modules').mkdir()
    (origin/'modules/shared.cl').write_text('module shared.\nexport data.\n: data(qty(cny_cent)).\n& seeded data(200@cny_cent).\n')
    def library(name, result, rule, scoped=False):
        src=origin/(name+'.cl')
        src.write_text(f'module {name}.\nuse shared.\nexport {result}.\n: {result}(qty(cny_cent)).\n{rule}\n')
        lock=src.with_suffix('.lock');lock.write_bytes(run(cl,'lock',src))
        api=src.with_suffix('.api');api.write_bytes(run(cl,'project-api',src,lock))
        stage=root/'stages/module-scope.clir'; stage_pin=pin(stage.read_bytes())
        output=run(cl,'project-scoped-pack',src,lock,api,stage,stage_pin) if scoped else run(cl,'project-pack',src,lock,api)
        pkg=origin/(name+'.clpkg');pkg.write_bytes(output)
        return pkg, (stage_pin if scoped else '-')
    cost,cost_policy=library('costs','cost','cost($v) <- shared::data($v).',True)
    grant,grant_policy=library('grants','grant','grant($v) <- shared::data($raw) & qty_ratio_ceil($raw,1,2,$v).')
    base='''module app.
use costs.
use grants.
export invoice.
input approved.
: invoice(qty(cny_cent)).
: outcome(qty(cny_cent)).
: approved(sym).
invoice($v) <- costs::cost($v) & approved(yes).
outcome($v) <- grants::grant($v).
'''
    app=origin/'app.cl';app.write_text(base)
    lock=origin/'workspace.lock';lock.write_text(
        f'CLWORK-1\ncosts {cost.name} {pin(cost.read_bytes())} {cost_policy}\ngrants {grant.name} {pin(grant.read_bytes())} {grant_policy}\n')
    lock_pin=pin(lock.read_bytes());data=origin/'extra.cl';data.write_text('& cleared approved(yes).\n')
    archive=inputs/'workspace';archive.write_bytes(run(cl,'workspace-pack',app,lock,lock_pin,data))
    archive_pin=pin(archive.read_bytes())
    ir=inputs/'ir';ir.write_bytes(run(cl,'workspace-bundle-ir',archive,archive_pin,lock_pin))
    goals=inputs/'goals'; goals.write_text('invoice(200@cny_cent)\noutcome(100@cny_cent)\n')
    proof=inputs/'proof';proof.write_bytes(run(cl,'workspace-prove',archive,archive_pin,lock_pin,goals))
    assert proof.read_bytes().count(b'"status":"POSITIVE"')==2,proof.read_bytes()
    changed=inputs/'candidate';changed.write_text(base.replace('outcome($v) <- grants::grant($v).',
        'outcome($new) <- grants::grant($v) & qty_ratio_ceil($v,1,2,$new).'))
    forbidden=inputs/'unsafe';forbidden.write_text(base.replace('export invoice.','export outcome.'))
    rebuilt=inputs/'rebuilt';rebuilt.write_bytes(run(cl,'workspace-rebuild',archive,archive_pin,lock_pin,changed,pin(changed.read_bytes())))
    assert rebuilt.read_bytes()!=archive.read_bytes()
    next_goals=inputs/'next-goals';next_goals.write_text('invoice(200@cny_cent)\noutcome(50@cny_cent)\n')
    assert run(cl,'workspace-prove',rebuilt,pin(rebuilt.read_bytes()),lock_pin,next_goals).count(b'"status":"POSITIVE"')==2
    assert b'fact limit' in run(cl,'workspace-prove',archive,archive_pin,lock_pin,goals,'128','1','2000000','2000000',ok=False)
    for f in (app,lock,data,grant,cost):shutil.copy2(f,inputs/f.name)
    shutil.rmtree(origin)
    assert set(p.name for p in portable.iterdir())=={'cl-workspace-sdk-check','libcl_runtime.so'}
    run(portable/'cl-workspace-sdk-check',inputs/app.name,inputs/lock.name,lock_pin,inputs/data.name,archive,archive_pin,
        ir,goals,proof,changed,pin(changed.read_bytes()),rebuilt,forbidden,pin(forbidden.read_bytes()),
        inputs/grant.name,inputs/cost.name,cwd=portable)
    assert set(p.name for p in portable.iterdir())=={'cl-workspace-sdk-check','libcl_runtime.so'}
    memory=d/'isolated buffer-only';memory.mkdir()
    only={'cl-workspace-memory-sdk-check','libcl_memory.so'}
    for name in only:shutil.copy2(root/name,memory/name)
    run(memory/'cl-workspace-memory-sdk-check',inputs/app.name,inputs/lock.name,lock_pin,inputs/data.name,archive,archive_pin,
        ir,goals,proof,changed,pin(changed.read_bytes()),rebuilt,forbidden,pin(forbidden.read_bytes()),
        inputs/grant.name,inputs/cost.name,cwd=memory)
    assert set(p.name for p in memory.iterdir())==only
print('PASS: relocated C host with no CL CLI composes two pinned typed CL dependencies from memory, verifies IR, evaluates grounded proofs, and rebuilds source across four native threads with exact CLI parity and deterministic refusal.')
