from hashlib import sha256
from pathlib import Path
from shutil import copytree, rmtree
from tempfile import TemporaryDirectory
import json, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_bytes(data if isinstance(data,bytes) else data.encode());return p
def run(*args,code=0,error=b''):
    q=subprocess.run([cl,*args],capture_output=True,timeout=25,env={'PATH':'','LC_ALL':'C'})
    assert q.returncode==code,(q.args,q.returncode,q.stderr)
    if error:assert error in q.stderr and not q.stdout,q
    return q.stdout

with TemporaryDirectory(prefix='CL trusted offline release catalog ') as tmp:
    d=Path(tmp); store=d/'local catalog';store.mkdir(); producers=d/'producers';producers.mkdir()
    policy=root/'stages/module-scope.clir'
    scope=pin(policy)
    def release(module,v,amount,policy_pin='-',broken_api=False):
        folder=producers/(module+v);folder.mkdir()
        (folder/'modules').mkdir()
        write(folder/'modules/shared.cl',f'module shared.\nexport price.\n: price(qty(cny_cent)).\n& tagged price({amount}@cny_cent).\n')
        symbol='money' if module=='costs' else 'share'
        if broken_api:symbol='renamed'
        app=write(folder/'main.cl',f'module {module}.\nuse shared.\nexport {symbol}.\n: {symbol}(qty(cny_cent)).\n{symbol}($x) <- shared::price($x).\n')
        lock=write(folder/'lock',run('lock',app))
        api=write(folder/'api',run('project-api',app,lock))
        data=(run('project-scoped-pack',app,lock,api,policy,scope) if policy_pin!='-'
                else run('project-pack',app,lock,api))
        pkg=write(store/(module+v+'.clpkg'),data)
        return (f'{module} {v} {pkg.name} {pin(pkg)} {policy_pin}\n',pkg)
    c1,p1=release('costs','1.0.0',150,scope)
    c2,p2=release('costs','1.10.0',160,scope)
    g1,p3=release('grants','1.0.0',150)
    g2,p4=release('grants','1.1.0',150,broken_api=True)
    rmtree(producers)
    catalog=write(store/'catalog','CLCAT-1\n'+c1+c2+g1+g2)
    requirements=write(store/'requires','CLREQ-1\ncosts 1.0.0 2.0.0 '+scope+'\ngrants 1.0.0 2.0.0 -\n')
    app=write(store/'app.cl','''module app.
use costs.
use grants.
input approved.
: approved(sym).
: total(qty(cny_cent)).
: split(qty(cny_cent)).
total($v) <- costs::money($v) & approved(yes).
split($v) <- grants::share($v).
''')
    data=write(store/'observations.cl','& allowed approved(yes).\n')
    def args(home=store):
        files=(home/app.name,home/requirements.name,home/catalog.name,home/data.name)
        return tuple(value for f in files for value in (f,pin(f)))
    before=set(x.name for x in store.iterdir())
    lock=run('workspace-resolve',*args())
    assert set(x.name for x in store.iterdir())==before
    assert lock==run('workspace-resolve',*args())
    assert lock==('CLWORK-1\ncosts '+p1.name+' '+pin(p1)+' '+scope+'\ngrants '+p3.name+' '+pin(p3)+' -\n').encode(),lock
    single=write(store/'single.cl','module single.\nuse costs.\n: total(qty(cny_cent)).\ntotal($v) <- costs::money($v).\n')
    one=write(store/'single.req','CLREQ-1\ncosts 1.0.0 2.0.0 '+scope+'\n')
    highest=run('workspace-resolve',single,pin(single),one,pin(one),catalog,pin(catalog))
    assert highest==('CLWORK-1\ncosts '+p2.name+' '+pin(p2)+' '+scope+'\n').encode()
    acquired=write(store/'resolved.lock',lock)
    built=write(store/'archive',run('workspace-pack',app,acquired,pin(acquired),data))
    goals=write(store/'goals','total(150@cny_cent)\nsplit(150@cny_cent)\ntotal(160@cny_cent)\n')
    proof=json.loads(run('workspace-prove',built,pin(built),pin(acquired),goals))
    assert [row['status'] for row in proof['results']]==['POSITIVE','POSITIVE','UNKNOWN']
    isolated=d/'detached';copytree(store,isolated)
    assert run('workspace-resolve',*args(isolated))==lock
    wrong=list(args());wrong[-1]='0'*64
    run('workspace-resolve',*wrong,code=1,error=b'data digest mismatch')
    wrong=list(args());wrong[1]='0'*64
    run('workspace-resolve',*wrong,code=1,error=b'app digest mismatch')
    req= requirements.read_text()
    write(requirements,req.replace('1.0.0 2.0.0 '+scope,'1.1.0 2.0.0 '+scope))
    run('workspace-resolve',*args(),code=1,error=b'conflicting embedded module shared')
    write(requirements,req.replace(scope,'0'*64))
    run('workspace-resolve',*args(),code=1,error=b'no CL catalog version meets required interval and scope')
    write(requirements,'CLREQ-1\ncosts 1.0.0 2.0.0 '+scope+'\n')
    run('workspace-resolve',*args(),code=1,error=b'must cover exactly')
    write(requirements,req)
    catalog_text=catalog.read_text()
    write(catalog,catalog_text.replace('costs 1.10.0','costs 01.10.0'))
    run('workspace-resolve',*args(),code=1,error=b'noncanonical CL numeric release version')
    write(catalog,catalog_text)
    body=p2.read_bytes()
    write(p2,body[:-1]+b'?')
    run('workspace-resolve',*args(),code=1,error=b'package digest mismatch')
    write(p2,body)
    moved=p2.with_suffix('.moved');p2.rename(moved);p2.symlink_to(moved)
    run('workspace-resolve',*args(),code=1,error=b'cannot read eligible CL package')
    assert 'producers' not in {x.name for x in d.iterdir()}
print('PASS: pinned local numeric resolver rejects shared-module and missing-API higher choices, selects an exact lock consumed by native CL, repeats after relocation, and fails closed on wrong pins, constraints, scopes and eligible file substitutions.')
