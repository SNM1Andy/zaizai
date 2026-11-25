from ctypes import CDLL, c_uint32
from hashlib import sha256
from pathlib import Path
from shutil import copy2, rmtree
from tempfile import TemporaryDirectory
import re, subprocess
root=Path(__file__).resolve().parent
cl=root/'cl'
def pin(p):return sha256(p.read_bytes()).hexdigest()
def put(p,s):p.write_bytes(s if isinstance(s,bytes) else s.encode());return p
def run(tool,*args,text_in=None,env=None,cwd=None):
    p=subprocess.run([tool,*args],input=text_in,capture_output=True,timeout=25,env=env,cwd=cwd)
    assert not p.returncode,(p.args,p.returncode,p.stderr)
    return p.stdout
full=CDLL(str(root/'libcl_runtime.so'))
full.cl_runtime_features_v1.restype=c_uint32
assert full.cl_runtime_features_v1()==127
full_defs=run('nm','-D','--defined-only',root/'libcl_runtime.so').decode()
memory_defs=run('nm','-D','--defined-only',root/'libcl_memory.so').decode()
for symbol in ('cl_evidence_session_open_v1','cl_evidence_audit_open_v1'):
    assert symbol in full_defs and symbol not in memory_defs
for symbol in ('cl_runtime_features_v1','cl_workspace_pack_v1','cl_package_profile_v1','cl_evidence_freeze_v1','cl_evidence_integrity_v1','cl_profile_rebuild_v1','cl_profile_rebuild_audit_v1','cl_workspace_prepare_v1','cl_prepared_workspace_proof_v1','cl_prepared_workspace_close_v1'):
    assert symbol in memory_defs
undefined=run('nm','-D','--undefined-only',root/'libcl_memory.so').decode()
assert not re.search(r'\b(?:flock|openat|unlinkat|renameat|fsync|getrandom|fstatat|linkat)(?:@|\s|$)',undefined)
deps=run('c++','-std=c++20','-DCL_NATIVE_LIBRARY','-DCL_PORTABLE_MEMORY_CORE','-MM','cl-src/cl.cpp',cwd=root)
assert b'native-os.hpp' not in deps
with TemporaryDirectory(prefix='CL genuine memory SDK without file lease ') as tmp:
    d=Path(tmp);pub=d/'publisher';pub.mkdir()
    s=put(pub/'bank.cl','''module bank.
: record(sym).
: valid(sym).
valid($x) <- record($x).
''')
    lock=put(pub/'locked',run(cl,'lock',s));api=put(pub/'public',run(cl,'project-api',s,lock))
    pkg=put(d/'package',run(cl,'project-pack',s,lock,api))
    goal=put(d/'goal','valid(one)\n')
    baseline=put(d/'old',run(cl,'package-prove',pkg,pin(pkg),goal))
    report=put(d/'profile',run(cl,'package-profile',pkg,pin(pkg),goal))
    session=pub/'journal'
    run(cl,'evidence-init',pkg,pin(pkg),goal,session,text_in=b'a batch one 0 ; observe hit record(one)\n')
    journal=put(d/'incoming',session.read_bytes())
    seal=put(d/'artifact',run(cl,'evidence-freeze',pkg,pin(pkg),goal,journal,pin(journal)))
    proof=put(d/'verified',run(cl,'evidence-frozen-verify',seal,pin(seal),pin(pkg),pin(journal)))
    rmtree(pub)
    sdk=d/'relocated';sdk.mkdir()
    allow=('cl-memory-sdk-check','libcl_memory.so')
    for name in allow:copy2(root/name,sdk/name)
    assert not run(sdk/'cl-memory-sdk-check',pkg,pin(pkg),goal,baseline,journal,pin(journal),seal,pin(seal),
                   proof,report,env={'PATH':'','LC_ALL':'C'},cwd=sdk)
    assert set(x.name for x in sdk.iterdir())==set(allow)
print('PASS: separate buffer-only native CL SDK excludes platform file adapters and their direct linked calls, exact proof/format bytes match full CLI, and an isolated C program freezes and verifies a real journal from memory.')
