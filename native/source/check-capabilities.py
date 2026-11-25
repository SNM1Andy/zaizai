from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import subprocess

root=Path(__file__).resolve().parent
with TemporaryDirectory(prefix='CL detached discovery ') as td:
    isolated=Path(td)/'cl'
    shutil.copy2(root/'cl',isolated)
    def use(*args):
        return subprocess.check_output([isolated,*args],cwd=td,env={'PATH':'','LC_ALL':'C'},timeout=15)
    assert b'cl capabilities' in use('--help')
    manifest=json.loads(use('capabilities'))
    assert manifest['release']=='0.157' and manifest['pcgm_required'] is False and manifest['evaluation_backend']=='cpu'
    assert manifest['c_abi']==1 and len(manifest['formats'])==8 and 'CLIR-8' in manifest['formats'] and 'CLIR-6' in manifest['formats']
    assert manifest['c_workspace_build'] is True and manifest['c_prepared_workspace'] is True
    commands={x['command']:x['arguments'] for x in manifest['commands']}
    assert len(commands)==len(manifest['commands']) and 'evidence-freeze' in commands and 'evidence-frozen-verify' in commands and 'workspace-prove' in commands and 'package-compare' in commands and 'workspace-resolve' in commands and 'workspace-branch-additive' in commands and 'package-profile' in commands
    workspace=Path(td)/'sample'
    use('init',workspace)
    lock=use('lock',workspace/'main.cl')
    assert lock
    assert not (Path(td)/'pcgm-alpha').exists()
print('PASS: detached independent CL advertises its tested CPU capabilities and creates a native source workspace before any PCGM utilities are installed.')
