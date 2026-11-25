"""Run the supplied acceptance programs against the installed Windows images."""
from pathlib import Path
import contextlib,shutil,tempfile,subprocess,sys,os,json
ROOT=Path(__file__).resolve().parents[1]
NAMES=["check-parallel-decisions","check-atomic-evidence-decision","check-frozen-proof-admission",
       "check-authored-module-scope","check-proportional-types","check-unicode-symbols"]
def main():
    summary={}
    images=Path(sys.argv[1]).resolve(strict=True) if len(sys.argv)>1 else ROOT/"bin"
    from windows_sdk_probe import build_probe
    consumer=build_probe()
    with tempfile.TemporaryDirectory(prefix="zaizai-win-verification-") as scratch:
        wd=Path(scratch)
        shutil.copy2(consumer,wd/"cl-unicode-sdk-check.exe")
        shutil.copy2(images/"cl_memory.dll",wd/"cl_memory.dll")
        shutil.copytree(ROOT/"source/fixtures",wd/"fixtures")
        for directory in ("stages","profiles"):
            shutil.copytree(ROOT/"source"/directory,wd/directory)
        for name in ("pcgm-alpha","pcgm-beta","cl"):
            shutil.copyfile(images/(name+".exe"),wd/name)
            shutil.copyfile(images/(name+".exe"),wd/(name+".exe"))
        for name in NAMES:
            source=(ROOT/"source"/(name+".py")).read_text(encoding="utf8")
            # Windows TerminateProcess returns a nonzero exit status instead of -SIGKILL.
            source=source.replace("wait(timeout=5)<0","wait(timeout=5)!=0")
            if name=="check-unicode-symbols":
                source=source.replace("'cl-unicode-sdk-check'","'cl-unicode-sdk-check.exe'").replace("'consumer'","'consumer.exe'").replace("'libcl_memory.so'","'cl_memory.dll'")
            # Keep upstream byte protocols identical on Windows.
            header="from pathlib import Path\n_write=Path.write_text\nPath.write_text=lambda s,d,*a,**k:_write(s,d,*a,**(dict(newline='\\n')|k))\n"
            path=wd/(name+".py");path.write_bytes((header+source).encode())
            try:
                p=subprocess.run([sys.executable,"-X","utf8",path],cwd=wd,capture_output=True,timeout=90,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                info=dict(exit=p.returncode,stdout=p.stdout.decode("utf8","replace"),stderr=p.stderr.decode("utf8","replace")[-3000:])
            except subprocess.TimeoutExpired as exc:info=dict(exit=None,error="timeout")
            summary[name]=info
            (ROOT/"evidence/upstream-windows.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf8")
            print(name,info.get("exit"),info.get("stderr","")[-420:],flush=True)
    if not all(i["exit"]==0 for i in summary.values()):sys.exit(1)
if __name__=="__main__":main()

