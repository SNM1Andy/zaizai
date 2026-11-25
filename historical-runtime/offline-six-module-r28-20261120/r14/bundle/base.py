import hashlib
import json
import os
from pathlib import Path
import re
import sys

PACKAGE = Path(__file__).resolve().parent
LIB = PACKAGE / 'lib'
BASE = Path(sys.base_prefix).resolve()
SITE = BASE / 'Lib/site-packages'
DENIALS = {
    'native-dispatch': ['NO_R13_HOST_GRANT', 'NO_VERIFIED_RESTRICTED_WINDOWS_LAUNCH', 'NO_INDEPENDENT_ACTION_OBSERVER'],
    'outside-read': ['NATIVE_GATE_CLOSED', 'NO_SAME_TOKEN_READ_AND_WRITE_DENIAL_EVIDENCE'],
    'live-translation': ['NO_TRUSTED_TRANSLATOR_TO_NATIVE_ACTION_AND_RECEIPT_BINDING'],
    'cold-recover': ['NO_ADAPTER_FOR_JOINT_STATE_AND_M5_AT_ONE_VERIFIED_GENERATION'],
}

def gate(capability):
    return dict(capability=capability, status='BLOCKED_BEFORE_DISPATCH', reasons=DENIALS[capability],
                executed=False, replay=False, payload=None)

def check(value, reason):
    if not value:
        raise ValueError(reason)

def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    with path.open('x', encoding='utf8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        f.write('\n')

def verified(pin):
    check(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode and not sys.flags.optimize,
          'use -I -S -B')
    check(sha(PACKAGE/'FREEZE.json') == pin, 'FREEZE_SHA256')
    p = read(PACKAGE/'FREEZE.json')
    check(Path(sys.executable).resolve() == Path(p['python']).resolve() and
          sys.version == p['python_version'] and sha(Path(sys.executable)) == p['python_sha256'], 'PYTHON_PIN')
    expected = set(p['files']) | {'FREEZE.json'}
    check({f.relative_to(PACKAGE).as_posix() for f in PACKAGE.rglob('*') if f.is_file()} == expected, 'FILE_SET')
    for rel, h in p['files'].items():
        path = PACKAGE/rel
        check(path.resolve() == path and sha(path) == h, 'PACKAGE_PIN '+rel)
    return p

def output_path(name):
    check(re.fullmatch(r'first|fresh-[a-zA-Z0-9_-]{1,32}', name), 'exclusive fresh run name required')
    path = PACKAGE.parent / name
    check(path == path.resolve(), 'redirected output')
    return path

def session_of(pin):
    from uuid import uuid4
    unique = uuid4().hex
    return dict(identity='TEST-R13-'+unique, freeze_sha256=pin, scope_ref='scope_'+unique,
                run_id=unique, job_id=None, attempt=1)

def constrain(run, writable=None):
    """Application-level guard for fixed offline Python only."""
    def path_ok(raw, writing=False):
        if isinstance(raw, int):
            return
        path = Path(os.path.abspath(raw)).resolve()
        if writing:
            check(writable is not None and path.is_relative_to(writable), 'WRITE_SCOPE '+str(path))
        else:
            check(any(path.is_relative_to(root) for root in (run, PACKAGE, BASE)), 'READ_SCOPE '+str(path))
    def audit(event, args):
        if event.startswith(('socket.', 'subprocess.', 'winreg.', 'os.spawn', 'os.exec',
                             'os.startfile', 'os.posix_spawn')) or event in (
                'os.system','os.chdir','os.link','os.symlink','os.chmod','sqlite3.load_extension'):
            raise PermissionError(event)
        if event == 'open':
            path_ok(args[0], args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        elif event in ('os.listdir', 'os.scandir'):
            path_ok(args[0] or os.getcwd())
        elif event in ('os.mkdir','os.remove','os.rmdir','os.utime'):
            path_ok(args[0], True)
        elif event == 'os.rename':
            for raw in args[:2]:
                path_ok(raw, True)
        elif event == 'sqlite3.connect':
            dbs = [] if writable is None else [writable/s/f'm5-{i}.sqlite' for s in ('amber','teal') for i in (1,2)]
            check(any(os.fspath(args[0]) in (str(p), p.as_uri()+'?mode=rw', p.as_uri()+'?mode=ro') for p in dbs),
                  'DB_SCOPE')
    sys.addaudithook(audit)

def enable_numeric(pins):
    for rel, h in pins['numpy_files'].items():
        check(sha(SITE/rel) == h, 'NUMPY_PIN '+rel)
    from importlib.abc import MetaPathFinder
    class Dependencies(MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            top = fullname.split('.')[0]
            if top == 'numpy' or top in sys.stdlib_module_names or (LIB/top).is_dir() or (LIB/(top+'.py')).is_file():
                return None
            raise ModuleNotFoundError(fullname)
    sys.meta_path.insert(0, Dependencies())
    sys.path.append(str(SITE))
    import numpy
    check(numpy.__version__ == pins['numpy_version'] and Path(numpy.__file__).resolve() == SITE/'numpy/__init__.py',
          'NUMPY_ORIGIN')
    return numpy

def project_origins(pins):
    origins = {}
    for name, mod in list(sys.modules.items()):
        path = getattr(mod,'__file__',None)
        if path and Path(path).is_absolute() and Path(path).is_relative_to(PACKAGE):
            rel = Path(path).relative_to(PACKAGE).as_posix()
            h = sha(Path(path))
            check(pins['files'].get(rel) == h, 'PROJECT_ORIGIN '+name)
            origins[name] = dict(file=rel,sha256=h)
    return origins
