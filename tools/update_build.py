"""Update the inactive identity-preserving PCGM slot, claim it, then refresh the former owner."""
import json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
import native as n
import service
def replace(target,incoming):
    tmp=target.with_suffix(target.suffix+".updating")
    shutil.copyfile(incoming,tmp)
    if n.sha(tmp.read_bytes())!=n.sha(incoming.read_bytes()):raise IOError("复制后校验失败")
    os.replace(tmp,target)
def update(folder):
    with service.writer():
        if n.status()["handoff_pending"]:n.finish_switch()
        old=n.status()["owner"];other="beta" if old=="alpha" else "alpha"
        backup=ROOT/"rollback"/("build-"+str(time.time_ns()))
        backup.mkdir()
        before=n.status()
        records=[]
        for name in ("cl.exe","cl_runtime.dll","cl_memory.dll","pcgm-alpha.exe","pcgm-beta.exe"):
            if not (folder/name).is_file():raise ValueError("缺少 "+name)
            shutil.copy2(n.BIN/name,backup/name)
        for slot in ("alpha","beta"):
            image=folder/n.exe(slot).name
            cap=json.loads(n.run(image,"--capabilities"))
            if cap["endpoint"]!=slot or cap["release"]!="0.159" or cap["binary_sha256"]!=n.sha(image.read_bytes()):
                raise ValueError("更新候选端点、版本或构建摘要不符")
        try:
            replace(n.exe(other),folder/n.exe(other).name)
            records.append(n.switch())
            check=n.status()
            if check["owner"]!=other or check["state"]["individual"]!=n.IDENTITY:raise ValueError("新端点核对失败")
            records.append({"stable_proof":n.execute(":proof_integrity identity_restored(zaizai)")})
            replace(n.exe(old),folder/n.exe(old).name)
            for name in ("cl.exe","cl_runtime.dll","cl_memory.dll"):replace(n.BIN/name,folder/name)
            records.append(n.switch())
        except Exception:
            # Only restore an inactive executable. On uncertain handoff keep both images for reconciliation.
            now=n.status()
            if not now["handoff_pending"] and now["owner"]==old:
                replace(n.exe(other),backup/n.exe(other).name)
            raise
        report=dict(before=before,after=n.status(),records=records,backup=str(backup),
                    hashes={p.name:n.sha(p.read_bytes()) for p in n.BIN.iterdir() if p.suffix in {".dll",".exe"}})
        (ROOT/"evidence/build-handoff.json").write_text(n.canonical(report),encoding="utf8")
        print(before["owner"],"->",other,"->",n.status()["owner"],"|",n.IDENTITY)
if __name__=="__main__":update(Path(sys.argv[1]).resolve(strict=True))

