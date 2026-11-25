from concurrent.futures import ThreadPoolExecutor
from ctypes import byref, c_int, c_size_t, c_uint32, c_void_p, CDLL, create_string_buffer, cast, string_at, Structure
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from subprocess import run
from tempfile import TemporaryDirectory
import json
import os

ROOT = Path(__file__).resolve().parent
CL = ROOT / 'cl'
class Slice(Structure):
    _fields_ = [('bytes',c_void_p),('size',c_size_t)]
class Buffer(Structure):
    _fields_ = [('bytes',c_void_p),('size',c_size_t)]

def native(*args, data=None):
    r=run([CL,*args],input=data,capture_output=True,timeout=15)
    assert r.returncode==0,(r.args,r.stdout,r.stderr)
    return r.stdout

def pin(p):
    return sha256(p.read_bytes()).hexdigest()

def bind(lib):
    dll=CDLL(str(lib))
    fn=dll.cl_evidence_integrity_v1
    fn.restype=c_int
    from ctypes import POINTER
    fn.argtypes=[Slice]*4+[POINTER(Buffer)]*2
    dll.cl_free_v1.argtypes=[POINTER(Buffer)]
    dll.cl_free_v1.restype=None
    dll.cl_runtime_features_v1.restype=c_uint32
    assert dll.cl_abi_version_v1()==1 and dll.cl_runtime_features_v1()&64
    return dll

def slices(args):
    backing=[create_string_buffer(a) for a in args]
    return backing,[Slice(cast(b,c_void_p),len(a)) for a,b in zip(args,backing)]

def apply(dll,args,code=0):
    keep, a=slices(args)
    out,err=Buffer(),Buffer()
    try:
        got=dll.cl_evidence_integrity_v1(*a,byref(out),byref(err))
        msg=string_at(err.bytes,err.size) if err.bytes else b''
        assert got==code,(got,code,msg)
        if got:
            assert not out.bytes and not out.size and msg
            return msg
        assert not err.bytes and not err.size and out.bytes and out.size
        return string_at(out.bytes,out.size)
    finally:
        dll.cl_free_v1(byref(out));dll.cl_free_v1(byref(err))
        assert not out.bytes and not err.bytes and len(keep)==4

with TemporaryDirectory(prefix='relocated-frozen-sdk-') as tmp:
    d=Path(tmp); pub=d/'publisher';pub.mkdir()
    host=d/'host';host.mkdir()
    s=pub/'world.cl';s.write_text('''module world.
: disputed(sym).
: alternate(sym).
: target(sym).
target($x) <- disputed($x).
target($x) <- alternate($x).
!target($x) <- !alternate($x).
''')
    lock=pub/'lock';lock.write_bytes(native('lock',s))
    api=pub/'api';api.write_bytes(native('project-api',s,lock))
    p=pub/'pkg';p.write_bytes(native('project-pack',s,lock,api))
    g=pub/'goals';g.write_text('target(point)\n')
    cases=[]
    for i,(ev,status) in enumerate([
        ('observe a disputed(point) ; observe b !disputed(point)','DISPUTED_ANCESTRY'),
        ('observe a disputed(point) ; observe b !disputed(point) ; observe c alternate(point)','CLEAN_WITNESS'),
        ('observe a !alternate(point)','NO_SUPPORT'),
        ('observe a disputed(point) ; observe b !alternate(point)','DIRECT_DISPUTE')]):
        j=pub/f'j-{i}'
        native('evidence-init',p,pin(p),g,j,data=('s batch gather 0 ; '+ev+'\n').encode())
        a=pub/f'artifact-{i}'
        a.write_bytes(native('evidence-freeze',p,pin(p),g,j,pin(j)))
        proof=native('evidence-frozen-integrity',a,pin(a),pin(p),pin(j))
        assert json.loads(proof)['results'][0]['positive_status']==status
        cases.append(((a.read_bytes(),pin(a).encode(),pin(p).encode(),pin(j).encode()),proof))
    for lib in ('libcl_runtime.so','libcl_memory.so'):
        copy2(ROOT/lib,host/lib)
    # The native caller sees only input bytes plus the relocated library paths.
    os.chdir(host)
    for lib in ('libcl_runtime.so','libcl_memory.so'):
        dll=bind(host/lib)
        def test(case):
            args,proof=case
            assert apply(dll,args)==proof
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(test,cases*5))
        args,proof=cases[1]
        for ix in (1,2,3):
            wrong=list(args);wrong[ix]=b'0'*64
            assert b'pin mismatch' in apply(dll,wrong,1)
        oversize=list(args);oversize[0]=b'x'*(5*1024*1024+1)
        assert b'buffer or size' in apply(dll,oversize,2)
        keep,inputs=slices(args)
        out=Buffer()
        assert dll.cl_evidence_integrity_v1(*inputs,byref(out),byref(out))==2
        assert not out.bytes and not out.size
        assert dll.cl_evidence_integrity_v1(*inputs,None,byref(out))==2
        a=create_string_buffer(b'x')
        occupied=Buffer(cast(a,c_void_p),1)
        assert dll.cl_evidence_integrity_v1(*inputs,byref(occupied),None)==2
        assert occupied.size==1 and string_at(occupied.bytes,1)==b'x' and len(keep)==4
    os.chdir(ROOT)
print('PASS: full and memory-only relocated native C ABIs recompute identical frozen integrity, with 40 concurrent verifications and strict pin/buffer refusal; no application-state access.')
