from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
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
    first,second=d/'first.clcpt',d/'second.clcpt'
    digest=lambda path:sha256(path.read_bytes()).hexdigest()
    def refusal(pkg,pkg_pin,query,cp,pin_value,reason,*options):
        run=subprocess.run([tool,'package-round-reopen',pkg,pkg_pin,query,cp,pin_value,*options],
                           timeout=10,capture_output=True)
        assert run.returncode==1 and reason in run.stderr and not run.stdout,(run.args,run)
    with live('package-round-checkpoint',package,pin,goals,first) as p:
        assert json.loads(p.stdout.readline())['rounds']==0
        assert 'usable remaining rounds' in issue(p,'checkpoint')[0]['error']
        _=issue(p,'step 19')
        out,_=issue(p,'checkpoint')
        first_sha=out['sha256']
        state19=out['state']
        assert digest(first)==first_sha and state19['rounds']==19
        assert 'already exists' in issue(p,'checkpoint')[0]['error'] and digest(first)==first_sha
        assert issue(p,'step 3')[0]['rounds']==22
        p.kill();assert p.wait(timeout=5)<0
    assert digest(first)==first_sha
    copy=d/'moved';first.rename(copy)
    with live('package-round-recheckpoint',package,pin,goals,copy,first_sha,second) as p:
        assert json.loads(p.stdout.readline())==state19
        assert 'no complete proof' in issue(p,'proof')[0]['error']
        state36,_=issue(p,'step 17')
        assert state36['rounds']==36 and state36['probes']>state19['probes']
        emitted,_=issue(p,'checkpoint')
        second_sha=emitted['sha256']
        assert emitted['state']==state36 and digest(second)==second_sha
        p.kill();assert p.wait(timeout=5)<0
    assert digest(copy)==first_sha and digest(second)==second_sha
    with live('package-round-reopen',package,pin,goals,second,second_sha) as p:
        assert json.loads(p.stdout.readline())==state36
        finish,_=issue(p,'finish')
        assert finish['status']=='complete'
        assert issue(p,'proof')[1]==absolute
    with live('package-round-session',package,pin,goals) as uninterrupted:
        assert json.loads(uninterrupted.stdout.readline())['rounds']==0
        assert issue(uninterrupted,'finish')[0]==finish
        assert issue(uninterrupted,'proof')[1]==absolute
    refusal(package,pin,goals,second,first_sha,b'does not match supplied')
    refusal(package,pin,goals,second,'',b'does not match supplied')
    refusal(package,pin,goals,second,second_sha,b'resource limits mismatch','100')
    lost=d/'changed'
    lost.write_bytes(second.read_bytes()[:-1])
    refusal(package,pin,goals,lost,second_sha,b'does not match supplied')
    refusal(package,pin,goals,lost,digest(lost),b'body checksum mismatch')
    wrong=d/'other_goals';wrong.write_bytes(goals.read_bytes()+b'# changed wire bytes\n')
    refusal(package,pin,wrong,second,second_sha,b'goals mismatch')
    assert digest(copy)==first_sha and digest(second)==second_sha
    assert not list(d.glob('.cl-frontier-*'))
print('PASS: native CL resumes twice after real SIGKILL at exact round, frontier and counters; final receipt matches uninterrupted computation and invalid checkpoints fail.')
