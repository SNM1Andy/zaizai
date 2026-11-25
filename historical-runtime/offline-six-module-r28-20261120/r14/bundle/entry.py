"""Public entry for the frozen R13 package. Only 'run' creates a fresh TEST run."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
sys.pycache_prefix = str(root/'.no-bytecode')
sys.path.insert(0,str(root))
from base import (BASE, DENIALS, LIB, PACKAGE, check, constrain, digest, enable_numeric, gate, output_path,
                  project_origins, read, save, session_of, sha, verified)

def utc():
    return datetime.now(timezone.utc).isoformat()

def emit(value):
    print(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False),flush=True)

def call(role, run, pin):
    argv = [sys.executable,'-X','utf8','-I','-S','-B',str(PACKAGE/'entry.py'),role,run.name,pin]
    start = utc()
    out, err = run/(role+'.stdout'), run/(role+'.stderr')
    with out.open('xb') as stdout, err.open('xb') as stderr:
        with subprocess.Popen(argv,cwd=run,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as proc:
            code = proc.wait()
    save(run/(role+'.exit.json'),dict(pid=proc.pid,parent=os.getpid(),argv=argv,started=start,ended=utc(),
                                      exit_code=code,stdout_sha256=sha(out),stderr_sha256=sha(err),
                                      stdout_bytes=out.stat().st_size,stderr_bytes=err.stat().st_size))
    check(code==0 and err.stat().st_size==0, role+' stopped; original streams preserved')
    check(read(out)['pid']==proc.pid,role+' stdout PID mismatch')

def worker(role,run,pin,pins):
    check(Path.cwd().resolve()==run,'private worker requires its run cwd')
    # Workers write through the parent-owned stdout/stderr handles. Only the
    # world worker may also create its own SQLite and joint state in data/.
    constrain(run,writable=run/'data' if role=='world' else None)
    sys.path.insert(0,str(LIB))
    session = read(run/'session.json')
    check(session['freeze_sha256']==pin and session['attempt']==1 and
          session['identity']=='TEST-R13-'+session['run_id'] and session['scope_ref']=='scope_'+session['run_id'],
          'TEST_SESSION_BINDING')
    from offline import exercise,translate
    if role=='language':
        result = translate(session)
        check('al01.integrated' not in sys.modules and 'al01.folder_broker' not in sys.modules and
              'numpy' not in sys.modules, 'translator isolation')
    else:
        exit_record = read(run/'language.exit.json')
        check(exit_record['exit_code']==0 and sha(run/'language.stdout')==exit_record['stdout_sha256'],
              'unconfirmed translation process')
        doc = read(run/'language.stdout')
        check(doc['pid']==exit_record['pid'] and doc['freeze_sha256']==pin and doc['role']=='language','LANGUAGE_ORIGIN')
        np = enable_numeric(pins)
        result = exercise(run,session,doc['result'],np,pins['expected'])
    emit(dict(pid=os.getpid(),parent=os.getppid(),role=role,freeze_sha256=pin,python=sys.version,
              isolated=sys.flags.isolated,no_site=sys.flags.no_site,no_bytecode=sys.dont_write_bytecode,
              numpy_version=sys.modules['numpy'].__version__ if 'numpy' in sys.modules else None,
              project_modules=project_origins(pins),result=result))

def fresh(run, pin):
    run.mkdir(exist_ok=False)
    save(run/'session.json',session_of(pin))
    (run/'data').mkdir()
    call('language',run,pin)
    call('world',run,pin)
    files = {f.relative_to(run).as_posix():sha(f) for f in sorted(run.rglob('*')) if f.is_file()}
    save(run/'seal.json',dict(freeze_sha256=pin,supervisor_pid=os.getpid(),files=files))
    emit(dict(status='COLLECTED',pid=os.getpid(),run=run.name,freeze_sha256=pin,seal_sha256=sha(run/'seal.json')))

def main():
    args = sys.argv[1:]
    if len(args)==4 and args[0]=='cold-recover':
        gen, pin, anchor_pin = args[1:]
        pins = verified(pin)
        from r14_restore import cold
        check(gen in ('1','2'), 'closed TEST generation required')
        emit(cold(int(gen),pin,pins,anchor_pin))
        return 0
    if len(args)==2 and args[0] in DENIALS:
        verified(args[1])
        emit(gate(args[0]))
        return 3
    if len(args)==2 and args[0]=='check':
        pins=verified(args[1])
        constrain(PACKAGE)
        sys.path.insert(0,str(LIB))
        np=enable_numeric(pins)
        from al01.integrated import IntegratedLife
        from al01.folder_broker import FolderBroker
        from zhcl_r4 import ZhClPipelineR4
        from cli_frozen import Shell
        import original_action
        emit(dict(status='PACKAGE_IMPORT_OK',numpy=np.__version__,modules=project_origins(pins),pid=os.getpid()))
        return 0
    check(len(args) in (3,4),'use check PIN | run NAME PIN | verify NAME PIN SEAL | capability PIN')
    mode,name,pin = args[:3]
    pins = verified(pin)
    run = output_path(name)
    if mode=='verify' and len(args)==4:
        from review import verify
        emit(verify(run,pin,pins,args[3]))
    elif mode=='run' and len(args)==3:
        fresh(run,pin)
    elif mode in ('language','world') and len(args)==3:
        worker(mode,run,pin,pins)
    else:
        raise ValueError('unsupported entry mode')
    return 0

if __name__=='__main__':
    sys.exit(main())
