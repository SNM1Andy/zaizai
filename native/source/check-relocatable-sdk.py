from contextlib import contextmanager
from ctypes import CDLL, c_uint32
from hashlib import sha256
from pathlib import Path
from shutil import rmtree, which
from tempfile import TemporaryDirectory
import json, os, re, shlex, subprocess, sys
root=Path(__file__).resolve().parent
stage=root/'distribution/stage-runtime.py'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def put(p,b):p.write_bytes(b);return p
def call(*args,env=None,code=0,error=b'',data=None):
    p=subprocess.run(args,env=env,input=data,capture_output=True,timeout=30)
    assert p.returncode==code,(p.args,p.returncode,p.stderr,p.stdout)
    if error:assert error in p.stderr,p
    return p.stdout
@contextmanager
def live(*args):
    with subprocess.Popen(args,env={'PATH':'','LC_ALL':'C'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def ask(p,s):
    p.stdin.write(s+'\n');p.stdin.flush();row=p.stdout.readline()
    assert row,(s,p.poll())
    return row
def key(line,n):return re.search(fr'{n}=([a-z0-9]+)',line)[1]
def verify(prefix,wanted,code=0,error=b''):
    return call(sys.executable,stage,'verify',prefix,wanted,code=code,error=error)
with TemporaryDirectory(prefix='CL self-contained native redistribution ') as tmp:
    d=Path(tmp);source=d/'source';source.mkdir()
    original=d/'before move';original.mkdir();release=original/'Runtime SDK'
    put(source/'module.cl',b'''module parcel.
: quote(sym,sym,i64,i64).
: out(qty(token)).
& sample quote(cny_cent,token,3,2).
& reverse quote(token,cny_cent,2,3).
out($v) <- qty_convert_ceil(quote,-5@cny_cent,token,$v).
''')
    want=call(sys.executable,stage,'stage',release).decode().strip()
    assert re.fullmatch(r'[a-f0-9]{64}',want)
    assert pin(release/'MANIFEST.sha256.json')==want
    verify(release,want)
    call(sys.executable,stage,'stage',release,code=1,error=b'File exists')
    archive=os.environ.get('CL_RELEASE_TAR')
    if archive:
        assert pin(Path(archive))==os.environ['CL_RELEASE_TAR_SHA256']
        rmtree(release)
        release.mkdir()
        call(which('tar'),'-xzf',archive,'--strip-components=1','-C',release)
        want=os.environ['CL_RELEASE_MANIFEST_SHA256']
        assert pin(release/'MANIFEST.sha256.json')==want
        verify(release,want)

    pkg_env={**os.environ,'PKG_CONFIG_PATH':'','PKG_CONFIG_LIBDIR':str(release/'lib/pkgconfig')}
    flags=call(which('pkg-config'),'--cflags','--libs','CLRuntime',env=pkg_env).decode()
    assert str(release) in ' '.join(shlex.split(flags))
    check=root/'cl-unit-conversion-sdk-check.c'
    applications=original/'apps';applications.mkdir()
    exe=applications/'direct-check'
    call(which('cc'),'-std=c11','-Wall','-Wextra','-Werror',check,'-o',exe,*shlex.split(flags),
         '-Wl,-rpath,$ORIGIN/../Runtime SDK/lib')
    before=release/'bin/cl'
    deps=source/'deps';deps.mkdir()
    for name in ('supply','guard'):
        src=put(deps/(name+'.cl'),f'module {name}.\nexport permitted.\n: permitted(sym).\n& ready permitted(now).\n'.encode())
        lock=put(src.with_suffix('.lock'),call(before,'lock',src))
        api=put(src.with_suffix('.api'),call(before,'project-api',src,lock))
        put(src.with_suffix('.clpkg'),call(before,'project-pack',src,lock,api))
    workspace=(source/'module.cl').read_bytes().replace(b'module parcel.\n',b'module parcel.\nuse supply.\nuse guard.\n')
    app=put(deps/'app.cl',workspace)
    lock=put(deps/'workspace.lock',('CLWORK-1\n'+''.join(f'{m} {m}.clpkg {pin(deps/(m+".clpkg"))} -\n' for m in ('guard','supply'))).encode())
    locked=pin(lock)
    archive=put(d/'program.clw',call(before,'workspace-pack',app,lock,locked))
    goals=put(d/'goal',b'out(-7@token)\nout(-8@token)\n')
    proof=put(d/'proof',call(before,'workspace-prove',archive,pin(archive),locked,goals))
    assert [p['status'] for p in json.loads(proof.read_bytes())['results']]==['POSITIVE','UNKNOWN']
    assert not call(exe,archive,pin(archive),locked,goals,proof,env={'PATH':'','LC_ALL':'C'})
    seed=release/'share/cl/fixtures/observed-unit-conversion.cl'
    state=d/'personal generated state'
    with live(release/'bin/pcgm-alpha','--init-managed',seed,state) as p:
        who=key(p.stdout.readline(),'individual')
        assert 'UNKNOWN' in ask(p,'upper(negative,-7@token)')
        assert ask(p,':observe fresh quote(cny_cent,token,3,2)').startswith('observation_version')
        assert 'POSITIVE' in ask(p,'upper(negative,-7@token)')
        p.kill();assert p.wait(timeout=5)<0
    before_move=pin(state)
    rmtree(source)
    target=d/'after move';original.rename(target)
    release=target/'Runtime SDK';after=release/'bin/cl';exe=target/'apps/direct-check'
    fresh={'PATH':'','LC_ALL':'C'}
    verify(release,want)
    assert not original.exists()
    installed_env={**os.environ,'CL_KIT_VALIDATION_ROOT':str(release)}
    prep_proof=call(sys.executable,root/'check-prepared-workspace.py',env=installed_env)
    assert b'six concurrent detached C readers' in prep_proof
    assert call(after,'workspace-prove',archive,pin(archive),locked,goals,env=fresh)==proof.read_bytes()
    assert not call(exe,archive,pin(archive),locked,goals,proof,env=fresh)
    assert json.loads(call(after,'capabilities',env=fresh))['evaluation_backend']=='cpu'
    # The other ABI is independently buildable using only the installed include/pkg-config files.
    manifest_info=json.loads((release/'MANIFEST.sha256.json').read_bytes())
    assert manifest_info['version']=='0.163' and manifest_info['sdk_profiles']=={'CLRuntime':127,'CLMemory':125}
    assert manifest_info['components']=={'cl':'0.157','pcgm':'0.159'}
    assert json.loads(call(after,'capabilities',env=fresh))['release']==manifest_info['components']['cl']
    twins=[release/'bin'/('pcgm-'+endpoint) for endpoint in ('alpha','beta')]
    for engine,endpoint in zip(twins,('alpha','beta')):
        caps=json.loads(call(engine,'--capabilities',env=fresh))
        assert caps['release']==manifest_info['components']['pcgm'] and caps['endpoint']==endpoint
        assert caps['binary_sha256']==pin(engine) and caps['state_opened'] is False
        assert {'observation_batch_audit','choice_attribution'}<=set(caps['features'])
    for sdk_name,library_name in [('CLRuntime','libcl_runtime.so'),('CLMemory','libcl_memory.so')]:
        info=CDLL(str(release/'lib'/library_name))
        info.cl_runtime_features_v1.restype=c_uint32
        assert info.cl_runtime_features_v1()==manifest_info['sdk_profiles'][sdk_name]
    verifier=release/'share/cl/verify-runtime.py'
    assert call(sys.executable,verifier,'verify',release,want,env=fresh).startswith(b'release_verified')
    pkg_env={**os.environ,'PKG_CONFIG_PATH':'','PKG_CONFIG_LIBDIR':str(release/'lib/pkgconfig')}
    assert call(which('pkg-config'),'--modversion','CLMemory','CLRuntime',env=pkg_env)==b'0.157\n0.157\n'
    specs=call(which('pkg-config'),'--cflags','--libs','CLMemory',env=pkg_env).decode()
    assert '-lcl_memory' in specs and '-lcl_runtime' not in specs
    consumer=target/'apps/memory-host'
    call(which('cc'),'-std=c11','-Wall','-Wextra','-Werror',release/'share/cl/examples/evidence-host.c',
         '-o',consumer,*shlex.split(specs),'-Wl,-rpath,$ORIGIN/../Runtime SDK/lib')
    dynamic=call(which('readelf'),'-d',consumer)
    assert b'libcl_memory.so' in dynamic and b'libcl_runtime.so' not in dynamic
    # Reuse the shipped C example and shipped CL stages, with no build-tree paths.
    share=release/'share/cl'
    profile=share/'profiles'/'unicode-forward.clcp'
    baseline=share/'profiles'/'standard.clcp'
    proposed=share/'profiles'/'unicode-standard.clcp'
    smoke=put(d/'profile-smoke.cl',b': ok(sym).\n? ok(check).\nok(check).\n')
    smoke_pin=sha256(call(after,'compile',smoke,env=fresh)).hexdigest()
    query=put(d/'c-unicode-example.cl',': facts(sym).\n& source facts("江浙 # 上海：已核对").\n? facts("江浙 # 上海：已核对").\n'.encode())
    pack=put(d/'packed-forward.clir',call(after,'profile-build',profile,pin(profile),share/'fixtures/unicode-example.cl',env=fresh))
    goals_text=json.loads(call(after,'ir-json',pack,env=fresh))['results']
    assert goals_text[0]['status']=='POSITIVE'
    assert goals_text[0]['goal']['arguments'][0]['value']=='江浙 # 上海：已核对'
    host=target/'apps/profile-rebuild'
    call(which('cc'),'-std=c11','-Wall','-Wextra','-Werror','-pthread',share/'examples/profile-rebuild-host.c',
         '-o',host,*shlex.split(specs),'-Wl,-rpath,$ORIGIN/../Runtime SDK/lib')
    rebuild_parameters=[]
    for f in (baseline,share/'fixtures/unicode-standard-grammar.cl',
              share/'fixtures/numeric-type-checker.cl',share/'fixtures/lowerer.cl',smoke):
        rebuild_parameters += [f,pin(f)]
    rebuild_parameters += [smoke_pin]
    built,receipt=d/'reproduced.clcp',d/'receipt.json'
    assert call(host,'rebuild',*rebuild_parameters,built,receipt,query,pin(query),pin(proposed),env=fresh)==call(after,'compile',query,env=fresh)
    assert built.read_bytes()==proposed.read_bytes() and not json.loads(receipt.read_bytes())['applied']
    assert not call(host,'audit',*rebuild_parameters,built,pin(built),receipt,pin(receipt),env=fresh)
    incl=put(d/'memory.cl',b'module memory.\n: source(sym).\n: known(sym).\nknown($x) <- source($x).\n')
    ml=put(d/'memory.lock',call(after,'lock',incl,env=fresh))
    ma=put(d/'memory.api',call(after,'project-api',incl,ml,env=fresh))
    mp=put(d/'memory.clpkg',call(after,'project-pack',incl,ml,ma,env=fresh))
    mg=put(d/'memory.goal',b'known(sample)\n')
    for f in incl,ml,ma:f.unlink()
    def split_buffers(raw,fields):
        values=[]
        for _ in range(fields):
            n,raw=raw.split(b'\n',1);n=int(n);assert len(raw)>=n
            values.append(raw[:n]);raw=raw[n:]
        assert not raw
        return values
    args=mp,pin(mp),mg
    mstate,=split_buffers(call(consumer,'init',*args,env=fresh),1)
    journal=d/'known.session';init=put(d/'known.prior',mstate)
    command='trial batch inserted 0 ; observe collected source(sample)'
    ms,mreceipt,mproof=split_buffers(call(consumer,'batch',*args,init,pin(init),command,env=fresh),3)
    actual=json.loads(call(after,'evidence-init',*args,journal,env=fresh,data=(command+'\n').encode()))
    assert ms==journal.read_bytes() and json.loads(mreceipt)==actual['payload']
    assert json.loads(mproof)['planes'][0]['results'][0]['status']=='POSITIVE'
    assert mstate==init.read_bytes()
    alpha,beta=release/'bin/pcgm-alpha',release/'bin/pcgm-beta'
    assert pin(state)==before_move
    with live(alpha,'--resume',state) as p:
        assert key(p.stdout.readline(),'individual')==who
        assert 'POSITIVE' in ask(p,'upper(negative,-7@token)')
        ready=call(beta,'--prepare',state,env=fresh).decode()
        swap=ask(p,':handoff beta '+key(ready,'binary_sha256')+' '+key(ready,'snapshot_sha256'))
        assert swap.startswith('handoff_prepared') and p.wait(timeout=10)==0
    with live(beta,'--claim',state,key(swap,'nonce')) as p:
        assert key(p.stdout.readline(),'individual')==who
        assert 'POSITIVE' in ask(p,'upper(negative,-7@token)')
        check=json.loads(call(beta,'--read-channel',state,env=fresh,data=b'v proof upper(negative,-7@token)\n'))
        assert check['ok'] and check['payload']['results'][0]['status']=='POSITIVE'
        p.kill();assert p.wait(timeout=5)<0
    with live(beta,'--resume',state) as p:
        assert key(p.stdout.readline(),'individual')==who
        assert 'POSITIVE' in ask(p,'upper(negative,-7@token)')
        old_head=pin(state)
        batch=f':observation_batch_audited releasecheck {old_head} ; withdraw fresh'
        approved=json.loads(ask(p,batch))
        assert approved['status']=='committed'
        review='q observation_batch_audit releasecheck '+sha256(batch.encode()).hexdigest()+' ; upper(negative,-7@token)\n'
        def audit_batch():
            return json.loads(call(beta,'--read-channel',state,env=fresh,data=review.encode()))['payload']
        audited=audit_batch()
        assert audited['basis_sha256']==old_head and audited['reconstructed_after_sha256']==pin(state)
        assert audited['results'][0]['before']['status']=='POSITIVE'
        assert audited['results'][0]['after']['status']=='UNKNOWN'
        assert ask(p,':restore fresh').startswith('observation_version')
        assert 'POSITIVE' in ask(p,'upper(negative,-7@token)')
        assert audit_batch()==audited
        p.kill();assert p.wait(timeout=5)<0
    assert audit_batch()==audited
    manifest=release/'MANIFEST.sha256.json'
    old=manifest.read_bytes()
    manifest.write_bytes(old+b' ')
    verify(release,want,code=1,error=b'manifest hash or mode mismatch')
    manifest.write_bytes(old)
    header=release/'include/cl-c-api.h';contents=header.read_bytes()
    header.write_bytes(contents[:-1])
    verify(release,want,code=1,error=b'payload bytes do not match')
    header.write_bytes(contents)
    header.chmod(0o600)
    verify(release,want,code=1,error=b'payload mode mismatch')
    header.chmod(0o644)
    shadow=d/'unrelated.h';shadow.write_bytes(contents)
    header.unlink();header.symlink_to(shadow)
    verify(release,want,code=1,error=b'non-regular file')
    header.unlink();header.write_bytes(contents);header.chmod(0o644)
    verify(release,want)
    library=release/'lib/libcl_memory.so'
    displaced=d/'displaced-memory-library'
    library.rename(displaced)
    verify(release,want,code=1,error=b'incomplete release')
    displaced.rename(library)
    put(release/'noise',b'unlisted')
    verify(release,want,code=1,error=b'unexpected or non-regular file')
    (release/'noise').unlink()
    verify(release,want)
print('PASS: relocated actual Linux kit reports separate CL/PCGM identity; installed CL builds concurrent exact proofs through the shipped C headers; native PCGM recovers identity and exact historical observation proof after move, A/B and forced exit; verification refuses altered bytes, modes and symlinks.')
