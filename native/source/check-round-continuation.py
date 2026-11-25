from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import subprocess
import json

root=Path(__file__).resolve().parent
tool=root/'cl'

def call(*args):
    return subprocess.check_output([tool,*args],timeout=15,env={'PATH':'','LC_ALL':'C'})

@contextmanager
def live(*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,bufsize=1,env={'PATH':'','LC_ALL':'C'}) as p:
        try:yield p
        finally:
            if p.poll() is None:
                p.stdin.close()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)

def issue(p, value):
    p.stdin.write(value+'\n')
    p.stdin.flush()
    reply=p.stdout.readline()
    assert reply,(value,p.poll())
    return json.loads(reply),reply.encode()

with TemporaryDirectory(prefix='live recursive bounded CL sessions ') as tmp:
    d=Path(tmp)
    src=d/'progress.cl'
    flags=['module progress.', ': edge(sym,sym).', ': reachable(sym,sym).',
           'reachable($x,$y) <- edge($x,$y).',
           'reachable($x,$z) <- reachable($x,$y) & edge($y,$z).',
           '!reachable($x,$z) <- reachable($x,$y) & !edge($y,$z).',
           '& blocked !edge(n55,barrier).']
    flags += [f'& segment{i} edge(n{i},n{i+1}).' for i in range(55)]
    src.write_text('\n'.join(flags)+'\n')
    lock=d/'progress.lock';lock.write_bytes(call('lock',src))
    api=d/'progress.clapi';api.write_bytes(call('project-api',src,lock))
    package=d/'progress.clpkg';package.write_bytes(call('project-pack',src,lock,api))
    pin=sha256(package.read_bytes()).hexdigest()
    for file in (src,lock,api):file.unlink()
    goals=d/'goals';goals.write_bytes(b'reachable(n0,n55)\nreachable(n0,barrier)\nreachable(n55,n0)\n')
    absolute=call('package-prove',package,pin,goals)
    assert [x['status'] for x in json.loads(absolute)['results']]==['POSITIVE','NEGATIVE','UNKNOWN']
    def plan(step_sizes):
        with live('package-round-session',package,pin,goals) as p:
            starting=json.loads(p.stdout.readline()); original_pid=p.pid
            assert starting['rounds']==0 and starting['status']=='running'
            blocked,_=issue(p,'proof')
            assert blocked['schema']=='cl-round-error-v1' and 'results' not in blocked
            previous=starting
            for n in step_sizes:
                now,_=issue(p,f'step {n}')
                assert now['rounds']==previous['rounds']+n and now['status']=='running'
                assert now['facts']>previous['facts'] and now['probes']>previous['probes'] and now['indexed']>=previous['indexed']
                assert p.pid==original_pid
                assert issue(p,'status')[0]==now
                previous=now
            finished,_=issue(p,'finish')
            assert finished['status']=='complete'
            assert issue(p,'proof')[1]==absolute
            assert issue(p,'step 33')[0]==finished
            assert issue(p,'proof')[1]==absolute
            return finished
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(plan,[(1,2,3,4),(12,17),(23,)]))
    assert results[0]==results[1]==results[2]
    with live('package-round-session',package,pin,goals,'3') as interrupted:
        start=json.loads(interrupted.stdout.readline())
        assert start['status']=='running'
        fail,_=issue(interrupted,'step 6')
        assert fail['state']['status']=='exhausted' and fail['state']['rounds']==3
        assert 'fixpoint budget' in fail['error']
        assert 'no complete proof' in issue(interrupted,'proof')[0]['error']
        assert issue(interrupted,'abort')[0]['status']=='aborted'
        assert interrupted.wait(timeout=5)==0
    assert call('package-prove',package,pin,goals)==absolute
print('PASS: native CL retains its exact in-process frontier over three pause schedules; all final proofs/counters match, over-budget slices never produce a proof, and an independent complete run matches.')
