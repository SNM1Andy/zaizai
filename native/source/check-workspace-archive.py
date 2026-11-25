from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parent
def h(x):return sha256(x).hexdigest()
def run(tool,*args,code=0,error=b'',cwd=None):
    p=subprocess.run([tool,*args],cwd=cwd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=25)
    assert p.returncode==code,(p.args,p.returncode,p.stderr[:1500],p.stdout[:500])
    if error:assert error in p.stderr and not p.stdout,(p.args,p)
    return p.stdout
with TemporaryDirectory(prefix='true CL composition from pinned package files ') as td:
    d=Path(td);release=d/'publisher';release.mkdir()
    recv=d/'receiving host';recv.mkdir()
    publisher=shutil.copy2(root/'cl',release/'tool')
    consumer=shutil.copy2(root/'cl',recv/'tool')
    profile=root/'stages'/'module-scope.clir'
    profile_pin=h(profile.read_bytes())
    def produce(label,claim=101,scoped=False):
        build=release/(label+str(claim));build.mkdir()
        modules=build/'modules';modules.mkdir()
        common=modules/'shared.cl'
        common.write_text(f'''
module shared.
export entries.
: entries(sym,sym,qty(cny_cent)).
& funding entries(budget,first,{claim}@cny_cent).
& spare entries(budget,second,100@cny_cent).
''')
        src=build/(label+'.cl')
        if label=='cost':
            src.write_text("""
module cost.
use shared.
export total.
: total(qty(cny_cent)).
total($amount) <- qty_fold_sum(shared::entries,budget,$amount).
""")
        else:
            src.write_text("""
module grant.
use shared.
export allocation.
: allocation(qty(cny_cent)).
allocation($out) <- qty_fold_sum(shared::entries,budget,$v) & qty_ratio_ceil($v,1,2,$out).
""")
        lock=src.with_suffix('.lock');lock.write_bytes(run(publisher,'lock',src))
        api=src.with_suffix('.clapi');api.write_bytes(run(publisher,'project-api',src,lock))
        result=(run(publisher,'project-scoped-pack',src,lock,api,profile,profile_pin)
                if scoped else run(publisher,'project-pack',src,lock,api))
        assert result.startswith(b'CLPKG-2\n' if scoped else b'CLPKG-1\n')
        return result
    a,b,c=produce('cost',scoped=True),produce('grant'),produce('grant',102)
    shutil.rmtree(release)
    (recv/'cost.clpkg').write_bytes(a)
    (recv/'grant.clpkg').write_bytes(b)
    (recv/'changed.clpkg').write_bytes(c)
    app=recv/'other_entry_name.cl'
    app.write_text("""
module app.
use cost.
use grant.
input trusted.
: trusted(sym).
: invoice(qty(cny_cent)).
: share(qty(cny_cent)).
invoice($amount) <- cost::total($amount) & trusted(yes).
share($amount) <- grant::allocation($amount).
? invoice(201@cny_cent).
? share(101@cny_cent).
""")
    data=recv/'local.cl';data.write_text('& seen trusted(yes).\n')
    lock=recv/'work.lock'
    cost=f'cost cost.clpkg {h(a)} {profile_pin}\n'
    grant=f'grant grant.clpkg {h(b)} -\n'
    def with_lock(*entries):
        lock.write_text('CLWORK-1\n'+''.join(entries))
        return h(lock.read_bytes())
    pin=with_lock(cost,grant)
    image=run(consumer,'workspace-compile',app,lock,pin,data)
    assert image.startswith(b'CLIR-4\n')
    output=d/'proof.clir';output.write_bytes(image)
    result=run(consumer,'ir-run',output)
    assert b'invoice(201@cny_cent) POSITIVE' in result and b'share(101@cny_cent) POSITIVE' in result
    info=json.loads(run(consumer,'workspace-report',app,lock,pin,data))
    assert info['source_units']==4 and info['identical_shared_modules']==1
    assert info['lock_sha256']==pin and info['ir_sha256']==h(image) and info['data_sha256']==h(data.read_bytes())
    assert [x['profile_sha256'] for x in info['libraries']]==[profile_pin,None]
    moved=d/'move';shutil.copytree(recv,moved)
    renamed=moved/'relocated.cl';(moved/app.name).rename(renamed)
    assert run(moved/'tool','workspace-compile',renamed,moved/lock.name,pin,moved/data.name)==image
    assert not list((moved/'modules').glob('*.cl'))
    archive=run(consumer,'workspace-pack',app,lock,pin,data)
    assert archive.startswith(b'CLWPACK-2\n')
    identical=run(moved/'tool','workspace-pack',renamed,moved/lock.name,pin,moved/data.name)
    assert identical==archive
    external=d/'single_artifact_recipient';external.mkdir()
    tool=shutil.copy2(root/'cl',external/'tool')
    release_file=external/'application.clw';release_file.write_bytes(archive)
    def ask(cmd,target,archive_pin,libraries_pin,code=0,error=b''):
        return run(tool,cmd,target,archive_pin,libraries_pin,code=code,error=error,cwd=external)
    if len(sys.argv)>1:
        previous=Path(sys.argv[1]).resolve()
        legacy=run(previous,'workspace-pack',app,lock,pin,data)
        assert legacy.startswith(b'CLWPACK-1\n')
        legacy_file=external/'old_release';legacy_file.write_bytes(legacy)
        expected=run(previous,'workspace-bundle-ir',legacy_file,h(legacy),pin)
        assert ask('workspace-bundle-ir',legacy_file,h(legacy),pin)==expected
        assert expected!=image
        legacy_file.unlink()
    lock_pin=pin
    archive_pin=h(archive)
    assert b'workspace_bundle_ok' in ask('workspace-bundle-verify',release_file,archive_pin,lock_pin)
    assert ask('workspace-bundle-ir',release_file,archive_pin,lock_pin)==image
    assert json.loads(ask('workspace-bundle-report',release_file,archive_pin,lock_pin))==info
    assert set(x.name for x in external.iterdir())=={'tool','application.clw'}
    ask('workspace-bundle-verify',release_file,'0'*64,lock_pin,code=1,error=b'archive does not match')
    ask('workspace-bundle-verify',release_file,archive_pin,'0'*64,code=1,error=b'lock does not match')
    header,_,payload=archive.split(b'\n',2)
    fake=external/'faulty'
    def broken(body,message):
        raw=header+b'\n'+h(body).encode()+b'\n'+body
        fake.write_bytes(raw)
        ask('workspace-bundle-verify',fake,h(raw),lock_pin,code=1,error=message)
    broken(payload[:-64]+b'0'*64,b'audit receipt differs')
    assert payload.count(image)==1
    broken(payload.replace(image,b'X'+image[1:],1),b'IR differs')
    assert payload.count(a)==1
    broken(payload.replace(a,a[:-1]+b'x',1),b'library package digest mismatch')
    standalone=external/'ordinary';standalone.write_bytes(a)
    ask('workspace-bundle-verify',standalone,h(a),lock_pin,code=1,error=b'unsupported or truncated')

    run(consumer,'workspace-compile',app,lock,'0'*64,data,code=1,error=b'lock does not match')
    pin=with_lock(cost,f'grant changed.clpkg {h(c)} -\n')
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'conflicting versions of workspace module shared')
    pin=with_lock(cost)
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'not pin every explicit')
    pin=with_lock(cost.replace(profile_pin,'-'),grant)
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'required CL module policy differs')
    pin=with_lock(cost,grant.replace(h(b),'0'*64))
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'library package digest mismatch')
    pin=with_lock(grant,cost)
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'not canonical')
    pin=with_lock(cost.replace('cost.clpkg','../cost.clpkg'),grant)
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'outside local package')
    (recv/'alias.clpkg').symlink_to(recv/'cost.clpkg')
    pin=with_lock(cost.replace('cost.clpkg','alias.clpkg'),grant)
    run(consumer,'workspace-compile',app,lock,pin,data,code=1,error=b'cannot open pinned workspace package')
print('PASS: standalone native CL publisher and independent consumer build the exact same multi-package archive/IR, reject forged nested library/IR/report despite fresh outer hashes, and verify without source tree or external access.')
