"""Visual Studio build environment for the standalone Windows file-type check."""
from pathlib import Path
import shutil
import subprocess


def env_for_build():
    from build import env
    tools = {name: shutil.which(name, path=env["PATH"]) for name in ("cl.exe", "lib.exe", "dumpbin.exe")}
    if not all(tools.values()):
        raise RuntimeError("The Visual Studio x64 native toolchain is unavailable")
    return env, tools


def run(argv, *, env, cwd):
    return subprocess.run([str(item) for item in argv], env=env, cwd=Path(cwd), check=True,
                          capture_output=True, timeout=180).stdout
