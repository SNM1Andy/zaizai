from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import subprocess

here=Path(__file__).resolve().parent
alpha=here/'pcgm-alpha'
beta=here/'pcgm-beta'
env={'PATH':'','LC_ALL':'C'}
def hash_bytes(data):return sha256(data).hexdigest()
def token(line,key):return re.search(fr'(?:^| ){key}=([a-z0-9]+)',line)[1]
def call(exe,*args,data=b'',code=0):
    done=subprocess.run([exe,*args],env=env,input=data,timeout=20,capture_output=True)
    assert done.returncode==code,(done.args,done.stdout,done.stderr,done.returncode)
    return done.stdout
def start(exe,*args):
    return subprocess.Popen([exe,*args],env=env,text=True,bufsize=1,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def request(p,cmd):
    p.stdin.write(cmd+'\n');p.stdin.flush()
    got=p.stdout.readline().strip()
    assert got,(cmd,p.poll())
    return got
def terminate(p):
    if p.poll() is None:
        p.kill();p.wait(timeout=10)
def view(exe,state):
    return json.loads(call(exe,'--read-channel',state,data=b'r archives\n'))
with TemporaryDirectory(prefix='PCGM anchored immutable assets ') as tmp:
    d=Path(tmp);state=d/'state';seed=d/'seed.cl'
    seed.write_text(': observed(sym).\n: anchor(sym).\n& baseline anchor(active).\n')
    wrong=d/'decoy';wrong.mkdir();marker=wrong/'unchanged'
    marker.write_bytes(b'outside store')
    episode=d/'state.episodes';history=d/'state.history'
    p=start(alpha,'--init-managed',seed,state)
    try:
        actor=token(p.stdout.readline(),'individual')
        prior=state.read_bytes()
        episode.symlink_to(wrong,target_is_directory=True)
        assert 'cannot open secure durable asset folder' in request(p,':pin link')
        assert state.read_bytes()==prior and list(wrong.iterdir())==[marker]
        episode.unlink();episode.mkdir()
        addr=episode/(hash_bytes(prior)+'.snap')
        addr.symlink_to(marker)
        assert 'cannot open the pinned snapshot' in request(p,':pin bad_leaf')
        assert addr.is_symlink() and marker.read_bytes()==b'outside store' and state.read_bytes()==prior
        addr.unlink();addr.write_bytes(b'bad but regular')
        assert 'differs from expected bytes' in request(p,':pin wrong_bytes')
        assert addr.read_bytes()==b'bad but regular' and state.read_bytes()==prior
        addr.write_bytes(prior)
        before=addr.stat().st_ino
        assert request(p,':pin preserved').startswith('pin_committed')
        assert addr.stat().st_ino==before and addr.read_bytes()==prior
        assert request(p,':observe measurement observed(next)').startswith('observation_version')
        head=state.read_bytes()
        history.symlink_to(wrong,target_is_directory=True)
        assert 'cannot open secure durable asset folder' in request(p,':seal_history '+hash_bytes(head))
        assert state.read_bytes()==head and list(wrong.iterdir())==[marker]
        history.unlink()
        sealed=request(p,':seal_history '+hash_bytes(head))
        segment=history/(token(sealed,'sha256')+'.logseg')
        assert segment.is_file() and not list(history.glob('.pcgm-asset-*'))
        assert request(p,':compact_state '+hash_bytes(state.read_bytes())).startswith('state_representation compact')
        head=state.read_bytes()
        archives=view(alpha,state)['payload']
        reader=start(alpha,'--read-channel',state)
        try:
            assert json.loads(request(reader,'r archives'))['payload']==archives
            moved=d/'moved'
            history.rename(moved)
            history.symlink_to(moved,target_is_directory=True)
            refused=json.loads(request(reader,'r archives'))
            assert not refused['ok'] and 'secure durable asset folder' in refused['error'],refused
            invalid=subprocess.run([alpha,'--read-channel',state],input=b'r archives\n',env=env,capture_output=True,timeout=20)
            assert invalid.returncode==1 and b'secure durable asset folder' in invalid.stderr
            assert state.read_bytes()==head
            history.unlink();moved.rename(history)
            assert json.loads(request(reader,'r archives'))['payload']==archives
        finally:terminate(reader)
        ready=call(beta,'--prepare',state).decode()
        hand=request(p,':handoff beta '+token(ready,'binary_sha256')+' '+token(ready,'snapshot_sha256'))
        assert p.wait(timeout=10)==0 and hand.startswith('handoff_prepared'),hand
        q=start(beta,'--claim',state,token(hand,'nonce'))
        try:
            assert token(q.stdout.readline(),'individual')==actor
            assert request(q,'observed(next)').startswith('POSITIVE')
        finally:terminate(q)
        assert view(beta,state)['payload']['segments']==archives['segments']
        out=d/'published'
        assert b'transfer_exported' in call(beta,'--export',state,out)
        assert (out/'episodes'/addr.name).read_bytes()==prior
        assert (out/'history'/segment.name).read_bytes()==segment.read_bytes()
    finally:terminate(p)
print('PASS: real PCGM anchored immutable assets reject links and wrong bytes without moving state, reuse an exact physical snapshot, and support verified compact reopen, A/B, forced exit and export.')
