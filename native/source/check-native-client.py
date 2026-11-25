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
import os,fcntl
from concurrent.futures import ThreadPoolExecutor
with TemporaryDirectory(prefix='PCGM real native clients ') as t:
    d=Path(t);seed=d/'seed.cl';state=d/'state';pipes=d/'lanes'
    seed.write_text(': known(sym).\n& anchor known(test).\n')
    def cmd(lane,body,expect=0):
        p=subprocess.run([alpha,'--fifo-query',pipes,str(lane),body],capture_output=True,timeout=10)
        assert p.returncode==expect,(p.args,p.returncode,p.stderr,p.stdout[:100])
        return p
    with live(alpha,'--init',seed,state,wd=d) as p:
        uid=val(p.stdout.readline(),'individual')
        with live(alpha,'--serve-fifo',state,pipes,'4',wd=d) as supervisor:
            assert 'lanes=4' in supervisor.stdout.readline()
            first=json.loads(cmd(1,'status').stdout)
            assert first['payload']['state']['individual']==uid and len(first['id'])==33
            before=state.read_bytes()
            raw=os.open(pipes/'request_1',os.O_WRONLY)
            os.write(raw,b'leftover status\n');os.close(raw)
            correct=json.loads(cmd(1,'proof known(test)').stdout)
            assert correct['id']!='leftover' and correct['payload']['results'][0]['status']=='POSITIVE'
            assert state.read_bytes()==before
            with open(pipes/'lane_1.lock','rb+') as gate:
                fcntl.flock(gate,fcntl.LOCK_EX|fcntl.LOCK_NB)
                assert b'lane is busy' in cmd(1,'status',expect=1).stderr
                assert json.loads(cmd(2,'status').stdout)['ok']
            with ThreadPoolExecutor(max_workers=4) as scheduled:
                running=[scheduled.submit(cmd,lane,'status') for lane in range(1,5)]
                assert len({json.loads(i.result().stdout)['id'] for i in running})==4
            error=json.loads(cmd(1,'observe unknown(test)',expect=2).stdout)
            assert not error['ok'] and 'unknown read operation' in error['error'] and state.read_bytes()==before
            assert not cmd(1,'status\nextra proof known(test)',expect=1).stdout
            assert issue(p,':observe done known(later)').startswith('observation_version')
            assert json.loads(cmd(4,'proof known(later)').stdout)['payload']['results'][0]['status']=='POSITIVE'
            leftover=pipes/'keep';leftover.write_text('not native endpoint ownership')
            supervisor.terminate();assert supervisor.wait(timeout=8)==0
            assert sorted(x.name for x in pipes.iterdir())==['keep']
            assert b'endpoint is absent' in cmd(1,'status',expect=1).stderr
print('PASS: real native FIFO clients use per-lane exclusive leases and return only their own random correlated receipts; sequential and parallel state reads do not stop the writer.')
