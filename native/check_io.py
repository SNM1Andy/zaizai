import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"tools"))
import build_sdk


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    with TemporaryDirectory(prefix="zai-disk-type-") as name:
        td=Path(name)
        env,tools=build_sdk.env_for_build()
        exe=td/"verify.exe"
        build_sdk.run([tools["cl.exe"],"/nologo","/std:c++20","/EHsc","/utf-8","/MD","/O2",
                        "/I"+str(ROOT/"source"),ROOT/"type_probe.cpp","/Fe"+str(exe)],env=env,cwd=td)
        p=subprocess.run([exe,td],cwd=td,capture_output=True,timeout=6,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        report={"passed":True,"stdout":p.stdout.decode().strip(),"probe_source_sha256":sha(ROOT/"type_probe.cpp"),
                "windows_reader_sha256":sha(ROOT/"source/native-os-win.hpp"),"probe_binary":sha(exe),
                "anonymous_pipe_writer_closed_before_test":True}
    (ROOT/"evidence").mkdir(exist_ok=True)
    (ROOT/"evidence/file-types.json").write_text(json.dumps(report,indent=2),encoding="utf8")
    print(report["stdout"])


if __name__=="__main__":main()
