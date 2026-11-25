"""Reproducible x64 native build using the installed Visual Studio toolchain."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"source"
OBJ=ROOT/"build"
BIN=Path(os.environ.get("ZAIZAI_BUILD_OUT",str(OBJ/"candidate")))
LOG=ROOT/"evidence"/"build"
for folder in (OBJ,BIN,LOG):
    folder.mkdir(exist_ok=True,parents=True)
vswhere=Path(os.environ["ProgramFiles(x86)"])/"Microsoft Visual Studio/Installer/vswhere.exe"
vs=Path(subprocess.check_output([vswhere,"-latest","-products","*","-requires","Microsoft.VisualStudio.Component.VC.Tools.x86.x64","-property","installationPath"],text=True).strip())
setup=vs/"Common7/Tools/VsDevCmd.bat"
raw=subprocess.check_output(f'cmd.exe /d /s /c ""{setup}" -arch=x64 -host_arch=x64 >nul && set"',shell=False)
env=os.environ.copy()
for line in raw.decode("mbcs","replace").splitlines():
    k,sep,v=line.partition("=")
    if k and sep:env[k.upper()]=v
compiler=vs/"VC/Tools/Llvm/x64/bin/clang-cl.exe"
if not compiler.exists():compiler=Path(shutil.which("cl.exe",path=env["PATH"]))
common=[str(compiler),"/nologo","/std:c++20","/EHsc","/utf-8","/O2","/MD","/bigobj","/D_CRT_SECURE_NO_WARNINGS","/DNOMINMAX"]
def run(name,cmd):
    result=subprocess.run(cmd,cwd=OBJ,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (LOG/(name+".txt")).write_bytes((subprocess.list2cmdline(cmd)+"\n").encode()+result.stdout)
    if result.returncode:
        print(name,"failed:",result.stdout.decode("utf8","replace")[-2300:],flush=True)
        raise RuntimeError(name)
    print(name,"OK",flush=True)
jobs={
  "cl":("cl-src/cl.cpp",[]),
  "cl-core":("cl-src/cl.cpp",["/DCL_NATIVE_LIBRARY"]),
  "cl-memory-core":("cl-src/cl.cpp",["/DCL_NATIVE_LIBRARY","/DCL_PORTABLE_MEMORY_CORE"]),
  "runtime-api":("cl-c-api.cpp",["/DCL_BUILD_DLL"]),
  "memory-api":("cl-c-api.cpp",["/DCL_BUILD_DLL","/DCL_PORTABLE_MEMORY_CORE"]),
  "alpha":("pcgm-src/cl.cpp",['/DPCGM_BUILD_NAME="alpha"']),
  "beta":("pcgm-src/cl.cpp",['/DPCGM_BUILD_NAME="beta"'])}
def compile_one(name):
    src,flags=jobs[name]
    run(name,common+flags+["/c",str(SRC/src),"/Fo"+str(OBJ/(name+".obj"))])
if __name__=="__main__":
    names=sys.argv[1:] or list(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(compile_one,names))
    artifacts={"cl.exe":["cl"],"pcgm-alpha.exe":["alpha","cl-core"],"pcgm-beta.exe":["beta","cl-core"],
               "cl_runtime.dll":["runtime-api","cl-core"],"cl_memory.dll":["memory-api","cl-memory-core"]}
    for filename,units in artifacts.items():
        if not all((OBJ/(u+".obj")).exists() for u in units):continue
        out=BIN/filename
        cmd=[str(compiler),"/nologo",*[str(OBJ/(u+".obj")) for u in units],"/Fe"+str(out)]
        if out.suffix==".dll":cmd+=["/LD"]
        cmd+=["/link","/OPT:REF","/OPT:ICF","/MANIFEST:EMBED","/MANIFESTINPUT:"+str(ROOT/"tools/utf8.manifest")]
        run("link-"+filename,cmd)
    (LOG/"hashes.json").write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in BIN.iterdir() if p.is_file()},indent=2))


