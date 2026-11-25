from pathlib import Path
import ctypes,json,os,shutil,subprocess,sys,tempfile,time
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
import service as s
def main():
    out={}
    cap,peers=n.negotiate();out["capabilities"]=[cap,*peers]
    for dll in ("cl_runtime.dll","cl_memory.dll"):
        lib=ctypes.CDLL(str(n.BIN/dll))
        out[dll]={"abi":lib.cl_abi_version_v1(),"features":lib.cl_runtime_features_v1()}
        assert out[dll]["abi"]==1
    with s.writer():
        owner=n.status()["owner"];standby="beta" if owner=="alpha" else "alpha"
        writer=subprocess.Popen([n.exe(owner),"--resume",n.SAVE],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        pipe=n.STATE/"desktop-verification-endpoint"
        reader=subprocess.Popen([n.exe(owner),"--serve-fifo",n.SAVE,pipe,"2"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            assert n.IDENTITY.encode() in writer.stdout.readline()
            listening=reader.stdout.readline().decode()
            assert n.IDENTITY in listening,listening
            status=json.loads(n.run(n.exe(owner),"--fifo-query",pipe,"1","status"))
            assert status["payload"]["owner"]==owner
            contended=subprocess.run([n.exe(standby),"--resume",n.SAVE],input=b"",capture_output=True)
            assert contended.returncode and "lock" in contended.stderr.decode().lower(),contended.stderr
            ready=n.run(n.exe(standby),"--prepare",n.SAVE).decode()
            fields=dict(n.re.findall(r"(\w+)=([^\s]+)",ready))
            writer.stdin.write((":handoff "+standby+" "+fields["binary_sha256"]+" "+fields["snapshot_sha256"]+"\n").encode());writer.stdin.flush()
            raw=writer.stdout.readline().decode()
            assert raw.startswith("handoff_prepared") and writer.wait(timeout=8)==0
            nonce=n.re.search(r"nonce=([0-9a-f]+)",raw)[1]
            # Leave the standby unclaimed and return the old writer via its persisted handoff receipt.
            n.run(n.exe(owner),"--cancel-handoff",n.SAVE,nonce)
            after=json.loads(n.run(n.exe(owner),"--fifo-query",pipe,"2","status"))["payload"]
            assert after["owner"]==owner and not after["handoff_pending"]
            out["live_ipc"]={"warm_writer_pid":writer.pid,"reader_pid":reader.pid,"read":status,"rejected_writer":
                contended.stderr.decode(),"candidate_ready":ready,"prepared":raw,"restored":after}
        finally:
            for proc in (reader,writer):
                if proc.poll() is None:proc.kill()
                proc.wait(timeout=5)
        original=n.SAVE.read_bytes()
        rest=n.run(n.exe(owner),"--field-selfcheck").decode()
        assert "direction_only" in rest and "initial field_tick=0" in rest and "replayed field_tick=1" in rest
        assert n.SAVE.read_bytes()==original
        with ZipFile(ROOT/"upstream/CL-PCGM-0.159-linux-source.zip") as archive:
            hashes={name:n.sha((ROOT/"source/pcgm-src"/name).read_bytes()) for name in ["field.hpp","field_assets.inc","field_runtime.inc","primordial.hpp"]}
            assert all(v==n.sha(archive.read("pcgm-src/"+k)) for k,v in hashes.items())
        old=json.loads((n.NATIVE/"run/world/joint.json").read_bytes())["data"]
        out["field"]={"binary_solver_replay":rest,"original_bytes_unchanged":True,"code_sha256":hashes,
                      "migrated_switches":old["modules"]["switches"],"legacy_module_names":list(old["modules"])}
    (ROOT/"evidence/native.json").write_text(n.canonical(out),encoding="utf8")
    print("DLL ABI, live named pipes, writer exclusion, interrupted handoff cancellation and same-identity field readback OK")
if __name__=="__main__":main()

