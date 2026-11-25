from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess,json,re
home=Path(__file__).resolve().parent
cl,pcgm=home/'cl',home/'pcgm-alpha'
def h(data):return sha256(data).hexdigest()
def run(exe,*args,data=b'',ok=0,wd=None):
    p=subprocess.run([exe,*args],input=data,cwd=wd,env={'PATH':'','LC_ALL':'C'},capture_output=True,timeout=20)
    assert p.returncode==ok,(p.args,p.returncode,p.stdout[:100],p.stderr[:500])
    return p.stdout
@contextmanager
def live(exe,*args,wd=None):
    p=subprocess.Popen([exe,*args],cwd=wd,env={'PATH':'','LC_ALL':'C'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:yield p
    finally:
        if p.poll() is None:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def issue(p,command):
    p.stdin.write(command+'\n');p.stdin.flush()
    ans=p.stdout.readline().strip();assert ans,(command,p.poll());return ans
alpha,beta=home/'pcgm-alpha',home/'pcgm-beta'
def val(row,key):
    return re.search(fr'(?:^| ){key}=([0-9a-z]+)',row)[1]
import sys
legacy=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else None
with TemporaryDirectory(prefix='PCGM >2MB actual durable events ') as t:
    d=Path(t);seed=d/'seed.cl';state=d/'state'
    seed.write_text((home/'fixtures'/'chain80.cl').read_text()+'\n: marker(sym).\n& control marker(stop).\n')
    def storage(reader):
        data=json.loads(issue(reader,'s storage'));assert data['ok'],data
        return data['payload']
    def explain_turn(p,key):
        reply=issue(p,':chat journal '+key+' why')
        assert reply.startswith('chat_committed'),reply
        p.stdin.write('marker(stop)\n');p.stdin.flush()
        length=0
        for _ in range(600):
            text=p.stdout.readline()
            assert text,'writer closed during actual proof'
            if text.startswith('POSITIVE plus=obs:control'):return length
            length+=len(text)
        raise AssertionError('proof boundary missing')
    with live(alpha,'--init-managed',seed,state,wd=d) as p:
        who=val(p.stdout.readline(),'individual')
        assert issue(p,':chat journal initial focus reach(v0,v80)').startswith('chat_committed')
        assert 'POSITIVE' in p.stdout.readline()
        assert issue(p,':pin beginning').startswith('pin_committed')
        with live(alpha,'--read-channel',state,wd=d) as view:
            assert issue(p,':seal_history '+storage(view)['logical_sha256']).startswith('archive_sealed')
            assert issue(p,':compact_state '+storage(view)['logical_sha256']).startswith('state_representation compact')
            emitted=0
            for i in range(1,245):
                emitted+=explain_turn(p,f'turn{i}')
                if i%20==0:
                    s=storage(view)
                    assert s['representation']=='compact'
                    assert issue(p,':seal_history '+s['logical_sha256']).startswith('archive_sealed')
                    if s['logical_bytes']>2300000:break
            active=storage(view)
            assert active['logical_bytes']>2*1024*1024 and active['physical_bytes']<600000,(i,emitted,active)
            assert active['state']['individual']==who and active['state']['event']>100
            if legacy:
                old=subprocess.run([legacy,'--inspect',state],capture_output=True,timeout=12)
                assert old.returncode==1 and (b'expands' in old.stderr or b'exceeds limit' in old.stderr),old.stderr
            assert issue(p,'marker(stop)').startswith('POSITIVE')
            p.kill();assert p.wait(timeout=5)<0
    with live(alpha,'--resume',state,wd=d) as p:
        assert val(p.stdout.readline(),'individual')==who
        assert issue(p,'reach(v0,v80)').startswith('POSITIVE')
        assert issue(p,':then beginning reach(v0,v80)').endswith('POSITIVE')
    bundle=d/'backup'
    assert b'transfer_exported' in run(alpha,'--export-compact',state,bundle,wd=d)
    destination=d/'recovered'
    assert b'activation=required' in run(alpha,'--restore-copy',bundle,destination,wd=d)
    compare=run(alpha,'--read-channel',destination,wd=d,data=b'q proof reach(v0,v80)\n')
    assert b'"status":"POSITIVE"' in compare and who.encode() in compare
    print(f'Actual dialogue turns={i}; logical={active["logical_bytes"]} bytes; physical={active["physical_bytes"]} bytes; proof characters produced={emitted}')
print('PASS: a real PCGM journal exceeds the old logical memory ceiling, keeps its active compact file bounded, and survives native kill/restart and authenticated-by-hash offline staged transfer.')
