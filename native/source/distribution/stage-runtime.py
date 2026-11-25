#!/usr/bin/env python3
"""Build/verify the native CPU release layout in a new explicit directory."""
from hashlib import sha256
from pathlib import Path
import argparse, json, os, shutil, stat, sys

ROOT=Path(__file__).resolve().parent.parent
MANIFEST='MANIFEST.sha256.json'
MAX_FILE=16*1024*1024
VERSION='0.163'
COMPONENTS={'cl':'0.157','pcgm':'0.159'}
PLATFORM={'os':'linux','machine':'x86_64','backend':'cpu','c_abi':1}
PROFILES={'CLRuntime':127,'CLMemory':125}
SOURCES={
    'bin/cl':('cl',0o755),
    'bin/pcgm-alpha':('pcgm-alpha',0o755),
    'bin/pcgm-beta':('pcgm-beta',0o755),
    'lib/libcl_runtime.so':('libcl_runtime.so',0o644),
    'lib/libcl_memory.so':('libcl_memory.so',0o644),
    'include/cl-memory-api.h':('cl-memory-api.h',0o644),
    'lib/pkgconfig/CLMemory.pc':('distribution/CLMemory.pc',0o644),
    'share/cl/verify-runtime.py':('distribution/stage-runtime.py',0o644),
    'share/cl/examples/evidence-host.c':('cl-transition-sdk-check.c',0o644),
    'share/cl/examples/prepared-workspace-host.c':('cl-prepared-workspace-sdk-check.c',0o644),
    'include/cl-c-api.h':('cl-c-api.h',0o644),
    'lib/pkgconfig/CLRuntime.pc':('distribution/CLRuntime.pc',0o644),
    'share/cl/GETTING-STARTED.zh-CN.md':('GETTING-STARTED.zh-CN.md',0o644),
    'share/cl/README.zh-CN.md':('distribution/README.zh-CN.md',0o644),
    'share/cl/fixtures/observed-unit-conversion.cl':('fixtures/observed-unit-conversion.cl',0o644),
    'share/cl/profiles/observed-unit-conversion.clcp':('profiles/observed-unit-conversion.clcp',0o644),
    'share/cl/examples/profile-rebuild-host.c':('cl-profile-rebuild-sdk-check.c',0o644),
    'share/cl/profiles/standard.clcp':('profiles/standard.clcp',0o644),
    'share/cl/profiles/unicode-standard.clcp':('profiles/unicode-standard.clcp',0o644),
    'share/cl/profiles/unicode-forward.clcp':('profiles/unicode-forward.clcp',0o644),
    'share/cl/profiles/exact-symbol-guards.clcp':('profiles/exact-symbol-guards.clcp',0o644),
    'share/cl/fixtures/symbol-guard-type-checker.cl':('fixtures/symbol-guard-type-checker.cl',0o644),
    'share/cl/fixtures/unicode-standard-grammar.cl':('fixtures/unicode-standard-grammar.cl',0o644),
    'share/cl/fixtures/unicode-forward-grammar.cl':('fixtures/unicode-forward-grammar.cl',0o644),
    'share/cl/fixtures/numeric-type-checker.cl':('fixtures/numeric-type-checker.cl',0o644),
    'share/cl/fixtures/lowerer.cl':('fixtures/lowerer.cl',0o644),
    'share/cl/fixtures/unicode-example.cl':('fixtures/unicode-example.cl',0o644),
}
def require(test,msg):
    if not test:raise ValueError(msg)
def regular(path,limit=MAX_FILE):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        require(stat.S_ISREG(s.st_mode) and s.st_size<=limit,'not a bounded regular release file')
        data=f.read(limit+1)
        require(len(data)==s.st_size and len(data)<=limit,'release file changed while reading')
        return data,stat.S_IMODE(s.st_mode)
def digest(data):return sha256(data).hexdigest()
def render(o):
    return (json.dumps(o,sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n').encode()
def enumerate_prefix(prefix):
    dirs={str(parent) for name in SOURCES for parent in Path(name).parents if str(parent)!='.'}
    files=set(SOURCES)|{MANIFEST}
    actual_files=set(); actual_dirs=set()
    def visit(path):
        with os.scandir(path) as rows:
            for entry in rows:
                name=str(Path(entry.path).relative_to(prefix))
                if entry.is_dir(follow_symlinks=False):
                    require(name in dirs,'unexpected directory: '+name)
                    actual_dirs.add(name);visit(entry.path)
                else:
                    require(entry.is_file(follow_symlinks=False) and name in files,'unexpected or non-regular file: '+name)
                    actual_files.add(name)
    visit(prefix)
    require(actual_files==files and actual_dirs==dirs,'incomplete release contents')
def verify(prefix,expected):
    require(prefix.is_dir() and not prefix.is_symlink(),'release prefix must be a real directory')
    enumerate_prefix(prefix)
    raw,stamp=regular(prefix/MANIFEST,64*1024)
    require(stamp==0o644 and digest(raw)==expected,'release manifest hash or mode mismatch')
    files=[]
    for rel,(_,mode) in sorted(SOURCES.items()):
        data,actual=regular(prefix/rel)
        require(actual==mode,'release payload mode mismatch: '+rel)
        files.append({'path':rel,'mode':mode,'bytes':len(data),'sha256':digest(data)})
    canonical=render({'schema':'cl-native-release-v1','version':VERSION,'components':COMPONENTS,'platform':PLATFORM,'sdk_profiles':PROFILES,'files':files})
    require(canonical==raw,'release payload bytes do not match the manifest')
def stage(prefix):
    require((ROOT/'Makefile').is_file(),'stage from the verified source tree; this extracted copy is a verifier')
    require(prefix.is_absolute() and prefix.name not in ('','..','.'),'explicit absolute non-root release prefix required')
    require(prefix.parent.is_dir(),'release prefix parent does not exist')
    prefix.mkdir(mode=0o755)
    made=True
    try:
        entries=[]
        for rel,(original,mode) in sorted(SOURCES.items()):
            data,_=regular(ROOT/original)
            target=prefix/rel;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:f.write(data)
            target.chmod(mode)
            entries.append({'path':rel,'mode':mode,'bytes':len(data),'sha256':digest(data)})
        raw=render({'schema':'cl-native-release-v1','version':VERSION,'components':COMPONENTS,'platform':PLATFORM,'sdk_profiles':PROFILES,'files':entries})
        path=prefix/MANIFEST
        with path.open('xb') as f:f.write(raw)
        path.chmod(0o644)
        stamp=digest(raw);verify(prefix,stamp)
        print(stamp)
        made=False
    finally:
        if made:shutil.rmtree(prefix)
def main():
    p=argparse.ArgumentParser()
    commands=p.add_subparsers(dest='which',required=True)
    build=commands.add_parser('stage');build.add_argument('prefix',type=Path)
    check=commands.add_parser('verify');check.add_argument('prefix',type=Path);check.add_argument('expected')
    a=p.parse_args()
    try:
        if a.which=='stage':stage(a.prefix)
        else:
            verify(a.prefix,a.expected);print('release_verified '+a.expected)
    except (OSError,ValueError) as e:
        print('release: '+str(e),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
