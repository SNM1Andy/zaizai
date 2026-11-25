from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

cl=Path(__file__).resolve().parent/'cl'
def pin(b):
    return sha256(b).hexdigest()
def call(*args,wants=None,stdin=None):
    r=subprocess.run([cl,*args],input=stdin,capture_output=True,timeout=15)
    if wants:assert r.returncode!=0 and wants.encode() in r.stderr and not r.stdout,r
    else:assert r.returncode==0,r
    return r.stdout
with TemporaryDirectory() as tmp:
    d=Path(tmp); src=d/'rules.cl';lock=d/'lock';api=d/'api';pkg=d/'rules.clpkg';journal=d/'journal';goals=d/'goals'
    src.write_text("""module rules.
: first(sym).
: second(sym).
: result(sym).
result($x) <- first($x).
result($x) <- second($x).
""")
    lock.write_bytes(call('lock',src)); api.write_bytes(call('project-api',src,lock))
    pkg.write_bytes(call('project-pack',src,lock,api)); package=pin(pkg.read_bytes())
    goals.write_text('result(q)\n')
    def change(init,action):
        out=json.loads(call('evidence-init' if init else 'evidence-resume',pkg,package,goals,journal,stdin=('x '+action+'\n').encode()))
        assert out['ok'],out
    def seal(name,kind):
        snapshot=pin(journal.read_bytes())
        artifact=d/(name+'.clef')
        artifact.write_bytes(call('evidence-freeze',pkg,package,goals,journal,snapshot))
        ah=pin(artifact.read_bytes())
        base=call('evidence-frozen-verify',artifact,ah,package,snapshot)
        raw=call('evidence-frozen-integrity',artifact,ah,package,snapshot)
        r=json.loads(raw)
        assert r['artifact_sha256']==ah and r['snapshot_sha256']==snapshot
        assert r['package_sha256']==package and r['goals_sha256']==pin(goals.read_bytes())
        assert r['signed_proof_sha256']==pin(base.removesuffix(b'\n'))
        assert r['results'][0]['positive_status']==kind,raw
        assert json.loads(base)['results'][0]['status']=='POSITIVE'
        assert call('evidence-frozen-verify',artifact,ah,package,snapshot)==base
        assert call('evidence-frozen-integrity',artifact,ah,package,snapshot)==raw
        return (artifact,ah,package,snapshot),r
    change(True,'batch start 0 ; observe p first(q) ; observe n !first(q)')
    disputed,_=seal('disputed','DISPUTED_ANCESTRY')
    change(False,'batch alternate 1 ; observe independent second(q)')
    clean,r=seal('alternate','CLEAN_WITNESS')
    assert 'live_independent' in str(r['results'][0]['positive_witness'])
    change(False,'batch remove 2 ; withdraw independent ; withdraw n')
    ordinary,r=seal('withdrawn','CLEAN_WITNESS')
    assert 'live_p' in str(r['results'][0]['positive_witness'])
    change(False,'batch reappear 3 ; restore n')
    seal('restored','DISPUTED_ANCESTRY')
    call('evidence-frozen-integrity',*disputed,wants=None)
    call('evidence-frozen-integrity',disputed[0],disputed[1],disputed[2],clean[3],wants='snapshot pin mismatch')
    call('evidence-frozen-integrity',disputed[0],'0'*64,disputed[2],disputed[3],wants='artifact pin mismatch')
    # Change bytes inside the conventional embedded proof and recompute both outer hashes.
    frozen=disputed[0].read_bytes()
    outer=frozen.split(b'\n',2)
    payload=outer[2].replace(b'"engine":"cl"',b'"engine":"zz"')
    assert len(payload)==len(outer[2]) and payload!=outer[2]
    tampered=outer[0]+b'\n'+pin(payload).encode()+b'\n'+payload
    fake=d/'fake.clef';fake.write_bytes(tampered)
    call('evidence-frozen-integrity',fake,pin(tampered),disputed[2],disputed[3],wants='differs from independent recomputation')
print('PASS: exact frozen CL snapshot certifies dirty-only and independently clean paths, archived withdrawal/restore and original proof reproducibility; wrong pins and forged receipt refused.')
