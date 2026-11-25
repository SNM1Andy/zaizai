from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import json, subprocess, time

root=Path(__file__).resolve().parent
cl=root/'cl'
def run(*args,ok=True):
    r=subprocess.run(args,capture_output=True,timeout=12)
    assert (r.returncode==0)==ok,r
    return r.stdout if ok else r.stderr
@contextmanager
def process(*argv):
    with subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try: yield p
        finally:
            if p.poll() is None: p.kill(); p.wait(timeout=5)
def send(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
    raw=p.stdout.readline()
    assert raw,(s,p.poll())
    return raw,json.loads(raw)
def write(p,s):
    _,r=send(p,'writer '+s)
    assert r['ok'],r
    return r['payload']
def ledger(path):
    return path.read_text().splitlines()[3:]
def wait_written(path,p):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if path.exists():return
        assert p.poll() is None,(p.returncode,p.stderr.read())
        time.sleep(.01)
    raise AssertionError('consumer did not commit its local checkpoint')

with TemporaryDirectory(prefix='cl independent durable consumer ') as tmp:
    d=Path(tmp)
    portable=d/'native relocated'
    portable.mkdir()
    for name in ('cl-audit-consumer','libcl_runtime.so'): copy2(root/name,portable/name)
    source=d/'source.cl'
    source.write_text('module signal.\n: sample(sym).\n: accepted(sym).\naccepted($x) <- sample($x).\n')
    lock=d/'lock';lock.write_bytes(run(cl,'lock',source))
    api=d/'api';api.write_bytes(run(cl,'project-api',source,lock))
    package=d/'package';package.write_bytes(run(cl,'project-pack',source,lock,api))
    pin=sha256(package.read_bytes()).hexdigest()
    goals=d/'goals';goals.write_text('accepted(one)\naccepted(two)\n')
    j=d/'primary'; jargs=(package,pin,goals,j); check=d/'checkpoint'; other=d/'independent'
    exe=portable/'cl-audit-consumer'
    call=(exe,*jargs,check,'1')
    with process(cl,'evidence-init',*jargs) as writer,process(cl,'evidence-audit',*jargs) as audit:
        write(writer,'view')
        one=write(writer,'batch zfirst 0 ; observe first sample(one)')
        write(writer,'observe 1 legacy sample(legacy)')
        two=write(writer,'batch asecond 2 ; observe second sample(two)')
        raw_first,expected=send(audit,'app resume latest 0 origin 1')
        assert expected['result']['events']==[one] and expected['result']['more']
        # Hard kill the native SDK process after its ledger+cursor commit and before it returns.
        with process(*call,'hold') as interrupted:
            wait_written(check,interrupted)
            assert b'checkpoint already has a reader' in run(*call,ok=False)
            interrupted.kill(); assert interrupted.wait(timeout=5)<0
            assert interrupted.stdout.read()==''
        assert ledger(check)==['zfirst']
        assert json.loads(run(exe,*jargs,other,'1'))==expected
        assert ledger(other)==['zfirst']
        _,cursor,prefix,*_=check.read_text().splitlines()
        current=send(audit,f'app resume latest {cursor} {prefix} 1')[0]
        assert run(*call).decode()==current
        assert json.loads(current)['result']['events']==[two] and ledger(check)==['zfirst','asecond']
        third=write(writer,'batch third 3 ; withdraw first')
        assert json.loads(run(*call))['result']['events']==[third]
        assert ledger(check)==['zfirst','asecond','third']
        end=j.read_bytes()
        assert b'must not alias' in run(exe,*jargs,j,'1',ok=False)
        assert b'must not alias' in run(exe,*jargs,d/'primary.lock','1',ok=False)
        alias=d/'hardlink';alias.hardlink_to(j)
        assert b'aliases the writer journal' in run(exe,*jargs,alias,'1',ok=False)
        assert j.read_bytes()==end
        assert json.loads(run(*call))['result']['events']==[] and j.read_bytes()==end
        _,cursor,prefix,*_=check.read_text().splitlines()
        assert not send(audit,f'app resume latest {cursor} {"a"*64} 1')[1]['ok']
        writer.kill(); assert writer.wait(timeout=5)<0
    copied=d/'copy'; copied.write_bytes(j.read_bytes())
    assert json.loads(run(exe,package,pin,goals,copied,check,'1'))['result']['events']==[]
    assert not (d/'copy.lock').exists()
    assert not (portable/'cl').exists()
    # Valid alternative history with the correct package/goals and same tip revision.
    fork=d/'fork'; fork_args=(package,pin,goals,fork)
    with process(cl,'evidence-init',*fork_args) as writer:
        write(writer,'view')
        write(writer,'batch different 0 ; observe first sample(one)')
        write(writer,'observe 1 legacy sample(legacy)')
        write(writer,'batch asecond 2 ; observe second sample(two)')
        write(writer,'batch third 3 ; withdraw first')
        saved=check.read_bytes()
        assert b'acknowledged receipt prefix differs' in run(exe,*fork_args,check,'1',ok=False)
        assert check.read_bytes()==saved
    assert raw_first.endswith('\n')
print('PASS: detached native SDK reader commits its local receipt ledger+cursor atomically, resumes after SIGKILL without duplicates, matches CLI feed bytes, rejects divergent acknowledged history, and never leases or modifies the writer journal.')
