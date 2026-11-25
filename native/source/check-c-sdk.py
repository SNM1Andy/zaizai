from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent
def h(data): return sha256(data).hexdigest()
def run(args, cwd=None, **env):
    return subprocess.check_output(args, cwd=cwd, env=dict(PATH='', LC_ALL='C', **env), timeout=20)

with TemporaryDirectory(prefix='CL C SDK independent relocated app ') as td:
    install = Path(td)/'application'
    install.mkdir()
    for name in ('libcl_runtime.so','cl-c-sdk-check'):
        shutil.copy2(root/name, install/name)
    profile = root/'profiles'/'standard.clcp'
    source = root/'fixtures'/'arithmetic.cl'
    pkg = root/'fixtures'/'pilot.clpkg'
    tool = root/'cl'
    for file, key in [(profile,'profile'),(source,'source'),(pkg,'package')]:
        shutil.copyfile(file,install/key)
    goals=install/'queries';goals.write_bytes(b'feasible(test_b)\nfeasible(missing)\n')
    pin=h(pkg.read_bytes());profile_pin=h(profile.read_bytes());source_pin=h(source.read_bytes())
    (install/'expected-ir').write_bytes(run([tool,'package-ir',pkg]))
    (install/'proof').write_bytes(run([tool,'package-prove',pkg,pin,goals]))
    args=[install/'cl-c-sdk-check','package',pin,'expected-ir','queries','proof','profile',profile_pin,'source',source_pin]
    expected=run([tool,'profile-build',profile,profile_pin,source])
    actual=run(args,install,CL_SDK_CAPTURE='1')
    assert actual==expected, (actual[:80],expected[:80])
    assert not (install/'cl').exists() and not (install/'pcgm-alpha').exists()
print('PASS: independent native C app exercises four concurrent in-process CL proof calls, validates wrong pins, and matches exact CLI profile/IR/proof bytes without a CLI at runtime.')
