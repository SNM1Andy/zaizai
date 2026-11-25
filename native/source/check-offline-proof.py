from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import json
import os
import shutil
import subprocess

root = Path(__file__).resolve().parent

def run(tool, cwd, *argv, expected=0, error=b''):
    result = subprocess.run([tool, *argv], cwd=cwd, env={'PATH': '', 'LC_ALL': 'C'},
                            capture_output=True, timeout=10)
    assert result.returncode == expected, (result.args, result.stderr, result.stdout[:200])
    if expected:
        assert error in result.stderr and not result.stdout, result
    return result.stdout

with TemporaryDirectory(prefix='two independent CL workspaces ') as td:
    home = Path(td)
    sender, recipient = home/'sender', home/'other host'
    sender.mkdir()
    recipient.mkdir()
    sender_bin = shutil.copy2(root/'cl', sender/'compile')
    receiver_bin = shutil.copy2(root/'cl', recipient/'verify')
    project = sender/'original'
    shutil.copytree(root/'fixtures'/'portfolio_units', project)
    commands = [project/'pilot.cl', project/'pilot.lock', project/'pilot.clapi', project/'pilot_data.cl']
    package = run(sender_bin, sender, 'project-pack', *commands)
    pin = sha256(package).hexdigest()
    project.joinpath('pilot_data.cl').write_bytes(
        project.joinpath('pilot_data.cl').read_bytes().replace(b'2000@cny_cent', b'1700@cny_cent'))
    alternate = run(sender_bin, sender, 'project-pack', *commands)
    alternate_pin = sha256(alternate).hexdigest()
    assert alternate_pin != pin
    shutil.rmtree(project)
    goals = b'feasible(test_a)\nfeasible(test_b)\nfeasible(unobserved)\n'
    sender.joinpath('package').write_bytes(package)
    sender.joinpath('goals').write_bytes(goals)
    receipt = run(sender_bin, sender, 'package-prove', 'package', pin, 'goals')
    data = json.loads(receipt)
    assert data['engine'] == 'cl' and data['context']['package_sha256'] == pin
    assert data['context']['goals_sha256'] == sha256(goals).hexdigest()
    assert [x['status'] for x in data['results']] == ['POSITIVE', 'NEGATIVE', 'UNKNOWN'], data
    assert data['results'][0]['positive']['nodes'] and data['results'][1]['negative']['nodes']
    shutil.rmtree(sender)
    for file, value in {'foreign.clpkg': package, 'questions': goals, 'received': receipt, 'other': alternate}.items():
        recipient.joinpath(file).write_bytes(value)
    proof = ('package-proof-check', 'foreign.clpkg', pin, 'questions', 'received')
    assert run(receiver_bin, recipient, *proof).strip().endswith(sha256(receipt).hexdigest().encode())
    assert run(receiver_bin, recipient, 'package-prove', 'foreign.clpkg', pin, 'questions') == receipt
    run(receiver_bin, recipient, 'package-proof-check', 'other', pin, 'questions', 'received',
        expected=1, error=b'does not match supplied SHA-256')
    run(receiver_bin, recipient, 'package-proof-check', 'other', alternate_pin, 'questions', 'received',
        expected=1, error=b'does not match reconstructed proof')
    recipient.joinpath('questions').write_bytes(b'\n'.join(reversed(goals.splitlines())) + b'\n')
    run(receiver_bin, recipient, *proof, expected=1, error=b'reconstructed proof')
    recipient.joinpath('questions').write_bytes(goals + b'# exact bytes matter\n')
    run(receiver_bin, recipient, *proof, expected=1, error=b'reconstructed proof')
    recipient.joinpath('questions').write_bytes(goals)
    recipient.joinpath('received').write_bytes(receipt[:-1])
    run(receiver_bin, recipient, *proof, expected=1, error=b'reconstructed proof')
    recipient.joinpath('received').unlink()
    os.mkfifo(recipient/'received')
    run(receiver_bin, recipient, *proof, expected=1, error=b'must be a regular file')
    recipient.joinpath('received').unlink()
    recipient.joinpath('received').write_bytes(receipt)
    assert run(receiver_bin, recipient, *proof).strip().endswith(sha256(receipt).hexdigest().encode())
    assert not list(recipient.glob('*.cl'))
print('PASS: two native independent CL tools produce and recompute the same exact receipt after source removal; changed package, exchanged receipt, changed goal bytes and truncated receipt all fail.')
